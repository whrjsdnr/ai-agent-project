"""Tests for specification-driven coding-agent orchestration."""

import pytest

from ai_agent_project.agent.acceptance import (
    AcceptanceReport,
    AcceptanceStatus,
    RequirementValidationResult,
)
from ai_agent_project.agent.coding_service import (
    CodingAgentService,
    build_coding_instruction,
)
from ai_agent_project.agent.plan import ImplementationPlan
from ai_agent_project.agent.specification import Specification
from ai_agent_project.agent.specification_parser import SpecificationParseError
from ai_agent_project.agent.state import AgentState, AgentStatus


def make_specification() -> Specification:
    """Create a representative parsed source specification."""
    return Specification.model_validate(
        {
            "project_name": "Example API",
            "requirements": [
                {
                    "id": "REQ-001",
                    "title": "Greeting endpoint",
                    "description": "Expose a greeting endpoint.",
                    "acceptance_criteria": ["GET /greeting returns 200."],
                }
            ],
            "constraints": ["Use FastAPI."],
        }
    )


def make_plan() -> ImplementationPlan:
    """Create a traceable plan with all coding-instruction sections."""
    return ImplementationPlan.model_validate(
        {
            "summary": "Add the greeting endpoint.",
            "tasks": [
                {
                    "id": "TASK-001",
                    "title": "Implement greeting endpoint",
                    "description": "Add the route and its test.",
                    "requirement_ids": ["REQ-001"],
                    "depends_on": ["TASK-000"],
                    "files_to_inspect": ["src/ai_agent_project/api/app.py"],
                    "files_to_modify": ["tests/api/test_app.py"],
                    "files": ["pyproject.toml"],
                },
                {
                    "id": "TASK-000",
                    "title": "Inspect project",
                    "description": "Inspect current API conventions.",
                    "requirement_ids": ["REQ-001"],
                },
            ],
            "validation_commands": ["uv run pytest", "uv run ruff check ."],
        }
    )


class FakeParser:
    """Record parser calls and return a configured outcome."""

    def __init__(self, outcome: Specification | Exception, calls: list[str]) -> None:
        self._outcome = outcome
        self._calls = calls
        self.received_text: str | None = None

    def parse(self, text: str) -> Specification:
        self._calls.append("parse")
        self.received_text = text
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


class FakePlanner:
    """Record planner calls and return a configured outcome."""

    def __init__(self, outcome: ImplementationPlan | Exception, calls: list[str]) -> None:
        self._outcome = outcome
        self._calls = calls
        self.received_specification: Specification | None = None

    def plan(self, specification: Specification) -> ImplementationPlan:
        self._calls.append("plan")
        self.received_specification = specification
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


class FakeAgentService:
    """Record coding instructions without running tools."""

    def __init__(self, state: AgentState, calls: list[str]) -> None:
        self._state = state
        self._calls = calls
        self.received_instruction: str | None = None

    def run(self, instruction: str) -> AgentState:
        self._calls.append("agent")
        self.received_instruction = instruction
        return self._state


class FakeAcceptanceValidator:
    """Record validation after an agent state has been produced."""

    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    def validate(
        self,
        specification: Specification,
        plan: ImplementationPlan,
        agent_state: AgentState,
    ) -> AcceptanceReport:
        del specification, plan, agent_state
        self._calls.append("validate")
        return AcceptanceReport(
            requirements=[
                RequirementValidationResult(
                    requirement_id="REQ-001",
                    status=AcceptanceStatus.PASSED,
                )
            ]
        )


def test_coding_service_orchestrates_parse_plan_and_agent_run() -> None:
    calls: list[str] = []
    specification = make_specification()
    plan = make_plan()
    agent_state = AgentState(status=AgentStatus.COMPLETED, final_answer="Done")
    parser = FakeParser(specification, calls)
    planner = FakePlanner(plan, calls)
    agent = FakeAgentService(agent_state, calls)
    service = CodingAgentService(
        parser,
        planner,
        agent,  # type: ignore[arg-type]
        FakeAcceptanceValidator(calls),
    )

    result = service.run_from_specification("source requirements")

    assert calls == ["parse", "plan", "agent", "validate"]
    assert parser.received_text == "source requirements"
    assert planner.received_specification is specification
    assert result.specification is specification
    assert result.plan is plan
    assert result.agent_run is agent_state
    assert result.acceptance_report.status is AcceptanceStatus.PASSED
    assert agent.received_instruction is not None
    assert "REQ-001" in agent.received_instruction
    assert "TASK-001" in agent.received_instruction


def test_coding_instruction_includes_plan_context_and_execution_guidance() -> None:
    instruction = build_coding_instruction(make_specification(), make_plan())

    for expected in (
        "REQ-001",
        "TASK-001",
        "Dependencies: TASK-000",
        "GET /greeting returns 200.",
        "Files to inspect",
        "src/ai_agent_project/api/app.py",
        "Files to modify",
        "tests/api/test_app.py",
        "Validation commands",
        "uv run pytest",
        "Inspect the actual project before modifying files.",
    ):
        assert expected in instruction


def test_parser_failure_stops_planner_and_agent() -> None:
    calls: list[str] = []
    parser = FakeParser(SpecificationParseError("empty document"), calls)
    planner = FakePlanner(make_plan(), calls)
    agent = FakeAgentService(AgentState(), calls)
    service = CodingAgentService(parser, planner, agent)  # type: ignore[arg-type]

    with pytest.raises(SpecificationParseError, match="empty document"):
        service.run_from_specification("   ")

    assert calls == ["parse"]


def test_planner_failure_stops_agent() -> None:
    calls: list[str] = []
    parser = FakeParser(make_specification(), calls)
    planner = FakePlanner(ValueError("invalid plan"), calls)
    agent = FakeAgentService(AgentState(), calls)
    service = CodingAgentService(parser, planner, agent)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="invalid plan"):
        service.run_from_specification("requirements")

    assert calls == ["parse", "plan"]


def test_agent_failure_preserves_specification_and_plan() -> None:
    calls: list[str] = []
    specification = make_specification()
    plan = make_plan()
    failed_state = AgentState(status=AgentStatus.FAILED, error="validation failed")
    service = CodingAgentService(
        FakeParser(specification, calls),
        FakePlanner(plan, calls),
        FakeAgentService(failed_state, calls),  # type: ignore[arg-type]
    )

    result = service.run_from_specification("requirements")

    assert result.specification is specification
    assert result.plan is plan
    assert result.agent_run.status is AgentStatus.FAILED
    assert result.agent_run.error == "validation failed"
