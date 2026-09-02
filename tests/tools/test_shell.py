"""Tests for the allowlisted workspace shell tool."""

import subprocess
from pathlib import Path
from typing import Any

import pytest

from ai_agent_project.tools.shell import ShellTool, parse_command


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Provide an isolated Git workspace without touching project files."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    return tmp_path


@pytest.fixture
def shell_tool(workspace: Path) -> ShellTool:
    """Provide a shell tool constrained to the isolated workspace."""
    return ShellTool(workspace)


@pytest.mark.parametrize("command", ["git status", "git status --short"])
def test_git_status_commands_succeed(shell_tool: ShellTool, command: str) -> None:
    result = shell_tool.execute({"command": command})

    assert result.success is True
    assert result.data["exit_code"] == 0


@pytest.mark.parametrize("command", ["python --version", "uv --version"])
def test_version_commands_succeed(shell_tool: ShellTool, command: str) -> None:
    result = shell_tool.execute({"command": command})

    assert result.success is True
    assert result.data["exit_code"] == 0
    assert result.data["stdout"] or result.data["stderr"]


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("uv run pytest", ["uv", "run", "pytest"]),
        ("uv run pytest tests/tools/test_shell.py", ["uv", "run", "pytest", "tests/tools/test_shell.py"]),
        ("uv run ruff check src", ["uv", "run", "ruff", "check", "src"]),
    ],
)
def test_allowed_uv_commands_are_parsed(command: str, expected: list[str]) -> None:
    assert parse_command(command) == expected


def test_shell_tool_allows_the_default_planner_validation_command(
    shell_tool: ShellTool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured["argv"] = args[0]
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="", stderr="")

    monkeypatch.setattr("ai_agent_project.tools.shell.subprocess.run", run)

    result = shell_tool.execute({"command": "uv run pytest"})

    assert result.success is True
    assert captured["argv"] == ["uv", "run", "pytest"]


def test_shell_tool_rejects_plain_pytest_options(shell_tool: ShellTool) -> None:
    result = shell_tool.execute({"command": "pytest -q"})

    assert result.success is False
    assert result.error == "Command is not in the allowlist"


@pytest.mark.parametrize(
    ("command", "error"),
    [
        ("sudo whoami", "Command is not allowed: sudo"),
        ("rm file.txt", "Command is not allowed: rm"),
        ("git reset --hard", "Git command is not allowed: git reset"),
        ("git clean -fd", "Git command is not allowed: git clean"),
        ("git commit -m message", "Git command is not allowed: git commit"),
    ],
)
def test_dangerous_commands_are_blocked(shell_tool: ShellTool, command: str, error: str) -> None:
    result = shell_tool.execute({"command": command})

    assert result.success is False
    assert result.error == error


@pytest.mark.parametrize(
    "command",
    [
        "git status | cat",
        "git status && git diff",
        "git status > status.txt",
        "git status $(whoami)",
    ],
)
def test_shell_operators_are_blocked(shell_tool: ShellTool, command: str) -> None:
    result = shell_tool.execute({"command": command})

    assert result.success is False
    assert result.error == "Shell operators are not allowed"


def test_timeout_returns_a_clear_failure(
    monkeypatch: pytest.MonkeyPatch,
    shell_tool: ShellTool,
) -> None:
    def timeout(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise subprocess.TimeoutExpired(cmd="git status", timeout=1)

    monkeypatch.setattr("ai_agent_project.tools.shell.subprocess.run", timeout)

    result = shell_tool.execute({"command": "git status", "timeout_seconds": 1})

    assert result.success is False
    assert result.error == "Command timed out after 1 seconds"


def test_captures_stdout_and_stderr(monkeypatch: pytest.MonkeyPatch, shell_tool: ShellTool) -> None:
    def run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        del args, kwargs
        return subprocess.CompletedProcess(
            args=["git", "status"],
            returncode=7,
            stdout="output",
            stderr="problem",
        )

    monkeypatch.setattr("ai_agent_project.tools.shell.subprocess.run", run)

    result = shell_tool.execute({"command": "git status"})

    assert result.success is False
    assert result.data == {"exit_code": 7, "stdout": "output", "stderr": "problem"}
    assert result.error == "Command exited with code 7"


def test_uses_workspace_as_cwd(
    monkeypatch: pytest.MonkeyPatch,
    shell_tool: ShellTool,
    workspace: Path,
) -> None:
    captured: dict[str, object] = {}

    def run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured.update(kwargs)
        return subprocess.CompletedProcess(
            args=["git", "status"],
            returncode=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr("ai_agent_project.tools.shell.subprocess.run", run)

    result = shell_tool.execute({"command": "git status"})

    assert result.success is True
    assert captured["cwd"] == workspace
    assert captured["text"] is True
    assert captured["capture_output"] is True
    assert captured["check"] is False
