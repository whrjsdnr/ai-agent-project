"""Application-layer storage and lifecycle operations for project runs."""

from typing import Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from ai_agent_project.agent.checkpoint import CheckpointDecision
from ai_agent_project.agent.plan_revision import (
    PlanReviewStatus,
    PlanRevisionState,
    ProjectPlanReviser,
)
from ai_agent_project.agent.project_execution import (
    ProjectExecutionService,
    ProjectExecutionState,
    ProjectExecutionStatus,
)
from ai_agent_project.agent.project_runner import ProjectRun, ProjectRunner


class ProjectRunError(Exception):
    """Base error for provider-neutral project run application operations."""


class ProjectRunNotFoundError(ProjectRunError):
    """Raised when a requested project run is absent from the store."""


class ProjectRunAlreadyExistsError(ProjectRunError):
    """Raised when store creation would overwrite an existing project run."""


class ProjectPlanReviewError(ProjectRunError):
    """Raised when a project plan review operation violates its lifecycle."""


class ProjectRunStore(Protocol):
    """Whole-snapshot storage abstraction for immutable project runs."""

    def create(self, project_run_id: str, project_run: ProjectRun) -> None:
        """Store a new project run without overwriting an existing ID."""
        ...

    def get(self, project_run_id: str) -> ProjectRun | None:
        """Return the latest snapshot, or None when the ID is unknown."""
        ...

    def replace(self, project_run_id: str, project_run: ProjectRun) -> None:
        """Replace an existing project run with a whole immutable snapshot."""
        ...


class InMemoryProjectRunStore:
    """Small process-local ProjectRun store with explicit replacement semantics."""

    def __init__(self) -> None:
        self._project_runs: dict[str, ProjectRun] = {}

    def create(self, project_run_id: str, project_run: ProjectRun) -> None:
        if project_run_id in self._project_runs:
            raise ProjectRunAlreadyExistsError(
                f"Project run already exists: {project_run_id}"
            )
        self._project_runs[project_run_id] = project_run

    def get(self, project_run_id: str) -> ProjectRun | None:
        return self._project_runs.get(project_run_id)

    def replace(self, project_run_id: str, project_run: ProjectRun) -> None:
        if project_run_id not in self._project_runs:
            raise ProjectRunNotFoundError(f"Project run not found: {project_run_id}")
        self._project_runs[project_run_id] = project_run


class StoredProjectRun(BaseModel):
    """Immutable public application result pairing a run ID with its snapshot."""

    model_config = ConfigDict(frozen=True)

    id: str
    project_run: ProjectRun


class ProjectApplicationService:
    """Manage stored snapshots while delegating all domain lifecycle behavior."""

    def __init__(
        self,
        project_runner: ProjectRunner,
        project_execution_service: ProjectExecutionService,
        store: ProjectRunStore,
        plan_reviser: ProjectPlanReviser | None = None,
    ) -> None:
        self._project_runner = project_runner
        self._project_execution_service = project_execution_service
        self._store = store
        self._plan_reviser = plan_reviser

    def create_project(
        self,
        source_text: str,
        *,
        project_title: str | None = None,
        source_format: str | None = None,
    ) -> StoredProjectRun:
        """Bootstrap and store a ready project without running a phase."""
        project_run = self._project_runner.start(
            source_text,
            project_title=project_title,
            source_format=source_format,
        )
        project_run_id = str(uuid4())
        self._store.create(project_run_id, project_run)
        return StoredProjectRun(id=project_run_id, project_run=project_run)

    def get_project(self, project_run_id: str) -> StoredProjectRun:
        """Return the latest stored immutable project run snapshot."""
        return StoredProjectRun(
            id=project_run_id,
            project_run=self._require_project_run(project_run_id),
        )

    def execute_current_phase(self, project_run_id: str) -> StoredProjectRun:
        """Execute the current phase and replace only the stored state snapshot."""
        project_run = self._require_project_run(project_run_id)
        if project_run.plan_revision_state is None or (
            project_run.plan_revision_state.status is not PlanReviewStatus.APPROVED
        ):
            raise ProjectPlanReviewError(
                "Project plan must be approved before execution"
            )
        execution_state = self._project_execution_service.execute_current_phase(
            project_run.execution_state,
            project_run.specification,
            project_run.project_specification,
            project_run.project_plan,
        )
        updated_run = _with_execution_state(project_run, execution_state)
        self._store.replace(project_run_id, updated_run)
        return StoredProjectRun(id=project_run_id, project_run=updated_run)

    def get_plan(self, project_run_id: str) -> PlanRevisionState:
        """Return the immutable plan review history for one stored project run."""
        revision_state = self._require_project_run(project_run_id).plan_revision_state
        if revision_state is None:
            raise ProjectPlanReviewError("Project run has no plan review state")
        return revision_state

    def revise_plan(self, project_run_id: str, feedback: str) -> StoredProjectRun:
        """Replace the active pre-execution phase grouping without changing tasks."""
        project_run = self._require_project_run(project_run_id)
        revision_state = _revision_state(project_run)
        _require_pre_execution_review(project_run, revision_state)
        if not feedback.strip():
            raise ProjectPlanReviewError("Plan revision feedback must not be blank")
        if self._plan_reviser is None:
            raise ProjectPlanReviewError("Project plan revision is not configured")
        revised_plan = self._plan_reviser.revise(
            project_run.project_specification,
            revision_state.active_plan,
            feedback,
            project_run.workspace,
        )
        if (
            revised_plan.implementation_plan
            != revision_state.active_plan.implementation_plan
        ):
            raise ProjectPlanReviewError(
                "A revised plan must preserve the implementation plan"
            )
        revised_plan.validate_against(project_run.project_specification)
        revised_revisions = revision_state.revise(revised_plan, feedback)
        execution_state = self._project_execution_service.start(
            project_run.specification,
            project_run.project_specification,
            revised_plan,
        ).model_copy(update={"status": ProjectExecutionStatus.AWAITING_PLAN_APPROVAL})
        updated_run = project_run.model_copy(
            update={
                "project_plan": revised_plan,
                "plan_revision_state": revised_revisions,
                "execution_state": execution_state,
            }
        )
        self._store.replace(project_run_id, updated_run)
        return StoredProjectRun(id=project_run_id, project_run=updated_run)

    def approve_plan(self, project_run_id: str) -> StoredProjectRun:
        """Approve the active plan and make its first phase ready without executing."""
        project_run = self._require_project_run(project_run_id)
        revision_state = _revision_state(project_run)
        if revision_state.status is PlanReviewStatus.APPROVED:
            raise ProjectPlanReviewError("Project plan is already approved")
        _require_pre_execution_review(project_run, revision_state)
        approved_revisions = revision_state.approve()
        execution_state = self._project_execution_service.start(
            project_run.specification,
            project_run.project_specification,
            approved_revisions.active_plan,
        )
        updated_run = project_run.model_copy(
            update={
                "project_plan": approved_revisions.active_plan,
                "plan_revision_state": approved_revisions,
                "execution_state": execution_state,
            }
        )
        self._store.replace(project_run_id, updated_run)
        return StoredProjectRun(id=project_run_id, project_run=updated_run)

    def decide_current_phase(
        self,
        project_run_id: str,
        decision: CheckpointDecision,
        *,
        note: str | None = None,
    ) -> StoredProjectRun:
        """Store a checkpoint decision without executing a phase or replanning."""
        project_run = self._require_project_run(project_run_id)
        execution_state = self._project_execution_service.decide_current_phase(
            project_run.execution_state,
            project_run.project_plan,
            decision,
            note,
        )
        updated_run = _with_execution_state(project_run, execution_state)
        self._store.replace(project_run_id, updated_run)
        return StoredProjectRun(id=project_run_id, project_run=updated_run)

    def _require_project_run(self, project_run_id: str) -> ProjectRun:
        project_run = self._store.get(project_run_id)
        if project_run is None:
            raise ProjectRunNotFoundError(f"Project run not found: {project_run_id}")
        return project_run


def _with_execution_state(
    project_run: ProjectRun,
    execution_state: ProjectExecutionState,
) -> ProjectRun:
    """Return a new ProjectRun snapshot without mutating the prior snapshot."""
    return project_run.model_copy(update={"execution_state": execution_state})


def _revision_state(project_run: ProjectRun) -> PlanRevisionState:
    if project_run.plan_revision_state is None:
        raise ProjectPlanReviewError("Project run has no plan review state")
    return project_run.plan_revision_state


def _require_pre_execution_review(
    project_run: ProjectRun,
    revision_state: PlanRevisionState,
) -> None:
    if revision_state.status is PlanReviewStatus.APPROVED:
        raise ProjectPlanReviewError("An approved project plan cannot be revised")
    if any(
        record.attempt_count for record in project_run.execution_state.phase_records
    ):
        raise ProjectPlanReviewError(
            "Project plan cannot be revised after phase execution"
        )
