"""Opt-in OpenAI E2E coverage for planning-only project bootstrap."""

import hashlib
import os
from pathlib import Path

import pytest

from ai_agent_project.agent.checkpoint import (
    PhaseCheckpointService,
    ProgressReporter,
)
from ai_agent_project.agent.phase_execution import PhaseExecutionService
from ai_agent_project.agent.project_execution import (
    ProjectExecutionService,
    ProjectExecutionStatus,
)
from ai_agent_project.agent.project_runner import ProjectRunner
from ai_agent_project.agent.workspace import FilesystemWorkspaceInspector
from ai_agent_project.agent.workspace_acceptance import WorkspaceAcceptanceValidator
from ai_agent_project.api.app import create_default_agent_service
from ai_agent_project.llm.providers.openai_planner import OpenAIImplementationPlanner
from ai_agent_project.llm.providers.openai_project_planner import OpenAIProjectPlanner
from ai_agent_project.llm.providers.openai_specification import (
    OpenAISpecificationParser,
)


@pytest.mark.skipif(
    os.getenv("RUN_OPENAI_E2E") != "1",
    reason="requires explicit OpenAI E2E opt-in",
)
def test_project_runner_bootstraps_markdown_without_phase_execution() -> None:
    root = Path(__file__).resolve().parents[2]
    source_paths = (
        root / "src/ai_agent_project/string_utils.py",
        root / "tests/test_string_utils.py",
    )
    before = {path: hashlib.sha256(path.read_bytes()).digest() for path in source_paths}

    phase_execution_service = PhaseExecutionService(
        create_default_agent_service(root),
        WorkspaceAcceptanceValidator(root),
    )
    execution_service = ProjectExecutionService(
        phase_execution_service,
        ProgressReporter(),
        PhaseCheckpointService(),
    )
    runner = ProjectRunner(
        OpenAISpecificationParser(),
        FilesystemWorkspaceInspector(root),
        OpenAIImplementationPlanner(),
        OpenAIProjectPlanner(),
        execution_service,
    )

    project_run = runner.start(
        """# String Utility Extension

## Objective
Extend the existing string utility module with several deterministic helper functions.

## REQ-001 Reverse Words
Add a function that reverses word order in a string.

Acceptance criteria:
- reverse_words("hello world") returns "world hello"
- reverse_words("") returns ""

## REQ-002 Count ASCII Digits
Add a function that returns the number of ASCII digit characters in a string.

Acceptance criteria:
- count_ascii_digits("a1b2c3") returns 3
- count_ascii_digits("abc") returns 0
- count_ascii_digits("１２３") returns 0

## REQ-003 Normalize Spaces
Add a function that collapses consecutive ASCII spaces into one space and strips
leading/trailing ASCII spaces.

Acceptance criteria:
- normalize_spaces("  hello   world  ") returns "hello world"
- normalize_spaces("") returns ""

## Constraints
- Python 3.12
- Keep changes inside the existing string utility module and its tests.
- Do not add external runtime dependencies.
- Preserve existing behavior.
""",
        project_title="String Utility Extension",
        source_format="markdown",
    )

    specification = project_run.specification
    requirement_ids = [requirement.id for requirement in specification.requirements]
    requirement_text = " ".join(
        " ".join(
            item
            for item in (
                requirement.title,
                requirement.description,
                *requirement.acceptance_criteria,
            )
            if item
        )
        for requirement in specification.requirements
    ).lower()
    assert specification.requirements
    assert len(requirement_ids) == len(set(requirement_ids))
    assert all(
        requirement.acceptance_criteria for requirement in specification.requirements
    )
    assert all(
        name in requirement_text
        for name in ("reverse_words", "count_ascii_digits", "normalize_spaces")
    )

    project_specification = project_run.project_specification
    assert project_specification.title == "String Utility Extension"
    assert project_specification.source_format == "markdown"
    assert tuple(requirement_ids) == tuple(
        requirement.id for requirement in project_specification.requirements
    )
    assert tuple(
        requirement.acceptance_criteria for requirement in specification.requirements
    ) == tuple(
        requirement.acceptance_criteria
        for requirement in project_specification.requirements
    )

    workspace = project_run.workspace
    assert workspace.files
    assert "src/ai_agent_project/string_utils.py" in workspace.files
    assert "tests/test_string_utils.py" in workspace.files

    implementation_plan = project_run.implementation_plan
    valid_requirement_ids = set(requirement_ids)
    assert implementation_plan.tasks
    assert len({task.id for task in implementation_plan.tasks}) == len(
        implementation_plan.tasks
    )
    assert {
        requirement_id
        for task in implementation_plan.tasks
        for requirement_id in task.requirement_ids
    } >= valid_requirement_ids
    assert all(
        set(task.requirement_ids) <= valid_requirement_ids
        for task in implementation_plan.tasks
    )
    for task in implementation_plan.tasks:
        for path in [*task.files_to_inspect, *task.files_to_modify, *task.files]:
            candidate = Path(path)
            assert not candidate.is_absolute()
            assert ".." not in candidate.parts
            assert ".env" not in candidate.parts
    assert (
        implementation_plan.validate_traceability(specification) is implementation_plan
    )

    project_plan = project_run.project_plan
    phase_ids = [phase.id for phase in project_plan.phases]
    assigned_task_ids = [
        task_id for phase in project_plan.phases for task_id in phase.task_ids
    ]
    covered_requirement_ids = {
        requirement_id
        for phase in project_plan.phases
        for requirement_id in phase.requirement_ids
    }
    task_ids = {task.id for task in implementation_plan.tasks}
    assert project_plan.phases
    assert len(phase_ids) == len(set(phase_ids))
    assert set(assigned_task_ids) == task_ids
    assert len(assigned_task_ids) == len(set(assigned_task_ids))
    assert covered_requirement_ids == valid_requirement_ids
    assert all(
        set(phase.requirement_ids) <= valid_requirement_ids
        and set(phase.task_ids) <= task_ids
        and set(phase.depends_on) <= set(phase_ids)
        for phase in project_plan.phases
    )
    assert project_plan.validate_against(project_specification) is project_plan

    state = project_run.execution_state
    current_phase = next(
        phase for phase in project_plan.phases if phase.id == state.current_phase_id
    )
    assert state.status is ProjectExecutionStatus.AWAITING_PLAN_APPROVAL
    assert state.current_phase_id is not None
    assert set(current_phase.depends_on) <= set(state.completed_phase_ids)
    assert state.completed_phase_ids == ()
    assert all(record.attempt_count == 0 for record in state.phase_records)
    assert all(record.execution is None for record in state.phase_records)
    assert all(record.progress_report is None for record in state.phase_records)
    assert all(record.checkpoint is None for record in state.phase_records)
    assert {
        path: hashlib.sha256(path.read_bytes()).digest() for path in source_paths
    } == before
