from types import SimpleNamespace

import pytest

from ai_agent_project.agent.hybrid_coordination_application import (
    HybridCoordinationError,
    HybridCoordinationService,
)
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
)
from ai_agent_project.agent.research import ResearchStatus, WorkMode
from ai_agent_project.agent.upgrade import ProjectMode


class _Proposer:
    def __init__(self) -> None:
        self.calls = 0

    def propose(self, _request: str) -> ProjectModeProposal:
        self.calls += 1
        return ProjectModeProposal(
            proposed_work_mode=WorkMode.HYBRID,
            proposed_project_mode=ProjectMode.NEW,
            rationale="Advisory",
        )


class _Reader:
    def __init__(self, values: dict[str, object]) -> None:
        self.values = values

    def get(self, run_id: str):
        return self.values.get(run_id)


def _developer(status: ProjectExecutionStatus):
    review = (
        PlanReviewStatus.AWAITING_APPROVAL
        if status is ProjectExecutionStatus.AWAITING_PLAN_APPROVAL
        else PlanReviewStatus.APPROVED
    )
    return SimpleNamespace(
        plan_revision_state=SimpleNamespace(status=review),
        execution_state=SimpleNamespace(status=status),
    )


def _researcher(status: ResearchStatus):
    return SimpleNamespace(status=status)


def _services(
    developer_status: ProjectExecutionStatus | None,
    researcher_status: ResearchStatus | None,
    *,
    mode: WorkMode = WorkMode.HYBRID,
):
    proposer = _Proposer()
    developers = _Reader(
        {} if developer_status is None else {"D": _developer(developer_status)}
    )
    researchers = _Reader(
        {} if researcher_status is None else {"R": _researcher(researcher_status)}
    )
    sessions = ProjectSessionService(
        InMemoryProjectSessionStore(), proposer, developers, researchers
    )
    project_id = sessions.create_project_request("Coordinate").id
    sessions.confirm_project_mode(project_id, mode, ProjectMode.NEW)
    coordination = HybridCoordinationService(sessions, developers, researchers)
    return sessions, coordination, proposer, project_id, developers, researchers


@pytest.mark.parametrize(
    ("developer_status", "researcher_status", "expected", "both_terminal"),
    (
        (
            ProjectExecutionStatus.READY,
            ResearchStatus.DIRECTION_SELECTED,
            (
                ProjectPendingActionType.CONTINUE_DEVELOPER,
                ProjectPendingActionType.CONTINUE_RESEARCHER,
            ),
            False,
        ),
        (
            ProjectExecutionStatus.COMPLETED,
            ResearchStatus.DIRECTION_SELECTED,
            (ProjectPendingActionType.CONTINUE_RESEARCHER,),
            False,
        ),
        (
            ProjectExecutionStatus.READY,
            ResearchStatus.PAPER_MATERIALS_READY,
            (ProjectPendingActionType.CONTINUE_DEVELOPER,),
            False,
        ),
        (
            ProjectExecutionStatus.COMPLETED,
            ResearchStatus.PAPER_MATERIALS_READY,
            (),
            True,
        ),
    ),
)
def test_coordination_lane_matrix_and_stable_order(
    developer_status, researcher_status, expected, both_terminal
) -> None:
    sessions, coordination, _, project_id, _, _ = _services(
        developer_status, researcher_status
    )
    sessions.bind_developer_run(project_id, "D")
    sessions.bind_research_run(project_id, "R")

    view = coordination.get_coordination(project_id)

    assert tuple(item.action_type for item in view.actionable_actions) == expected
    assert view.both_workflows_terminal is both_terminal
    assert view.developer.terminal is (
        developer_status is ProjectExecutionStatus.COMPLETED
    )
    assert view.researcher.terminal is (
        researcher_status is ResearchStatus.PAPER_MATERIALS_READY
    )


def test_unbound_lanes_remain_independent_and_developer_first() -> None:
    sessions, coordination, _, project_id, _, _ = _services(
        ProjectExecutionStatus.READY, ResearchStatus.DIRECTION_SELECTED
    )
    sessions.bind_research_run(project_id, "R")
    view = coordination.get_coordination(project_id)
    assert view.developer.run_id is None
    assert view.developer.pending_action.action_type is (
        ProjectPendingActionType.BIND_DEVELOPER_RUN
    )
    assert view.researcher.pending_action.action_type is (
        ProjectPendingActionType.CONTINUE_RESEARCHER
    )
    assert tuple(item.action_type for item in view.actionable_actions) == (
        ProjectPendingActionType.BIND_DEVELOPER_RUN,
        ProjectPendingActionType.CONTINUE_RESEARCHER,
    )

    sessions, coordination, _, project_id, _, _ = _services(
        ProjectExecutionStatus.READY, ResearchStatus.DIRECTION_SELECTED
    )
    sessions.bind_developer_run(project_id, "D")
    view = coordination.get_coordination(project_id)
    assert view.researcher.pending_action.action_type is (
        ProjectPendingActionType.BIND_RESEARCH_RUN
    )


def test_missing_runs_and_non_hybrid_are_explicit() -> None:
    sessions, coordination, _, project_id, _, _ = _services(None, None)
    sessions.bind_developer_run(project_id, "missing-D")
    sessions.bind_research_run(project_id, "missing-R")
    with pytest.raises(ProjectSessionError, match="Linked Developer run not found"):
        coordination.get_coordination(project_id)

    sessions, coordination, _, project_id, developers, _ = _services(
        ProjectExecutionStatus.READY, None
    )
    sessions.bind_developer_run(project_id, "D")
    sessions.bind_research_run(project_id, "missing-R")
    with pytest.raises(ProjectSessionError, match="Linked Researcher run not found"):
        HybridCoordinationService(sessions, developers, _Reader({})).get_coordination(
            project_id
        )

    _, coordination, _, project_id, _, _ = _services(
        ProjectExecutionStatus.READY,
        ResearchStatus.DIRECTION_SELECTED,
        mode=WorkMode.DEVELOPER,
    )
    with pytest.raises(HybridCoordinationError, match="not Hybrid"):
        coordination.get_coordination(project_id)


def test_missing_readers_are_explicit() -> None:
    sessions, _, _, project_id, developers, researchers = _services(
        ProjectExecutionStatus.READY, ResearchStatus.DIRECTION_SELECTED
    )
    sessions.bind_developer_run(project_id, "D")
    sessions.bind_research_run(project_id, "R")
    with pytest.raises(HybridCoordinationError, match="Developer run reader"):
        HybridCoordinationService(sessions, None, researchers).get_coordination(
            project_id
        )
    with pytest.raises(HybridCoordinationError, match="Research run reader"):
        HybridCoordinationService(sessions, developers, None).get_coordination(
            project_id
        )


def test_completed_coordination_still_rejects_missing_linked_run() -> None:
    sessions, coordination, _, project_id, _, _ = _services(None, None)
    sessions.bind_developer_run(project_id, "missing-D")
    sessions.complete_project(project_id)
    with pytest.raises(HybridCoordinationError, match="Linked Developer run not found"):
        coordination.get_coordination(project_id)


def test_completed_view_inspects_reality_but_has_no_actions() -> None:
    sessions, coordination, proposer, project_id, developers, researchers = _services(
        ProjectExecutionStatus.COMPLETED, ResearchStatus.PAPER_MATERIALS_READY
    )
    sessions.bind_developer_run(project_id, "D")
    sessions.bind_research_run(project_id, "R")
    sessions.complete_project(project_id)
    before = sessions.get_project(project_id).project

    first = coordination.get_coordination(project_id)
    second = coordination.get_coordination(project_id)

    assert first == second
    assert first.project_status is ProjectStatus.COMPLETED
    assert first.actionable_actions == ()
    assert first.developer.source_status == "completed"
    assert first.researcher.source_status == "paper_materials_ready"
    assert first.both_workflows_terminal
    assert sessions.get_project(project_id).project == before
    assert (
        developers.get("D").execution_state.status is ProjectExecutionStatus.COMPLETED
    )
    assert researchers.get("R").status is ResearchStatus.PAPER_MATERIALS_READY
    assert proposer.calls == 1


@pytest.mark.parametrize(
    ("developer_status", "researcher_status", "bind_developer", "bind_researcher"),
    (
        (
            ProjectExecutionStatus.COMPLETED,
            ResearchStatus.PAPER_MATERIALS_READY,
            True,
            True,
        ),
        (
            ProjectExecutionStatus.COMPLETED,
            ResearchStatus.DIRECTION_SELECTED,
            True,
            True,
        ),
        (ProjectExecutionStatus.READY, ResearchStatus.DIRECTION_SELECTED, True, True),
        (ProjectExecutionStatus.READY, ResearchStatus.DIRECTION_SELECTED, False, False),
    ),
)
def test_explicit_completion_remains_closure_without_domain_mutation(
    developer_status, researcher_status, bind_developer, bind_researcher
) -> None:
    sessions, _, _, project_id, developers, researchers = _services(
        developer_status, researcher_status
    )
    if bind_developer:
        sessions.bind_developer_run(project_id, "D")
    if bind_researcher:
        sessions.bind_research_run(project_id, "R")
    developer_before = developers.get("D")
    researcher_before = researchers.get("R")

    completed = sessions.complete_project(project_id)

    assert completed.project.status is ProjectStatus.COMPLETED
    assert developers.get("D") is developer_before
    assert researchers.get("R") is researcher_before


def test_both_terminal_does_not_automatically_complete_project() -> None:
    sessions, coordination, _, project_id, _, _ = _services(
        ProjectExecutionStatus.COMPLETED, ResearchStatus.PAPER_MATERIALS_READY
    )
    sessions.bind_developer_run(project_id, "D")
    sessions.bind_research_run(project_id, "R")
    assert coordination.get_coordination(project_id).both_workflows_terminal
    assert sessions.get_project(project_id).project.status is ProjectStatus.ACTIVE
