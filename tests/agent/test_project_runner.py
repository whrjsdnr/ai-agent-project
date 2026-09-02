"""Tests for provider-neutral project bootstrap orchestration."""

import pytest
from pydantic import ValidationError

from ai_agent_project.agent.plan import ImplementationPlan
from ai_agent_project.agent.project import (
    ProjectPhase,
    ProjectPlan,
    ProjectSpecification,
)
from ai_agent_project.agent.project_execution import (
    PhaseExecutionRecord,
    ProjectExecutionState,
    ProjectExecutionStatus,
)
from ai_agent_project.agent.project_runner import ProjectRunner
from ai_agent_project.agent.specification import Specification
from ai_agent_project.agent.workspace import WorkspaceSnapshot


def make_specification() -> Specification:
    return Specification.model_validate(
        {
            "project_name": "Original title",
            "summary": "Project objective.",
            "requirements": [
                {
                    "id": "REQ-001",
                    "description": "Build feature.",
                    "acceptance_criteria": ["Feature works."],
                }
            ],
            "constraints": ["Python 3.12"],
        }
    )


def make_implementation_plan() -> ImplementationPlan:
    return ImplementationPlan.model_validate(
        {
            "tasks": [
                {
                    "id": "TASK-001",
                    "title": "Build feature",
                    "description": "Build the feature.",
                    "requirement_ids": ["REQ-001"],
                }
            ],
            "validation_commands": ["uv run pytest"],
        }
    )


def make_project_plan(plan: ImplementationPlan) -> ProjectPlan:
    return ProjectPlan(
        project_title="Project title",
        phases=(
            ProjectPhase(
                id="PHASE-001",
                title="Feature",
                objective="Build the feature.",
                requirement_ids=("REQ-001",),
                task_ids=("TASK-001",),
            ),
        ),
        implementation_plan=plan,
    )


class FakeParser:
    def __init__(
        self, specification: Specification | Exception, calls: list[str]
    ) -> None:
        self._specification = specification
        self._calls = calls
        self.text: str | None = None

    def parse(self, text: str) -> Specification:
        self._calls.append("parse")
        self.text = text
        if isinstance(self._specification, Exception):
            raise self._specification
        return self._specification


class FakeWorkspaceInspector:
    def __init__(
        self, workspace: WorkspaceSnapshot | Exception, calls: list[str]
    ) -> None:
        self._workspace = workspace
        self._calls = calls

    def inspect(self) -> WorkspaceSnapshot:
        self._calls.append("inspect")
        if isinstance(self._workspace, Exception):
            raise self._workspace
        return self._workspace


class FakeImplementationPlanner:
    def __init__(self, plan: ImplementationPlan | Exception, calls: list[str]) -> None:
        self._plan = plan
        self._calls = calls
        self.specification: Specification | None = None
        self.workspace: WorkspaceSnapshot | None = None

    def plan(
        self,
        specification: Specification,
        workspace: WorkspaceSnapshot | None = None,
    ) -> ImplementationPlan:
        self._calls.append("implementation_plan")
        self.specification = specification
        self.workspace = workspace
        if isinstance(self._plan, Exception):
            raise self._plan
        return self._plan


class FakeProjectPlanner:
    def __init__(self, plan: ProjectPlan | Exception, calls: list[str]) -> None:
        self._plan = plan
        self._calls = calls
        self.specification: ProjectSpecification | None = None
        self.implementation_plan: ImplementationPlan | None = None
        self.workspace: WorkspaceSnapshot | None = None

    def plan(
        self,
        specification: ProjectSpecification,
        implementation_plan: ImplementationPlan,
        workspace: WorkspaceSnapshot | None = None,
    ) -> ProjectPlan:
        self._calls.append("project_plan")
        self.specification = specification
        self.implementation_plan = implementation_plan
        self.workspace = workspace
        if isinstance(self._plan, Exception):
            raise self._plan
        return self._plan


class FakeProjectExecutionService:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls
        self.arguments: (
            tuple[Specification, ProjectSpecification, ProjectPlan] | None
        ) = None

    def start(
        self,
        specification: Specification,
        project_specification: ProjectSpecification,
        project_plan: ProjectPlan,
    ) -> ProjectExecutionState:
        self._calls.append("execution_start")
        self.arguments = (specification, project_specification, project_plan)
        return ProjectExecutionState(
            project_title=project_plan.project_title,
            status=ProjectExecutionStatus.READY,
            current_phase_id=project_plan.phases[0].id,
            phase_records=tuple(
                PhaseExecutionRecord(phase_id=phase.id) for phase in project_plan.phases
            ),
        )


def make_runner(
    parser_value: Specification | Exception,
    workspace_value: WorkspaceSnapshot | Exception,
    implementation_value: ImplementationPlan | Exception,
    project_value: ProjectPlan | Exception,
    calls: list[str],
) -> tuple[
    ProjectRunner,
    FakeImplementationPlanner,
    FakeProjectPlanner,
    FakeProjectExecutionService,
]:
    implementation_planner = FakeImplementationPlanner(implementation_value, calls)
    project_planner = FakeProjectPlanner(project_value, calls)
    execution_service = FakeProjectExecutionService(calls)
    return (
        ProjectRunner(
            FakeParser(parser_value, calls),
            FakeWorkspaceInspector(workspace_value, calls),
            implementation_planner,
            project_planner,
            execution_service,  # type: ignore[arg-type]
        ),
        implementation_planner,
        project_planner,
        execution_service,
    )


def test_project_runner_bootstraps_in_exact_order_without_phase_execution() -> None:
    calls: list[str] = []
    specification = make_specification()
    workspace = WorkspaceSnapshot(files=["src/feature.py"])
    implementation_plan = make_implementation_plan()
    project_plan = make_project_plan(implementation_plan)
    runner, implementation_planner, project_planner, execution_service = make_runner(
        specification,
        workspace,
        implementation_plan,
        project_plan,
        calls,
    )

    run = runner.start(
        "# Requirements", project_title="Explicit title", source_format="markdown"
    )

    assert calls == [
        "parse",
        "inspect",
        "implementation_plan",
        "project_plan",
        "execution_start",
    ]
    assert run.specification is specification
    assert run.workspace is workspace
    assert run.implementation_plan is implementation_plan
    assert run.project_plan is project_plan
    assert run.project_specification.title == "Explicit title"
    assert run.project_specification.source_format == "markdown"
    assert run.project_specification.requirements[0].id == "REQ-001"
    assert run.project_specification.requirements[0].acceptance_criteria == [
        "Feature works."
    ]
    assert run.project_specification.constraints == ("Python 3.12",)
    assert implementation_planner.workspace is workspace
    assert project_planner.workspace is workspace
    assert project_planner.implementation_plan is implementation_plan
    assert execution_service.arguments == (
        specification,
        run.project_specification,
        project_plan,
    )
    assert run.execution_state.status is ProjectExecutionStatus.READY
    assert all(record.execution is None for record in run.execution_state.phase_records)
    assert all(
        record.progress_report is None for record in run.execution_state.phase_records
    )
    assert all(
        record.checkpoint is None for record in run.execution_state.phase_records
    )
    assert all(
        record.attempt_count == 0 for record in run.execution_state.phase_records
    )
    with pytest.raises(ValidationError):
        run.workspace = WorkspaceSnapshot()  # type: ignore[misc]


def test_project_runner_uses_conversion_defaults_and_execution_state_is_unexecuted() -> (
    None
):
    calls: list[str] = []
    specification = make_specification()
    implementation_plan = make_implementation_plan()
    project_plan = make_project_plan(implementation_plan)
    runner, _, _, _ = make_runner(
        specification,
        WorkspaceSnapshot(),
        implementation_plan,
        project_plan,
        calls,
    )

    run = runner.start("requirements")

    assert run.project_specification.title == "Original title"
    assert run.project_specification.source_format is None
    assert calls[-1] == "execution_start"


@pytest.mark.parametrize(
    (
        "parser_value",
        "workspace_value",
        "implementation_value",
        "project_value",
        "expected_calls",
    ),
    [
        (
            ValueError("parse failed"),
            WorkspaceSnapshot(),
            make_implementation_plan(),
            make_project_plan(make_implementation_plan()),
            ["parse"],
        ),
        (
            make_specification(),
            ValueError("workspace failed"),
            make_implementation_plan(),
            make_project_plan(make_implementation_plan()),
            ["parse", "inspect"],
        ),
        (
            make_specification(),
            WorkspaceSnapshot(),
            ValueError("implementation failed"),
            make_project_plan(make_implementation_plan()),
            ["parse", "inspect", "implementation_plan"],
        ),
        (
            make_specification(),
            WorkspaceSnapshot(),
            make_implementation_plan(),
            ValueError("project failed"),
            ["parse", "inspect", "implementation_plan", "project_plan"],
        ),
    ],
)
def test_project_runner_short_circuits_failures(
    parser_value: Specification | Exception,
    workspace_value: WorkspaceSnapshot | Exception,
    implementation_value: ImplementationPlan | Exception,
    project_value: ProjectPlan | Exception,
    expected_calls: list[str],
) -> None:
    calls: list[str] = []
    runner, _, _, _ = make_runner(
        parser_value,
        workspace_value,
        implementation_value,
        project_value,
        calls,
    )

    with pytest.raises(ValueError):
        runner.start("requirements")

    assert calls == expected_calls


def test_invalid_project_plan_prevents_execution_start() -> None:
    calls: list[str] = []
    specification = make_specification()
    implementation_plan = make_implementation_plan()
    invalid_plan = ProjectPlan.model_construct(
        project_title="Invalid",
        phases=(
            ProjectPhase(
                id="PHASE-001",
                title="Invalid",
                objective="Invalid.",
                requirement_ids=("REQ-999",),
                task_ids=("TASK-001",),
            ),
        ),
        implementation_plan=implementation_plan,
    )
    runner, _, _, _ = make_runner(
        specification,
        WorkspaceSnapshot(),
        implementation_plan,
        invalid_plan,
        calls,
    )

    with pytest.raises(ValueError, match="unknown requirement"):
        runner.start("requirements")

    assert calls == ["parse", "inspect", "implementation_plan", "project_plan"]
