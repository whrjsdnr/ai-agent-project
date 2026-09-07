"""HTTP API for agent runs."""

from pathlib import Path

from fastapi import FastAPI, HTTPException, Response, status
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
from ai_agent_project.agent.hybrid_coordination import HybridCoordinationView
from ai_agent_project.agent.hybrid_coordination_application import (
    HybridCoordinationError,
    HybridCoordinationService,
)
from ai_agent_project.agent.phase_execution import PhaseExecutionService
from ai_agent_project.agent.plan import ImplementationPlan
from ai_agent_project.agent.plan_revision import PlanRevisionState
from ai_agent_project.agent.project_action_application import (
    ApproveDeveloperPlanCommand,
    ApproveResearchPlanCommand,
    ContinueDeveloperCommand,
    ContinueResearcherCommand,
    ProjectActionCompletedError,
    ProjectActionNotAllowedError,
    ProjectActionResult,
    ProjectActionService,
    ProvideResearchResultsCommand,
    SelectResearchDirectionCommand,
)
from ai_agent_project.agent.project_application import (
    InMemoryProjectRunStore,
    ProjectApplicationService,
    ProjectPlanReviewError,
    ProjectRunAlreadyExistsError,
    ProjectRunError,
    ProjectRunNotFoundError,
    ProjectRunStore,
    StoredProjectRun,
)
from ai_agent_project.agent.project_artifact import (
    ProjectArtifactCatalog,
    ProjectArtifactView,
)
from ai_agent_project.agent.project_artifact_application import (
    ProjectArtifactError,
    ProjectArtifactNotFoundError,
    ProjectArtifactService,
)
from ai_agent_project.agent.project_artifact_rendering import (
    MARKDOWN_MEDIA_TYPE,
    TEXT_MEDIA_TYPE,
    ProjectArtifactFormat,
    ProjectArtifactRenderingError,
    render_project_artifact,
)
from ai_agent_project.agent.project_execution import ProjectExecutionService
from ai_agent_project.agent.project_runner import ProjectRunner, UpgradeProjectRunner
from ai_agent_project.agent.project_session_application import (
    DeveloperRunReader,
    InMemoryProjectSessionStore,
    ProjectSessionError,
    ProjectSessionNotFoundError,
    ProjectSessionService,
    ProjectSessionStateError,
    ProjectSessionStore,
    ResearchRunReader,
    StoredProjectSession,
)
from ai_agent_project.agent.research import ResearchResultSubmission, WorkMode
from ai_agent_project.agent.research_application import (
    InMemoryResearchRunStore,
    InvalidResearchStateError,
    ResearchApplicationService,
    ResearchDirectionNotFoundError,
    ResearchResultsNotProvidedError,
    ResearchRunError,
    ResearchRunNotFoundError,
    StoredResearchRun,
)
from ai_agent_project.agent.research_discovery import ResearchDiscoveryService
from ai_agent_project.agent.research_file_store import FileResearchRunStore
from ai_agent_project.agent.service import AgentService
from ai_agent_project.agent.specification import Specification
from ai_agent_project.agent.state import AgentState, AgentStatus
from ai_agent_project.agent.upgrade import ProjectMode, UpgradeContext
from ai_agent_project.agent.workspace import FilesystemWorkspaceInspector
from ai_agent_project.agent.workspace_acceptance import WorkspaceAcceptanceValidator
from ai_agent_project.llm.providers.openai import OpenAIClient
from ai_agent_project.llm.providers.openai_codebase_analyzer import (
    OpenAICodebaseAnalyzer,
)
from ai_agent_project.llm.providers.openai_planner import OpenAIImplementationPlanner
from ai_agent_project.llm.providers.openai_project_mode_proposer import (
    OpenAIProjectModeProposer,
)
from ai_agent_project.llm.providers.openai_project_plan_reviser import (
    OpenAIProjectPlanReviser,
)
from ai_agent_project.llm.providers.openai_project_planner import OpenAIProjectPlanner
from ai_agent_project.llm.providers.openai_research_discovery_synthesizer import (
    OpenAIResearchDiscoverySynthesizer,
)
from ai_agent_project.llm.providers.openai_research_evidence_extractor import (
    OpenAIResearchEvidenceExtractor,
)
from ai_agent_project.llm.providers.openai_research_implementation import (
    OpenAIResearchImplementationGenerator,
    OpenAIResearchImplementationPlanner,
)
from ai_agent_project.llm.providers.openai_research_paper_materials import (
    OpenAIResearchPaperMaterialsGenerator,
)
from ai_agent_project.llm.providers.openai_research_plan_generator import (
    OpenAIResearchPlanGenerator,
)
from ai_agent_project.llm.providers.openai_research_question_planner import (
    OpenAIResearchQuestionPlanner,
)
from ai_agent_project.llm.providers.openai_research_result_analyzer import (
    OpenAIResearchResultAnalyzer,
)
from ai_agent_project.llm.providers.openai_research_result_synthesizer import (
    OpenAIResearchResultSynthesizer,
)
from ai_agent_project.llm.providers.openai_specification import (
    OpenAISpecificationParser,
)
from ai_agent_project.llm.providers.openai_upgrade_analyzer import OpenAIUpgradeAnalyzer
from ai_agent_project.llm.providers.openai_web_research import (
    OpenAIWebResearchSourceProvider,
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


class CreateProjectSessionRequest(BaseModel):
    original_request: str
    title: str | None = None

    @field_validator("original_request")
    @classmethod
    def reject_blank_request(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("original_request must not be blank")
        return value


class ConfirmProjectModeRequest(BaseModel):
    work_mode: WorkMode
    project_mode: ProjectMode


class BindProjectRunRequest(BaseModel):
    run_id: str

    @field_validator("run_id")
    @classmethod
    def reject_blank_run_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("run_id must not be blank")
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


class CreateUpgradeProjectRequest(BaseModel):
    request_text: str
    project_title: str | None = None

    @field_validator("request_text")
    @classmethod
    def reject_blank_request(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("request_text must not be blank")
        return value


class CreateResearchRunRequest(BaseModel):
    topic: str
    user_context: str | None = None

    @field_validator("topic")
    @classmethod
    def reject_blank_topic(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("topic must not be blank")
        return value


class SelectResearchDirectionRequest(BaseModel):
    direction_id: str = Field(min_length=1)


class ResearchPlanRevisionRequest(BaseModel):
    note: str

    @field_validator("note")
    @classmethod
    def reject_blank_note(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("note must not be blank")
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
    upgrade_runner = UpgradeProjectRunner(
        FilesystemWorkspaceInspector(resolved_workspace_root),
        OpenAICodebaseAnalyzer(),
        OpenAIUpgradeAnalyzer(),
        OpenAIImplementationPlanner(),
        OpenAIProjectPlanner(),
        project_execution_service,
    )
    return ProjectApplicationService(
        project_runner,
        project_execution_service,
        store if store is not None else InMemoryProjectRunStore(),
        OpenAIProjectPlanReviser(),
        upgrade_runner,
    )


def create_default_project_session_service(
    *,
    store: ProjectSessionStore | None = None,
    developer_run_reader: DeveloperRunReader | None = None,
    research_run_reader: ResearchRunReader | None = None,
) -> ProjectSessionService:
    """Compose proposal-only project-session orchestration."""
    return ProjectSessionService(
        store if store is not None else InMemoryProjectSessionStore(),
        OpenAIProjectModeProposer(),
        developer_run_reader,
        research_run_reader,
    )


def create_default_research_application_service(
    workspace_root: Path | None = None,
    *,
    store: InMemoryResearchRunStore | FileResearchRunStore | None = None,
) -> ResearchApplicationService:
    """Compose real OpenAI planning, retrieval, and synthesis without fallback."""
    resolved_workspace_root = workspace_root or _default_workspace_root()
    discovery = ResearchDiscoveryService(
        OpenAIResearchQuestionPlanner(),
        OpenAIWebResearchSourceProvider(),
        OpenAIResearchEvidenceExtractor(),
        OpenAIResearchDiscoverySynthesizer(),
        FilesystemWorkspaceInspector(resolved_workspace_root),
    )
    return ResearchApplicationService(
        discovery,
        store if store is not None else InMemoryResearchRunStore(),
        OpenAIResearchPlanGenerator(),
        OpenAIResearchImplementationPlanner(),
        OpenAIResearchImplementationGenerator(),
        OpenAIResearchResultAnalyzer(),
        OpenAIResearchResultSynthesizer(),
        OpenAIResearchPaperMaterialsGenerator(),
    )


def create_app(
    agent_service: AgentService | None = None,
    workspace_root: Path | None = None,
    coding_agent_service: CodingAgentService | None = None,
    acceptance_validator: AcceptanceValidator | None = None,
    project_application_service: ProjectApplicationService | None = None,
    project_session_service: ProjectSessionService | None = None,
    project_artifact_service: ProjectArtifactService | None = None,
    project_action_service: ProjectActionService | None = None,
    hybrid_coordination_service: HybridCoordinationService | None = None,
    research_application_service: ResearchApplicationService | None = None,
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
        project_run_store = InMemoryProjectRunStore()
        project_application_service = create_default_project_application_service(
            workspace_root,
            agent_service=agent_service,
            store=project_run_store,
        )
    else:
        project_run_store = None
    if research_application_service is None:
        research_run_store = InMemoryResearchRunStore()
        research_application_service = create_default_research_application_service(
            workspace_root, store=research_run_store
        )
    else:
        research_run_store = None
    if project_session_service is None:
        project_session_service = create_default_project_session_service(
            developer_run_reader=project_run_store,
            research_run_reader=research_run_store,
        )
    if project_artifact_service is None:
        project_artifact_service = ProjectArtifactService(
            project_session_service,
            project_run_store,
            research_run_store,
        )
    if project_action_service is None:
        project_action_service = ProjectActionService(
            project_session_service,
            project_application_service,
            research_application_service,
        )
    if hybrid_coordination_service is None:
        hybrid_coordination_service = HybridCoordinationService(
            project_session_service,
            project_run_store,
            research_run_store,
        )

    app = FastAPI(title="AI Agent Project")
    app.state.agent_service = agent_service
    app.state.coding_agent_service = coding_agent_service
    app.state.project_application_service = project_application_service
    app.state.project_session_service = project_session_service
    app.state.project_artifact_service = project_artifact_service
    app.state.project_action_service = project_action_service
    app.state.hybrid_coordination_service = hybrid_coordination_service
    app.state.research_application_service = research_application_service

    @app.get("/health")
    def health() -> dict[str, str]:
        """Return a lightweight service health response."""
        return {"status": "ok"}

    def require_research_service() -> ResearchApplicationService:
        if research_application_service is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Research discovery source retrieval is not configured.",
            )
        return research_application_service

    def require_project_session_service() -> ProjectSessionService:
        assert project_session_service is not None
        return project_session_service

    def require_project_artifact_service() -> ProjectArtifactService:
        assert project_artifact_service is not None
        return project_artifact_service

    def require_project_action_service() -> ProjectActionService:
        assert project_action_service is not None
        return project_action_service

    def require_hybrid_coordination_service() -> HybridCoordinationService:
        assert hybrid_coordination_service is not None
        return hybrid_coordination_service

    @app.post("/v1/projects", response_model=StoredProjectSession, status_code=201)
    def create_project_session(
        request: CreateProjectSessionRequest,
    ) -> StoredProjectSession:
        try:
            return require_project_session_service().create_project_request(
                request.original_request, title=request.title
            )
        except ProjectSessionError as error:
            raise HTTPException(
                status_code=503, detail="Project mode proposal unavailable."
            ) from error

    @app.get("/v1/projects/{project_id}", response_model=StoredProjectSession)
    def get_project_session(project_id: str) -> StoredProjectSession:
        try:
            return require_project_session_service().get_project(project_id)
        except ProjectSessionNotFoundError as error:
            raise HTTPException(status_code=404, detail="Project not found.") from error

    @app.post(
        "/v1/projects/{project_id}/confirm-mode", response_model=StoredProjectSession
    )
    def confirm_project_mode(
        project_id: str, request: ConfirmProjectModeRequest
    ) -> StoredProjectSession:
        try:
            return require_project_session_service().confirm_project_mode(
                project_id, request.work_mode, request.project_mode
            )
        except ProjectSessionNotFoundError as error:
            raise HTTPException(status_code=404, detail="Project not found.") from error
        except ProjectSessionStateError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post(
        "/v1/projects/{project_id}/developer-run", response_model=StoredProjectSession
    )
    def bind_project_developer_run(
        project_id: str, request: BindProjectRunRequest
    ) -> StoredProjectSession:
        try:
            return require_project_session_service().bind_developer_run(
                project_id, request.run_id
            )
        except ProjectSessionNotFoundError as error:
            raise HTTPException(status_code=404, detail="Project not found.") from error
        except ProjectSessionStateError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post(
        "/v1/projects/{project_id}/research-run", response_model=StoredProjectSession
    )
    def bind_project_research_run(
        project_id: str, request: BindProjectRunRequest
    ) -> StoredProjectSession:
        try:
            return require_project_session_service().bind_research_run(
                project_id, request.run_id
            )
        except ProjectSessionNotFoundError as error:
            raise HTTPException(status_code=404, detail="Project not found.") from error
        except ProjectSessionStateError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/v1/projects/{project_id}/complete", response_model=StoredProjectSession)
    def complete_project_session(project_id: str) -> StoredProjectSession:
        try:
            return require_project_session_service().complete_project(project_id)
        except ProjectSessionNotFoundError as error:
            raise HTTPException(status_code=404, detail="Project not found.") from error
        except ProjectSessionStateError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/v1/projects/{project_id}/pending-action")
    def get_project_pending_action(project_id: str):
        try:
            return {
                "project_id": project_id,
                "pending_actions": require_project_session_service().get_pending_actions(
                    project_id
                ),
            }
        except ProjectSessionNotFoundError as error:
            raise HTTPException(status_code=404, detail="Project not found.") from error
        except ProjectSessionError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/v1/projects/{project_id}/resume")
    def resume_project_session(project_id: str):
        try:
            return require_project_session_service().resume_project(project_id)
        except ProjectSessionNotFoundError as error:
            raise HTTPException(status_code=404, detail="Project not found.") from error
        except ProjectSessionError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get(
        "/v1/projects/{project_id}/coordination",
        response_model=HybridCoordinationView,
    )
    def get_hybrid_coordination(project_id: str) -> HybridCoordinationView:
        try:
            return require_hybrid_coordination_service().get_coordination(project_id)
        except ProjectSessionNotFoundError as error:
            raise HTTPException(status_code=404, detail="Project not found.") from error
        except (HybridCoordinationError, ProjectSessionError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get(
        "/v1/projects/{project_id}/artifacts",
        response_model=ProjectArtifactCatalog,
    )
    def list_project_artifacts(project_id: str) -> ProjectArtifactCatalog:
        try:
            return require_project_artifact_service().list_artifacts(project_id)
        except ProjectArtifactNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ProjectArtifactError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get(
        "/v1/projects/{project_id}/artifacts/{artifact_id}",
        response_model=None,
    )
    def inspect_project_artifact(
        project_id: str,
        artifact_id: str,
        format: ProjectArtifactFormat = ProjectArtifactFormat.JSON,
    ) -> ProjectArtifactView | Response:
        try:
            view = require_project_artifact_service().get_artifact(
                project_id, artifact_id
            )
            if format is ProjectArtifactFormat.JSON:
                return view
            media_type = (
                MARKDOWN_MEDIA_TYPE
                if format is ProjectArtifactFormat.MARKDOWN
                else TEXT_MEDIA_TYPE
            )
            return Response(
                content=render_project_artifact(view, format),
                media_type=media_type,
            )
        except ProjectArtifactNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ProjectArtifactRenderingError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except ProjectArtifactError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post(
        "/v1/projects/{project_id}/actions/approve-developer-plan",
        response_model=ProjectActionResult,
    )
    def route_developer_plan_approval(project_id: str) -> ProjectActionResult:
        try:
            return require_project_action_service().approve_developer_plan(
                ApproveDeveloperPlanCommand(project_id=project_id)
            )
        except ProjectSessionNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ProjectRunNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except (
            ProjectActionNotAllowedError,
            ProjectActionCompletedError,
            ProjectSessionError,
            ProjectRunError,
        ) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post(
        "/v1/projects/{project_id}/actions/select-research-direction",
        response_model=ProjectActionResult,
    )
    def route_research_direction_selection(
        project_id: str, request: SelectResearchDirectionRequest
    ) -> ProjectActionResult:
        try:
            return require_project_action_service().select_research_direction(
                SelectResearchDirectionCommand(
                    project_id=project_id, direction_id=request.direction_id
                )
            )
        except (
            ProjectSessionNotFoundError,
            ResearchRunNotFoundError,
            ResearchDirectionNotFoundError,
        ) as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except (
            ProjectActionNotAllowedError,
            ProjectActionCompletedError,
            ProjectSessionError,
            ResearchRunError,
        ) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post(
        "/v1/projects/{project_id}/actions/approve-research-plan",
        response_model=ProjectActionResult,
    )
    def route_research_plan_approval(project_id: str) -> ProjectActionResult:
        try:
            return require_project_action_service().approve_research_plan(
                ApproveResearchPlanCommand(project_id=project_id)
            )
        except (ProjectSessionNotFoundError, ResearchRunNotFoundError) as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except (
            ProjectActionNotAllowedError,
            ProjectActionCompletedError,
            ProjectSessionError,
            ResearchRunError,
        ) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post(
        "/v1/projects/{project_id}/actions/continue-developer",
        response_model=ProjectActionResult,
    )
    def route_developer_continuation(project_id: str) -> ProjectActionResult:
        try:
            return require_project_action_service().continue_developer(
                ContinueDeveloperCommand(project_id=project_id)
            )
        except (ProjectSessionNotFoundError, ProjectRunNotFoundError) as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except (
            ProjectActionNotAllowedError,
            ProjectActionCompletedError,
            ProjectSessionError,
            ProjectRunError,
            ValueError,
        ) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post(
        "/v1/projects/{project_id}/actions/continue-researcher",
        response_model=ProjectActionResult,
    )
    def route_researcher_continuation(project_id: str) -> ProjectActionResult:
        try:
            return require_project_action_service().continue_researcher(
                ContinueResearcherCommand(project_id=project_id)
            )
        except (ProjectSessionNotFoundError, ResearchRunNotFoundError) as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except (
            ProjectActionNotAllowedError,
            ProjectActionCompletedError,
            ProjectSessionError,
            ResearchRunError,
            ValueError,
        ) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post(
        "/v1/projects/{project_id}/actions/provide-research-results",
        response_model=ProjectActionResult,
    )
    def route_research_result_submission(
        project_id: str, submission: ResearchResultSubmission
    ) -> ProjectActionResult:
        try:
            return require_project_action_service().provide_research_results(
                ProvideResearchResultsCommand(
                    project_id=project_id, submission=submission
                )
            )
        except (ProjectSessionNotFoundError, ResearchRunNotFoundError) as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except (
            ProjectActionNotAllowedError,
            ProjectActionCompletedError,
            ProjectSessionError,
            ResearchRunError,
        ) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post(
        "/v1/research-runs",
        response_model=StoredResearchRun,
        status_code=status.HTTP_201_CREATED,
    )
    def create_research_run(request: CreateResearchRunRequest) -> StoredResearchRun:
        try:
            return require_research_service().create_research_run(
                request.topic, user_context=request.user_context
            )
        except ValueError as error:
            raise HTTPException(
                status_code=409, detail="Research discovery failed."
            ) from error

    @app.get("/v1/research-runs/{research_run_id}", response_model=StoredResearchRun)
    def get_research_run(research_run_id: str) -> StoredResearchRun:
        try:
            return require_research_service().get_research_run(research_run_id)
        except ResearchRunNotFoundError as error:
            raise HTTPException(
                status_code=404, detail="Research run not found."
            ) from error

    @app.get("/v1/research-runs/{research_run_id}/report")
    def get_research_report(research_run_id: str):
        try:
            return require_research_service().get_research_report(research_run_id)
        except ResearchRunNotFoundError as error:
            raise HTTPException(
                status_code=404, detail="Research run not found."
            ) from error

    @app.get("/v1/research-runs/{research_run_id}/directions")
    def get_research_directions(research_run_id: str):
        try:
            return require_research_service().get_research_directions(research_run_id)
        except ResearchRunNotFoundError as error:
            raise HTTPException(
                status_code=404, detail="Research run not found."
            ) from error

    @app.post(
        "/v1/research-runs/{research_run_id}/direction",
        response_model=StoredResearchRun,
    )
    def select_research_direction(
        research_run_id: str, request: SelectResearchDirectionRequest
    ) -> StoredResearchRun:
        try:
            return require_research_service().select_research_direction(
                research_run_id, request.direction_id
            )
        except (ResearchRunNotFoundError, ResearchDirectionNotFoundError) as error:
            raise HTTPException(
                status_code=404, detail="Research run or direction not found."
            ) from error
        except InvalidResearchStateError as error:
            raise HTTPException(
                status_code=409, detail="Research lifecycle conflict."
            ) from error

    @app.post("/v1/research-runs/{research_run_id}/plan")
    def generate_research_plan(research_run_id: str) -> StoredResearchRun:
        try:
            return require_research_service().generate_plan(research_run_id)
        except ResearchRunNotFoundError as error:
            raise HTTPException(
                status_code=404, detail="Research run not found."
            ) from error
        except InvalidResearchStateError as error:
            raise HTTPException(
                status_code=409, detail="Research lifecycle conflict."
            ) from error
        except (ResearchRunError, ValueError) as error:
            raise HTTPException(
                status_code=503, detail="Research plan generation unavailable."
            ) from error

    @app.get("/v1/research-runs/{research_run_id}/plan")
    def get_research_plan(research_run_id: str):
        try:
            return require_research_service().get_plan(research_run_id)
        except ResearchRunNotFoundError as error:
            raise HTTPException(
                status_code=404, detail="Research run not found."
            ) from error
        except InvalidResearchStateError as error:
            raise HTTPException(
                status_code=409, detail="Research plan unavailable."
            ) from error

    @app.post("/v1/research-runs/{research_run_id}/plan/revisions")
    def revise_research_plan(
        research_run_id: str, request: ResearchPlanRevisionRequest
    ) -> StoredResearchRun:
        try:
            return require_research_service().revise_plan(research_run_id, request.note)
        except ResearchRunNotFoundError as error:
            raise HTTPException(
                status_code=404, detail="Research run not found."
            ) from error
        except InvalidResearchStateError as error:
            raise HTTPException(
                status_code=409, detail="Research lifecycle conflict."
            ) from error
        except (ResearchRunError, ValueError) as error:
            raise HTTPException(
                status_code=503, detail="Research plan revision unavailable."
            ) from error

    @app.post("/v1/research-runs/{research_run_id}/plan/approval")
    def approve_research_plan(research_run_id: str) -> StoredResearchRun:
        try:
            return require_research_service().approve_plan(research_run_id)
        except ResearchRunNotFoundError as error:
            raise HTTPException(
                status_code=404, detail="Research run not found."
            ) from error
        except InvalidResearchStateError as error:
            raise HTTPException(
                status_code=409, detail="Research lifecycle conflict."
            ) from error

    @app.post("/v1/research-runs/{research_run_id}/implementation-plan")
    def generate_research_implementation_plan(
        research_run_id: str,
    ) -> StoredResearchRun:
        try:
            return require_research_service().generate_implementation_plan(
                research_run_id
            )
        except ResearchRunNotFoundError as error:
            raise HTTPException(
                status_code=404, detail="Research run not found."
            ) from error
        except InvalidResearchStateError as error:
            raise HTTPException(
                status_code=409, detail="Research lifecycle conflict."
            ) from error
        except (ResearchRunError, ValueError) as error:
            raise HTTPException(
                status_code=503, detail="Research implementation planning unavailable."
            ) from error

    @app.get("/v1/research-runs/{research_run_id}/implementation-plan")
    def get_research_implementation_plan(research_run_id: str):
        try:
            return require_research_service().get_implementation_plan(research_run_id)
        except ResearchRunNotFoundError as error:
            raise HTTPException(
                status_code=404, detail="Research run not found."
            ) from error
        except InvalidResearchStateError as error:
            raise HTTPException(
                status_code=409, detail="Research implementation plan unavailable."
            ) from error

    @app.post("/v1/research-runs/{research_run_id}/implementation-package")
    def generate_research_implementation_package(
        research_run_id: str,
    ) -> StoredResearchRun:
        try:
            return require_research_service().generate_implementation_package(
                research_run_id
            )
        except ResearchRunNotFoundError as error:
            raise HTTPException(
                status_code=404, detail="Research run not found."
            ) from error
        except InvalidResearchStateError as error:
            raise HTTPException(
                status_code=409, detail="Research lifecycle conflict."
            ) from error
        except (ResearchRunError, ValueError) as error:
            raise HTTPException(
                status_code=503,
                detail="Research implementation generation unavailable.",
            ) from error

    @app.get("/v1/research-runs/{research_run_id}/implementation-package")
    def get_research_implementation_package(research_run_id: str):
        try:
            return require_research_service().get_implementation_package(
                research_run_id
            )
        except ResearchRunNotFoundError as error:
            raise HTTPException(
                status_code=404, detail="Research run not found."
            ) from error
        except InvalidResearchStateError as error:
            raise HTTPException(
                status_code=409, detail="Research implementation package unavailable."
            ) from error

    @app.get("/v1/research-runs/{research_run_id}/result-guide")
    def get_research_result_guide(research_run_id: str):
        try:
            return {
                "result_guide": require_research_service().prepare_result_submission(
                    research_run_id
                )
            }
        except ResearchRunNotFoundError as error:
            raise HTTPException(
                status_code=404, detail="Research run not found."
            ) from error
        except InvalidResearchStateError as error:
            raise HTTPException(
                status_code=409, detail="Research lifecycle conflict."
            ) from error

    @app.post("/v1/research-runs/{research_run_id}/results")
    def submit_research_results(research_run_id: str, submission: dict):
        from ai_agent_project.agent.research import ResearchResultSubmission

        try:
            return require_research_service().submit_results(
                research_run_id, ResearchResultSubmission.model_validate(submission)
            )
        except ResearchRunNotFoundError as error:
            raise HTTPException(
                status_code=404, detail="Research run not found."
            ) from error
        except InvalidResearchStateError as error:
            raise HTTPException(
                status_code=409, detail="Research lifecycle conflict."
            ) from error
        except ValueError as error:
            raise HTTPException(
                status_code=422, detail="Invalid result submission."
            ) from error

    @app.get("/v1/research-runs/{research_run_id}/results")
    def get_research_results(research_run_id: str):
        try:
            return require_research_service().get_results(research_run_id)
        except ResearchRunNotFoundError as error:
            raise HTTPException(
                status_code=404, detail="Research run not found."
            ) from error
        except ResearchResultsNotProvidedError as error:
            raise HTTPException(
                status_code=409, detail="Research results not provided."
            ) from error

    @app.post("/v1/research-runs/{research_run_id}/analysis")
    def analyze_research_results(research_run_id: str):
        try:
            return require_research_service().analyze_results(research_run_id)
        except ResearchRunNotFoundError as error:
            raise HTTPException(
                status_code=404, detail="Research run not found."
            ) from error
        except (InvalidResearchStateError, ResearchResultsNotProvidedError) as error:
            raise HTTPException(
                status_code=409, detail="Research results not ready for analysis."
            ) from error
        except (ResearchRunError, ValueError) as error:
            raise HTTPException(
                status_code=503, detail="Research analysis unavailable."
            ) from error

    @app.get("/v1/research-runs/{research_run_id}/analysis")
    def get_research_analysis(research_run_id: str):
        try:
            return require_research_service().get_result_analysis(research_run_id)
        except ResearchRunNotFoundError as error:
            raise HTTPException(
                status_code=404, detail="Research run not found."
            ) from error
        except InvalidResearchStateError as error:
            raise HTTPException(
                status_code=409, detail="Research analysis unavailable."
            ) from error

    @app.post("/v1/research-runs/{research_run_id}/synthesis")
    def generate_research_synthesis(research_run_id: str) -> StoredResearchRun:
        try:
            return require_research_service().generate_synthesis(research_run_id)
        except ResearchRunNotFoundError as error:
            raise HTTPException(
                status_code=404, detail="Research run not found."
            ) from error
        except InvalidResearchStateError as error:
            raise HTTPException(
                status_code=409, detail="Research synthesis lifecycle conflict."
            ) from error
        except (ResearchRunError, ValueError) as error:
            raise HTTPException(
                status_code=503, detail="Research synthesis unavailable."
            ) from error

    @app.get("/v1/research-runs/{research_run_id}/synthesis")
    def get_research_synthesis(research_run_id: str):
        try:
            return require_research_service().get_synthesis(research_run_id)
        except ResearchRunNotFoundError as error:
            raise HTTPException(
                status_code=404, detail="Research run not found."
            ) from error
        except InvalidResearchStateError as error:
            raise HTTPException(
                status_code=409, detail="Research synthesis unavailable."
            ) from error

    @app.post("/v1/research-runs/{research_run_id}/paper-materials")
    def generate_research_paper_materials(research_run_id: str) -> StoredResearchRun:
        try:
            return require_research_service().generate_paper_materials(research_run_id)
        except ResearchRunNotFoundError as error:
            raise HTTPException(
                status_code=404, detail="Research run not found."
            ) from error
        except InvalidResearchStateError as error:
            raise HTTPException(
                status_code=409, detail="Research paper materials lifecycle conflict."
            ) from error
        except (ResearchRunError, ValueError) as error:
            raise HTTPException(
                status_code=503, detail="Research paper materials unavailable."
            ) from error

    @app.get("/v1/research-runs/{research_run_id}/paper-materials")
    def get_research_paper_materials(research_run_id: str):
        try:
            return require_research_service().get_paper_materials(research_run_id)
        except ResearchRunNotFoundError as error:
            raise HTTPException(
                status_code=404, detail="Research run not found."
            ) from error
        except InvalidResearchStateError as error:
            raise HTTPException(
                status_code=409, detail="Research paper materials unavailable."
            ) from error

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

    @app.post(
        "/v1/project-runs/upgrades",
        response_model=StoredProjectRun,
        status_code=status.HTTP_201_CREATED,
    )
    def create_upgrade_project(
        request: CreateUpgradeProjectRequest,
    ) -> StoredProjectRun:
        try:
            return project_application_service.create_upgrade_project(
                request.request_text, project_title=request.project_title
            )
        except ProjectRunError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Upgrade project creation failed.",
            ) from error

    @app.get(
        "/v1/project-runs/{project_run_id}/analysis", response_model=UpgradeContext
    )
    def get_upgrade_analysis(project_run_id: str) -> UpgradeContext:
        try:
            return project_application_service.get_analysis(project_run_id)
        except ProjectRunNotFoundError as error:
            raise HTTPException(
                status_code=404, detail="Project run not found."
            ) from error
        except ProjectRunError as error:
            raise HTTPException(
                status_code=409, detail="Upgrade analysis unavailable."
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
