import builtins
import importlib
from time import monotonic
from unittest.mock import Mock

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QPushButton

from ai_agent_project.agent.research import WorkMode
from ai_agent_project.desktop_app.application import (
    build_desktop_application,
)
from ai_agent_project.desktop_app.dialogs import (
    DirectionSelectionDialog,
    ResearchResultsDialog,
    TextInputDialog,
)
from ai_agent_project.desktop_app.window import MainWindow
from ai_agent_project.desktop_app.worker import OperationWorker
from ai_agent_project.llm.config import ProviderConfig


def wait_for_operation(qapp, window):
    deadline = monotonic() + 5
    while window.busy and monotonic() < deadline:
        qapp.processEvents()
        QThread.msleep(1)
    assert not window.busy
    qapp.processEvents()


def texts(widget):
    return "\n".join(w.text() for w in widget.findChildren(QLabel))


def test_composition_and_import_without_fastapi(tmp_path, monkeypatch):
    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        assert not name.startswith(("fastapi", "ai_agent_project.api"))
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    for name in (
        "ai_agent_project.composition",
        "ai_agent_project.desktop_app.application",
        "ai_agent_project.desktop_app.main",
    ):
        importlib.reload(importlib.import_module(name))
    service = build_desktop_application(tmp_path, tmp_path)
    assert service.get_dashboard().total_projects == 0


def test_window_and_empty_pages(qapp, tmp_path):
    window = MainWindow(build_desktop_application(tmp_path, tmp_path))
    window.show()
    for row, name in enumerate(window.NAVIGATION):
        window.sidebar.setCurrentRow(row)
        assert window.state.current_page == name
        assert window.stack.currentIndex() == window.page_indices[name]
    for name in ("Developer", "Researcher", "Hybrid"):
        window.navigate(name)
        assert "No project selected" in texts(window.pages[name])
    assert window.close()


def test_phase6c_acceptance(qapp, setup, monkeypatch):
    window = MainWindow(setup.desktop)
    window.show()
    assert window.pages["Dashboard"].metrics[0].text() == "3"
    window.navigate("Projects")
    page = window.pages["Projects"]
    assert page.table.rowCount() == 3
    page.table.setCurrentCell(0, 0)
    page.open_selected()
    assert window.state.selected_project_id == page.projects[0].project_id
    for mode, action in [
        (WorkMode.DEVELOPER, "approve_developer_plan"),
        (WorkMode.RESEARCHER, "select_research_direction"),
        (WorkMode.HYBRID, "approve_developer_plan"),
    ]:
        window.select_project(setup.ids[mode])
        window.navigate(mode.value.title())
        assert window.pages[mode.value.title()].findChild(QPushButton, action)
    assert "Developer" in [
        g.title()
        for g in window.pages["Hybrid"].findChildren(
            __import__("PySide6.QtWidgets", fromlist=["QGroupBox"]).QGroupBox
        )
    ]
    assert window.pages["Hybrid"].findChild(QPushButton, "select_research_direction")
    window.navigate("Artifacts")
    artifacts = window.pages["Artifacts"]
    assert artifacts.table.rowCount() > 0
    artifacts.table.setCurrentCell(0, 0)
    assert (
        artifacts.preview.toPlainText()
        == setup.desktop.get_artifact_view(
            setup.ids[WorkMode.HYBRID], artifacts.artifacts[0].artifact_id
        ).content
    )
    window.navigate("Settings")
    assert "Credential configured: No" in texts(window.pages["Settings"])
    before = setup.snapshot()
    for _ in range(3):
        for name in window.NAVIGATION:
            window.navigate(name)
            window.refresh()
    assert setup.snapshot() == before
    pid = setup.ids[WorkMode.HYBRID]
    original = setup.desktop.approve_developer_plan
    spy = Mock(wraps=original)
    monkeypatch.setattr(setup.desktop, "approve_developer_plan", spy)
    research_before = setup.researchers.get(
        setup.desktop.get_project_view(pid).researcher.run_id
    )
    window.navigate("Hybrid")
    window.pages["Hybrid"].findChild(QPushButton, "approve_developer_plan").click()
    assert window.busy
    assert not window.centralWidget().isEnabled()
    wait_for_operation(qapp, window)
    spy.assert_called_once_with(pid)
    after = setup.snapshot()
    assert sum(before.get(path) != value for path, value in after.items()) == 1
    view = setup.desktop.get_project_view(pid)
    assert view.developer.pending_action.action_type == "continue_developer"
    assert setup.researchers.get(view.researcher.run_id) == research_before
    window.close()
    # Recompose all services and stores from disk, not the prior GUI/service instance.
    recreated = MainWindow(build_desktop_application(setup.root, setup.root))
    assert recreated.pages["Dashboard"].table.rowCount() == 3
    recreated.select_project(pid)
    assert (
        recreated.service.get_project_view(pid).developer.pending_action.action_type
        == "continue_developer"
    )
    recreated.close()
    print("PHASE_6C_PYSIDE6_DESKTOP_UI=PASSED")


def test_direction_requires_choice(qapp, setup):
    directions = setup.desktop.get_project_view(
        setup.ids[WorkMode.RESEARCHER]
    ).researcher.directions
    dialog = DirectionSelectionDialog(directions)
    assert dialog.direction_id is None
    assert not dialog.confirm.isEnabled()
    dialog.choices.setCurrentRow(0)
    assert dialog.confirm.isEnabled()
    assert dialog.direction_id == directions[0].direction_id
    assert dialog.confirm.text() == "Select Direction"


def test_direction_one_action(qapp, setup, monkeypatch):
    window = MainWindow(setup.desktop)
    pid = setup.ids[WorkMode.RESEARCHER]
    window.select_project(pid)
    spy = Mock(wraps=setup.desktop.select_research_direction)
    monkeypatch.setattr(setup.desktop, "select_research_direction", spy)

    def accept(dialog):
        dialog.choices.setCurrentRow(0)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(DirectionSelectionDialog, "exec", accept)
    before = setup.snapshot()
    window.request_action("select_research_direction")
    wait_for_operation(qapp, window)
    spy.assert_called_once_with(pid, "DIRECTION:1")
    assert sum(before.get(k) != v for k, v in setup.snapshot().items()) == 1
    assert setup.desktop.get_project_view(pid).researcher.status == "direction_selected"
    window.close()


def test_results_one_submission_no_analysis(qapp, setup, monkeypatch):
    window = MainWindow(setup.desktop)
    pid = setup.ids[WorkMode.RESEARCHER]
    view = setup.desktop.get_project_view(pid)
    lane = view.researcher.model_copy(
        update={"approved_plan_version": 2, "implementation_plan_version": 2}
    )
    monkeypatch.setattr(
        setup.desktop,
        "get_project_view",
        lambda _: view.model_copy(update={"researcher": lane}),
    )
    submit = Mock()
    advance = Mock()
    monkeypatch.setattr(setup.desktop, "provide_research_results", submit)
    monkeypatch.setattr(setup.desktop, "continue_researcher", advance)

    def accept(dialog):
        dialog.text.setPlainText("Measured outcome: no improvement.")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(ResearchResultsDialog, "exec", accept)
    window.select_project(pid)
    window.request_action("provide_research_results")
    wait_for_operation(qapp, window)
    submit.assert_called_once()
    assert submit.call_args.args[1].user_observations == (
        "Measured outcome: no improvement.",
    )
    assert submit.call_args.args[1].approved_plan_version == 2
    advance.assert_not_called()
    window.close()


def test_bootstrap_requires_explicit_submit(qapp, setup, monkeypatch):
    window = MainWindow(setup.desktop)
    pid = setup.ids[WorkMode.HYBRID]
    window.select_project(pid)
    bootstrap, handoff, approve = Mock(), Mock(), Mock()
    monkeypatch.setattr(setup.desktop, "bootstrap_developer_from_handoff", bootstrap)
    monkeypatch.setattr(setup.desktop, "create_handoff", handoff)
    monkeypatch.setattr(setup.desktop, "approve_developer_plan", approve)
    monkeypatch.setattr(TextInputDialog, "exec", lambda _: QDialog.DialogCode.Rejected)
    window.bootstrap("handoff")
    bootstrap.assert_not_called()

    def accept(dialog):
        dialog.text.setPlainText("Build from this research")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(TextInputDialog, "exec", accept)
    window.bootstrap("handoff")
    wait_for_operation(qapp, window)
    bootstrap.assert_called_once_with(pid, "handoff", "Build from this research")
    handoff.assert_not_called()
    approve.assert_not_called()
    window.close()


def test_handoff_is_single_explicit_action(qapp, setup, monkeypatch):
    window = MainWindow(setup.desktop)
    pid = setup.ids[WorkMode.HYBRID]
    window.select_project(pid)
    window.navigate("Artifacts")
    page = window.pages["Artifacts"]
    page.table.setCurrentCell(0, 0)
    create, bootstrap = Mock(return_value="handoff"), Mock()
    monkeypatch.setattr(setup.desktop, "create_handoff", create)
    monkeypatch.setattr(setup.desktop, "bootstrap_developer_from_handoff", bootstrap)
    create.assert_not_called()
    page.create_handoff()
    wait_for_operation(qapp, window)
    create.assert_called_once_with(pid, page.artifacts[0].artifact_id)
    bootstrap.assert_not_called()
    window.close()


def test_settings_secrets_and_connection(qapp, tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    service = build_desktop_application(tmp_path, tmp_path)
    secret = "synthetic-desktop-credential"
    service.save_provider_config(ProviderConfig(api_key=secret))
    assert secret not in (tmp_path / "settings" / "llm.json").read_text()
    assert secret not in repr(service.get_provider_config())
    window = MainWindow(service)
    window.navigate("Settings")
    settings = window.pages["Settings"]
    assert settings.key.echoMode() == QLineEdit.EchoMode.Password
    assert settings.key.text() == ""
    assert secret not in texts(window)
    assert "Credential configured: Yes" in texts(settings)
    monkeypatch.setattr(
        "ai_agent_project.llm.runtime.build_openai_client",
        Mock(side_effect=RuntimeError(secret)),
    )
    settings.apply(True)
    wait_for_operation(qapp, window)
    assert "Failure:" in window.statusBar().currentMessage()
    assert secret not in window.statusBar().currentMessage()
    assert secret not in repr(ProviderConfig(api_key=secret))
    assert secret not in str(ProviderConfig(api_key=secret))
    window.close()
    assert (
        not build_desktop_application(tmp_path, tmp_path)
        .get_provider_config()
        .credential_configured
    )


def test_worker_one_callable_and_sanitized_error(qapp):
    operation = Mock(return_value="done")
    worker = OperationWorker(operation)
    result = []
    worker.signals.succeeded.connect(result.append)
    worker.run()
    operation.assert_called_once_with()
    assert result == ["done"]
    worker = OperationWorker(Mock(side_effect=RuntimeError("synthetic-secret")))
    errors = []
    worker.signals.failed.connect(errors.append)
    worker.run()
    assert len(errors) == 1
    assert "synthetic-secret" not in errors[0]


def test_no_auto_next_or_research_execution(qapp, setup):
    window = MainWindow(setup.desktop)
    window.select_project(setup.ids[WorkMode.RESEARCHER])
    window.navigate("Researcher")
    buttons = [
        b.text().lower() for b in window.pages["Researcher"].findChildren(QPushButton)
    ]
    assert buttons
    assert not any(
        term in text
        for text in buttons
        for term in ("next", "experiment", "execute", "train", "shell")
    )
    window.close()


def test_real_result_intake_keeps_analysis_pending(
    qapp, setup, research_seed, monkeypatch
):
    from ai_agent_project.agent.research import ResearchStatus

    pid = setup.ids[WorkMode.HYBRID]
    view = setup.desktop.get_project_view(pid)
    plan = research_seed._implementation_plan()
    run = research_seed._approved_run().model_copy(
        update={
            "status": ResearchStatus.IMPLEMENTATION_PACKAGE_READY,
            "implementation_plan": plan,
            "implementation_package": research_seed._package(plan),
        }
    )
    setup.researchers.replace(view.researcher.run_id, run)
    window = MainWindow(setup.desktop)
    window.select_project(pid)
    window.navigate("Researcher")
    before = setup.snapshot()

    def accept(dialog):
        dialog.text.setPlainText(
            "No experiments were executed. Manual review found missing evidence."
        )
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(ResearchResultsDialog, "exec", accept)
    window.pages["Researcher"].findChild(
        QPushButton, "provide_research_results"
    ).click()
    wait_for_operation(qapp, window)
    after = setup.researchers.get(view.researcher.run_id)
    assert after.result_submission is not None
    assert after.result_analysis is None
    assert after.result_synthesis is None
    assert sum(before.get(k) != v for k, v in setup.snapshot().items()) == 1
    window.close()


def test_real_handoff_and_bootstrap_remain_separate(
    qapp, setup, research_seed, developer_seed, monkeypatch
):
    from uuid import uuid4

    from ai_agent_project.agent.project_application import StoredProjectRun
    from ai_agent_project.agent.project_developer_bootstrap_application import (
        ProjectDeveloperBootstrapService,
    )
    from ai_agent_project.agent.project_handoff_consumption import (
        ProjectHandoffConsumptionService,
    )
    from ai_agent_project.agent.project_session import (
        ProjectModeProposal,
        ProjectSession,
    )
    from ai_agent_project.agent.upgrade import ProjectMode

    pid, rid = str(uuid4()), str(uuid4())
    setup.sessions._store.create(
        pid,
        ProjectSession.awaiting_confirmation(
            project_id=pid,
            title="Bootstrap",
            original_request="Build",
            mode_proposal=ProjectModeProposal(
                proposed_work_mode=WorkMode.HYBRID,
                proposed_project_mode=ProjectMode.NEW,
                rationale="Seed",
            ),
        ),
    )
    setup.sessions.confirm_project_mode(pid, WorkMode.HYBRID, ProjectMode.NEW)
    setup.researchers.create(rid, research_seed._approved_run())
    setup.sessions.bind_research_run(pid, rid)

    def create(request, *, context, provenance):
        run_id = str(uuid4())
        run = developer_seed()
        setup.developers.create(run_id, run)
        return StoredProjectRun(id=run_id, project_run=run)

    developer = Mock()
    developer.create_project_with_context.side_effect = create
    setup.desktop._bootstrap = ProjectDeveloperBootstrapService(
        setup.sessions,
        ProjectHandoffConsumptionService(
            setup.sessions, setup.artifacts, setup.handoff_store, setup.researchers
        ),
        developer,
    )
    window = MainWindow(setup.desktop)
    window.select_project(pid)
    window.navigate("Artifacts")
    page = window.pages["Artifacts"]
    row = next(
        i
        for i, a in enumerate(page.artifacts)
        if a.artifact_type == "research_plan_revision"
    )
    page.table.setCurrentCell(row, 0)
    assert page.handoff.isEnabled()
    before = setup.snapshot()
    page.handoff.click()
    wait_for_operation(qapp, window)
    assert len(setup.desktop.list_handoffs(pid)) == 1
    assert setup.desktop.get_project_view(pid).developer.bound is False
    developer.create_project_with_context.assert_not_called()
    assert len(set(setup.snapshot()) - set(before)) == 1
    window.navigate("Hybrid")
    button = next(
        b
        for b in window.pages["Hybrid"].findChildren(QPushButton)
        if b.text() == "Create Developer Run From Research"
    )
    assert button.isEnabled()

    def accept(dialog):
        dialog.text.setPlainText("Build from approved research")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(TextInputDialog, "exec", accept)
    research_before = setup.researchers.get(rid)
    button.click()
    wait_for_operation(qapp, window)
    developer.create_project_with_context.assert_called_once()
    view = setup.desktop.get_project_view(pid)
    assert view.developer.pending_action.action_type == "approve_developer_plan"
    assert setup.researchers.get(rid) == research_before
    window.close()


def test_safe_export_refuses_overwrite_and_symlink(qapp, setup, tmp_path):
    import pytest

    from ai_agent_project.desktop import DesktopError

    pid = setup.ids[WorkMode.DEVELOPER]
    aid = setup.desktop.list_project_artifacts(pid)[0].artifact_id
    target = tmp_path / "export.json"
    setup.desktop.export_artifact(pid, aid, target)
    original = target.read_bytes()
    with pytest.raises(DesktopError):
        setup.desktop.export_artifact(pid, aid, target)
    alias = tmp_path / "alias.json"
    alias.symlink_to(target)
    with pytest.raises(DesktopError):
        setup.desktop.export_artifact(pid, aid, alias)
    assert target.read_bytes() == original
    with pytest.raises(DesktopError):
        setup.desktop.get_artifact_view(pid, "../../private")


def test_worker_completion_on_gui_thread_and_close_guard(qapp, setup):
    from threading import Event

    release = Event()
    window = MainWindow(setup.desktop)
    gui_thread = qapp.thread()
    calls = []

    def operation():
        assert QThread.currentThread() != gui_thread
        release.wait(3)
        return "finished"

    window.submit(
        operation, lambda result: calls.append((result, QThread.currentThread()))
    )
    ignored = Mock()
    window.submit(ignored)
    assert not window.close()
    release.set()
    wait_for_operation(qapp, window)
    assert calls == [("finished", gui_thread)]
    ignored.assert_not_called()
    assert window.close()


def test_mode_proposal_and_confirmation_separate(qapp, setup, monkeypatch):
    from ai_agent_project.agent.project_session import ProjectModeProposal
    from ai_agent_project.agent.upgrade import ProjectMode
    from ai_agent_project.desktop_app.dialogs import (
        CreateProjectDialog,
        ModeConfirmationDialog,
    )

    proposer = Mock()
    proposer.propose.return_value = ProjectModeProposal(
        proposed_work_mode=WorkMode.HYBRID,
        proposed_project_mode=ProjectMode.NEW,
        rationale="Proposal",
    )
    monkeypatch.setattr(setup.sessions, "_mode_proposer", proposer)
    window = MainWindow(setup.desktop)

    def accept_create(dialog):
        dialog.title.setText("Created in UI")
        dialog.request.setPlainText("Build and research")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(CreateProjectDialog, "exec", accept_create)
    window.create_project()
    wait_for_operation(qapp, window)
    pid = window.state.selected_project_id
    view = setup.desktop.get_project_view(pid)
    assert view.project.work_mode is None
    assert view.project.pending_actions[0].action_type == "confirm_mode"
    monkeypatch.setattr(
        ModeConfirmationDialog, "exec", lambda _: QDialog.DialogCode.Accepted
    )
    window.request_action("confirm_mode")
    wait_for_operation(qapp, window)
    view = setup.desktop.get_project_view(pid)
    assert view.project.work_mode == "hybrid"
    assert not view.developer.bound and not view.researcher.bound
    assert window.pages["Project Detail"].findChild(QPushButton, "bind_developer_run")
    assert window.pages["Project Detail"].findChild(QPushButton, "bind_research_run")
    window.close()


def test_provider_operation_clients_close_on_error(monkeypatch):
    import pytest

    from ai_agent_project.llm.runtime import (
        ConfiguredOpenAIProvider,
        provider_client_scope,
    )

    client = Mock()
    monkeypatch.setattr(
        "ai_agent_project.llm.runtime.build_openai_client", lambda _: client
    )
    with pytest.raises(RuntimeError), provider_client_scope():
        provider = ConfiguredOpenAIProvider()
        provider._configure(
            config=ProviderConfig(api_key="synthetic"),
            api_key=None,
            model=None,
            client=None,
        )
        provider._get_client()
        raise RuntimeError("operation failed")
    client.close.assert_called_once()


def test_run_creation_does_not_bind_or_approve(
    qapp, setup, developer_seed, monkeypatch
):
    from uuid import uuid4

    from ai_agent_project.agent.project_application import StoredProjectRun
    from ai_agent_project.desktop_app.dialogs import CreatedRunDialog

    pid = setup.ids[WorkMode.DEVELOPER]
    creator = Mock()

    def create(request):
        run_id = str(uuid4())
        run = developer_seed()
        setup.developers.create(run_id, run)
        return StoredProjectRun(id=run_id, project_run=run)

    creator.create_project.side_effect = create
    setup.desktop._developer_application = creator
    window = MainWindow(setup.desktop)
    window.select_project(pid)
    before = setup.desktop.get_project_view(pid)
    monkeypatch.setattr(CreatedRunDialog, "exec", lambda _: QDialog.DialogCode.Rejected)
    window.create_run("developer")
    wait_for_operation(qapp, window)
    creator.create_project.assert_called_once()
    assert setup.desktop.get_project_view(pid) == before
    creator.approve_plan.assert_not_called()
    window.close()


def test_created_run_binding_is_explicit(qapp, setup, developer_seed, monkeypatch):
    from uuid import uuid4

    from ai_agent_project.desktop_app.dialogs import CreatedRunDialog

    pid = setup.ids[WorkMode.DEVELOPER]
    run_id = str(uuid4())
    setup.developers.create(run_id, developer_seed())
    window = MainWindow(setup.desktop)
    window.select_project(pid)
    bind = Mock(wraps=setup.desktop.bind_developer_run)
    monkeypatch.setattr(setup.desktop, "bind_developer_run", bind)
    monkeypatch.setattr(CreatedRunDialog, "exec", lambda _: QDialog.DialogCode.Accepted)
    window.offer_binding("developer", pid, run_id)
    wait_for_operation(qapp, window)
    bind.assert_called_once_with(pid, run_id)
    assert (
        setup.desktop.get_project_view(pid).developer.pending_action.action_type
        == "approve_developer_plan"
    )
    window.close()


def test_shared_composition_preserves_default_workspace():
    from pathlib import Path

    from ai_agent_project.composition import _default_workspace_root

    assert _default_workspace_root() == Path(__file__).resolve().parents[2]
