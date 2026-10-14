"""Read-only execution outcome classification, never workflow recovery actions."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from ai_agent_project.agent.execution_event_store import (
    ExecutionEventError,
    FileExecutionEventStore,
)
from ai_agent_project.agent.execution_events import PublicExecutionEvent


class ExecutionRecoveryRequiredError(ExecutionEventError):
    """An unresolved attempt must not be silently repeated."""


class AttemptRecovery(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    attempt_id: str
    phase_id: str | None
    status: Literal["Active", "Finished", "Failed", "Interrupted", "Outcome Unknown"]
    last_event: PublicExecutionEvent
    message: str


class ExecutionRecovery(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    attempts: tuple[AttemptRecovery, ...]
    blocks_execution: bool
    message: str


def inspect_recovery(
    store: FileExecutionEventStore | None,
    run_id: str,
    *,
    activity_override: str | None = None,
) -> ExecutionRecovery:
    if store is None:
        return ExecutionRecovery(
            attempts=(),
            blocks_execution=False,
            message="No recorded execution evidence.",
        )
    recorded = sorted(store.recovery_events(run_id), key=lambda event: event.sequence)
    groups: dict[str, list[PublicExecutionEvent]] = {}
    for event in recorded:
        groups.setdefault(event.attempt_id, []).append(event)
    execution_groups = [
        events
        for events in groups.values()
        if any(
            event.kind == "phase_started"
            or event.kind == "snapshot_saved"
            and event.snapshot_stage == "before"
            for event in events
        )
    ]
    newest = max(
        execution_groups,
        key=lambda events: max(event.sequence for event in events),
        default=[],
    )
    activity = activity_override or store.run_activity(run_id)
    result = []
    for events in execution_groups:
        last = max(events, key=lambda event: event.sequence)
        terminals = [
            event
            for event in events
            if event.kind in {"phase_finished", "phase_failed"}
        ]
        started = any(event.kind == "phase_started" for event in events)
        if terminals:
            terminal = max(terminals, key=lambda event: event.sequence)
            status = "Finished" if terminal.kind == "phase_finished" else "Failed"
            message = "Terminal workflow evidence exists. This does not assert that all tools or tests succeeded."
        elif activity == "active" and events is newest:
            status = "Active"
            message = (
                "An active execution lease exists; workflow outcome is not yet known."
            )
        elif started and activity == "inactive":
            status = "Interrupted"
            message = "Phase start was recorded, no terminal event or active lease exists. Outcome Unknown."
        else:
            status = "Outcome Unknown"
            message = (
                "Start/end evidence or execution lease could not establish an outcome."
            )
        result.append(
            AttemptRecovery(
                attempt_id=last.attempt_id,
                phase_id=last.phase_id,
                status=status,
                last_event=last,
                message=message,
            )
        )
    result.sort(key=lambda attempt: attempt.last_event.sequence, reverse=True)
    blocked = any(
        attempt.status in {"Interrupted", "Outcome Unknown"} for attempt in result
    )
    return ExecutionRecovery(
        attempts=tuple(result),
        blocks_execution=blocked,
        message="Recovery is read-only. No retry, repair or rollback is performed."
        if result
        else "No recorded execution evidence.",
    )
