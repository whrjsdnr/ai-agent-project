"""Crash evidence and snapshot transaction recovery never rerun the Agent."""

import os
import select
import subprocess
import sys
from dataclasses import replace
from uuid import uuid4

import pytest

from ai_agent_project.agent.code_snapshot import compare_snapshots, record_snapshot
from ai_agent_project.agent.execution_event_store import FileExecutionEventStore
from ai_agent_project.agent.execution_events import (
    ExecutionContext,
    emit,
    execution_context,
)
from ai_agent_project.agent.execution_recovery import inspect_recovery


@pytest.fixture
def recovery(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store = FileExecutionEventStore(tmp_path / "execution-events")
    context = ExecutionContext(store, str(uuid4()), "PHASE-1", str(uuid4()), workspace)
    return store, context


def test_empty_preparation_active_interrupted_and_terminal_states(recovery):
    store, context = recovery
    assert inspect_recovery(store, context.run_id).attempts == ()
    assert not store.root.exists()
    with execution_context(context):
        record_snapshot("before")
    prepared = inspect_recovery(store, context.run_id)
    assert (
        prepared.attempts[0].status == "Outcome Unknown" and prepared.blocks_execution
    )
    with (
        store.guard(context.run_id, workspace=context.workspace),
        execution_context(context),
    ):
        emit("phase_started", "running")
        assert inspect_recovery(store, context.run_id).attempts[0].status == "Active"
        assert not inspect_recovery(store, context.run_id).blocks_execution
    interrupted = inspect_recovery(store, context.run_id)
    assert (
        interrupted.attempts[0].status == "Interrupted" and interrupted.blocks_execution
    )
    assert "Outcome Unknown" in interrupted.attempts[0].message
    with execution_context(context):
        emit("phase_failed", "failed", error="execution_failed")
    ended = inspect_recovery(store, context.run_id)
    assert ended.attempts[0].status == "Failed" and not ended.blocks_execution
    next_context = replace(context, attempt_id=str(uuid4()))
    with execution_context(next_context):
        emit("phase_started", "running")
        emit("phase_finished", "awaiting_checkpoint")
    finished = inspect_recovery(store, context.run_id)
    assert [attempt.status for attempt in finished.attempts] == ["Finished", "Failed"]
    assert "does not assert" in finished.attempts[0].message


def test_unknown_lease_never_claims_interruption_or_success(recovery, monkeypatch):
    store, context = recovery
    with execution_context(context):
        emit("phase_started", "running")
    monkeypatch.setattr(store, "run_activity", lambda _: "unknown")
    recovered = inspect_recovery(store, context.run_id)
    assert (
        recovered.attempts[0].status == "Outcome Unknown" and recovered.blocks_execution
    )


def _kill_ready_process(code):
    process = subprocess.Popen(
        [sys.executable, "-c", code],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        ready, _, _ = select.select([process.stdout], [], [], 10)
        assert ready and process.stdout.readline().strip() == "READY"
    except BaseException:
        process.kill()
        process.communicate(timeout=5)
        raise
    return process


def _script_header(store, context):
    return "\n".join(
        [
            "from pathlib import Path",
            "import time",
            "from ai_agent_project.agent.execution_event_store import FileExecutionEventStore",
            "from ai_agent_project.agent.execution_events import ExecutionContext, execution_context, emit",
            "from ai_agent_project.agent.code_snapshot import record_snapshot",
            "from ai_agent_project.tools.file import FileTool",
            f"store = FileExecutionEventStore(Path({str(store.root)!r}))",
            f"context = ExecutionContext(store, {context.run_id!r}, 'PHASE-1', {context.attempt_id!r}, Path({str(context.workspace)!r}))",
        ]
    )


def test_sigkill_preserves_committed_snapshots_and_unknown_outcome(recovery):
    if os.name != "posix":
        pytest.skip("POSIX SIGKILL and pipe readiness")
    store, context = recovery
    code = (
        _script_header(store, context)
        + "\n"
        + """with store.guard(context.run_id, workspace=context.workspace), execution_context(context):
    record_snapshot('before')
    emit('phase_started', 'running')
    assert FileTool(context.workspace).execute({'operation':'write_file', 'path':'app.py', 'content':'print(42)\\n'}).success
    print('READY', flush=True)
    time.sleep(120)
"""
    )
    process = _kill_ready_process(code)
    try:
        assert inspect_recovery(store, context.run_id).attempts[0].status == "Active"
    finally:
        process.kill()
        process.communicate(timeout=5)
    assert process.returncode == -9
    fresh = FileExecutionEventStore(store.root)
    recovered = inspect_recovery(fresh, context.run_id)
    assert recovered.attempts[0].status == "Interrupted" and recovered.blocks_execution
    before = fresh.attempt_snapshot(context.run_id, context.attempt_id, baseline=True)
    after = fresh.attempt_snapshot(context.run_id, context.attempt_id, baseline=False)
    assert before and after and after.stage == "tool"
    assert "+print(42)" in compare_snapshots(before, after).changes[0].diff
    original = (context.workspace / "app.py").read_bytes()
    inspect_recovery(fresh, context.run_id)
    assert (context.workspace / "app.py").read_bytes() == original


def test_sigkill_during_snapshot_transaction_exposes_no_partial_record(recovery):
    if os.name != "posix":
        pytest.skip("POSIX SIGKILL and pipe readiness")
    store, context = recovery
    code = (
        _script_header(store, context)
        + "\n"
        + """original = store._insert_snapshot
def blocked(connection, snapshot):
    original(connection, snapshot)
    print('READY', flush=True)
    time.sleep(120)
store._insert_snapshot = blocked
with store.guard(context.run_id, workspace=context.workspace), execution_context(context):
    emit('phase_started', 'running')
    record_snapshot('after')
"""
    )
    process = _kill_ready_process(code)
    process.kill()
    process.communicate(timeout=5)
    fresh = FileExecutionEventStore(store.root)
    assert fresh.list_snapshots(context.run_id) == ()
    assert [event.kind for event in fresh.query(context.run_id)] == ["phase_started"]
    assert inspect_recovery(fresh, context.run_id).attempts[0].status == "Interrupted"
