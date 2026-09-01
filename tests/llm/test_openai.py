"""Tests for the OpenAI provider without making network requests."""

from types import SimpleNamespace
from typing import Any

import pytest

from ai_agent_project.agent.state import AgentMessage, ToolCall
from ai_agent_project.llm.providers.openai import DEFAULT_MODEL, OpenAIClient
from ai_agent_project.tools.calculator import CalculatorTool


class FakeResponsesAPI:
    """Capture Responses API requests and return predefined responses."""

    def __init__(self, responses: list[object]) -> None:
        self._responses = responses
        self.requests: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> object:
        self.requests.append(kwargs)
        return self._responses.pop(0)


class FakeOpenAIAPIClient:
    """Expose a fake Responses API in the same shape as the OpenAI client."""

    def __init__(self, responses: list[object]) -> None:
        self.responses = FakeResponsesAPI(responses)


def test_openai_client_converts_calculator_tool_and_function_call() -> None:
    response = SimpleNamespace(
        output=[
            SimpleNamespace(
                type="function_call",
                call_id="call_123",
                name="calculator",
                arguments='{"operation":"add","a":10,"b":20}',
            )
        ],
        output_text="",
    )
    fake_client = FakeOpenAIAPIClient([response])
    provider = OpenAIClient(client=fake_client, model="test-model")

    result = provider.complete(
        [AgentMessage(role="user", content="Calculate 10 + 20")],
        [CalculatorTool().definition()],
    )

    assert result.tool_call == ToolCall(
        id="call_123",
        name="calculator",
        arguments={"operation": "add", "a": 10, "b": 20},
    )
    request = fake_client.responses.requests[0]
    assert request["model"] == "test-model"
    assert request["tools"] == [
        {
            "type": "function",
            "name": "calculator",
            "description": "Perform addition, subtraction, multiplication, or division.",
            "parameters": CalculatorTool().input_schema.model_json_schema(),
            "strict": False,
        }
    ]


def test_openai_client_converts_tool_result_to_function_call_output() -> None:
    response = SimpleNamespace(output=[], output_text="The result is 30.")
    fake_client = FakeOpenAIAPIClient([response])
    provider = OpenAIClient(client=fake_client, model="test-model")
    tool_call = ToolCall(
        id="call_123",
        name="calculator",
        arguments={"operation": "add", "a": 10, "b": 20},
    )

    result = provider.complete(
        [
            AgentMessage(role="user", content="Calculate 10 + 20"),
            AgentMessage(role="assistant", content="", tool_call=tool_call),
            AgentMessage(
                role="tool",
                content='{"success":true,"data":{"result":30},"error":null}',
                tool_call_id="call_123",
            ),
        ],
        [CalculatorTool().definition()],
    )

    assert result.final_answer == "The result is 30."
    assert fake_client.responses.requests[0]["input"][-1] == {
        "type": "function_call_output",
        "call_id": "call_123",
        "output": '{"success":true,"data":{"result":30},"error":null}',
    }


def test_openai_client_replays_all_output_items_for_stateless_tool_calls() -> None:
    first_response = SimpleNamespace(
        id="response_123",
        output=[
            SimpleNamespace(type="reasoning", id="reasoning_123", encrypted_content="opaque"),
            SimpleNamespace(
                type="function_call",
                call_id="call_123",
                name="calculator",
                arguments='{"operation":"add","a":10,"b":20}',
            ),
        ],
        output_text="",
    )
    second_response = SimpleNamespace(output=[], output_text="The result is 30.")
    fake_client = FakeOpenAIAPIClient([first_response, second_response])
    provider = OpenAIClient(client=fake_client, model="test-model")

    first_result = provider.complete(
        [AgentMessage(role="user", content="Calculate 10 + 20")],
        [CalculatorTool().definition()],
    )
    second_result = provider.complete(
        [
            AgentMessage(role="user", content="Calculate 10 + 20"),
            AgentMessage(
                role="assistant",
                content="",
                tool_call=first_result.tool_call,
                provider_context=first_result.provider_context,
            ),
            AgentMessage(
                role="tool",
                content='{"success":true,"data":{"result":30},"error":null}',
                tool_call_id="call_123",
            ),
        ],
        [CalculatorTool().definition()],
    )

    assert second_result.final_answer == "The result is 30."
    assert fake_client.responses.requests[1]["input"][1:3] == [
        {"type": "reasoning", "id": "reasoning_123", "encrypted_content": "opaque"},
        {
            "type": "function_call",
            "call_id": "call_123",
            "name": "calculator",
            "arguments": '{"operation":"add","a":10,"b":20}',
        },
    ]


def test_openai_client_replays_output_items_from_each_completed_turn() -> None:
    first_response = SimpleNamespace(
        id="response_123",
        output=[
            SimpleNamespace(
                type="function_call",
                call_id="call_123",
                name="calculator",
                arguments='{"operation":"add","a":10,"b":20}',
            )
        ],
        output_text="",
    )
    second_response = SimpleNamespace(
        id="response_456",
        output=[
            SimpleNamespace(type="reasoning", id="reasoning_456", encrypted_content="opaque"),
            SimpleNamespace(
                type="message",
                id="message_456",
                role="assistant",
                content=[{"type": "output_text", "text": "The result is 30."}],
            ),
        ],
        output_text="The result is 30.",
    )
    third_response = SimpleNamespace(output=[], output_text="Anything else?")
    fake_client = FakeOpenAIAPIClient([first_response, second_response, third_response])
    provider = OpenAIClient(client=fake_client, model="test-model")

    first_result = provider.complete(
        [AgentMessage(role="user", content="Calculate 10 + 20")],
        [CalculatorTool().definition()],
    )
    second_result = provider.complete(
        [
            AgentMessage(role="user", content="Calculate 10 + 20"),
            AgentMessage(
                role="assistant",
                content="",
                tool_call=first_result.tool_call,
                provider_context=first_result.provider_context,
            ),
            AgentMessage(
                role="tool",
                content='{"success":true,"data":{"result":30},"error":null}',
                tool_call_id="call_123",
            ),
        ],
        [CalculatorTool().definition()],
    )
    provider.complete(
        [
            AgentMessage(role="user", content="Calculate 10 + 20"),
            AgentMessage(
                role="assistant",
                content="",
                tool_call=first_result.tool_call,
                provider_context=first_result.provider_context,
            ),
            AgentMessage(
                role="tool",
                content='{"success":true,"data":{"result":30},"error":null}',
                tool_call_id="call_123",
            ),
            AgentMessage(
                role="assistant",
                content=second_result.final_answer or "",
                provider_context=second_result.provider_context,
            ),
            AgentMessage(role="user", content="What should I try next?"),
        ],
        [CalculatorTool().definition()],
    )

    assert fake_client.responses.requests[2]["input"][-3:] == [
        {"type": "reasoning", "id": "reasoning_456", "encrypted_content": "opaque"},
        {
            "type": "message",
            "id": "message_456",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "The result is 30."}],
        },
        {"role": "user", "content": "What should I try next?"},
    ]


def test_openai_client_can_continue_with_previous_response_id() -> None:
    first_response = SimpleNamespace(
        id="response_123",
        output=[
            SimpleNamespace(
                type="function_call",
                call_id="call_123",
                name="calculator",
                arguments='{"operation":"add","a":10,"b":20}',
            )
        ],
        output_text="",
    )
    second_response = SimpleNamespace(output=[], output_text="The result is 30.")
    fake_client = FakeOpenAIAPIClient([first_response, second_response])
    provider = OpenAIClient(
        client=fake_client,
        model="test-model",
        use_previous_response_id=True,
    )

    first_result = provider.complete(
        [AgentMessage(role="user", content="Calculate 10 + 20")],
        [CalculatorTool().definition()],
    )
    provider.complete(
        [
            AgentMessage(role="user", content="Calculate 10 + 20"),
            AgentMessage(
                role="assistant",
                content="",
                tool_call=first_result.tool_call,
                provider_context=first_result.provider_context,
            ),
            AgentMessage(
                role="tool",
                content='{"success":true,"data":{"result":30},"error":null}',
                tool_call_id="call_123",
            ),
        ],
        [CalculatorTool().definition()],
    )

    assert fake_client.responses.requests[0]["store"] is True
    assert fake_client.responses.requests[1]["previous_response_id"] == "response_123"
    assert fake_client.responses.requests[1]["input"] == [
        {
            "type": "function_call_output",
            "call_id": "call_123",
            "output": '{"success":true,"data":{"result":30},"error":null}',
        }
    ]


def test_openai_client_uses_environment_model(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = FakeOpenAIAPIClient([SimpleNamespace(output=[], output_text="Hi")])
    monkeypatch.setenv("OPENAI_MODEL", "configured-model")

    provider = OpenAIClient(client=fake_client)
    provider.complete([], [])

    assert fake_client.responses.requests[0]["model"] == "configured-model"


def test_openai_client_requires_api_key_when_creating_sdk_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    provider = OpenAIClient()

    with pytest.raises(ValueError, match="OPENAI_API_KEY must be configured"):
        provider.complete([], [])


def test_default_model_is_configurable_fallback() -> None:
    assert DEFAULT_MODEL == "gpt-5-mini"
