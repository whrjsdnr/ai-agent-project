"""Real Tool recording, durable order, public content and concurrent guards."""

import os
import sqlite3
import subprocess
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from ai_agent_project.agent.execution_event_store import (
    ExecutionEventError,
    FileExecutionEventStore,
)
from ai_agent_project.agent.execution_events import (
    CURRENT_EXECUTION,
    ExecutionContext,
    PublicExecutionEvent,
    emit,
    execution_context,
)
from ai_agent_project.execution_privacy import MAX_LOG_CHARS
from ai_agent_project.tools.file import FileTool
from ai_agent_project.tools.shell import ShellTool


@pytest.fixture
def recording(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store = FileExecutionEventStore(tmp_path / "execution-events")
    context = ExecutionContext(
        store,
        str(uuid4()),
        "PHASE-1",
        str(uuid4()),
        workspace,
        ("synthetic-api-value", "synthetic-env-value"),
    )
    return store, context


def events(store, context):
    return store.query(context.run_id, limit=500)


def test_actual_file_and_shell_tools_generate_persisted_events(recording):
    store, context = recording
    with execution_context(context):
        result = FileTool(context.workspace).execute(
            {
                "operation": "write_file",
                "path": "app.py",
                "content": "print('private body not published')",
            }
        )
        assert result.success
        assert ShellTool(context.workspace).execute({"command": "uv --version"}).success
    all_records = events(store, context)
    recorded = [event for event in all_records if event.kind != "snapshot_saved"]
    assert [e.kind for e in recorded] == [
        "tool_started",
        "tool_completed",
        "file_observed",
        "tool_started",
        "tool_completed",
    ]
    assert (
        recorded[0].operation_id == recorded[1].operation_id == recorded[2].operation_id
    )
    assert recorded[2].change == "created" and recorded[2].attribution == "unattributed"
    assert recorded[-1].exit_code == 0 and "uv" in recorded[-1].stdout
    assert "private body not published" not in "".join(
        e.model_dump_json() for e in recorded
    )
    assert [e.sequence for e in all_records] == list(range(1, len(all_records) + 1))
    reopened = FileExecutionEventStore(store.root)
    assert reopened.query(context.run_id, after_sequence=3) == all_records[3:]
    assert reopened.latest(context.run_id) == all_records[-1]
    assert CURRENT_EXECUTION.get() is None


def test_modified_and_deleted_observations_have_no_causal_claim(recording, monkeypatch):
    store, context = recording
    tool = FileTool(context.workspace)
    with execution_context(context):
        tool.execute({"operation": "write_file", "path": "app.py", "content": "a"})
        tool.execute(
            {"operation": "write_file", "path": "app.py", "content": "changed"}
        )
        original_run = subprocess.run

        def external_delete(*args, **kwargs):
            (context.workspace / "app.py").unlink()
            return original_run(*args, **kwargs)

        monkeypatch.setattr(
            "ai_agent_project.tools.shell.subprocess.run", external_delete
        )
        ShellTool(context.workspace).execute({"command": "uv --version"})
    observed = [e for e in events(store, context) if e.kind == "file_observed"]
    assert [e.change for e in observed] == ["created", "modified", "deleted"]
    assert all(e.attribution == "unattributed" for e in observed)


def test_failure_timeout_and_safe_logs(recording, monkeypatch):
    store, context = recording
    outcomes = [
        subprocess.CompletedProcess(
            ["uv"],
            7,
            stdout="synthetic-api-value\nplain output\n" + "x" * 20_000,
            stderr=f"ENV_VALUE=synthetic-env-value\n{context.workspace}/app.py\n/etc/hidden-file",
        ),
        subprocess.TimeoutExpired(["uv", "--version"], 1),
    ]

    def run(*args, **kwargs):
        value = outcomes.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr("ai_agent_project.tools.shell.subprocess.run", run)
    with execution_context(context):
        assert (
            not ShellTool(context.workspace)
            .execute({"command": "uv --version"})
            .success
        )
        assert (
            not ShellTool(context.workspace)
            .execute({"command": "uv --version", "timeout_seconds": 1})
            .success
        )
    recorded = [
        event for event in events(store, context) if event.kind != "snapshot_saved"
    ]
    assert [e.kind for e in recorded] == [
        "tool_started",
        "tool_failed",
        "tool_started",
        "tool_failed",
    ]
    assert recorded[1].exit_code == 7 and "plain output" in recorded[1].stdout
    assert len(recorded[1].stdout) <= MAX_LOG_CHARS + 12
    assert "[truncated]" in recorded[1].stdout
    assert recorded[-1].status == "timeout" and recorded[-1].exit_code is None
    # Inspect raw durable rows, not just the presentation DTO.
    with sqlite3.connect(store.database) as connection:
        raw = str(connection.execute("SELECT content FROM events").fetchall())
    for hidden in [
        "synthetic-api-value",
        "synthetic-env-value",
        "/etc/hidden-file",
        str(context.workspace),
    ]:
        assert hidden not in raw


def test_private_transcript_output_is_withheld(recording, monkeypatch):
    store, context = recording
    monkeypatch.setattr(
        "ai_agent_project.tools.shell.subprocess.run",
        lambda *a, **k: subprocess.CompletedProcess(
            ["uv"],
            0,
            stdout='{"messages": ["PRIVATE_TRANSCRIPT_SENTINEL"], "provider_context": {}}',
            stderr="",
        ),
    )
    with execution_context(context):
        ShellTool(context.workspace).execute({"command": "uv --version"})
    assert (
        next(
            event for event in events(store, context) if event.kind == "tool_completed"
        ).stdout
        == "[REDACTED internal data]"
    )


@pytest.mark.parametrize(
    "path", ["../outside.py", "/tmp/outside.py", ".env", "credentials.py"]
)
def test_unsafe_paths_are_not_published(recording, path):
    store, context = recording
    with execution_context(context):
        FileTool(context.workspace).execute(
            {"operation": "write_file", "path": path, "content": "private"}
        )
    assert not any(e.path for e in events(store, context))
    assert "private" not in "".join(e.stdout for e in events(store, context))


def test_symlink_escape_does_not_publish_external_content(recording, tmp_path):
    store, context = recording
    outside = tmp_path / "outside.py"
    outside.write_text("external-private")
    (context.workspace / "alias.py").symlink_to(outside)
    with execution_context(context):
        result = FileTool(context.workspace).execute(
            {"operation": "read_file", "path": "alias.py"}
        )
    assert not result.success
    assert [e.kind for e in events(store, context)] == ["tool_started", "tool_failed"]
    assert all(
        not e.stdout and not e.stderr and not e.path for e in events(store, context)
    )


def test_invalid_query_and_event_store_symlink_are_rejected(recording, tmp_path):
    store, context = recording
    assert store.query(context.run_id) == () and not store.root.exists()
    with pytest.raises(ExecutionEventError):
        store.query("../run")
    with pytest.raises(ExecutionEventError):
        store.query(context.run_id, after_sequence=-1)
    outside = tmp_path / "outside"
    outside.mkdir()
    store.root.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ExecutionEventError):
        store.query(context.run_id)
    with pytest.raises(ExecutionEventError):
        store.append(
            PublicExecutionEvent(
                run_id=context.run_id,
                phase_id="PHASE-1",
                attempt_id=context.attempt_id,
                kind="phase_started",
                status="running",
            )
        )
    assert list(outside.iterdir()) == []


def test_atomic_sequence_with_multiple_writers(recording):
    store, context = recording

    def append(_):
        return store.append(
            PublicExecutionEvent(
                run_id=context.run_id,
                phase_id="PHASE-1",
                attempt_id=context.attempt_id,
                kind="agent_started",
                status="running",
            )
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(append, range(20)))
    assert [e.sequence for e in events(store, context)] == list(range(1, 21))


def test_nonblocking_run_and_shared_workspace_guards(recording):
    store, context = recording
    second = FileExecutionEventStore(store.root)
    with store.guard(context.run_id, workspace=context.workspace):
        for run_id in [context.run_id, str(uuid4())]:
            with (
                pytest.raises(ExecutionEventError),
                second.guard(run_id, workspace=context.workspace),
            ):
                pytest.fail("Concurrent mutation accepted")
    with second.guard(context.run_id, workspace=context.workspace):
        pass


def test_committed_event_survives_abrupt_process_exit(recording):
    store, context = recording
    code = "\n".join(
        [
            "import os",
            "from pathlib import Path",
            "from ai_agent_project.agent.execution_event_store import FileExecutionEventStore",
            "from ai_agent_project.agent.execution_events import PublicExecutionEvent",
            f"store = FileExecutionEventStore(Path({str(store.root)!r}))",
            f"store.append(PublicExecutionEvent(run_id={context.run_id!r}, phase_id='PHASE-1', attempt_id={context.attempt_id!r}, kind='phase_started', status='running'))",
            "os._exit(23)",
        ]
    )
    completed = subprocess.run(
        [os.sys.executable, "-c", code], check=False, capture_output=True
    )
    assert completed.returncode == 23
    assert store.latest(context.run_id).kind == "phase_started"


def test_real_process_timeout_is_recorded(recording, tmp_path, monkeypatch):
    if os.name != "posix":
        pytest.skip("POSIX test executable")
    store, context = recording
    binaries = tmp_path / "bin"
    binaries.mkdir()
    executable = binaries / "uv"
    executable.write_text("#!/bin/sh\nexec /bin/sleep 3\n")
    executable.chmod(0o700)
    monkeypatch.setenv("PATH", str(binaries) + os.pathsep + os.environ.get("PATH", ""))
    with execution_context(context):
        result = ShellTool(context.workspace).execute(
            {"command": "uv --version", "timeout_seconds": 1}
        )
    assert not result.success
    failed = next(
        event for event in events(store, context) if event.kind == "tool_failed"
    )
    assert failed.status == "timeout"
    assert failed.exit_code is None


def test_private_event_fields_are_rejected(recording):
    from pydantic import ValidationError

    store, context = recording
    with pytest.raises(ValidationError):
        PublicExecutionEvent(
            run_id=context.run_id,
            phase_id="PHASE-1",
            attempt_id=context.attempt_id,
            kind="agent_started",
            status="running",
            messages=["private"],
        )
    assert not store.database.exists()


def test_masking_happens_before_log_truncation_and_handles_multiline(recording):
    store, context = recording
    secret = "synthetic-api-value"
    with execution_context(context):
        emit(
            "tool_completed",
            "completed",
            tool="shell",
            stdout="x" * (MAX_LOG_CHARS - 5) + secret,
        )
        emit(
            "tool_completed",
            "completed",
            tool="shell",
            stdout='{"api_key":\n"unconfigured-private-value"}',
        )
    recorded = events(store, context)
    assert secret[:5] not in recorded[0].stdout
    assert "unconfigured-private-value" not in recorded[1].stdout
    assert "multiline" in recorded[1].stdout


def test_short_sensitive_environment_values_are_masked(recording, monkeypatch):
    from dataclasses import replace

    from ai_agent_project.agent.execution_runtime import runtime_secrets

    store, context = recording
    monkeypatch.setenv("SYNTHETIC_SECRET", "AB")
    context = replace(context, secrets=runtime_secrets())
    with execution_context(context):
        emit("tool_completed", "completed", tool="shell", stdout="AB")
    assert store.latest(context.run_id).stdout == "[REDACTED]"
