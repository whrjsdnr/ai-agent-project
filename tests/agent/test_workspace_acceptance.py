"""Tests for deterministic workspace acceptance validation."""

from pathlib import Path

import pytest

from ai_agent_project.agent.acceptance import (
    AcceptanceReport,
    AcceptanceStatus,
    RequirementValidationResult,
)
from ai_agent_project.agent.plan import ImplementationPlan
from ai_agent_project.agent.specification import Specification
from ai_agent_project.agent.state import AgentState, AgentStatus
from ai_agent_project.agent.workspace_acceptance import WorkspaceAcceptanceValidator
from ai_agent_project.tools.base import ToolResult


class FakeShellTool:
    """Capture safe validation commands without starting subprocesses."""

    def __init__(self, result: ToolResult) -> None:
        self.result = result
        self.commands: list[str] = []

    def execute(self, arguments: dict[str, object]) -> ToolResult:
        self.commands.append(str(arguments["command"]))
        return self.result


def make_specification() -> Specification:
    return Specification.model_validate(
        {
            "requirements": [
                {
                    "id": "REQ-001",
                    "description": "Create a reverse-string helper.",
                    "acceptance_criteria": ["Add pytest tests."],
                }
            ]
        }
    )


def make_plan(command: str = "uv run pytest") -> ImplementationPlan:
    return ImplementationPlan.model_validate(
        {
            "tasks": [
                {
                    "id": "TASK-001",
                    "title": "Implement helper",
                    "description": "Add code and tests.",
                    "requirement_ids": ["REQ-001"],
                    "files_to_modify": ["src/string_utils.py", "tests/test_string_utils.py"],
                }
            ],
            "validation_commands": [command],
        }
    )


def test_report_aggregates_pass_fail_and_unknown_statuses() -> None:
    def report(*statuses: AcceptanceStatus) -> AcceptanceReport:
        return AcceptanceReport(
            requirements=[
                RequirementValidationResult(requirement_id=str(index), status=status)
                for index, status in enumerate(statuses)
            ]
        )

    assert report(AcceptanceStatus.PASSED, AcceptanceStatus.PASSED).status is AcceptanceStatus.PASSED
    assert report(AcceptanceStatus.PASSED, AcceptanceStatus.UNKNOWN).status is AcceptanceStatus.UNKNOWN
    assert report(AcceptanceStatus.PASSED, AcceptanceStatus.FAILED).status is AcceptanceStatus.FAILED


def test_validator_records_traceability_files_and_validation_evidence(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/string_utils.py").write_text("def reverse(value): return value[::-1]\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_string_utils.py").write_text("def test_reverse(): pass\n")
    shell = FakeShellTool(ToolResult(success=True, data={}))
    validator = WorkspaceAcceptanceValidator(tmp_path, shell_tool=shell)  # type: ignore[arg-type]

    report = validator.validate(make_specification(), make_plan(), AgentState(status=AgentStatus.COMPLETED))

    requirement = report.requirements[0]
    assert report.status is AcceptanceStatus.PASSED
    assert requirement.implemented_files == ["src/string_utils.py"]
    assert requirement.test_files == ["tests/test_string_utils.py"]
    assert shell.commands == ["uv run pytest"]
    assert "Validation command passed: uv run pytest" in requirement.evidence


def test_validation_failure_overrides_agent_final_answer(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/string_utils.py").touch()
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_string_utils.py").touch()
    shell = FakeShellTool(ToolResult(success=False, error="Command exited with code 1"))
    validator = WorkspaceAcceptanceValidator(tmp_path, shell_tool=shell)  # type: ignore[arg-type]

    report = validator.validate(
        make_specification(),
        make_plan(),
        AgentState(status=AgentStatus.COMPLETED, final_answer="All tests passed"),
    )

    assert report.status is AcceptanceStatus.FAILED
    assert "All tests passed" not in "\n".join(report.requirements[0].evidence)


def test_validator_rejects_unsafe_commands_without_running_shell(tmp_path: Path) -> None:
    shell = FakeShellTool(ToolResult(success=True, data={}))
    validator = WorkspaceAcceptanceValidator(tmp_path, shell_tool=shell)  # type: ignore[arg-type]
    unsafe_plan = ImplementationPlan.model_construct(
        tasks=[], validation_commands=["pytest -q"]
    )

    report = validator.validate(make_specification(), unsafe_plan, AgentState())

    assert report.status is AcceptanceStatus.FAILED
    assert shell.commands == []


def test_failed_agent_produces_failed_report(tmp_path: Path) -> None:
    shell = FakeShellTool(ToolResult(success=True, data={}))
    validator = WorkspaceAcceptanceValidator(tmp_path, shell_tool=shell)  # type: ignore[arg-type]
    plan = ImplementationPlan.model_construct(tasks=[], validation_commands=["uv run pytest"])

    report = validator.validate(
        make_specification(), plan, AgentState(status=AgentStatus.FAILED, error="tool limit")
    )

    assert report.status is AcceptanceStatus.FAILED
    assert "Agent run failed: tool limit" in report.requirements[0].evidence


@pytest.mark.parametrize(
    ("criterion", "test_files", "commands_passed", "expected"),
    [
        (
            "Add pytest tests for the function.",
            ["tests/test_string_utils.py"],
            True,
            AcceptanceStatus.PASSED,
        ),
        ("All tests must pass.", [], True, AcceptanceStatus.PASSED),
        ("All tests must pass.", [], False, AcceptanceStatus.FAILED),
        ("Do not add tests.", ["tests/test_string_utils.py"], True, AcceptanceStatus.UNKNOWN),
        ("Tests are not required.", ["tests/test_string_utils.py"], True, AcceptanceStatus.UNKNOWN),
        ("latest result must be displayed", [], True, AcceptanceStatus.UNKNOWN),
        ("contest mode must be supported", [], True, AcceptanceStatus.UNKNOWN),
        ('is_palindrome("level") returns True', [], True, AcceptanceStatus.UNKNOWN),
    ],
)
def test_criterion_classification_is_conservative(
    criterion: str,
    test_files: list[str],
    commands_passed: bool,
    expected: AcceptanceStatus,
) -> None:
    result = WorkspaceAcceptanceValidator._validate_criterion(
        criterion,
        test_files,
        commands_passed,
        ["Validation command passed: uv run pytest"],
    )

    assert result.status is expected
