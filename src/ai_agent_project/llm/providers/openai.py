"""OpenAI Responses API implementation of the LLM client interface."""

import json
import os
from collections.abc import Mapping
from typing import Any, Literal, Protocol

from openai.types.responses import (
    ResponseFunctionToolCallParam,
    ResponseOutputMessageParam,
    ResponseReasoningItemParam,
)

from ai_agent_project.agent.state import AgentMessage, ToolCall
from ai_agent_project.llm.base import LLMResponse
from ai_agent_project.tools.base import ToolDefinition

DEFAULT_MODEL = "gpt-5-mini"
ToolChoice = Literal["auto", "required"]


class ResponsesAPI(Protocol):
    """The subset of the OpenAI Responses API used by this provider."""

    def create(self, **kwargs: Any) -> Any:
        """Create a model response."""
        ...


class OpenAIAPIClient(Protocol):
    """The subset of the OpenAI client used by this provider."""

    responses: ResponsesAPI


class OpenAIClient:
    """Adapt the OpenAI Responses API to the application's LLM interface."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        client: OpenAIAPIClient | None = None,
        use_previous_response_id: bool = False,
        tool_choice: ToolChoice = "auto",
    ) -> None:
        if tool_choice not in {"auto", "required"}:
            raise ValueError("tool_choice must be 'auto' or 'required'")

        self._model = model or os.getenv("OPENAI_MODEL", DEFAULT_MODEL)
        self._client = client
        self._api_key = api_key or os.getenv("OPENAI_API_KEY")
        self._use_previous_response_id = use_previous_response_id
        self._tool_choice = tool_choice

    def complete(
        self,
        messages: list[AgentMessage],
        tools: list[ToolDefinition],
    ) -> LLMResponse:
        """Request either a final answer or one function call from OpenAI."""
        input_items, previous_response_id = self._request_input(messages)
        request: dict[str, Any] = {
            "model": self._model,
            "input": input_items,
            "tools": self._to_openai_tools(tools),
            "tool_choice": self._tool_choice,
            "parallel_tool_calls": False,
            "store": self._use_previous_response_id,
        }
        if previous_response_id is not None:
            request["previous_response_id"] = previous_response_id

        response = self._get_client().responses.create(**request)
        provider_context = self._provider_context(response)

        tool_calls = self._extract_tool_calls(response)
        if tool_calls:
            return LLMResponse(
                tool_call=tool_calls[0],
                tool_calls=tool_calls,
                provider_context=provider_context,
            )

        return LLMResponse(
            final_answer=getattr(response, "output_text", ""),
            provider_context=provider_context,
        )

    def _request_input(
        self,
        messages: list[AgentMessage],
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Build input for stateless replay or a previous-response continuation."""
        if not self._use_previous_response_id:
            return self._to_openai_input(messages), None

        for index in range(len(messages) - 1, -1, -1):
            context = messages[index].provider_context
            if context is None:
                continue

            response_id = context.get("response_id")
            if isinstance(response_id, str):
                return self._to_openai_input(messages[index + 1 :]), response_id

        return self._to_openai_input(messages), None

    @classmethod
    def _provider_context(cls, response: Any) -> dict[str, Any]:
        """Store response output as request-safe continuation input items."""
        context: dict[str, Any] = {
            "input_items": [
                cls._response_output_to_input_item(item)
                for item in getattr(response, "output", [])
            ]
        }
        response_id = getattr(response, "id", None)
        if isinstance(response_id, str):
            context["response_id"] = response_id

        return context

    @classmethod
    def _response_output_to_input_item(cls, item: Any) -> dict[str, Any]:
        """Normalize an output item to the matching Responses input schema.

        Responses output objects contain server-populated fields such as ``status``.
        Constructing each supported input item field-by-field prevents them from being
        sent back on a stateless continuation.
        """
        item_type = cls._item_value(item, "type")
        if item_type == "function_call":
            return cls._function_call_input(item)
        if item_type == "reasoning":
            return cls._reasoning_input(item)
        if item_type == "message":
            return cls._message_input(item)

        raise ValueError(f"Unsupported OpenAI response output item type: {item_type!r}")

    @classmethod
    def _function_call_input(cls, item: Any) -> ResponseFunctionToolCallParam:
        """Build a request function call from its response counterpart."""
        return {
            "type": "function_call",
            "call_id": cls._required_string(item, "call_id"),
            "name": cls._required_string(item, "name"),
            "arguments": cls._required_string(item, "arguments"),
        }

    @classmethod
    def _reasoning_input(cls, item: Any) -> ResponseReasoningItemParam:
        """Build request-safe reasoning input, including encrypted continuation data."""
        reasoning: ResponseReasoningItemParam = {
            "type": "reasoning",
            "id": cls._required_string(item, "id"),
            "summary": cls._reasoning_parts(item, "summary", "summary_text"),
        }
        content = cls._item_value(item, "content")
        if content is not None:
            reasoning["content"] = cls._reasoning_parts(item, "content", "reasoning_text")
        encrypted_content = cls._item_value(item, "encrypted_content")
        if isinstance(encrypted_content, str):
            reasoning["encrypted_content"] = encrypted_content
        return reasoning

    @classmethod
    def _reasoning_parts(
        cls,
        item: Any,
        field: str,
        part_type: str,
    ) -> list[dict[str, str]]:
        """Convert reasoning text parts without replaying response-only attributes."""
        parts = cls._item_value(item, field)
        if not isinstance(parts, list | tuple):
            raise TypeError(f"OpenAI reasoning item must include a {field} list")
        return [
            {"type": part_type, "text": cls._required_string(part, "text")}
            for part in parts
        ]

    @classmethod
    def _message_input(cls, item: Any) -> ResponseOutputMessageParam:
        """Build an assistant message input from supported output content parts."""
        content = cls._item_value(item, "content")
        if not isinstance(content, list | tuple):
            raise TypeError("OpenAI message output must include a content list")

        message: ResponseOutputMessageParam = {
            "type": "message",
            "id": cls._required_string(item, "id"),
            "role": "assistant",
            "content": [cls._message_content_input(part) for part in content],
        }
        phase = cls._item_value(item, "phase")
        if phase in {"commentary", "final_answer"}:
            message["phase"] = phase
        return message

    @classmethod
    def _message_content_input(cls, part: Any) -> dict[str, str]:
        """Keep only content fields accepted for a replayed assistant message."""
        part_type = cls._item_value(part, "type")
        if part_type == "output_text":
            return {"type": "output_text", "text": cls._required_string(part, "text")}
        if part_type == "refusal":
            return {"type": "refusal", "refusal": cls._required_string(part, "refusal")}
        raise ValueError(f"Unsupported OpenAI message content type: {part_type!r}")

    @staticmethod
    def _item_value(item: Any, field: str) -> Any:
        """Read one SDK model field without serializing the complete output object."""
        if isinstance(item, Mapping):
            return item.get(field)
        return getattr(item, field, None)

    @classmethod
    def _required_string(cls, item: Any, field: str) -> str:
        """Return a required string field from an OpenAI response item."""
        value = cls._item_value(item, field)
        if not isinstance(value, str):
            raise TypeError(f"OpenAI response item field {field!r} must be a string")
        return value

    @staticmethod
    def _to_openai_tools(tools: list[ToolDefinition]) -> list[dict[str, Any]]:
        """Convert internal tool definitions into OpenAI function tools."""
        return [
            {
                "type": "function",
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
                "strict": False,
            }
            for tool in tools
        ]

    @staticmethod
    def _to_openai_input(messages: list[AgentMessage]) -> list[dict[str, Any]]:
        """Convert the agent's message history into Responses API input items."""
        input_items: list[dict[str, Any]] = []
        for message in messages:
            if message.provider_context is not None:
                continuation_items = message.provider_context.get("input_items")
                if isinstance(continuation_items, list):
                    input_items.extend(continuation_items)
                    continue
            tool_calls = message.tool_calls or (
                [message.tool_call] if message.tool_call is not None else []
            )
            if tool_calls:
                input_items.extend(
                    {
                        "type": "function_call",
                        "call_id": tool_call.id,
                        "name": tool_call.name,
                        "arguments": json.dumps(tool_call.arguments),
                    }
                    for tool_call in tool_calls
                )
            elif message.role == "tool":
                if message.tool_call_id is None:
                    raise ValueError("Tool messages must include a tool_call_id")
                input_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": message.tool_call_id,
                        "output": message.content,
                    }
                )
            else:
                input_items.append({"role": message.role, "content": message.content})

        return input_items

    def _get_client(self) -> OpenAIAPIClient:
        """Create the SDK client only when an agent run needs it."""
        if self._client is not None:
            return self._client

        if not self._api_key:
            raise ValueError("OPENAI_API_KEY must be configured")

        from openai import OpenAI

        self._client = OpenAI(api_key=self._api_key)
        return self._client


    @staticmethod
    def _extract_tool_calls(response: Any) -> list[ToolCall]:
        """Extract every function call requested in an OpenAI response."""
        tool_calls: list[ToolCall] = []
        for item in getattr(response, "output", []):
            if getattr(item, "type", None) != "function_call":
                continue

            try:
                arguments = json.loads(item.arguments)
            except json.JSONDecodeError as error:
                raise ValueError("OpenAI returned invalid function call arguments") from error

            if not isinstance(arguments, dict):
                raise TypeError("OpenAI function call arguments must be an object")

            tool_calls.append(
                ToolCall(id=item.call_id, name=item.name, arguments=arguments)
            )

        return tool_calls
