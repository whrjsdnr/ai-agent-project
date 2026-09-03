"""Opt-in HTTP E2E for one real project phase in an isolated workspace."""

import hashlib
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.mark.skipif(
    os.getenv("RUN_OPENAI_E2E") != "1",
    reason="requires explicit OpenAI E2E opt-in",
)
def test_project_http_lifecycle_executes_only_one_phase(tmp_path: Path) -> None:
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
    before_source = hashlib.sha256(source_path.read_bytes()).digest()
    before_test = hashlib.sha256(test_path.read_bytes()).digest()
    client = TestClient(create_app(workspace_root=tmp_path))

    created = client.post(
        "/v1/project-runs",
        json={
            "project_title": "String Utility HTTP E2E",
            "source_format": "markdown",
            "source_text": """# String Utility Extension

## Objective
Extend the existing string utility module with a deterministic ASCII digit counter.

## REQ-001 ASCII Digit Counter
Add count_ascii_digits(value: str) -> int to the existing string utility module.

Acceptance criteria:
- count_ascii_digits("a1b2c3") returns 3
- count_ascii_digits("abc") returns 0
- count_ascii_digits("１２３") returns 0
- Add pytest tests for the new function.
- All tests must pass.

## Constraints
- Python 3.12
- Modify the existing string_utils.py and its tests.
- Do not add external runtime dependencies.
- Preserve existing reverse_string behavior.
""",
        },
    )

    assert created.status_code == 201
    created_body = created.json()
    project_run_id = created_body["id"]
    created_state = created_body["project_run"]["execution_state"]
    assert created_state["status"] == "awaiting_plan_approval"
    assert created_state["current_phase_id"] is not None
    assert created_state["completed_phase_ids"] == []
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

    fetched_ready = client.get(f"/v1/project-runs/{project_run_id}")
    assert fetched_ready.status_code == 200
    assert fetched_ready.json()["id"] == project_run_id
    assert (
        fetched_ready.json()["project_run"]["execution_state"]["current_phase_id"]
        == created_state["current_phase_id"]
    )

    approved_plan = client.post(f"/v1/project-runs/{project_run_id}/plan/approve")
    assert approved_plan.status_code == 200
    assert approved_plan.json()["project_run"]["execution_state"]["status"] == "ready"

    executed = client.post(f"/v1/project-runs/{project_run_id}/execute")

    assert executed.status_code == 200
    executed_body = executed.json()
    executed_state = executed_body["project_run"]["execution_state"]
    current_phase_id = executed_state["current_phase_id"]
    current_record = next(
        record
        for record in executed_state["phase_records"]
        if record["phase_id"] == current_phase_id
    )
    assert executed_state["status"] == "awaiting_checkpoint"
    assert current_record["attempt_count"] == 1
    assert current_record["execution"] is not None
    assert current_record["progress_report"] is not None
    assert current_record["checkpoint"] is not None
    assert current_record["checkpoint"]["status"] == "awaiting_decision"
    assert current_record["checkpoint"]["decision"] is None

    phase = next(
        phase
        for phase in executed_body["project_run"]["project_plan"]["phases"]
        if phase["id"] == current_phase_id
    )
    acceptance_requirements = current_record["execution"]["acceptance_report"][
        "requirements"
    ]
    assert all(
        requirement["requirement_id"] in phase["requirement_ids"]
        for requirement in acceptance_requirements
    )
    assert len(current_record["execution"]["repair_attempts"]) <= 2
    assert all(
        record["attempt_count"] == 0
        and record["execution"] is None
        and record["progress_report"] is None
        and record["checkpoint"] is None
        for record in executed_state["phase_records"]
        if record["phase_id"] != current_phase_id
    )

    fetched_executed = client.get(f"/v1/project-runs/{project_run_id}")
    assert fetched_executed.status_code == 200
    fetched_record = next(
        record
        for record in fetched_executed.json()["project_run"]["execution_state"][
            "phase_records"
        ]
        if record["phase_id"] == current_phase_id
    )
    assert (
        fetched_executed.json()["project_run"]["execution_state"]["status"]
        == "awaiting_checkpoint"
    )
    assert fetched_record["attempt_count"] == 1
    assert fetched_record["execution"] is not None
    assert fetched_record["progress_report"] is not None
    assert fetched_record["checkpoint"] is not None

    assert source_path.is_relative_to(tmp_path)
    assert test_path.is_relative_to(tmp_path)
    assert {
        path: hashlib.sha256(path.read_bytes()).digest() for path in repository_paths
    } == repository_hashes
    if current_record["execution"]["status"] == "completed":
        assert (
            hashlib.sha256(source_path.read_bytes()).digest() != before_source
            or hashlib.sha256(test_path.read_bytes()).digest() != before_test
        )


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
