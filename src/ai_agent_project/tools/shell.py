"""Workspace-scoped execution of a small allowlist of development commands."""

import shlex
import subprocess
from pathlib import Path

from pydantic import BaseModel, Field

from ai_agent_project.tools.base import ToolDefinition, ToolResult

MAX_OUTPUT_CHARS = 20_000
SHELL_OPERATORS = ("&&", "||", ";", ">>", ">", "<", "|", "$(", "`")
DANGEROUS_COMMANDS = frozenset(
    {
        "sudo",
        "su",
        "rm",
        "mv",
        "cp",
        "chmod",
        "chown",
        "kill",
        "pkill",
        "curl",
        "wget",
        "ssh",
        "scp",
        "docker",
        "apt",
        "apt-get",
        "pip",
        "npm",
    }
)
DANGEROUS_GIT_SUBCOMMANDS = frozenset(
    {"reset", "clean", "checkout", "restore", "commit", "push", "pull"}
)


class ShellInput(BaseModel):
    """Validated input for one allowlisted workspace command."""

    command: str
    timeout_seconds: int = Field(default=30, ge=1, le=300)


class ShellCommandError(ValueError):
    """Raised when a command falls outside the safe command policy."""


def parse_command(command: str) -> list[str]:
    """Parse and validate a command before it is passed to subprocess."""
    if any(operator in command for operator in SHELL_OPERATORS):
        raise ShellCommandError("Shell operators are not allowed")

    try:
        argv = shlex.split(command)
    except ValueError as error:
        raise ShellCommandError(f"Invalid command syntax: {error}") from error

    if not argv:
        raise ShellCommandError("Command must not be empty")
    _reject_dangerous_command(argv)
    _validate_allowlist(argv)
    return argv


def _reject_dangerous_command(argv: list[str]) -> None:
    """Reject explicitly dangerous executable and Git subcommand forms."""
    if argv[0] in DANGEROUS_COMMANDS:
        raise ShellCommandError(f"Command is not allowed: {argv[0]}")
    if len(argv) >= 2 and argv[0] == "git" and argv[1] in DANGEROUS_GIT_SUBCOMMANDS:
        raise ShellCommandError(f"Git command is not allowed: git {argv[1]}")


def _validate_allowlist(argv: list[str]) -> None:
    """Allow only fixed command forms and safe relative-path variants."""
    if argv in (
        ["git", "status"],
        ["git", "status", "--short"],
        ["git", "diff"],
        ["git", "diff", "--check"],
        ["git", "log"],
        ["git", "log", "--oneline"],
        ["python", "--version"],
        ["uv", "--version"],
        ["uv", "run", "pytest"],
        ["uv", "run", "ruff", "check", "."],
        ["uv", "run", "ruff", "format", "--check", "."],
    ):
        return

    if _is_relative_path_variant(argv, ["uv", "run", "pytest"]):
        return
    if _is_relative_path_variant(argv, ["uv", "run", "ruff", "check"]):
        return

    raise ShellCommandError("Command is not in the allowlist")


def _is_relative_path_variant(argv: list[str], prefix: list[str]) -> bool:
    """Return whether argv is one allowed command prefix plus one safe path."""
    if argv[: len(prefix)] != prefix or len(argv) != len(prefix) + 1:
        return False

    path = Path(argv[-1])
    if path.is_absolute() or ".." in path.parts:
        raise ShellCommandError("Command paths must be relative to the workspace")
    return True


def _truncate_output(output: str) -> str:
    """Limit captured command output while making truncation visible."""
    if len(output) <= MAX_OUTPUT_CHARS:
        return output
    return f"{output[:MAX_OUTPUT_CHARS]}\n... [truncated]"


class ShellTool:
    """Run a narrow, non-shell command allowlist inside one workspace."""

    name = "shell"
    description = "Run an allowlisted development command in the workspace."
    input_schema = ShellInput

    def __init__(self, workspace_root: Path) -> None:
        self._workspace_root = workspace_root.resolve()
        if not self._workspace_root.is_dir():
            raise ValueError("workspace_root must be an existing directory")

    def execute(self, arguments: dict[str, object]) -> ToolResult:
        """Validate and execute an allowlisted command without a shell."""
        try:
            values = self.input_schema.model_validate(arguments)
            argv = parse_command(values.command)
        except ValueError as error:
            return ToolResult(success=False, error=str(error))

        try:
            completed = subprocess.run(
                argv,
                cwd=self._workspace_root,
                text=True,
                capture_output=True,
                timeout=values.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                error=f"Command timed out after {values.timeout_seconds} seconds",
            )
        except OSError as error:
            return ToolResult(success=False, error=str(error))

        data = {
            "exit_code": completed.returncode,
            "stdout": _truncate_output(completed.stdout),
            "stderr": _truncate_output(completed.stderr),
        }
        if completed.returncode != 0:
            return ToolResult(
                success=False,
                data=data,
                error=f"Command exited with code {completed.returncode}",
            )
        return ToolResult(success=True, data=data)

    def definition(self) -> ToolDefinition:
        """Return the shell tool metadata exposed to an LLM."""
        return ToolDefinition(
            name=self.name,
            description=self.description,
            input_schema=self.input_schema.model_json_schema(),
        )
