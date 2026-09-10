"""Local composition and presentation-only selection state."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import SecretStr

from ai_agent_project.agent.hybrid_coordination_application import (
    HybridCoordinationService,
)
from ai_agent_project.agent.project_action_application import ProjectActionService
from ai_agent_project.agent.project_artifact_application import ProjectArtifactService
from ai_agent_project.agent.project_developer_bootstrap_application import (
    ProjectDeveloperBootstrapService,
)
from ai_agent_project.agent.project_file_store import (
    FileProjectRunStore,
    default_project_run_store_root,
)
from ai_agent_project.agent.project_handoff_application import ProjectHandoffService
from ai_agent_project.agent.project_handoff_consumption import (
    ProjectHandoffConsumptionService,
)
from ai_agent_project.agent.project_handoff_file_store import (
    FileProjectHandoffStore,
    default_project_handoff_store_root,
)
from ai_agent_project.agent.project_session_application import ProjectSessionService
from ai_agent_project.agent.project_session_file_store import (
    FileProjectStore,
    default_project_store_root,
)
from ai_agent_project.agent.research_file_store import (
    FileResearchRunStore,
    default_research_run_store_root,
)
from ai_agent_project.composition import (
    create_default_project_application_service,
    create_default_research_application_service,
)
from ai_agent_project.desktop import DesktopService
from ai_agent_project.improvement.service import build_improvement_service
from ai_agent_project.llm.config import ProviderConfig, ProviderConfigService
from ai_agent_project.llm.providers.openai_project_mode_proposer import (
    OpenAIProjectModeProposer,
)
from ai_agent_project.llm.runtime import provider_client_scope
from ai_agent_project.paths import desktop_workspace


@dataclass
class PresentationState:
    selected_project_id: str | None = None
    current_page: str = "Dashboard"


class SessionProviderConfigService(ProviderConfigService):
    """Runtime credential belongs to this application instance, never environment/JSON."""

    def __init__(self, path: Path | None = None) -> None:
        super().__init__(path)
        self._credential: SecretStr | None = None

    def save(self, config: ProviderConfig) -> None:
        super().save(config)
        if config.api_key is not None:
            self._credential = config.api_key

    def resolve(
        self, explicit: ProviderConfig | None = None, **kwargs: Any
    ) -> ProviderConfig:
        if explicit is None or explicit.api_key is None:
            kwargs.setdefault("api_key", self._credential)
        return super().resolve(explicit, **kwargs)


class LazyApplication:
    """Construct existing application services only for the requested call."""

    def __init__(self, factory: Callable[..., Any]) -> None:
        self.factory = factory

    def __getattr__(self, name: str) -> Callable[..., Any]:
        def invoke(*args: Any, **kwargs: Any) -> Any:
            with provider_client_scope():
                return getattr(self.factory(name, args), name)(*args, **kwargs)

        return invoke


def build_desktop_application(
    root: Path | None = None, workspace: Path | None = None
) -> DesktopService:
    workspace = workspace or (
        root / "workspaces" / "default" if root else desktop_workspace()
    )
    developers = FileProjectRunStore(
        root / "developers" if root else default_project_run_store_root(),
        workspace_root=workspace,
    )
    researchers = FileResearchRunStore(
        root / "researchers" if root else default_research_run_store_root()
    )
    provider = SessionProviderConfigService(
        root / "settings" / "llm.json" if root else None
    )
    sessions = ProjectSessionService(
        FileProjectStore(root / "projects" if root else default_project_store_root()),
        LazyApplication(
            lambda name, args: OpenAIProjectModeProposer(config=provider.resolve())
        ),
        developers,
        researchers,
    )
    improvements = build_improvement_service(
        root=root / "improvements" if root else None,
        developer_reader=developers,
        researcher_reader=researchers,
        projects=sessions,
        provider_config=provider.resolve,
    )
    developer = LazyApplication(
        lambda name, args: create_default_project_application_service(
            developers.workspace_root_for(args[0])
            if name == "execute_current_phase"
            else workspace,
            store=developers,
            provider_config=provider.resolve(),
            improvement_service=improvements,
        )
    )
    research = LazyApplication(
        lambda name, args: create_default_research_application_service(
            workspace,
            store=researchers,
            provider_config=provider.resolve(),
            improvement_service=improvements,
        )
    )
    artifacts = ProjectArtifactService(sessions, developers, researchers)
    handoff_store = FileProjectHandoffStore(
        root / "handoffs" if root else default_project_handoff_store_root()
    )
    return DesktopService(
        improvements=improvements,
        project_sessions=sessions,
        actions=ProjectActionService(sessions, developer, research),
        artifacts=artifacts,
        handoffs=ProjectHandoffService(sessions, artifacts, handoff_store, researchers),
        coordination=HybridCoordinationService(sessions, developers, researchers),
        provider_config=provider,
        developer_reader=developers,
        research_reader=researchers,
        bootstrap=ProjectDeveloperBootstrapService(
            sessions,
            ProjectHandoffConsumptionService(
                sessions, artifacts, handoff_store, researchers
            ),
            developer,
        ),
        developer_application=developer,
        research_application=research,
    )
