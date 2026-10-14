"""Live UI reads persisted evidence before an approved phase returns."""

from threading import Event
from time import monotonic
from unittest.mock import Mock

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPushButton

from ai_agent_project.agent.checkpoint import PhaseCheckpointService, ProgressReporter
from ai_agent_project.agent.execution_event_store import FileExecutionEventStore
from ai_agent_project.agent.phase_execution import PhaseExecutionService
from ai_agent_project.agent.plan_revision import PlanRevisionState
from ai_agent_project.agent.project_execution import ProjectExecutionService
from ai_agent_project.agent.research import WorkMode
from ai_agent_project.agent.service import AgentService
from ai_agent_project.agent.state import ToolCall
from ai_agent_project.agent.workspace_acceptance import WorkspaceAcceptanceValidator
from ai_agent_project.desktop.errors import DesktopError
from ai_agent_project.desktop_app.application import build_desktop_application
from ai_agent_project.desktop_app.developer_workspace import DeveloperWorkspacePanel
from ai_agent_project.desktop_app.execution_timeline import ExecutionTimelinePanel
from ai_agent_project.desktop_app.window import MainWindow
from ai_agent_project.llm.base import LLMResponse
from ai_agent_project.tools.file import FileTool
from ai_agent_project.tools.registry import ToolRegistry
from ai_agent_project.tools.shell import ShellTool


@pytest.fixture
def observable(setup, monkeypatch):
    pid = setup.ids[WorkMode.DEVELOPER]
    rid = setup.desktop.get_project_view(pid).developer.run_id
    run = setup.developers.get(rid)
    task = run.implementation_plan.tasks[0].model_copy(
        update={"files_to_modify": ["src/app.py"]}
    )
    plan = run.implementation_plan.model_copy(
        update={"tasks": [task], "validation_commands": ["uv --version"]}
    )
    project_plan = run.project_plan.model_copy(update={"implementation_plan": plan})
    run = run.model_copy(
        update={
            "implementation_plan": plan,
            "project_plan": project_plan,
            "plan_revision_state": PlanRevisionState.from_plan(project_plan),
        }
    )
    setup.developers.replace(rid, run)
    store = FileExecutionEventStore(setup.root / "execution-events")
    registry = ToolRegistry()
    registry.register(FileTool(setup.root))
    registry.register(ShellTool(setup.root))
    client = Mock()
    client.complete.side_effect = [
        LLMResponse(
            tool_call=ToolCall(
                name="file",
                arguments={
                    "operation": "write_file",
                    "path": "src/app.py",
                    "content": "print('actual saved code')\n",
                },
            )
        ),
        LLMResponse(
            tool_call=ToolCall(name="shell", arguments={"command": "uv --version"})
        ),
        LLMResponse(final_answer="PRIVATE_FINAL_ANSWER; imaginary.py created"),
    ]
    phase = PhaseExecutionService(
        AgentService(client, registry),
        WorkspaceAcceptanceValidator(setup.root),
        max_repair_attempts=0,
    )
    application = setup.desktop._actions._developer_plans
    monkeypatch.setattr(application, "_events", store)
    monkeypatch.setattr(
        application,
        "_project_execution_service",
        ProjectExecutionService(phase, ProgressReporter(), PhaseCheckpointService()),
    )
    monkeypatch.setattr(setup.desktop, "_events", store)
    return setup, pid, rid, store, client


def wait_until(qapp, condition, timeout=5):
    deadline = monotonic() + timeout
    while not condition() and monotonic() < deadline:
        qapp.processEvents()
        QTest.qWait(5)
    assert condition()


def test_real_tools_validation_checkpoint_and_restart(qapp, observable):
    setup, pid, rid, store, _ = observable
    assert setup.desktop.get_developer_events(pid) == ()
    with pytest.raises(DesktopError):
        setup.desktop.continue_developer(pid)
    assert setup.desktop.get_developer_events(pid) == ()
    setup.desktop.approve_developer_plan(pid)
    setup.desktop.continue_developer(pid)
    recorded = setup.desktop.get_developer_events(pid)
    kinds = [e.kind for e in recorded]
    lifecycle = [kind for kind in kinds if kind != "snapshot_saved"]
    assert lifecycle[:3] == ["plan_approved", "phase_started", "agent_started"]
    assert lifecycle[-2:] == ["phase_finished", "checkpoint_created"]
    assert "validation_started" in kinds and "validation_finished" in kinds
    shell = [e for e in recorded if e.tool == "shell" and e.kind == "tool_completed"]
    assert len(shell) == 2 and all(e.exit_code == 0 for e in shell)
    assert {e.source for e in shell} == {"tool", "validation"}
    assert setup.desktop.get_project_view(pid).developer.status == "awaiting_checkpoint"
    assert (setup.root / "src" / "app.py").read_text() == "print('actual saved code')\n"
    assert "PRIVATE_FINAL_ANSWER" not in "".join(e.model_dump_json() for e in recorded)
    assert not setup.desktop.get_developer_workspace_code(pid, "imaginary.py").exists
    # Neither metadata store nor raw run transcript appears in Workspace.
    assert [f.path for f in setup.desktop.get_developer_workspace(pid).files] == [
        "src/app.py"
    ]
    fresh = build_desktop_application(setup.root, setup.root)
    assert fresh.get_developer_events(pid) == recorded
    window = MainWindow(fresh)
    window.select_project(pid)
    window.navigate("Developer")
    panel = window.pages["Developer"].findChild(ExecutionTimelinePanel)
    assert panel.sequence == recorded[-1].sequence
    panel.tree.setCurrentItem(
        panel.tree.topLevelItem(
            kinds.index("tool_completed", kinds.index("file_observed"))
        )
    )
    assert "종료 코드: 0" in panel.logs.toPlainText()
    assert "명령어: uv --version" in panel.logs.toPlainText()
    window.close()
    # A different project cannot query this run or advance it through a read.
    with pytest.raises(DesktopError):
        setup.desktop.get_developer_events(setup.ids[WorkMode.RESEARCHER])
    assert setup.desktop.get_developer_events(setup.ids[WorkMode.HYBRID]) == ()
    assert store.latest_phase(rid).kind == "phase_finished"
    assert store.latest(rid).snapshot_stage == "after"


def test_timeline_updates_before_finish_and_workspace_reads_stay_enabled(
    qapp, observable
):
    setup, pid, _, _, client = observable
    blocked = Event()
    release = Event()
    responses = list(client.complete.side_effect)
    count = 0

    def complete(*args):
        nonlocal count
        index = count
        count += 1
        if index == 1:
            blocked.set()
            assert release.wait(5)
        return responses[index]

    client.complete.side_effect = complete
    setup.desktop.approve_developer_plan(pid)
    window = MainWindow(setup.desktop)
    window.select_project(pid)
    window.navigate("Developer")
    window.show()
    try:
        window.submit(lambda: setup.desktop.continue_developer(pid))
        wait_until(qapp, blocked.is_set)
        timeline = window.pages["Developer"].findChild(ExecutionTimelinePanel)
        wait_until(qapp, lambda: timeline.sequence >= 6)
        assert window.busy and window.centralWidget().isEnabled()
        assert (
            not window.pages["Developer"]
            .findChild(QPushButton, "continue_developer")
            .isEnabled()
        )
        workspace = window.pages["Developer"].findChild(DeveloperWorkspacePanel)
        assert workspace.isEnabled()
        assert setup.desktop.get_developer_workspace_code(pid, "src/app.py").exists
        assert not any(
            e.kind == "phase_finished" for e in setup.desktop.get_developer_events(pid)
        )
        assert "실행 중" in timeline.status.text()
        assert any(
            event.kind == "file_observed"
            for event in setup.desktop.get_developer_events(pid)
        )
        ignored = Mock()
        window.submit(ignored)
        ignored.assert_not_called()
        with pytest.raises(DesktopError):
            setup.desktop.continue_developer(pid)
        with pytest.raises(DesktopError):
            setup.desktop.approve_developer_plan(pid)
        window.navigate("Artifacts")
        assert window.state.current_page == "Artifacts"
        window.navigate("Developer")
        assert window.pages["Developer"].findChild(ExecutionTimelinePanel).sequence >= 6
    finally:
        release.set()
        wait_until(qapp, lambda: not window.busy)
        window.close()
    assert setup.desktop.get_developer_last_event(pid).snapshot_stage == "after"


def test_empty_timeline_poll_does_not_create_events_or_fake_progress(qapp, observable):
    setup, pid, _, store, _ = observable
    window = MainWindow(setup.desktop)
    window.select_project(pid)
    window.navigate("Developer")
    panel = window.pages["Developer"].findChild(ExecutionTimelinePanel)
    for _ in range(3):
        panel.poll()
    assert panel.sequence == 0 and panel.tree.topLevelItemCount() == 0
    assert "기록된 실행 이벤트가 없습니다" in panel.status.text()
    assert not store.database.exists()
    window.close()


def test_checkpoint_retry_and_repair_attempt_event_order(qapp, observable, monkeypatch):
    from ai_agent_project.agent.acceptance import (
        AcceptanceReport,
        RequirementValidationResult,
    )
    from ai_agent_project.agent.checkpoint import CheckpointDecision

    setup, pid, _, _, client = observable
    application = setup.desktop._actions._developer_plans
    phase = application._project_execution_service._phase_execution_service
    phase._max_repair_attempts = 1
    reports = [
        AcceptanceReport(
            requirements=[
                RequirementValidationResult(requirement_id="REQ-1", status="failed")
            ]
        ),
        AcceptanceReport(
            requirements=[
                RequirementValidationResult(requirement_id="REQ-1", status="failed")
            ]
        ),
    ]
    monkeypatch.setattr(
        phase._acceptance_validator, "validate", Mock(side_effect=reports)
    )
    client.complete.side_effect = [
        LLMResponse(final_answer="Unverified first response"),
        LLMResponse(
            tool_call=ToolCall(
                name="file",
                arguments={
                    "operation": "write_file",
                    "path": "src/app.py",
                    "content": "print('repaired')\n",
                },
            )
        ),
        LLMResponse(final_answer="Unverified repair response"),
    ]
    setup.desktop.approve_developer_plan(pid)
    setup.desktop.continue_developer(pid)
    first = setup.desktop.get_developer_events(pid)
    kinds = [e.kind for e in first]
    assert (
        kinds.index("validation_finished")
        < kinds.index("repair_started")
        < kinds.index("file_observed")
        < kinds.index("checkpoint_created")
    )
    repaired = next(e for e in first if e.kind == "file_observed")
    assert repaired.repair_attempt == 1
    setup.desktop.decide_developer_checkpoint(pid, CheckpointDecision.RETRY)
    assert setup.desktop.get_developer_last_event(pid).kind == "checkpoint_decided"
    assert setup.desktop.get_developer_last_event(pid).status == "retry"
    client.complete.side_effect = [LLMResponse(final_answer="Still unverified")]
    monkeypatch.setattr(
        phase._acceptance_validator,
        "validate",
        Mock(
            return_value=AcceptanceReport(
                requirements=[
                    RequirementValidationResult(requirement_id="REQ-1", status="passed")
                ]
            )
        ),
    )
    setup.desktop.continue_developer(pid)
    starts = [
        e for e in setup.desktop.get_developer_events(pid) if e.kind == "phase_started"
    ]
    assert len(starts) == 2 and starts[0].attempt_id != starts[1].attempt_id
    assert starts[0].sequence < starts[1].sequence


def test_agent_failure_does_not_publish_private_error(qapp, observable):
    setup, pid, _, _, client = observable
    client.complete.side_effect = RuntimeError(
        "PRIVATE_AGENT_EXCEPTION /outside/private-path"
    )
    setup.desktop.approve_developer_plan(pid)
    setup.desktop.continue_developer(pid)
    recorded = setup.desktop.get_developer_events(pid)
    assert "agent_failed" in [e.kind for e in recorded]
    assert "PRIVATE_AGENT_EXCEPTION" not in "".join(
        e.model_dump_json() for e in recorded
    )
    assert all("/outside" not in e.stderr for e in recorded)
    assert setup.desktop.get_project_view(pid).developer.status == "awaiting_checkpoint"


def test_history_pages_keep_older_persisted_events_accessible(qapp, observable):
    from uuid import uuid4

    from ai_agent_project.agent.execution_events import PublicExecutionEvent

    setup, pid, rid, store, _ = observable
    attempt = str(uuid4())
    for _ in range(510):
        store.append(
            PublicExecutionEvent(
                run_id=rid,
                phase_id="PHASE-1",
                attempt_id=attempt,
                kind="tool_started",
                status="running",
                tool="file",
            )
        )
    window = MainWindow(setup.desktop)
    window.select_project(pid)
    window.navigate("Developer")
    window.show()
    panel = window.pages["Developer"].findChild(ExecutionTimelinePanel)
    wait_until(qapp, lambda: panel.sequence == 510)
    assert panel.tree.topLevelItemCount() == 500
    panel.load_earlier()
    assert panel.history
    from PySide6.QtCore import Qt

    assert panel.tree.topLevelItem(0).data(0, Qt.ItemDataRole.UserRole).sequence == 1
    panel.return_to_live()
    assert not panel.history and panel.sequence == 510
    assert store.latest(rid).sequence == 510
    window.close()
