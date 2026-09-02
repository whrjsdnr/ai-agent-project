"""HTTP API for agent runs."""

from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel, Field

from ai_agent_project.agent.coding_service import CodingAgentService, CodingRunResult
from ai_agent_project.agent.plan import ImplementationPlan
from ai_agent_project.agent.service import AgentService
from ai_agent_project.agent.specification import Specification
from ai_agent_project.agent.state import AgentState, AgentStatus
from ai_agent_project.llm.providers.openai import OpenAIClient
from ai_agent_project.llm.providers.openai_planner import OpenAIImplementationPlanner
from ai_agent_project.llm.providers.openai_specification import (
    OpenAISpecificationParser,
)
from ai_agent_project.tools.calculator import CalculatorTool
from ai_agent_project.tools.file import FileTool
from ai_agent_project.tools.registry import ToolRegistry
from ai_agent_project.tools.shell import ShellTool


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


class CodingRunRequest(BaseModel):
    """Request body for a specification-driven coding run."""

    specification: str = Field(min_length=1)


class CodingRunResponse(BaseModel):
    """Public result of parsing, planning, and a coding-agent run."""

    status: AgentStatus
    specification: Specification
    plan: ImplementationPlan
    agent_run: AgentRunResponse

    @classmethod
    def from_result(cls, result: CodingRunResult) -> "CodingRunResponse":
        """Build an API response without exposing mutable internal state details."""
        return cls(
            status=result.agent_run.status,
            specification=result.specification,
            plan=result.plan,
            agent_run=AgentRunResponse.from_state(result.agent_run),
        )


def _default_workspace_root() -> Path:
    """Return the project root containing the source tree."""
    return Path(__file__).resolve().parents[3]


def create_default_agent_service(workspace_root: Path | None = None) -> AgentService:
    """Build the default agent with OpenAI and workspace-scoped development tools."""
    registry = ToolRegistry()
    resolved_workspace_root = workspace_root or _default_workspace_root()
    registry.register(CalculatorTool())
    registry.register(FileTool(resolved_workspace_root))
    registry.register(ShellTool(resolved_workspace_root))
    return AgentService(OpenAIClient(), registry)


def create_default_coding_agent_service(
    workspace_root: Path | None = None,
    *,
    agent_service: AgentService | None = None,
) -> CodingAgentService:
    """Compose OpenAI parsing/planning with the generic default coding agent."""
    return CodingAgentService(
        specification_parser=OpenAISpecificationParser(),
        planner=OpenAIImplementationPlanner(),
        agent_service=agent_service or create_default_agent_service(workspace_root),
    )


def create_app(
    agent_service: AgentService | None = None,
    workspace_root: Path | None = None,
    coding_agent_service: CodingAgentService | None = None,
) -> FastAPI:
    """Create the FastAPI app with injectable agent and default workspace root."""
    if agent_service is None:
        agent_service = create_default_agent_service(workspace_root)
    if coding_agent_service is None:
        coding_agent_service = create_default_coding_agent_service(
            workspace_root,
            agent_service=agent_service,
        )

    app = FastAPI(title="AI Agent Project")
    app.state.agent_service = agent_service
    app.state.coding_agent_service = coding_agent_service

    @app.get("/health")
    def health() -> dict[str, str]:
        """Return a lightweight service health response."""
        return {"status": "ok"}

    @app.post("/v1/agent-runs", response_model=AgentRunResponse)
    def run_agent(request: AgentRunRequest) -> AgentRunResponse:
        """Run the configured agent with a single user message."""
        state = agent_service.run(request.user_message)
        return AgentRunResponse.from_state(state)

    @app.post("/v1/coding-runs", response_model=CodingRunResponse)
    def run_coding_agent(request: CodingRunRequest) -> CodingRunResponse:
        """Parse, plan, and execute one specification-driven coding run."""
        result = coding_agent_service.run_from_specification(request.specification)
        return CodingRunResponse.from_result(result)

    return app


app = create_app()
