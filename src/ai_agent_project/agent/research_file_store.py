"""Atomic JSON-backed storage for CLI Research Discovery snapshots."""

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID

from ai_agent_project.agent.research import ResearchRun
from ai_agent_project.agent.research_application import (
    ResearchRunAlreadyExistsError,
    ResearchRunError,
    ResearchRunNotFoundError,
)


class ResearchRunStorageError(ResearchRunError):
    """Raised when a persisted research snapshot is invalid or unreadable."""


class FileResearchRunStore:
    """Persist one immutable ResearchRun JSON snapshot per canonical UUID."""

    def __init__(self, root: Path) -> None:
        self._root = root.expanduser().resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        if not self._root.is_dir():
            raise ResearchRunStorageError("Research run store root is not a directory")

    def create(self, research_run_id: str, research_run: ResearchRun) -> None:
        path = self._path_for(research_run_id)
        if path.exists():
            raise ResearchRunAlreadyExistsError(
                f"Research run already exists: {research_run_id}"
            )
        self._write(
            path,
            {
                "research_run_id": research_run_id,
                "research_run": research_run.model_dump(mode="json"),
            },
        )

    def get(self, research_run_id: str) -> ResearchRun | None:
        path = self._path_for(research_run_id)
        if not path.exists():
            return None
        return self._read(research_run_id, path)

    def replace(self, research_run_id: str, research_run: ResearchRun) -> None:
        path = self._path_for(research_run_id)
        if not path.exists():
            raise ResearchRunNotFoundError(f"Research run not found: {research_run_id}")
        self._read(research_run_id, path)
        self._write(
            path,
            {
                "research_run_id": research_run_id,
                "research_run": research_run.model_dump(mode="json"),
            },
        )

    def _path_for(self, research_run_id: str) -> Path:
        try:
            parsed = UUID(research_run_id)
        except ValueError as error:
            raise ResearchRunStorageError(
                "Research run ID must be a canonical UUID"
            ) from error
        if str(parsed) != research_run_id:
            raise ResearchRunStorageError("Research run ID must be a canonical UUID")
        return self._root / f"{research_run_id}.json"

    def _read(self, research_run_id: str, path: Path) -> ResearchRun:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ResearchRunStorageError(
                f"Could not read research run snapshot: {research_run_id}"
            ) from error
        if not isinstance(raw, dict) or raw.get("research_run_id") != research_run_id:
            raise ResearchRunStorageError(
                "Research run snapshot ID does not match its file"
            )
        payload = raw.get("research_run")
        if not isinstance(payload, dict):
            raise ResearchRunStorageError(
                "Research run snapshot is missing research data"
            )
        try:
            return ResearchRun.model_validate(payload)
        except ValueError as error:
            raise ResearchRunStorageError(
                f"Research run snapshot is invalid: {research_run_id}"
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
            raise ResearchRunStorageError(
                f"Could not persist research run snapshot: {path.stem}"
            ) from error


def default_research_run_store_root() -> Path:
    """Return the user-local default root for CLI research-run snapshots."""
    return Path.home() / ".local" / "share" / "ai-agent" / "research-runs"
