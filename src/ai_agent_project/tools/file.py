"""Workspace-scoped file operations for an agent."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, model_validator

from ai_agent_project.tools.base import ToolDefinition, ToolResult


class FileInput(BaseModel):
    """Validated input for a workspace file operation."""

    operation: Literal["list_files", "read_file", "write_file"]
    path: str = "."
    content: str | None = None

    @model_validator(mode="after")
    def require_content_for_writes(self) -> "FileInput":
        """Require text content only when writing a file."""
        if self.operation == "write_file" and self.content is None:
            raise ValueError("write_file requires content")
        return self


class WorkspacePathError(ValueError):
    """Raised when a path is not safe to access from the workspace."""


class FileTool:
    """Read and write UTF-8 text files within one explicitly supplied workspace."""

    name = "file"
    description = "List, read, or write UTF-8 text files within the workspace."
    input_schema = FileInput

    def __init__(self, workspace_root: Path) -> None:
        self._workspace_root = workspace_root.resolve()
        if not self._workspace_root.is_dir():
            raise ValueError("workspace_root must be an existing directory")

    def execute(self, arguments: dict[str, object]) -> ToolResult:
        """Validate and perform one workspace-scoped file operation."""
        try:
            values = self.input_schema.model_validate(arguments)
            if values.operation == "list_files":
                return self._list_files(values.path)
            if values.operation == "read_file":
                return self._read_file(values.path)
            return self._write_file(values.path, values.content)
        except (OSError, UnicodeError, ValueError) as error:
            return ToolResult(success=False, error=str(error))

    def _list_files(self, path: str) -> ToolResult:
        """List safe children of a directory in deterministic order."""
        directory = self._resolve_workspace_path(path)
        if not directory.is_dir():
            raise NotADirectoryError(f"Not a directory: {path}")

        entries: list[dict[str, str]] = []
        for child in sorted(directory.iterdir(), key=lambda entry: entry.name):
            try:
                self._ensure_safe_resolved_path(child.resolve())
                self._reject_env_path(child)
            except WorkspacePathError:
                continue

            entry_type = "directory" if child.is_dir() else "file"
            entries.append({"name": child.name, "type": entry_type})

        return ToolResult(success=True, data={"path": path, "entries": entries})

    def _read_file(self, path: str) -> ToolResult:
        """Read one UTF-8 text file from the workspace."""
        file_path = self._resolve_workspace_path(path)
        if not file_path.is_file():
            raise FileNotFoundError(f"Not a file: {path}")

        return ToolResult(
            success=True,
            data={"path": path, "content": file_path.read_text(encoding="utf-8")},
        )

    def _write_file(self, path: str, content: str | None) -> ToolResult:
        """Create or overwrite one UTF-8 text file inside the workspace."""
        file_path = self._resolve_workspace_path(path)
        if file_path.exists() and file_path.is_dir():
            raise IsADirectoryError(f"Not a file: {path}")

        file_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_safe_resolved_path(file_path.parent.resolve())
        file_path.write_text(content or "", encoding="utf-8")
        return ToolResult(success=True, data={"path": path})

    def _resolve_workspace_path(self, path: str) -> Path:
        """Resolve a relative path and reject workspace escapes before access."""
        candidate = Path(path)
        if candidate.is_absolute():
            raise WorkspacePathError("Absolute paths are not allowed")
        if ".." in candidate.parts:
            raise WorkspacePathError("Path traversal is not allowed")
        self._reject_env_path(candidate)

        resolved = (self._workspace_root / candidate).resolve()
        self._ensure_safe_resolved_path(resolved)
        return resolved

    def _ensure_safe_resolved_path(self, path: Path) -> None:
        """Ensure a resolved path is still inside the configured workspace root."""
        try:
            path.relative_to(self._workspace_root)
        except ValueError as error:
            raise WorkspacePathError("Path must remain inside the workspace") from error

    @staticmethod
    def _reject_env_path(path: Path) -> None:
        """Prevent access to .env files anywhere below the workspace root."""
        if ".env" in path.parts:
            raise WorkspacePathError("Access to .env files is not allowed")

    def definition(self) -> ToolDefinition:
        """Return the file tool metadata exposed to an LLM."""
        return ToolDefinition(
            name=self.name,
            description=self.description,
            input_schema=self.input_schema.model_json_schema(),
        )
