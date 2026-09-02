"""Tests for the agent execution loop."""

import json
from collections.abc import Sequence

from ai_agent_project.agent.service import AgentService
from ai_agent_project.agent.state import AgentMessage, AgentStatus, ToolCall
from ai_agent_project.llm.base import LLMResponse
from ai_agent_project.tools.base import ToolDefinition, ToolResult
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


class FakeTool:
    """Record calls and return predefined tool results."""

    def __init__(self, name: str, results: Sequence[ToolResult]) -> None:
        self.name = name
        self._results = list(results)
        self.calls: list[dict[str, object]] = []

    def execute(self, arguments: dict[str, object]) -> ToolResult:
        self.calls.append(arguments)
        return self._results.pop(0)

    def definition(self) -> ToolDefinition:
        return ToolDefinition(name=self.name, description="Fake tool", input_schema={})


def make_fake_registry(*tools: FakeTool) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    return registry


def test_agent_completes_with_a_final_answer() -> None:
    service = AgentService(FakeLLMClient([LLMResponse(final_answer="Hello")]), make_registry())

    state = service.run("Say hello")

    assert state.status is AgentStatus.COMPLETED
    assert state.final_answer == "Hello"
    assert state.error is None
    assert state.tool_calls == []


def test_agent_preserves_provider_context_for_a_final_answer() -> None:
    context = {"input_items": [{"type": "message", "id": "msg_123"}]}
    service = AgentService(
        FakeLLMClient([LLMResponse(final_answer="Hello", provider_context=context)]),
        make_registry(),
    )

    state = service.run("Say hello")

    assert state.messages[-1].provider_context == context


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
    assert state.tool_results[0].success is True
    assert '"result":5' in llm.requests[1][-1].content


def test_agent_returns_unknown_tool_error_to_the_llm() -> None:
    llm = FakeLLMClient(
        [
            LLMResponse(tool_call=ToolCall(id="missing_1", name="missing")),
            LLMResponse(final_answer="I will use a different approach."),
        ]
    )
    service = AgentService(llm, make_registry())

    state = service.run("Use a missing tool")

    assert state.status is AgentStatus.COMPLETED
    assert state.tool_results == [ToolResult(success=False, error="Tool not found: missing")]
    assert json.loads(llm.requests[1][-1].content) == {
        "success": False,
        "data": {},
        "error": "Tool not found: missing",
    }


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


def test_agent_runs_read_write_pytest_steps_then_completes() -> None:
    file_tool = FakeTool(
        "file",
        [
            ToolResult(success=True, data={"content": "before"}),
            ToolResult(success=True, data={"path": "calculator.py"}),
        ],
    )
    shell_tool = FakeTool("shell", [ToolResult(success=True, data={"exit_code": 0})])
    llm = FakeLLMClient(
        [
            LLMResponse(
                tool_call=ToolCall(
                    id="read_1",
                    name="file",
                    arguments={"operation": "read_file", "path": "calculator.py"},
                )
            ),
            LLMResponse(
                tool_call=ToolCall(
                    id="write_1",
                    name="file",
                    arguments={"operation": "write_file", "path": "calculator.py"},
                )
            ),
            LLMResponse(
                tool_call=ToolCall(
                    id="test_1",
                    name="shell",
                    arguments={"command": "uv run pytest"},
                )
            ),
            LLMResponse(final_answer="Updated the file and tests pass."),
        ]
    )
    service = AgentService(llm, make_fake_registry(file_tool, shell_tool))

    state = service.run("Inspect, update, and test calculator.py")

    assert state.status is AgentStatus.COMPLETED
    assert state.final_answer == "Updated the file and tests pass."
    assert [call.id for call in state.tool_calls] == ["read_1", "write_1", "test_1"]
    assert [result.success for result in state.tool_results] == [True, True, True]
    assert state.iteration_count == 4
    assert json.loads(llm.requests[1][-1].content)["data"] == {"content": "before"}


def test_agent_executes_all_tool_calls_from_one_response() -> None:
    file_tool = FakeTool(
        "file",
        [
            ToolResult(success=True, data={"content": "a"}),
            ToolResult(success=True, data={"content": "b"}),
        ],
    )
    llm = FakeLLMClient(
        [
            LLMResponse(
                tool_calls=[
                    ToolCall(
                        id="read_a",
                        name="file",
                        arguments={"operation": "read_file", "path": "a.py"},
                    ),
                    ToolCall(
                        id="read_b",
                        name="file",
                        arguments={"operation": "read_file", "path": "b.py"},
                    ),
                ]
            ),
            LLMResponse(final_answer="Both files were read."),
        ]
    )
    service = AgentService(llm, make_fake_registry(file_tool))

    state = service.run("Read both files")

    assert state.status is AgentStatus.COMPLETED
    assert [call.id for call in state.tool_calls] == ["read_a", "read_b"]
    assert file_tool.calls == [
        {"operation": "read_file", "path": "a.py"},
        {"operation": "read_file", "path": "b.py"},
    ]
    tool_messages = [message for message in llm.requests[1] if message.role == "tool"]
    assert [message.tool_call_id for message in tool_messages] == ["read_a", "read_b"]


def test_agent_continues_after_a_tool_returns_failure() -> None:
    file_tool = FakeTool(
        "file",
        [
            ToolResult(success=True, data={"content": "before"}),
            ToolResult(success=True, data={"path": "calculator.py"}),
            ToolResult(success=True, data={"path": "calculator.py"}),
        ],
    )
    shell_tool = FakeTool(
        "shell",
        [
            ToolResult(success=False, data={"exit_code": 1}, error="Tests failed"),
            ToolResult(success=True, data={"exit_code": 0}),
        ],
    )
    llm = FakeLLMClient(
        [
            LLMResponse(tool_call=ToolCall(id="read", name="file")),
            LLMResponse(tool_call=ToolCall(id="write_1", name="file")),
            LLMResponse(tool_call=ToolCall(id="test_1", name="shell")),
            LLMResponse(tool_call=ToolCall(id="write_2", name="file")),
            LLMResponse(tool_call=ToolCall(id="test_2", name="shell")),
            LLMResponse(final_answer="Fixed the failing test."),
        ]
    )
    service = AgentService(llm, make_fake_registry(file_tool, shell_tool))

    state = service.run("Fix the failing test")

    assert state.status is AgentStatus.COMPLETED
    assert state.tool_results[2] == ToolResult(
        success=False,
        data={"exit_code": 1},
        error="Tests failed",
    )
    assert json.loads(llm.requests[3][-1].content) == {
        "success": False,
        "data": {"exit_code": 1},
        "error": "Tests failed",
    }
    assert state.iteration_count == 6


def test_agent_fails_when_iteration_limit_is_exceeded() -> None:
    file_tool = FakeTool(
        "file",
        [ToolResult(success=True), ToolResult(success=True)],
    )
    repeated_tool_call = LLMResponse(tool_call=ToolCall(name="file"))
    service = AgentService(
        FakeLLMClient([repeated_tool_call, repeated_tool_call]),
        make_fake_registry(file_tool),
        max_iterations=2,
    )

    state = service.run("Keep working")

    assert state.status is AgentStatus.FAILED
    assert state.error == "Maximum iteration limit (2) exceeded"
    assert state.iteration_count == 2
