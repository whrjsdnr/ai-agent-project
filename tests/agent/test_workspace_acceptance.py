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


class CommandResultsShellTool:
    """Return deterministic results per command for attribution tests."""

    def __init__(self, results: dict[str, ToolResult]) -> None:
        self.results = results
        self.commands: list[str] = []

    def execute(self, arguments: dict[str, object]) -> ToolResult:
        command = str(arguments["command"])
        self.commands.append(command)
        return self.results[command]


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
                    "files_to_modify": [
                        "src/string_utils.py",
                        "tests/test_string_utils.py",
                    ],
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

    assert (
        report(AcceptanceStatus.PASSED, AcceptanceStatus.PASSED).status
        is AcceptanceStatus.PASSED
    )
    assert (
        report(AcceptanceStatus.PASSED, AcceptanceStatus.UNKNOWN).status
        is AcceptanceStatus.UNKNOWN
    )
    assert (
        report(AcceptanceStatus.PASSED, AcceptanceStatus.FAILED).status
        is AcceptanceStatus.FAILED
    )


def test_validator_records_traceability_files_and_validation_evidence(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/string_utils.py").write_text(
        "def reverse(value): return value[::-1]\n"
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_string_utils.py").write_text("def test_reverse(): pass\n")
    shell = FakeShellTool(ToolResult(success=True, data={}))
    validator = WorkspaceAcceptanceValidator(tmp_path, shell_tool=shell)  # type: ignore[arg-type]

    report = validator.validate(
        make_specification(), make_plan(), AgentState(status=AgentStatus.COMPLETED)
    )

    requirement = report.requirements[0]
    assert report.status is AcceptanceStatus.PASSED
    assert requirement.implemented_files == ["src/string_utils.py"]
    assert requirement.test_files == ["tests/test_string_utils.py"]
    assert shell.commands == ["uv run pytest"]
    assert "Validation command passed: uv run pytest" in requirement.evidence


def test_traceability_collects_inspect_modify_and_legacy_files(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/example.py").touch()
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_example.py").touch()
    specification = Specification.model_validate(
        {"requirements": [{"id": "REQ-001", "description": "feature"}]}
    )
    plan = ImplementationPlan.model_validate(
        {
            "tasks": [
                {
                    "id": "TASK-001",
                    "title": "feature",
                    "description": "feature",
                    "requirement_ids": ["REQ-001"],
                    "files_to_modify": ["src/example.py", "tests/test_example.py"],
                    "files_to_inspect": ["tests/test_example.py", "src/example.py"],
                    "files": ["tests/test_example.py"],
                }
            ],
            "validation_commands": ["uv run pytest"],
        }
    )
    report = WorkspaceAcceptanceValidator(
        tmp_path,
        shell_tool=FakeShellTool(ToolResult(success=True, data={})),  # type: ignore[arg-type]
    ).validate(specification, plan, AgentState(status=AgentStatus.COMPLETED))

    result = report.requirements[0]
    assert result.implemented_files == ["src/example.py"]
    assert result.test_files == ["tests/test_example.py"]


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


def test_validator_rejects_unsafe_commands_without_running_shell(
    tmp_path: Path,
) -> None:
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
    plan = ImplementationPlan.model_construct(
        tasks=[], validation_commands=["uv run pytest"]
    )

    report = validator.validate(
        make_specification(),
        plan,
        AgentState(status=AgentStatus.FAILED, error="tool limit"),
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
        (
            "All existing pytest tests pass without modification unless tests are explicitly extended.",
            [],
            True,
            AcceptanceStatus.PASSED,
        ),
        (
            "All existing pytest tests pass without modification unless tests are explicitly extended.",
            [],
            False,
            AcceptanceStatus.FAILED,
        ),
        ("All tests must pass.", [], False, AcceptanceStatus.FAILED),
        (
            "Do not add tests.",
            ["tests/test_string_utils.py"],
            True,
            AcceptanceStatus.UNKNOWN,
        ),
        (
            "Tests are not required.",
            ["tests/test_string_utils.py"],
            True,
            AcceptanceStatus.UNKNOWN,
        ),
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


@pytest.mark.parametrize(
    ("criterion", "assertion"),
    [
        (
            'is_digits_only("12345") returns True',
            'assert is_digits_only("12345") is True',
        ),
        (
            'is_digits_only("12a") returns False',
            'assert is_digits_only("12a") is False',
        ),
        ('is_digits_only("") returns False', 'assert not is_digits_only("")'),
        (
            'reverse_string("abc") returns "cba"',
            'assert reverse_string("abc") == "cba"',
        ),
        ('is_palindrome("level") returns True', 'assert is_palindrome("level")'),
        ('is_palindrome("hello") returns False', 'assert not is_palindrome("hello")'),
    ],
)
def test_functional_criteria_match_direct_ast_assertions(
    tmp_path: Path,
    criterion: str,
    assertion: str,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/string_utils.py").touch()
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_string_utils.py").write_text(assertion)
    specification = Specification.model_validate(
        {
            "requirements": [
                {
                    "id": "REQ-001",
                    "description": "feature",
                    "acceptance_criteria": [criterion],
                }
            ]
        }
    )
    shell = FakeShellTool(ToolResult(success=True, data={}))
    report = WorkspaceAcceptanceValidator(tmp_path, shell_tool=shell).validate(  # type: ignore[arg-type]
        specification, make_plan(), AgentState(status=AgentStatus.COMPLETED)
    )

    result = report.requirements[0].criteria[0]
    assert result.status is AcceptanceStatus.PASSED
    assert any("Matched test assertion" in item for item in result.evidence)


def test_functional_criterion_without_exact_assertion_is_unknown(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/string_utils.py").touch()
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_string_utils.py").write_text(
        'assert is_digits_only("999") is True'
    )
    specification = Specification.model_validate(
        {
            "requirements": [
                {
                    "id": "REQ-001",
                    "description": "feature",
                    "acceptance_criteria": ['is_digits_only("12345") returns True'],
                }
            ]
        }
    )
    report = WorkspaceAcceptanceValidator(
        tmp_path,
        shell_tool=FakeShellTool(ToolResult(success=True, data={})),  # type: ignore[arg-type]
    ).validate(specification, make_plan(), AgentState(status=AgentStatus.COMPLETED))

    assert report.requirements[0].criteria[0].status is AcceptanceStatus.UNKNOWN


def test_phase_local_document_validation_uses_hashes_not_git(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("before\n")
    (tmp_path / "app").mkdir()
    (tmp_path / "app/main.py").write_text("earlier phase change\n")
    specification = Specification.model_validate(
        {
            "requirements": [
                {
                    "id": "REQ-001",
                    "description": "Document filtering.",
                    "acceptance_criteria": ["Document completed filtering."],
                }
            ]
        }
    )
    plan = ImplementationPlan.model_validate(
        {
            "tasks": [
                {
                    "id": "T3",
                    "title": "Docs",
                    "description": "README only.",
                    "requirement_ids": ["REQ-001"],
                    "required_file_contents": [
                        {
                            "path": "README.md",
                            "required_fragments": ["completed", "true", "false"],
                        }
                    ],
                    "allowed_changed_files": ["README.md"],
                }
            ]
        }
    )
    shell = FakeShellTool(ToolResult(success=True, data={}))
    validator = WorkspaceAcceptanceValidator(tmp_path, shell_tool=shell)  # type: ignore[arg-type]
    before = validator.capture_workspace_state()
    (tmp_path / "README.md").write_text("completed=true or false\n")
    report = validator.validate(
        specification,
        plan,
        AgentState(status=AgentStatus.COMPLETED),
        workspace_before=before,
    )

    assert report.requirements[0].status is AcceptanceStatus.PASSED
    assert shell.commands == ["uv run pytest"]


def test_phase_local_document_validation_rejects_disallowed_changes(
    tmp_path: Path,
) -> None:
    (tmp_path / "README.md").write_text("before\n")
    (tmp_path / "app").mkdir()
    (tmp_path / "app/main.py").write_text("before\n")
    specification = Specification.model_validate(
        {"requirements": [{"id": "REQ-001", "description": "Document."}]}
    )
    plan = ImplementationPlan.model_validate(
        {
            "tasks": [
                {
                    "id": "T3",
                    "title": "Docs",
                    "description": "README only.",
                    "requirement_ids": ["REQ-001"],
                    "allowed_changed_files": ["README.md"],
                }
            ]
        }
    )
    validator = WorkspaceAcceptanceValidator(
        tmp_path, shell_tool=FakeShellTool(ToolResult(success=True, data={}))
    )  # type: ignore[arg-type]
    before = validator.capture_workspace_state()
    (tmp_path / "README.md").write_text("after\n")
    (tmp_path / "app/main.py").write_text("unexpected\n")
    report = validator.validate(
        specification,
        plan,
        AgentState(status=AgentStatus.COMPLETED),
        workspace_before=before,
    )

    assert report.requirements[0].status is AcceptanceStatus.FAILED


def test_functional_evidence_does_not_override_failed_validation(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/string_utils.py").touch()
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_string_utils.py").write_text(
        'assert is_digits_only("12345") is True'
    )
    specification = Specification.model_validate(
        {
            "requirements": [
                {
                    "id": "REQ-001",
                    "description": "feature",
                    "acceptance_criteria": ['is_digits_only("12345") returns True'],
                }
            ]
        }
    )
    report = WorkspaceAcceptanceValidator(
        tmp_path,
        shell_tool=FakeShellTool(ToolResult(success=False, error="pytest failed")),  # type: ignore[arg-type]
    ).validate(specification, make_plan(), AgentState(status=AgentStatus.COMPLETED))

    assert report.requirements[0].criteria[0].status is AcceptanceStatus.FAILED


def test_task_validation_command_is_attributable_requirement_evidence(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/store.py").write_text("# existing store\n")
    specification = Specification.model_validate(
        {
            "requirements": [
                {
                    "id": "UPG-REQ-001",
                    "description": "Filter Todos by completion.",
                    "acceptance_criteria": [
                        "Support optional completed filtering while preserving unfiltered listing."
                    ],
                },
                {
                    "id": "UPG-REQ-002",
                    "description": "Preserve unrelated API behavior.",
                    "acceptance_criteria": ["Existing API behavior is preserved."],
                },
            ]
        }
    )
    plan = ImplementationPlan.model_validate(
        {
            "tasks": [
                {
                    "id": "TASK-FILTER",
                    "title": "Test filtering",
                    "description": "Validate Todo completion filtering.",
                    "requirement_ids": ["UPG-REQ-001"],
                    "files_to_modify": ["src/store.py"],
                    "validation_commands": [
                        "uv run pytest tests/test_todos.py::test_store_list_filtering"
                    ],
                },
                {
                    "id": "TASK-OTHER",
                    "title": "Other behavior",
                    "description": "Do not validate unrelated behavior here.",
                    "requirement_ids": ["UPG-REQ-002"],
                },
            ]
        }
    )
    command = "uv run pytest tests/test_todos.py::test_store_list_filtering"
    validator = WorkspaceAcceptanceValidator(
        tmp_path,
        shell_tool=CommandResultsShellTool(
            {
                "uv run pytest": ToolResult(success=True, data={}),
                command: ToolResult(success=True, data={}),
            }
        ),  # type: ignore[arg-type]
    )

    report = validator.validate(
        specification, plan, AgentState(status=AgentStatus.COMPLETED)
    )

    assert [item.status for item in report.requirements] == [
        AcceptanceStatus.PASSED,
        AcceptanceStatus.UNKNOWN,
    ]
    assert command in validator._shell_tool.commands  # type: ignore[attr-defined]
    assert any(
        "Requirement-attributed task validation (TASK-FILTER)" in evidence
        for evidence in report.requirements[0].evidence
    )


def test_attributable_command_failure_fails_only_its_requirement(
    tmp_path: Path,
) -> None:
    specification = Specification.model_validate(
        {
            "requirements": [
                {
                    "id": "REQ-001",
                    "description": "first",
                    "acceptance_criteria": ["first"],
                },
                {
                    "id": "REQ-002",
                    "description": "second",
                    "acceptance_criteria": ["second"],
                },
            ]
        }
    )
    plan = ImplementationPlan.model_validate(
        {
            "tasks": [
                {
                    "id": "TASK-001",
                    "title": "first",
                    "description": "first",
                    "requirement_ids": ["REQ-001"],
                    "validation_commands": ["uv run pytest tests/test_first.py"],
                },
                {
                    "id": "TASK-002",
                    "title": "second",
                    "description": "second",
                    "requirement_ids": ["REQ-002"],
                    "validation_commands": ["uv run pytest tests/test_second.py"],
                },
            ]
        }
    )
    report = WorkspaceAcceptanceValidator(
        tmp_path,
        shell_tool=CommandResultsShellTool(
            {
                "uv run pytest": ToolResult(success=True, data={}),
                "uv run pytest tests/test_first.py": ToolResult(
                    success=False, error="failed"
                ),
                "uv run pytest tests/test_second.py": ToolResult(success=True, data={}),
            }
        ),  # type: ignore[arg-type]
    ).validate(specification, plan, AgentState(status=AgentStatus.COMPLETED))

    assert [item.status for item in report.requirements] == [
        AcceptanceStatus.FAILED,
        AcceptanceStatus.PASSED,
    ]


def test_invalid_test_syntax_is_unknown_with_evidence(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/string_utils.py").touch()
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_string_utils.py").write_text("assert is_digits_only(")
    specification = Specification.model_validate(
        {
            "requirements": [
                {
                    "id": "REQ-001",
                    "description": "feature",
                    "acceptance_criteria": ['is_digits_only("12345") returns True'],
                }
            ]
        }
    )
    report = WorkspaceAcceptanceValidator(
        tmp_path,
        shell_tool=FakeShellTool(ToolResult(success=True, data={})),  # type: ignore[arg-type]
    ).validate(specification, make_plan(), AgentState(status=AgentStatus.COMPLETED))

    criterion = report.requirements[0].criteria[0]
    assert criterion.status is AcceptanceStatus.UNKNOWN
    assert "Could not parse test file: tests/test_string_utils.py" in criterion.evidence


@pytest.mark.parametrize(
    ("criterion", "assertion"),
    [
        (
            'is_digits_only("１２３") returns False',
            'assert is_digits_only("１２３") is True',
        ),
        (
            'reverse_string("abc") returns "cba"',
            'assert reverse_string("abc") == "abc"',
        ),
        ('is_palindrome("hello") returns False', 'assert is_palindrome("hello")'),
        ('is_palindrome("level") returns True', 'assert not is_palindrome("level")'),
        ('normalize("ABC") returns "abc"', 'assert normalize("ABC") == "ABC"'),
        ('find_value("x") returns None', 'assert find_value("x") == "x"'),
    ],
)
def test_functional_contradictions_fail_with_direct_evidence(
    tmp_path: Path,
    criterion: str,
    assertion: str,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/string_utils.py").touch()
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_string_utils.py").write_text(assertion)
    specification = Specification.model_validate(
        {
            "requirements": [
                {
                    "id": "REQ-001",
                    "description": "feature",
                    "acceptance_criteria": [criterion],
                }
            ]
        }
    )
    report = WorkspaceAcceptanceValidator(
        tmp_path,
        shell_tool=FakeShellTool(ToolResult(success=True, data={})),  # type: ignore[arg-type]
    ).validate(specification, make_plan(), AgentState(status=AgentStatus.COMPLETED))

    result = report.requirements[0].criteria[0]
    assert result.status is AcceptanceStatus.FAILED
    assert any("Contradictory test assertion" in item for item in result.evidence)


def test_contradiction_precedes_matching_evidence(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/string_utils.py").touch()
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_string_utils.py").write_text(
        'assert foo("x") is True\nassert foo("x") is False'
    )
    specification = Specification.model_validate(
        {
            "requirements": [
                {
                    "id": "REQ-001",
                    "description": "feature",
                    "acceptance_criteria": ['foo("x") returns True'],
                }
            ]
        }
    )
    report = WorkspaceAcceptanceValidator(
        tmp_path,
        shell_tool=FakeShellTool(ToolResult(success=True, data={})),  # type: ignore[arg-type]
    ).validate(specification, make_plan(), AgentState(status=AgentStatus.COMPLETED))

    assert report.requirements[0].criteria[0].status is AcceptanceStatus.FAILED


def test_bool_and_int_do_not_match_or_contradict(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/string_utils.py").touch()
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_string_utils.py").write_text("assert foo() == 1")
    specification = Specification.model_validate(
        {
            "requirements": [
                {
                    "id": "REQ-001",
                    "description": "feature",
                    "acceptance_criteria": ["foo() returns True"],
                }
            ]
        }
    )
    report = WorkspaceAcceptanceValidator(
        tmp_path,
        shell_tool=FakeShellTool(ToolResult(success=True, data={})),  # type: ignore[arg-type]
    ).validate(specification, make_plan(), AgentState(status=AgentStatus.COMPLETED))

    assert report.requirements[0].criteria[0].status is AcceptanceStatus.UNKNOWN
