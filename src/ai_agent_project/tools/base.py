"""Interfaces and models for agent tools."""

from typing import Any, Protocol

from pydantic import BaseModel, Field


class ToolDefinition(BaseModel):
    """Describes a tool for an LLM without exposing implementation details."""

    name: str
    description: str
    input_schema: dict[str, Any]


class ToolResult(BaseModel):
    """The structured result returned by a tool execution."""

    success: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class Tool(Protocol):
    """A capability that can be offered to an LLM-driven agent."""

    name: str
    description: str
    input_schema: type[BaseModel]

    def execute(self, arguments: dict[str, object]) -> ToolResult:
        """Validate and execute the tool with LLM-provided arguments."""
        ...

    def definition(self) -> ToolDefinition:
        """Return the tool metadata exposed to an LLM."""
        ...
