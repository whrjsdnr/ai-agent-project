"""Interfaces shared by LLM provider implementations."""

from typing import Protocol

from pydantic import BaseModel

from ai_agent_project.agent.state import AgentMessage, ToolCall
from ai_agent_project.tools.base import ToolDefinition


class LLMResponse(BaseModel):
    """Either a final answer or one requested tool call from an LLM."""

    final_answer: str | None = None
    tool_call: ToolCall | None = None


class LLMClient(Protocol):
    """A provider-independent LLM client used by the agent."""

    def complete(
        self,
        messages: list[AgentMessage],
        tools: list[ToolDefinition],
    ) -> LLMResponse:
        """Return the next LLM response for the supplied conversation."""
        ...
