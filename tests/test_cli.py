"""Offline tests for the thin persisted project lifecycle CLI."""

from io import StringIO
from pathlib import Path
from uuid import uuid4

from ai_agent_project.agent.acceptance import (
    AcceptanceCriterionResult,
    AcceptanceReport,
    AcceptanceStatus,
    RequirementValidationResult,
)
from ai_agent_project.agent.checkpoint import (
    CheckpointDecision,
    CheckpointStatus,
    NextAction,
    PhaseCheckpoint,
    PhaseProgressReport,
)
from ai_agent_project.agent.phase_execution import (
    PhaseExecutionResult,
    PhaseExecutionService,
    PhaseExecutionStatus,
)
from ai_agent_project.agent.plan import ImplementationPlan
from ai_agent_project.agent.project import (
    ProjectPhase,
    ProjectPlan,
    ProjectSpecification,
)
from ai_agent_project.agent.project_application import StoredProjectRun
from ai_agent_project.agent.project_execution import (
    PhaseExecutionRecord,
    ProjectExecutionState,
    ProjectExecutionStatus,
)
from ai_agent_project.agent.project_file_store import FileProjectRunStore
from ai_agent_project.agent.project_runner import ProjectRun
from ai_agent_project.agent.specification import Specification
from ai_agent_project.agent.state import AgentState, AgentStatus
from ai_agent_project.agent.workspace import WorkspaceSnapshot
from ai_agent_project.cli import run_cli


def make_project_run(*, executed: bool = False) -> ProjectRun:
    specification = Specification.model_validate(
        {"requirements": [{"id": "REQ-001", "description": "Build feature."}]}
    )
    project_specification = ProjectSpecification.from_specification(specification)
    implementation_plan = ImplementationPlan.model_validate(
        {
            "tasks": [
                {
                    "id": "TASK-001",
                    "title": "Build",
                    "description": "Build feature.",
                    "requirement_ids": ["REQ-001"],
                }
            ]
        }
    )
    project_plan = ProjectPlan(
        project_title="Demo",
        phases=(
            ProjectPhase(
                id="PHASE-001",
                title="Feature",
                objective="Build feature.",
                requirement_ids=("REQ-001",),
                task_ids=("TASK-001",),
            ),
        ),
        implementation_plan=implementation_plan,
    )
    record = PhaseExecutionRecord(phase_id="PHASE-001")
    status = ProjectExecutionStatus.AWAITING_PLAN_APPROVAL
    if executed:
        acceptance = AcceptanceReport(
            requirements=[
                RequirementValidationResult(
                    requirement_id="REQ-001",
                    status=AcceptanceStatus.PASSED,
                    criteria=[
                        AcceptanceCriterionResult(
                            criterion="Feature works.", status=AcceptanceStatus.PASSED
                        )
                    ],
                )
            ]
        )
        execution = PhaseExecutionResult(
            phase_id="PHASE-001",
            status=PhaseExecutionStatus.COMPLETED,
            requirement_ids=("REQ-001",),
            task_ids=("TASK-001",),
            agent_run=AgentState(status=AgentStatus.COMPLETED),
            acceptance_report=acceptance,
        )
        progress = PhaseProgressReport(
            phase_id="PHASE-001",
            phase_title="Feature",
            execution_status=PhaseExecutionStatus.COMPLETED,
            requirement_ids=("REQ-001",),
            task_ids=("TASK-001",),
            passed_requirement_ids=("REQ-001",),
            failed_requirement_ids=(),
            unknown_requirement_ids=(),
            repair_attempt_count=0,
            summary="Phase completed.",
            recommended_decisions=(CheckpointDecision.APPROVE,),
        )
        record = PhaseExecutionRecord(
            phase_id="PHASE-001",
            execution=execution,
            progress_report=progress,
            checkpoint=PhaseCheckpoint(
                phase_id="PHASE-001",
                execution_status=PhaseExecutionStatus.COMPLETED,
                status=CheckpointStatus.AWAITING_DECISION,
                next_action=NextAction.BLOCKED,
            ),
            attempt_count=1,
        )
        status = ProjectExecutionStatus.AWAITING_CHECKPOINT
    return ProjectRun(
        specification=specification,
        project_specification=project_specification,
        workspace=WorkspaceSnapshot(files=["src/example.py"]),
        implementation_plan=implementation_plan,
        project_plan=project_plan,
        execution_state=ProjectExecutionState(
            project_title="Demo",
            status=status,
            current_phase_id="PHASE-001",
            phase_records=(record,),
        ),
    )


class FakeProjectApplicationService:
    def __init__(self, store: FileProjectRunStore) -> None:
        self.store = store
        self.create_calls: list[tuple[str, str | None, str | None]] = []
        self.execute_calls: list[str] = []
        self.decision_calls: list[tuple[str, CheckpointDecision, str | None]] = []

    def create_project(
        self,
        source_text: str,
        *,
        project_title: str | None = None,
        source_format: str | None = None,
    ) -> StoredProjectRun:
        self.create_calls.append((source_text, project_title, source_format))
        project_run_id = str(uuid4())
        project_run = make_project_run()
        self.store.create(project_run_id, project_run)
        return StoredProjectRun(id=project_run_id, project_run=project_run)

    def get_project(self, project_run_id: str) -> StoredProjectRun:
        project_run = self.store.get(project_run_id)
        assert project_run is not None
        return StoredProjectRun(id=project_run_id, project_run=project_run)

    def get_plan(self, project_run_id: str):
        project_run = self.store.get(project_run_id)
        assert project_run is not None
        assert project_run.plan_revision_state is not None
        return project_run.plan_revision_state

    def revise_plan(self, project_run_id: str, feedback: str) -> StoredProjectRun:
        project_run = self.store.get(project_run_id)
        assert project_run is not None
        revisions = project_run.plan_revision_state.revise(
            project_run.project_plan, feedback
        )
        updated = project_run.model_copy(update={"plan_revision_state": revisions})
        self.store.replace(project_run_id, updated)
        return StoredProjectRun(id=project_run_id, project_run=updated)

    def approve_plan(self, project_run_id: str) -> StoredProjectRun:
        project_run = self.store.get(project_run_id)
        assert project_run is not None
        revisions = project_run.plan_revision_state.approve()
        state = project_run.execution_state.model_copy(
            update={"status": ProjectExecutionStatus.READY}
        )
        updated = project_run.model_copy(
            update={"plan_revision_state": revisions, "execution_state": state}
        )
        self.store.replace(project_run_id, updated)
        return StoredProjectRun(id=project_run_id, project_run=updated)

    def execute_current_phase(self, project_run_id: str) -> StoredProjectRun:
        self.execute_calls.append(project_run_id)
        project_run = make_project_run(executed=True)
        self.store.replace(project_run_id, project_run)
        return StoredProjectRun(id=project_run_id, project_run=project_run)

    def decide_current_phase(
        self,
        project_run_id: str,
        decision: CheckpointDecision,
        *,
        note: str | None = None,
    ) -> StoredProjectRun:
        self.decision_calls.append((project_run_id, decision, note))
        project_run = self.store.get(project_run_id)
        assert project_run is not None
        status = {
            CheckpointDecision.APPROVE: ProjectExecutionStatus.READY,
            CheckpointDecision.RETRY: ProjectExecutionStatus.RETRY_REQUESTED,
            CheckpointDecision.REQUEST_CHANGES: ProjectExecutionStatus.REVISION_REQUESTED,
            CheckpointDecision.STOP: ProjectExecutionStatus.STOPPED,
        }[decision]
        state = project_run.execution_state.model_copy(
            update={"status": status, "stopped_reason": note}
        )
        updated = project_run.model_copy(update={"execution_state": state})
        self.store.replace(project_run_id, updated)
        return StoredProjectRun(id=project_run_id, project_run=updated)


def make_builder(services: list[FakeProjectApplicationService]):
    def build(
        _workspace: Path, store: FileProjectRunStore
    ) -> FakeProjectApplicationService:
        service = FakeProjectApplicationService(store)
        services.append(service)
        return service

    return build


def test_create_persists_workspace_and_status_reopens_separate_service(
    tmp_path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    plan = tmp_path / "plan.md"
    plan.write_text("# Demo", encoding="utf-8")
    store_root = tmp_path / "runs"
    services: list[FakeProjectApplicationService] = []
    output = StringIO()

    assert (
        run_cli(
            [
                "project",
                "--store-root",
                str(store_root),
                "create",
                str(plan),
                "--workspace",
                str(workspace),
            ],
            cwd=tmp_path,
            service_builder=make_builder(services),
            stdout=output,
        )
        == 0
    )
    run_id = next(store_root.glob("*.json")).stem
    assert services[0].create_calls == [("# Demo", None, "markdown")]
    assert services[0].execute_calls == []
    assert FileProjectRunStore(store_root).workspace_root_for(run_id) == workspace
    assert "awaiting_plan_approval" in output.getvalue()

    status_output = StringIO()
    assert (
        run_cli(
            ["project", "--store-root", str(store_root), "status", run_id],
            service_builder=make_builder(services),
            stdout=status_output,
        )
        == 0
    )
    assert "Run ID:" in status_output.getvalue()
    assert len(services) == 2


def test_plan_review_cli_commands_are_explicit_and_pre_execution(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store_root = tmp_path / "runs"
    run_id = str(uuid4())
    FileProjectRunStore(store_root, workspace_root=workspace).create(
        run_id, make_project_run()
    )
    services: list[FakeProjectApplicationService] = []
    builder = make_builder(services)

    plan_output = StringIO()
    assert (
        run_cli(
            ["project", "--store-root", str(store_root), "plan", run_id],
            service_builder=builder,
            stdout=plan_output,
        )
        == 0
    )
    assert "Plan version: 1" in plan_output.getvalue()

    revision_output = StringIO()
    assert (
        run_cli(
            [
                "project",
                "--store-root",
                str(store_root),
                "revise-plan",
                run_id,
                "--note",
                "Clarify responsibilities.",
            ],
            service_builder=builder,
            stdout=revision_output,
        )
        == 0
    )
    assert "v1 -> v2" in revision_output.getvalue()
    assert (
        FileProjectRunStore(store_root).get(run_id).plan_revision_state.active_version
        == 2
    )

    approval_output = StringIO()
    assert (
        run_cli(
            ["project", "--store-root", str(store_root), "approve-plan", run_id],
            service_builder=builder,
            stdout=approval_output,
        )
        == 0
    )
    assert "Project status: ready" in approval_output.getvalue()


def test_execute_and_decisions_delegate_without_automatic_execution(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store_root = tmp_path / "runs"
    run_id = str(uuid4())
    FileProjectRunStore(store_root, workspace_root=workspace).create(
        run_id, make_project_run()
    )
    services: list[FakeProjectApplicationService] = []
    builder = make_builder(services)

    assert (
        run_cli(
            ["project", "--store-root", str(store_root), "execute", run_id],
            service_builder=builder,
            stdout=StringIO(),
        )
        == 0
    )
    assert services[-1].execute_calls == [run_id]

    for command, decision in (
        ("approve", CheckpointDecision.APPROVE),
        ("retry", CheckpointDecision.RETRY),
        ("request-changes", CheckpointDecision.REQUEST_CHANGES),
        ("stop", CheckpointDecision.STOP),
    ):
        arguments = ["project", "--store-root", str(store_root), command, run_id]
        if command == "request-changes":
            arguments.extend(["--note", "needs revision"])
        assert (
            run_cli(
                arguments,
                service_builder=builder,
                stdout=StringIO(),
            )
            == 0
        )
        assert services[-1].decision_calls == [
            (
                run_id,
                decision,
                "needs revision" if command == "request-changes" else None,
            )
        ]
        assert services[-1].execute_calls == []
        expected_status = {
            "approve": ProjectExecutionStatus.READY,
            "retry": ProjectExecutionStatus.RETRY_REQUESTED,
            "request-changes": ProjectExecutionStatus.REVISION_REQUESTED,
            "stop": ProjectExecutionStatus.STOPPED,
        }[command]
        assert (
            FileProjectRunStore(store_root).get(run_id).execution_state.status
            is expected_status
        )


def test_cli_reports_file_and_unknown_run_errors_without_network(tmp_path) -> None:
    errors = StringIO()
    assert (
        run_cli(
            ["project", "--store-root", str(tmp_path / "runs"), "create", "missing.md"],
            cwd=tmp_path,
            stdout=StringIO(),
            stderr=errors,
        )
        == 1
    )
    assert "Could not read plan file" in errors.getvalue()

    empty = tmp_path / "empty.md"
    empty.write_text("   ", encoding="utf-8")
    errors = StringIO()
    assert (
        run_cli(
            ["project", "--store-root", str(tmp_path / "runs"), "create", str(empty)],
            cwd=tmp_path,
            stdout=StringIO(),
            stderr=errors,
        )
        == 1
    )
    assert "must not be empty" in errors.getvalue()

    errors = StringIO()
    assert (
        run_cli(
            [
                "project",
                "--store-root",
                str(tmp_path / "runs"),
                "status",
                str(uuid4()),
            ],
            service_builder=make_builder([]),
            stdout=StringIO(),
            stderr=errors,
        )
        == 1
    )
    assert "Project run not found" in errors.getvalue()


def test_status_json_is_machine_readable(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store_root = tmp_path / "runs"
    run_id = str(uuid4())
    FileProjectRunStore(store_root, workspace_root=workspace).create(
        run_id, make_project_run()
    )
    output = StringIO()

    assert (
        run_cli(
            ["project", "--store-root", str(store_root), "status", run_id, "--json"],
            service_builder=make_builder([]),
            stdout=output,
        )
        == 0
    )
    assert '"id": "' in output.getvalue()
    assert '"workspace": "' in output.getvalue()


def test_bootstrap_developer_production_builder_persists_cwd_workspace(
    tmp_path, monkeypatch
) -> None:
    from datetime import UTC, datetime

    from ai_agent_project import cli
    from ai_agent_project.agent.project_artifact_application import (
        ProjectArtifactService,
    )
    from ai_agent_project.agent.project_handoff import ProjectHandoffPurpose
    from ai_agent_project.agent.project_handoff_application import ProjectHandoffService
    from ai_agent_project.agent.project_handoff_file_store import (
        FileProjectHandoffStore,
    )
    from ai_agent_project.agent.project_session import (
        ProjectModeProposal,
        ProjectPendingActionType,
        ProjectSession,
        ProjectStatus,
    )
    from ai_agent_project.agent.project_session_application import ProjectSessionService
    from ai_agent_project.agent.project_session_file_store import FileProjectStore
    from ai_agent_project.agent.research import WorkMode
    from ai_agent_project.agent.research_file_store import FileResearchRunStore
    from ai_agent_project.agent.upgrade import ProjectMode
    from ai_agent_project.llm.providers.openai_planner import (
        OpenAIImplementationPlanner,
    )
    from ai_agent_project.llm.providers.openai_project_planner import (
        OpenAIProjectPlanner,
    )
    from ai_agent_project.llm.providers.openai_specification import (
        OpenAISpecificationParser,
    )

    monkeypatch.syspath_prepend(str(Path(__file__).parent / "agent"))
    from test_research_implementation import (
        _approved_run,
        _implementation_plan,
    )

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "sentinel.txt").write_text("unchanged\n", encoding="utf-8")
    research = FileResearchRunStore(tmp_path / "research")
    projects = FileProjectStore(tmp_path / "projects")
    research_id, project_id = str(uuid4()), str(uuid4())
    research.create(
        research_id,
        _approved_run().model_copy(
            update={"implementation_plan": _implementation_plan()}
        ),
    )
    now = datetime.now(UTC)
    projects.create(
        project_id,
        ProjectSession(
            project_id=project_id,
            title="Workspace regression",
            original_request="Implement research",
            status=ProjectStatus.ACTIVE,
            mode_proposal=ProjectModeProposal(
                proposed_work_mode=WorkMode.HYBRID,
                proposed_project_mode=ProjectMode.NEW,
                rationale="Test fixture",
            ),
            work_mode=WorkMode.HYBRID,
            project_mode=ProjectMode.NEW,
            research_run_id=research_id,
            created_at=now,
            updated_at=now,
        ),
    )
    sessions = ProjectSessionService(projects, research_run_reader=research)
    artifacts = ProjectArtifactService(sessions, None, research)
    selected = next(
        item
        for item in artifacts.list_artifacts(project_id).artifacts
        if item.artifact_type.value == "research_implementation_plan"
    )
    handoffs = FileProjectHandoffStore(tmp_path / "projects" / "handoffs")
    handoff = ProjectHandoffService(sessions, artifacts, handoffs, research).register(
        project_id,
        selected.artifact_id,
        ProjectHandoffPurpose.DEVELOPER_BOOTSTRAP_CONTEXT,
    )
    ids = {"cli_project": project_id, "cli_handoff": handoff.handoff_id}
    # The CLI has no workspace option here: normal Developer cwd semantics apply.
    monkeypatch.chdir(workspace)
    monkeypatch.setattr(
        cli, "default_project_run_store_root", lambda: tmp_path / "developer"
    )
    monkeypatch.setattr(
        cli, "default_research_run_store_root", lambda: tmp_path / "research"
    )
    fixture = make_project_run()
    provider_calls: list[str] = []

    def parse(self, source_text, *, context=None):
        assert context is not None
        provider_calls.append("specification")
        return fixture.specification

    def implementation(self, specification, inspected_workspace):
        assert inspected_workspace.files == ["sentinel.txt"]
        provider_calls.append("implementation")
        return fixture.implementation_plan

    def project(self, specification, implementation_plan, inspected_workspace):
        assert inspected_workspace.files == ["sentinel.txt"]
        provider_calls.append("project")
        return fixture.project_plan

    def forbid_execution(*args, **kwargs):
        raise AssertionError("Bootstrap must not execute a Developer phase")

    monkeypatch.setattr(PhaseExecutionService, "execute", forbid_execution)
    monkeypatch.setattr(OpenAISpecificationParser, "parse", parse)
    monkeypatch.setattr(OpenAIImplementationPlanner, "plan", implementation)
    monkeypatch.setattr(OpenAIProjectPlanner, "plan", project)

    def snapshot(root: Path) -> dict[str, bytes]:
        return {
            str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file()
        }

    before = {
        name: snapshot(tmp_path / name)
        for name in ("workspace", "research", "projects/handoffs")
    }
    output, errors = StringIO(), StringIO()
    args = [
        "project-session",
        "--store-root",
        str(tmp_path / "projects"),
        "bootstrap-developer",
        ids["cli_project"],
        ids["cli_handoff"],
        "--request",
        "Implement the selected research task",
    ]
    assert run_cli(args, stdout=output, stderr=errors) == 0, errors.getvalue()
    assert provider_calls == ["specification", "implementation", "project"]
    projects = FileProjectStore(tmp_path / "projects")
    developers = FileProjectRunStore(tmp_path / "developer")
    session = projects.get(ids["cli_project"])
    assert session is not None and session.developer_run_id is not None
    run_id = session.developer_run_id
    assert developers.workspace_root_for(run_id) == workspace.resolve()
    run = developers.get(run_id)
    assert run is not None
    assert run.execution_state.status is ProjectExecutionStatus.AWAITING_PLAN_APPROVAL
    assert run.plan_revision_state.status.value == "awaiting_approval"
    assert run.execution_state.completed_phase_ids == ()
    assert all(
        record.attempt_count == 0 and record.execution is None
        for record in run.execution_state.phase_records
    )
    sessions = ProjectSessionService(
        projects, developer_run_reader=developers, research_run_reader=research
    )
    assert ProjectPendingActionType.APPROVE_DEVELOPER_PLAN in {
        action.action_type
        for action in sessions.get_pending_actions(ids["cli_project"])
    }
    assert before == {name: snapshot(tmp_path / name) for name in before}
    assert "Pending Action: approve_developer_plan" in output.getvalue()
    assert run_cli(args, stdout=StringIO(), stderr=StringIO()) != 0
    assert provider_calls == ["specification", "implementation", "project"]
    assert len(list((tmp_path / "developer").glob("*.json"))) == 1
    assert projects.get(ids["cli_project"]).developer_run_id == run_id
