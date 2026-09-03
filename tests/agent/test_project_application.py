"""Tests for immutable stored project-run application lifecycle operations."""

from uuid import UUID

import pytest

from ai_agent_project.agent.checkpoint import CheckpointDecision
from ai_agent_project.agent.plan import ImplementationPlan
from ai_agent_project.agent.project import (
    ProjectPhase,
    ProjectPlan,
    ProjectSpecification,
)
from ai_agent_project.agent.project_application import (
    InMemoryProjectRunStore,
    ProjectApplicationService,
    ProjectPlanReviewError,
    ProjectRunAlreadyExistsError,
    ProjectRunNotFoundError,
)
from ai_agent_project.agent.project_execution import (
    PhaseExecutionRecord,
    ProjectExecutionState,
    ProjectExecutionStatus,
)
from ai_agent_project.agent.project_runner import ProjectRun
from ai_agent_project.agent.specification import Specification
from ai_agent_project.agent.workspace import WorkspaceSnapshot


def make_project_run(
    status: ProjectExecutionStatus = ProjectExecutionStatus.READY,
) -> ProjectRun:
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
    state = ProjectExecutionState(
        project_title="Demo",
        status=status,
        current_phase_id="PHASE-001"
        if status is not ProjectExecutionStatus.COMPLETED
        else None,
        phase_records=(PhaseExecutionRecord(phase_id="PHASE-001"),),
    )
    return ProjectRun(
        specification=specification,
        project_specification=project_specification,
        workspace=WorkspaceSnapshot(files=["src/example.py"]),
        implementation_plan=implementation_plan,
        project_plan=project_plan,
        execution_state=state,
    )


class FakeProjectRunner:
    def __init__(self, outcome: ProjectRun | Exception) -> None:
        self._outcome = outcome
        self.calls: list[tuple[str, str | None, str | None]] = []

    def start(
        self,
        source_text: str,
        *,
        project_title: str | None = None,
        source_format: str | None = None,
    ) -> ProjectRun:
        self.calls.append((source_text, project_title, source_format))
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


class FakeProjectExecutionService:
    def __init__(
        self,
        execute_outcome: ProjectExecutionState | Exception,
        decide_outcome: ProjectExecutionState | Exception,
    ) -> None:
        self._execute_outcome = execute_outcome
        self._decide_outcome = decide_outcome
        self.execute_calls: list[tuple[object, ...]] = []
        self.decide_calls: list[tuple[object, ...]] = []
        self.start_calls: list[tuple[object, ...]] = []

    def start(self, *args: object) -> ProjectExecutionState:
        self.start_calls.append(args)
        plan = args[2]
        assert isinstance(plan, ProjectPlan)
        return ProjectExecutionState(
            project_title=plan.project_title,
            status=ProjectExecutionStatus.READY,
            current_phase_id=plan.phases[0].id,
            phase_records=tuple(
                PhaseExecutionRecord(phase_id=phase.id) for phase in plan.phases
            ),
        )

    def execute_current_phase(self, *args: object) -> ProjectExecutionState:
        self.execute_calls.append(args)
        if isinstance(self._execute_outcome, Exception):
            raise self._execute_outcome
        return self._execute_outcome

    def decide_current_phase(self, *args: object) -> ProjectExecutionState:
        self.decide_calls.append(args)
        if isinstance(self._decide_outcome, Exception):
            raise self._decide_outcome
        return self._decide_outcome


class RecordingStore(InMemoryProjectRunStore):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []

    def create(self, project_run_id: str, project_run: ProjectRun) -> None:
        self.calls.append("create")
        super().create(project_run_id, project_run)

    def get(self, project_run_id: str) -> ProjectRun | None:
        self.calls.append("get")
        return super().get(project_run_id)

    def replace(self, project_run_id: str, project_run: ProjectRun) -> None:
        self.calls.append("replace")
        super().replace(project_run_id, project_run)


class FakePlanReviser:
    def __init__(self, plan: ProjectPlan | Exception) -> None:
        self.plan_result = plan
        self.calls: list[tuple[object, ...]] = []

    def revise(self, *args: object) -> ProjectPlan:
        self.calls.append(args)
        if isinstance(self.plan_result, Exception):
            raise self.plan_result
        return self.plan_result


def make_service(
    project_run: ProjectRun,
    *,
    execute_outcome: ProjectExecutionState | Exception | None = None,
    decide_outcome: ProjectExecutionState | Exception | None = None,
    plan_reviser: FakePlanReviser | None = None,
) -> tuple[
    ProjectApplicationService,
    FakeProjectRunner,
    FakeProjectExecutionService,
    RecordingStore,
]:
    runner = FakeProjectRunner(project_run)
    execution_service = FakeProjectExecutionService(
        execute_outcome or project_run.execution_state,
        decide_outcome or project_run.execution_state,
    )
    store = RecordingStore()
    return (
        ProjectApplicationService(
            runner,  # type: ignore[arg-type]
            execution_service,  # type: ignore[arg-type]
            store,
            plan_reviser,  # type: ignore[arg-type]
        ),
        runner,
        execution_service,
        store,
    )


def test_store_create_get_replace_and_instance_isolation() -> None:
    first = InMemoryProjectRunStore()
    second = InMemoryProjectRunStore()
    original = make_project_run()
    replacement = make_project_run(ProjectExecutionStatus.RETRY_REQUESTED)

    first.create("run-1", original)
    assert first.get("run-1") is original
    assert second.get("run-1") is None
    with pytest.raises(ProjectRunAlreadyExistsError):
        first.create("run-1", replacement)
    first.replace("run-1", replacement)
    assert first.get("run-1") is replacement
    with pytest.raises(ProjectRunNotFoundError):
        first.replace("missing", replacement)


def test_create_project_bootstraps_once_stores_uuid_and_does_not_execute() -> None:
    project_run = make_project_run()
    service, runner, execution_service, store = make_service(project_run)

    stored = service.create_project(
        "# Project", project_title="Explicit", source_format="markdown"
    )

    assert UUID(stored.id)
    assert stored.project_run is project_run
    assert stored.project_run.execution_state.status is ProjectExecutionStatus.READY
    assert runner.calls == [("# Project", "Explicit", "markdown")]
    assert execution_service.execute_calls == []
    assert store.calls == ["create"]
    assert store.get(stored.id) is project_run


def test_get_project_returns_snapshot_and_missing_id_has_domain_error() -> None:
    service, _, _, _ = make_service(make_project_run())
    stored = service.create_project("project")

    assert service.get_project(stored.id).project_run is stored.project_run
    with pytest.raises(ProjectRunNotFoundError):
        service.get_project("missing")


def test_execute_replaces_only_execution_state_without_rebootstrap() -> None:
    original = make_project_run()
    updated_state = original.execution_state.model_copy(
        update={"status": ProjectExecutionStatus.AWAITING_CHECKPOINT}
    )
    service, runner, execution_service, store = make_service(
        original,
        execute_outcome=updated_state,
    )
    stored = service.create_project("project")
    store.calls.clear()

    updated = service.execute_current_phase(stored.id)

    assert store.calls == ["get", "replace"]
    assert len(execution_service.execute_calls) == 1
    assert runner.calls == [("project", None, None)]
    assert execution_service.execute_calls[0] == (
        original.execution_state,
        original.specification,
        original.project_specification,
        original.project_plan,
    )
    assert updated.project_run.execution_state is updated_state
    assert updated.project_run.workspace is original.workspace
    assert updated.project_run.implementation_plan is original.implementation_plan
    assert updated.project_run.project_plan is original.project_plan
    assert stored.project_run.execution_state.status is ProjectExecutionStatus.READY
    assert service.get_project(stored.id).project_run is updated.project_run


@pytest.mark.parametrize(
    ("decision", "status"),
    [
        (CheckpointDecision.APPROVE, ProjectExecutionStatus.READY),
        (CheckpointDecision.RETRY, ProjectExecutionStatus.RETRY_REQUESTED),
        (CheckpointDecision.REQUEST_CHANGES, ProjectExecutionStatus.REVISION_REQUESTED),
        (CheckpointDecision.STOP, ProjectExecutionStatus.STOPPED),
    ],
)
def test_decide_replaces_state_without_auto_execution(
    decision: CheckpointDecision,
    status: ProjectExecutionStatus,
) -> None:
    original = make_project_run(ProjectExecutionStatus.AWAITING_CHECKPOINT)
    decided_state = original.execution_state.model_copy(update={"status": status})
    service, runner, execution_service, store = make_service(
        original,
        decide_outcome=decided_state,
    )
    stored = service.create_project("project")
    store.calls.clear()

    updated = service.decide_current_phase(stored.id, decision, note="review note")

    assert store.calls == ["get", "replace"]
    assert runner.calls == [("project", None, None)]
    assert execution_service.execute_calls == []
    assert execution_service.decide_calls == [
        (original.execution_state, original.project_plan, decision, "review note")
    ]
    assert updated.project_run.execution_state is decided_state
    assert updated.project_run.execution_state.status is status


@pytest.mark.parametrize("operation", ["execute", "decide"])
def test_execution_service_failure_keeps_original_snapshot(
    operation: str,
) -> None:
    original = make_project_run(
        ProjectExecutionStatus.AWAITING_CHECKPOINT
        if operation == "decide"
        else ProjectExecutionStatus.READY
    )
    failure = ValueError("domain failure")
    service, _, _, store = make_service(
        original,
        execute_outcome=failure,
        decide_outcome=failure,
    )
    stored = service.create_project("project")
    store.calls.clear()

    with pytest.raises(ValueError, match="domain failure"):
        if operation == "execute":
            service.execute_current_phase(stored.id)
        else:
            service.decide_current_phase(stored.id, CheckpointDecision.STOP)

    assert store.calls == ["get"]
    assert service.get_project(stored.id).project_run is original


def test_bootstrap_failure_stores_nothing() -> None:
    runner = FakeProjectRunner(ValueError("bootstrap failure"))
    execution_service = FakeProjectExecutionService(
        make_project_run().execution_state,
        make_project_run().execution_state,
    )
    store = RecordingStore()
    service = ProjectApplicationService(
        runner,  # type: ignore[arg-type]
        execution_service,  # type: ignore[arg-type]
        store,
    )

    with pytest.raises(ValueError, match="bootstrap failure"):
        service.create_project("project")

    assert runner.calls == [("project", None, None)]
    assert store.calls == []


def test_plan_revision_resets_pre_execution_state_and_preserves_tasks() -> None:
    original = make_project_run(ProjectExecutionStatus.AWAITING_PLAN_APPROVAL)
    revised_plan = original.project_plan.model_copy(
        update={
            "phases": (
                original.project_plan.phases[0].model_copy(
                    update={"id": "PHASE-REVISED", "title": "Clearer feature phase"}
                ),
            )
        }
    )
    reviser = FakePlanReviser(revised_plan)
    service, _, execution_service, store = make_service(original, plan_reviser=reviser)
    stored = service.create_project("project")
    store.calls.clear()

    revised = service.revise_plan(stored.id, "Clarify phase responsibilities.")

    assert reviser.calls[0][1] is original.project_plan
    assert revised.project_run.project_plan == revised_plan
    assert revised.project_run.plan_revision_state.active_version == 2
    assert (
        revised.project_run.plan_revision_state.revisions[0].plan
        is original.project_plan
    )
    assert revised.project_run.implementation_plan is original.implementation_plan
    assert (
        revised.project_run.execution_state.status
        is ProjectExecutionStatus.AWAITING_PLAN_APPROVAL
    )
    assert [
        record.phase_id for record in revised.project_run.execution_state.phase_records
    ] == ["PHASE-REVISED"]
    assert all(
        record.attempt_count == 0
        for record in revised.project_run.execution_state.phase_records
    )
    assert execution_service.start_calls
    assert store.calls == ["get", "replace"]


def test_plan_approval_makes_phase_ready_without_execution() -> None:
    original = make_project_run(ProjectExecutionStatus.AWAITING_PLAN_APPROVAL)
    service, _, execution_service, _ = make_service(original)
    stored = service.create_project("project")

    approved = service.approve_plan(stored.id)

    assert approved.project_run.plan_revision_state.status.value == "approved"
    assert approved.project_run.execution_state.status is ProjectExecutionStatus.READY
    assert approved.project_run.execution_state.current_phase_id == "PHASE-001"
    assert execution_service.execute_calls == []
    with pytest.raises(ProjectPlanReviewError, match="approved"):
        service.approve_plan(stored.id)
    with pytest.raises(ProjectPlanReviewError, match="approved"):
        service.revise_plan(stored.id, "Another layout")


def test_execution_is_blocked_until_plan_approval_and_blank_feedback_is_rejected() -> (
    None
):
    original = make_project_run(ProjectExecutionStatus.AWAITING_PLAN_APPROVAL)
    reviser = FakePlanReviser(original.project_plan)
    service, _, execution_service, _ = make_service(original, plan_reviser=reviser)
    stored = service.create_project("project")

    with pytest.raises(ProjectPlanReviewError, match="must be approved"):
        service.execute_current_phase(stored.id)
    with pytest.raises(ProjectPlanReviewError, match="must not be blank"):
        service.revise_plan(stored.id, " ")
    assert execution_service.execute_calls == []
    assert reviser.calls == []
