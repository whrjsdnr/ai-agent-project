"""Provider-neutral deterministic workspace inventory."""

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

_IGNORED_DIRECTORIES = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        "node_modules",
        "dist",
        "build",
    }
)


class WorkspaceSnapshot(BaseModel):
    """Bounded, relative-only workspace file metadata for planning."""

    model_config = ConfigDict(frozen=True)

    files: list[str] = Field(default_factory=list)
    truncated: bool = False


class WorkspaceInspector(Protocol):
    def inspect(self) -> WorkspaceSnapshot:
        """Return a deterministic, safe inventory of workspace-relative files."""
        ...


class FilesystemWorkspaceInspector:
    """List safe workspace files without reading their contents."""

    def __init__(self, workspace_root: Path, *, max_files: int = 500) -> None:
        self._workspace_root = workspace_root.resolve()
        if not self._workspace_root.is_dir():
            raise ValueError("workspace_root must be an existing directory")
        if max_files < 1:
            raise ValueError("max_files must be at least one")
        self._max_files = max_files

    def inspect(self) -> WorkspaceSnapshot:
        paths: list[str] = []
        for candidate in sorted(self._workspace_root.rglob("*")):
            relative = candidate.relative_to(self._workspace_root)
            if any(part in _IGNORED_DIRECTORIES for part in relative.parts):
                continue
            if _is_secret_env_file(relative):
                continue
            try:
                resolved = candidate.resolve()
                resolved.relative_to(self._workspace_root)
            except (OSError, ValueError):
                continue
            if candidate.is_file():
                paths.append(relative.as_posix())
        return WorkspaceSnapshot(
            files=paths[: self._max_files], truncated=len(paths) > self._max_files
        )


def _is_secret_env_file(path: Path) -> bool:
    return path.name == ".env" or (
        path.name.startswith(".env.") and path.name != ".env.example"
    )
