"""Offscreen user actions go through the existing single-operation Qt worker."""

import time
from unittest.mock import Mock

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

from ai_agent_project.agent.research import WorkMode
from ai_agent_project.desktop_app.improvements import FeedbackDialog, feedback_run
from ai_agent_project.desktop_app.window import MainWindow
from ai_agent_project.improvement.file_store import FileImprovementStore
from ai_agent_project.improvement.service import ImprovementService


@pytest.fixture
def window(env, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(QMessageBox, "warning", Mock())
    value = MainWindow(env.seed.desktop)
    yield value, app
    value.pool.waitForDone(5000)
    value.close()
    app.processEvents()


def finish(window, app):
    deadline = time.monotonic() + 5
    while window.busy and time.monotonic() < deadline:
        app.processEvents()
        QTest.qWait(5)
    assert not window.busy
    app.processEvents()


def test_gui_explicit_evaluate_approve_disable_restart(env, window):
    win, app = window
    win.select_project(env.seed.ids[WorkMode.DEVELOPER])
    win.navigate("Developer")
    before = {
        k: v
        for k, v in env.seed.snapshot().items()
        if not k.startswith("improvements/")
    }
    button = win.pages["Developer"].findChild(QPushButton, "evaluate_developer")
    assert button is not None
    button.click()
    assert win.busy and not win.centralWidget().isEnabled()
    finish(win, app)
    assert len(env.evaluator.calls) == 1
    assert win.state.current_page == "Improvements"
    page = win.pages["Improvements"]
    assert page.tables["Candidates"].rowCount() == 1
    assert not env.service.list_rules()
    page.tables["Candidates"].setCurrentCell(0, 0)
    assert "evidence_refs" in page.preview.toPlainText()
    page.buttons["Approve Candidate"].click()
    finish(win, app)
    assert len(env.service.list_rules()) == 1 and len(env.evaluator.calls) == 1
    page.tabs.setCurrentIndex(1)
    page.tables["Approved Rules"].setCurrentCell(0, 0)
    assert "Observed usage" in page.preview.toPlainText()
    page.buttons["Disable Rule"].click()
    finish(win, app)
    assert not env.service.list_rules()[0].enabled
    assert len(env.service.overview().rules) == 2
    snapshot = env.seed.snapshot()
    for _ in range(2):
        for name in win.NAVIGATION:
            win.navigate(name)
            win.refresh()
    assert env.seed.snapshot() == snapshot and len(env.evaluator.calls) == 1
    env.seed.desktop._improvements = ImprovementService(
        FileImprovementStore(env.service.store.root)
    )
    reopened = MainWindow(env.seed.desktop)
    reopened.navigate("Improvements")
    assert reopened.pages["Improvements"].tables["Approved Rules"].rowCount() == 1
    assert not env.seed.desktop.list_improvement_rules()[0].enabled
    reopened.close()
    assert {
        k: v
        for k, v in env.seed.snapshot().items()
        if not k.startswith("improvements/")
    } == before


def test_gui_rejection_and_enable_are_explicit(env, window):
    win, app = window
    env.service.evaluate("researcher", env.researcher)
    win.navigate("Improvements")
    page = win.pages["Improvements"]
    page.tables["Candidates"].setCurrentCell(0, 0)
    page.buttons["Reject Candidate"].click()
    finish(win, app)
    assert env.service.list_candidates()[0].status == "rejected"
    assert not env.service.list_rules()
    env.service.evaluate("developer", env.developer)
    rule = env.service.approve_candidate(env.service.list_candidates()[-1].candidate_id)
    env.service.set_enabled(rule.rule_id, False)
    win.refresh()
    page.tabs.setCurrentIndex(1)
    page.tables["Approved Rules"].setCurrentCell(0, 0)
    page.buttons["Enable Rule"].click()
    finish(win, app)
    assert env.service.get_rule(rule.rule_id).enabled
    assert len(env.evaluator.calls) == 2


def test_gui_feedback_does_not_evaluate(env, window, monkeypatch):
    win, app = window
    monkeypatch.setattr(
        FeedbackDialog, "exec", lambda self: FeedbackDialog.DialogCode.Accepted
    )
    feedback_run(win, "researcher", env.researcher)
    finish(win, app)
    assert len(env.service.overview().feedback) == 1
    assert not env.evaluator.calls
