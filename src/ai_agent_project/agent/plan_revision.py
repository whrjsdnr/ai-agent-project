"""Immutable project-plan review and revision domain models."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_agent_project.agent.project import ProjectPlan, ProjectSpecification
from ai_agent_project.agent.workspace import WorkspaceSnapshot


class PlanReviewStatus(StrEnum):
    """Manual review lifecycle for a project plan before phase execution."""

    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"


class PlanRevision(BaseModel):
    """One immutable version of a project phase plan."""

    model_config = ConfigDict(frozen=True)

    version: int = Field(ge=1)
    plan: ProjectPlan
    feedback: str | None = None
    created_at: datetime


class PlanRevisionState(BaseModel):
    """Ordered immutable plan-review history with one active plan version."""

    model_config = ConfigDict(frozen=True)

    active_version: int = Field(ge=1)
    status: PlanReviewStatus
    revisions: tuple[PlanRevision, ...] = Field(min_length=1)

    @classmethod
    def from_plan(cls, plan: ProjectPlan) -> "PlanRevisionState":
        return cls(
            active_version=1,
            status=PlanReviewStatus.AWAITING_APPROVAL,
            revisions=(
                PlanRevision(
                    version=1,
                    plan=plan,
                    created_at=datetime.now(UTC),
                ),
            ),
        )

    @property
    def active_plan(self) -> ProjectPlan:
        return next(
            revision.plan
            for revision in self.revisions
            if revision.version == self.active_version
        )

    @model_validator(mode="after")
    def validate_history(self) -> "PlanRevisionState":
        versions = tuple(revision.version for revision in self.revisions)
        if versions != tuple(range(1, len(versions) + 1)):
            raise ValueError("Plan revision versions must be ordered and contiguous")
        if self.active_version != versions[-1]:
            raise ValueError("Active plan revision must be the latest revision")
        return self

    def revise(self, plan: ProjectPlan, feedback: str) -> "PlanRevisionState":
        """Append one pre-approval revision preserving the implementation plan."""
        normalized_feedback = feedback.strip()
        if not normalized_feedback:
            raise ValueError("Plan revision feedback must not be blank")
        if self.status is PlanReviewStatus.APPROVED:
            raise ValueError("An approved project plan cannot be revised")
        if plan.implementation_plan != self.active_plan.implementation_plan:
            raise ValueError("A plan revision must preserve the implementation plan")
        revision = PlanRevision(
            version=self.active_version + 1,
            plan=plan,
            feedback=normalized_feedback,
            created_at=datetime.now(UTC),
        )
        return self.model_copy(
            update={
                "active_version": revision.version,
                "revisions": (*self.revisions, revision),
            }
        )

    def approve(self) -> "PlanRevisionState":
        """Approve the active plan exactly once."""
        if self.status is PlanReviewStatus.APPROVED:
            raise ValueError("Project plan is already approved")
        return self.model_copy(update={"status": PlanReviewStatus.APPROVED})


class ProjectPlanReviser(Protocol):
    """Provider-neutral revision of phases over an unchanged implementation plan."""

    def revise(
        self,
        specification: ProjectSpecification,
        current_plan: ProjectPlan,
        feedback: str,
        workspace: WorkspaceSnapshot | None = None,
    ) -> ProjectPlan:
        """Return a validated regrouping of an existing implementation plan."""
        ...
