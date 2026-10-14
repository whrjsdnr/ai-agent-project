"""Tests for deterministic phase progress reports and checkpoints."""

import pytest
from pydantic import ValidationError

from ai_agent_project.agent.acceptance import (
    AcceptanceReport,
    AcceptanceStatus,
    RequirementValidationResult,
)
from ai_agent_project.agent.checkpoint import (
    CheckpointDecision,
    CheckpointStatus,
    NextAction,
    PhaseCheckpointService,
    PhaseProgressReport,
    ProgressReporter,
)
from ai_agent_project.agent.coding_service import RepairAttempt
from ai_agent_project.agent.phase_execution import (
    PhaseExecutionResult,
    PhaseExecutionStatus,
)
from ai_agent_project.agent.project import ProjectPhase
from ai_agent_project.agent.state import AgentState, AgentStatus


def make_phase() -> ProjectPhase:
    return ProjectPhase(
        id="PHASE-001",
        title="Foundation",
        objective="Build the foundation.",
        requirement_ids=("REQ-001", "REQ-002", "REQ-003"),
        task_ids=("TASK-001", "TASK-002"),
    )


def requirement(
    requirement_id: str,
    status: AcceptanceStatus,
    *,
    evidence: list[str] | None = None,
    criterion: str | None = None,
) -> RequirementValidationResult:
    return RequirementValidationResult(
        requirement_id=requirement_id,
        status=status,
        criteria=(
            [
                {
                    "criterion": criterion,
                    "status": status,
                    "evidence": evidence or [],
                }
            ]
            if criterion
            else []
        ),
        evidence=evidence or [],
    )


def make_result(
    status: PhaseExecutionStatus,
    requirements: list[RequirementValidationResult],
    *,
    agent_state: AgentState | None = None,
    repair_attempts: tuple[RepairAttempt, ...] = (),
) -> PhaseExecutionResult:
    return PhaseExecutionResult(
        phase_id="PHASE-001",
        status=status,
        requirement_ids=("REQ-001", "REQ-002", "REQ-003"),
        task_ids=("TASK-001", "TASK-002"),
        agent_run=agent_state or AgentState(status=AgentStatus.COMPLETED),
        acceptance_report=AcceptanceReport(requirements=requirements),
        repair_attempts=repair_attempts,
    )


def test_completed_progress_report_is_ordered_immutable_and_recommends_approval() -> (
    None
):
    phase = make_phase()
    result = make_result(
        PhaseExecutionStatus.COMPLETED,
        [
            requirement("REQ-003", AcceptanceStatus.PASSED),
            requirement("REQ-001", AcceptanceStatus.PASSED),
            requirement("REQ-002", AcceptanceStatus.PASSED),
        ],
    )

    report = ProgressReporter().build(phase, result)

    assert report.passed_requirement_ids == ("REQ-001", "REQ-002", "REQ-003")
    assert report.failed_requirement_ids == ()
    assert report.unknown_requirement_ids == ()
    assert report.blockers == ()
    assert report.summary == "Phase PHASE-001 completed: 3/3 requirements passed."
    assert CheckpointDecision.APPROVE in report.recommended_decisions
    with pytest.raises(ValidationError):
        report.summary = "changed"  # type: ignore[misc]


def test_failed_progress_report_uses_evidence_and_excludes_approval() -> None:
    result = make_result(
        PhaseExecutionStatus.FAILED,
        [
            requirement("REQ-001", AcceptanceStatus.PASSED),
            requirement(
                "REQ-002",
                AcceptanceStatus.FAILED,
                evidence=["validation command failed: uv run pytest"],
            ),
            requirement("REQ-003", AcceptanceStatus.UNKNOWN),
        ],
    )

    report = ProgressReporter().build(make_phase(), result)

    assert report.passed_requirement_ids == ("REQ-001",)
    assert report.failed_requirement_ids == ("REQ-002",)
    assert report.unknown_requirement_ids == ("REQ-003",)
    assert report.blockers == (
        "REQ-002: validation command failed: uv run pytest",
        "REQ-003: acceptance validation is unresolved.",
    )
    assert report.summary == "Phase PHASE-001 failed: 1 failed, 1 passed."
    assert CheckpointDecision.APPROVE not in report.recommended_decisions
    assert set(report.recommended_decisions) == {
        CheckpointDecision.RETRY,
        CheckpointDecision.REQUEST_CHANGES,
        CheckpointDecision.STOP,
    }


def test_unknown_progress_report_uses_unresolved_criterion_and_agent_failure() -> None:
    result = make_result(
        PhaseExecutionStatus.UNKNOWN,
        [
            requirement("REQ-001", AcceptanceStatus.PASSED),
            requirement(
                "REQ-002",
                AcceptanceStatus.UNKNOWN,
                criterion="foo() returns True",
            ),
        ],
        agent_state=AgentState(status=AgentStatus.FAILED, error="tool limit"),
    )

    report = ProgressReporter().build(make_phase(), result)

    assert report.unknown_requirement_ids == ("REQ-002", "REQ-003")
    assert report.blockers == (
        "Agent execution failed: tool limit",
        "REQ-002: acceptance criterion unresolved: foo() returns True",
        "REQ-003: acceptance validation is unresolved.",
    )
    assert report.summary == "Phase PHASE-001 unresolved: 2 unknown, 1 passed."
    assert CheckpointDecision.APPROVE not in report.recommended_decisions


def test_progress_report_counts_repair_attempts_and_rejects_mismatched_phase() -> None:
    result = make_result(
        PhaseExecutionStatus.COMPLETED,
        [
            requirement("REQ-001", AcceptanceStatus.PASSED),
            requirement("REQ-002", AcceptanceStatus.PASSED),
            requirement("REQ-003", AcceptanceStatus.PASSED),
        ],
        repair_attempts=(
            RepairAttempt(
                attempt=1,
                failed_requirement_ids=["REQ-001"],
                agent_run=AgentState(status=AgentStatus.COMPLETED),
                acceptance_report=AcceptanceReport(),
            ),
            RepairAttempt(
                attempt=2,
                failed_requirement_ids=["REQ-001"],
                agent_run=AgentState(status=AgentStatus.COMPLETED),
                acceptance_report=AcceptanceReport(),
            ),
        ),
    )
    reporter = ProgressReporter()

    assert reporter.build(make_phase(), result).repair_attempt_count == 2
    with pytest.raises(ValueError, match="does not belong"):
        reporter.build(make_phase().model_copy(update={"id": "PHASE-999"}), result)


def test_checkpoint_create_returns_awaiting_blocked_checkpoint() -> None:
    phase = make_phase()
    result = make_result(
        PhaseExecutionStatus.COMPLETED,
        [
            requirement("REQ-001", AcceptanceStatus.PASSED),
            requirement("REQ-002", AcceptanceStatus.PASSED),
            requirement("REQ-003", AcceptanceStatus.PASSED),
        ],
    )
    progress = ProgressReporter().build(phase, result)

    checkpoint = PhaseCheckpointService().create(phase, result, progress)

    assert checkpoint.status is CheckpointStatus.AWAITING_DECISION
    assert checkpoint.decision is None
    assert checkpoint.next_action is NextAction.BLOCKED


@pytest.mark.parametrize(
    ("status", "decision", "expected_status", "expected_action"),
    [
        (
            PhaseExecutionStatus.COMPLETED,
            CheckpointDecision.APPROVE,
            CheckpointStatus.APPROVED,
            NextAction.ADVANCE,
        ),
        (
            PhaseExecutionStatus.COMPLETED,
            CheckpointDecision.REQUEST_CHANGES,
            CheckpointStatus.CHANGES_REQUESTED,
            NextAction.REVISE,
        ),
        (
            PhaseExecutionStatus.FAILED,
            CheckpointDecision.REQUEST_CHANGES,
            CheckpointStatus.CHANGES_REQUESTED,
            NextAction.REVISE,
        ),
        (
            PhaseExecutionStatus.UNKNOWN,
            CheckpointDecision.REQUEST_CHANGES,
            CheckpointStatus.CHANGES_REQUESTED,
            NextAction.REVISE,
        ),
        (
            PhaseExecutionStatus.FAILED,
            CheckpointDecision.RETRY,
            CheckpointStatus.RETRY_REQUESTED,
            NextAction.RETRY,
        ),
        (
            PhaseExecutionStatus.UNKNOWN,
            CheckpointDecision.RETRY,
            CheckpointStatus.RETRY_REQUESTED,
            NextAction.RETRY,
        ),
        (
            PhaseExecutionStatus.COMPLETED,
            CheckpointDecision.STOP,
            CheckpointStatus.STOPPED,
            NextAction.STOP,
        ),
        (
            PhaseExecutionStatus.FAILED,
            CheckpointDecision.STOP,
            CheckpointStatus.STOPPED,
            NextAction.STOP,
        ),
        (
            PhaseExecutionStatus.UNKNOWN,
            CheckpointDecision.STOP,
            CheckpointStatus.STOPPED,
            NextAction.STOP,
        ),
    ],
)
def test_checkpoint_decision_mappings(
    status: PhaseExecutionStatus,
    decision: CheckpointDecision,
    expected_status: CheckpointStatus,
    expected_action: NextAction,
) -> None:
    phase = make_phase()
    requirements = [
        requirement(requirement_id, AcceptanceStatus.PASSED)
        for requirement_id in phase.requirement_ids
    ]
    result = make_result(status, requirements)
    progress = ProgressReporter().build(phase, result)
    service = PhaseCheckpointService()
    initial = service.create(phase, result, progress)

    decided = service.decide(initial, decision, note="reviewed")

    assert decided.status is expected_status
    assert decided.next_action is expected_action
    assert decided.note == "reviewed"
    assert initial.decision is None
    with pytest.raises(ValueError, match="cannot be decided again"):
        service.decide(decided, CheckpointDecision.STOP)


@pytest.mark.parametrize(
    "status",
    [PhaseExecutionStatus.FAILED, PhaseExecutionStatus.UNKNOWN],
)
def test_checkpoint_rejects_approval_of_unresolved_work(
    status: PhaseExecutionStatus,
) -> None:
    phase = make_phase()
    result = make_result(status, [])
    progress = ProgressReporter().build(phase, result)
    checkpoint = PhaseCheckpointService().create(phase, result, progress)

    with pytest.raises(ValueError, match="Only a completed phase"):
        PhaseCheckpointService().decide(checkpoint, CheckpointDecision.APPROVE)


def test_checkpoint_rejects_retry_for_completed_phase() -> None:
    phase = make_phase()
    result = make_result(PhaseExecutionStatus.COMPLETED, [])
    progress = ProgressReporter().build(phase, result)
    checkpoint = PhaseCheckpointService().create(phase, result, progress)

    with pytest.raises(ValueError, match="Only failed or unknown"):
        PhaseCheckpointService().decide(checkpoint, CheckpointDecision.RETRY)


def test_checkpoint_rejects_mismatched_progress_report() -> None:
    phase = make_phase()
    result = make_result(PhaseExecutionStatus.COMPLETED, [])
    progress = PhaseProgressReport(
        phase_id=phase.id,
        phase_title=phase.title,
        execution_status=PhaseExecutionStatus.FAILED,
        requirement_ids=phase.requirement_ids,
        task_ids=phase.task_ids,
        passed_requirement_ids=(),
        failed_requirement_ids=(),
        unknown_requirement_ids=phase.requirement_ids,
        repair_attempt_count=0,
        summary="mismatch",
    )

    with pytest.raises(ValueError, match="does not match"):
        PhaseCheckpointService().create(phase, result, progress)
