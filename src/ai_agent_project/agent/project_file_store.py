"""Atomic JSON-backed storage for CLI project-run snapshots."""

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID

from ai_agent_project.agent.project_application import (
    ProjectRunAlreadyExistsError,
    ProjectRunError,
    ProjectRunNotFoundError,
)
from ai_agent_project.agent.project_runner import ProjectRun


class ProjectRunStorageError(ProjectRunError):
    """Raised when a persisted CLI project-run snapshot is invalid or unreadable."""


class FileProjectRunStore:
    """Persist whole immutable project snapshots in one JSON file per UUID."""

    def __init__(
        self,
        root: Path,
        *,
        workspace_root: Path | None = None,
    ) -> None:
        self._root = root.expanduser().resolve()
        self._workspace_root = (
            workspace_root.expanduser().resolve()
            if workspace_root is not None
            else None
        )
        self._root.mkdir(parents=True, exist_ok=True)
        if not self._root.is_dir():
            raise ProjectRunStorageError("Project run store root is not a directory")

    def create(self, project_run_id: str, project_run: ProjectRun) -> None:
        """Create a snapshot without overwriting an existing project run."""
        path = self._path_for(project_run_id)
        if path.exists():
            raise ProjectRunAlreadyExistsError(
                f"Project run already exists: {project_run_id}"
            )
        if self._workspace_root is None:
            raise ProjectRunStorageError("A workspace root is required to create a run")
        self._write(
            path,
            {
                "project_run_id": project_run_id,
                "workspace_root": str(self._workspace_root),
                "project_run": project_run.model_dump(mode="json"),
            },
        )

    def get(self, project_run_id: str) -> ProjectRun | None:
        """Load a snapshot, returning None when a valid ID has no saved run."""
        path = self._path_for(project_run_id)
        if not path.exists():
            return None
        return self._read(project_run_id, path)["project_run"]

    def replace(self, project_run_id: str, project_run: ProjectRun) -> None:
        """Atomically replace an existing whole snapshot while preserving metadata."""
        path = self._path_for(project_run_id)
        if not path.exists():
            raise ProjectRunNotFoundError(f"Project run not found: {project_run_id}")
        envelope = self._read(project_run_id, path)
        self._write(
            path,
            {
                "project_run_id": project_run_id,
                "workspace_root": str(envelope["workspace_root"]),
                "project_run": project_run.model_dump(mode="json"),
            },
        )

    def workspace_root_for(self, project_run_id: str) -> Path:
        """Return the saved absolute workspace root for one persisted run."""
        path = self._path_for(project_run_id)
        if not path.exists():
            raise ProjectRunNotFoundError(f"Project run not found: {project_run_id}")
        return Path(self._read(project_run_id, path)["workspace_root"])

    def _path_for(self, project_run_id: str) -> Path:
        try:
            parsed = UUID(project_run_id)
        except ValueError as error:
            raise ProjectRunStorageError(
                "Project run ID must be a canonical UUID"
            ) from error
        if str(parsed) != project_run_id:
            raise ProjectRunStorageError("Project run ID must be a canonical UUID")
        return self._root / f"{project_run_id}.json"

    def _read(self, project_run_id: str, path: Path) -> dict[str, object]:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ProjectRunStorageError(
                f"Could not read project run snapshot: {project_run_id}"
            ) from error
        if not isinstance(raw, dict):
            raise ProjectRunStorageError("Project run snapshot must be a JSON object")
        if raw.get("project_run_id") != project_run_id:
            raise ProjectRunStorageError(
                "Project run snapshot ID does not match its file"
            )
        workspace_root = raw.get("workspace_root")
        project_run = raw.get("project_run")
        if (
            not isinstance(workspace_root, str)
            or not Path(workspace_root).is_absolute()
        ):
            raise ProjectRunStorageError("Project run workspace root must be absolute")
        if not isinstance(project_run, dict):
            raise ProjectRunStorageError("Project run snapshot is missing project data")
        try:
            return {
                "workspace_root": workspace_root,
                "project_run": ProjectRun.model_validate(project_run),
            }
        except ValueError as error:
            raise ProjectRunStorageError(
                f"Project run snapshot is invalid: {project_run_id}"
            ) from error

    def _write(self, path: Path, payload: dict[str, object]) -> None:
        temporary_path: Path | None = None
        try:
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self._root,
                prefix=f".{path.stem}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                json.dump(payload, temporary, ensure_ascii=False, sort_keys=True)
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = Path(temporary.name)
            os.replace(temporary_path, path)
        except OSError as error:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise ProjectRunStorageError(
                f"Could not persist project run snapshot: {path.stem}"
            ) from error


def default_project_run_store_root() -> Path:
    """Return the Linux-friendly default storage location for CLI project runs."""
    return Path.home() / ".local" / "share" / "ai-agent" / "project-runs"
