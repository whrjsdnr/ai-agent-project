"""Shallow, user-confirmed orchestration state above project and research runs."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ai_agent_project.agent.research import WorkMode
from ai_agent_project.agent.upgrade import ProjectMode


def _nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("Project session values must not be blank")
    return value


def _nonblank_optional(value: str | None) -> str | None:
    return None if value is None else _nonblank(value)


class ProjectStatus(StrEnum):
    AWAITING_MODE_CONFIRMATION = "awaiting_mode_confirmation"
    ACTIVE = "active"
    COMPLETED = "completed"


class ProjectPendingActionType(StrEnum):
    """Explicit human action derived from authoritative linked-run state."""

    CONFIRM_MODE = "confirm_mode"
    BIND_DEVELOPER_RUN = "bind_developer_run"
    BIND_RESEARCH_RUN = "bind_research_run"
    APPROVE_DEVELOPER_PLAN = "approve_developer_plan"
    CONTINUE_DEVELOPER = "continue_developer"
    SELECT_RESEARCH_DIRECTION = "select_research_direction"
    APPROVE_RESEARCH_PLAN = "approve_research_plan"
    PROVIDE_RESEARCH_RESULTS = "provide_research_results"
    CONTINUE_RESEARCHER = "continue_researcher"


class ProjectPendingAction(BaseModel):
    """Read-only orchestration guidance; it is never persisted as workflow state."""

    model_config = ConfigDict(frozen=True)

    action_type: ProjectPendingActionType
    message: str = Field(min_length=1)
    suggested_action: str = Field(min_length=1)
    developer_run_id: str | None = None
    research_run_id: str | None = None
    source_status: str | None = None


class ProjectModeProposal(BaseModel):
    """Advisory provider output; it never activates a project session."""

    model_config = ConfigDict(frozen=True)

    proposed_work_mode: WorkMode
    proposed_project_mode: ProjectMode
    rationale: str = Field(min_length=1)

    _validate_rationale = field_validator("rationale")(_nonblank)


class ProjectModeProposer(Protocol):
    def propose(self, original_request: str) -> ProjectModeProposal:
        """Propose independent work and project modes for a user request."""
        ...


class ProjectSession(BaseModel):
    """Persistent orchestration metadata; linked run state remains external."""

    model_config = ConfigDict(frozen=True)

    project_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    original_request: str = Field(min_length=1)
    status: ProjectStatus
    mode_proposal: ProjectModeProposal
    work_mode: WorkMode | None = None
    project_mode: ProjectMode | None = None
    developer_run_id: str | None = None
    research_run_id: str | None = None
    created_at: datetime
    updated_at: datetime

    _validate_required = field_validator("project_id", "title", "original_request")(
        _nonblank
    )
    _validate_optional = field_validator("developer_run_id", "research_run_id")(
        _nonblank_optional
    )

    @model_validator(mode="after")
    def validate_lifecycle(self) -> "ProjectSession":
        confirmed = self.work_mode is not None and self.project_mode is not None
        if self.status is ProjectStatus.AWAITING_MODE_CONFIRMATION:
            if (
                confirmed
                or self.developer_run_id is not None
                or self.research_run_id is not None
            ):
                raise ValueError(
                    "Awaiting confirmation project must not have active modes or bindings"
                )
        elif not confirmed:
            raise ValueError("Active or completed project requires confirmed modes")
        if self.updated_at < self.created_at:
            raise ValueError("Project session updated time cannot precede creation")
        return self

    @classmethod
    def awaiting_confirmation(
        cls,
        *,
        project_id: str,
        title: str,
        original_request: str,
        mode_proposal: ProjectModeProposal,
    ) -> "ProjectSession":
        now = datetime.now(UTC)
        return cls(
            project_id=project_id,
            title=title,
            original_request=original_request,
            status=ProjectStatus.AWAITING_MODE_CONFIRMATION,
            mode_proposal=mode_proposal,
            created_at=now,
            updated_at=now,
        )
