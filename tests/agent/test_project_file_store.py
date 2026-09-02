"""Tests for persistent, whole-snapshot CLI project-run storage."""

from uuid import uuid4

import pytest

from ai_agent_project.agent.plan import ImplementationPlan
from ai_agent_project.agent.project import (
    ProjectPhase,
    ProjectPlan,
    ProjectSpecification,
)
from ai_agent_project.agent.project_application import (
    ProjectRunAlreadyExistsError,
    ProjectRunNotFoundError,
)
from ai_agent_project.agent.project_execution import (
    PhaseExecutionRecord,
    ProjectExecutionState,
    ProjectExecutionStatus,
)
from ai_agent_project.agent.project_file_store import (
    FileProjectRunStore,
    ProjectRunStorageError,
)
from ai_agent_project.agent.project_runner import ProjectRun
from ai_agent_project.agent.specification import Specification
from ai_agent_project.agent.workspace import WorkspaceSnapshot


def make_project_run(
    status: ProjectExecutionStatus = ProjectExecutionStatus.READY,
) -> ProjectRun:
    specification = Specification.model_validate(
        {
            "constraints": ["Python 3.12"],
            "requirements": [
                {
                    "id": "REQ-001",
                    "description": "Build the feature.",
                    "acceptance_criteria": ['feature("x") returns True'],
                }
            ],
        }
    )
    project_specification = ProjectSpecification.from_specification(specification)
    implementation_plan = ImplementationPlan.model_validate(
        {
            "tasks": [
                {
                    "id": "TASK-001",
                    "title": "Build",
                    "description": "Build the feature.",
                    "requirement_ids": ["REQ-001"],
                }
            ]
        }
    )
    project_plan = ProjectPlan(
        project_title="Demo",
        phases=(
            ProjectPhase(
                id="PHASE-001",
                title="Feature",
                objective="Build the feature.",
                requirement_ids=("REQ-001",),
                task_ids=("TASK-001",),
            ),
        ),
        implementation_plan=implementation_plan,
    )
    state = ProjectExecutionState(
        project_title="Demo",
        status=status,
        current_phase_id="PHASE-001"
        if status is not ProjectExecutionStatus.COMPLETED
        else None,
        phase_records=(PhaseExecutionRecord(phase_id="PHASE-001"),),
    )
    return ProjectRun(
        specification=specification,
        project_specification=project_specification,
        workspace=WorkspaceSnapshot(files=["src/example.py"]),
        implementation_plan=implementation_plan,
        project_plan=project_plan,
        execution_state=state,
    )


def test_create_get_round_trip_reopens_and_preserves_workspace(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store_root = tmp_path / "runs"
    run_id = str(uuid4())
    original = make_project_run()

    FileProjectRunStore(store_root, workspace_root=workspace).create(run_id, original)
    reopened = FileProjectRunStore(store_root)

    assert reopened.get(run_id) == original
    assert reopened.workspace_root_for(run_id) == workspace.resolve()
    assert list(store_root.glob("*.json")) == [store_root / f"{run_id}.json"]
    assert not list(store_root.glob("*.tmp"))


def test_replace_persists_whole_new_snapshot(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store = FileProjectRunStore(tmp_path / "runs", workspace_root=workspace)
    run_id = str(uuid4())
    store.create(run_id, make_project_run())
    replacement = make_project_run(ProjectExecutionStatus.RETRY_REQUESTED)

    store.replace(run_id, replacement)

    assert FileProjectRunStore(tmp_path / "runs").get(run_id) == replacement


def test_duplicate_and_missing_store_operations_are_rejected(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store = FileProjectRunStore(tmp_path / "runs", workspace_root=workspace)
    run_id = str(uuid4())
    project_run = make_project_run()
    store.create(run_id, project_run)

    with pytest.raises(ProjectRunAlreadyExistsError):
        store.create(run_id, project_run)
    assert store.get(str(uuid4())) is None
    with pytest.raises(ProjectRunNotFoundError):
        store.replace(str(uuid4()), project_run)


@pytest.mark.parametrize("project_run_id", ["../escape", "run.json", "not-a-uuid"])
def test_path_traversal_and_malformed_ids_are_rejected(
    tmp_path, project_run_id: str
) -> None:
    store = FileProjectRunStore(tmp_path / "runs")

    with pytest.raises(ProjectRunStorageError):
        store.get(project_run_id)


def test_corrupted_json_raises_clear_storage_error(tmp_path) -> None:
    store = FileProjectRunStore(tmp_path / "runs")
    run_id = str(uuid4())
    (tmp_path / "runs" / f"{run_id}.json").write_text("{broken", encoding="utf-8")

    with pytest.raises(ProjectRunStorageError, match="Could not read"):
        store.get(run_id)
