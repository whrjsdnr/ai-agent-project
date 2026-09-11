"""Derived artifact catalog and exact JSON inspection for linked project runs."""

import hashlib
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel

from ai_agent_project.agent.project_artifact import (
    JsonValue,
    ProjectArtifactCatalog,
    ProjectArtifactDescriptor,
    ProjectArtifactSource,
    ProjectArtifactType,
    ProjectArtifactView,
)
from ai_agent_project.agent.project_artifact_rendering import (
    canonical_artifact_content_bytes,
    supported_media_types,
)
from ai_agent_project.agent.project_runner import ProjectRun
from ai_agent_project.agent.project_session import ProjectSession, ProjectStatus
from ai_agent_project.agent.project_session_application import (
    ProjectSessionNotFoundError,
    StoredProjectSession,
)
from ai_agent_project.agent.research import ResearchRun, WorkMode


class ProjectArtifactError(Exception):
    """Base error for read-only project artifact operations."""


class ProjectArtifactNotFoundError(ProjectArtifactError):
    """Raised when a project or linked artifact cannot be resolved."""


class ProjectArtifactProjectReader(Protocol):
    def get_project(self, project_id: str) -> StoredProjectSession: ...


class ProjectArtifactDeveloperReader(Protocol):
    def get(self, run_id: str) -> ProjectRun | None: ...


class ProjectArtifactResearchReader(Protocol):
    def get(self, run_id: str) -> ResearchRun | None: ...


@dataclass(frozen=True)
class _ArtifactEntry:
    descriptor: ProjectArtifactDescriptor
    content: JsonValue


class ProjectArtifactService:
    """Read authoritative linked snapshots without progressing either workflow."""

    def __init__(
        self,
        project_reader: ProjectArtifactProjectReader,
        developer_reader: ProjectArtifactDeveloperReader | None = None,
        research_reader: ProjectArtifactResearchReader | None = None,
    ) -> None:
        self._project_reader = project_reader
        self._developer_reader = developer_reader
        self._research_reader = research_reader

    def list_artifacts(self, project_id: str) -> ProjectArtifactCatalog:
        entries = self._entries(project_id)
        return ProjectArtifactCatalog(
            project_id=project_id,
            artifacts=tuple(entry.descriptor for entry in entries),
        )

    def get_artifact(self, project_id: str, artifact_id: str) -> ProjectArtifactView:
        for entry in self._entries(project_id):
            if entry.descriptor.artifact_id == artifact_id:
                return ProjectArtifactView(
                    descriptor=entry.descriptor, content=entry.content
                )
        raise ProjectArtifactNotFoundError(f"Project artifact not found: {artifact_id}")

    def _entries(self, project_id: str) -> tuple[_ArtifactEntry, ...]:
        try:
            project = self._project_reader.get_project(project_id).project
        except ProjectSessionNotFoundError as error:
            raise ProjectArtifactNotFoundError(
                f"Project not found: {project_id}"
            ) from error
        if project.status is ProjectStatus.AWAITING_MODE_CONFIRMATION:
            return ()

        entries: list[_ArtifactEntry] = []
        if project.work_mode in {WorkMode.DEVELOPER, WorkMode.HYBRID}:
            entries.extend(self._developer_entries(project))
        if project.work_mode in {WorkMode.RESEARCHER, WorkMode.HYBRID}:
            entries.extend(self._research_entries(project))
        return tuple(entries)

    def _developer_entries(self, project: ProjectSession) -> list[_ArtifactEntry]:
        run_id = project.developer_run_id
        if run_id is None:
            return []
        if self._developer_reader is None:
            raise ProjectArtifactError("Developer run reader is not configured")
        run = self._developer_reader.get(run_id)
        if run is None:
            raise ProjectArtifactError(f"Linked Developer run not found: {run_id}")

        revision_state = run.plan_revision_state
        active_version = revision_state.active_version
        entries = [
            _entry(
                ProjectArtifactSource.DEVELOPER,
                run_id,
                ProjectArtifactType.SPECIFICATION,
                "v1",
                "Developer specification",
                run.specification,
            ),
            _entry(
                ProjectArtifactSource.DEVELOPER,
                run_id,
                ProjectArtifactType.PROJECT_SPECIFICATION,
                "v1",
                "Developer project specification",
                run.project_specification,
            ),
            _entry(
                ProjectArtifactSource.DEVELOPER,
                run_id,
                ProjectArtifactType.IMPLEMENTATION_PLAN,
                "v1",
                "Developer implementation plan",
                run.implementation_plan,
            ),
            _entry(
                ProjectArtifactSource.DEVELOPER,
                run_id,
                ProjectArtifactType.PROJECT_PLAN,
                f"v{active_version}",
                f"Developer project plan v{active_version}",
                run.project_plan,
            ),
        ]
        entries.extend(
            _entry(
                ProjectArtifactSource.DEVELOPER,
                run_id,
                ProjectArtifactType.PROJECT_PLAN_REVISION,
                f"v{revision.version}",
                f"Developer project plan revision v{revision.version}",
                revision,
            )
            for revision in sorted(
                revision_state.revisions, key=lambda item: item.version
            )
        )
        entries.extend(
            (
                _entry(
                    ProjectArtifactSource.DEVELOPER,
                    run_id,
                    ProjectArtifactType.PLAN_REVISION_HISTORY,
                    f"v{active_version}-{revision_state.status.value}",
                    "Developer plan revision history",
                    revision_state,
                ),
                _entry(
                    ProjectArtifactSource.DEVELOPER,
                    run_id,
                    ProjectArtifactType.EXECUTION_STATE,
                    _content_version(run.execution_state),
                    "Developer execution state",
                    run.execution_state,
                ),
            )
        )
        if run.upgrade_context is not None:
            entries.append(
                _entry(
                    ProjectArtifactSource.DEVELOPER,
                    run_id,
                    ProjectArtifactType.UPGRADE_CONTEXT,
                    "v1",
                    "Developer upgrade context",
                    run.upgrade_context,
                )
            )
        return entries

    def _research_entries(self, project: ProjectSession) -> list[_ArtifactEntry]:
        run_id = project.research_run_id
        if run_id is None:
            return []
        if self._research_reader is None:
            raise ProjectArtifactError("Research run reader is not configured")
        run = self._research_reader.get(run_id)
        if run is None:
            raise ProjectArtifactError(f"Linked Researcher run not found: {run_id}")

        entries = [
            _entry(
                ProjectArtifactSource.RESEARCHER,
                run_id,
                ProjectArtifactType.RESEARCH_REQUEST,
                "v1",
                "Research request",
                run.request,
            ),
            _entry(
                ProjectArtifactSource.RESEARCHER,
                run_id,
                ProjectArtifactType.DISCOVERY_REPORT,
                "v1",
                "Research discovery report",
                run.report,
            ),
        ]
        if run.selected_direction_id is not None:
            direction = next(
                item
                for item in run.report.directions
                if item.id == run.selected_direction_id
            )
            entries.append(
                _entry(
                    ProjectArtifactSource.RESEARCHER,
                    run_id,
                    ProjectArtifactType.SELECTED_DIRECTION,
                    direction.id,
                    f"Selected research direction: {direction.title}",
                    direction,
                )
            )

        revision_state = run.plan_revision_state
        if revision_state is not None:
            active_version = revision_state.active_version
            entries.append(
                _entry(
                    ProjectArtifactSource.RESEARCHER,
                    run_id,
                    ProjectArtifactType.RESEARCH_PLAN,
                    f"v{active_version}",
                    f"Research plan v{active_version}",
                    revision_state.active_plan,
                )
            )
            entries.extend(
                _entry(
                    ProjectArtifactSource.RESEARCHER,
                    run_id,
                    ProjectArtifactType.RESEARCH_PLAN_REVISION,
                    f"v{revision.version}",
                    f"Research plan revision v{revision.version}",
                    revision,
                )
                for revision in sorted(
                    revision_state.revisions, key=lambda item: item.version
                )
            )
            approval = "approved" if revision_state.approved else "draft"
            entries.append(
                _entry(
                    ProjectArtifactSource.RESEARCHER,
                    run_id,
                    ProjectArtifactType.RESEARCH_PLAN_HISTORY,
                    f"v{active_version}-{approval}",
                    "Research plan revision history",
                    revision_state,
                )
            )

        plan = run.implementation_plan
        if plan is not None:
            plan_version = f"plan-v{plan.approved_plan_version}"
            entries.append(
                _entry(
                    ProjectArtifactSource.RESEARCHER,
                    run_id,
                    ProjectArtifactType.RESEARCH_IMPLEMENTATION_PLAN,
                    plan_version,
                    "Research implementation plan",
                    plan,
                )
            )
        else:
            plan_version = None

        package = run.implementation_package
        if package is not None and plan_version is not None:
            entries.append(
                _entry(
                    ProjectArtifactSource.RESEARCHER,
                    run_id,
                    ProjectArtifactType.RESEARCH_IMPLEMENTATION_PACKAGE,
                    plan_version,
                    "Research implementation package",
                    package,
                )
            )
            entries.extend(
                _entry(
                    ProjectArtifactSource.RESEARCHER,
                    run_id,
                    ProjectArtifactType.RESEARCH_GENERATED_FILE,
                    f"{plan_version}:{artifact.artifact_id}",
                    f"Generated research file: {artifact.relative_path}",
                    artifact,
                )
                for artifact in package.artifacts
            )

        for artifact_type, title, content in (
            (
                ProjectArtifactType.RESEARCH_RESULTS,
                "Research results",
                run.result_submission,
            ),
            (
                ProjectArtifactType.RESEARCH_RESULT_ANALYSIS,
                "Research result analysis",
                run.result_analysis,
            ),
            (
                ProjectArtifactType.RESEARCH_SYNTHESIS,
                "Research synthesis",
                run.result_synthesis,
            ),
            (
                ProjectArtifactType.PAPER_MATERIALS,
                "Research paper materials",
                run.paper_materials,
            ),
        ):
            if content is not None:
                entries.append(
                    _entry(
                        ProjectArtifactSource.RESEARCHER,
                        run_id,
                        artifact_type,
                        _research_linked_version(run),
                        title,
                        content,
                    )
                )
        return entries


def _research_linked_version(run: ResearchRun) -> str:
    if run.plan_revision_state is None or run.implementation_plan is None:
        raise ProjectArtifactError("Research result artifact has no version lineage")
    return (
        f"plan-v{run.plan_revision_state.active_version}-"
        f"implementation-v{run.implementation_plan.approved_plan_version}"
    )


def _entry(
    source: ProjectArtifactSource,
    run_id: str,
    artifact_type: ProjectArtifactType,
    source_version: str,
    title: str,
    content: BaseModel,
) -> _ArtifactEntry:
    descriptor = ProjectArtifactDescriptor(
        artifact_id=f"{source.value}:{run_id}:{artifact_type.value}:{source_version}",
        artifact_type=artifact_type,
        source_domain=source,
        source_run_id=run_id,
        source_version=source_version,
        title=title,
        media_types=supported_media_types(artifact_type),
    )
    # AgentState contains private conversations, tool arguments/results and
    # provider context. Keep it in the historical run, never in public artifacts.
    exclude = None
    if artifact_type is ProjectArtifactType.EXECUTION_STATE:
        exclude = {
            "phase_records": {
                "__all__": {
                    "execution": {
                        "agent_run": True,
                        "repair_attempts": {"__all__": {"agent_run": True}},
                    }
                }
            }
        }
    return _ArtifactEntry(
        descriptor=descriptor,
        content=content.model_dump(mode="json", exclude=exclude),
    )


def _content_version(content: BaseModel) -> str:
    encoded = canonical_artifact_content_bytes(content.model_dump(mode="json"))
    return f"sha256-{hashlib.sha256(encoded).hexdigest()}"
