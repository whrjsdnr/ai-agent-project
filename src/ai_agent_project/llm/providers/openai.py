"""OpenAI Responses API implementation of the LLM client interface."""

import json
import os
from collections.abc import Mapping
from typing import Any, Protocol

from ai_agent_project.agent.state import AgentMessage, ToolCall
from ai_agent_project.llm.base import LLMResponse
from ai_agent_project.tools.base import ToolDefinition

DEFAULT_MODEL = "gpt-5-mini"


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
    ) -> None:
        self._model = model or os.getenv("OPENAI_MODEL", DEFAULT_MODEL)
        self._client = client
        self._api_key = api_key or os.getenv("OPENAI_API_KEY")
        self._use_previous_response_id = use_previous_response_id

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
            "parallel_tool_calls": False,
            "store": self._use_previous_response_id,
        }
        if previous_response_id is not None:
            request["previous_response_id"] = previous_response_id

        response = self._get_client().responses.create(**request)
        provider_context = self._provider_context(response)

        tool_call = self._extract_tool_call(response)
        if tool_call is not None:
            return LLMResponse(tool_call=tool_call, provider_context=provider_context)

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
        """Preserve every response output item for a later stateless replay."""
        context: dict[str, Any] = {
            "output_items": [
                cls._to_json_value(item) for item in getattr(response, "output", [])
            ]
        }
        response_id = getattr(response, "id", None)
        if isinstance(response_id, str):
            context["response_id"] = response_id

        return context

    @classmethod
    def _to_json_value(cls, value: Any) -> Any:
        """Convert SDK response models into JSON-compatible data without filtering fields."""
        if hasattr(value, "model_dump"):
            return cls._to_json_value(value.model_dump(mode="json", exclude_none=False))
        if isinstance(value, Mapping):
            return {key: cls._to_json_value(item) for key, item in value.items()}
        if isinstance(value, list | tuple):
            return [cls._to_json_value(item) for item in value]
        if hasattr(value, "__dict__"):
            return {
                key: cls._to_json_value(item)
                for key, item in vars(value).items()
                if not key.startswith("_")
            }
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
                output_items = message.provider_context.get("output_items")
                if isinstance(output_items, list):
                    input_items.extend(output_items)
                    continue
            if message.tool_call is not None:
                input_items.append(
                    {
                        "type": "function_call",
                        "call_id": message.tool_call.id,
                        "name": message.tool_call.name,
                        "arguments": json.dumps(message.tool_call.arguments),
                    }
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
    def _extract_tool_call(response: Any) -> ToolCall | None:
        """Extract the first function call requested in an OpenAI response."""
        for item in getattr(response, "output", []):
            if getattr(item, "type", None) != "function_call":
                continue

            try:
                arguments = json.loads(item.arguments)
            except json.JSONDecodeError as error:
                raise ValueError("OpenAI returned invalid function call arguments") from error

            if not isinstance(arguments, dict):
                raise TypeError("OpenAI function call arguments must be an object")

            return ToolCall(id=item.call_id, name=item.name, arguments=arguments)

        return None
