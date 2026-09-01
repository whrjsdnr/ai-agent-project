"""HTTP API for agent runs."""

from fastapi import FastAPI
from pydantic import BaseModel, Field

from ai_agent_project.agent.service import AgentService
from ai_agent_project.agent.state import AgentState, AgentStatus
from ai_agent_project.llm.base import LLMResponse
from ai_agent_project.tools.registry import ToolRegistry


class AgentRunRequest(BaseModel):
    """Request body for an agent run."""

    user_message: str = Field(min_length=1)


class AgentRunResponse(BaseModel):
    """Public result of an agent run."""

    run_id: str
    status: AgentStatus
    final_answer: str | None
    error: str | None
    tool_calls: int

    @classmethod
    def from_state(cls, state: AgentState) -> "AgentRunResponse":
        """Build an API response from internal agent state."""
        return cls(
            run_id=state.run_id,
            status=state.status,
            final_answer=state.final_answer,
            error=state.error,
            tool_calls=len(state.tool_calls),
        )


class UnconfiguredLLMClient:
    """Default client that reports a missing LLM provider configuration."""

    def complete(self, messages: list[object], tools: list[object]) -> LLMResponse:
        """Explain why a default app cannot execute an agent run yet."""
        del messages, tools
        raise RuntimeError("No LLM client is configured")


def create_app(agent_service: AgentService | None = None) -> FastAPI:
    """Create the FastAPI application, optionally with an injected agent."""
    if agent_service is None:
        agent_service = AgentService(UnconfiguredLLMClient(), ToolRegistry())

    app = FastAPI(title="AI Agent Project")

    @app.get("/health")
    def health() -> dict[str, str]:
        """Return a lightweight service health response."""
        return {"status": "ok"}

    @app.post("/v1/agent-runs", response_model=AgentRunResponse)
    def run_agent(request: AgentRunRequest) -> AgentRunResponse:
        """Run the configured agent with a single user message."""
        state = agent_service.run(request.user_message)
        return AgentRunResponse.from_state(state)

    return app


app = create_app()
