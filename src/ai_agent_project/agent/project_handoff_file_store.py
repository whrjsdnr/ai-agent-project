"""Atomic create-once storage of orchestration-owned handoff metadata."""

import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID

from ai_agent_project.agent.project_handoff import ProjectHandoff
from ai_agent_project.agent.project_handoff_application import (
    ProjectHandoffAlreadyExistsError,
    ProjectHandoffError,
)
from ai_agent_project.paths import runtime_paths


class ProjectHandoffStorageError(ProjectHandoffError):
    """An invalid/unreadable handoff record cannot be silently skipped."""


class FileProjectHandoffStore:
    """One canonical UUID JSON file per handoff; reads create no directories."""

    def __init__(self, root: Path) -> None:
        self._root = root.expanduser().resolve()

    def create(self, handoff: ProjectHandoff) -> None:
        path = self._path_for(handoff.handoff_id)
        temporary_path: Path | None = None
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self._root,
                prefix=f".{handoff.handoff_id}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(handoff.model_dump_json())
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
            # Publishing a hard link is atomic and cannot overwrite another
            # process's winning record (unlike os.replace).
            os.link(temporary_path, path)
        except FileExistsError as error:
            raise ProjectHandoffAlreadyExistsError(
                f"Handoff already exists: {handoff.handoff_id}"
            ) from error
        except OSError as error:
            raise ProjectHandoffStorageError(
                f"Could not persist handoff: {handoff.handoff_id}"
            ) from error
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def get(self, handoff_id: str) -> ProjectHandoff | None:
        path = self._path_for(handoff_id)
        if path.is_symlink():
            raise ProjectHandoffStorageError("Handoff snapshot must not be a symlink")
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except (OSError, UnicodeError) as error:
            raise ProjectHandoffStorageError(
                f"Could not read handoff: {handoff_id}"
            ) from error
        try:
            handoff = ProjectHandoff.model_validate_json(raw)
        except ValueError as error:
            raise ProjectHandoffStorageError(
                f"Invalid handoff snapshot: {handoff_id}"
            ) from error
        if handoff.handoff_id != handoff_id:
            raise ProjectHandoffStorageError("Handoff snapshot ID does not match file")
        return handoff

    def list_for_project(self, project_id: str) -> tuple[ProjectHandoff, ...]:
        if not self._root.exists():
            return ()
        if not self._root.is_dir():
            raise ProjectHandoffStorageError("Handoff store root is not a directory")
        try:
            paths = sorted(self._root.glob("*.json"))
            handoffs = []
            for path in paths:
                handoff = self.get(path.stem)
                if handoff is None:
                    raise ProjectHandoffStorageError(
                        "Handoff disappeared while listing"
                    )
                if handoff.project_id == project_id:
                    handoffs.append(handoff)
        except OSError as error:
            raise ProjectHandoffStorageError("Could not list handoff store") from error
        return tuple(sorted(handoffs, key=lambda h: (h.created_at, h.handoff_id)))

    def _path_for(self, handoff_id: str) -> Path:
        try:
            parsed = UUID(handoff_id)
        except ValueError as error:
            raise ProjectHandoffStorageError(
                "Handoff ID must be a canonical UUID"
            ) from error
        if str(parsed) != handoff_id:
            raise ProjectHandoffStorageError("Handoff ID must be a canonical UUID")
        return self._root / f"{handoff_id}.json"


def default_project_handoff_store_root() -> Path:
    return runtime_paths().data / "handoffs"
