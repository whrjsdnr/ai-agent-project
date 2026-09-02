"""Tests for provider-neutral single-phase execution."""

import pytest
from pydantic import ValidationError

from ai_agent_project.agent.acceptance import (
    AcceptanceReport,
    AcceptanceStatus,
    RequirementValidationResult,
)
from ai_agent_project.agent.phase_execution import (
    PhaseExecutionResult,
    PhaseExecutionService,
    PhaseExecutionStatus,
    build_phase_implementation_plan,
    build_phase_specification,
)
from ai_agent_project.agent.plan import ImplementationPlan
from ai_agent_project.agent.project import (
    ProjectPhase,
    ProjectPlan,
    ProjectSpecification,
)
from ai_agent_project.agent.specification import Specification
from ai_agent_project.agent.state import AgentState, AgentStatus


def make_specification() -> Specification:
    return Specification.model_validate(
        {
            "project_name": "Phase demo",
            "summary": "Deliver phases safely.",
            "requirements": [
                {
                    "id": "REQ-001",
                    "description": "Implement the foundation.",
                    "acceptance_criteria": ["Foundation works."],
                },
                {
                    "id": "REQ-002",
                    "description": "Implement the extension.",
                    "acceptance_criteria": ["Extension works."],
                },
            ],
            "constraints": ["Keep compatibility."],
            "assumptions": ["The workspace already exists."],
        }
    )


def make_plan() -> ImplementationPlan:
    return ImplementationPlan.model_validate(
        {
            "summary": "Build foundation then extension.",
            "tasks": [
                {
                    "id": "TASK-001",
                    "title": "Inspect foundation",
                    "description": "Inspect existing foundation code.",
                    "requirement_ids": ["REQ-001"],
                    "files_to_inspect": ["src/foundation.py"],
                },
                {
                    "id": "TASK-002",
                    "title": "Implement foundation",
                    "description": "Implement the foundation.",
                    "requirement_ids": ["REQ-001"],
                    "depends_on": ["TASK-001"],
                    "files_to_modify": ["src/foundation.py"],
                    "files": ["tests/test_foundation.py"],
                },
                {
                    "id": "TASK-003",
                    "title": "Implement extension",
                    "description": "Implement the extension.",
                    "requirement_ids": ["REQ-002"],
                    "depends_on": ["TASK-002"],
                    "files_to_inspect": ["src/foundation.py"],
                    "files_to_modify": ["src/extension.py"],
                },
            ],
            "validation_commands": ["uv run pytest"],
        }
    )


def make_project_plan() -> tuple[ProjectSpecification, ProjectPlan]:
    specification = make_specification()
    project_specification = ProjectSpecification.from_specification(specification)
    plan = ProjectPlan(
        project_title="Phase demo",
        phases=(
            ProjectPhase(
                id="PHASE-001",
                title="Foundation",
                objective="Build the foundation.",
                requirement_ids=("REQ-001",),
                task_ids=("TASK-001", "TASK-002"),
                acceptance_criteria=("Foundation is validated.",),
            ),
            ProjectPhase(
                id="PHASE-002",
                title="Extension",
                objective="Build the extension.",
                requirement_ids=("REQ-002",),
                task_ids=("TASK-003",),
                depends_on=("PHASE-001",),
                acceptance_criteria=("Extension is validated.",),
            ),
        ),
        implementation_plan=make_plan(),
    )
    return project_specification, plan


def report(
    status: AcceptanceStatus, requirement_id: str = "REQ-001"
) -> AcceptanceReport:
    return AcceptanceReport(
        requirements=[
            RequirementValidationResult(
                requirement_id=requirement_id,
                status=status,
                criteria=[
                    {
                        "criterion": "Foundation works.",
                        "status": status,
                        "evidence": ["test evidence"],
                    }
                ],
                evidence=["test evidence"],
            )
        ]
    )


class FakeAgentService:
    def __init__(self, states: list[AgentState]) -> None:
        self._states = states
        self.instructions: list[str] = []

    def run(self, instruction: str) -> AgentState:
        self.instructions.append(instruction)
        return self._states.pop(0)


class FakeAcceptanceValidator:
    def __init__(self, reports: list[AcceptanceReport]) -> None:
        self._reports = reports
        self.calls: list[tuple[Specification, ImplementationPlan, AgentState]] = []

    def validate(
        self,
        specification: Specification,
        plan: ImplementationPlan,
        agent_state: AgentState,
    ) -> AcceptanceReport:
        self.calls.append((specification, plan, agent_state))
        return self._reports.pop(0)


def test_phase_result_is_immutable_and_uses_explicit_status() -> None:
    result = PhaseExecutionResult(
        phase_id="PHASE-001",
        status=PhaseExecutionStatus.PENDING,
        requirement_ids=("REQ-001",),
        task_ids=("TASK-001",),
        agent_run=AgentState(),
        acceptance_report=AcceptanceReport(),
    )

    assert result.status is PhaseExecutionStatus.PENDING
    with pytest.raises(ValidationError):
        result.status = PhaseExecutionStatus.COMPLETED  # type: ignore[misc]


def test_phase_scoping_keeps_only_selected_requirements_tasks_and_context() -> None:
    specification = make_specification()
    _, project_plan = make_project_plan()
    phase = project_plan.phases[0]

    scoped_specification = build_phase_specification(specification, phase)
    scoped_plan = build_phase_implementation_plan(project_plan, phase)

    assert [item.id for item in scoped_specification.requirements] == ["REQ-001"]
    assert scoped_specification.constraints == specification.constraints
    assert scoped_specification.assumptions == specification.assumptions
    assert [item.id for item in scoped_plan.tasks] == ["TASK-001", "TASK-002"]
    assert scoped_plan.tasks[1].depends_on == ["TASK-001"]
    assert scoped_plan.tasks[1].files == ["tests/test_foundation.py"]
    assert [item.id for item in project_plan.implementation_plan.tasks] == [
        "TASK-001",
        "TASK-002",
        "TASK-003",
    ]
    assert project_plan.implementation_plan.tasks[1].depends_on == ["TASK-001"]


def test_phase_scoping_removes_external_dependency_without_pulling_task() -> None:
    _, project_plan = make_project_plan()

    scoped_plan = build_phase_implementation_plan(project_plan, project_plan.phases[1])

    assert [task.id for task in scoped_plan.tasks] == ["TASK-003"]
    assert scoped_plan.tasks[0].depends_on == []
    assert project_plan.implementation_plan.tasks[2].depends_on == ["TASK-002"]


def test_phase_execution_scopes_instruction_and_acceptance() -> None:
    specification = make_specification()
    project_specification, project_plan = make_project_plan()
    agent = FakeAgentService(
        [AgentState(status=AgentStatus.COMPLETED, final_answer="done")]
    )
    validator = FakeAcceptanceValidator([report(AcceptanceStatus.PASSED)])
    service = PhaseExecutionService(agent, validator)  # type: ignore[arg-type]

    result = service.execute(
        specification, project_specification, project_plan, "PHASE-001"
    )

    assert result.status is PhaseExecutionStatus.COMPLETED
    assert result.summary == "done"
    instruction = agent.instructions[0]
    for expected in (
        "PHASE-001",
        "Foundation",
        "Build the foundation.",
        "TASK-001",
        "TASK-002",
        "REQ-001",
        "Foundation is validated.",
    ):
        assert expected in instruction
    assert "TASK-003" not in instruction
    assert "REQ-002" not in instruction
    validated_specification, validated_plan, _ = validator.calls[0]
    assert [item.id for item in validated_specification.requirements] == ["REQ-001"]
    assert [task.id for task in validated_plan.tasks] == ["TASK-001", "TASK-002"]


def test_phase_execution_includes_dependency_as_unproven_context() -> None:
    specification = make_specification()
    project_specification, project_plan = make_project_plan()
    agent = FakeAgentService([AgentState(status=AgentStatus.COMPLETED)])
    service = PhaseExecutionService(
        agent, FakeAcceptanceValidator([report(AcceptanceStatus.PASSED, "REQ-002")])
    )  # type: ignore[arg-type]

    service.execute(specification, project_specification, project_plan, "PHASE-002")

    assert "PHASE-001" in agent.instructions[0]
    assert "completion is not asserted" in agent.instructions[0]


@pytest.mark.parametrize(
    ("acceptance_status", "expected_status"),
    [
        (AcceptanceStatus.PASSED, PhaseExecutionStatus.COMPLETED),
        (AcceptanceStatus.UNKNOWN, PhaseExecutionStatus.UNKNOWN),
        (AcceptanceStatus.FAILED, PhaseExecutionStatus.FAILED),
    ],
)
def test_phase_execution_maps_acceptance_status(
    acceptance_status: AcceptanceStatus,
    expected_status: PhaseExecutionStatus,
) -> None:
    specification = make_specification()
    project_specification, project_plan = make_project_plan()
    agent = FakeAgentService([AgentState(status=AgentStatus.COMPLETED)])
    service = PhaseExecutionService(
        agent,
        FakeAcceptanceValidator([report(acceptance_status)]),
        max_repair_attempts=0,
    )  # type: ignore[arg-type]

    result = service.execute(
        specification, project_specification, project_plan, "PHASE-001"
    )

    assert result.status is expected_status


def test_agent_failure_is_failed_without_repair() -> None:
    specification = make_specification()
    project_specification, project_plan = make_project_plan()
    agent = FakeAgentService(
        [AgentState(status=AgentStatus.FAILED, error="tool limit")]
    )
    validator = FakeAcceptanceValidator([report(AcceptanceStatus.FAILED)])
    service = PhaseExecutionService(agent, validator)  # type: ignore[arg-type]

    result = service.execute(
        specification, project_specification, project_plan, "PHASE-001"
    )

    assert result.status is PhaseExecutionStatus.FAILED
    assert len(agent.instructions) == 1
    assert result.repair_attempts == ()


def test_failed_phase_repairs_and_revalidates_with_bounded_history() -> None:
    specification = make_specification()
    project_specification, project_plan = make_project_plan()
    agent = FakeAgentService(
        [
            AgentState(status=AgentStatus.COMPLETED),
            AgentState(status=AgentStatus.COMPLETED, final_answer="fixed"),
        ]
    )
    validator = FakeAcceptanceValidator(
        [report(AcceptanceStatus.FAILED), report(AcceptanceStatus.PASSED)]
    )
    service = PhaseExecutionService(agent, validator, max_repair_attempts=2)  # type: ignore[arg-type]

    result = service.execute(
        specification, project_specification, project_plan, "PHASE-001"
    )

    assert result.status is PhaseExecutionStatus.COMPLETED
    assert len(agent.instructions) == 2
    assert len(validator.calls) == 2
    assert len(result.repair_attempts) == 1
    assert result.repair_attempts[0].attempt == 1
    assert result.repair_attempts[0].failed_requirement_ids == ["REQ-001"]
    assert "Failed requirement: REQ-001" in agent.instructions[1]


def test_unknown_never_repairs_and_max_attempts_are_respected() -> None:
    specification = make_specification()
    project_specification, project_plan = make_project_plan()
    unknown_agent = FakeAgentService([AgentState(status=AgentStatus.COMPLETED)])
    unknown_service = PhaseExecutionService(
        unknown_agent,
        FakeAcceptanceValidator([report(AcceptanceStatus.UNKNOWN)]),
    )  # type: ignore[arg-type]

    unknown_result = unknown_service.execute(
        specification, project_specification, project_plan, "PHASE-001"
    )

    assert unknown_result.status is PhaseExecutionStatus.UNKNOWN
    assert len(unknown_agent.instructions) == 1

    failed_agent = FakeAgentService(
        [AgentState(status=AgentStatus.COMPLETED) for _ in range(3)]
    )
    failed_validator = FakeAcceptanceValidator(
        [report(AcceptanceStatus.FAILED) for _ in range(3)]
    )
    failed_service = PhaseExecutionService(
        failed_agent, failed_validator, max_repair_attempts=2
    )  # type: ignore[arg-type]
    failed_result = failed_service.execute(
        specification, project_specification, project_plan, "PHASE-001"
    )

    assert failed_result.status is PhaseExecutionStatus.FAILED
    assert len(failed_agent.instructions) == 3
    assert len(failed_result.repair_attempts) == 2


def test_unknown_phase_and_negative_repair_limit_are_rejected() -> None:
    specification = make_specification()
    project_specification, project_plan = make_project_plan()
    service = PhaseExecutionService(
        FakeAgentService([]),
        FakeAcceptanceValidator([]),  # type: ignore[arg-type]
    )

    with pytest.raises(ValueError, match="Unknown project phase"):
        service.execute(specification, project_specification, project_plan, "PHASE-999")
    with pytest.raises(ValueError, match="max_repair_attempts"):
        PhaseExecutionService(
            FakeAgentService([]), FakeAcceptanceValidator([]), max_repair_attempts=-1
        )  # type: ignore[arg-type]
