"""Provider-neutral bootstrap from source text to a ready project execution."""

from pydantic import BaseModel, ConfigDict

from ai_agent_project.agent.plan import ImplementationPlan, ImplementationPlanner
from ai_agent_project.agent.project import (
    ProjectPlan,
    ProjectPlanner,
    ProjectSpecification,
)
from ai_agent_project.agent.project_execution import (
    ProjectExecutionService,
    ProjectExecutionState,
)
from ai_agent_project.agent.specification import Specification
from ai_agent_project.agent.specification_parser import SpecificationParser
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
        return ProjectRun(
            specification=specification,
            project_specification=project_specification,
            workspace=workspace,
            implementation_plan=implementation_plan,
            project_plan=project_plan,
            execution_state=execution_state,
        )
