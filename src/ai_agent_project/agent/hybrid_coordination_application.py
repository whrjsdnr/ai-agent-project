"""Provider-free derivation of independently actionable Hybrid workflow lanes."""

from typing import Protocol

from ai_agent_project.agent.hybrid_coordination import (
    HybridCoordinationLane,
    HybridCoordinationView,
)
from ai_agent_project.agent.project_action_application import ProjectActionSource
from ai_agent_project.agent.project_execution import ProjectExecutionStatus
from ai_agent_project.agent.project_runner import ProjectRun
from ai_agent_project.agent.project_session import (
    ProjectPendingAction,
    ProjectPendingActionType,
    ProjectStatus,
)
from ai_agent_project.agent.project_session_application import ProjectSessionService
from ai_agent_project.agent.research import ResearchRun, ResearchStatus, WorkMode


class HybridCoordinationError(Exception):
    """Raised when a Hybrid coordination view cannot be derived safely."""


class HybridCoordinationProjectReader(Protocol):
    def get(self, run_id: str) -> ProjectRun | None: ...


class HybridCoordinationResearchReader(Protocol):
    def get(self, run_id: str) -> ResearchRun | None: ...


class HybridCoordinationService:
    """Inspect both Hybrid lanes without progressing or persisting either one."""

    def __init__(
        self,
        project_sessions: ProjectSessionService,
        developer_reader: HybridCoordinationProjectReader | None = None,
        research_reader: HybridCoordinationResearchReader | None = None,
    ) -> None:
        self._project_sessions = project_sessions
        self._developer_reader = developer_reader
        self._research_reader = research_reader

    def get_coordination(self, project_id: str) -> HybridCoordinationView:
        project = self._project_sessions.get_project(project_id).project
        if project.work_mode is not WorkMode.HYBRID:
            raise HybridCoordinationError(f"Project is not Hybrid: {project_id}")

        actions = (
            self._project_sessions.get_pending_actions(project_id)
            if project.status is not ProjectStatus.COMPLETED
            else ()
        )
        developer = self._developer_lane(project.developer_run_id, actions)
        researcher = self._researcher_lane(project.research_run_id, actions)
        return HybridCoordinationView(
            project_id=project_id,
            project_status=project.status,
            developer=developer,
            researcher=researcher,
            actionable_actions=actions,
            both_workflows_terminal=developer.terminal and researcher.terminal,
        )

    def _developer_lane(
        self, run_id: str | None, actions: tuple[ProjectPendingAction, ...]
    ) -> HybridCoordinationLane:
        action = next(
            (item for item in actions if item.developer_run_id is not None), None
        )
        if run_id is None:
            action = next(
                (
                    item
                    for item in actions
                    if item.developer_run_id is None
                    and item.research_run_id is None
                    and item.action_type is ProjectPendingActionType.BIND_DEVELOPER_RUN
                ),
                None,
            )
            return HybridCoordinationLane(
                source_domain=ProjectActionSource.DEVELOPER,
                run_id=None,
                source_status=None,
                pending_action=action,
                terminal=False,
            )
        if self._developer_reader is None:
            raise HybridCoordinationError("Developer run reader is not configured")
        run = self._developer_reader.get(run_id)
        if run is None:
            raise HybridCoordinationError(f"Linked Developer run not found: {run_id}")
        status = run.execution_state.status
        return HybridCoordinationLane(
            source_domain=ProjectActionSource.DEVELOPER,
            run_id=run_id,
            source_status=status.value,
            pending_action=action,
            terminal=status is ProjectExecutionStatus.COMPLETED,
        )

    def _researcher_lane(
        self, run_id: str | None, actions: tuple[ProjectPendingAction, ...]
    ) -> HybridCoordinationLane:
        action = next(
            (item for item in actions if item.research_run_id is not None), None
        )
        if run_id is None:
            action = next(
                (
                    item
                    for item in actions
                    if item.developer_run_id is None
                    and item.research_run_id is None
                    and item.action_type is ProjectPendingActionType.BIND_RESEARCH_RUN
                ),
                None,
            )
            return HybridCoordinationLane(
                source_domain=ProjectActionSource.RESEARCHER,
                run_id=None,
                source_status=None,
                pending_action=action,
                terminal=False,
            )
        if self._research_reader is None:
            raise HybridCoordinationError("Research run reader is not configured")
        run = self._research_reader.get(run_id)
        if run is None:
            raise HybridCoordinationError(f"Linked Researcher run not found: {run_id}")
        status = run.status
        return HybridCoordinationLane(
            source_domain=ProjectActionSource.RESEARCHER,
            run_id=run_id,
            source_status=status.value,
            pending_action=action,
            terminal=status is ResearchStatus.PAPER_MATERIALS_READY,
        )
