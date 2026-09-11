"""Immutable presentation data; no run objects, credentials or mutable JSON."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DesktopModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class DesktopPendingActionView(DesktopModel):
    action_type: str
    domain: str
    title: str
    description: str
    requires_payload: bool
    payload_kind: str | None


class DesktopProjectSummary(DesktopModel):
    project_id: str
    display_title: str
    status: str
    work_mode: str | None
    project_mode: str | None
    created_at: datetime
    developer_run_id: str | None
    researcher_run_id: str | None
    pending_actions: tuple[DesktopPendingActionView, ...]


class DesktopDirectionView(DesktopModel):
    direction_id: str
    title: str
    question: str


class DesktopLaneView(DesktopModel):
    domain: str
    bound: bool
    run_id: str | None
    status: str | None
    phase: str | None
    pending_action: DesktopPendingActionView | None
    selected_direction: str | None = None
    directions: tuple[DesktopDirectionView, ...] = ()
    approved_plan_version: int | None = None
    implementation_plan_version: int | None = None
    result_state: str | None = None
    synthesis_state: str | None = None
    # Resolver guidance only. The action service still authorizes each request.
    available_actions: tuple[str, ...]


class DesktopArtifactSummary(DesktopModel):
    artifact_id: str
    artifact_type: str
    source_domain: str
    source_run_id: str
    source_version: str
    title: str
    media_types: tuple[str, ...]


class DesktopArtifactView(DesktopModel):
    summary: DesktopArtifactSummary
    format: str
    content: str


class DesktopHandoffSummary(DesktopModel):
    bootstrap_available: bool = False
    handoff_id: str
    source_domain: str
    artifact_id: str
    artifact_type: str | None
    purpose: str
    created_at: datetime
    status: str


class DesktopProviderView(DesktopModel):
    provider_type: str
    base_url: str
    model: str
    timeout_seconds: float
    credential_configured: bool


class DesktopConnectionView(DesktopModel):
    success: bool
    message: str


class DesktopHybridView(DesktopModel):
    both_workflows_terminal: bool
    actionable_actions: tuple[DesktopPendingActionView, ...]


class DesktopProjectView(DesktopModel):
    project: DesktopProjectSummary
    proposed_work_mode: str
    proposed_project_mode: str
    developer: DesktopLaneView | None
    researcher: DesktopLaneView | None
    hybrid: DesktopHybridView | None
    artifacts: tuple[DesktopArtifactSummary, ...]
    handoffs: tuple[DesktopHandoffSummary, ...]


class DesktopDashboardView(DesktopModel):
    total_projects: int
    active_projects: int
    completed_projects: int
    awaiting_user_action_count: int
    recent_projects: tuple[DesktopProjectSummary, ...]
    provider: DesktopProviderView
