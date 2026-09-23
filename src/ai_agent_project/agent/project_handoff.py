"""Immutable, metadata-only selections for later explicit Developer bootstrap.

Selection does not approve, consume, copy, or execute an artifact. A digest
verifies later resolution; it does not archive content that has disappeared.
"""

from enum import StrEnum
from typing import TYPE_CHECKING, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from ai_agent_project.agent.project_artifact import (
    JsonValue,
    ProjectArtifactDescriptor,
    ProjectArtifactSource,
    ProjectArtifactType,
)

if TYPE_CHECKING:
    from ai_agent_project.agent.developer_bootstrap_context import (
        DeveloperBootstrapContext,
    )


class ProjectHandoffPurpose(StrEnum):
    DEVELOPER_BOOTSTRAP_CONTEXT = "developer-bootstrap-context"


SUPPORTED_HANDOFF_ARTIFACTS = frozenset(
    {
        ProjectArtifactType.RESEARCH_PLAN_REVISION,
        ProjectArtifactType.RESEARCH_IMPLEMENTATION_PLAN,
        ProjectArtifactType.RESEARCH_GENERATED_FILE,
        ProjectArtifactType.RESEARCH_RESULT_ANALYSIS,
        ProjectArtifactType.RESEARCH_SYNTHESIS,
    }
)


class ProjectHandoffStatus(StrEnum):
    AVAILABLE = "available"
    SOURCE_REBOUND = "source_rebound"
    SOURCE_MISSING = "source_missing"
    ARTIFACT_MISSING = "artifact_missing"
    CONTENT_MISMATCH = "content_mismatch"


class ProjectHandoffSelection(BaseModel):
    """Only user-controlled selection fields; source identity is resolved."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_id: str = Field(min_length=1)
    purpose: ProjectHandoffPurpose

    @field_validator("artifact_id")
    @classmethod
    def reject_blank_artifact(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Artifact ID must not be blank")
        return value


class ProjectHandoff(BaseModel):
    """Create-once trusted identity, with no artifact body or target-run state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    handoff_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    source_domain: Literal[ProjectArtifactSource.RESEARCHER]
    source_run_id: str = Field(min_length=1)
    artifact_id: str = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    purpose: ProjectHandoffPurpose
    created_at: AwareDatetime

    @field_validator("handoff_id", "project_id", "source_run_id", "artifact_id")
    @classmethod
    def reject_blank_identity(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Handoff identity must not be blank")
        return value


class ResearchBootstrapProvenance(BaseModel):
    """Immutable metadata linking a future Developer run to a handoff."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_id: str = Field(min_length=1)
    handoff_id: str = Field(min_length=1)
    research_run_id: str = Field(min_length=1)
    artifact_id: str = Field(min_length=1)
    artifact_type: ProjectArtifactType
    source_version: str = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator(
        "project_id", "handoff_id", "research_run_id", "artifact_id", "source_version"
    )
    @classmethod
    def reject_blank_provenance(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Bootstrap provenance values must not be blank")
        return value

    @classmethod
    def from_verified_context(
        cls, context: "VerifiedResearchContext"
    ) -> "ResearchBootstrapProvenance":
        return cls(
            project_id=context.project_id,
            handoff_id=context.handoff_id,
            research_run_id=context.source_run_id,
            artifact_id=context.artifact_id,
            artifact_type=context.artifact_type,
            source_version=context.source_version,
            content_sha256=context.content_sha256,
        )


class VerifiedResearchContext(BaseModel):
    """Exact, digest-verified Researcher content for a later bootstrap."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    handoff_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    artifact_id: str = Field(min_length=1)
    artifact_type: ProjectArtifactType
    source_run_id: str = Field(min_length=1)
    source_version: str = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    content: JsonValue

    def to_developer_context(self) -> "DeveloperBootstrapContext":
        """Convert verified content to the neutral Developer planning boundary."""
        from ai_agent_project.agent.developer_bootstrap_context import (
            DEVELOPER_BOOTSTRAP_CONTEXT_SOURCE,
            DeveloperBootstrapContext,
        )

        return DeveloperBootstrapContext(
            source_label=DEVELOPER_BOOTSTRAP_CONTEXT_SOURCE,
            artifact_type=self.artifact_type.value,
            source_version=self.source_version,
            content=self.content,
        )

    def to_provenance(self) -> ResearchBootstrapProvenance:
        return ResearchBootstrapProvenance(
            project_id=self.project_id,
            handoff_id=self.handoff_id,
            research_run_id=self.source_run_id,
            artifact_id=self.artifact_id,
            artifact_type=self.artifact_type,
            source_version=self.source_version,
            content_sha256=self.content_sha256,
        )


class ProjectHandoffView(BaseModel):
    """Derived availability of an immutable selection; never exposes content."""

    model_config = ConfigDict(frozen=True)

    handoff: ProjectHandoff
    status: ProjectHandoffStatus
    source_artifact: ProjectArtifactDescriptor | None = None


class ProjectHandoffList(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_id: str
    handoffs: tuple[ProjectHandoffView, ...]
