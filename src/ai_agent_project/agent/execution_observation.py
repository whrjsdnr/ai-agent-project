"""Observe real tool results and metadata changes without saving file contents."""

import os
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from uuid import uuid4

from ai_agent_project.agent.code_snapshot import record_snapshot
from ai_agent_project.agent.execution_events import CURRENT_EXECUTION, emit
from ai_agent_project.execution_privacy import public_command, public_relative_path
from ai_agent_project.tools.base import ToolResult


class _UnavailableObservation(Exception):
    pass


def _safe_metadata(root: Path, value: str) -> tuple[int, int, int] | None:
    relative = public_relative_path(value)
    path = root
    for part in relative.parts:
        path /= part
        if path.is_symlink() or path.is_junction():
            raise _UnavailableObservation
    if not path.resolve().is_relative_to(root):
        raise _UnavailableObservation
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return None
    if not path.is_file():
        return None
    return metadata.st_mtime_ns, metadata.st_size, metadata.st_ino


def capture_metadata(
    root: Path, *, target: str | None = None
) -> dict[str, tuple[int, int, int]] | None:
    try:
        if not root.is_dir() or any(
            path.is_symlink() or path.is_junction() for path in (root, *root.parents)
        ):
            return None
        if target is not None:
            value = public_relative_path(target).as_posix()
            metadata = _safe_metadata(root, value)
            return {value: metadata} if metadata is not None else {}
        result = {}
        visited = 0
        for directory, dirs, files in os.walk(root, followlinks=False):
            retained = []
            for name in dirs:
                path = Path(directory) / name
                try:
                    public_relative_path(
                        (path.relative_to(root) / "inspection.py").as_posix()
                    )
                    if not path.is_symlink() and not path.is_junction():
                        retained.append(name)
                except ValueError:
                    continue
            dirs[:] = retained
            for name in files:
                visited += 1
                if visited > 5_000 or len(result) >= 500:
                    return None
                relative = (Path(directory) / name).relative_to(root).as_posix()
                try:
                    metadata = _safe_metadata(root, relative)
                except (ValueError, _UnavailableObservation):
                    continue
                if metadata is not None:
                    result[relative] = metadata
        return result
    except (OSError, ValueError, _UnavailableObservation):
        return None


def record_changes(
    before: dict[str, tuple[int, int, int]] | None,
    after: dict[str, tuple[int, int, int]] | None,
    *,
    operation_id: str,
) -> None:
    if before is None or after is None:
        emit(
            "observation_unavailable",
            "unknown",
            source="workspace_observation",
            error="observation_unavailable",
            operation_id=operation_id,
        )
        return
    for path in sorted(before.keys() | after.keys()):
        if before.get(path) == after.get(path):
            continue
        change = (
            "created"
            if path not in before
            else "deleted"
            if path not in after
            else "modified"
        )
        emit(
            "file_observed",
            "completed",
            source="workspace_observation",
            path=path,
            change=change,
            attribution="unattributed",
            operation_id=operation_id,
        )


def observe_tool(name: str):
    def decorate(operation: Callable):
        @wraps(operation)
        def observed(self, arguments: dict[str, object]) -> ToolResult:
            context = CURRENT_EXECUTION.get()
            if context is None:
                return operation(self, arguments)
            operation_id = str(uuid4())
            source = "validation" if context.source == "validation" else "tool"
            command = None
            try:
                if name == "shell" and isinstance(arguments.get("command"), str):
                    command = public_command(arguments["command"])
            except ValueError:
                pass
            target = arguments.get("path") if name == "file" else None
            observe_files = name == "shell" or (
                name == "file"
                and arguments.get("operation") in {"write_file", "delete_file"}
            )
            before = (
                capture_metadata(context.workspace, target=target)
                if observe_files and (target is None or isinstance(target, str))
                else None
            )
            emit(
                "tool_started",
                "running",
                source=source,
                tool=name,
                command=command,
                operation_id=operation_id,
            )
            try:
                result = operation(self, arguments)
            except Exception:
                emit(
                    "tool_failed",
                    "failed",
                    source=source,
                    tool=name,
                    command=command,
                    operation_id=operation_id,
                    error="tool_failed",
                )
                if observe_files:
                    record_snapshot("tool", operation_id=operation_id)
                raise
            timed_out = bool(
                result.error and result.error.startswith("Command timed out after ")
            )
            data = (
                result.data if isinstance(result.data, dict) and name == "shell" else {}
            )
            emit(
                "tool_completed" if result.success else "tool_failed",
                "completed" if result.success else "timeout" if timed_out else "failed",
                tool=name,
                operation_id=operation_id,
                command=command,
                source=source,
                exit_code=data.get("exit_code")
                if isinstance(data.get("exit_code"), int)
                else None,
                stdout=data.get("stdout")
                if isinstance(data.get("stdout"), str)
                else "",
                stderr=data.get("stderr")
                if isinstance(data.get("stderr"), str)
                else "",
                error=None
                if result.success
                else "timeout"
                if timed_out
                else "tool_failed",
            )
            if observe_files:
                after = (
                    capture_metadata(context.workspace, target=target)
                    if target is None or isinstance(target, str)
                    else None
                )
                record_changes(before, after, operation_id=operation_id)
                record_snapshot("tool", operation_id=operation_id)
            return result

        return observed

    return decorate
