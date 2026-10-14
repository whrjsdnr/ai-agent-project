"""Provider-neutral phase progress summaries and checkpoint decisions."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from ai_agent_project.agent.acceptance import (
    AcceptanceReport,
    AcceptanceStatus,
    RequirementValidationResult,
)
from ai_agent_project.agent.phase_execution import (
    PhaseExecutionResult,
    PhaseExecutionStatus,
)
from ai_agent_project.agent.project import ProjectPhase
from ai_agent_project.agent.state import AgentStatus


class CheckpointDecision(StrEnum):
    """A user or caller decision after reviewing a phase result."""

    APPROVE = "approve"
    REQUEST_CHANGES = "request_changes"
    RETRY = "retry"
    STOP = "stop"


class CheckpointStatus(StrEnum):
    """Lifecycle state of a phase checkpoint."""

    AWAITING_DECISION = "awaiting_decision"
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"
    RETRY_REQUESTED = "retry_requested"
    STOPPED = "stopped"


class NextAction(StrEnum):
    """A future action recommendation; this module never executes it."""

    ADVANCE = "advance"
    REVISE = "revise"
    RETRY = "retry"
    STOP = "stop"
    BLOCKED = "blocked"


class PhaseProgressReport(BaseModel):
    """Deterministic progress view derived from evidence-backed phase output."""

    model_config = ConfigDict(frozen=True)

    phase_id: str
    phase_title: str
    execution_status: PhaseExecutionStatus
    requirement_ids: tuple[str, ...]
    task_ids: tuple[str, ...]
    passed_requirement_ids: tuple[str, ...]
    failed_requirement_ids: tuple[str, ...]
    unknown_requirement_ids: tuple[str, ...]
    repair_attempt_count: int
    summary: str
    blockers: tuple[str, ...] = ()
    recommended_decisions: tuple[CheckpointDecision, ...] = ()


class PhaseCheckpoint(BaseModel):
    """An immutable manual-decision boundary for one completed phase execution."""

    model_config = ConfigDict(frozen=True)

    phase_id: str
    execution_status: PhaseExecutionStatus
    status: CheckpointStatus
    decision: CheckpointDecision | None = None
    note: str | None = None
    next_action: NextAction


class ProgressReporter:
    """Build a stable, non-LLM progress report for a selected phase."""

    def build(
        self,
        phase: ProjectPhase,
        result: PhaseExecutionResult,
    ) -> PhaseProgressReport:
        """Classify phase requirements using only acceptance report evidence."""
        if result.phase_id != phase.id:
            raise ValueError(
                "PhaseExecutionResult does not belong to the supplied phase"
            )

        statuses = {
            requirement.requirement_id: requirement.status
            for requirement in result.acceptance_report.requirements
        }
        passed = tuple(
            requirement_id
            for requirement_id in phase.requirement_ids
            if statuses.get(requirement_id) is AcceptanceStatus.PASSED
        )
        failed = tuple(
            requirement_id
            for requirement_id in phase.requirement_ids
            if statuses.get(requirement_id) is AcceptanceStatus.FAILED
        )
        unknown = tuple(
            requirement_id
            for requirement_id in phase.requirement_ids
            if statuses.get(requirement_id) is not AcceptanceStatus.PASSED
            and statuses.get(requirement_id) is not AcceptanceStatus.FAILED
        )
        blockers = _build_blockers(phase, result, result.acceptance_report)
        return PhaseProgressReport(
            phase_id=phase.id,
            phase_title=phase.title,
            execution_status=result.status,
            requirement_ids=phase.requirement_ids,
            task_ids=phase.task_ids,
            passed_requirement_ids=passed,
            failed_requirement_ids=failed,
            unknown_requirement_ids=unknown,
            repair_attempt_count=len(result.repair_attempts),
            summary=_summary(
                phase.id, result.status, len(passed), len(failed), len(unknown)
            ),
            blockers=blockers,
            recommended_decisions=_recommended_decisions(result.status),
        )


class PhaseCheckpointService:
    """Create immutable decision records without triggering project actions."""

    def create(
        self,
        phase: ProjectPhase,
        result: PhaseExecutionResult,
        report: PhaseProgressReport,
    ) -> PhaseCheckpoint:
        """Create an awaiting-decision checkpoint for the supplied phase result."""
        if result.phase_id != phase.id or report.phase_id != phase.id:
            raise ValueError("Phase, result, and report must refer to the same phase")
        if report.execution_status is not result.status:
            raise ValueError(
                "Progress report does not match the phase execution status"
            )
        return PhaseCheckpoint(
            phase_id=phase.id,
            execution_status=result.status,
            status=CheckpointStatus.AWAITING_DECISION,
            next_action=NextAction.BLOCKED,
        )

    def decide(
        self,
        checkpoint: PhaseCheckpoint,
        decision: CheckpointDecision,
        note: str | None = None,
    ) -> PhaseCheckpoint:
        """Return a new checkpoint containing a valid decision-to-action mapping."""
        if checkpoint.decision is not None:
            raise ValueError("A checkpoint with a decision cannot be decided again")
        status, next_action = _decision_outcome(checkpoint.execution_status, decision)
        return PhaseCheckpoint(
            phase_id=checkpoint.phase_id,
            execution_status=checkpoint.execution_status,
            status=status,
            decision=decision,
            note=note,
            next_action=next_action,
        )


def _build_blockers(
    phase: ProjectPhase,
    result: PhaseExecutionResult,
    report: AcceptanceReport,
) -> tuple[str, ...]:
    blockers: list[str] = []
    if result.agent_run.status is AgentStatus.FAILED:
        if result.agent_run.error:
            blockers.append(f"Agent execution failed: {result.agent_run.error}")
        else:
            blockers.append("Agent execution failed.")

    results_by_requirement = {
        requirement.requirement_id: requirement for requirement in report.requirements
    }
    for requirement_id in phase.requirement_ids:
        requirement = results_by_requirement.get(requirement_id)
        if requirement is None:
            blockers.append(f"{requirement_id}: acceptance validation is unresolved.")
            continue
        if requirement.status is AcceptanceStatus.FAILED:
            blockers.extend(_failed_blockers(requirement_id, requirement))
        elif requirement.status is AcceptanceStatus.UNKNOWN:
            blockers.extend(_unknown_blockers(requirement_id, requirement))
    return tuple(_stable_unique(blockers))


def _failed_blockers(
    requirement_id: str,
    requirement: RequirementValidationResult,
) -> list[str]:
    evidence = requirement.evidence
    notes = requirement.notes
    if evidence:
        return [f"{requirement_id}: {item}" for item in evidence]
    if notes:
        return [f"{requirement_id}: {notes}"]
    return [f"{requirement_id}: acceptance validation failed."]


def _unknown_blockers(
    requirement_id: str,
    requirement: RequirementValidationResult,
) -> list[str]:
    blockers = [
        f"{requirement_id}: acceptance criterion unresolved: {criterion.criterion}"
        for criterion in requirement.criteria
        if criterion.status is AcceptanceStatus.UNKNOWN
    ]
    if blockers:
        return blockers
    evidence = requirement.evidence
    notes = requirement.notes
    if evidence:
        return [f"{requirement_id}: {item}" for item in evidence]
    if notes:
        return [f"{requirement_id}: {notes}"]
    return [f"{requirement_id}: acceptance validation is unresolved."]


def _summary(
    phase_id: str,
    status: PhaseExecutionStatus,
    passed: int,
    failed: int,
    unknown: int,
) -> str:
    total = passed + failed + unknown
    if status is PhaseExecutionStatus.COMPLETED:
        return f"Phase {phase_id} completed: {passed}/{total} requirements passed."
    if status is PhaseExecutionStatus.FAILED:
        return f"Phase {phase_id} failed: {failed} failed, {passed} passed."
    return f"Phase {phase_id} unresolved: {unknown} unknown, {passed} passed."


def _recommended_decisions(
    status: PhaseExecutionStatus,
) -> tuple[CheckpointDecision, ...]:
    if status is PhaseExecutionStatus.COMPLETED:
        return (CheckpointDecision.APPROVE, CheckpointDecision.REQUEST_CHANGES)
    if status is PhaseExecutionStatus.FAILED:
        return (
            CheckpointDecision.RETRY,
            CheckpointDecision.REQUEST_CHANGES,
            CheckpointDecision.STOP,
        )
    return (
        CheckpointDecision.REQUEST_CHANGES,
        CheckpointDecision.RETRY,
        CheckpointDecision.STOP,
    )


def _decision_outcome(
    execution_status: PhaseExecutionStatus,
    decision: CheckpointDecision,
) -> tuple[CheckpointStatus, NextAction]:
    if decision is CheckpointDecision.APPROVE:
        if execution_status is not PhaseExecutionStatus.COMPLETED:
            raise ValueError("Only a completed phase can be approved")
        return CheckpointStatus.APPROVED, NextAction.ADVANCE
    if decision is CheckpointDecision.REQUEST_CHANGES:
        return CheckpointStatus.CHANGES_REQUESTED, NextAction.REVISE
    if decision is CheckpointDecision.RETRY:
        if execution_status not in {
            PhaseExecutionStatus.FAILED,
            PhaseExecutionStatus.UNKNOWN,
        }:
            raise ValueError("Only failed or unknown phases can be retried")
        return CheckpointStatus.RETRY_REQUESTED, NextAction.RETRY
    return CheckpointStatus.STOPPED, NextAction.STOP


def _stable_unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
