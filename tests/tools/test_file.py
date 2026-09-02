"""Tests for workspace-scoped file tool operations."""

from pathlib import Path

import pytest

from ai_agent_project.tools.file import FileTool
from ai_agent_project.tools.registry import ToolRegistry


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Provide an isolated workspace without touching project files."""
    return tmp_path / "workspace"


@pytest.fixture
def file_tool(workspace: Path) -> FileTool:
    """Provide a file tool constrained to the isolated workspace."""
    workspace.mkdir()
    return FileTool(workspace)


def test_read_file_returns_utf8_content(file_tool: FileTool, workspace: Path) -> None:
    (workspace / "note.txt").write_text("안녕하세요", encoding="utf-8")

    result = file_tool.execute({"operation": "read_file", "path": "note.txt"})

    assert result.success is True
    assert result.data == {"path": "note.txt", "content": "안녕하세요"}


def test_write_file_creates_utf8_file(file_tool: FileTool, workspace: Path) -> None:
    result = file_tool.execute(
        {"operation": "write_file", "path": "note.txt", "content": "hello"}
    )

    assert result.success is True
    assert result.data == {"path": "note.txt"}
    assert (workspace / "note.txt").read_text(encoding="utf-8") == "hello"


def test_list_files_returns_files_and_directories(
    file_tool: FileTool,
    workspace: Path,
) -> None:
    (workspace / "a.txt").write_text("a", encoding="utf-8")
    (workspace / "directory").mkdir()

    result = file_tool.execute({"operation": "list_files"})

    assert result.success is True
    assert result.data == {
        "path": ".",
        "entries": [
            {"name": "a.txt", "type": "file"},
            {"name": "directory", "type": "directory"},
        ],
    }


def test_write_file_creates_nested_directories(
    file_tool: FileTool,
    workspace: Path,
) -> None:
    result = file_tool.execute(
        {"operation": "write_file", "path": "notes/today.txt", "content": "plan"}
    )

    assert result.success is True
    assert (workspace / "notes" / "today.txt").read_text(encoding="utf-8") == "plan"


@pytest.mark.parametrize("operation", ["list_files", "read_file", "write_file"])
def test_path_traversal_is_blocked(file_tool: FileTool, operation: str) -> None:
    arguments: dict[str, object] = {"operation": operation, "path": "../outside.txt"}
    if operation == "write_file":
        arguments["content"] = "blocked"

    result = file_tool.execute(arguments)

    assert result.success is False
    assert result.error == "Path traversal is not allowed"


@pytest.mark.parametrize("operation", ["list_files", "read_file", "write_file"])
def test_absolute_path_is_blocked(file_tool: FileTool, operation: str) -> None:
    arguments: dict[str, object] = {"operation": operation, "path": "/etc/passwd"}
    if operation == "write_file":
        arguments["content"] = "blocked"

    result = file_tool.execute(arguments)

    assert result.success is False
    assert result.error == "Absolute paths are not allowed"


def test_symlink_escape_is_blocked(file_tool: FileTool, workspace: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("private", encoding="utf-8")
    (workspace / "escape.txt").symlink_to(outside)

    result = file_tool.execute({"operation": "read_file", "path": "escape.txt"})

    assert result.success is False
    assert result.error == "Path must remain inside the workspace"


@pytest.mark.parametrize("operation", ["read_file", "write_file"])
def test_env_file_access_is_blocked(file_tool: FileTool, operation: str) -> None:
    arguments: dict[str, object] = {"operation": operation, "path": ".env"}
    if operation == "write_file":
        arguments["content"] = "SECRET=value"

    result = file_tool.execute(arguments)

    assert result.success is False
    assert result.error == "Access to .env files is not allowed"


def test_reading_a_missing_file_returns_a_failure(file_tool: FileTool) -> None:
    result = file_tool.execute({"operation": "read_file", "path": "missing.txt"})

    assert result.success is False
    assert result.error == "Not a file: missing.txt"


def test_file_tool_can_be_registered(file_tool: FileTool) -> None:
    registry = ToolRegistry()
    registry.register(file_tool)

    assert registry.get("file") is file_tool
