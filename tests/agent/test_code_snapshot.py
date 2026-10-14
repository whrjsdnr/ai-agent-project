"""Actual filesystem snapshots, bounded storage, exact diffs and TOCTOU denial."""

import os
import sqlite3
from contextlib import contextmanager
from dataclasses import replace
from uuid import uuid4

import pytest

from ai_agent_project.agent.code_snapshot import (
    MAX_FILE_BYTES,
    SnapshotError,
    capture_snapshot,
    compare_snapshots,
    record_snapshot,
)
from ai_agent_project.agent.execution_event_store import (
    ExecutionEventError,
    FileExecutionEventStore,
)
from ai_agent_project.agent.execution_events import ExecutionContext, execution_context
from ai_agent_project.tools.file import FileTool
from ai_agent_project.tools.shell import ShellTool


@pytest.fixture
def snapshots(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    store = FileExecutionEventStore(tmp_path / "execution-events")
    context = ExecutionContext(
        store, str(uuid4()), "PHASE-1", str(uuid4()), root, ("synthetic-private-value",)
    )
    return store, context


def save(store, context, stage):
    with execution_context(context):
        return store.save_snapshot(capture_snapshot(context, stage))


def test_real_file_creation_repeated_modification_and_deletion(snapshots):
    store, context = snapshots
    (context.workspace / "app.py").write_text("print('original')\n")
    (context.workspace / "remove.py").write_text("print('remove')\n")
    baseline = save(store, context, "before")
    with execution_context(context):
        tool = FileTool(context.workspace)
        assert tool.execute(
            {
                "operation": "write_file",
                "path": "created.py",
                "content": "print('created')\n",
            }
        ).success
        assert tool.execute(
            {"operation": "write_file", "path": "app.py", "content": "print('first')\n"}
        ).success
        assert tool.execute(
            {
                "operation": "write_file",
                "path": "app.py",
                "content": "print('second')\n",
            }
        ).success
        assert tool.execute({"operation": "delete_file", "path": "remove.py"}).success
        record_snapshot("after")
    latest = store.attempt_snapshot(context.run_id, context.attempt_id, baseline=False)
    view = compare_snapshots(baseline, latest)
    changes = {change.path: change for change in view.changes}
    assert {path: change.status for path, change in changes.items()} == {
        "app.py": "Modified",
        "created.py": "Created",
        "remove.py": "Deleted",
    }
    assert (
        "-print('original')" in changes["app.py"].diff
        and "+print('second')" in changes["app.py"].diff
    )
    assert all(change.attribution == "Observed Change" for change in changes.values())
    history = list(reversed(store.list_snapshots(context.run_id)))
    assert [item.stage for item in history] == [
        "before",
        "tool",
        "tool",
        "tool",
        "tool",
        "after",
    ]
    previous = store.get_snapshot(context.run_id, history[2].snapshot_id)
    following = store.get_snapshot(context.run_id, history[3].snapshot_id)
    step = compare_snapshots(previous, following).changes[0]
    assert "-print('first')" in step.diff and "+print('second')" in step.diff
    fresh = FileExecutionEventStore(store.root)
    assert fresh.get_snapshot(context.run_id, baseline.snapshot_id) == baseline
    assert (
        fresh.attempt_snapshot(context.run_id, context.attempt_id, baseline=False)
        == latest
    )


def test_shell_process_changes_are_compared_after_failure(
    snapshots, tmp_path, monkeypatch
):
    if os.name != "posix":
        pytest.skip("POSIX test executable")
    store, context = snapshots
    baseline = save(store, context, "before")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    executable = binaries / "uv"
    executable.write_text(
        "#!/bin/sh\nprintf 'created by process\\n' > process.txt\nexit 7\n"
    )
    executable.chmod(0o700)
    monkeypatch.setenv("PATH", str(binaries) + os.pathsep + os.environ.get("PATH", ""))
    with execution_context(context):
        result = ShellTool(context.workspace).execute({"command": "uv --version"})
    assert not result.success and result.data["exit_code"] == 7
    after = store.attempt_snapshot(context.run_id, context.attempt_id, baseline=False)
    change = compare_snapshots(baseline, after).changes[0]
    assert change.path == "process.txt" and change.status == "Created"
    assert "+created by process" in change.diff
    assert change.attribution == "Observed Change"


def test_timeout_retains_actual_file_change(snapshots, tmp_path, monkeypatch):
    if os.name != "posix":
        pytest.skip("POSIX test executable")
    store, context = snapshots
    baseline = save(store, context, "before")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    executable = binaries / "uv"
    executable.write_text(
        "#!/bin/sh\nprintf 'changed before timeout\\n' > timeout.txt\nexec /bin/sleep 3\n"
    )
    executable.chmod(0o700)
    monkeypatch.setenv("PATH", str(binaries) + os.pathsep + os.environ.get("PATH", ""))
    with execution_context(context):
        result = ShellTool(context.workspace).execute(
            {"command": "uv --version", "timeout_seconds": 1}
        )
    assert not result.success
    after = store.attempt_snapshot(context.run_id, context.attempt_id, baseline=False)
    assert (
        "+changed before timeout" in compare_snapshots(baseline, after).changes[0].diff
    )
    assert any(event.status == "timeout" for event in store.query(context.run_id))


def test_private_files_and_content_never_enter_storage(snapshots):
    store, context = snapshots
    root = context.workspace
    for name in (".env", "api_key.txt", "key.pem", "cert.crt"):
        (root / name).write_text("synthetic-private-value")
    (root / "settings").mkdir()
    (root / "settings" / "llm.json").write_text("synthetic-private-value")
    for name, content in {
        "code.py": 'print("synthetic-private-value")',
        "log.json": '{"messages": ["PRIVATE_DIALOG"], "provider_context": {}}',
        "certificate.txt": "-----BEGIN CERTIFICATE-----\nPRIVATE_CERTIFICATE\n-----END CERTIFICATE-----",
    }.items():
        (root / name).write_text(content)
    baseline = save(store, context, "before")
    assert {file.path for file in baseline.files} == {
        "code.py",
        "log.json",
        "certificate.txt",
    }
    assert all(
        file.content is None and file.content_state == "sensitive_content"
        for file in baseline.files
    )
    with sqlite3.connect(store.database) as connection:
        raw = str(connection.execute("SELECT content FROM snapshots").fetchall())
    for hidden in (
        "synthetic-private-value",
        "PRIVATE_DIALOG",
        "PRIVATE_CERTIFICATE",
        "provider_context",
    ):
        assert hidden not in raw


def test_binary_and_large_files_store_only_metadata(snapshots):
    store, context = snapshots
    (context.workspace / "image.png").write_bytes(b"BINARY_SENTINEL")
    (context.workspace / "large.py").write_text("x" * (MAX_FILE_BYTES + 1))
    (context.workspace / "nul.py").write_bytes(b"binary\x00payload")
    baseline = save(store, context, "before")
    assert {file.path: file.content_state for file in baseline.files} == {
        "image.png": "binary",
        "large.py": "too_large",
        "nul.py": "binary",
    }
    assert all(file.content is None for file in baseline.files)
    (context.workspace / "image.png").write_bytes(b"CHANGED_BINARY_SENTINEL")
    after = save(store, context, "after")
    change = compare_snapshots(baseline, after).changes[0]
    assert change.status == "Modified" and not change.diff and "binary" in change.reason
    assert change.before_size == len(b"BINARY_SENTINEL")
    assert change.after_size == len(b"CHANGED_BINARY_SENTINEL")
    assert (
        change.before_modified_ns is not None and change.after_modified_ns is not None
    )
    assert "SENTINEL" not in after.model_dump_json()


def test_limits_do_not_turn_unknown_absence_into_deletion(snapshots, monkeypatch):
    import ai_agent_project.agent.code_snapshot as module

    store, context = snapshots
    (context.workspace / "a.py").write_text("a" * 40)
    (context.workspace / "b.py").write_text("b" * 40)
    baseline = save(store, context, "before")
    monkeypatch.setattr(module, "MAX_TOTAL_BYTES", 60)
    limited = capture_snapshot(context, "after")
    assert [file.content_state for file in limited.files] == ["text", "total_limit"]
    monkeypatch.setattr(module, "MAX_SNAPSHOT_FILES", 1)
    after = save(store, context, "after")
    assert not after.complete and after.reason == "inventory_limit"
    observed = compare_snapshots(baseline, after).changes[0]
    assert (
        observed.path == "b.py" and observed.status == "Observed" and not observed.diff
    )


@pytest.mark.parametrize(
    "path",
    [
        "../outside.py",
        "/tmp/outside.py",
        r"..\outside.py",
        "settings/llm.json",
        ".env",
        "cert.crt",
    ],
)
def test_storage_revalidates_paths_and_refuses_forged_snapshot(snapshots, path):
    store, context = snapshots
    (context.workspace / "app.py").write_text("print('public')")
    snapshot = capture_snapshot(context, "before")
    forged = snapshot.model_copy(
        update={"files": (snapshot.files[0].model_copy(update={"path": path}),)}
    )
    with execution_context(context), pytest.raises(SnapshotError):
        store.save_snapshot(forged)
    assert not store.database.exists()


def test_symlink_hardlink_and_root_alias_do_not_read_external_data(snapshots, tmp_path):
    store, context = snapshots
    outside = tmp_path / "outside.py"
    outside.write_text("EXTERNAL_DATA_SENTINEL")
    (context.workspace / "alias.py").symlink_to(outside)
    os.link(outside, context.workspace / "hard.py")
    baseline = save(store, context, "before")
    assert not baseline.complete
    assert len(baseline.files) == 1 and baseline.files[0].content_state == "hardlink"
    assert baseline.files[0].content is None
    assert "EXTERNAL_DATA_SENTINEL" not in baseline.model_dump_json()
    alias = tmp_path / "root-alias"
    alias.symlink_to(context.workspace, target_is_directory=True)
    with pytest.raises(OSError):
        capture_snapshot(replace(context, workspace=alias), "after")


def test_file_replacement_with_symlink_is_blocked(snapshots, tmp_path, monkeypatch):
    _, context = snapshots
    file = context.workspace / "app.py"
    file.write_text("inside")
    outside = tmp_path / "outside.py"
    outside.write_text("OUTSIDE_REPLACEMENT_SENTINEL")
    original = os.open
    swapped = False

    def attack(path, flags, *args, **kwargs):
        nonlocal swapped
        if path == "app.py" and not swapped:
            file.rename(context.workspace / "original.py")
            file.symlink_to(outside)
            swapped = True
        return original(path, flags, *args, **kwargs)

    monkeypatch.setattr("ai_agent_project.agent.code_snapshot.os.open", attack)
    snapshot = capture_snapshot(context, "before")
    assert swapped and not snapshot.complete
    assert "OUTSIDE_REPLACEMENT_SENTINEL" not in snapshot.model_dump_json()
    assert not any(file.content for file in snapshot.files)


def test_parent_directory_swap_is_blocked(snapshots, tmp_path, monkeypatch):
    _, context = snapshots
    nested = context.workspace / "src"
    nested.mkdir()
    (nested / "app.py").write_text("inside")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "app.py").write_text("OUTSIDE_PARENT_SENTINEL")
    original = os.open
    swapped = False

    def attack(path, flags, *args, **kwargs):
        nonlocal swapped
        if path == "src" and not swapped:
            nested.rename(context.workspace / "original")
            nested.symlink_to(outside, target_is_directory=True)
            swapped = True
        return original(path, flags, *args, **kwargs)

    monkeypatch.setattr("ai_agent_project.workspace_io.os.open", attack)
    snapshot = capture_snapshot(context, "before")
    assert swapped and not snapshot.complete and snapshot.files == ()


def test_concurrent_in_place_write_discards_content(snapshots, monkeypatch):
    _, context = snapshots
    path = context.workspace / "app.py"
    path.write_text("original content")
    fdopen = os.fdopen

    @contextmanager
    def attack(descriptor, mode):
        with fdopen(descriptor, mode) as stream:

            class ReadThenWrite:
                def read(self, size):
                    data = stream.read(size)
                    path.write_text("replacement content with different length")
                    return data

            yield ReadThenWrite()

    monkeypatch.setattr("ai_agent_project.agent.code_snapshot.os.fdopen", attack)
    snapshot = capture_snapshot(context, "before")
    assert not snapshot.complete and snapshot.files[0].content is None
    assert snapshot.files[0].content_state == "changed_during_capture"


def test_atomic_failure_leaves_no_snapshot_or_snapshot_saved_event(
    snapshots, monkeypatch
):
    store, context = snapshots
    original = store._insert_snapshot

    def fail(connection, snapshot):
        original(connection, snapshot)
        raise sqlite3.OperationalError("synthetic storage failure")

    monkeypatch.setattr(store, "_insert_snapshot", fail)
    with execution_context(context), pytest.raises(ExecutionEventError):
        store.save_snapshot(capture_snapshot(context, "before"))
    assert store.list_snapshots(context.run_id) == ()
    assert store.query(context.run_id) == ()


def test_serialized_size_limit_prevents_any_content_commit(snapshots, monkeypatch):
    import ai_agent_project.agent.code_snapshot as module

    store, context = snapshots
    monkeypatch.setattr(module, "MAX_SERIALIZED_BYTES", 100)
    with execution_context(context), pytest.raises(SnapshotError):
        store.save_snapshot(capture_snapshot(context, "before"))
    assert not store.database.exists()


def test_no_newline_diff_and_historical_unavailability(snapshots):
    store, context = snapshots
    (context.workspace / "app.py").write_text("old")
    before = save(store, context, "before")
    (context.workspace / "app.py").write_text("new")
    after = save(store, context, "after")
    diff = compare_snapshots(before, after).changes[0].diff
    assert (
        "-old\n\\ No newline at end of file\n+new\n\\ No newline at end of file\n"
        in diff
    )
    assert "Historical Diff Unavailable" in compare_snapshots(None, after).message


def test_unverified_platform_is_explicit_and_reads_no_content(snapshots, monkeypatch):
    import ai_agent_project.agent.code_snapshot as module

    _, context = snapshots
    monkeypatch.setattr(module, "snapshot_platform_verified", lambda: False)
    snapshot = capture_snapshot(context, "before")
    assert (
        snapshot.reason == "platform_unverified"
        and not snapshot.complete
        and not snapshot.files
    )


def test_change_then_restore_keeps_step_history(snapshots):
    store, context = snapshots
    (context.workspace / "app.py").write_text("original\n")
    before = save(store, context, "before")
    with execution_context(context):
        FileTool(context.workspace).execute(
            {"operation": "write_file", "path": "app.py", "content": "temporary\n"}
        )
        FileTool(context.workspace).execute(
            {"operation": "write_file", "path": "app.py", "content": "original\n"}
        )
        record_snapshot("after")
    after = store.attempt_snapshot(context.run_id, context.attempt_id, baseline=False)
    assert compare_snapshots(before, after).changes == ()
    steps = [
        item
        for item in reversed(store.list_snapshots(context.run_id))
        if item.stage == "tool"
    ]
    first = store.get_snapshot(context.run_id, steps[0].snapshot_id)
    second = store.get_snapshot(context.run_id, steps[1].snapshot_id)
    assert "+temporary" in compare_snapshots(before, first).changes[0].diff
    assert "-temporary" in compare_snapshots(first, second).changes[0].diff


def test_reparse_metadata_is_excluded_without_opening_file(snapshots, monkeypatch):
    from types import SimpleNamespace

    _, context = snapshots
    (context.workspace / "app.py").write_text("reparse content must not be read")
    scandir = os.scandir

    @contextmanager
    def reparse(directory):
        with scandir(directory) as entries:
            converted = []
            for entry in entries:
                metadata = entry.stat(follow_symlinks=False)
                converted.append(
                    SimpleNamespace(
                        name=entry.name,
                        stat=lambda metadata=metadata, **_kwargs: SimpleNamespace(
                            st_mode=metadata.st_mode, st_file_attributes=0x400
                        ),
                    )
                )
            yield iter(converted)

    monkeypatch.setattr("ai_agent_project.agent.code_snapshot.os.scandir", reparse)
    snapshot = capture_snapshot(context, "before")
    assert not snapshot.files and snapshot.reason == "unsafe_path"


def test_store_rejects_private_text_even_if_capture_is_bypassed(snapshots):
    store, context = snapshots
    (context.workspace / "app.py").write_text("public\n")
    original = capture_snapshot(context, "before")
    forged = original.model_copy(
        update={
            "files": (
                original.files[0].model_copy(
                    update={"content": "synthetic-private-value"}
                ),
            )
        }
    )
    with execution_context(context), pytest.raises(SnapshotError):
        store.save_snapshot(forged)
    assert not store.database.exists()


@pytest.mark.parametrize("operation", ["read_file", "write_file", "delete_file"])
def test_real_file_tool_parent_replacement_cannot_access_external_file(
    snapshots, tmp_path, monkeypatch, operation
):
    _, context = snapshots
    nested = context.workspace / "src"
    nested.mkdir()
    (nested / "app.py").write_text("inside")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "app.py").write_text("EXTERNAL_TOOL_SENTINEL")
    tool = FileTool(context.workspace)
    original = tool._resolve_workspace_path

    def replaced(path):
        resolved = original(path)
        nested.rename(context.workspace / "original")
        nested.symlink_to(outside, target_is_directory=True)
        return resolved

    monkeypatch.setattr(tool, "_resolve_workspace_path", replaced)
    result = tool.execute(
        {
            "operation": operation,
            "path": "src/app.py",
            "content": "attempted external write",
        }
    )
    assert not result.success
    assert "EXTERNAL_TOOL_SENTINEL" not in str(result)
    assert (outside / "app.py").read_text() == "EXTERNAL_TOOL_SENTINEL"


def test_snapshot_binding_and_control_character_paths_are_revalidated(snapshots):
    store, context = snapshots
    (context.workspace / "app.py").write_text("public\n")
    snapshot = capture_snapshot(context, "before")
    with execution_context(context), pytest.raises(ExecutionEventError):
        store.save_snapshot(snapshot.model_copy(update={"phase_id": "OTHER-PHASE"}))
    forged = snapshot.model_copy(
        update={
            "files": (
                snapshot.files[0].model_copy(update={"path": "fake\n+++ other.py"}),
            )
        }
    )
    with execution_context(context), pytest.raises(SnapshotError):
        store.save_snapshot(forged)
    assert not store.database.exists()


def test_directory_enumeration_budget_is_global(snapshots, monkeypatch):
    import ai_agent_project.agent.code_snapshot as module

    _, context = snapshots
    for index in range(5):
        directory = context.workspace / f"dir{index}"
        directory.mkdir()
        (directory / "app.py").write_text("public\n")
    monkeypatch.setattr(module, "MAX_VISITED_ENTRIES", 5)
    snapshot = capture_snapshot(context, "before")
    assert not snapshot.complete and snapshot.reason == "inventory_limit"
    assert not snapshot.files
