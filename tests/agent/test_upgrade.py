"""Deterministic upgrade-bootstrap coverage without provider network calls."""

import pytest
from pydantic import ValidationError

from ai_agent_project.agent.codebase_analysis import CodebaseAnalysis
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
from ai_agent_project.agent.project_runner import ProjectRun, UpgradeProjectRunner
from ai_agent_project.agent.specification import Requirement, Specification
from ai_agent_project.agent.upgrade import (
    ProjectMode,
    UpgradeImpact,
    UpgradeSpecification,
)
from ai_agent_project.agent.workspace import WorkspaceSnapshot


def _implementation_plan() -> ImplementationPlan:
    return ImplementationPlan.model_validate(
        {
            "tasks": [
                {
                    "id": "TASK-001",
                    "title": "Upgrade endpoint",
                    "description": "Implement the requested safe upgrade.",
                    "requirement_ids": ["UPG-REQ-001"],
                    "files_to_inspect": ["src/app.py", "tests/test_app.py"],
                    "files_to_modify": ["src/app.py", "tests/test_app.py"],
                }
            ],
            "validation_commands": ["uv run pytest"],
        }
    )


class _Inspector:
    def __init__(self, calls: list[str], workspace: WorkspaceSnapshot) -> None:
        self.calls, self.workspace = calls, workspace

    def inspect(self) -> WorkspaceSnapshot:
        self.calls.append("inspect")
        return self.workspace


class _CodebaseAnalyzer:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def analyze(self, workspace: WorkspaceSnapshot) -> CodebaseAnalysis:
        self.calls.append("codebase")
        assert "src/app.py" in workspace.files
        return CodebaseAnalysis(project_name="Existing API", project_type="FastAPI")


class _UpgradeAnalyzer:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def analyze(self, codebase: CodebaseAnalysis, request, workspace=None):  # type: ignore[no-untyped-def]
        self.calls.append("upgrade")
        assert codebase.project_type == "FastAPI"
        assert workspace is not None
        return UpgradeSpecification(
            title=request.title or "API upgrade",
            objective="Add completed filtering while preserving CRUD.",
            current_system_summary="Existing Todo API.",
            requirements=(
                Requirement(
                    id="UPG-REQ-001",
                    description="Add completed filtering.",
                    acceptance_criteria=("filter_todos(True) returns completed items",),
                ),
            ),
            impact=UpgradeImpact(affected_files=("src/app.py",)),
        )


class _ImplementationPlanner:
    def __init__(self, calls: list[str], plan: ImplementationPlan) -> None:
        self.calls, self.plan_value = calls, plan

    def plan(self, specification: Specification, workspace=None) -> ImplementationPlan:  # type: ignore[no-untyped-def]
        self.calls.append("implementation")
        assert specification.requirements[0].id == "UPG-REQ-001"
        return self.plan_value


class _ProjectPlanner:
    def __init__(self, calls: list[str], plan: ImplementationPlan) -> None:
        self.calls, self.implementation_plan = calls, plan

    def plan(
        self, specification: ProjectSpecification, implementation_plan, workspace=None
    ):  # type: ignore[no-untyped-def]
        self.calls.append("project")
        assert implementation_plan is self.implementation_plan
        return ProjectPlan(
            project_title=specification.title,
            phases=(
                ProjectPhase(
                    id="PHASE-001",
                    title="Upgrade",
                    objective="Implement filtering.",
                    requirement_ids=("UPG-REQ-001",),
                    task_ids=("TASK-001",),
                ),
            ),
            implementation_plan=implementation_plan,
        )


class _ExecutionService:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def start(self, specification, project_specification, project_plan):  # type: ignore[no-untyped-def]
        self.calls.append("execution")
        return ProjectExecutionState(
            project_title=project_plan.project_title,
            status=ProjectExecutionStatus.READY,
            current_phase_id="PHASE-001",
            phase_records=(PhaseExecutionRecord(phase_id="PHASE-001"),),
        )


def test_upgrade_bootstrap_is_read_only_and_enters_plan_review() -> None:
    calls: list[str] = []
    workspace = WorkspaceSnapshot(files=["src/app.py", "tests/test_app.py"])
    plan = _implementation_plan()
    runner = UpgradeProjectRunner(
        _Inspector(calls, workspace),  # type: ignore[arg-type]
        _CodebaseAnalyzer(calls),  # type: ignore[arg-type]
        _UpgradeAnalyzer(calls),  # type: ignore[arg-type]
        _ImplementationPlanner(calls, plan),  # type: ignore[arg-type]
        _ProjectPlanner(calls, plan),  # type: ignore[arg-type]
        _ExecutionService(calls),  # type: ignore[arg-type]
    )

    run = runner.start_upgrade("Add completed filtering.", project_title="Todo upgrade")

    assert calls == [
        "inspect",
        "codebase",
        "upgrade",
        "implementation",
        "project",
        "execution",
    ]
    assert run.mode is ProjectMode.UPGRADE
    assert run.upgrade_context is not None
    assert run.project_specification.requirements[0].id == "UPG-REQ-001"
    assert run.execution_state.status is ProjectExecutionStatus.AWAITING_PLAN_APPROVAL
    assert run.plan_revision_state is not None
    assert run.plan_revision_state.active_version == 1
    assert all(
        record.attempt_count == 0 for record in run.execution_state.phase_records
    )


def test_upgrade_run_requires_context_and_safe_paths_are_enforced() -> None:
    with pytest.raises(ValidationError):
        UpgradeImpact(affected_files=("../outside.py",))
    with pytest.raises(ValidationError):
        CodebaseAnalysis(test_files=("/outside.py",))

    # Existing NEW snapshots retain their migration-compatible default mode.
    assert ProjectRun.model_fields["mode"].default is ProjectMode.NEW
