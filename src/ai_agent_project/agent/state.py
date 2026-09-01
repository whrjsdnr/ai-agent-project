"""Models describing the state of an agent run."""

from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class AgentStatus(StrEnum):
    """Lifecycle states for an agent run."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ToolCall(BaseModel):
    """A request from an LLM to execute a named tool."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    arguments: dict[str, object] = Field(default_factory=dict)


class AgentMessage(BaseModel):
    """A message exchanged by the user, LLM, or a tool."""

    role: str
    content: str
    tool_call_id: str | None = None
    tool_call: ToolCall | None = None
    provider_context: dict[str, Any] | None = None


class AgentState(BaseModel):
    """Mutable state captured during a single agent run."""

    run_id: str = Field(default_factory=lambda: str(uuid4()))
    messages: list[AgentMessage] = Field(default_factory=list)
    status: AgentStatus = AgentStatus.RUNNING
    tool_calls: list[ToolCall] = Field(default_factory=list)
    error: str | None = None
    final_answer: str | None = None
