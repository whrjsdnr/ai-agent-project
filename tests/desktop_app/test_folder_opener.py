"""Real QProcess fixtures exercise dispatch without installing a file manager."""

import os
from time import monotonic

import pytest
from PySide6.QtTest import QTest

from ai_agent_project.desktop_app.folder_opener import FolderOpener


def wait(qapp, condition):
    deadline = monotonic() + 3
    while not condition() and monotonic() < deadline:
        qapp.processEvents()
        QTest.qWait(5)
    assert condition()


@pytest.fixture
def commands(tmp_path, monkeypatch):
    directory = tmp_path / "folder with spaces"
    directory.mkdir()
    binary = tmp_path / "bin"
    binary.mkdir()
    monkeypatch.setenv("PATH", str(binary) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("DISPLAY", ":fixture")
    monkeypatch.setattr(
        "ai_agent_project.desktop_app.folder_opener.platform.release", lambda: "Linux"
    )

    def script(name, body):
        target = binary / name
        target.write_text("#!/bin/sh\n" + body)
        target.chmod(0o700)

    script("xdg-mime", "printf 'fixture.desktop\\n'\n")
    return directory, script


@pytest.mark.parametrize("exit_code", [0, 7])
def test_linux_process_success_failure_and_path(qapp, commands, exit_code):
    directory, script = commands
    script("xdg-open", f"exit {exit_code}\n")
    opener = FolderOpener()
    result = []
    opener.finished.connect(lambda *args: result.append(args))
    opener.open(directory)
    wait(qapp, lambda: bool(result))
    assert result[0][0] == (exit_code == 0)
    assert str(directory) in result[0][1]
    assert not opener.busy


def test_no_default_handler_never_calls_opener(qapp, commands):
    directory, script = commands
    marker = directory / "called"
    script("xdg-mime", "exit 0\n")
    script("xdg-open", f'touch "{marker}"\n')
    opener = FolderOpener()
    result = []
    opener.finished.connect(lambda *args: result.append(args))
    opener.open(directory)
    wait(qapp, lambda: bool(result))
    assert not marker.exists() and not result[0][0]
    assert "연결되어 있지 않습니다" in result[0][1]


def test_timeout_duplicate_calls_and_output_discard(qapp, commands):
    directory, script = commands
    marker = directory / "called"
    script(
        "xdg-open",
        f'echo once >> "{marker}"\nprintf "private-provider-context" >&2\nexec sleep 2\n',
    )
    opener = FolderOpener(timeout_ms=80)
    result = []
    opener.finished.connect(lambda *args: result.append(args))
    opener.open(directory)
    opener.open(directory)
    wait(qapp, lambda: bool(result))
    assert marker.read_text() == "once\n"
    assert not result[0][0] and "초과" in result[0][1]
    assert "private-provider-context" not in result[0][1]
    assert len(result) == 1


def test_start_failure(qapp, commands):
    directory, script = commands
    # Existing executable with an unavailable interpreter.
    script("xdg-open", "exit 0\n")
    from pathlib import Path

    path = Path(os.environ["PATH"].split(os.pathsep)[0]) / "xdg-open"
    path.write_text("#!/missing/interpreter\n")
    opener = FolderOpener()
    result = []
    opener.finished.connect(lambda *args: result.append(args))
    opener.open(directory)
    wait(qapp, lambda: bool(result))
    assert not result[0][0] and "시작할 수 없습니다" in result[0][1]


def test_wsl_safe_conversion_and_explorer_arguments(qapp, commands, monkeypatch):
    directory, script = commands
    marker = directory / "arguments"
    script("wslpath", "printf 'C:\\\\fixture path\\n'\n")
    script("explorer.exe", f'printf "%s" "$1" > "{marker}"\n')
    monkeypatch.setattr(
        "ai_agent_project.desktop_app.folder_opener.platform.release",
        lambda: "microsoft-standard-WSL2",
    )
    opener = FolderOpener()
    result = []
    opener.finished.connect(lambda *args: result.append(args))
    opener.open(directory)
    wait(qapp, lambda: bool(result))
    assert result[0][0] and marker.read_text() == "C:\\fixture path"


def test_headless_missing_directory_and_permission(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "ai_agent_project.desktop_app.folder_opener.platform.release", lambda: "Linux"
    )
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    opener = FolderOpener()
    result = []
    opener.finished.connect(lambda *args: result.append(args))
    opener.open(tmp_path)
    assert "GUI" in result[-1][1] and not result[-1][0]
    opener.open(tmp_path / "missing")
    assert "없거나 접근할 수 없습니다" in result[-1][1]
    monkeypatch.setattr(
        "ai_agent_project.desktop.project_directory.os.access", lambda *args: False
    )
    opener.open(tmp_path)
    assert not result[-1][0]


def test_missing_file_manager_commands(qapp, commands, monkeypatch):
    directory, _script = commands
    monkeypatch.setattr(
        "ai_agent_project.desktop_app.folder_opener.shutil.which", lambda name: None
    )
    opener = FolderOpener()
    result = []
    opener.finished.connect(lambda *args: result.append(args))
    opener.open(directory)
    assert "기본 파일 관리자를 사용할 수 없습니다" in result[-1][1]


def test_windows_dispatch_is_preserved_with_mock(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "ai_agent_project.desktop_app.folder_opener.sys.platform", "win32"
    )
    requested = []
    monkeypatch.setattr(
        "ai_agent_project.desktop_app.folder_opener.QDesktopServices.openUrl",
        lambda url: requested.append(url.toLocalFile()) or True,
    )
    opener = FolderOpener()
    result = []
    opener.finished.connect(lambda *args: result.append(args))
    opener.open(tmp_path)
    assert requested == [str(tmp_path)] and result[0][0]


def test_wsl_bad_conversion_never_calls_explorer(qapp, commands, monkeypatch):
    directory, script = commands
    marker = directory / "opened"
    script("wslpath", "printf '../unsafe\\n'\n")
    script("explorer.exe", f'touch "{marker}"\n')
    monkeypatch.setattr(
        "ai_agent_project.desktop_app.folder_opener.platform.release",
        lambda: "microsoft-standard-WSL2",
    )
    opener = FolderOpener()
    result = []
    opener.finished.connect(lambda *args: result.append(args))
    opener.open(directory)
    wait(qapp, lambda: bool(result))
    assert not result[0][0] and "변환할 수 없습니다" in result[0][1]
    assert not marker.exists()


def test_wsl_explorer_exit_one_is_outcome_unknown(qapp, commands, monkeypatch):
    directory, script = commands
    script("wslpath", "printf 'C:\\\\fixture path\\n'\n")
    script("explorer.exe", "exit 1\n")
    monkeypatch.setattr(
        "ai_agent_project.desktop_app.folder_opener.platform.release",
        lambda: "microsoft-standard-WSL2",
    )
    opener = FolderOpener()
    result = []
    opener.finished.connect(lambda *args: result.append(args))
    opener.open(directory)
    wait(qapp, lambda: bool(result))
    assert not result[0][0] and "창이 열렸는지 확인하세요" in result[0][1]
