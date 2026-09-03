"""Provider-neutral bootstrap from source text to a ready project execution."""

from pydantic import BaseModel, ConfigDict, model_validator

from ai_agent_project.agent.codebase_analysis import CodebaseAnalyzer
from ai_agent_project.agent.plan import ImplementationPlan, ImplementationPlanner
from ai_agent_project.agent.plan_revision import PlanRevisionState
from ai_agent_project.agent.project import (
    ProjectPlan,
    ProjectPlanner,
    ProjectSpecification,
)
from ai_agent_project.agent.project_execution import (
    ProjectExecutionService,
    ProjectExecutionState,
    ProjectExecutionStatus,
)
from ai_agent_project.agent.specification import Specification
from ai_agent_project.agent.specification_parser import SpecificationParser
from ai_agent_project.agent.upgrade import (
    BaselineStatus,
    BaselineValidation,
    ProjectMode,
    UpgradeAnalyzer,
    UpgradeContext,
    UpgradeRequest,
)
from ai_agent_project.agent.workspace import WorkspaceInspector, WorkspaceSnapshot


class ProjectRun(BaseModel):
    """Immutable output of one project bootstrap pass, before phase execution."""

    model_config = ConfigDict(frozen=True)

    specification: Specification
    project_specification: ProjectSpecification
    workspace: WorkspaceSnapshot
    implementation_plan: ImplementationPlan
    project_plan: ProjectPlan
    execution_state: ProjectExecutionState
    plan_revision_state: PlanRevisionState | None = None
    mode: ProjectMode = ProjectMode.NEW
    upgrade_context: UpgradeContext | None = None

    @model_validator(mode="after")
    def synchronize_active_plan(self) -> "ProjectRun":
        """Keep the legacy active plan field aligned with revision history."""
        revision_state = self.plan_revision_state
        if revision_state is None:
            revision_state = PlanRevisionState.from_plan(self.project_plan)
            if (
                self.execution_state.status
                is not ProjectExecutionStatus.AWAITING_PLAN_APPROVAL
            ):
                revision_state = revision_state.approve()
        if revision_state.active_plan != self.project_plan:
            raise ValueError("ProjectRun project_plan must match the active revision")
        if self.mode is ProjectMode.UPGRADE and self.upgrade_context is None:
            raise ValueError("Upgrade ProjectRun requires upgrade_context")
        if self.mode is ProjectMode.NEW and self.upgrade_context is not None:
            raise ValueError("New ProjectRun cannot include upgrade_context")
        object.__setattr__(self, "plan_revision_state", revision_state)
        return self


class ProjectRunner:
    """Compose existing parsing and planning services without executing a phase."""

    def __init__(
        self,
        specification_parser: SpecificationParser,
        workspace_inspector: WorkspaceInspector,
        implementation_planner: ImplementationPlanner,
        project_planner: ProjectPlanner,
        project_execution_service: ProjectExecutionService,
    ) -> None:
        self._specification_parser = specification_parser
        self._workspace_inspector = workspace_inspector
        self._implementation_planner = implementation_planner
        self._project_planner = project_planner
        self._project_execution_service = project_execution_service

    def start(
        self,
        source_text: str,
        *,
        project_title: str | None = None,
        source_format: str | None = None,
    ) -> ProjectRun:
        """Build a ready project state without running any coding phase."""
        specification = self._specification_parser.parse(source_text)
        project_specification = ProjectSpecification.from_specification(specification)
        project_specification = project_specification.model_copy(
            update={
                **({"title": project_title} if project_title is not None else {}),
                **(
                    {"source_format": source_format}
                    if source_format is not None
                    else {}
                ),
            }
        )
        workspace = self._workspace_inspector.inspect()
        implementation_plan = self._implementation_planner.plan(
            specification, workspace
        )
        project_plan = self._project_planner.plan(
            project_specification,
            implementation_plan,
            workspace,
        )
        project_plan.validate_against(project_specification)
        execution_state = self._project_execution_service.start(
            specification,
            project_specification,
            project_plan,
        )
        revision_state = PlanRevisionState.from_plan(project_plan)
        awaiting_plan_approval = execution_state.model_copy(
            update={"status": ProjectExecutionStatus.AWAITING_PLAN_APPROVAL}
        )
        return ProjectRun(
            specification=specification,
            project_specification=project_specification,
            workspace=workspace,
            implementation_plan=implementation_plan,
            project_plan=project_plan,
            execution_state=awaiting_plan_approval,
            plan_revision_state=revision_state,
        )


class UpgradeProjectRunner:
    """Bootstrap a safe upgrade project without modifying the existing workspace."""

    def __init__(
        self,
        workspace_inspector: WorkspaceInspector,
        codebase_analyzer: CodebaseAnalyzer,
        upgrade_analyzer: UpgradeAnalyzer,
        implementation_planner: ImplementationPlanner,
        project_planner: ProjectPlanner,
        project_execution_service: ProjectExecutionService,
    ) -> None:
        self._workspace_inspector = workspace_inspector
        self._codebase_analyzer = codebase_analyzer
        self._upgrade_analyzer = upgrade_analyzer
        self._implementation_planner = implementation_planner
        self._project_planner = project_planner
        self._project_execution_service = project_execution_service

    def start_upgrade(
        self, request_text: str, *, project_title: str | None = None
    ) -> ProjectRun:
        workspace = self._workspace_inspector.inspect()
        request = UpgradeRequest(request_text=request_text, title=project_title)
        analysis = self._codebase_analyzer.analyze(workspace)
        upgrade = self._upgrade_analyzer.analyze(analysis, request, workspace)
        specification = Specification(
            project_name=project_title or upgrade.title,
            summary=upgrade.objective,
            requirements=list(upgrade.requirements),
            constraints=list(upgrade.constraints),
        )
        project_specification = ProjectSpecification.from_specification(
            specification
        ).model_copy(update={"objective": upgrade.objective})
        implementation_plan = self._implementation_planner.plan(
            specification, workspace
        )
        implementation_plan.validate_traceability(specification)
        project_plan = self._project_planner.plan(
            project_specification, implementation_plan, workspace
        ).validate_against(project_specification)
        execution_state = self._project_execution_service.start(
            specification, project_specification, project_plan
        ).model_copy(update={"status": ProjectExecutionStatus.AWAITING_PLAN_APPROVAL})
        return ProjectRun(
            specification=specification,
            project_specification=project_specification,
            workspace=workspace,
            implementation_plan=implementation_plan,
            project_plan=project_plan,
            execution_state=execution_state,
            plan_revision_state=PlanRevisionState.from_plan(project_plan),
            mode=ProjectMode.UPGRADE,
            upgrade_context=UpgradeContext(
                request=request,
                codebase_analysis=analysis,
                upgrade_specification=upgrade,
                baseline_validation=BaselineValidation(
                    status=BaselineStatus.UNAVAILABLE,
                    details=(
                        "Baseline validation is not configured for this workspace.",
                    ),
                ),
            ),
        )
