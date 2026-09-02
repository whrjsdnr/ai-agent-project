"""Workspace-scoped execution of a small allowlist of development commands."""

import subprocess
from pathlib import Path

from pydantic import BaseModel, Field

from ai_agent_project.command_policy import CommandPolicyError, parse_safe_command
from ai_agent_project.tools.base import ToolDefinition, ToolResult

MAX_OUTPUT_CHARS = 20_000


class ShellInput(BaseModel):
    """Validated input for one allowlisted workspace command."""

    command: str
    timeout_seconds: int = Field(default=30, ge=1, le=300)


# Backward-compatible exports for callers that used ShellTool's original helpers.
ShellCommandError = CommandPolicyError
parse_command = parse_safe_command


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
            argv = parse_safe_command(values.command)
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
