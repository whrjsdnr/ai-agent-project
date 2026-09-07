"""Explicit ProjectSession routing for authoritative human checkpoint actions."""

from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from ai_agent_project.agent.project_application import StoredProjectRun
from ai_agent_project.agent.project_session import (
    ProjectPendingAction,
    ProjectPendingActionType,
    ProjectStatus,
)
from ai_agent_project.agent.project_session_application import ProjectSessionService
from ai_agent_project.agent.research import (
    ResearchResultSubmission,
    ResearchStatus,
    WorkMode,
)
from ai_agent_project.agent.research_application import StoredResearchRun


class ProjectActionError(Exception):
    """Base error for explicit project-level human checkpoint routing."""


class ProjectActionNotAllowedError(ProjectActionError):
    """Raised when a requested action is not the current pending action."""


class ProjectActionCompletedError(ProjectActionNotAllowedError):
    """Raised when mutation is requested through a completed ProjectSession."""


class ProjectActionSource(StrEnum):
    DEVELOPER = "developer"
    RESEARCHER = "researcher"


class ApproveDeveloperPlanCommand(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_id: str = Field(min_length=1)


class SelectResearchDirectionCommand(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_id: str = Field(min_length=1)
    direction_id: str = Field(min_length=1)


class ApproveResearchPlanCommand(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_id: str = Field(min_length=1)


class ContinueDeveloperCommand(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_id: str = Field(min_length=1)


class ContinueResearcherCommand(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_id: str = Field(min_length=1)


class ProvideResearchResultsCommand(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_id: str = Field(min_length=1)
    submission: ResearchResultSubmission


class ProjectActionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_id: str
    action: ProjectPendingActionType
    source_domain: ProjectActionSource
    source_run_id: str
    previous_pending_action: ProjectPendingAction
    next_pending_action: ProjectPendingAction | None
    project_status: ProjectStatus
    source_status: str


class DeveloperPlanApprover(Protocol):
    def approve_plan(self, project_run_id: str) -> StoredProjectRun: ...

    def execute_current_phase(self, project_run_id: str) -> StoredProjectRun: ...


class ResearchCheckpointService(Protocol):
    def get_research_run(self, research_run_id: str) -> StoredResearchRun: ...

    def select_research_direction(
        self, research_run_id: str, direction_id: str
    ) -> StoredResearchRun: ...

    def approve_plan(self, research_run_id: str) -> StoredResearchRun: ...

    def generate_plan(self, research_run_id: str) -> StoredResearchRun: ...

    def generate_implementation_plan(
        self, research_run_id: str
    ) -> StoredResearchRun: ...

    def generate_implementation_package(
        self, research_run_id: str
    ) -> StoredResearchRun: ...

    def submit_results(
        self, research_run_id: str, submission: ResearchResultSubmission
    ) -> StoredResearchRun: ...

    def analyze_results(self, research_run_id: str) -> StoredResearchRun: ...

    def generate_synthesis(self, research_run_id: str) -> StoredResearchRun: ...

    def generate_paper_materials(self, research_run_id: str) -> StoredResearchRun: ...


class ProjectActionService:
    """Validate one explicit command and route exactly one domain mutation."""

    def __init__(
        self,
        project_sessions: ProjectSessionService,
        developer_plans: DeveloperPlanApprover,
        research_checkpoints: ResearchCheckpointService,
    ) -> None:
        self._project_sessions = project_sessions
        self._developer_plans = developer_plans
        self._research_checkpoints = research_checkpoints

    def approve_developer_plan(
        self, command: ApproveDeveloperPlanCommand
    ) -> ProjectActionResult:
        previous = self._require_action(
            command.project_id, ProjectPendingActionType.APPROVE_DEVELOPER_PLAN
        )
        run_id = previous.developer_run_id
        if run_id is None:
            raise ProjectActionError("Developer approval action has no linked run")
        stored = self._developer_plans.approve_plan(run_id)
        return self._result(
            command.project_id,
            previous,
            ProjectActionSource.DEVELOPER,
            run_id,
            stored.project_run.execution_state.status.value,
        )

    def select_research_direction(
        self, command: SelectResearchDirectionCommand
    ) -> ProjectActionResult:
        previous = self._require_action(
            command.project_id, ProjectPendingActionType.SELECT_RESEARCH_DIRECTION
        )
        run_id = previous.research_run_id
        if run_id is None:
            raise ProjectActionError("Research selection action has no linked run")
        stored = self._research_checkpoints.select_research_direction(
            run_id, command.direction_id
        )
        return self._result(
            command.project_id,
            previous,
            ProjectActionSource.RESEARCHER,
            run_id,
            stored.research_run.status.value,
        )

    def approve_research_plan(
        self, command: ApproveResearchPlanCommand
    ) -> ProjectActionResult:
        previous = self._require_action(
            command.project_id, ProjectPendingActionType.APPROVE_RESEARCH_PLAN
        )
        run_id = previous.research_run_id
        if run_id is None:
            raise ProjectActionError("Research approval action has no linked run")
        stored = self._research_checkpoints.approve_plan(run_id)
        return self._result(
            command.project_id,
            previous,
            ProjectActionSource.RESEARCHER,
            run_id,
            stored.research_run.status.value,
        )

    def continue_developer(
        self, command: ContinueDeveloperCommand
    ) -> ProjectActionResult:
        previous = self._require_action(
            command.project_id, ProjectPendingActionType.CONTINUE_DEVELOPER
        )
        run_id = previous.developer_run_id
        if run_id is None:
            raise ProjectActionError("Developer continuation action has no linked run")
        stored = self._developer_plans.execute_current_phase(run_id)
        return self._result(
            command.project_id,
            previous,
            ProjectActionSource.DEVELOPER,
            run_id,
            stored.project_run.execution_state.status.value,
        )

    def continue_researcher(
        self, command: ContinueResearcherCommand
    ) -> ProjectActionResult:
        previous = self._require_action(
            command.project_id, ProjectPendingActionType.CONTINUE_RESEARCHER
        )
        run_id = previous.research_run_id
        if run_id is None:
            raise ProjectActionError("Research continuation action has no linked run")
        status = self._research_checkpoints.get_research_run(run_id).research_run.status
        operations = {
            ResearchStatus.DIRECTION_SELECTED: self._research_checkpoints.generate_plan,
            ResearchStatus.RESEARCH_PLAN_APPROVED: (
                self._research_checkpoints.generate_implementation_plan
            ),
            ResearchStatus.IMPLEMENTATION_GENERATION_STARTED: (
                self._research_checkpoints.generate_implementation_package
            ),
            ResearchStatus.RESEARCH_RESULTS_SUBMITTED: (
                self._research_checkpoints.analyze_results
            ),
            ResearchStatus.RESEARCH_RESULTS_ANALYZED: (
                self._research_checkpoints.generate_synthesis
            ),
            ResearchStatus.RESEARCH_SYNTHESIS_READY: (
                self._research_checkpoints.generate_paper_materials
            ),
        }
        operation = operations.get(status)
        if operation is None:
            raise ProjectActionNotAllowedError(
                "Researcher continuation has no bounded progression for "
                f"status: {status.value}"
            )
        stored = operation(run_id)
        return self._result(
            command.project_id,
            previous,
            ProjectActionSource.RESEARCHER,
            run_id,
            stored.research_run.status.value,
        )

    def provide_research_results(
        self, command: ProvideResearchResultsCommand
    ) -> ProjectActionResult:
        previous = self._require_action(
            command.project_id, ProjectPendingActionType.PROVIDE_RESEARCH_RESULTS
        )
        run_id = previous.research_run_id
        if run_id is None:
            raise ProjectActionError("Research results action has no linked run")
        stored = self._research_checkpoints.submit_results(run_id, command.submission)
        return self._result(
            command.project_id,
            previous,
            ProjectActionSource.RESEARCHER,
            run_id,
            stored.research_run.status.value,
        )

    def _require_action(
        self, project_id: str, requested: ProjectPendingActionType
    ) -> ProjectPendingAction:
        project = self._project_sessions.get_project(project_id).project
        if project.status is ProjectStatus.COMPLETED:
            raise ProjectActionCompletedError(
                f"Completed project cannot perform action: {requested.value}"
            )
        actions = self._project_sessions.get_pending_actions(project_id)
        if project.work_mode is WorkMode.HYBRID:
            source = _ACTION_SOURCES[requested]
            current = next(
                (
                    action
                    for action in actions
                    if action.action_type is requested
                    and (
                        action.developer_run_id is not None
                        if source is ProjectActionSource.DEVELOPER
                        else action.research_run_id is not None
                    )
                ),
                None,
            )
        else:
            current = actions[0] if actions else None
        if current is None or current.action_type is not requested:
            first = actions[0] if actions else None
            current_name = first.action_type.value if first is not None else "none"
            raise ProjectActionNotAllowedError(
                f"Project action {requested.value} is not currently allowed; "
                f"current pending action: {current_name}"
            )
        return current

    def _result(
        self,
        project_id: str,
        previous: ProjectPendingAction,
        source_domain: ProjectActionSource,
        source_run_id: str,
        source_status: str,
    ) -> ProjectActionResult:
        project = self._project_sessions.get_project(project_id).project
        next_actions = self._project_sessions.get_pending_actions(project_id)
        return ProjectActionResult(
            project_id=project_id,
            action=previous.action_type,
            source_domain=source_domain,
            source_run_id=source_run_id,
            previous_pending_action=previous,
            next_pending_action=next_actions[0] if next_actions else None,
            project_status=project.status,
            source_status=source_status,
        )


_ACTION_SOURCES = {
    ProjectPendingActionType.APPROVE_DEVELOPER_PLAN: ProjectActionSource.DEVELOPER,
    ProjectPendingActionType.CONTINUE_DEVELOPER: ProjectActionSource.DEVELOPER,
    ProjectPendingActionType.SELECT_RESEARCH_DIRECTION: ProjectActionSource.RESEARCHER,
    ProjectPendingActionType.APPROVE_RESEARCH_PLAN: ProjectActionSource.RESEARCHER,
    ProjectPendingActionType.PROVIDE_RESEARCH_RESULTS: ProjectActionSource.RESEARCHER,
    ProjectPendingActionType.CONTINUE_RESEARCHER: ProjectActionSource.RESEARCHER,
}
