"""Tests for deterministic planner workspace snapshots."""

from pathlib import Path

import pytest

from ai_agent_project.agent.workspace import FilesystemWorkspaceInspector


def test_workspace_inspector_returns_safe_sorted_relative_files(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/app.py").touch()
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_app.py").touch()
    (tmp_path / "pyproject.toml").touch()
    (tmp_path / ".env").touch()
    (tmp_path / ".env.example").touch()
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git/config").touch()

    snapshot = FilesystemWorkspaceInspector(tmp_path).inspect()

    assert snapshot.files == [
        ".env.example",
        "pyproject.toml",
        "src/app.py",
        "tests/test_app.py",
    ]
    assert snapshot.truncated is False


def test_workspace_inspector_limits_files_and_rejects_invalid_root(tmp_path: Path) -> None:
    for name in ("b.py", "a.py", "c.py"):
        (tmp_path / name).touch()

    snapshot = FilesystemWorkspaceInspector(tmp_path, max_files=2).inspect()

    assert snapshot.files == ["a.py", "b.py"]
    assert snapshot.truncated is True
    with pytest.raises(ValueError):
        FilesystemWorkspaceInspector(tmp_path / "missing")
