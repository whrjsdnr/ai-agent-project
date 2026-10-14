"""Durable public event journal with atomic sequences and nonblocking run locks."""

import hashlib
import os
import sqlite3
from collections.abc import Iterator
from contextlib import ExitStack, closing, contextmanager
from pathlib import Path
from uuid import UUID

from ai_agent_project.agent.code_snapshot import (
    CodeSnapshot,
    SnapshotError,
    SnapshotSummary,
    summary,
    validate_snapshot,
)
from ai_agent_project.agent.execution_events import (
    CURRENT_EXECUTION,
    PublicExecutionEvent,
)
from ai_agent_project.execution_privacy import (
    public_command,
    public_log,
    public_relative_path,
)
from ai_agent_project.file_lock import exclusive_file_lock


class ExecutionEventError(Exception):
    """Safe event storage or mutation conflict boundary."""


def canonical_id(value: str) -> str:
    try:
        if str(UUID(value)) != value:
            raise ValueError
    except (ValueError, AttributeError):
        raise ExecutionEventError("Invalid execution identifier") from None
    return value


class FileExecutionEventStore:
    def __init__(self, root: Path) -> None:
        self.root = root.absolute()
        self.database = self.root / "events.sqlite3"

    def _check(self) -> None:
        for path in (
            self.database,
            *(
                self.root / (self.database.name + suffix)
                for suffix in ("-wal", "-shm", "-journal")
            ),
            self.root,
            *self.root.parents,
        ):
            if path.is_symlink() or path.is_junction():
                raise ExecutionEventError("Unsafe event store path")

    def _prepare(self) -> None:
        self._check()
        self.root.mkdir(parents=True, exist_ok=True)
        self._check()

    @contextmanager
    def guard(self, run_id: str, *, workspace: Path | None = None) -> Iterator[None]:
        canonical_id(run_id)
        self._prepare()
        locks = [self.root / f"run-{run_id}.lock"]
        if workspace is not None:
            locks.append(self.root / f"execution-{run_id}.lock")
            digest = hashlib.sha256(str(workspace).encode()).hexdigest()
            locks.append(self.root / f"workspace-{digest}.lock")
        try:
            with ExitStack() as stack:
                for path in locks:
                    if path.is_symlink() or path.is_junction():
                        raise ExecutionEventError("Unsafe execution lock")
                    stack.enter_context(exclusive_file_lock(path, blocking=False))
                yield
        except (OSError, sqlite3.Error):
            raise ExecutionEventError(
                "Execution is busy or event storage is unavailable"
            ) from None

    def _clean_event(self, event: PublicExecutionEvent) -> PublicExecutionEvent:
        canonical_id(event.run_id)
        canonical_id(event.attempt_id)
        canonical_id(event.event_id)
        if event.operation_id:
            canonical_id(event.operation_id)
        if event.snapshot_id:
            canonical_id(event.snapshot_id)
        context = CURRENT_EXECUTION.get()
        workspace = context.workspace if context else Path("/nonpublic-workspace")
        secrets = context.secrets if context else ()
        command = None
        path = None
        try:
            if event.command:
                command = public_command(event.command)
            if event.path:
                path = public_relative_path(event.path).as_posix()
                if context:
                    candidate = workspace
                    for part in Path(path).parts:
                        candidate /= part
                        if candidate.is_symlink() or candidate.is_junction():
                            path = None
                            break
                    if not candidate.resolve().is_relative_to(workspace):
                        path = None
        except ValueError:
            pass
        clean = event.model_copy(
            update={
                "command": public_log(command, secrets=secrets, workspace=workspace)
                if command
                else None,
                "path": public_log(path, secrets=secrets, workspace=workspace)
                if path
                else None,
                "phase_id": public_log(
                    event.phase_id, secrets=secrets, workspace=workspace
                )
                if event.phase_id
                else None,
                "stdout": public_log(
                    event.stdout, secrets=secrets, workspace=workspace
                ),
                "stderr": public_log(
                    event.stderr, secrets=secrets, workspace=workspace
                ),
            }
        )
        return clean

    @staticmethod
    def _initialize(connection: sqlite3.Connection) -> None:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS events (run_id TEXT NOT NULL, sequence INTEGER NOT NULL, content TEXT NOT NULL, PRIMARY KEY (run_id, sequence))"
        )

    @staticmethod
    def _insert_event(
        connection: sqlite3.Connection, event: PublicExecutionEvent
    ) -> PublicExecutionEvent:
        sequence = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM events WHERE run_id = ?",
            (event.run_id,),
        ).fetchone()[0]
        event = event.model_copy(update={"sequence": sequence})
        connection.execute(
            "INSERT INTO events VALUES (?, ?, ?)",
            (event.run_id, sequence, event.model_dump_json()),
        )
        return event

    def append(self, event: PublicExecutionEvent) -> PublicExecutionEvent:
        clean = self._clean_event(event)
        try:
            self._prepare()
            with closing(sqlite3.connect(self.database, timeout=5)) as connection:
                self._initialize(connection)
                connection.execute("BEGIN IMMEDIATE")
                clean = self._insert_event(connection, clean)
                connection.commit()
            return clean
        except (OSError, sqlite3.Error):
            raise ExecutionEventError(
                "Could not persist public execution event"
            ) from None

    def save_snapshot(self, snapshot: CodeSnapshot) -> CodeSnapshot:
        canonical_id(snapshot.snapshot_id)
        canonical_id(snapshot.run_id)
        canonical_id(snapshot.attempt_id)
        if snapshot.operation_id:
            canonical_id(snapshot.operation_id)
        context = CURRENT_EXECUTION.get()
        if context is None or (
            context.run_id,
            context.attempt_id,
            context.phase_id,
            context.repair_attempt,
        ) != (
            snapshot.run_id,
            snapshot.attempt_id,
            snapshot.phase_id,
            snapshot.repair_attempt,
        ):
            raise ExecutionEventError(
                "Snapshot must belong to the active execution context"
            )
        validate_snapshot(snapshot, secrets=context.secrets)
        event = self._clean_event(
            PublicExecutionEvent(
                run_id=snapshot.run_id,
                phase_id=snapshot.phase_id,
                attempt_id=snapshot.attempt_id,
                repair_attempt=snapshot.repair_attempt,
                operation_id=snapshot.operation_id,
                kind="snapshot_saved",
                status="completed" if snapshot.complete else "unknown",
                source="workspace_observation",
                snapshot_id=snapshot.snapshot_id,
                snapshot_stage=snapshot.stage,
            )
        )
        snapshot = snapshot.model_copy(update={"phase_id": event.phase_id})
        try:
            self._prepare()
            with closing(sqlite3.connect(self.database, timeout=5)) as connection:
                self._initialize(connection)
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS snapshots (snapshot_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, attempt_id TEXT NOT NULL, sequence INTEGER NOT NULL, summary TEXT NOT NULL, content TEXT NOT NULL)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS snapshots_run_sequence ON snapshots (run_id, sequence)"
                )
                connection.execute("BEGIN IMMEDIATE")
                event = self._insert_event(connection, event)
                snapshot = snapshot.model_copy(update={"sequence": event.sequence})
                self._insert_snapshot(connection, snapshot)
                connection.commit()
            return snapshot
        except (OSError, sqlite3.Error):
            raise ExecutionEventError("Could not atomically persist snapshot") from None

    @staticmethod
    def _insert_snapshot(
        connection: sqlite3.Connection, snapshot: CodeSnapshot
    ) -> None:
        connection.execute(
            "INSERT INTO snapshots VALUES (?, ?, ?, ?, ?, ?)",
            (
                snapshot.snapshot_id,
                snapshot.run_id,
                snapshot.attempt_id,
                snapshot.sequence,
                summary(snapshot).model_dump_json(),
                snapshot.model_dump_json(),
            ),
        )

    def list_snapshots(
        self, run_id: str, *, before_sequence: int | None = None, limit: int = 100
    ) -> tuple[SnapshotSummary, ...]:
        canonical_id(run_id)
        if not 1 <= limit <= 500 or before_sequence is not None and before_sequence < 1:
            raise ExecutionEventError("Invalid snapshot query")
        self._check()
        if not self.database.exists():
            return ()
        try:
            with closing(
                sqlite3.connect(
                    self.database.as_uri() + "?mode=ro", uri=True, timeout=5
                )
            ) as connection:
                if not connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='snapshots'"
                ).fetchone():
                    return ()
                rows = connection.execute(
                    "SELECT summary FROM snapshots WHERE run_id = ? AND (? IS NULL OR sequence < ?) ORDER BY sequence DESC LIMIT ?",
                    (run_id, before_sequence, before_sequence, limit),
                ).fetchall()
            return tuple(SnapshotSummary.model_validate_json(row[0]) for row in rows)
        except (OSError, sqlite3.Error, ValueError):
            raise ExecutionEventError("Could not read snapshot history") from None

    def get_snapshot(self, run_id: str, snapshot_id: str) -> CodeSnapshot | None:
        canonical_id(run_id)
        canonical_id(snapshot_id)
        self._check()
        if not self.database.exists():
            return None
        try:
            with closing(
                sqlite3.connect(
                    self.database.as_uri() + "?mode=ro", uri=True, timeout=5
                )
            ) as connection:
                if not connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='snapshots'"
                ).fetchone():
                    return None
                row = connection.execute(
                    "SELECT content FROM snapshots WHERE run_id = ? AND snapshot_id = ?",
                    (run_id, snapshot_id),
                ).fetchone()
            result = CodeSnapshot.model_validate_json(row[0]) if row else None
            if result:
                if result.run_id != run_id or result.snapshot_id != snapshot_id:
                    raise SnapshotError(
                        "Snapshot identity does not match its storage row"
                    )
                validate_snapshot(result, secrets=())
            return result
        except (OSError, sqlite3.Error, ValueError, SnapshotError):
            raise ExecutionEventError("Could not safely read snapshot") from None

    def attempt_snapshot(
        self, run_id: str, attempt_id: str, *, baseline: bool
    ) -> CodeSnapshot | None:
        canonical_id(run_id)
        canonical_id(attempt_id)
        self._check()
        if not self.database.exists():
            return None
        try:
            with closing(
                sqlite3.connect(
                    self.database.as_uri() + "?mode=ro", uri=True, timeout=5
                )
            ) as connection:
                if not connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='snapshots'"
                ).fetchone():
                    return None
                row = connection.execute(
                    "SELECT snapshot_id FROM snapshots WHERE run_id = ? AND attempt_id = ? AND json_extract(summary, '$.stage') "
                    + (
                        "= 'before' ORDER BY sequence ASC LIMIT 1"
                        if baseline
                        else "!= 'before' ORDER BY sequence DESC LIMIT 1"
                    ),
                    (run_id, attempt_id),
                ).fetchone()
            return self.get_snapshot(run_id, row[0]) if row else None
        except (OSError, sqlite3.Error):
            raise ExecutionEventError("Could not read attempt snapshot") from None

    def recovery_events(self, run_id: str) -> tuple[PublicExecutionEvent, ...]:
        canonical_id(run_id)
        self._check()
        if not self.database.exists():
            return ()
        try:
            with closing(
                sqlite3.connect(
                    self.database.as_uri() + "?mode=ro", uri=True, timeout=5
                )
            ) as connection:
                rows = connection.execute(
                    "SELECT content FROM events WHERE run_id = ? AND (json_extract(content, '$.kind') IN ('phase_started', 'phase_finished', 'phase_failed') OR (json_extract(content, '$.kind') = 'snapshot_saved' AND json_extract(content, '$.snapshot_stage') = 'before')) ORDER BY sequence",
                    (run_id,),
                ).fetchall()
                last = connection.execute(
                    "SELECT content FROM events WHERE run_id = ? AND sequence IN (SELECT MAX(sequence) FROM events WHERE run_id = ? GROUP BY json_extract(content, '$.attempt_id')) ORDER BY sequence",
                    (run_id, run_id),
                ).fetchall()
            return tuple(
                PublicExecutionEvent.model_validate_json(row[0])
                for row in [*rows, *last]
            )
        except (OSError, sqlite3.Error, ValueError):
            raise ExecutionEventError(
                "Could not read execution recovery evidence"
            ) from None

    def previous_snapshot(
        self, run_id: str, snapshot: CodeSnapshot
    ) -> CodeSnapshot | None:
        canonical_id(run_id)
        self._check()
        try:
            with closing(
                sqlite3.connect(
                    self.database.as_uri() + "?mode=ro", uri=True, timeout=5
                )
            ) as connection:
                row = connection.execute(
                    "SELECT snapshot_id FROM snapshots WHERE run_id = ? AND attempt_id = ? AND sequence < ? ORDER BY sequence DESC LIMIT 1",
                    (run_id, snapshot.attempt_id, snapshot.sequence),
                ).fetchone()
            return self.get_snapshot(run_id, row[0]) if row else None
        except (OSError, sqlite3.Error):
            raise ExecutionEventError("Could not read previous snapshot") from None

    def run_activity(self, run_id: str) -> str:
        """Probe an existing lease; never create files or alter workflow state."""
        canonical_id(run_id)
        self._check()
        path = self.root / f"execution-{run_id}.lock"
        if not path.exists():
            return "inactive"
        if path.is_symlink() or path.is_junction():
            return "unknown"
        try:
            with path.open("r+b") as stream:
                if not os.path.samestat(path.stat(), os.fstat(stream.fileno())):
                    return "unknown"
                if os.name == "nt":
                    import msvcrt

                    try:
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    except OSError:
                        return "active"
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    try:
                        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        return "active"
            return "inactive"
        except OSError:
            return "unknown"

    def query(
        self, run_id: str, *, after_sequence: int = 0, limit: int = 200
    ) -> tuple[PublicExecutionEvent, ...]:
        canonical_id(run_id)
        if (
            not isinstance(after_sequence, int)
            or not isinstance(limit, int)
            or after_sequence < 0
            or not 1 <= limit <= 500
        ):
            raise ExecutionEventError("Invalid event query")
        self._check()
        if not self.database.exists():
            return ()
        try:
            with closing(
                sqlite3.connect(
                    self.database.as_uri() + "?mode=ro", uri=True, timeout=5
                )
            ) as connection:
                rows = connection.execute(
                    "SELECT content FROM events WHERE run_id = ? AND sequence > ? ORDER BY sequence LIMIT ?",
                    (run_id, after_sequence, limit),
                ).fetchall()
            return tuple(
                PublicExecutionEvent.model_validate_json(row[0]) for row in rows
            )
        except (OSError, sqlite3.Error, ValueError):
            raise ExecutionEventError(
                "Could not read public execution events"
            ) from None

    def latest(self, run_id: str) -> PublicExecutionEvent | None:
        return self._latest(run_id)

    def latest_phase(self, run_id: str) -> PublicExecutionEvent | None:
        return self._latest(run_id, phase_only=True)

    def _latest(
        self, run_id: str, *, phase_only: bool = False
    ) -> PublicExecutionEvent | None:
        canonical_id(run_id)
        self._check()
        if not self.database.exists():
            return None
        try:
            with closing(
                sqlite3.connect(
                    self.database.as_uri() + "?mode=ro", uri=True, timeout=5
                )
            ) as connection:
                row = connection.execute(
                    "SELECT content FROM events WHERE run_id = ? "
                    + (
                        "AND json_extract(content, '$.kind') IN ('phase_started', 'phase_finished', 'phase_failed') "
                        if phase_only
                        else ""
                    )
                    + "ORDER BY sequence DESC LIMIT 1",
                    (run_id,),
                ).fetchone()
            return PublicExecutionEvent.model_validate_json(row[0]) if row else None
        except (OSError, sqlite3.Error, ValueError):
            raise ExecutionEventError(
                "Could not read public execution events"
            ) from None
