"""Provider-neutral, caller-driven orchestration across project phases."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_agent_project.agent.checkpoint import (
    CheckpointDecision,
    NextAction,
    PhaseCheckpoint,
    PhaseCheckpointService,
    PhaseProgressReport,
    ProgressReporter,
)
from ai_agent_project.agent.phase_execution import (
    PhaseExecutionResult,
    PhaseExecutionService,
)
from ai_agent_project.agent.project import (
    ProjectPhase,
    ProjectPlan,
    ProjectSpecification,
)
from ai_agent_project.agent.specification import Specification


class ProjectExecutionStatus(StrEnum):
    """Caller-controlled lifecycle of an in-memory project execution."""

    AWAITING_PLAN_APPROVAL = "awaiting_plan_approval"
    READY = "ready"
    RUNNING = "running"
    AWAITING_CHECKPOINT = "awaiting_checkpoint"
    REVISION_REQUESTED = "revision_requested"
    RETRY_REQUESTED = "retry_requested"
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"


class PhaseExecutionRecord(BaseModel):
    """The latest execution, report, and checkpoint for one project phase."""

    model_config = ConfigDict(frozen=True)

    phase_id: str
    execution: PhaseExecutionResult | None = None
    progress_report: PhaseProgressReport | None = None
    checkpoint: PhaseCheckpoint | None = None
    attempt_count: int = Field(default=0, ge=0)


class ProjectExecutionState(BaseModel):
    """Immutable, non-persistent state for a caller-driven project lifecycle."""

    model_config = ConfigDict(frozen=True)

    project_title: str
    status: ProjectExecutionStatus
    current_phase_id: str | None
    phase_records: tuple[PhaseExecutionRecord, ...]
    completed_phase_ids: tuple[str, ...] = ()
    stopped_reason: str | None = None

    @model_validator(mode="after")
    def validate_references(self) -> "ProjectExecutionState":
        record_ids = [record.phase_id for record in self.phase_records]
        if len(record_ids) != len(set(record_ids)):
            raise ValueError("Phase execution record IDs must be unique")
        if len(self.completed_phase_ids) != len(set(self.completed_phase_ids)):
            raise ValueError("Completed phase IDs must be unique")
        known_ids = set(record_ids)
        if self.current_phase_id is not None and self.current_phase_id not in known_ids:
            raise ValueError("Current phase ID must reference a phase execution record")
        if not set(self.completed_phase_ids) <= known_ids:
            raise ValueError(
                "Completed phase IDs must reference phase execution records"
            )
        return self


class ProjectExecutionService:
    """Coordinate explicit phase execution and checkpoint decisions only."""

    def __init__(
        self,
        phase_execution_service: PhaseExecutionService,
        progress_reporter: ProgressReporter,
        checkpoint_service: PhaseCheckpointService,
    ) -> None:
        self._phase_execution_service = phase_execution_service
        self._progress_reporter = progress_reporter
        self._checkpoint_service = checkpoint_service

    def start(
        self,
        specification: Specification,
        project_specification: ProjectSpecification,
        project_plan: ProjectPlan,
    ) -> ProjectExecutionState:
        """Return a ready state without running a phase."""
        del specification
        project_plan.validate_against(project_specification)
        if not project_plan.phases:
            raise ValueError("ProjectPlan must contain at least one phase")
        records = tuple(
            PhaseExecutionRecord(phase_id=phase.id) for phase in project_plan.phases
        )
        state = ProjectExecutionState(
            project_title=project_plan.project_title,
            status=ProjectExecutionStatus.READY,
            current_phase_id=None,
            phase_records=records,
        )
        phase = _next_ready_phase(project_plan, state.completed_phase_ids)
        if phase is None:
            raise ValueError("ProjectPlan has no dependency-ready phase")
        return state.model_copy(update={"current_phase_id": phase.id})

    def execute_current_phase(
        self,
        state: ProjectExecutionState,
        specification: Specification,
        project_specification: ProjectSpecification,
        project_plan: ProjectPlan,
    ) -> ProjectExecutionState:
        """Execute exactly one selected phase, then await a checkpoint decision."""
        if state.status not in {
            ProjectExecutionStatus.READY,
            ProjectExecutionStatus.RETRY_REQUESTED,
            ProjectExecutionStatus.REVISION_REQUESTED,
        }:
            raise ValueError("Current project state does not allow phase execution")
        _validate_state_for_plan(state, project_plan, project_specification)
        phase = _current_phase(state, project_plan)
        if not set(phase.depends_on) <= set(state.completed_phase_ids):
            raise ValueError("Current phase dependencies are not approved")

        result = self._phase_execution_service.execute(
            specification,
            project_specification,
            project_plan,
            phase.id,
        )
        progress_report = self._progress_reporter.build(phase, result)
        checkpoint = self._checkpoint_service.create(phase, result, progress_report)
        record = _record_for_phase(state, phase.id)
        updated_record = record.model_copy(
            update={
                "execution": result,
                "progress_report": progress_report,
                "checkpoint": checkpoint,
                "attempt_count": record.attempt_count + 1,
            }
        )
        return state.model_copy(
            update={
                "status": ProjectExecutionStatus.AWAITING_CHECKPOINT,
                "phase_records": _replace_record(state.phase_records, updated_record),
            }
        )

    def decide_current_phase(
        self,
        state: ProjectExecutionState,
        project_plan: ProjectPlan,
        decision: CheckpointDecision,
        note: str | None = None,
    ) -> ProjectExecutionState:
        """Record a decision; advancing only makes a later phase ready."""
        if state.status is not ProjectExecutionStatus.AWAITING_CHECKPOINT:
            raise ValueError("A decision requires a project awaiting checkpoint")
        _validate_state_records(state, project_plan)
        phase = _current_phase(state, project_plan)
        record = _record_for_phase(state, phase.id)
        if (
            record.execution is None
            or record.progress_report is None
            or record.checkpoint is None
            or record.checkpoint.decision is not None
        ):
            raise ValueError("Current phase has no undecided execution checkpoint")

        checkpoint = self._checkpoint_service.decide(record.checkpoint, decision, note)
        updated_record = record.model_copy(update={"checkpoint": checkpoint})
        records = _replace_record(state.phase_records, updated_record)

        if checkpoint.next_action is NextAction.ADVANCE:
            completed = (*state.completed_phase_ids, phase.id)
            next_phase = _next_ready_phase(project_plan, completed)
            if next_phase is not None:
                return state.model_copy(
                    update={
                        "status": ProjectExecutionStatus.READY,
                        "current_phase_id": next_phase.id,
                        "phase_records": records,
                        "completed_phase_ids": completed,
                    }
                )
            if len(completed) == len(project_plan.phases):
                return state.model_copy(
                    update={
                        "status": ProjectExecutionStatus.COMPLETED,
                        "current_phase_id": None,
                        "phase_records": records,
                        "completed_phase_ids": completed,
                    }
                )
            raise ValueError("No dependency-ready phase is available after approval")
        if checkpoint.next_action is NextAction.RETRY:
            return state.model_copy(
                update={
                    "status": ProjectExecutionStatus.RETRY_REQUESTED,
                    "phase_records": records,
                }
            )
        if checkpoint.next_action is NextAction.REVISE:
            return state.model_copy(
                update={
                    "status": ProjectExecutionStatus.REVISION_REQUESTED,
                    "phase_records": records,
                }
            )
        if checkpoint.next_action is NextAction.STOP:
            return state.model_copy(
                update={
                    "status": ProjectExecutionStatus.STOPPED,
                    "phase_records": records,
                    "stopped_reason": note,
                }
            )
        raise ValueError("A checkpoint decision cannot leave the next action blocked")


def _validate_state_for_plan(
    state: ProjectExecutionState,
    project_plan: ProjectPlan,
    project_specification: ProjectSpecification,
) -> None:
    project_plan.validate_against(project_specification)
    _validate_state_records(state, project_plan)


def _validate_state_records(
    state: ProjectExecutionState,
    project_plan: ProjectPlan,
) -> None:
    plan_phase_ids = tuple(phase.id for phase in project_plan.phases)
    record_ids = tuple(record.phase_id for record in state.phase_records)
    if record_ids != plan_phase_ids:
        raise ValueError("Project execution records must match ProjectPlan phase order")


def _current_phase(
    state: ProjectExecutionState,
    project_plan: ProjectPlan,
) -> ProjectPhase:
    if state.current_phase_id is None:
        raise ValueError("Project execution has no current phase")
    for phase in project_plan.phases:
        if phase.id == state.current_phase_id:
            return phase
    raise ValueError("Current phase is absent from ProjectPlan")


def _next_ready_phase(
    project_plan: ProjectPlan,
    completed_phase_ids: tuple[str, ...],
) -> ProjectPhase | None:
    completed = set(completed_phase_ids)
    return next(
        (
            phase
            for phase in project_plan.phases
            if phase.id not in completed and set(phase.depends_on) <= completed
        ),
        None,
    )


def _record_for_phase(
    state: ProjectExecutionState,
    phase_id: str,
) -> PhaseExecutionRecord:
    for record in state.phase_records:
        if record.phase_id == phase_id:
            return record
    raise ValueError("Current phase has no execution record")


def _replace_record(
    records: tuple[PhaseExecutionRecord, ...],
    updated_record: PhaseExecutionRecord,
) -> tuple[PhaseExecutionRecord, ...]:
    return tuple(
        updated_record if record.phase_id == updated_record.phase_id else record
        for record in records
    )
