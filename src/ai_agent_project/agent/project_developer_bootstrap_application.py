"""Explicit, planning-only bootstrap of a Developer run from a handoff."""

from pydantic import BaseModel, ConfigDict, Field

from ai_agent_project.agent.plan_revision import PlanReviewStatus
from ai_agent_project.agent.project_application import ProjectApplicationService
from ai_agent_project.agent.project_execution import ProjectExecutionStatus
from ai_agent_project.agent.project_handoff_consumption import (
    ProjectHandoffConsumptionService,
)
from ai_agent_project.agent.project_session import (
    ProjectPendingActionType,
    ProjectStatus,
)
from ai_agent_project.agent.project_session_application import (
    ProjectSessionError,
    ProjectSessionService,
)
from ai_agent_project.agent.research import WorkMode
from ai_agent_project.agent.upgrade import ProjectMode


class ProjectDeveloperBootstrapError(ValueError):
    """Raised when explicit Developer bootstrap cannot complete safely."""


class DeveloperBootstrapResult(BaseModel):
    """Metadata-only result returned after planning and binding."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_id: str = Field(min_length=1)
    handoff_id: str = Field(min_length=1)
    developer_run_id: str = Field(min_length=1)
    developer_status: str = Field(min_length=1)
    pending_action: ProjectPendingActionType


class ProjectDeveloperBootstrapService:
    """Orchestrate one explicit, non-executing Developer bootstrap."""

    def __init__(
        self,
        project_sessions: ProjectSessionService,
        handoff_consumption: ProjectHandoffConsumptionService,
        project_application: ProjectApplicationService,
    ) -> None:
        self._project_sessions = project_sessions
        self._handoff_consumption = handoff_consumption
        self._project_application = project_application

    def bootstrap(
        self, project_id: str, handoff_id: str, request: str
    ) -> DeveloperBootstrapResult:
        if not request.strip():
            raise ProjectDeveloperBootstrapError("Bootstrap request must not be blank")
        project = self._project_sessions.get_project(project_id).project
        if project.status is not ProjectStatus.ACTIVE:
            raise ProjectDeveloperBootstrapError("Project must be active")
        if project.work_mode is not WorkMode.HYBRID:
            raise ProjectDeveloperBootstrapError("Project must be Hybrid")
        if project.project_mode is not ProjectMode.NEW:
            raise ProjectDeveloperBootstrapError("Project must be NEW")
        if project.research_run_id is None:
            raise ProjectDeveloperBootstrapError("Project has no linked Researcher run")
        if project.developer_run_id is not None:
            raise ProjectDeveloperBootstrapError(
                "Project already has a Developer run bound"
            )

        verified = self._handoff_consumption.resolve_for_developer_bootstrap(
            project_id, handoff_id
        )
        context = verified.to_developer_context()
        stored = self._project_application.create_project_with_context(
            request,
            context=context,
            provenance=verified.to_provenance(),
        )
        run = stored.project_run
        if (
            run.execution_state.status
            is not ProjectExecutionStatus.AWAITING_PLAN_APPROVAL
            or run.plan_revision_state.status is not PlanReviewStatus.AWAITING_APPROVAL
        ):
            try:
                self._project_application.delete_project_run(stored.id)
            except Exception as rollback_error:
                raise ProjectDeveloperBootstrapError(
                    f"Developer run {stored.id} has invalid bootstrap state; "
                    "rollback also failed"
                ) from rollback_error
            raise ProjectDeveloperBootstrapError(
                "Developer bootstrap produced a run outside the plan-approval state"
            )
        try:
            self._project_sessions.bind_developer_run_if_unbound(project_id, stored.id)
        except ProjectSessionError as error:
            try:
                self._project_application.delete_project_run(stored.id)
            except Exception as rollback_error:
                raise ProjectDeveloperBootstrapError(
                    f"Developer run {stored.id} was created but binding failed; "
                    "rollback also failed"
                ) from rollback_error
            raise ProjectDeveloperBootstrapError(
                "Developer bootstrap binding failed; created run was rolled back"
            ) from error

        return DeveloperBootstrapResult(
            project_id=project_id,
            handoff_id=handoff_id,
            developer_run_id=stored.id,
            developer_status=stored.project_run.execution_state.status.value,
            pending_action=ProjectPendingActionType.APPROVE_DEVELOPER_PLAN,
        )
