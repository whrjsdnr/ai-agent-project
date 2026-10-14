"""Bounded, public snapshots and comparisons of actual workspace files."""

import difflib
import os
import stat
from datetime import UTC, datetime
from itertools import islice
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from ai_agent_project.agent.execution_events import (
    CURRENT_EXECUTION,
    ExecutionContext,
    emit,
)
from ai_agent_project.execution_privacy import public_relative_path, sanitize_text
from ai_agent_project.workspace_io import open_directory_nofollow

MAX_FILE_BYTES = 200_000
MAX_TOTAL_BYTES = 2_000_000
MAX_SNAPSHOT_FILES = 500
MAX_VISITED_ENTRIES = 5_000
MAX_SERIALIZED_BYTES = 4_000_000
MAX_DIFF_CHARS = 400_000
TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".txt",
    ".toml",
    ".json",
    ".yaml",
    ".yml",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".html",
    ".css",
    ".sql",
    ".rst",
    ".ini",
    ".cfg",
    ".sh",
    ".bat",
    ".ps1",
}
BINARY_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".pdf",
    ".zip",
    ".exe",
    ".dll",
    ".so",
    ".woff",
    ".woff2",
}
SnapshotStage = Literal["before", "tool", "after"]
ContentState = Literal[
    "text",
    "binary",
    "unsupported",
    "too_large",
    "total_limit",
    "sensitive_content",
    "changed_during_capture",
    "unavailable",
    "hardlink",
]


class SnapshotError(Exception):
    """Snapshot failure whose private OS details must never be published."""


class SnapshotModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SnapshotFile(SnapshotModel):
    path: str
    size: int
    modified_ns: int
    changed_ns: int
    identity: tuple[int, int]
    content_state: ContentState
    content: str | None = None


class CodeSnapshot(SnapshotModel):
    schema_version: Literal[1] = 1
    snapshot_id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    phase_id: str | None
    attempt_id: str
    repair_attempt: int = 0
    operation_id: str | None = None
    sequence: int = 0
    stage: SnapshotStage
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    complete: bool
    reason: Literal[
        "complete",
        "inventory_limit",
        "unsafe_path",
        "changed_during_capture",
        "unavailable",
        "platform_unverified",
    ]
    files: tuple[SnapshotFile, ...] = ()


class SnapshotSummary(SnapshotModel):
    snapshot_id: str
    phase_id: str | None
    attempt_id: str
    repair_attempt: int
    operation_id: str | None
    sequence: int
    stage: SnapshotStage
    captured_at: datetime
    complete: bool
    reason: str
    file_count: int


class CodeChange(SnapshotModel):
    path: str
    status: Literal["Created", "Modified", "Deleted", "Observed"]
    attribution: Literal["Observed Change"] = "Observed Change"
    diff: str
    reason: str
    before_state: str | None
    after_state: str | None
    before_size: int | None = None
    after_size: int | None = None
    before_modified_ns: int | None = None
    after_modified_ns: int | None = None


class CodeChangesView(SnapshotModel):
    before: SnapshotSummary | None
    after: SnapshotSummary | None
    changes: tuple[CodeChange, ...]
    message: str


def summary(snapshot: CodeSnapshot) -> SnapshotSummary:
    return SnapshotSummary(
        **snapshot.model_dump(exclude={"schema_version", "run_id", "files"}),
        file_count=len(snapshot.files),
    )


def _metadata(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _verify_directory(root: Path, relative: Path, descriptor: int) -> None:
    with_directory = open_directory_nofollow(root / relative)
    try:
        if not os.path.samestat(os.fstat(descriptor), os.fstat(with_directory)):
            raise SnapshotError("Workspace directory changed during capture")
    finally:
        os.close(with_directory)


def _read_entry(
    root: Path,
    relative: Path,
    directory_fd: int,
    remaining: int,
    secrets: tuple[str, ...],
) -> SnapshotFile:
    """Never follow a link; reject replacement or writes during a content read."""
    _verify_directory(root, relative.parent, directory_fd)
    initial = os.stat(relative.name, dir_fd=directory_fd, follow_symlinks=False)
    if (
        not stat.S_ISREG(initial.st_mode)
        or getattr(initial, "st_file_attributes", 0) & 0x400
    ):
        raise SnapshotError("Unsafe snapshot entry")
    values = {
        "path": relative.as_posix(),
        "size": initial.st_size,
        "modified_ns": initial.st_mtime_ns,
        "changed_ns": initial.st_ctime_ns,
        "identity": (initial.st_dev, initial.st_ino),
    }
    if initial.st_nlink > 1:
        return SnapshotFile(**values, content_state="hardlink")
    if relative.suffix.casefold() not in TEXT_SUFFIXES:
        return SnapshotFile(
            **values,
            content_state="binary"
            if relative.suffix.casefold() in BINARY_SUFFIXES
            else "unsupported",
        )
    if initial.st_size > MAX_FILE_BYTES:
        return SnapshotFile(**values, content_state="too_large")
    if initial.st_size > remaining:
        return SnapshotFile(**values, content_state="total_limit")
    descriptor = os.open(
        relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd
    )
    try:
        opened = os.fstat(descriptor)
        if _metadata(opened) != _metadata(initial) or not stat.S_ISREG(opened.st_mode):
            return SnapshotFile(**values, content_state="changed_during_capture")
        _verify_directory(root, relative.parent, directory_fd)
        with os.fdopen(os.dup(descriptor), "rb") as stream:
            data = stream.read(MAX_FILE_BYTES + 1)
        final = os.fstat(descriptor)
        named = os.stat(relative.name, dir_fd=directory_fd, follow_symlinks=False)
        _verify_directory(root, relative.parent, directory_fd)
        if (
            _metadata(initial) != _metadata(final)
            or _metadata(final) != _metadata(named)
            or len(data) != initial.st_size
        ):
            return SnapshotFile(**values, content_state="changed_during_capture")
        try:
            content = data.decode("utf-8")
        except UnicodeError:
            return SnapshotFile(**values, content_state="binary")
        if b"\0" in data:
            return SnapshotFile(**values, content_state="binary")
        if (
            sanitize_text(content, secrets=secrets) != content
            or "-----BEGIN CERTIFICATE-----" in content
        ):
            return SnapshotFile(**values, content_state="sensitive_content")
        return SnapshotFile(**values, content_state="text", content=content)
    finally:
        os.close(descriptor)


def snapshot_platform_verified() -> bool:
    return os.name == "posix"


def capture_snapshot(
    context: ExecutionContext, stage: SnapshotStage, *, operation_id: str | None = None
) -> CodeSnapshot:
    header = {
        "run_id": context.run_id,
        "phase_id": context.phase_id,
        "attempt_id": context.attempt_id,
        "repair_attempt": context.repair_attempt,
        "stage": stage,
        "operation_id": operation_id,
    }
    # No pathname fallback on platforms without verified directory-descriptor reads.
    if not snapshot_platform_verified():
        return CodeSnapshot(**header, complete=False, reason="platform_unverified")
    root = context.workspace
    if not root.is_absolute():
        raise SnapshotError("Workspace root must be absolute")
    files: list[SnapshotFile] = []
    total = 0
    visited = 0
    reason = "complete"
    root_fd = open_directory_nofollow(root)
    root_metadata = os.fstat(root_fd)

    def visit(relative: Path, descriptor: int) -> None:
        nonlocal total, visited, reason
        remaining_entries = MAX_VISITED_ENTRIES - visited
        if remaining_entries <= 0 or len(relative.parts) > 64:
            reason = "inventory_limit"
            return
        _verify_directory(root, relative, descriptor)
        directory_before = os.fstat(descriptor)
        with os.scandir(descriptor) as entries:
            bounded = list(islice(entries, remaining_entries))
            visited += len(bounded)
            if len(bounded) == remaining_entries and next(entries, None) is not None:
                reason = "inventory_limit"
            for entry in sorted(bounded, key=lambda item: item.name):
                if len(files) >= MAX_SNAPSHOT_FILES:
                    reason = "inventory_limit"
                    return
                path = relative / entry.name
                try:
                    public_relative_path(path.as_posix())
                    if (
                        sanitize_text(path.as_posix(), secrets=context.secrets)
                        != path.as_posix()
                    ):
                        continue
                except ValueError:
                    continue
                metadata = entry.stat(follow_symlinks=False)
                if (
                    stat.S_ISLNK(metadata.st_mode)
                    or getattr(metadata, "st_file_attributes", 0) & 0x400
                ):
                    reason = "unsafe_path"
                    continue
                if stat.S_ISDIR(metadata.st_mode):
                    child = os.open(
                        entry.name,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                        dir_fd=descriptor,
                    )
                    try:
                        visit(path, child)
                    finally:
                        os.close(child)
                elif stat.S_ISREG(metadata.st_mode):
                    try:
                        file = _read_entry(
                            root,
                            path,
                            descriptor,
                            MAX_TOTAL_BYTES - total,
                            context.secrets,
                        )
                    except (OSError, SnapshotError):
                        reason = "changed_during_capture"
                        continue
                    if file.content_state == "changed_during_capture":
                        reason = "changed_during_capture"
                    files.append(file)
                    if file.content is not None:
                        total += len(file.content.encode("utf-8"))
        _verify_directory(root, relative, descriptor)
        directory_after = os.fstat(descriptor)
        if (directory_before.st_mtime_ns, directory_before.st_ctime_ns) != (
            directory_after.st_mtime_ns,
            directory_after.st_ctime_ns,
        ):
            reason = "changed_during_capture"

    try:
        visit(Path("."), root_fd)
        fresh = open_directory_nofollow(root)
        try:
            if not os.path.samestat(root_metadata, os.fstat(fresh)):
                raise SnapshotError("Workspace root replaced")
        finally:
            os.close(fresh)
        return CodeSnapshot(
            **header, complete=reason == "complete", reason=reason, files=tuple(files)
        )
    except (OSError, SnapshotError):
        # Discard all content if directory/root integrity could not be established.
        return CodeSnapshot(**header, complete=False, reason="changed_during_capture")
    finally:
        os.close(root_fd)


def validate_snapshot(snapshot: CodeSnapshot, *, secrets: tuple[str, ...]) -> None:
    if len(snapshot.files) > MAX_SNAPSHOT_FILES:
        raise SnapshotError("Snapshot file limit exceeded")
    total = 0
    paths = set()
    for file in snapshot.files:
        try:
            path = public_relative_path(file.path).as_posix()
        except ValueError:
            raise SnapshotError("Unsafe snapshot path") from None
        if path in paths or path != file.path or len(path.encode()) > 1024:
            raise SnapshotError("Invalid snapshot path")
        paths.add(path)
        if sanitize_text(path, secrets=secrets) != path:
            raise SnapshotError("Snapshot path contains private data")
        if file.content is not None:
            if (
                file.content_state != "text"
                or len(file.content.encode("utf-8")) > MAX_FILE_BYTES
                or sanitize_text(file.content, secrets=secrets) != file.content
                or "-----BEGIN CERTIFICATE-----" in file.content
            ):
                raise SnapshotError("Snapshot contains private or oversized content")
            total += len(file.content.encode("utf-8"))
    if (
        total > MAX_TOTAL_BYTES
        or len(snapshot.model_dump_json().encode("utf-8")) > MAX_SERIALIZED_BYTES
    ):
        raise SnapshotError("Snapshot size limit exceeded")


def record_snapshot(stage: SnapshotStage, *, operation_id: str | None = None) -> None:
    context = CURRENT_EXECUTION.get()
    if context is None:
        return
    writer = getattr(context.writer, "save_snapshot", None)
    if writer is None:
        return
    try:
        writer(capture_snapshot(context, stage, operation_id=operation_id))
    except Exception:
        emit("snapshot_failed", "failed", error="snapshot_failed")
        raise


def compare_snapshots(
    before: CodeSnapshot | None, after: CodeSnapshot | None
) -> CodeChangesView:
    if before is None or after is None:
        return CodeChangesView(
            before=summary(before) if before else None,
            after=summary(after) if after else None,
            changes=(),
            message="Historical Diff Unavailable: a before or after snapshot was not recorded.",
        )
    if (
        before.run_id != after.run_id
        or before.attempt_id != after.attempt_id
        or before.sequence >= after.sequence
    ):
        raise SnapshotError(
            "Snapshots do not describe the same ordered execution attempt"
        )
    if before.reason == "platform_unverified" or after.reason == "platform_unverified":
        return CodeChangesView(
            before=summary(before),
            after=summary(after),
            changes=(),
            message="Historical Diff Unavailable: verified snapshot reads are unavailable on this platform.",
        )
    old = {file.path: file for file in before.files}
    new = {file.path: file for file in after.files}
    changes = []
    for path in sorted(old.keys() | new.keys()):
        left, right = old.get(path), new.get(path)
        if left == right:
            continue
        if (
            left
            and right
            and left.content is not None
            and right.content is not None
            and left.content == right.content
        ):
            continue
        status = (
            "Created"
            if left is None and before.complete
            else "Deleted"
            if right is None and after.complete
            else "Modified"
            if left and right
            else "Observed"
        )
        available = (
            left is None
            and before.complete
            or left is not None
            and left.content is not None
        ) and (
            right is None
            and after.complete
            or right is not None
            and right.content is not None
        )
        diff = ""
        reason = "Unified Diff of public text; causation is unconfirmed."
        if available:
            old_text = left.content if left else ""
            new_text = right.content if right else ""
            parts = difflib.unified_diff(
                old_text.splitlines(keepends=True),
                new_text.splitlines(keepends=True),
                fromfile=f"before/{path}" if left else "/dev/null",
                tofile=f"after/{path}" if right else "/dev/null",
            )
            diff = "".join(
                part
                if part.endswith("\n")
                else part + "\n\\ No newline at end of file\n"
                for part in parts
            )
            if len(diff) > MAX_DIFF_CHARS:
                diff = diff[:MAX_DIFF_CHARS] + "\n[Diff truncated]"
        else:
            states = [
                file.content_state
                for file in (left, right)
                if file and file.content is None
            ]
            reason = "Unified Diff unavailable: " + (
                ", ".join(states)
                if states
                else "incomplete inventory; absence does not prove creation or deletion"
            )
        changes.append(
            CodeChange(
                path=path,
                status=status,
                diff=diff,
                reason=reason,
                before_state=left.content_state if left else None,
                after_state=right.content_state if right else None,
                before_size=left.size if left else None,
                after_size=right.size if right else None,
                before_modified_ns=left.modified_ns if left else None,
                after_modified_ns=right.modified_ns if right else None,
            )
        )
    return CodeChangesView(
        before=summary(before),
        after=summary(after),
        changes=tuple(changes),
        message="Observed Change comparison. "
        + (
            "Inventory is incomplete; missing entries have unknown status."
            if not before.complete or not after.complete
            else "Snapshots reflect the captured files; no Agent causation is asserted."
        ),
    )
