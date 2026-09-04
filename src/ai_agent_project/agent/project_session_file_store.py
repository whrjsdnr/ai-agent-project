"""Atomic persistence for shallow project-session orchestration state."""

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID

from ai_agent_project.agent.project_session import ProjectSession
from ai_agent_project.agent.project_session_application import (
    ProjectSessionAlreadyExistsError,
    ProjectSessionError,
    ProjectSessionNotFoundError,
)


class ProjectSessionStorageError(ProjectSessionError):
    """Raised for invalid or unreadable project-session snapshots."""


class FileProjectStore:
    """Persist ProjectSession envelopes separately from Developer project runs."""

    def __init__(self, root: Path) -> None:
        self._root = root.expanduser().resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        if not self._root.is_dir():
            raise ProjectSessionStorageError("Project store root is not a directory")

    def create(self, project_id: str, project: ProjectSession) -> None:
        path = self._path_for(project_id)
        if path.exists():
            raise ProjectSessionAlreadyExistsError(
                f"Project already exists: {project_id}"
            )
        self._write(
            path, {"project_id": project_id, "project": project.model_dump(mode="json")}
        )

    def get(self, project_id: str) -> ProjectSession | None:
        path = self._path_for(project_id)
        if not path.exists():
            return None
        return self._read(project_id, path)

    def replace(self, project_id: str, project: ProjectSession) -> None:
        path = self._path_for(project_id)
        if not path.exists():
            raise ProjectSessionNotFoundError(f"Project not found: {project_id}")
        self._read(project_id, path)
        self._write(
            path, {"project_id": project_id, "project": project.model_dump(mode="json")}
        )

    def _path_for(self, project_id: str) -> Path:
        try:
            parsed = UUID(project_id)
        except ValueError as error:
            raise ProjectSessionStorageError(
                "Project ID must be a canonical UUID"
            ) from error
        if str(parsed) != project_id:
            raise ProjectSessionStorageError("Project ID must be a canonical UUID")
        return self._root / f"{project_id}.json"

    @staticmethod
    def _read(project_id: str, path: Path) -> ProjectSession:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ProjectSessionStorageError(
                f"Could not read project snapshot: {project_id}"
            ) from error
        if not isinstance(raw, dict) or raw.get("project_id") != project_id:
            raise ProjectSessionStorageError(
                "Project snapshot ID does not match its file"
            )
        payload = raw.get("project")
        if not isinstance(payload, dict):
            raise ProjectSessionStorageError("Project snapshot is missing project data")
        try:
            return ProjectSession.model_validate(payload)
        except ValueError as error:
            raise ProjectSessionStorageError(
                f"Project snapshot is invalid: {project_id}"
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
            raise ProjectSessionStorageError(
                f"Could not persist project snapshot: {path.stem}"
            ) from error


def default_project_store_root() -> Path:
    return Path.home() / ".local" / "share" / "ai-agent" / "projects"
