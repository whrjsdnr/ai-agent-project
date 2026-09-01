"""Tests for the agent execution loop."""

from collections.abc import Sequence

from ai_agent_project.agent.service import AgentService
from ai_agent_project.agent.state import AgentMessage, AgentStatus, ToolCall
from ai_agent_project.llm.base import LLMResponse
from ai_agent_project.tools.calculator import CalculatorTool
from ai_agent_project.tools.registry import ToolRegistry


class FakeLLMClient:
    """Return predefined responses without calling an external LLM."""

    def __init__(self, responses: Sequence[LLMResponse]) -> None:
        self._responses = list(responses)
        self.requests: list[list[AgentMessage]] = []

    def complete(self, messages: list[AgentMessage], tools: list[object]) -> LLMResponse:
        del tools
        self.requests.append(list(messages))
        return self._responses.pop(0)


def make_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(CalculatorTool())
    return registry


def test_agent_completes_with_a_final_answer() -> None:
    service = AgentService(FakeLLMClient([LLMResponse(final_answer="Hello")]), make_registry())

    state = service.run("Say hello")

    assert state.status is AgentStatus.COMPLETED
    assert state.final_answer == "Hello"
    assert state.error is None
    assert state.tool_calls == []


def test_agent_executes_tool_then_completes() -> None:
    llm = FakeLLMClient(
        [
            LLMResponse(
                tool_call=ToolCall(
                    name="calculator",
                    arguments={"operation": "add", "a": 2, "b": 3},
                )
            ),
            LLMResponse(final_answer="The result is 5."),
        ]
    )
    service = AgentService(llm, make_registry())

    state = service.run("What is 2 plus 3?")

    assert state.status is AgentStatus.COMPLETED
    assert state.final_answer == "The result is 5."
    assert [call.name for call in state.tool_calls] == ["calculator"]
    assert '"result":5' in llm.requests[1][-1].content


def test_agent_fails_for_unknown_tool() -> None:
    service = AgentService(
        FakeLLMClient([LLMResponse(tool_call=ToolCall(name="missing"))]),
        make_registry(),
    )

    state = service.run("Use a missing tool")

    assert state.status is AgentStatus.FAILED
    assert state.error == "Tool not found: missing"


def test_agent_fails_when_tool_call_limit_is_exceeded() -> None:
    tool_call = LLMResponse(
        tool_call=ToolCall(
            name="calculator",
            arguments={"operation": "add", "a": 1, "b": 1},
        )
    )
    service = AgentService(FakeLLMClient([tool_call, tool_call]), make_registry(), max_tool_calls=1)

    state = service.run("Keep calculating")

    assert state.status is AgentStatus.FAILED
    assert state.error == "Maximum tool call limit (1) exceeded"
