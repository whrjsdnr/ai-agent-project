"""Persistence tests for immutable handoff snapshots."""

from datetime import UTC, datetime, timedelta

import pytest

from ai_agent_project.agent.project_artifact import ProjectArtifactSource
from ai_agent_project.agent.project_handoff import ProjectHandoff, ProjectHandoffPurpose
from ai_agent_project.agent.project_handoff_application import (
    ProjectHandoffAlreadyExistsError,
)
from ai_agent_project.agent.project_handoff_file_store import (
    FileProjectHandoffStore,
    ProjectHandoffStorageError,
)


def _handoff(identifier: str, project: str = "p", offset: int = 0) -> ProjectHandoff:
    return ProjectHandoff(
        handoff_id=identifier,
        project_id=project,
        source_domain=ProjectArtifactSource.RESEARCHER,
        source_run_id="r",
        artifact_id="a",
        content_sha256="0" * 64,
        purpose=ProjectHandoffPurpose.DEVELOPER_BOOTSTRAP_CONTEXT,
        created_at=datetime(2025, 1, 1, tzinfo=UTC) + timedelta(seconds=offset),
    )


def test_create_get_reload_and_deterministic_list(tmp_path) -> None:
    store = FileProjectHandoffStore(tmp_path)
    second = _handoff("00000000-0000-0000-0000-000000000002", offset=2)
    first = _handoff("00000000-0000-0000-0000-000000000001", offset=1)
    store.create(second)
    store.create(first)
    assert store.get(first.handoff_id) == first
    assert FileProjectHandoffStore(tmp_path).get(second.handoff_id) == second
    assert FileProjectHandoffStore(tmp_path).list_for_project("p") == (first, second)
    assert store.list_for_project("other") == ()


def test_malformed_and_schema_invalid_records_fail_explicitly(tmp_path) -> None:
    store = FileProjectHandoffStore(tmp_path)
    path = tmp_path / "00000000-0000-0000-0000-000000000001.json"
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(ProjectHandoffStorageError):
        store.get(path.stem)
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ProjectHandoffStorageError):
        store.list_for_project("p")


def test_duplicate_snapshot_is_rejected_without_update(tmp_path) -> None:
    store = FileProjectHandoffStore(tmp_path)
    handoff = _handoff("00000000-0000-0000-0000-000000000001")
    store.create(handoff)
    with pytest.raises(ProjectHandoffAlreadyExistsError):
        store.create(handoff)
    assert store.get(handoff.handoff_id) == handoff
    assert "body" not in (tmp_path / f"{handoff.handoff_id}.json").read_text()
