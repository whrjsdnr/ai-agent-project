"""HTTP API for agent runs."""

from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from ai_agent_project.agent.acceptance import AcceptanceReport
from ai_agent_project.agent.acceptance_validator import AcceptanceValidator
from ai_agent_project.agent.checkpoint import (
    CheckpointDecision,
    PhaseCheckpointService,
    ProgressReporter,
)
from ai_agent_project.agent.coding_service import (
    CodingAgentService,
    CodingRunResult,
    RepairAttempt,
)
from ai_agent_project.agent.phase_execution import PhaseExecutionService
from ai_agent_project.agent.plan import ImplementationPlan
from ai_agent_project.agent.plan_revision import PlanRevisionState
from ai_agent_project.agent.project_application import (
    InMemoryProjectRunStore,
    ProjectApplicationService,
    ProjectPlanReviewError,
    ProjectRunAlreadyExistsError,
    ProjectRunNotFoundError,
    ProjectRunStore,
    StoredProjectRun,
)
from ai_agent_project.agent.project_execution import ProjectExecutionService
from ai_agent_project.agent.project_runner import ProjectRunner
from ai_agent_project.agent.service import AgentService
from ai_agent_project.agent.specification import Specification
from ai_agent_project.agent.state import AgentState, AgentStatus
from ai_agent_project.agent.workspace import FilesystemWorkspaceInspector
from ai_agent_project.agent.workspace_acceptance import WorkspaceAcceptanceValidator
from ai_agent_project.llm.providers.openai import OpenAIClient
from ai_agent_project.llm.providers.openai_planner import OpenAIImplementationPlanner
from ai_agent_project.llm.providers.openai_project_plan_reviser import (
    OpenAIProjectPlanReviser,
)
from ai_agent_project.llm.providers.openai_project_planner import OpenAIProjectPlanner
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
    acceptance_report: AcceptanceReport
    repair_attempts: list[RepairAttempt]

    @classmethod
    def from_result(cls, result: CodingRunResult) -> "CodingRunResponse":
        """Build an API response without exposing mutable internal state details."""
        return cls(
            status=result.agent_run.status,
            specification=result.specification,
            plan=result.plan,
            agent_run=AgentRunResponse.from_state(result.agent_run),
            acceptance_report=result.acceptance_report,
            repair_attempts=result.repair_attempts,
        )


class CreateProjectRunRequest(BaseModel):
    """Request body for a planning-only project bootstrap."""

    source_text: str
    project_title: str | None = None
    source_format: str | None = None

    @field_validator("source_text")
    @classmethod
    def reject_blank_source_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("source_text must not be blank")
        return value


class ProjectDecisionRequest(BaseModel):
    """Request body for an explicit project phase checkpoint decision."""

    decision: CheckpointDecision
    note: str | None = None


class ProjectPlanRevisionRequest(BaseModel):
    """Request body for one pre-execution plan revision."""

    feedback: str

    @field_validator("feedback")
    @classmethod
    def reject_blank_feedback(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("feedback must not be blank")
        return value


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
    acceptance_validator: AcceptanceValidator | None = None,
) -> CodingAgentService:
    """Compose OpenAI parsing/planning with the generic default coding agent."""
    return CodingAgentService(
        specification_parser=OpenAISpecificationParser(),
        planner=OpenAIImplementationPlanner(),
        agent_service=agent_service or create_default_agent_service(workspace_root),
        acceptance_validator=acceptance_validator
        or WorkspaceAcceptanceValidator(workspace_root or _default_workspace_root()),
        workspace_inspector=FilesystemWorkspaceInspector(
            workspace_root or _default_workspace_root()
        ),
    )


def create_default_project_application_service(
    workspace_root: Path | None = None,
    *,
    agent_service: AgentService | None = None,
    store: ProjectRunStore | None = None,
) -> ProjectApplicationService:
    """Compose production planning and lifecycle services with an injected store."""
    resolved_workspace_root = workspace_root or _default_workspace_root()
    phase_execution_service = PhaseExecutionService(
        agent_service or create_default_agent_service(resolved_workspace_root),
        WorkspaceAcceptanceValidator(resolved_workspace_root),
    )
    project_execution_service = ProjectExecutionService(
        phase_execution_service,
        ProgressReporter(),
        PhaseCheckpointService(),
    )
    project_runner = ProjectRunner(
        OpenAISpecificationParser(),
        FilesystemWorkspaceInspector(resolved_workspace_root),
        OpenAIImplementationPlanner(),
        OpenAIProjectPlanner(),
        project_execution_service,
    )
    return ProjectApplicationService(
        project_runner,
        project_execution_service,
        store if store is not None else InMemoryProjectRunStore(),
        OpenAIProjectPlanReviser(),
    )


def create_app(
    agent_service: AgentService | None = None,
    workspace_root: Path | None = None,
    coding_agent_service: CodingAgentService | None = None,
    acceptance_validator: AcceptanceValidator | None = None,
    project_application_service: ProjectApplicationService | None = None,
) -> FastAPI:
    """Create the FastAPI app with injectable agent and default workspace root."""
    if agent_service is None:
        agent_service = create_default_agent_service(workspace_root)
    if coding_agent_service is None:
        coding_agent_service = create_default_coding_agent_service(
            workspace_root,
            agent_service=agent_service,
            acceptance_validator=acceptance_validator,
        )
    if project_application_service is None:
        project_application_service = create_default_project_application_service(
            workspace_root,
            agent_service=agent_service,
        )

    app = FastAPI(title="AI Agent Project")
    app.state.agent_service = agent_service
    app.state.coding_agent_service = coding_agent_service
    app.state.project_application_service = project_application_service

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

    @app.post(
        "/v1/project-runs",
        response_model=StoredProjectRun,
        status_code=status.HTTP_201_CREATED,
    )
    def create_project_run(request: CreateProjectRunRequest) -> StoredProjectRun:
        """Bootstrap and store a project without executing its first phase."""
        try:
            return project_application_service.create_project(
                request.source_text,
                project_title=request.project_title,
                source_format=request.source_format,
            )
        except ProjectRunAlreadyExistsError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Project run already exists.",
            ) from error

    @app.get("/v1/project-runs/{project_run_id}", response_model=StoredProjectRun)
    def get_project_run(project_run_id: str) -> StoredProjectRun:
        """Return one stored project run snapshot without changing its lifecycle."""
        try:
            return project_application_service.get_project(project_run_id)
        except ProjectRunNotFoundError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project run not found.",
            ) from error

    @app.get(
        "/v1/project-runs/{project_run_id}/plan",
        response_model=PlanRevisionState,
    )
    def get_project_plan(project_run_id: str) -> PlanRevisionState:
        """Return immutable plan review history without changing project state."""
        try:
            return project_application_service.get_plan(project_run_id)
        except ProjectRunNotFoundError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project run not found.",
            ) from error

    @app.post(
        "/v1/project-runs/{project_run_id}/plan/revisions",
        response_model=StoredProjectRun,
    )
    def revise_project_plan(
        project_run_id: str,
        request: ProjectPlanRevisionRequest,
    ) -> StoredProjectRun:
        """Persist a revised phase grouping before plan approval."""
        try:
            return project_application_service.revise_plan(
                project_run_id, request.feedback
            )
        except ProjectRunNotFoundError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project run not found.",
            ) from error
        except (ProjectPlanReviewError, ValueError) as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Project plan review conflict.",
            ) from error

    @app.post(
        "/v1/project-runs/{project_run_id}/plan/approve",
        response_model=StoredProjectRun,
    )
    def approve_project_plan(project_run_id: str) -> StoredProjectRun:
        """Approve a plan without executing its first phase."""
        try:
            return project_application_service.approve_plan(project_run_id)
        except ProjectRunNotFoundError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project run not found.",
            ) from error
        except (ProjectPlanReviewError, ValueError) as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Project plan review conflict.",
            ) from error

    @app.post(
        "/v1/project-runs/{project_run_id}/execute",
        response_model=StoredProjectRun,
    )
    def execute_project_phase(project_run_id: str) -> StoredProjectRun:
        """Execute exactly the current phase; callers decide checkpoints separately."""
        try:
            return project_application_service.execute_current_phase(project_run_id)
        except ProjectRunNotFoundError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project run not found.",
            ) from error
        except (ProjectPlanReviewError, ValueError) as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Project lifecycle conflict.",
            ) from error

    @app.post(
        "/v1/project-runs/{project_run_id}/decisions",
        response_model=StoredProjectRun,
    )
    def decide_project_phase(
        project_run_id: str,
        request: ProjectDecisionRequest,
    ) -> StoredProjectRun:
        """Store a phase decision without automatically executing another phase."""
        try:
            return project_application_service.decide_current_phase(
                project_run_id,
                request.decision,
                note=request.note,
            )
        except ProjectRunNotFoundError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project run not found.",
            ) from error
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Project lifecycle conflict.",
            ) from error

    return app


app = create_app()
