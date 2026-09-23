"""A provider-neutral LLM and multi-step tool execution loop."""

from ai_agent_project.agent.state import AgentMessage, AgentState, AgentStatus, ToolCall
from ai_agent_project.llm.base import LLMClient
from ai_agent_project.tools.base import ToolResult
from ai_agent_project.tools.registry import ToolNotFoundError, ToolRegistry


class AgentService:
    """Run an LLM with a registry of tools."""

    def __init__(
        self,
        llm_client: LLMClient,
        tool_registry: ToolRegistry,
        *,
        max_tool_calls: int = 20,
        max_iterations: int = 20,
    ) -> None:
        if max_tool_calls < 0:
            raise ValueError("max_tool_calls must be zero or greater")
        if max_iterations < 1:
            raise ValueError("max_iterations must be at least one")

        self._llm_client = llm_client
        self._tool_registry = tool_registry
        self._max_tool_calls = max_tool_calls
        self._max_iterations = max_iterations

    def run(self, user_message: str) -> AgentState:
        """Process a user message until the LLM returns a final answer."""
        state = AgentState(messages=[AgentMessage(role="user", content=user_message)])

        try:
            while state.iteration_count < self._max_iterations:
                state.iteration_count += 1
                response = self._llm_client.complete(
                    state.messages,
                    self._tool_registry.definitions(),
                )

                tool_calls = response.tool_calls or (
                    [response.tool_call] if response.tool_call is not None else []
                )
                if tool_calls:
                    self._execute_tool_calls(
                        state, tool_calls, response.provider_context
                    )
                    continue

                if response.final_answer is not None:
                    state.messages.append(
                        AgentMessage(
                            role="assistant",
                            content=response.final_answer,
                            provider_context=response.provider_context or None,
                        )
                    )
                    state.final_answer = response.final_answer
                    state.status = AgentStatus.COMPLETED
                    return state

                raise ValueError(
                    "LLM response must include a final answer or tool call"
                )

            raise RuntimeError(
                f"Maximum iteration limit ({self._max_iterations}) exceeded"
            )

        except Exception as error:  # noqa: BLE001 - Agent runs must record all failures.
            state.status = AgentStatus.FAILED
            state.error = str(error)
            return state

    def _execute_tool_calls(
        self,
        state: AgentState,
        tool_calls: list[ToolCall],
        provider_context: dict[str, object],
    ) -> None:
        """Record and execute all tool calls returned by one LLM response."""
        if len(state.tool_calls) + len(tool_calls) > self._max_tool_calls:
            raise RuntimeError(
                f"Maximum tool call limit ({self._max_tool_calls}) exceeded"
            )

        state.tool_calls.extend(tool_calls)
        state.messages.append(
            AgentMessage(
                role="assistant",
                content="",
                tool_call=tool_calls[0],
                tool_calls=tool_calls,
                provider_context=provider_context or None,
            )
        )
        for tool_call in tool_calls:
            tool_result = self._execute_tool_call(tool_call.name, tool_call.arguments)
            state.tool_results.append(tool_result)
            state.messages.append(
                AgentMessage(
                    role="tool",
                    content=tool_result.model_dump_json(),
                    tool_call_id=tool_call.id,
                )
            )

    def _execute_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, object],
    ) -> ToolResult:
        """Return expected lookup failures to the LLM as normal tool results."""
        try:
            tool = self._tool_registry.get(tool_name)
        except ToolNotFoundError as error:
            return ToolResult(success=False, error=str(error))
        return tool.execute(arguments)
