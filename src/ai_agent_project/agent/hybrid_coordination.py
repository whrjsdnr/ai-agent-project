"""Read-only models for independently coordinated Hybrid workflow lanes."""

from pydantic import BaseModel, ConfigDict

from ai_agent_project.agent.project_action_application import ProjectActionSource
from ai_agent_project.agent.project_session import ProjectPendingAction, ProjectStatus


class HybridCoordinationLane(BaseModel):
    """One authoritative workflow lane in a Hybrid ProjectSession."""

    model_config = ConfigDict(frozen=True)

    source_domain: ProjectActionSource
    run_id: str | None
    source_status: str | None
    pending_action: ProjectPendingAction | None
    terminal: bool


class HybridCoordinationView(BaseModel):
    """Derived Hybrid state; never persisted as ProjectSession state."""

    model_config = ConfigDict(frozen=True)

    project_id: str
    project_status: ProjectStatus
    developer: HybridCoordinationLane
    researcher: HybridCoordinationLane
    actionable_actions: tuple[ProjectPendingAction, ...]
    both_workflows_terminal: bool
