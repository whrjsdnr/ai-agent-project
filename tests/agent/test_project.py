"""Tests for provider-neutral project specifications and phase plans."""

import pytest
from pydantic import ValidationError

from ai_agent_project.agent.plan import ImplementationPlan
from ai_agent_project.agent.project import (
    ProjectPhase,
    ProjectPlan,
    ProjectPlanner,
    ProjectSpecification,
)
from ai_agent_project.agent.specification import Specification
from ai_agent_project.agent.workspace import WorkspaceSnapshot


def make_specification() -> Specification:
    return Specification.model_validate(
        {
            "project_name": "Demo project",
            "summary": "Build the demo.",
            "requirements": [
                {
                    "id": "REQ-001",
                    "description": "Create the feature.",
                    "acceptance_criteria": ["Feature works."],
                },
                {
                    "id": "REQ-002",
                    "description": "Add coverage.",
                    "acceptance_criteria": ["Tests pass."],
                },
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
                    "title": "Implement feature",
                    "description": "Create the feature.",
                    "requirement_ids": ["REQ-001"],
                },
                {
                    "id": "TASK-002",
                    "title": "Test feature",
                    "description": "Add coverage.",
                    "requirement_ids": ["REQ-002"],
                    "depends_on": ["TASK-001"],
                },
            ]
        }
    )


def make_project_specification() -> ProjectSpecification:
    return ProjectSpecification.from_specification(make_specification())


def phase(
    phase_id: str,
    requirement_ids: tuple[str, ...],
    task_ids: tuple[str, ...],
    depends_on: tuple[str, ...] = (),
) -> ProjectPhase:
    return ProjectPhase(
        id=phase_id,
        title=phase_id,
        objective=phase_id,
        requirement_ids=requirement_ids,
        task_ids=task_ids,
        depends_on=depends_on,
    )


def make_project_plan(*, phases: tuple[ProjectPhase, ...] | None = None) -> ProjectPlan:
    return ProjectPlan(
        project_title="Demo project",
        phases=phases
        or (
            ProjectPhase(
                id="PHASE-001",
                title="Feature",
                objective="Implement the feature.",
                requirement_ids=("REQ-001",),
                task_ids=("TASK-001",),
            ),
            ProjectPhase(
                id="PHASE-002",
                title="Validation",
                objective="Validate the feature.",
                requirement_ids=("REQ-002",),
                task_ids=("TASK-002",),
                depends_on=("PHASE-001",),
            ),
        ),
        implementation_plan=make_implementation_plan(),
    )


def test_project_specification_is_valid_immutable_and_preserves_conversion() -> None:
    specification = make_specification()
    project = ProjectSpecification.from_specification(specification)

    assert project.title == "Demo project"
    assert project.objective == "Build the demo."
    assert tuple(item.id for item in project.requirements) == ("REQ-001", "REQ-002")
    assert project.requirements[0].acceptance_criteria == ["Feature works."]
    assert project.constraints == ("Python 3.12",)
    with pytest.raises(ValidationError):
        project.title = "Changed"  # type: ignore[misc]


def test_project_specification_rejects_empty_requirements_and_has_defaults() -> None:
    with pytest.raises(ValidationError):
        ProjectSpecification(title="x", objective="x", requirements=())

    source = Specification.model_validate(
        {"requirements": [{"id": "REQ-001", "description": "A"}]}
    )
    project = ProjectSpecification.from_specification(source)
    assert project.title == "Untitled Project"
    assert project.objective == ""
    assert project.constraints == ()
    assert project.acceptance_criteria == ()


def test_project_plan_accepts_valid_ordered_multi_phase_traceability() -> None:
    plan = make_project_plan()
    assert plan.validate_against(make_project_specification()) is plan
    assert [phase.id for phase in plan.phases] == ["PHASE-001", "PHASE-002"]


@pytest.mark.parametrize(
    ("phases", "message"),
    [
        (
            (
                phase("PHASE-001", ("REQ-001",), ("TASK-001",)),
                phase("PHASE-001", ("REQ-002",), ("TASK-002",)),
            ),
            "unique",
        ),
        (
            (
                phase("PHASE-001", ("REQ-001",), ("TASK-001",), ("UNKNOWN",)),
                phase("PHASE-002", ("REQ-002",), ("TASK-002",)),
            ),
            "unknown phase",
        ),
        (
            (
                phase("PHASE-001", ("REQ-001",), ("TASK-001",), ("PHASE-002",)),
                phase("PHASE-002", ("REQ-002",), ("TASK-002",), ("PHASE-001",)),
            ),
            "cycle",
        ),
        (
            (
                phase("PHASE-001", ("REQ-001",), ("TASK-001",)),
                phase("PHASE-002", ("REQ-002",), ("TASK-999",)),
            ),
            "unknown task",
        ),
        (
            (
                phase("PHASE-001", ("REQ-001",), ("TASK-001",)),
                phase("PHASE-002", ("REQ-002",), ("TASK-001", "TASK-002")),
            ),
            "exactly one",
        ),
        (
            (phase("PHASE-001", ("REQ-001",), ("TASK-001",)),),
            "exactly one",
        ),
    ],
)
def test_project_plan_rejects_invalid_phase_or_task_structure(
    phases: tuple[ProjectPhase, ...], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        make_project_plan(phases=phases)


@pytest.mark.parametrize(
    ("phases", "message"),
    [
        (
            (
                phase("PHASE-001", ("REQ-999",), ("TASK-001",)),
                phase("PHASE-002", ("REQ-002",), ("TASK-002",)),
            ),
            "unknown requirement",
        ),
        (
            (phase("PHASE-001", ("REQ-001",), ("TASK-001", "TASK-002")),),
            "Every requirement",
        ),
    ],
)
def test_project_plan_rejects_invalid_requirement_coverage(
    phases: tuple[ProjectPhase, ...], message: str
) -> None:
    plan = make_project_plan(phases=phases)
    with pytest.raises(ValueError, match=message):
        plan.validate_against(make_project_specification())


class FakeProjectPlanner:
    def __init__(self) -> None:
        self.received_workspace: WorkspaceSnapshot | None = None

    def plan(
        self,
        specification: ProjectSpecification,
        implementation_plan: ImplementationPlan,
        workspace: WorkspaceSnapshot | None = None,
    ) -> ProjectPlan:
        self.received_workspace = workspace
        return make_project_plan().validate_against(specification)


def test_project_planner_protocol_supports_optional_workspace() -> None:
    planner: ProjectPlanner = FakeProjectPlanner()
    project = make_project_specification()
    implementation_plan = make_implementation_plan()

    assert planner.plan(project, implementation_plan).project_title == "Demo project"
    snapshot = WorkspaceSnapshot(files=["src/example.py"])
    planner.plan(project, implementation_plan, snapshot)
    assert planner.received_workspace is snapshot  # type: ignore[attr-defined]
