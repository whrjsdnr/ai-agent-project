"""Tests for caller-driven project phase orchestration."""

import pytest
from pydantic import ValidationError

from ai_agent_project.agent.acceptance import (
    AcceptanceReport,
    AcceptanceStatus,
    RequirementValidationResult,
)
from ai_agent_project.agent.checkpoint import (
    CheckpointDecision,
    PhaseCheckpointService,
    ProgressReporter,
)
from ai_agent_project.agent.phase_execution import (
    PhaseExecutionResult,
    PhaseExecutionStatus,
)
from ai_agent_project.agent.plan import ImplementationPlan
from ai_agent_project.agent.project import (
    ProjectPhase,
    ProjectPlan,
    ProjectSpecification,
)
from ai_agent_project.agent.project_execution import (
    PhaseExecutionRecord,
    ProjectExecutionService,
    ProjectExecutionState,
    ProjectExecutionStatus,
)
from ai_agent_project.agent.specification import Specification
from ai_agent_project.agent.state import AgentState, AgentStatus


def make_specification() -> Specification:
    return Specification.model_validate(
        {
            "project_name": "Execution demo",
            "requirements": [
                {"id": "REQ-001", "description": "Foundation."},
                {"id": "REQ-002", "description": "Second phase."},
                {"id": "REQ-003", "description": "Third phase."},
            ],
        }
    )


def make_project_plan() -> tuple[ProjectSpecification, ProjectPlan]:
    specification = make_specification()
    implementation_plan = ImplementationPlan.model_validate(
        {
            "tasks": [
                {
                    "id": "TASK-001",
                    "title": "Foundation",
                    "description": "Build foundation.",
                    "requirement_ids": ["REQ-001"],
                },
                {
                    "id": "TASK-002",
                    "title": "Second",
                    "description": "Build second phase.",
                    "requirement_ids": ["REQ-002"],
                },
                {
                    "id": "TASK-003",
                    "title": "Third",
                    "description": "Build third phase.",
                    "requirement_ids": ["REQ-003"],
                },
            ]
        }
    )
    project_plan = ProjectPlan(
        project_title="Execution demo",
        phases=(
            ProjectPhase(
                id="PHASE-001",
                title="Foundation",
                objective="Build the foundation.",
                requirement_ids=("REQ-001",),
                task_ids=("TASK-001",),
            ),
            ProjectPhase(
                id="PHASE-002",
                title="Second",
                objective="Build second phase.",
                requirement_ids=("REQ-002",),
                task_ids=("TASK-002",),
                depends_on=("PHASE-001",),
            ),
            ProjectPhase(
                id="PHASE-003",
                title="Third",
                objective="Build third phase.",
                requirement_ids=("REQ-003",),
                task_ids=("TASK-003",),
                depends_on=("PHASE-001",),
            ),
        ),
        implementation_plan=implementation_plan,
    )
    return ProjectSpecification.from_specification(specification), project_plan


def phase_result(
    phase_id: str,
    requirement_id: str,
    status: PhaseExecutionStatus,
) -> PhaseExecutionResult:
    acceptance_status = {
        PhaseExecutionStatus.COMPLETED: AcceptanceStatus.PASSED,
        PhaseExecutionStatus.FAILED: AcceptanceStatus.FAILED,
        PhaseExecutionStatus.UNKNOWN: AcceptanceStatus.UNKNOWN,
    }[status]
    return PhaseExecutionResult(
        phase_id=phase_id,
        status=status,
        requirement_ids=(requirement_id,),
        task_ids=(f"TASK-{requirement_id[-3:]}",),
        agent_run=AgentState(status=AgentStatus.COMPLETED),
        acceptance_report=AcceptanceReport(
            requirements=[
                RequirementValidationResult(
                    requirement_id=requirement_id,
                    status=acceptance_status,
                    evidence=["acceptance evidence"],
                )
            ]
        ),
    )


class FakePhaseExecutionService:
    def __init__(self, results: list[PhaseExecutionResult]) -> None:
        self._results = results
        self.calls: list[str] = []

    def execute(self, *args: object) -> PhaseExecutionResult:
        self.calls.append(args[-1])  # type: ignore[arg-type]
        return self._results.pop(0)


def make_service(
    results: list[PhaseExecutionResult],
) -> tuple[ProjectExecutionService, FakePhaseExecutionService]:
    phase_service = FakePhaseExecutionService(results)
    return (
        ProjectExecutionService(
            phase_service,  # type: ignore[arg-type]
            ProgressReporter(),
            PhaseCheckpointService(),
        ),
        phase_service,
    )


def start_state(
    service: ProjectExecutionService,
) -> tuple[Specification, ProjectSpecification, ProjectPlan, ProjectExecutionState]:
    specification = make_specification()
    project_specification, project_plan = make_project_plan()
    return (
        specification,
        project_specification,
        project_plan,
        service.start(specification, project_specification, project_plan),
    )


def test_start_builds_ordered_records_without_executing_and_is_immutable() -> None:
    service, phase_service = make_service([])
    _, _, _, state = start_state(service)

    assert state.status is ProjectExecutionStatus.READY
    assert state.current_phase_id == "PHASE-001"
    assert [record.phase_id for record in state.phase_records] == [
        "PHASE-001",
        "PHASE-002",
        "PHASE-003",
    ]
    assert phase_service.calls == []
    with pytest.raises(ValidationError):
        state.status = ProjectExecutionStatus.STOPPED  # type: ignore[misc]


def test_execute_stores_execution_report_checkpoint_and_awaits_decision() -> None:
    service, phase_service = make_service(
        [phase_result("PHASE-001", "REQ-001", PhaseExecutionStatus.COMPLETED)]
    )
    specification, project_specification, project_plan, state = start_state(service)

    executed = service.execute_current_phase(
        state, specification, project_specification, project_plan
    )

    record = executed.phase_records[0]
    assert phase_service.calls == ["PHASE-001"]
    assert executed.status is ProjectExecutionStatus.AWAITING_CHECKPOINT
    assert record.execution is not None
    assert record.progress_report is not None
    assert record.checkpoint is not None
    assert record.attempt_count == 1
    assert state.phase_records[0].execution is None
    with pytest.raises(ValueError, match="does not allow"):
        service.execute_current_phase(
            executed, specification, project_specification, project_plan
        )


@pytest.mark.parametrize(
    "result_status",
    [PhaseExecutionStatus.FAILED, PhaseExecutionStatus.UNKNOWN],
)
def test_failed_or_unknown_execution_still_awaits_checkpoint(
    result_status: PhaseExecutionStatus,
) -> None:
    service, _ = make_service([phase_result("PHASE-001", "REQ-001", result_status)])
    specification, project_specification, project_plan, state = start_state(service)

    executed = service.execute_current_phase(
        state, specification, project_specification, project_plan
    )

    assert executed.status is ProjectExecutionStatus.AWAITING_CHECKPOINT


def test_approval_marks_completed_selects_next_ready_phase_without_execution() -> None:
    service, phase_service = make_service(
        [phase_result("PHASE-001", "REQ-001", PhaseExecutionStatus.COMPLETED)]
    )
    specification, project_specification, project_plan, state = start_state(service)
    awaiting = service.execute_current_phase(
        state, specification, project_specification, project_plan
    )

    approved = service.decide_current_phase(
        awaiting, project_plan, CheckpointDecision.APPROVE
    )

    assert approved.status is ProjectExecutionStatus.READY
    assert approved.completed_phase_ids == ("PHASE-001",)
    assert approved.current_phase_id == "PHASE-002"
    assert phase_service.calls == ["PHASE-001"]
    assert awaiting.completed_phase_ids == ()


def test_final_approval_completes_project_without_running_any_extra_phase() -> None:
    service, phase_service = make_service(
        [
            phase_result("PHASE-001", "REQ-001", PhaseExecutionStatus.COMPLETED),
            phase_result("PHASE-002", "REQ-002", PhaseExecutionStatus.COMPLETED),
            phase_result("PHASE-003", "REQ-003", PhaseExecutionStatus.COMPLETED),
        ]
    )
    specification, project_specification, project_plan, state = start_state(service)

    for _ in range(3):
        state = service.execute_current_phase(
            state, specification, project_specification, project_plan
        )
        state = service.decide_current_phase(
            state, project_plan, CheckpointDecision.APPROVE
        )

    assert state.status is ProjectExecutionStatus.COMPLETED
    assert state.current_phase_id is None
    assert state.completed_phase_ids == ("PHASE-001", "PHASE-002", "PHASE-003")
    assert phase_service.calls == ["PHASE-001", "PHASE-002", "PHASE-003"]


def test_retry_requires_explicit_reexecution_and_replaces_latest_checkpoint() -> None:
    service, phase_service = make_service(
        [
            phase_result("PHASE-001", "REQ-001", PhaseExecutionStatus.FAILED),
            phase_result("PHASE-001", "REQ-001", PhaseExecutionStatus.COMPLETED),
        ]
    )
    specification, project_specification, project_plan, state = start_state(service)
    awaiting = service.execute_current_phase(
        state, specification, project_specification, project_plan
    )

    retry = service.decide_current_phase(
        awaiting, project_plan, CheckpointDecision.RETRY
    )

    assert retry.status is ProjectExecutionStatus.RETRY_REQUESTED
    assert retry.current_phase_id == "PHASE-001"
    assert phase_service.calls == ["PHASE-001"]
    rerun = service.execute_current_phase(
        retry, specification, project_specification, project_plan
    )
    assert rerun.status is ProjectExecutionStatus.AWAITING_CHECKPOINT
    assert rerun.phase_records[0].attempt_count == 2
    assert rerun.phase_records[0].checkpoint is not None
    assert rerun.phase_records[0].checkpoint.decision is None
    assert phase_service.calls == ["PHASE-001", "PHASE-001"]


def test_request_changes_requires_explicit_reexecution() -> None:
    service, phase_service = make_service(
        [
            phase_result("PHASE-001", "REQ-001", PhaseExecutionStatus.COMPLETED),
            phase_result("PHASE-001", "REQ-001", PhaseExecutionStatus.COMPLETED),
        ]
    )
    specification, project_specification, project_plan, state = start_state(service)
    awaiting = service.execute_current_phase(
        state, specification, project_specification, project_plan
    )

    revision = service.decide_current_phase(
        awaiting, project_plan, CheckpointDecision.REQUEST_CHANGES
    )

    assert revision.status is ProjectExecutionStatus.REVISION_REQUESTED
    assert phase_service.calls == ["PHASE-001"]
    rerun = service.execute_current_phase(
        revision, specification, project_specification, project_plan
    )
    assert rerun.phase_records[0].attempt_count == 2


def test_stop_preserves_note_and_prevents_future_execution() -> None:
    service, _ = make_service(
        [phase_result("PHASE-001", "REQ-001", PhaseExecutionStatus.UNKNOWN)]
    )
    specification, project_specification, project_plan, state = start_state(service)
    awaiting = service.execute_current_phase(
        state, specification, project_specification, project_plan
    )

    stopped = service.decide_current_phase(
        awaiting, project_plan, CheckpointDecision.STOP, note="Pause project"
    )

    assert stopped.status is ProjectExecutionStatus.STOPPED
    assert stopped.stopped_reason == "Pause project"
    with pytest.raises(ValueError, match="does not allow"):
        service.execute_current_phase(
            stopped, specification, project_specification, project_plan
        )


def test_invalid_lifecycle_and_dependency_state_are_rejected() -> None:
    service, _ = make_service([])
    specification, project_specification, project_plan, state = start_state(service)

    with pytest.raises(ValueError, match="awaiting checkpoint"):
        service.decide_current_phase(state, project_plan, CheckpointDecision.STOP)

    invalid_dependency_state = state.model_copy(
        update={"current_phase_id": "PHASE-002"}
    )
    with pytest.raises(ValueError, match="dependencies are not approved"):
        service.execute_current_phase(
            invalid_dependency_state,
            specification,
            project_specification,
            project_plan,
        )

    invalid_records = state.model_copy(
        update={"phase_records": state.phase_records[:2]}
    )
    with pytest.raises(ValueError, match="must match"):
        service.execute_current_phase(
            invalid_records, specification, project_specification, project_plan
        )


@pytest.mark.parametrize(
    "status",
    [PhaseExecutionStatus.FAILED, PhaseExecutionStatus.UNKNOWN],
)
def test_orchestrator_rejects_approval_of_unresolved_phase(
    status: PhaseExecutionStatus,
) -> None:
    service, _ = make_service([phase_result("PHASE-001", "REQ-001", status)])
    specification, project_specification, project_plan, state = start_state(service)
    awaiting = service.execute_current_phase(
        state, specification, project_specification, project_plan
    )

    with pytest.raises(ValueError, match="Only a completed phase"):
        service.decide_current_phase(awaiting, project_plan, CheckpointDecision.APPROVE)


def test_state_rejects_unknown_current_phase_and_duplicate_references() -> None:
    with pytest.raises(ValidationError, match="Current phase"):
        ProjectExecutionState(
            project_title="x",
            status=ProjectExecutionStatus.READY,
            current_phase_id="PHASE-999",
            phase_records=(),
        )
    with pytest.raises(ValidationError, match="record IDs must be unique"):
        ProjectExecutionState(
            project_title="x",
            status=ProjectExecutionStatus.READY,
            current_phase_id="PHASE-001",
            phase_records=(
                PhaseExecutionRecord(phase_id="PHASE-001"),
                PhaseExecutionRecord(phase_id="PHASE-001"),
            ),
        )
    with pytest.raises(ValidationError, match="Completed phase IDs must be unique"):
        ProjectExecutionState(
            project_title="x",
            status=ProjectExecutionStatus.READY,
            current_phase_id="PHASE-001",
            phase_records=(PhaseExecutionRecord(phase_id="PHASE-001"),),
            completed_phase_ids=("PHASE-001", "PHASE-001"),
        )
