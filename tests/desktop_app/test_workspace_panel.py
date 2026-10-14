"""Offscreen UI checks for disk files, plain code and folder opening."""

from PySide6.QtWidgets import QLabel, QPushButton

from ai_agent_project.agent.research import WorkMode
from ai_agent_project.desktop_app.developer_workspace import DeveloperWorkspacePanel
from ai_agent_project.desktop_app.window import MainWindow
from ai_agent_project.tools.file import FileTool


def test_developer_panel_code_and_folder(qapp, setup, monkeypatch):
    pid = setup.ids[WorkMode.DEVELOPER]
    assert (
        FileTool(setup.root)
        .execute(
            {
                "operation": "write_file",
                "path": "src/app.py",
                "content": "print('<b>plain code</b>')\n",
            }
        )
        .success
    )
    window = MainWindow(setup.desktop)
    window.select_project(pid)
    window.navigate("Developer")
    panel = window.pages["Developer"].findChild(DeveloperWorkspacePanel)
    assert panel.findChild(QLabel, "workspacePath").text() == str(setup.root.resolve())
    leaf = panel.tree.topLevelItem(0).child(0)
    panel.tree.setCurrentItem(leaf)
    assert panel.code.isReadOnly()
    assert panel.code.toPlainText() == "print('<b>plain code</b>')\n"
    opened = []
    monkeypatch.setattr(
        panel.opener,
        "open",
        lambda folder: opened.append(str(folder)),
    )
    panel.findChild(QPushButton, "openWorkspaceFolder").click()
    assert opened == [str(setup.root.resolve())]
    (setup.root / "src" / "app.py").unlink()
    panel.inspect_selected()
    assert not panel.code.toPlainText()
    assert "저장된 파일이 없습니다" in panel.message.text()
    window.close()


def test_researcher_has_no_workspace_panel(qapp, setup):
    window = MainWindow(setup.desktop)
    window.select_project(setup.ids[WorkMode.RESEARCHER])
    window.navigate("Researcher")
    assert window.pages["Researcher"].findChild(DeveloperWorkspacePanel) is None
    window.close()


def test_open_folder_is_revalidated_and_failure_is_reported(qapp, setup, monkeypatch):
    from unittest.mock import Mock

    from ai_agent_project.desktop.errors import DesktopError, DesktopErrorCode

    window = MainWindow(setup.desktop)
    pid = setup.ids[WorkMode.DEVELOPER]
    window.select_project(pid)
    window.navigate("Developer")
    panel = window.pages["Developer"].findChild(DeveloperWorkspacePanel)
    opened = Mock(return_value=False)
    errors = []
    monkeypatch.setattr(
        panel.opener,
        "open",
        opened,
    )
    monkeypatch.setattr(window, "show_error", errors.append)
    panel.open_folder()
    panel.folder_result(False, "파일 관리자를 열 수 없습니다.")
    assert "열 수 없습니다" in errors[-1]
    monkeypatch.setattr(
        setup.desktop,
        "get_developer_workspace_folder",
        Mock(
            side_effect=DesktopError(
                DesktopErrorCode.NOT_FOUND, "Workspace folder does not exist."
            )
        ),
    )
    panel.open_folder()
    assert opened.call_count == 1
    assert "작업 폴더가 없습니다" in errors[-1]
    window.close()
