"""Selected folders use the production composition, persisted runs and real tools."""

from pathlib import Path
from unittest.mock import Mock

import pytest
from PySide6.QtWidgets import QLabel, QPushButton

from ai_agent_project.agent.plan_revision import PlanRevisionState
from ai_agent_project.agent.project_session import ProjectModeProposal
from ai_agent_project.agent.research import WorkMode
from ai_agent_project.agent.service import AgentService
from ai_agent_project.agent.state import ToolCall
from ai_agent_project.agent.upgrade import ProjectMode
from ai_agent_project.desktop.errors import DesktopError
from ai_agent_project.desktop.project_directory import (
    checked_directory,
    create_directory,
)
from ai_agent_project.desktop_app.application import build_desktop_application
from ai_agent_project.desktop_app.dialogs import (
    CreateProjectDialog,
    ModeConfirmationDialog,
)
from ai_agent_project.desktop_app.window import MainWindow
from ai_agent_project.llm.base import LLMResponse
from ai_agent_project.tools.file import FileTool
from ai_agent_project.tools.registry import ToolRegistry
from ai_agent_project.tools.shell import ShellTool


@pytest.fixture
def production(tmp_path, monkeypatch, developer_seed):
    root = tmp_path / "state"
    parent = tmp_path / "sources"
    parent.mkdir()
    service = build_desktop_application(root, parent)
    service._sessions._mode_proposer = Mock()
    service._sessions._mode_proposer.propose.return_value = ProjectModeProposal(
        proposed_work_mode=WorkMode.DEVELOPER,
        proposed_project_mode=ProjectMode.NEW,
        rationale="User request",
    )
    run = developer_seed()
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
    monkeypatch.setattr(
        "ai_agent_project.agent.project_runner.ProjectRunner.start",
        lambda *args, **kwargs: run,
    )
    monkeypatch.setattr(
        "ai_agent_project.agent.project_runner.UpgradeProjectRunner.start_upgrade",
        lambda *args, **kwargs: run,
    )
    paths = []
    clients = []

    def agent(folder, **kwargs):
        paths.append(folder)
        tools = ToolRegistry()
        tools.register(FileTool(folder))
        tools.register(ShellTool(folder))
        assert (
            tools.get("file")._workspace_root
            == tools.get("shell")._workspace_root
            == folder
        )
        client = Mock()
        client.complete.side_effect = [
            LLMResponse(
                tool_call=ToolCall(
                    name="file",
                    arguments={
                        "operation": "write_file",
                        "path": "src/app.py",
                        "content": 'print("selected folder")\n',
                    },
                )
            ),
            LLMResponse(
                tool_call=ToolCall(name="shell", arguments={"command": "uv --version"})
            ),
            LLMResponse(final_answer="Done"),
        ]
        clients.append(client)
        return AgentService(client, tools)

    monkeypatch.setattr(
        "ai_agent_project.composition.create_default_agent_service", agent
    )
    return service, root, parent, paths, clients


def test_selected_folder_real_execution_approval_restart_and_diff(
    production, monkeypatch
):
    service, root, parent, paths, _clients = production
    pid = service.create_project(
        "Build app", parent_directory=parent, folder_name="한글 프로젝트"
    )
    folder = parent / "한글 프로젝트"
    assert folder.is_dir() and list(folder.iterdir()) == []
    service.confirm_project_mode(pid, WorkMode.DEVELOPER, ProjectMode.NEW)
    rid = service.create_developer_run(pid)
    service.bind_developer_run(pid, rid)
    assert service._developers.workspace_root_for(rid) == folder
    with pytest.raises(DesktopError):
        service.continue_developer(pid)
    assert not (folder / "src/app.py").exists()
    # The real validation inspector and subprocess both observe the selected root.
    import ai_agent_project.agent.workspace_acceptance as acceptance

    original_capture = acceptance.WorkspaceAcceptanceValidator.capture_workspace_state
    validated = []

    def capture(self):
        validated.append(self._workspace_root)
        return original_capture(self)

    monkeypatch.setattr(
        acceptance.WorkspaceAcceptanceValidator, "capture_workspace_state", capture
    )
    import subprocess

    subprocess_run = subprocess.run
    command_roots = []

    def actual_command(*args, **kwargs):
        command_roots.append(kwargs.get("cwd"))
        return subprocess_run(*args, **kwargs)

    monkeypatch.setattr("ai_agent_project.tools.shell.subprocess.run", actual_command)
    service.approve_developer_plan(pid)
    service.continue_developer(pid)
    assert len(command_roots) >= 2 and all(
        Path(path) == folder for path in command_roots
    )
    assert (
        not FileTool(folder)
        .execute(
            {"operation": "write_file", "path": "../escape.py", "content": "blocked"}
        )
        .success
    )
    assert not (parent / "escape.py").exists()
    assert (folder / "src/app.py").read_text() == 'print("selected folder")\n'
    assert not (parent / "src/app.py").exists()
    assert all(path == folder for path in paths + validated) and validated
    assert service.get_developer_workspace(pid).absolute_path == str(folder)
    assert (
        service.get_developer_workspace_code(pid, "src/app.py").content
        == 'print("selected folder")\n'
    )
    assert any(
        e.tool == "shell" and e.exit_code == 0
        for e in service.get_developer_events(pid)
    )
    assert service.get_developer_code_changes(pid).changes[0].path == "src/app.py"
    fresh = build_desktop_application(root, parent)
    assert fresh.get_project_view(pid).project.workspace_root == str(folder)
    assert fresh.get_developer_code_changes(pid) == service.get_developer_code_changes(
        pid
    )
    with pytest.raises(DesktopError):
        fresh.set_project_workspace(pid, parent)
    assert fresh._developers.workspace_root_for(rid) == folder


def test_existing_folder_registration_preserves_files_and_deduplicates(production):
    service, root, parent, _, _ = production
    folder = parent / "existing"
    folder.mkdir()
    (folder / "keep.py").write_text("original\n")
    pid = service.open_existing_project(folder, "Improve code")
    assert service.open_existing_project(folder, "ignored") == pid
    assert len(service.list_projects()) == 1
    assert (folder / "keep.py").read_text() == "original\n"
    service.confirm_project_mode(pid, WorkMode.DEVELOPER, ProjectMode.UPGRADE)
    rid = service.create_developer_run(pid)
    service.bind_developer_run(pid, rid)
    with pytest.raises(DesktopError):
        service.continue_developer(pid)
    assert sorted(p.name for p in folder.iterdir()) == ["keep.py"]
    assert build_desktop_application(root, parent).find_project_directory(folder) == pid


@pytest.mark.parametrize("name", ["../escape", "a/b", "a\\b", "..", "CON", "a.", ""])
def test_folder_name_escape_rejected(tmp_path, name):
    with pytest.raises(DesktopError):
        create_directory(tmp_path, name)


def test_existing_missing_symlink_permissions_and_no_overwrite(tmp_path, monkeypatch):
    folder = tmp_path / "existing"
    folder.mkdir()
    with pytest.raises(DesktopError):
        create_directory(tmp_path, "existing")
    with pytest.raises(DesktopError):
        checked_directory(tmp_path / "missing")
    alias = tmp_path / "alias"
    alias.symlink_to(folder, target_is_directory=True)
    with pytest.raises(DesktopError):
        checked_directory(alias)
    with pytest.raises(DesktopError):
        checked_directory(tmp_path / ".." / "other")
    monkeypatch.setattr(
        "ai_agent_project.desktop.project_directory.os.access", lambda *args: False
    )
    with pytest.raises(DesktopError):
        checked_directory(folder)


def test_korean_dialog_enums_and_no_change_while_busy(qapp, production):
    service, _, parent, _, _ = production
    dialog = CreateProjectDialog()
    dialog.request.setPlainText("request")
    assert not dialog.confirm.isEnabled()
    dialog.parent_directory.setText(str(parent))
    dialog.folder_name.setText("프로젝트")
    assert dialog.confirm.isEnabled()
    pid = service.create_project(
        "request", parent_directory=parent, folder_name="sample"
    )
    window = MainWindow(service)
    window.select_project(pid)
    mode = ModeConfirmationDialog(service.get_project_view(pid))
    assert (
        mode.work.currentText() == "개발 에이전트"
        and mode.work.currentData() == "developer"
    )
    assert mode.mode.currentText() == "새 프로젝트" and mode.mode.currentData() == "new"
    button = window.pages["Project Detail"].findChild(
        QPushButton, "changeProjectDirectory"
    )
    assert button.isEnabled()
    window._worker = object()
    window._set_mutation_controls()
    assert not button.isEnabled()
    assert str(parent / "sample") in "\n".join(
        w.text() for w in window.findChildren(QLabel)
    )
    window._worker = None
    window.close()


def test_missing_saved_folder_does_not_fall_back(production):
    service, root, parent, _, _ = production
    pid = service.create_project(
        "Build", parent_directory=parent, folder_name="deleted"
    )
    folder = parent / "deleted"
    folder.rmdir()
    service.confirm_project_mode(pid, WorkMode.DEVELOPER, ProjectMode.NEW)
    with pytest.raises(DesktopError):
        service.create_developer_run(pid)
    assert build_desktop_application(root, parent).get_project_view(
        pid
    ).project.workspace_root == str(folder)
    assert list(parent.iterdir()) == []


def test_parallel_existing_registration_has_one_project(production):
    from concurrent.futures import ThreadPoolExecutor

    service, root, parent, _, _ = production
    fresh = build_desktop_application(root, parent)
    fresh._sessions._mode_proposer = service._sessions._mode_proposer
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(
            pool.map(
                lambda s: s.open_existing_project(parent, "request"), (service, fresh)
            )
        )
    assert ids[0] == ids[1] and len(service.list_projects()) == 1


def test_binding_foreign_root_is_rejected(production):
    service, _, parent, _, _ = production
    pid = service.create_project("A", parent_directory=parent, folder_name="first")
    other = service.create_project("B", parent_directory=parent, folder_name="second")
    for project_id in (pid, other):
        service.confirm_project_mode(project_id, WorkMode.DEVELOPER, ProjectMode.NEW)
    rid = service.create_developer_run(pid)
    with pytest.raises(DesktopError, match="작업 폴더"):
        service.bind_developer_run(other, rid)
    assert service._developers.workspace_root_for(rid) == parent / "first"


def test_korean_navigation_all_headers_and_qt_dialogs(qapp, production):
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtWidgets import QGroupBox, QTableWidget

    service, _, parent, _, _ = production
    pid = service.create_project(
        "Developer remains user content", parent_directory=parent, folder_name="display"
    )
    window = MainWindow(service)
    window.select_project(pid)
    assert [window.sidebar.item(i).text() for i in range(window.sidebar.count())] == [
        "대시보드",
        "프로젝트",
        "개발 에이전트",
        "리서치 에이전트",
        "통합 작업",
        "결과물",
        "개선 관리",
        "설정",
    ]
    assert QCoreApplication.translate("QPlatformTheme", "Cancel") == "취소"
    for name in window.NAVIGATION:
        window.navigate(name)
        for widget in window.pages[name].findChildren(QPushButton):
            assert any("가" <= c <= "힣" for c in widget.text())
        for widget in window.pages[name].findChildren(QGroupBox):
            assert any("가" <= c <= "힣" for c in widget.title())
        for widget in window.pages[name].findChildren(QTableWidget):
            assert all(
                any("가" <= c <= "힣" for c in widget.horizontalHeaderItem(i).text())
                for i in range(widget.columnCount())
            )
    assert (
        service._sessions.get_project(pid).project.original_request
        == "Developer remains user content"
    )
    window.close()


def test_private_and_storage_folders_cannot_be_registered(production):
    service, root, parent, _, _ = production
    private = parent / ".git"
    private.mkdir()
    with pytest.raises(DesktopError):
        service.open_existing_project(private, "request")
    with pytest.raises(DesktopError):
        service.open_existing_project(root, "request")
    with pytest.raises(DesktopError):
        service.create_project(
            "request", parent_directory=root / "projects", folder_name="inside"
        )
    assert not (root / "projects/inside").exists()


def test_parent_replacement_does_not_create_outside(tmp_path, monkeypatch):
    import ai_agent_project.desktop.project_directory as directories

    parent = tmp_path / "parent"
    parent.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    original = directories.open_directory_nofollow
    calls = 0

    def replace(path):
        nonlocal calls
        calls += 1
        if calls == 2:
            parent.rename(tmp_path / "old-parent")
            parent.symlink_to(outside, target_is_directory=True)
        return original(path)

    monkeypatch.setattr(directories, "open_directory_nofollow", replace)
    with pytest.raises(DesktopError):
        create_directory(parent, "project")
    assert list(outside.iterdir()) == []


def test_junction_signal_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "is_junction", lambda p: p == tmp_path)
    with pytest.raises(DesktopError):
        checked_directory(tmp_path)


def test_os_picker_labels_and_selected_directory(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QDialog, QFileDialog

    from ai_agent_project.desktop_app.dialogs import choose_directory, directory_dialog
    from ai_agent_project.desktop_app.strings import install_qt_translation

    install_qt_translation(qapp)
    dialog = directory_dialog(None, "프로젝트 폴더 선택", str(tmp_path))
    assert not dialog.testOption(QFileDialog.Option.DontUseNativeDialog)
    assert dialog.testOption(QFileDialog.Option.DontResolveSymlinks)
    assert dialog.labelText(QFileDialog.DialogLabel.LookIn) == "찾을 위치"
    assert dialog.labelText(QFileDialog.DialogLabel.Accept) == "선택"
    selected = tmp_path / "소스 폴더"
    selected.mkdir()
    dialog.setDirectory(str(selected))
    monkeypatch.setattr(
        "ai_agent_project.desktop_app.dialogs.directory_dialog", lambda *args: dialog
    )
    dialog.selectFile(str(selected))
    QTimer.singleShot(0, lambda: dialog.done(QDialog.DialogCode.Accepted))
    assert choose_directory(None, "선택") == str(selected)


def test_readonly_folder_actions_stay_available_and_do_not_record_events(
    qapp, production, monkeypatch
):
    from PySide6.QtWidgets import QApplication

    from ai_agent_project.desktop_app.developer_workspace import DeveloperWorkspacePanel

    service, _, parent, _, _ = production
    pid = service.create_project(
        "request", parent_directory=parent, folder_name="readonly"
    )
    service.confirm_project_mode(pid, WorkMode.DEVELOPER, ProjectMode.NEW)
    rid = service.create_developer_run(pid)
    service.bind_developer_run(pid, rid)
    window = MainWindow(service)
    window.select_project(pid)
    window.navigate("Developer")
    panel = window.pages["Developer"].findChild(DeveloperWorkspacePanel)
    recorded = service.get_developer_events(pid)
    calls = []
    monkeypatch.setattr(
        window.folder_opener, "_start", lambda *args: calls.append(args)
    )
    monkeypatch.setattr(
        "ai_agent_project.desktop_app.folder_opener.platform.release", lambda: "Linux"
    )
    monkeypatch.setenv("DISPLAY", ":fixture")
    panel.open_folder()
    panel.open_folder()
    assert len(calls) == 1 and window.folder_opener.busy
    window.refresh()
    new = window.pages["Developer"].findChild(DeveloperWorkspacePanel)
    assert not new.open_button.isEnabled()
    window._worker = object()
    window._set_mutation_controls()
    copy = new.findChild(QPushButton, "copyWorkspacePath")
    assert copy.isEnabled()
    copy.click()
    assert QApplication.clipboard().text() == str(parent / "readonly")
    assert service.get_developer_events(pid) == recorded
    window.folder_opener._finish(True, "fixture")
    window._worker = None
    window.close()
