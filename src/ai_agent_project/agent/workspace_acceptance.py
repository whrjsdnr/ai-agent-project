"""Deterministic, workspace-scoped acceptance validation."""

import ast
import re
from dataclasses import dataclass
from pathlib import Path

from ai_agent_project.agent.acceptance import (
    AcceptanceCriterionResult,
    AcceptanceReport,
    AcceptanceStatus,
    RequirementValidationResult,
)
from ai_agent_project.agent.plan import ImplementationPlan
from ai_agent_project.agent.specification import Requirement, Specification
from ai_agent_project.agent.state import AgentState, AgentStatus
from ai_agent_project.command_policy import CommandPolicyError, parse_safe_command
from ai_agent_project.tools.shell import ShellTool


class WorkspaceAcceptanceValidator:
    """Validate planned files and safe validation commands inside one workspace."""

    def __init__(self, workspace_root: Path, shell_tool: ShellTool | None = None) -> None:
        self._workspace_root = workspace_root.resolve()
        if not self._workspace_root.is_dir():
            raise ValueError("workspace_root must be an existing directory")
        self._shell_tool = shell_tool or ShellTool(self._workspace_root)

    def validate(
        self,
        specification: Specification,
        plan: ImplementationPlan,
        agent_state: AgentState,
    ) -> AcceptanceReport:
        """Validate traceable file evidence and safe command execution results."""
        commands = plan.validation_commands or ["uv run pytest"]
        command_evidence, commands_passed = self._run_validation_commands(commands)
        requirements = [
            self._validate_requirement(
                requirement,
                plan,
                agent_state,
                command_evidence,
                commands_passed,
            )
            for requirement in specification.requirements
        ]
        notes = []
        if agent_state.status is AgentStatus.FAILED:
            notes.append(f"Agent run failed: {agent_state.error or 'unknown error'}")
        return AcceptanceReport(
            requirements=requirements,
            validation_commands=commands,
            notes=notes,
        )

    def _run_validation_commands(self, commands: list[str]) -> tuple[list[str], bool]:
        evidence: list[str] = []
        passed = True
        for command in commands:
            try:
                parse_safe_command(command)
            except CommandPolicyError as error:
                evidence.append(f"Unsafe validation command rejected: {command} ({error})")
                passed = False
                continue
            result = self._shell_tool.execute({"command": command})
            if result.success:
                evidence.append(f"Validation command passed: {command}")
            else:
                evidence.append(f"Validation command failed: {command} ({result.error})")
                passed = False
        return evidence, passed

    def _validate_requirement(
        self,
        requirement: Requirement,
        plan: ImplementationPlan,
        agent_state: AgentState,
        command_evidence: list[str],
        commands_passed: bool,
    ) -> RequirementValidationResult:
        tasks = [task for task in plan.tasks if requirement.id in task.requirement_ids]
        paths = _stable_paths(
            path
            for task in tasks
            for path in [
                *task.files_to_modify,
                *task.files_to_inspect,
                *task.files,
            ]
        )
        implemented_files, test_files, file_evidence, files_exist = self._inspect_paths(paths)
        evidence = [*file_evidence, *command_evidence]
        if agent_state.status is AgentStatus.FAILED:
            evidence.append(f"Agent run failed: {agent_state.error or 'unknown error'}")

        criteria = [
            self._validate_criterion(
                criterion,
                test_files,
                commands_passed,
                evidence,
                self._find_functional_assertions(criterion, test_files, evidence),
            )
            for criterion in requirement.acceptance_criteria
        ]
        statuses = [criterion.status for criterion in criteria]
        if (
            agent_state.status is AgentStatus.FAILED
            or not commands_passed
            or not files_exist
            or any(status is AcceptanceStatus.FAILED for status in statuses)
        ):
            status = AcceptanceStatus.FAILED
        elif any(status is AcceptanceStatus.UNKNOWN for status in statuses):
            status = AcceptanceStatus.UNKNOWN
        elif paths or criteria:
            status = AcceptanceStatus.PASSED
        else:
            status = AcceptanceStatus.UNKNOWN
        return RequirementValidationResult(
            requirement_id=requirement.id,
            status=status,
            criteria=criteria,
            implemented_files=implemented_files,
            test_files=test_files,
            evidence=evidence,
        )

    def _inspect_paths(self, paths: list[str]) -> tuple[list[str], list[str], list[str], bool]:
        implemented: list[str] = []
        tests: list[str] = []
        evidence: list[str] = []
        exists = True
        for path in paths:
            resolved = self._safe_path(path)
            if resolved is None or not resolved.exists():
                evidence.append(f"Expected file missing or unsafe: {path}")
                exists = False
                continue
            evidence.append(f"Planned file exists: {path}")
            (tests if path.startswith("tests/") else implemented).append(path)
        return implemented, tests, evidence, exists

    def _safe_path(self, path: str) -> Path | None:
        candidate = Path(path)
        if candidate.is_absolute() or ".." in candidate.parts or ".env" in candidate.parts:
            return None
        resolved = (self._workspace_root / candidate).resolve()
        try:
            resolved.relative_to(self._workspace_root)
        except ValueError:
            return None
        return resolved

    @staticmethod
    def _validate_criterion(
        criterion: str,
        test_files: list[str],
        commands_passed: bool,
        evidence: list[str],
        functional_evidence: list["_FunctionalAssertion"] | None = None,
    ) -> AcceptanceCriterionResult:
        classification = _classify_test_requirement(criterion)
        if classification == "creation":
            passed = bool(test_files) and commands_passed
            return AcceptanceCriterionResult(
                criterion=criterion,
                status=AcceptanceStatus.PASSED if passed else AcceptanceStatus.FAILED,
                evidence=list(evidence),
            )
        if classification == "suite_pass":
            return AcceptanceCriterionResult(
                criterion=criterion,
                status=(
                    AcceptanceStatus.PASSED if commands_passed else AcceptanceStatus.FAILED
                ),
                evidence=list(evidence),
            )
        if _parse_functional_criterion(criterion) is not None:
            parsed = _parse_functional_criterion(criterion)
            assertions = functional_evidence or []
            contradictions = [
                item
                for item in assertions
                if parsed is not None
                and (
                    (item.expected is None or parsed.expected is None)
                    and item.expected is not parsed.expected
                    or type(item.expected) is type(parsed.expected)
                    and item.expected != parsed.expected
                )
            ]
            matches = [
                item
                for item in assertions
                if parsed is not None and _literal_same_type(item.expected, parsed.expected)
            ]
            if contradictions or not commands_passed:
                status = AcceptanceStatus.FAILED
            elif matches:
                status = AcceptanceStatus.PASSED
            else:
                status = AcceptanceStatus.UNKNOWN
            return AcceptanceCriterionResult(
                criterion=criterion,
                status=status,
                evidence=[
                    *evidence,
                    *[_format_assertion("Matched test assertion", item) for item in matches],
                    *[
                        _format_assertion("Contradictory test assertion", item)
                        + f"; Criterion expected: {parsed.expected!r}; Test asserts: {item.expected!r}"
                        for item in contradictions
                    ],
                ],
                notes=(
                    None
                    if matches or contradictions
                    else "No matching direct test assertion was found."
                ),
            )
        return AcceptanceCriterionResult(
            criterion=criterion,
            status=AcceptanceStatus.UNKNOWN,
            evidence=list(evidence),
            notes="Criterion is not mechanically verifiable in validator v1.",
        )

    def _find_functional_assertions(
        self,
        criterion: str,
        test_files: list[str],
        evidence: list[str],
    ) -> list["_FunctionalAssertion"]:
        """Find direct AST assert evidence for one narrowly parsed criterion."""
        parsed = _parse_functional_criterion(criterion)
        if parsed is None:
            return []
        matches: list[_FunctionalAssertion] = []
        for path in test_files:
            resolved = self._safe_path(path)
            if resolved is None:
                continue
            try:
                tree = ast.parse(resolved.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, SyntaxError):
                evidence.append(f"Could not parse test file: {path}")
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Assert):
                    assertion = _extract_assertion(node.test)
                    if assertion is not None and _call_matches(assertion.call, parsed):
                        matches.append(
                            _FunctionalAssertion(
                                parsed.function_name,
                                parsed.args,
                                assertion.expected,
                                path,
                                node.lineno,
                                ast.unparse(node),
                            )
                        )
        return matches


def _classify_test_requirement(criterion: str) -> str | None:
    """Classify only explicit, positive test requirements for validator v1."""
    normalized = criterion.lower().strip()
    negative_phrases = (
        "do not add tests",
        "tests are not required",
        "no tests required",
        "without tests",
    )
    if any(phrase in normalized for phrase in negative_phrases):
        return None

    if any(
        phrase in normalized
        for phrase in ("add pytest tests", "add tests", "pytest tests", "test coverage")
    ):
        return "creation"
    if any(
        phrase in normalized
        for phrase in ("tests must pass", "all tests must pass", "pytest must pass")
    ):
        return "suite_pass"
    return None


@dataclass(frozen=True)
class _FunctionalCriterion:
    function_name: str
    args: tuple[object, ...]
    expected: object


@dataclass(frozen=True)
class _FunctionalAssertion:
    function_name: str
    args: tuple[object, ...]
    expected: object
    path: str
    line: int
    source: str


@dataclass(frozen=True)
class _AssertExpression:
    call: ast.Call
    expected: object


_FUNCTIONAL_CRITERION = re.compile(
    r"^([A-Za-z_]\w*)\((.*)\)\s+returns\s+(.+)$"
)


def _parse_functional_criterion(criterion: str) -> _FunctionalCriterion | None:
    """Parse only ``function(literals) returns literal`` without evaluating code."""
    match = _FUNCTIONAL_CRITERION.fullmatch(criterion.strip())
    if match is None:
        return None
    try:
        raw_args = match.group(2).strip()
        args = () if not raw_args else ast.literal_eval(f"({raw_args},)")
        expected_text = match.group(3).strip()
        expected = None if expected_text == "None" else ast.literal_eval(expected_text)
    except (SyntaxError, ValueError):
        return None
    if not isinstance(args, tuple) or not _is_supported_literal(expected):
        return None
    if not all(_is_supported_literal(arg) for arg in args):
        return None
    return _FunctionalCriterion(match.group(1), args, expected)


def _is_supported_literal(value: object) -> bool:
    return value is None or isinstance(value, str | int | float | bool)


def _extract_assertion(expression: ast.expr) -> _AssertExpression | None:
    """Extract only the supported direct assertion shapes without dataflow."""
    if isinstance(expression, ast.Call):
        return _AssertExpression(expression, True)
    if isinstance(expression, ast.UnaryOp) and isinstance(expression.op, ast.Not):
        if isinstance(expression.operand, ast.Call):
            return _AssertExpression(expression.operand, False)
        return None
    if not isinstance(expression, ast.Compare) or len(expression.ops) != 1 or len(expression.comparators) != 1:
        return None
    if not isinstance(expression.left, ast.Call):
        return None
    if not isinstance(expression.ops[0], ast.Is | ast.Eq):
        return None
    try:
        comparator = expression.comparators[0]
        expected = comparator.value if isinstance(comparator, ast.Constant) else ast.literal_eval(comparator)
    except ValueError:
        return None
    if not _is_supported_literal(expected):
        return None
    return _AssertExpression(expression.left, expected)


def _literal_same_type(left: object, right: object) -> bool:
    return type(left) is type(right) and left == right


def _format_assertion(prefix: str, assertion: _FunctionalAssertion) -> str:
    return f"{prefix} in {assertion.path}:{assertion.line}: {assertion.source}"


def _call_matches(call: ast.Call, criterion: _FunctionalCriterion) -> bool:
    if not isinstance(call.func, ast.Name) or call.func.id != criterion.function_name or call.keywords:
        return False
    try:
        return tuple(ast.literal_eval(arg) for arg in call.args) == criterion.args
    except ValueError:
        return False


def _stable_paths(paths: object) -> list[str]:
    """Deduplicate ordered planner paths without trusting arbitrary values."""
    result: list[str] = []
    for path in paths:
        if isinstance(path, str) and path not in result:
            result.append(path)
    return result
