"""Typed public events and thread-local execution context, never AgentState."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

EventKind = Literal[
    "phase_started",
    "phase_finished",
    "phase_failed",
    "agent_started",
    "agent_completed",
    "agent_failed",
    "tool_started",
    "tool_completed",
    "tool_failed",
    "file_observed",
    "observation_unavailable",
    "validation_started",
    "validation_finished",
    "validation_failed",
    "repair_started",
    "checkpoint_created",
    "checkpoint_decided",
    "plan_approved",
    "snapshot_saved",
    "snapshot_failed",
]
EventStatus = Literal[
    "running",
    "completed",
    "failed",
    "passed",
    "unknown",
    "timeout",
    "awaiting_checkpoint",
    "approved",
    "approve",
    "request_changes",
    "retry",
    "revise",
    "stop",
]


class PublicExecutionEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    phase_id: str | None
    attempt_id: str
    repair_attempt: int = Field(default=0, ge=0)
    sequence: int = Field(default=0, ge=0)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    kind: EventKind
    status: EventStatus
    tool: Literal["file", "shell", "calculator", "unknown"] | None = None
    operation_id: str | None = None
    source: Literal[
        "workflow", "agent", "tool", "validation", "workspace_observation"
    ] = "workflow"
    command: str | None = None
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    error: (
        Literal[
            "tool_failed",
            "timeout",
            "execution_failed",
            "validation_failed",
            "observation_unavailable",
            "snapshot_failed",
        ]
        | None
    ) = None
    path: str | None = None
    change: Literal["created", "modified", "deleted"] | None = None
    attribution: Literal["unattributed"] | None = None
    snapshot_id: str | None = None
    snapshot_stage: Literal["before", "tool", "after"] | None = None


class EventWriter(Protocol):
    def append(self, event: PublicExecutionEvent) -> PublicExecutionEvent: ...


@dataclass(frozen=True)
class ExecutionContext:
    writer: EventWriter
    run_id: str
    phase_id: str | None
    attempt_id: str
    workspace: Path
    secrets: tuple[str, ...] = ()
    repair_attempt: int = 0
    source: Literal[
        "workflow", "agent", "tool", "validation", "workspace_observation"
    ] = "workflow"


CURRENT_EXECUTION: ContextVar[ExecutionContext | None] = ContextVar(
    "public_execution", default=None
)


@contextmanager
def execution_context(context: ExecutionContext) -> Iterator[None]:
    token = CURRENT_EXECUTION.set(context)
    try:
        yield
    finally:
        CURRENT_EXECUTION.reset(token)


@contextmanager
def execution_stage(
    *, source=None, repair_attempt: int | None = None
) -> Iterator[None]:
    context = CURRENT_EXECUTION.get()
    if context is None:
        yield
        return
    updates = {}
    if source is not None:
        updates["source"] = source
    if repair_attempt is not None:
        updates["repair_attempt"] = repair_attempt
    with execution_context(replace(context, **updates)):
        yield


def emit(kind: EventKind, status: EventStatus, **fields: object) -> None:
    context = CURRENT_EXECUTION.get()
    if context is None:
        return
    event = PublicExecutionEvent.model_validate(
        {
            "run_id": context.run_id,
            "phase_id": context.phase_id,
            "attempt_id": context.attempt_id,
            "repair_attempt": context.repair_attempt,
            "kind": kind,
            "status": status,
            "source": context.source,
            **fields,
        }
    )
    context.writer.append(event)
