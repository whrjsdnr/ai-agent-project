"""Atomic snapshot transactions; reads do not create paths or lock files."""

import os
from collections.abc import Callable
from pathlib import Path
from tempfile import NamedTemporaryFile

from pydantic import ValidationError

from ai_agent_project.file_lock import exclusive_file_lock
from ai_agent_project.improvement.errors import ImprovementError
from ai_agent_project.improvement.models import ImprovementState
from ai_agent_project.paths import runtime_paths


def default_improvement_root() -> Path:
    return runtime_paths().data / "improvements"


class FileImprovementStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root if root is not None else default_improvement_root()

    def read(self) -> ImprovementState:
        try:
            return ImprovementState.model_validate_json(
                (self.root / "state.json").read_text(encoding="utf-8")
            )
        except FileNotFoundError:
            return ImprovementState()
        except (OSError, ValueError, ValidationError):
            raise ImprovementError("Cannot read improvement records.") from None

    def transact(
        self, update: Callable[[ImprovementState], ImprovementState]
    ) -> ImprovementState:
        temporary = None
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            with exclusive_file_lock(self.root / "state.lock"):
                current = self.read()
                updated = update(current)
                if updated == current:
                    return current
                validated = ImprovementState.model_validate(updated.model_dump())
                with NamedTemporaryFile(
                    mode="w", encoding="utf-8", dir=self.root, delete=False
                ) as stream:
                    temporary = Path(stream.name)
                    stream.write(validated.model_dump_json())
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.root / "state.json")
                return validated
        except OSError:
            raise ImprovementError("Cannot persist improvement records.") from None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
