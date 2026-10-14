"""Provider-free verification of Phase 5A handoffs for later bootstrap use."""

from __future__ import annotations

import hashlib
from typing import Protocol

from ai_agent_project.agent.project_artifact import (
    ProjectArtifactSource,
)
from ai_agent_project.agent.project_artifact_application import (
    ProjectArtifactError,
    ProjectArtifactNotFoundError,
)
from ai_agent_project.agent.project_artifact_rendering import (
    canonical_artifact_content_bytes,
)
from ai_agent_project.agent.project_handoff import (
    SUPPORTED_HANDOFF_ARTIFACTS,
    ProjectHandoff,
    ProjectHandoffPurpose,
    VerifiedResearchContext,
)
from ai_agent_project.agent.project_session import ProjectStatus
from ai_agent_project.agent.project_session_application import (
    ProjectSessionNotFoundError,
)
from ai_agent_project.agent.research import WorkMode


class ProjectHandoffConsumptionError(ValueError):
    """Raised when an immutable handoff cannot be safely consumed."""


class _ProjectSessions(Protocol):
    def get_project(self, project_id: str): ...


class _HandoffStore(Protocol):
    def get(self, handoff_id: str) -> ProjectHandoff | None: ...


class _ArtifactService(Protocol):
    def get_artifact(self, project_id: str, artifact_id: str): ...


class _ResearchReader(Protocol):
    def get(self, run_id: str): ...


class ProjectHandoffConsumptionService:
    """Resolve one exact available handoff without mutating any store."""

    def __init__(
        self,
        project_sessions: _ProjectSessions,
        artifacts: _ArtifactService,
        handoffs: _HandoffStore,
        research_reader: _ResearchReader,
    ) -> None:
        self._project_sessions = project_sessions
        self._artifacts = artifacts
        self._handoffs = handoffs
        self._research_reader = research_reader

    def resolve_for_developer_bootstrap(
        self, project_id: str, handoff_id: str
    ) -> VerifiedResearchContext:
        try:
            project = self._project_sessions.get_project(project_id).project
        except ProjectSessionNotFoundError as error:
            raise ProjectHandoffConsumptionError(
                f"Project not found: {project_id}"
            ) from error
        if project.status is not ProjectStatus.ACTIVE:
            raise ProjectHandoffConsumptionError("Project must be active")
        if project.work_mode is not WorkMode.HYBRID:
            raise ProjectHandoffConsumptionError("Project must be Hybrid")
        if project.research_run_id is None:
            raise ProjectHandoffConsumptionError("Project has no linked Researcher run")

        handoff = self._handoffs.get(handoff_id)
        if handoff is None:
            raise ProjectHandoffConsumptionError(f"Handoff not found: {handoff_id}")
        if handoff.project_id != project_id:
            raise ProjectHandoffConsumptionError("Handoff belongs to another project")
        if handoff.purpose is not ProjectHandoffPurpose.DEVELOPER_BOOTSTRAP_CONTEXT:
            raise ProjectHandoffConsumptionError("Unsupported handoff purpose")
        if project.research_run_id != handoff.source_run_id:
            raise ProjectHandoffConsumptionError("Handoff source is rebound")
        if self._research_reader.get(handoff.source_run_id) is None:
            raise ProjectHandoffConsumptionError("Handoff source is missing")

        try:
            artifact = self._artifacts.get_artifact(project_id, handoff.artifact_id)
        except ProjectArtifactNotFoundError as error:
            raise ProjectHandoffConsumptionError(
                "Handoff artifact is missing"
            ) from error
        except ProjectArtifactError as error:
            raise ProjectHandoffConsumptionError(
                "Handoff artifact cannot be resolved"
            ) from error
        descriptor = artifact.descriptor
        if descriptor.source_domain is not ProjectArtifactSource.RESEARCHER:
            raise ProjectHandoffConsumptionError(
                "Handoff artifact is not from Researcher"
            )
        if descriptor.source_run_id != handoff.source_run_id:
            raise ProjectHandoffConsumptionError("Handoff artifact source run mismatch")
        if descriptor.artifact_id != handoff.artifact_id:
            raise ProjectHandoffConsumptionError("Handoff artifact ID mismatch")
        if descriptor.artifact_type not in SUPPORTED_HANDOFF_ARTIFACTS:
            raise ProjectHandoffConsumptionError("Handoff artifact type is unsupported")
        digest = hashlib.sha256(
            canonical_artifact_content_bytes(artifact.content)
        ).hexdigest()
        if digest != handoff.content_sha256:
            raise ProjectHandoffConsumptionError("Handoff artifact content mismatch")
        return VerifiedResearchContext(
            handoff_id=handoff.handoff_id,
            project_id=project_id,
            artifact_id=descriptor.artifact_id,
            artifact_type=descriptor.artifact_type,
            source_run_id=descriptor.source_run_id,
            source_version=descriptor.source_version,
            content_sha256=digest,
            content=artifact.content,
        )


def resolve_for_developer_bootstrap(
    project_id: str,
    handoff_id: str,
    *,
    project_sessions: _ProjectSessions,
    artifacts: _ArtifactService,
    handoffs: _HandoffStore,
    research_reader: _ResearchReader,
) -> VerifiedResearchContext:
    """Functional facade for the trusted handoff-consumption operation."""
    return ProjectHandoffConsumptionService(
        project_sessions, artifacts, handoffs, research_reader
    ).resolve_for_developer_bootstrap(project_id, handoff_id)
