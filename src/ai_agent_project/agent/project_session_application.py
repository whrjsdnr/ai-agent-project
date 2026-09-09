"""Application lifecycle for shallow user-confirmed project sessions."""

from datetime import UTC, datetime
from threading import Lock
from typing import Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from ai_agent_project.agent.plan_revision import PlanReviewStatus
from ai_agent_project.agent.project_execution import ProjectExecutionStatus
from ai_agent_project.agent.project_runner import ProjectRun
from ai_agent_project.agent.project_session import (
    ProjectModeProposer,
    ProjectPendingAction,
    ProjectPendingActionType,
    ProjectSession,
    ProjectStatus,
)
from ai_agent_project.agent.research import ResearchRun, ResearchStatus, WorkMode
from ai_agent_project.agent.upgrade import ProjectMode


class ProjectSessionError(Exception):
    """Base error for project-session orchestration operations."""


class ProjectSessionNotFoundError(ProjectSessionError):
    """Raised when a project session is absent."""


class ProjectSessionAlreadyExistsError(ProjectSessionError):
    """Raised when a session store would overwrite a project session."""


class ProjectSessionStateError(ProjectSessionError):
    """Raised when a project-session lifecycle transition is invalid."""


class ProjectSessionStore(Protocol):
    def create(self, project_id: str, project: ProjectSession) -> None: ...

    def get(self, project_id: str) -> ProjectSession | None: ...

    def replace(self, project_id: str, project: ProjectSession) -> None: ...

    def bind_developer_run_if_unbound(
        self, project_id: str, developer_run_id: str
    ) -> ProjectSession: ...


def _bind_developer_project(
    project: ProjectSession, developer_run_id: str
) -> ProjectSession:
    """Validate the freshly loaded session inside the store's critical section."""
    if project.status is not ProjectStatus.ACTIVE:
        raise ProjectSessionStateError("Project must be active")
    if project.work_mode is not WorkMode.HYBRID:
        raise ProjectSessionStateError(
            "Only Hybrid projects can use Developer bootstrap"
        )
    if project.project_mode is not ProjectMode.NEW:
        raise ProjectSessionStateError("Only NEW projects can use Developer bootstrap")
    if project.developer_run_id is not None:
        raise ProjectSessionStateError("Project already has a Developer run bound")
    return project.model_copy(
        update={"developer_run_id": developer_run_id, "updated_at": datetime.now(UTC)}
    )


class DeveloperRunReader(Protocol):
    def get(self, run_id: str) -> ProjectRun | None: ...


class ResearchRunReader(Protocol):
    def get(self, run_id: str) -> ResearchRun | None: ...


class InMemoryProjectSessionStore:
    def __init__(self) -> None:
        self._projects: dict[str, ProjectSession] = {}
        self._bind_lock = Lock()

    def create(self, project_id: str, project: ProjectSession) -> None:
        if project_id in self._projects:
            raise ProjectSessionAlreadyExistsError(
                f"Project already exists: {project_id}"
            )
        self._projects[project_id] = project

    def get(self, project_id: str) -> ProjectSession | None:
        return self._projects.get(project_id)

    def replace(self, project_id: str, project: ProjectSession) -> None:
        if project_id not in self._projects:
            raise ProjectSessionNotFoundError(f"Project not found: {project_id}")
        self._projects[project_id] = project

    def bind_developer_run_if_unbound(
        self, project_id: str, developer_run_id: str
    ) -> ProjectSession:
        with self._bind_lock:
            project = self.get(project_id)
            if project is None:
                raise ProjectSessionNotFoundError(f"Project not found: {project_id}")
            updated = _bind_developer_project(project, developer_run_id)
            self._projects[project_id] = updated
            return updated


class StoredProjectSession(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    project: ProjectSession


class ProjectResumeView(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_id: str
    status: ProjectStatus
    work_mode: WorkMode | None
    project_mode: ProjectMode | None
    developer_run_id: str | None
    research_run_id: str | None
    pending_actions: tuple[ProjectPendingAction, ...]


class ProjectSessionService:
    """Persist proposals and explicit user selections without starting workflows."""

    def __init__(
        self,
        store: ProjectSessionStore,
        mode_proposer: ProjectModeProposer | None = None,
        developer_run_reader: DeveloperRunReader | None = None,
        research_run_reader: ResearchRunReader | None = None,
    ) -> None:
        self._store = store
        self._mode_proposer = mode_proposer
        self._developer_run_reader = developer_run_reader
        self._research_run_reader = research_run_reader

    def create_project_request(
        self, original_request: str, *, title: str | None = None
    ) -> StoredProjectSession:
        if not original_request.strip():
            raise ProjectSessionError("Project request must not be blank")
        if self._mode_proposer is None:
            raise ProjectSessionError("Project mode proposal is not configured")
        proposal = self._mode_proposer.propose(original_request)
        project_id = str(uuid4())
        project = ProjectSession.awaiting_confirmation(
            project_id=project_id,
            title=title.strip() if title and title.strip() else "Untitled Project",
            original_request=original_request,
            mode_proposal=proposal,
        )
        self._store.create(project_id, project)
        return StoredProjectSession(id=project_id, project=project)

    def get_project(self, project_id: str) -> StoredProjectSession:
        return StoredProjectSession(id=project_id, project=self._require(project_id))

    def confirm_project_mode(
        self,
        project_id: str,
        work_mode: WorkMode,
        project_mode: ProjectMode,
    ) -> StoredProjectSession:
        project = self._require_pending(project_id)
        updated = project.model_copy(
            update={
                "status": ProjectStatus.ACTIVE,
                "work_mode": work_mode,
                "project_mode": project_mode,
                "updated_at": datetime.now(UTC),
            }
        )
        self._store.replace(project_id, updated)
        return StoredProjectSession(id=project_id, project=updated)

    def bind_developer_run(
        self, project_id: str, developer_run_id: str
    ) -> StoredProjectSession:
        project = self._require_active(project_id)
        if project.work_mode is WorkMode.RESEARCHER:
            raise ProjectSessionStateError(
                "Researcher project cannot bind a developer run"
            )
        return self._replace(project_id, project, developer_run_id=developer_run_id)

    def bind_developer_run_if_unbound(
        self, project_id: str, developer_run_id: str
    ) -> StoredProjectSession:
        """Bind a NEW Hybrid project only when its Developer lane is unbound."""
        project = self._store.bind_developer_run_if_unbound(
            project_id, developer_run_id
        )
        return StoredProjectSession(id=project_id, project=project)

    def bind_research_run(
        self, project_id: str, research_run_id: str
    ) -> StoredProjectSession:
        project = self._require_active(project_id)
        if project.work_mode is WorkMode.DEVELOPER:
            raise ProjectSessionStateError(
                "Developer project cannot bind a research run"
            )
        return self._replace(project_id, project, research_run_id=research_run_id)

    def complete_project(self, project_id: str) -> StoredProjectSession:
        project = self._require_active(project_id)
        updated = project.model_copy(
            update={"status": ProjectStatus.COMPLETED, "updated_at": datetime.now(UTC)}
        )
        self._store.replace(project_id, updated)
        return StoredProjectSession(id=project_id, project=updated)

    def get_pending_actions(self, project_id: str) -> tuple[ProjectPendingAction, ...]:
        project = self._require(project_id)
        if project.status is ProjectStatus.AWAITING_MODE_CONFIRMATION:
            return (_confirm_mode_action(project_id),)
        if project.status is ProjectStatus.COMPLETED:
            return ()

        actions: list[ProjectPendingAction] = []
        if project.work_mode in {WorkMode.DEVELOPER, WorkMode.HYBRID}:
            actions.extend(self._developer_actions(project))
        if project.work_mode in {WorkMode.RESEARCHER, WorkMode.HYBRID}:
            actions.extend(self._research_actions(project))
        return tuple(actions)

    def resume_project(self, project_id: str) -> ProjectResumeView:
        project = self._require(project_id)
        return ProjectResumeView(
            project_id=project.project_id,
            status=project.status,
            work_mode=project.work_mode,
            project_mode=project.project_mode,
            developer_run_id=project.developer_run_id,
            research_run_id=project.research_run_id,
            pending_actions=self.get_pending_actions(project_id),
        )

    def _developer_actions(self, project: ProjectSession) -> list[ProjectPendingAction]:
        run_id = project.developer_run_id
        if run_id is None:
            return [_bind_developer_action(project.project_id)]
        if self._developer_run_reader is None:
            raise ProjectSessionError("Developer run reader is not configured")
        run = self._developer_run_reader.get(run_id)
        if run is None:
            raise ProjectSessionError(f"Linked Developer run not found: {run_id}")
        action = _resolve_developer_action(run_id, run)
        return [] if action is None else [action]

    def _research_actions(self, project: ProjectSession) -> list[ProjectPendingAction]:
        run_id = project.research_run_id
        if run_id is None:
            return [_bind_research_action(project.project_id)]
        if self._research_run_reader is None:
            raise ProjectSessionError("Research run reader is not configured")
        run = self._research_run_reader.get(run_id)
        if run is None:
            raise ProjectSessionError(f"Linked Researcher run not found: {run_id}")
        action = _resolve_research_action(run_id, run)
        return [] if action is None else [action]

    def _require(self, project_id: str) -> ProjectSession:
        project = self._store.get(project_id)
        if project is None:
            raise ProjectSessionNotFoundError(f"Project not found: {project_id}")
        return project

    def _require_pending(self, project_id: str) -> ProjectSession:
        project = self._require(project_id)
        if project.status is not ProjectStatus.AWAITING_MODE_CONFIRMATION:
            raise ProjectSessionStateError("Project mode is already confirmed")
        return project

    def _require_active(self, project_id: str) -> ProjectSession:
        project = self._require(project_id)
        if project.status is ProjectStatus.COMPLETED:
            raise ProjectSessionStateError("Completed project cannot be changed")
        if project.status is not ProjectStatus.ACTIVE:
            raise ProjectSessionStateError("Project mode must be confirmed first")
        return project

    def _replace(
        self, project_id: str, project: ProjectSession, **values: str
    ) -> StoredProjectSession:
        updated = project.model_copy(update={**values, "updated_at": datetime.now(UTC)})
        self._store.replace(project_id, updated)
        return StoredProjectSession(id=project_id, project=updated)


def _action(
    action_type: ProjectPendingActionType,
    message: str,
    suggested_action: str,
    *,
    developer_run_id: str | None = None,
    research_run_id: str | None = None,
    source_status: str | None = None,
) -> ProjectPendingAction:
    return ProjectPendingAction(
        action_type=action_type,
        message=message,
        suggested_action=suggested_action,
        developer_run_id=developer_run_id,
        research_run_id=research_run_id,
        source_status=source_status,
    )


def _confirm_mode_action(project_id: str) -> ProjectPendingAction:
    return _action(
        ProjectPendingActionType.CONFIRM_MODE,
        "Confirm the work mode and project mode.",
        f"ai-agent project-session confirm-mode {project_id} --work-mode <MODE> --project-mode <MODE>",
        source_status=ProjectStatus.AWAITING_MODE_CONFIRMATION.value,
    )


def _bind_developer_action(project_id: str) -> ProjectPendingAction:
    return _action(
        ProjectPendingActionType.BIND_DEVELOPER_RUN,
        "Create a Developer run explicitly, then bind its ID to this project.",
        f"ai-agent project-session bind-developer {project_id} <RUN_ID>",
    )


def _bind_research_action(project_id: str) -> ProjectPendingAction:
    return _action(
        ProjectPendingActionType.BIND_RESEARCH_RUN,
        "Create a Researcher run explicitly, then bind its ID to this project.",
        f"ai-agent project-session bind-research {project_id} <RUN_ID>",
    )


def _resolve_developer_action(
    run_id: str, run: ProjectRun
) -> ProjectPendingAction | None:
    review_status = run.plan_revision_state.status
    status = run.execution_state.status
    if review_status is PlanReviewStatus.AWAITING_APPROVAL:
        return _action(
            ProjectPendingActionType.APPROVE_DEVELOPER_PLAN,
            "Review and explicitly approve or revise the Developer plan.",
            f"ai-agent project approve-plan {run_id}",
            developer_run_id=run_id,
            source_status=f"plan:{review_status.value};execution:{status.value}",
        )
    if status is ProjectExecutionStatus.COMPLETED:
        return None
    if status not in {
        ProjectExecutionStatus.READY,
        ProjectExecutionStatus.RUNNING,
        ProjectExecutionStatus.AWAITING_CHECKPOINT,
        ProjectExecutionStatus.REVISION_REQUESTED,
        ProjectExecutionStatus.RETRY_REQUESTED,
        ProjectExecutionStatus.STOPPED,
        ProjectExecutionStatus.FAILED,
    }:
        raise ProjectSessionError(f"Unsupported Developer run status: {status}")
    return _action(
        ProjectPendingActionType.CONTINUE_DEVELOPER,
        "Invoke the appropriate explicit Developer lifecycle command.",
        f"ai-agent project status {run_id}",
        developer_run_id=run_id,
        source_status=status.value,
    )


def _resolve_research_action(
    run_id: str, run: ResearchRun
) -> ProjectPendingAction | None:
    status = run.status
    if status is ResearchStatus.AWAITING_DIRECTION_SELECTION:
        return _action(
            ProjectPendingActionType.SELECT_RESEARCH_DIRECTION,
            "Select one of the available research directions explicitly.",
            f"ai-agent research select-direction {run_id} <DIRECTION_ID>",
            research_run_id=run_id,
            source_status=status.value,
        )
    if status is ResearchStatus.AWAITING_RESEARCH_PLAN_APPROVAL:
        return _action(
            ProjectPendingActionType.APPROVE_RESEARCH_PLAN,
            "Review and explicitly approve or revise the research plan.",
            f"ai-agent research approve-plan {run_id}",
            research_run_id=run_id,
            source_status=status.value,
        )
    if status in {
        ResearchStatus.IMPLEMENTATION_PACKAGE_READY,
        ResearchStatus.AWAITING_USER_RESULTS,
    }:
        return _action(
            ProjectPendingActionType.PROVIDE_RESEARCH_RESULTS,
            "Run the package externally and explicitly submit the research results.",
            f"ai-agent research submit-results {run_id} <RESULT_JSON_FILE>",
            research_run_id=run_id,
            source_status=status.value,
        )
    if status is ResearchStatus.PAPER_MATERIALS_READY:
        return None
    if status not in {
        ResearchStatus.DISCOVERING,
        ResearchStatus.DIRECTION_SELECTED,
        ResearchStatus.FAILED,
        ResearchStatus.COMPLETED_DISCOVERY,
        ResearchStatus.RESEARCH_PLAN_APPROVED,
        ResearchStatus.IMPLEMENTATION_GENERATION_STARTED,
        ResearchStatus.RESEARCH_RESULTS_SUBMITTED,
        ResearchStatus.RESEARCH_RESULTS_ANALYZED,
        ResearchStatus.SYNTHESIS_GENERATION_STARTED,
        ResearchStatus.RESEARCH_SYNTHESIS_READY,
    }:
        raise ProjectSessionError(f"Unsupported Researcher run status: {status}")
    return _action(
        ProjectPendingActionType.CONTINUE_RESEARCHER,
        "Invoke the appropriate explicit Researcher lifecycle command.",
        f"ai-agent research status {run_id}",
        research_run_id=run_id,
        source_status=status.value,
    )
