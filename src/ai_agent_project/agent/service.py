"""The minimal LLM and tool execution loop."""

from ai_agent_project.agent.state import AgentMessage, AgentState, AgentStatus
from ai_agent_project.llm.base import LLMClient
from ai_agent_project.tools.registry import ToolRegistry


class AgentService:
    """Run an LLM with a registry of tools."""

    def __init__(
        self,
        llm_client: LLMClient,
        tool_registry: ToolRegistry,
        *,
        max_tool_calls: int = 3,
    ) -> None:
        if max_tool_calls < 0:
            raise ValueError("max_tool_calls must be zero or greater")

        self._llm_client = llm_client
        self._tool_registry = tool_registry
        self._max_tool_calls = max_tool_calls

    def run(self, user_message: str) -> AgentState:
        """Process a user message until the LLM returns a final answer."""
        state = AgentState(messages=[AgentMessage(role="user", content=user_message)])

        try:
            while True:
                response = self._llm_client.complete(
                    state.messages,
                    self._tool_registry.definitions(),
                )

                if response.final_answer is not None:
                    state.messages.append(
                        AgentMessage(role="assistant", content=response.final_answer)
                    )
                    state.final_answer = response.final_answer
                    state.status = AgentStatus.COMPLETED
                    return state

                if response.tool_call is None:
                    raise ValueError("LLM response must include a final answer or tool call")

                if len(state.tool_calls) >= self._max_tool_calls:
                    raise RuntimeError(
                        f"Maximum tool call limit ({self._max_tool_calls}) exceeded"
                    )

                tool_call = response.tool_call
                state.tool_calls.append(tool_call)
                tool = self._tool_registry.get(tool_call.name)
                tool_result = tool.execute(tool_call.arguments)
                state.messages.append(
                    AgentMessage(
                        role="tool",
                        content=tool_result.model_dump_json(),
                        tool_call_id=tool_call.id,
                    )
                )
        except Exception as error:  # noqa: BLE001 - Agent runs must record all failures.
            state.status = AgentStatus.FAILED
            state.error = str(error)
            return state
