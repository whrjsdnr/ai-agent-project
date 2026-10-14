"""Provider-free exact artifact selection and read-only reference validation."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from ai_agent_project.agent.project_artifact import (
    ProjectArtifactSource,
    ProjectArtifactType,
)
from ai_agent_project.agent.project_artifact_application import (
    ProjectArtifactError,
    ProjectArtifactNotFoundError,
    ProjectArtifactService,
)
from ai_agent_project.agent.project_artifact_rendering import (
    canonical_artifact_content_bytes,
)
from ai_agent_project.agent.project_handoff import (
    SUPPORTED_HANDOFF_ARTIFACTS,
    ProjectHandoff,
    ProjectHandoffList,
    ProjectHandoffPurpose,
    ProjectHandoffStatus,
    ProjectHandoffView,
)
from ai_agent_project.agent.project_session import ProjectStatus
from ai_agent_project.agent.project_session_application import (
    ProjectSessionNotFoundError,
    ProjectSessionService,
    ResearchRunReader,
)
from ai_agent_project.agent.research import WorkMode


class ProjectHandoffError(Exception):
    """Selection or storage cannot safely satisfy the handoff contract."""


class ProjectHandoffAlreadyExistsError(ProjectHandoffError):
    """Create-once persistence refused an existing identity."""


class ProjectHandoffStore(Protocol):
    def create(self, handoff: ProjectHandoff) -> None: ...

    def get(self, handoff_id: str) -> ProjectHandoff | None: ...

    def list_for_project(self, project_id: str) -> tuple[ProjectHandoff, ...]: ...


class InMemoryProjectHandoffStore:
    def __init__(self) -> None:
        self._handoffs: dict[str, ProjectHandoff] = {}

    def create(self, handoff: ProjectHandoff) -> None:
        if handoff.handoff_id in self._handoffs:
            raise ProjectHandoffAlreadyExistsError("Handoff already exists")
        self._handoffs[handoff.handoff_id] = handoff

    def get(self, handoff_id: str) -> ProjectHandoff | None:
        return self._handoffs.get(handoff_id)

    def list_for_project(self, project_id: str) -> tuple[ProjectHandoff, ...]:
        return tuple(
            sorted(
                (h for h in self._handoffs.values() if h.project_id == project_id),
                key=lambda h: (h.created_at, h.handoff_id),
            )
        )


class ProjectHandoffService:
    """Record one explicit selection; never invoke either domain's operations."""

    def __init__(
        self,
        project_sessions: ProjectSessionService,
        artifacts: ProjectArtifactService,
        store: ProjectHandoffStore,
        research_reader: ResearchRunReader | None = None,
    ) -> None:
        self._project_sessions = project_sessions
        self._artifacts = artifacts
        self._store = store
        self._research_reader = research_reader

    def register(
        self, project_id: str, artifact_id: str, purpose: ProjectHandoffPurpose
    ) -> ProjectHandoff:
        try:
            project = self._project_sessions.get_project(project_id).project
        except ProjectSessionNotFoundError as error:
            # Keep the handoff boundary provider-free and expose one stable error
            # type to CLI/API callers without leaking session implementation errors.
            raise ProjectHandoffError(f"Project not found: {project_id}") from error
        if project.status is not ProjectStatus.ACTIVE:
            raise ProjectHandoffError("Handoff registration requires an active project")
        if project.work_mode is not WorkMode.HYBRID:
            raise ProjectHandoffError("Handoff registration requires a Hybrid project")
        if purpose != ProjectHandoffPurpose.DEVELOPER_BOOTSTRAP_CONTEXT:
            raise ProjectHandoffError("Unsupported handoff purpose")
        if project.research_run_id is None:
            raise ProjectHandoffError("Handoff requires a linked Researcher run")
        run = self._reader().get(project.research_run_id)
        if run is None:
            raise ProjectHandoffError(
                f"Linked Researcher run not found: {project.research_run_id}"
            )
        # Ownership must be established by the linked catalog, never ID parsing.
        try:
            artifact = self._artifacts.get_artifact(project_id, artifact_id)
        except ProjectArtifactError as error:
            raise ProjectHandoffError(
                f"Project artifact not found: {artifact_id}"
            ) from error
        descriptor = artifact.descriptor
        if (
            descriptor.source_domain is not ProjectArtifactSource.RESEARCHER
            or descriptor.source_run_id != project.research_run_id
        ):
            raise ProjectHandoffError("Handoff source must be the linked Researcher")
        if descriptor.artifact_type not in SUPPORTED_HANDOFF_ARTIFACTS:
            raise ProjectHandoffError(
                f"Unsupported handoff artifact type: {descriptor.artifact_type.value}"
            )
        if descriptor.artifact_type is ProjectArtifactType.RESEARCH_PLAN_REVISION:
            revisions = run.plan_revision_state
            if (
                revisions is None
                or not revisions.approved
                or not isinstance(artifact.content, dict)
                or artifact.content.get("version") != revisions.active_version
                or artifact.content.get("plan")
                != revisions.active_plan.model_dump(mode="json")
            ):
                raise ProjectHandoffError(
                    "Research plan handoff requires the exact approved revision"
                )
        digest = hashlib.sha256(
            canonical_artifact_content_bytes(artifact.content)
        ).hexdigest()
        # Stable application-owned IDs make concurrent identical registrations
        # converge through create-once stores, without an index or second write.
        identity = json.dumps(
            [project_id, descriptor.source_run_id, artifact_id, digest, purpose],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        handoff = ProjectHandoff(
            handoff_id=str(
                uuid5(NAMESPACE_URL, f"ai-agent:project-handoff:{identity}")
            ),
            project_id=project_id,
            source_domain=ProjectArtifactSource.RESEARCHER,
            source_run_id=descriptor.source_run_id,
            artifact_id=artifact_id,
            content_sha256=digest,
            purpose=purpose,
            created_at=datetime.now(UTC),
        )
        existing = self._store.get(handoff.handoff_id)
        if existing is None:
            try:
                self._store.create(handoff)
                return handoff
            except ProjectHandoffAlreadyExistsError:
                existing = self._store.get(handoff.handoff_id)
        if existing is None or existing.model_dump(exclude={"created_at"}) != (
            handoff.model_dump(exclude={"created_at"})
        ):
            raise ProjectHandoffError(
                "Stored handoff identity conflicts with selection"
            )
        return existing

    # Explicit alias for callers that model this operation as create-once
    # persistence rather than domain registration.
    def create(
        self, project_id: str, artifact_id: str, purpose: ProjectHandoffPurpose
    ) -> ProjectHandoff:
        return self.register(project_id, artifact_id, purpose)

    def list_handoffs(self, project_id: str) -> ProjectHandoffList:
        try:
            project = self._project_sessions.get_project(project_id).project
        except ProjectSessionNotFoundError as error:
            raise ProjectHandoffError(f"Project not found: {project_id}") from error
        views = []
        for handoff in self._store.list_for_project(project_id):
            descriptor = None
            if project.research_run_id != handoff.source_run_id:
                status = ProjectHandoffStatus.SOURCE_REBOUND
            elif self._reader().get(handoff.source_run_id) is None:
                status = ProjectHandoffStatus.SOURCE_MISSING
            else:
                try:
                    artifact = self._artifacts.get_artifact(
                        project_id, handoff.artifact_id
                    )
                except ProjectArtifactNotFoundError:
                    status = ProjectHandoffStatus.ARTIFACT_MISSING
                else:
                    descriptor = artifact.descriptor
                    digest = hashlib.sha256(
                        canonical_artifact_content_bytes(artifact.content)
                    ).hexdigest()
                    status = (
                        ProjectHandoffStatus.AVAILABLE
                        if digest == handoff.content_sha256
                        and descriptor.source_run_id == handoff.source_run_id
                        and descriptor.source_domain is handoff.source_domain
                        else ProjectHandoffStatus.CONTENT_MISMATCH
                    )
            views.append(
                ProjectHandoffView(
                    handoff=handoff, status=status, source_artifact=descriptor
                )
            )
        return ProjectHandoffList(project_id=project_id, handoffs=tuple(views))

    def _reader(self) -> ResearchRunReader:
        if self._research_reader is None:
            raise ProjectHandoffError("Researcher run reader is not configured")
        return self._research_reader
