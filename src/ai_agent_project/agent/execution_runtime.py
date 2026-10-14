"""Bind public recording only to approved Developer mutations."""

import os
from collections.abc import Callable
from functools import wraps
from uuid import uuid4

from ai_agent_project.agent.code_snapshot import record_snapshot
from ai_agent_project.agent.execution_event_store import ExecutionEventError
from ai_agent_project.agent.execution_events import (
    ExecutionContext,
    emit,
    execution_context,
)
from ai_agent_project.agent.execution_recovery import (
    ExecutionRecoveryRequiredError,
    inspect_recovery,
)


def runtime_secrets(configured: str | None = None) -> tuple[str, ...]:
    # Values stay in memory and are never serialized as event metadata.
    return tuple(
        {
            value
            for name, value in os.environ.items()
            if value
            and (
                len(value) >= 4
                or any(
                    label in name.upper()
                    for label in ("KEY", "TOKEN", "SECRET", "PASS", "CREDENTIAL")
                )
            )
        }
        | ({configured} if configured else set())
    )


def observed_mutation(operation: Callable):
    @wraps(operation)
    def observed(self, project_run_id: str, *args, **kwargs):
        if self._events is None:
            return operation(self, project_run_id, *args, **kwargs)
        root = self._store.workspace_root_for(project_run_id)
        executing = operation.__name__ == "execute_current_phase"
        if executing and (
            not root.is_dir()
            or any(
                path.is_symlink() or path.is_junction()
                for path in (root, *root.parents)
            )
        ):
            raise ExecutionEventError("Workspace is unavailable or unsafe")
        with self._events.guard(project_run_id, workspace=root if executing else None):
            if (
                executing
                and inspect_recovery(
                    self._events, project_run_id, activity_override="inactive"
                ).blocks_execution
            ):
                raise ExecutionRecoveryRequiredError(
                    "Previous execution outcome is unknown; recovery is read-only"
                )
            run = self._require_project_run(project_run_id)
            context = ExecutionContext(
                writer=self._events,
                run_id=project_run_id,
                phase_id=run.execution_state.current_phase_id,
                attempt_id=str(uuid4()),
                workspace=root,
                secrets=self._event_secrets(),
            )
            with execution_context(context):
                try:
                    return operation(self, project_run_id, *args, **kwargs)
                except Exception:
                    if executing:
                        last = self._events.latest(project_run_id)
                        if (
                            last
                            and last.attempt_id == context.attempt_id
                            and last.kind != "phase_failed"
                        ):
                            emit("phase_failed", "failed", error="execution_failed")
                    raise
                finally:
                    if executing:
                        last = self._events.latest(project_run_id)
                        if (
                            last
                            and last.attempt_id == context.attempt_id
                            and last.kind != "snapshot_failed"
                        ):
                            record_snapshot("after")

    return observed
