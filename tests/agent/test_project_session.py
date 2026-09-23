import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_agent_project.agent.plan_revision import PlanReviewStatus
from ai_agent_project.agent.project_execution import ProjectExecutionStatus
from ai_agent_project.agent.project_session import (
    ProjectModeProposal,
    ProjectPendingActionType,
    ProjectStatus,
)
from ai_agent_project.agent.project_session_application import (
    InMemoryProjectSessionStore,
    ProjectSessionError,
    ProjectSessionService,
    ProjectSessionStateError,
)
from ai_agent_project.agent.project_session_file_store import (
    FileProjectStore,
    ProjectSessionStorageError,
)
from ai_agent_project.agent.research import ResearchStatus, WorkMode
from ai_agent_project.agent.upgrade import ProjectMode


def _call_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return None


class _Proposer:
    def __init__(self) -> None:
        self.calls = 0

    def propose(self, _request: str) -> ProjectModeProposal:
        self.calls += 1
        return ProjectModeProposal(
            proposed_work_mode=WorkMode.HYBRID,
            proposed_project_mode=ProjectMode.UPGRADE,
            rationale="Advisory only.",
        )


def _service(store=None, proposer=None) -> ProjectSessionService:
    return ProjectSessionService(
        store or InMemoryProjectSessionStore(), proposer or _Proposer()
    )


class _Reader:
    def __init__(self, runs: dict[str, object]) -> None:
        self.runs = runs
        self.get_calls: list[str] = []

    def get(self, run_id: str):
        self.get_calls.append(run_id)
        return self.runs.get(run_id)


def _active_service(
    mode: WorkMode,
    *,
    developer_reader: _Reader | None = None,
    research_reader: _Reader | None = None,
) -> tuple[ProjectSessionService, str]:
    service = ProjectSessionService(
        InMemoryProjectSessionStore(),
        _Proposer(),
        developer_reader,  # type: ignore[arg-type]
        research_reader,  # type: ignore[arg-type]
    )
    project_id = service.create_project_request("Request").id
    service.confirm_project_mode(project_id, mode, ProjectMode.NEW)
    return service, project_id


def test_proposal_remains_pending_and_user_confirmation_is_authoritative() -> None:
    proposer = _Proposer()
    service = _service(proposer=proposer)
    created = service.create_project_request("Build a study", title="Study")
    assert created.project.status is ProjectStatus.AWAITING_MODE_CONFIRMATION
    assert created.project.work_mode is None
    assert created.project.project_mode is None
    assert proposer.calls == 1

    confirmed = service.confirm_project_mode(
        created.id, WorkMode.RESEARCHER, ProjectMode.NEW
    )
    assert confirmed.project.status is ProjectStatus.ACTIVE
    assert confirmed.project.work_mode is WorkMode.RESEARCHER
    assert confirmed.project.project_mode is ProjectMode.NEW
    assert confirmed.project.mode_proposal.proposed_work_mode is WorkMode.HYBRID
    assert confirmed.project.mode_proposal.proposed_project_mode is ProjectMode.UPGRADE


@pytest.mark.parametrize(
    ("mode", "developer_allowed", "research_allowed"),
    (
        (WorkMode.DEVELOPER, True, False),
        (WorkMode.RESEARCHER, False, True),
        (WorkMode.HYBRID, True, True),
    ),
)
def test_shallow_binding_respects_confirmed_work_mode(
    mode: WorkMode, developer_allowed: bool, research_allowed: bool
) -> None:
    service = _service()
    created = service.create_project_request("Request")
    service.confirm_project_mode(created.id, mode, ProjectMode.NEW)
    if developer_allowed:
        assert (
            service.bind_developer_run(
                created.id, "developer-run"
            ).project.developer_run_id
            == "developer-run"
        )
    else:
        with pytest.raises(ProjectSessionStateError):
            service.bind_developer_run(created.id, "developer-run")
    if research_allowed:
        assert (
            service.bind_research_run(
                created.id, "research-run"
            ).project.research_run_id
            == "research-run"
        )
    else:
        with pytest.raises(ProjectSessionStateError):
            service.bind_research_run(created.id, "research-run")


def test_lifecycle_resume_and_completion_are_explicit() -> None:
    service = _service()
    created = service.create_project_request("Request")
    assert service.resume_project(created.id).pending_actions[0].action_type is (
        ProjectPendingActionType.CONFIRM_MODE
    )
    with pytest.raises(ProjectSessionStateError):
        service.bind_research_run(created.id, "research-run")
    active = service.confirm_project_mode(
        created.id, WorkMode.HYBRID, ProjectMode.UPGRADE
    )
    assert active.project.status is ProjectStatus.ACTIVE
    assert tuple(
        action.action_type
        for action in service.resume_project(created.id).pending_actions
    ) == (
        ProjectPendingActionType.BIND_DEVELOPER_RUN,
        ProjectPendingActionType.BIND_RESEARCH_RUN,
    )
    completed = service.complete_project(created.id)
    assert completed.project.status is ProjectStatus.COMPLETED
    assert service.resume_project(created.id).pending_actions == ()
    with pytest.raises(ProjectSessionStateError):
        service.complete_project(created.id)
    with pytest.raises(ProjectSessionStateError):
        service.confirm_project_mode(created.id, WorkMode.DEVELOPER, ProjectMode.NEW)


def test_missing_proposer_is_explicit_and_reads_do_not_propose() -> None:
    store = InMemoryProjectSessionStore()
    with pytest.raises(ProjectSessionError, match="not configured"):
        ProjectSessionService(store).create_project_request("Request")
    proposer = _Proposer()
    service = _service(store, proposer)
    created = service.create_project_request("Request")
    assert service.get_project(created.id).project == created.project
    assert proposer.calls == 1


@pytest.mark.parametrize(
    ("mode", "expected"),
    (
        (WorkMode.DEVELOPER, ProjectPendingActionType.BIND_DEVELOPER_RUN),
        (WorkMode.RESEARCHER, ProjectPendingActionType.BIND_RESEARCH_RUN),
    ),
)
def test_unbound_active_project_requires_explicit_binding(
    mode: WorkMode, expected: ProjectPendingActionType
) -> None:
    service, project_id = _active_service(mode)
    assert service.get_pending_actions(project_id)[0].action_type is expected


@pytest.mark.parametrize(
    ("review_status", "execution_status", "expected"),
    (
        (
            PlanReviewStatus.AWAITING_APPROVAL,
            ProjectExecutionStatus.AWAITING_PLAN_APPROVAL,
            ProjectPendingActionType.APPROVE_DEVELOPER_PLAN,
        ),
        (
            PlanReviewStatus.APPROVED,
            ProjectExecutionStatus.READY,
            ProjectPendingActionType.CONTINUE_DEVELOPER,
        ),
        (PlanReviewStatus.APPROVED, ProjectExecutionStatus.COMPLETED, None),
    ),
)
def test_developer_authoritative_status_mapping(
    review_status: PlanReviewStatus,
    execution_status: ProjectExecutionStatus,
    expected: ProjectPendingActionType | None,
) -> None:
    run = SimpleNamespace(
        plan_revision_state=SimpleNamespace(status=review_status),
        execution_state=SimpleNamespace(status=execution_status),
    )
    reader = _Reader({"developer-run": run})
    service, project_id = _active_service(WorkMode.DEVELOPER, developer_reader=reader)
    service.bind_developer_run(project_id, "developer-run")
    actions = service.get_pending_actions(project_id)
    assert (() if expected is None else (actions[0].action_type,)) == (
        () if expected is None else (expected,)
    )


@pytest.mark.parametrize(
    ("status", "expected"),
    (
        (
            ResearchStatus.AWAITING_DIRECTION_SELECTION,
            ProjectPendingActionType.SELECT_RESEARCH_DIRECTION,
        ),
        (
            ResearchStatus.AWAITING_RESEARCH_PLAN_APPROVAL,
            ProjectPendingActionType.APPROVE_RESEARCH_PLAN,
        ),
        (
            ResearchStatus.AWAITING_USER_RESULTS,
            ProjectPendingActionType.PROVIDE_RESEARCH_RESULTS,
        ),
        (ResearchStatus.PAPER_MATERIALS_READY, None),
    ),
)
def test_researcher_authoritative_status_mapping(
    status: ResearchStatus, expected: ProjectPendingActionType | None
) -> None:
    reader = _Reader({"research-run": SimpleNamespace(status=status)})
    service, project_id = _active_service(WorkMode.RESEARCHER, research_reader=reader)
    service.bind_research_run(project_id, "research-run")
    actions = service.get_pending_actions(project_id)
    assert (() if expected is None else (actions[0].action_type,)) == (
        () if expected is None else (expected,)
    )


def test_missing_bound_run_fails_explicitly_without_repair() -> None:
    service, project_id = _active_service(
        WorkMode.DEVELOPER, developer_reader=_Reader({})
    )
    bound = service.bind_developer_run(project_id, "missing")
    with pytest.raises(ProjectSessionError, match="Linked Developer run not found"):
        service.get_pending_actions(project_id)
    assert service.get_project(project_id).project == bound.project


def test_hybrid_reports_independent_actions_and_reads_are_immutable() -> None:
    developer = SimpleNamespace(
        plan_revision_state=SimpleNamespace(status=PlanReviewStatus.AWAITING_APPROVAL),
        execution_state=SimpleNamespace(
            status=ProjectExecutionStatus.AWAITING_PLAN_APPROVAL
        ),
    )
    research = SimpleNamespace(status=ResearchStatus.AWAITING_USER_RESULTS)
    developer_reader = _Reader({"D": developer})
    research_reader = _Reader({"R": research})
    service, project_id = _active_service(
        WorkMode.HYBRID,
        developer_reader=developer_reader,
        research_reader=research_reader,
    )
    service.bind_developer_run(project_id, "D")
    before = service.bind_research_run(project_id, "R").project
    actions = service.resume_project(project_id).pending_actions
    assert tuple(action.action_type for action in actions) == (
        ProjectPendingActionType.APPROVE_DEVELOPER_PLAN,
        ProjectPendingActionType.PROVIDE_RESEARCH_RESULTS,
    )
    assert service.get_project(project_id).project == before
    assert developer.plan_revision_state.status is PlanReviewStatus.AWAITING_APPROVAL
    assert research.status is ResearchStatus.AWAITING_USER_RESULTS


def test_file_project_store_round_trip_and_corruption_fails(tmp_path: Path) -> None:
    proposer = _Proposer()
    root = tmp_path / "projects"
    service = _service(FileProjectStore(root), proposer)
    created = service.create_project_request("Request")
    confirmed = service.confirm_project_mode(
        created.id, WorkMode.DEVELOPER, ProjectMode.UPGRADE
    )
    reopened = FileProjectStore(root).get(created.id)
    assert reopened == confirmed.project

    path = root / f"{created.id}.json"
    path.write_text("not-json", encoding="utf-8")
    with pytest.raises(ProjectSessionStorageError):
        FileProjectStore(root).get(created.id)


@pytest.mark.parametrize(
    "relative_path",
    (
        "src/ai_agent_project/agent/project_session.py",
        "src/ai_agent_project/agent/project_session_application.py",
        "src/ai_agent_project/agent/project_session_file_store.py",
        "src/ai_agent_project/llm/providers/openai_project_mode_proposer.py",
        "src/ai_agent_project/cli.py",
        "src/ai_agent_project/api/app.py",
    ),
)
def test_project_session_surface_has_no_execution_calls(relative_path: str) -> None:
    tree = ast.parse(Path(relative_path).read_text(encoding="utf-8"))
    prohibited = {
        "exec",
        "eval",
        "os.system",
        "subprocess.run",
        "subprocess.Popen",
        "subprocess.call",
        "subprocess.check_call",
        "subprocess.check_output",
    }
    calls = {
        name
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and (name := _call_name(node.func)) is not None
    }
    assert not calls & prohibited


@pytest.mark.parametrize("file_backed", [False, True], ids=["memory", "file"])
def test_conditional_developer_bind_has_one_winner(tmp_path, file_backed) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    shared_store = InMemoryProjectSessionStore()
    store = FileProjectStore(tmp_path) if file_backed else shared_store
    service = _service(store)
    pending = service.create_project_request("Test conditional binding")
    original = service.confirm_project_mode(
        pending.id, WorkMode.HYBRID, ProjectMode.NEW
    ).project
    ready = Barrier(2)

    def bind(run_id: str):
        contender = FileProjectStore(tmp_path) if file_backed else shared_store
        ready.wait(timeout=10)
        try:
            return contender.bind_developer_run_if_unbound(pending.id, run_id)
        except ProjectSessionStateError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(bind, ("run-a", "run-b")))
    winners = [result for result in results if result is not None]
    assert len(winners) == 1
    winner = winners[0]
    assert store.get(pending.id) == winner
    assert winner.model_dump(
        exclude={"developer_run_id", "updated_at"}
    ) == original.model_dump(exclude={"developer_run_id", "updated_at"})
    with pytest.raises(ProjectSessionStateError, match="already"):
        store.bind_developer_run_if_unbound(pending.id, "run-c")
    assert store.get(pending.id) == winner
