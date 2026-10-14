"""Read-only Diff and interrupted state through the existing Desktop Facade."""

import importlib.util
import sqlite3
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from PySide6.QtWidgets import QPushButton

from ai_agent_project.agent.code_snapshot import record_snapshot
from ai_agent_project.agent.execution_events import (
    ExecutionContext,
    emit,
    execution_context,
)
from ai_agent_project.agent.research import WorkMode
from ai_agent_project.desktop.errors import DesktopError
from ai_agent_project.desktop_app.application import build_desktop_application
from ai_agent_project.desktop_app.code_changes import CodeChangesPanel
from ai_agent_project.desktop_app.developer_workspace import DeveloperWorkspacePanel
from ai_agent_project.desktop_app.execution_timeline import ExecutionTimelinePanel
from ai_agent_project.desktop_app.window import MainWindow
from ai_agent_project.tools.file import FileTool

_spec = importlib.util.spec_from_file_location(
    "snapshot_observable_seed", Path(__file__).with_name("test_execution_timeline.py")
)
_seed = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _seed
_spec.loader.exec_module(_seed)
observable = _seed.observable
wait_until = _seed.wait_until


def test_approved_phase_diff_ui_history_and_restart(qapp, observable):
    setup, pid, _, _, _ = observable
    assert setup.desktop.list_developer_snapshots(pid) == ()
    assert (
        "Historical Diff Unavailable"
        in setup.desktop.get_developer_code_changes(pid).message
    )
    with pytest.raises(DesktopError):
        setup.desktop.continue_developer(pid)
    assert setup.desktop.list_developer_snapshots(pid) == ()
    setup.desktop.approve_developer_plan(pid)
    setup.desktop.continue_developer(pid)
    snapshots = setup.desktop.list_developer_snapshots(pid)
    assert snapshots[0].stage == "after" and snapshots[-1].stage == "before"
    changes = setup.desktop.get_developer_code_changes(pid)
    assert changes.changes[0].path == "src/app.py"
    assert changes.changes[0].status == "Created"
    assert "+print('actual saved code')" in changes.changes[0].diff
    assert changes.changes[0].attribution == "Observed Change"
    assert setup.desktop.get_developer_recovery(pid).attempts[0].status == "Finished"
    fresh = build_desktop_application(setup.root, setup.root)
    assert fresh.get_developer_code_changes(pid) == changes
    window = MainWindow(fresh)
    window.select_project(pid)
    window.navigate("Developer")
    panel = window.pages["Developer"].findChild(CodeChangesPanel)
    assert panel.diff.isReadOnly() and panel.files.topLevelItemCount() == 1
    assert "+print('actual saved code')" in panel.diff.toPlainText()
    assert "관측된 변경" in panel.diff.toPlainText()
    assert "종료됨" in panel.recovery.text()
    assert window.pages["Developer"].findChild(ExecutionTimelinePanel)
    assert window.pages["Developer"].findChild(DeveloperWorkspacePanel)
    assert panel.snapshots.count() == len(snapshots)
    panel.snapshots.setCurrentIndex(panel.snapshots.count() - 1)
    assert "과거 변경 비교 불가" in panel.status.text()
    window.close()


def test_cross_run_snapshot_queries_and_researcher_reads_are_denied(observable):
    setup, pid, _, _, _ = observable
    setup.desktop.approve_developer_plan(pid)
    setup.desktop.continue_developer(pid)
    history = setup.desktop.list_developer_snapshots(pid)
    other = setup.ids[WorkMode.HYBRID]
    with pytest.raises(DesktopError):
        setup.desktop.get_developer_code_changes(
            other, after_snapshot_id=history[0].snapshot_id
        )
    with pytest.raises(DesktopError):
        setup.desktop.get_developer_code_changes(
            other,
            after_snapshot_id=history[0].snapshot_id,
            before_snapshot_id=history[-1].snapshot_id,
        )
    for command in (
        setup.desktop.list_developer_snapshots,
        setup.desktop.get_developer_code_changes,
        setup.desktop.get_developer_recovery,
    ):
        with pytest.raises(DesktopError):
            command(setup.ids[WorkMode.RESEARCHER])
    with pytest.raises(DesktopError):
        setup.desktop.get_developer_code_changes(pid, after_snapshot_id="../snapshot")


def test_interrupted_attempt_is_read_only_and_never_reexecuted(qapp, observable):
    setup, pid, rid, store, client = observable
    setup.desktop.approve_developer_plan(pid)
    context = ExecutionContext(store, rid, "PHASE-1", str(uuid4()), setup.root)
    with execution_context(context):
        record_snapshot("before")
        emit("phase_started", "running")
        FileTool(setup.root).execute(
            {
                "operation": "write_file",
                "path": "src/app.py",
                "content": "print('partial change')\n",
            }
        )
    client.complete.reset_mock()
    before = (setup.root / "src" / "app.py").read_bytes()
    recovered = setup.desktop.get_developer_recovery(pid)
    assert recovered.blocks_execution and recovered.attempts[0].status == "Interrupted"
    with pytest.raises(DesktopError, match="interrupted"):
        setup.desktop.continue_developer(pid)
    fresh = build_desktop_application(setup.root, setup.root)
    assert fresh.get_developer_recovery(pid).attempts[0].status == "Interrupted"
    window = MainWindow(fresh)
    window.select_project(pid)
    window.navigate("Developer")
    panel = window.pages["Developer"].findChild(CodeChangesPanel)
    assert (
        "실행 중단" in panel.recovery.text()
        and "결과를 확인할 수 없습니다" in panel.recovery.text()
    )
    assert "+print('partial change')" in panel.diff.toPlainText()
    assert fresh.get_project_view(pid).developer.status == "ready"
    assert (setup.root / "src" / "app.py").read_bytes() == before
    client.complete.assert_not_called()
    window.close()


def test_baseline_storage_failure_blocks_agent_and_leaves_no_partial_snapshot(
    observable, monkeypatch
):
    setup, pid, _, store, client = observable
    setup.desktop.approve_developer_plan(pid)
    original = store._insert_snapshot

    def fail(connection, snapshot):
        original(connection, snapshot)
        raise sqlite3.OperationalError("synthetic failure during baseline save")

    monkeypatch.setattr(store, "_insert_snapshot", fail)
    with pytest.raises(DesktopError):
        setup.desktop.continue_developer(pid)
    client.complete.assert_not_called()
    assert not (setup.root / "src" / "app.py").exists()
    assert setup.desktop.list_developer_snapshots(pid) == ()
    assert not any(
        event.kind == "snapshot_saved"
        for event in setup.desktop.get_developer_events(pid)
    )
    assert setup.desktop.get_developer_last_event(pid).kind == "snapshot_failed"


def test_legacy_run_and_live_diff_reads_do_not_mutate_workflow(qapp, observable):
    setup, pid, _, _, client = observable
    before = setup.desktop.get_project_view(pid)
    window = MainWindow(setup.desktop)
    window.select_project(pid)
    window.navigate("Developer")
    panel = window.pages["Developer"].findChild(CodeChangesPanel)
    panel.refresh()
    assert "과거 변경 비교 불가" in panel.status.text()
    assert setup.desktop.get_project_view(pid) == before
    client.complete.assert_not_called()
    window.close()


def test_previous_comparison_and_failed_execution_changes(observable):
    from ai_agent_project.agent.checkpoint import CheckpointDecision
    from ai_agent_project.agent.state import ToolCall
    from ai_agent_project.llm.base import LLMResponse

    setup, pid, _, _, client = observable
    setup.desktop.approve_developer_plan(pid)
    setup.desktop.continue_developer(pid)
    setup.desktop.decide_developer_checkpoint(pid, CheckpointDecision.REQUEST_CHANGES)
    responses = [
        LLMResponse(
            tool_call=ToolCall(
                name="file",
                arguments={
                    "operation": "write_file",
                    "path": "src/app.py",
                    "content": "print('changed before failure')\n",
                },
            )
        ),
        RuntimeError("private failure details"),
    ]
    client.complete.side_effect = responses
    setup.desktop.continue_developer(pid)
    diff = setup.desktop.get_developer_code_changes(pid)
    assert "changed before failure" in diff.changes[0].diff
    assert "private failure details" not in str(diff)
    assert (
        len({item.attempt_id for item in setup.desktop.list_developer_snapshots(pid)})
        == 2
    )
    latest = setup.desktop.list_developer_snapshots(pid)[0]
    previous = setup.desktop.get_developer_code_changes(
        pid, after_snapshot_id=latest.snapshot_id, comparison="previous"
    )
    assert (
        previous.changes == ()
    )  # The final snapshot retains the last confirmed tool state.
    assert setup.desktop.get_project_view(pid).developer.status == "awaiting_checkpoint"


def test_diff_accessible_during_execution_and_controls_stay_read_only(qapp, observable):
    from threading import Event

    setup, pid, _, _, client = observable
    responses = list(client.complete.side_effect)
    waiting, release = Event(), Event()
    count = 0

    def complete(*args):
        nonlocal count
        index = count
        count += 1
        if index == 1:
            waiting.set()
            assert release.wait(8)
        return responses[index]

    client.complete.side_effect = complete
    setup.desktop.approve_developer_plan(pid)
    window = MainWindow(setup.desktop)
    window.select_project(pid)
    window.navigate("Developer")
    window.show()
    try:
        window.submit(lambda: setup.desktop.continue_developer(pid))
        wait_until(qapp, waiting.is_set)
        panel = window.pages["Developer"].findChild(CodeChangesPanel)
        wait_until(qapp, lambda: "actual saved code" in panel.diff.toPlainText())
        assert window.busy and panel.isEnabled() and panel.diff.isReadOnly()
        assert panel.snapshots.isEnabled() and panel.comparison.isEnabled()
        assert "실행 중" in panel.recovery.text()
        assert (
            not window.pages["Developer"]
            .findChild(QPushButton, "continue_developer")
            .isEnabled()
        )
    finally:
        release.set()
        wait_until(qapp, lambda: not window.busy)
        window.close()
