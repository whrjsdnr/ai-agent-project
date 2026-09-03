"""Opt-in HTTP E2E proving approval never auto-executes the next phase."""

import hashlib
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.mark.skipif(
    os.getenv("RUN_OPENAI_E2E") != "1",
    reason="requires explicit OpenAI E2E opt-in",
)
def test_project_checkpoint_lifecycle_executes_phases_only_explicitly(
    tmp_path: Path,
) -> None:
    from ai_agent_project.api.app import create_app

    repository_root = Path(__file__).resolve().parents[2]
    repository_paths = (
        repository_root / "src/ai_agent_project/string_utils.py",
        repository_root / "tests/test_string_utils.py",
    )
    repository_hashes = {
        path: hashlib.sha256(path.read_bytes()).digest() for path in repository_paths
    }
    source_path, test_path = _create_workspace_fixture(tmp_path)
    client = TestClient(create_app(workspace_root=tmp_path))

    created = client.post(
        "/v1/project-runs",
        json={
            "project_title": "String Utilities Multi-Phase HTTP E2E",
            "source_format": "markdown",
            "source_text": """# String Utilities Multi-Phase Project

## Objective
Extend the existing string utility library with two independently verifiable
capabilities.

## REQ-001 Word Reversal
Add reverse_words(value: str) -> str to the existing string utility module.

Acceptance criteria:
- reverse_words("hello world") returns "world hello"
- reverse_words("") returns ""

## REQ-002 ASCII Digit Counter
Add count_ascii_digits(value: str) -> int to the existing string utility module.

Acceptance criteria:
- count_ascii_digits("a1b2c3") returns 3
- count_ascii_digits("abc") returns 0
- count_ascii_digits("１２３") returns 0

## Constraints
- Python 3.12
- Use the existing string_utils.py module and its tests.
- Add or update pytest tests for each implemented capability.
- Existing and new tests must pass.
- Do not add external runtime dependencies.
- Preserve existing behavior.
- Each requirement must be implemented and validated as an independent milestone.
- Do not create an inspection-only milestone.
""",
        },
    )

    assert created.status_code == 201
    created_body = created.json()
    project_run_id = created_body["id"]
    created_run = created_body["project_run"]
    created_state = created_run["execution_state"]
    project_phases = created_run["project_plan"]["phases"]
    assert created_state["status"] == "awaiting_plan_approval"
    assert created_state["current_phase_id"] is not None
    assert len(project_phases) >= 2, (
        "This checkpoint E2E requires at least two LLM-planned phases; "
        f"received phase IDs {[phase['id'] for phase in project_phases]}."
    )
    assert all(
        record["attempt_count"] == 0 for record in created_state["phase_records"]
    )
    assert all(record["execution"] is None for record in created_state["phase_records"])
    assert all(
        record["progress_report"] is None for record in created_state["phase_records"]
    )
    assert all(
        record["checkpoint"] is None for record in created_state["phase_records"]
    )

    phase_1_id = created_state["current_phase_id"]
    fetched_ready = client.get(f"/v1/project-runs/{project_run_id}")
    assert fetched_ready.status_code == 200
    assert (
        fetched_ready.json()["project_run"]["execution_state"]["current_phase_id"]
        == phase_1_id
    )

    plan_v1 = client.get(f"/v1/project-runs/{project_run_id}/plan")
    assert plan_v1.status_code == 200
    assert plan_v1.json()["active_version"] == 1
    revised = client.post(
        f"/v1/project-runs/{project_run_id}/plan/revisions",
        json={
            "feedback": (
                "Move automated tests before documentation and make phase "
                "responsibilities clearer."
            )
        },
    )
    assert revised.status_code == 200
    revised_run = revised.json()["project_run"]
    assert revised_run["plan_revision_state"]["active_version"] == 2
    assert revised_run["plan_revision_state"]["status"] == "awaiting_approval"
    assert revised_run["implementation_plan"] == created_run["implementation_plan"]
    assert revised_run["execution_state"]["status"] == "awaiting_plan_approval"
    assert all(
        record["attempt_count"] == 0
        for record in revised_run["execution_state"]["phase_records"]
    )
    phase_1_id = revised_run["execution_state"]["current_phase_id"]

    approved_plan = client.post(f"/v1/project-runs/{project_run_id}/plan/approve")
    assert approved_plan.status_code == 200
    assert approved_plan.json()["project_run"]["execution_state"]["status"] == "ready"

    phase_1_executed = client.post(f"/v1/project-runs/{project_run_id}/execute")
    assert phase_1_executed.status_code == 200
    phase_1_state = phase_1_executed.json()["project_run"]["execution_state"]
    phase_1_record = _record_for_phase(phase_1_state, phase_1_id)
    assert phase_1_state["status"] == "awaiting_checkpoint"
    assert phase_1_state["current_phase_id"] == phase_1_id
    assert phase_1_record["attempt_count"] == 1
    assert phase_1_record["execution"] is not None
    assert phase_1_record["progress_report"] is not None
    assert phase_1_record["checkpoint"] is not None
    assert phase_1_record["checkpoint"]["status"] == "awaiting_decision"
    assert phase_1_record["checkpoint"]["decision"] is None
    _assert_other_phases_unexecuted(phase_1_state, phase_1_id)

    phase_1_execution = phase_1_record["execution"]
    assert phase_1_execution["status"] == "completed", (
        "Phase 1 must complete before the real APPROVE endpoint can be tested. "
        f"phase_id={phase_1_id}, status={phase_1_execution['status']}, "
        f"requirement_ids={phase_1_execution['requirement_ids']}, "
        f"acceptance={_acceptance_diagnostics(phase_1_execution['acceptance_report'])}"
    )

    fetched_after_phase_1 = client.get(f"/v1/project-runs/{project_run_id}")
    assert fetched_after_phase_1.status_code == 200
    assert (
        _record_for_phase(
            fetched_after_phase_1.json()["project_run"]["execution_state"],
            phase_1_id,
        )["attempt_count"]
        == 1
    )

    approved = client.post(
        f"/v1/project-runs/{project_run_id}/decisions",
        json={
            "decision": "approve",
            "note": "phase 1 accepted by HTTP E2E",
        },
    )
    assert approved.status_code == 200
    approved_state = approved.json()["project_run"]["execution_state"]
    assert approved_state["status"] == "ready"
    assert approved_state["status"] != "completed"
    assert phase_1_id in approved_state["completed_phase_ids"]
    phase_2_id = approved_state["current_phase_id"]
    assert phase_2_id is not None
    assert phase_2_id != phase_1_id
    approved_phase_1_record = _record_for_phase(approved_state, phase_1_id)
    assert approved_phase_1_record["attempt_count"] == 1
    assert approved_phase_1_record["checkpoint"]["status"] == "approved"
    assert approved_phase_1_record["checkpoint"]["decision"] == "approve"
    phase_2_record = _record_for_phase(approved_state, phase_2_id)
    _assert_unexecuted(phase_2_record)

    fetched_after_approve = client.get(f"/v1/project-runs/{project_run_id}")
    assert fetched_after_approve.status_code == 200
    approved_snapshot = fetched_after_approve.json()["project_run"]["execution_state"]
    assert approved_snapshot["status"] == "ready"
    assert phase_1_id in approved_snapshot["completed_phase_ids"]
    assert approved_snapshot["current_phase_id"] == phase_2_id
    _assert_unexecuted(_record_for_phase(approved_snapshot, phase_2_id))

    phase_2_executed = client.post(f"/v1/project-runs/{project_run_id}/execute")
    assert phase_2_executed.status_code == 200
    phase_2_state = phase_2_executed.json()["project_run"]["execution_state"]
    phase_2_record = _record_for_phase(phase_2_state, phase_2_id)
    assert phase_2_state["status"] == "awaiting_checkpoint"
    assert phase_2_state["current_phase_id"] == phase_2_id
    assert phase_2_record["attempt_count"] == 1
    assert phase_2_record["execution"] is not None
    assert phase_2_record["progress_report"] is not None
    assert phase_2_record["checkpoint"] is not None
    assert phase_2_record["checkpoint"]["status"] == "awaiting_decision"
    assert phase_2_record["checkpoint"]["decision"] is None

    final_phase_1_record = _record_for_phase(phase_2_state, phase_1_id)
    assert final_phase_1_record["attempt_count"] == 1
    assert phase_1_id in phase_2_state["completed_phase_ids"]
    _assert_other_phases_unexecuted(phase_2_state, phase_2_id, phase_1_id)

    assert source_path.is_relative_to(tmp_path)
    assert test_path.is_relative_to(tmp_path)
    assert {
        path: hashlib.sha256(path.read_bytes()).digest() for path in repository_paths
    } == repository_hashes


def _record_for_phase(state: dict[str, object], phase_id: str) -> dict[str, object]:
    records = state["phase_records"]
    assert isinstance(records, list)
    return next(record for record in records if record["phase_id"] == phase_id)


def _acceptance_diagnostics(report: object) -> list[dict[str, object]]:
    if not isinstance(report, dict):
        return [{"report": report}]
    requirements = report.get("requirements", [])
    if not isinstance(requirements, list):
        return [{"report": report}]
    return [
        {
            "requirement_id": requirement.get("requirement_id"),
            "status": requirement.get("status"),
            "criteria": [
                {
                    "criterion": criterion.get("criterion"),
                    "status": criterion.get("status"),
                    "evidence": criterion.get("evidence"),
                }
                for criterion in requirement.get("criteria", [])
                if isinstance(criterion, dict)
            ],
        }
        for requirement in requirements
        if isinstance(requirement, dict)
    ]


def _assert_unexecuted(record: dict[str, object]) -> None:
    assert record["attempt_count"] == 0
    assert record["execution"] is None
    assert record["progress_report"] is None
    assert record["checkpoint"] is None


def _assert_other_phases_unexecuted(
    state: dict[str, object],
    *executed_phase_ids: str,
) -> None:
    for record in state["phase_records"]:
        if record["phase_id"] not in executed_phase_ids:
            _assert_unexecuted(record)


def _create_workspace_fixture(tmp_path: Path) -> tuple[Path, Path]:
    (tmp_path / "src/sample_project").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        """[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "sample-project"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = []

[dependency-groups]
dev = ["pytest>=8"]

[tool.setuptools.packages.find]
where = ["src"]
""",
        encoding="utf-8",
    )
    (tmp_path / "src/sample_project/__init__.py").write_text("", encoding="utf-8")
    source_path = tmp_path / "src/sample_project/string_utils.py"
    source_path.write_text(
        """def reverse_string(value: str) -> str:
    return value[::-1]
""",
        encoding="utf-8",
    )
    test_path = tmp_path / "tests/test_string_utils.py"
    test_path.write_text(
        """from sample_project.string_utils import reverse_string


def test_reverse_string() -> None:
    assert reverse_string("abc") == "cba"
""",
        encoding="utf-8",
    )
    return source_path, test_path
