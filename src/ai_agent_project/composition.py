"""Shared server-independent production service composition."""

from pathlib import Path

from ai_agent_project.agent.acceptance_validator import AcceptanceValidator
from ai_agent_project.agent.checkpoint import (
    PhaseCheckpointService,
    ProgressReporter,
)
from ai_agent_project.agent.coding_service import (
    CodingAgentService,
)
from ai_agent_project.agent.phase_execution import PhaseExecutionService
from ai_agent_project.agent.project_application import (
    InMemoryProjectRunStore,
    ProjectApplicationService,
    ProjectRunStore,
)
from ai_agent_project.agent.project_execution import ProjectExecutionService
from ai_agent_project.agent.project_runner import ProjectRunner, UpgradeProjectRunner
from ai_agent_project.agent.project_session_application import (
    DeveloperRunReader,
    InMemoryProjectSessionStore,
    ProjectSessionService,
    ProjectSessionStore,
    ResearchRunReader,
)
from ai_agent_project.agent.research_application import (
    InMemoryResearchRunStore,
    ResearchApplicationService,
)
from ai_agent_project.agent.research_discovery import ResearchDiscoveryService
from ai_agent_project.agent.research_file_store import FileResearchRunStore
from ai_agent_project.agent.service import AgentService
from ai_agent_project.agent.workspace import FilesystemWorkspaceInspector
from ai_agent_project.agent.workspace_acceptance import WorkspaceAcceptanceValidator
from ai_agent_project.llm.config import ProviderConfig, ProviderConfigService
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


def _default_workspace_root() -> Path:
    """Return the project root containing the source tree."""
    return Path(__file__).resolve().parents[2]


def create_default_agent_service(
    workspace_root: Path | None = None, *, provider_config: ProviderConfig | None = None
) -> AgentService:
    """Build the default agent with OpenAI and workspace-scoped development tools."""
    provider_config = ProviderConfigService().resolve(provider_config)
    registry = ToolRegistry()
    resolved_workspace_root = workspace_root or _default_workspace_root()
    registry.register(CalculatorTool())
    registry.register(FileTool(resolved_workspace_root))
    registry.register(ShellTool(resolved_workspace_root))
    return AgentService(OpenAIClient(config=provider_config), registry)


def create_default_coding_agent_service(
    workspace_root: Path | None = None,
    *,
    provider_config: ProviderConfig | None = None,
    agent_service: AgentService | None = None,
    acceptance_validator: AcceptanceValidator | None = None,
) -> CodingAgentService:
    """Compose OpenAI parsing/planning with the generic default coding agent."""
    provider_config = ProviderConfigService().resolve(provider_config)
    return CodingAgentService(
        specification_parser=OpenAISpecificationParser(config=provider_config),
        planner=OpenAIImplementationPlanner(config=provider_config),
        agent_service=agent_service
        or create_default_agent_service(
            workspace_root, provider_config=provider_config
        ),
        acceptance_validator=acceptance_validator
        or WorkspaceAcceptanceValidator(workspace_root or _default_workspace_root()),
        workspace_inspector=FilesystemWorkspaceInspector(
            workspace_root or _default_workspace_root()
        ),
    )


def create_default_project_application_service(
    workspace_root: Path | None = None,
    *,
    provider_config: ProviderConfig | None = None,
    agent_service: AgentService | None = None,
    store: ProjectRunStore | None = None,
) -> ProjectApplicationService:
    """Compose production planning and lifecycle services with an injected store."""
    provider_config = ProviderConfigService().resolve(provider_config)
    resolved_workspace_root = workspace_root or _default_workspace_root()
    phase_execution_service = PhaseExecutionService(
        agent_service
        or create_default_agent_service(
            resolved_workspace_root, provider_config=provider_config
        ),
        WorkspaceAcceptanceValidator(resolved_workspace_root),
    )
    project_execution_service = ProjectExecutionService(
        phase_execution_service,
        ProgressReporter(),
        PhaseCheckpointService(),
    )
    project_runner = ProjectRunner(
        OpenAISpecificationParser(config=provider_config),
        FilesystemWorkspaceInspector(resolved_workspace_root),
        OpenAIImplementationPlanner(config=provider_config),
        OpenAIProjectPlanner(config=provider_config),
        project_execution_service,
    )
    upgrade_runner = UpgradeProjectRunner(
        FilesystemWorkspaceInspector(resolved_workspace_root),
        OpenAICodebaseAnalyzer(config=provider_config),
        OpenAIUpgradeAnalyzer(config=provider_config),
        OpenAIImplementationPlanner(config=provider_config),
        OpenAIProjectPlanner(config=provider_config),
        project_execution_service,
    )
    return ProjectApplicationService(
        project_runner,
        project_execution_service,
        store if store is not None else InMemoryProjectRunStore(),
        OpenAIProjectPlanReviser(config=provider_config),
        upgrade_runner,
    )


def create_default_project_session_service(
    *,
    provider_config: ProviderConfig | None = None,
    store: ProjectSessionStore | None = None,
    developer_run_reader: DeveloperRunReader | None = None,
    research_run_reader: ResearchRunReader | None = None,
) -> ProjectSessionService:
    """Compose proposal-only project-session orchestration."""
    provider_config = ProviderConfigService().resolve(provider_config)
    return ProjectSessionService(
        store if store is not None else InMemoryProjectSessionStore(),
        OpenAIProjectModeProposer(config=provider_config),
        developer_run_reader,
        research_run_reader,
    )


def create_default_research_application_service(
    workspace_root: Path | None = None,
    *,
    provider_config: ProviderConfig | None = None,
    store: InMemoryResearchRunStore | FileResearchRunStore | None = None,
) -> ResearchApplicationService:
    """Compose real OpenAI planning, retrieval, and synthesis without fallback."""
    provider_config = ProviderConfigService().resolve(provider_config)
    resolved_workspace_root = workspace_root or _default_workspace_root()
    discovery = ResearchDiscoveryService(
        OpenAIResearchQuestionPlanner(config=provider_config),
        OpenAIWebResearchSourceProvider(config=provider_config),
        OpenAIResearchEvidenceExtractor(config=provider_config),
        OpenAIResearchDiscoverySynthesizer(config=provider_config),
        FilesystemWorkspaceInspector(resolved_workspace_root),
    )
    return ResearchApplicationService(
        discovery,
        store if store is not None else InMemoryResearchRunStore(),
        OpenAIResearchPlanGenerator(config=provider_config),
        OpenAIResearchImplementationPlanner(config=provider_config),
        OpenAIResearchImplementationGenerator(config=provider_config),
        OpenAIResearchResultAnalyzer(config=provider_config),
        OpenAIResearchResultSynthesizer(config=provider_config),
        OpenAIResearchPaperMaterialsGenerator(config=provider_config),
    )
