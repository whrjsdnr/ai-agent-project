"""Focused Phase 5A handoff-domain tests."""

from datetime import UTC, datetime

import pytest

from ai_agent_project.agent.project_artifact import (
    ProjectArtifactDescriptor,
    ProjectArtifactSource,
    ProjectArtifactType,
    ProjectArtifactView,
)
from ai_agent_project.agent.project_handoff import (
    ProjectHandoffPurpose,
    ProjectHandoffStatus,
)
from ai_agent_project.agent.project_handoff_application import (
    InMemoryProjectHandoffStore,
    ProjectHandoffError,
    ProjectHandoffService,
)
from ai_agent_project.agent.project_session import (
    ProjectModeProposal,
    ProjectSession,
    ProjectStatus,
)
from ai_agent_project.agent.project_session_application import (
    InMemoryProjectSessionStore,
    ProjectSessionService,
)
from ai_agent_project.agent.research import WorkMode
from ai_agent_project.agent.upgrade import ProjectMode


class _Reader:
    def __init__(self, runs: set[str] | None = None) -> None:
        self.runs = {"research-1"} if runs is None else runs

    def get(self, run_id: str) -> object | None:
        return object() if run_id in self.runs else None


class _Artifacts:
    def __init__(self, entries: dict[str, ProjectArtifactView]) -> None:
        self.entries = entries

    def get_artifact(self, project_id: str, artifact_id: str) -> ProjectArtifactView:
        del project_id
        try:
            return self.entries[artifact_id]
        except KeyError as error:
            from ai_agent_project.agent.project_artifact_application import (
                ProjectArtifactNotFoundError,
            )

            raise ProjectArtifactNotFoundError(artifact_id) from error


def _project(
    *,
    work_mode: WorkMode = WorkMode.HYBRID,
    status: ProjectStatus = ProjectStatus.ACTIVE,
    research_run_id: str | None = "research-1",
) -> ProjectSession:
    now = datetime.now(UTC)
    proposal = ProjectModeProposal(
        proposed_work_mode=WorkMode.HYBRID,
        proposed_project_mode=ProjectMode.NEW,
        rationale="test",
    )
    return ProjectSession(
        project_id="project-1",
        title="Test",
        original_request="Test request",
        status=status,
        mode_proposal=proposal,
        work_mode=None
        if status is ProjectStatus.AWAITING_MODE_CONFIRMATION
        else work_mode,
        project_mode=None
        if status is ProjectStatus.AWAITING_MODE_CONFIRMATION
        else ProjectMode.NEW,
        developer_run_id=None,
        research_run_id=None
        if status is ProjectStatus.AWAITING_MODE_CONFIRMATION
        else research_run_id,
        created_at=now,
        updated_at=now,
    )


def _service(
    *,
    artifact_type: ProjectArtifactType = ProjectArtifactType.RESEARCH_SYNTHESIS,
    content: dict[str, object] | None = None,
    project: ProjectSession | None = None,
    run_id: str = "research-1",
    artifact_id: str = "artifact-1",
    reader: _Reader | None = None,
) -> tuple[ProjectHandoffService, InMemoryProjectHandoffStore]:
    sessions = InMemoryProjectSessionStore()
    project = project or _project()
    sessions.create(project.project_id, project)
    descriptor = ProjectArtifactDescriptor(
        artifact_id=artifact_id,
        artifact_type=artifact_type,
        source_domain=ProjectArtifactSource.RESEARCHER,
        source_run_id=run_id,
        source_version="v1",
        title="Artifact",
        media_types=("application/json",),
    )
    artifacts = _Artifacts(
        {
            artifact_id: ProjectArtifactView(
                descriptor=descriptor, content=content or {"x": 1}
            )
        }
    )
    store = InMemoryProjectHandoffStore()
    service = ProjectHandoffService(
        ProjectSessionService(sessions), artifacts, store, reader or _Reader()
    )
    return service, store


def test_registration_is_trusted_deterministic_and_idempotent() -> None:
    service, store = _service(content={"body": "hello"})
    first = service.register(
        "project-1", "artifact-1", ProjectHandoffPurpose.DEVELOPER_BOOTSTRAP_CONTEXT
    )
    second = service.register(
        "project-1", "artifact-1", ProjectHandoffPurpose.DEVELOPER_BOOTSTRAP_CONTEXT
    )

    assert second == first
    assert first.source_domain is ProjectArtifactSource.RESEARCHER
    assert first.source_run_id == "research-1"
    assert (
        first.content_sha256
        == "1da63ae1d1c64f4549cece58555b23ef253aa7bb2c5ca6c48c12918863cff51a"
    )
    assert "body" not in first.model_dump()
    assert len(store.list_for_project("project-1")) == 1


def test_different_artifact_version_does_not_collapse() -> None:
    service, store = _service(content={"x": 1})
    first = service.register(
        "project-1", "artifact-1", ProjectHandoffPurpose.DEVELOPER_BOOTSTRAP_CONTEXT
    )
    service._artifacts.entries["artifact-2"] = ProjectArtifactView(
        descriptor=first_descriptor("artifact-2"), content={"x": 2}
    )
    second = service.register(
        "project-1", "artifact-2", ProjectHandoffPurpose.DEVELOPER_BOOTSTRAP_CONTEXT
    )
    assert first.handoff_id != second.handoff_id
    assert len(store.list_for_project("project-1")) == 2


def first_descriptor(artifact_id: str) -> ProjectArtifactDescriptor:
    return ProjectArtifactDescriptor(
        artifact_id=artifact_id,
        artifact_type=ProjectArtifactType.RESEARCH_SYNTHESIS,
        source_domain=ProjectArtifactSource.RESEARCHER,
        source_run_id="research-1",
        source_version="v1",
        title="Artifact",
        media_types=("application/json",),
    )


@pytest.mark.parametrize(
    "artifact_type",
    [
        ProjectArtifactType.RESEARCH_IMPLEMENTATION_PLAN,
        ProjectArtifactType.RESEARCH_GENERATED_FILE,
        ProjectArtifactType.RESEARCH_RESULT_ANALYSIS,
        ProjectArtifactType.RESEARCH_SYNTHESIS,
    ],
)
def test_supported_artifact_types_register(artifact_type: ProjectArtifactType) -> None:
    service, _ = _service(artifact_type=artifact_type)
    assert service.register(
        "project-1", "artifact-1", ProjectHandoffPurpose.DEVELOPER_BOOTSTRAP_CONTEXT
    )


@pytest.mark.parametrize(
    "artifact_type",
    [
        ProjectArtifactType.RESEARCH_IMPLEMENTATION_PACKAGE,
        ProjectArtifactType.PAPER_MATERIALS,
        ProjectArtifactType.SPECIFICATION,
        ProjectArtifactType.EXECUTION_STATE,
        ProjectArtifactType.RESEARCH_PLAN,
    ],
)
def test_unsupported_artifacts_are_rejected(artifact_type: ProjectArtifactType) -> None:
    service, _ = _service(artifact_type=artifact_type)
    with pytest.raises(ProjectHandoffError):
        service.register(
            "project-1", "artifact-1", ProjectHandoffPurpose.DEVELOPER_BOOTSTRAP_CONTEXT
        )


@pytest.mark.parametrize("mode", [WorkMode.DEVELOPER, WorkMode.RESEARCHER])
def test_non_hybrid_projects_are_rejected(mode: WorkMode) -> None:
    service, _ = _service(project=_project(work_mode=mode))
    with pytest.raises(ProjectHandoffError):
        service.register(
            "project-1", "artifact-1", ProjectHandoffPurpose.DEVELOPER_BOOTSTRAP_CONTEXT
        )


@pytest.mark.parametrize(
    "status", [ProjectStatus.AWAITING_MODE_CONFIRMATION, ProjectStatus.COMPLETED]
)
def test_inactive_projects_are_rejected(status: ProjectStatus) -> None:
    service, _ = _service(project=_project(status=status))
    with pytest.raises(ProjectHandoffError):
        service.register(
            "project-1", "artifact-1", ProjectHandoffPurpose.DEVELOPER_BOOTSTRAP_CONTEXT
        )


def test_ownership_and_missing_source_are_rejected() -> None:
    service, _ = _service(run_id="foreign-run")
    with pytest.raises(ProjectHandoffError):
        service.register(
            "project-1", "artifact-1", ProjectHandoffPurpose.DEVELOPER_BOOTSTRAP_CONTEXT
        )
    service, _ = _service(reader=_Reader(set()))
    with pytest.raises(ProjectHandoffError):
        service.register(
            "project-1", "artifact-1", ProjectHandoffPurpose.DEVELOPER_BOOTSTRAP_CONTEXT
        )
    service, _ = _service()
    with pytest.raises(ProjectHandoffError):
        service.register(
            "project-1", "fabricated", ProjectHandoffPurpose.DEVELOPER_BOOTSTRAP_CONTEXT
        )


def test_status_rebound_missing_and_mismatch_without_fallback() -> None:
    service, store = _service(content={"x": 1})
    handoff = service.register(
        "project-1", "artifact-1", ProjectHandoffPurpose.DEVELOPER_BOOTSTRAP_CONTEXT
    )
    assert (
        service.list_handoffs("project-1").handoffs[0].status
        is ProjectHandoffStatus.AVAILABLE
    )
    project_service = service._project_sessions
    project_service._store.replace("project-1", _project(research_run_id="new-run"))
    assert (
        service.list_handoffs("project-1").handoffs[0].status
        is ProjectHandoffStatus.SOURCE_REBOUND
    )
    project_service._store.replace("project-1", _project())
    service._artifacts.entries["artifact-1"] = ProjectArtifactView(
        descriptor=first_descriptor("artifact-1"), content={"x": 2}
    )
    assert (
        service.list_handoffs("project-1").handoffs[0].status
        is ProjectHandoffStatus.CONTENT_MISMATCH
    )
    del service._artifacts.entries["artifact-1"]
    assert (
        service.list_handoffs("project-1").handoffs[0].status
        is ProjectHandoffStatus.ARTIFACT_MISSING
    )
    assert store.get(handoff.handoff_id) == handoff


def test_completed_project_existing_handoff_remains_listable() -> None:
    service, _ = _service()
    service.register(
        "project-1", "artifact-1", ProjectHandoffPurpose.DEVELOPER_BOOTSTRAP_CONTEXT
    )
    service._project_sessions._store.replace(
        "project-1", _project(status=ProjectStatus.COMPLETED)
    )
    assert (
        service.list_handoffs("project-1").handoffs[0].status
        is ProjectHandoffStatus.AVAILABLE
    )
