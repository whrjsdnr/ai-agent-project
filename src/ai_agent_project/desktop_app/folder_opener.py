"""Non-Agent OS folder dispatch, with bounded output and no retries."""

import os
import platform
import shutil
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices

from ai_agent_project.desktop.errors import DesktopError
from ai_agent_project.desktop.project_directory import checked_directory


class FolderOpener(QObject):
    finished = Signal(bool, str)
    busy_changed = Signal(bool)

    def __init__(self, parent=None, *, timeout_ms: int = 10000) -> None:
        super().__init__(parent)
        self.busy = False
        self.folder: Path | None = None
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self._drain)
        self.process.readyReadStandardError.connect(self._discard_error)
        self.process.errorOccurred.connect(self._error)
        self.process.finished.connect(self._exited)
        self.timed_out = False
        self.stage = ""
        self.output = bytearray()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(timeout_ms)
        self.timer.timeout.connect(self._timeout)

    def open(self, folder: Path) -> None:
        if self.busy:
            return
        self.folder = folder
        try:
            checked_directory(folder)
        except DesktopError:
            self._finish(
                False,
                "작업 폴더가 없거나 접근할 수 없습니다. 경로와 권한을 확인하세요.",
            )
            return
        self.busy = True
        self.busy_changed.emit(True)
        if sys.platform == "win32":
            opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
            self._finish(
                opened,
                "Windows 파일 관리자에 열기를 요청했습니다."
                if opened
                else "Windows 파일 관리자를 실행할 수 없습니다.",
            )
        elif (
            "microsoft" in platform.release().lower()
            and shutil.which("explorer.exe")
            and shutil.which("wslpath")
        ):
            self._start("wslpath", ["-w", str(folder)], "wslpath")
        elif not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            self._finish(
                False,
                "GUI 연결이 없는 환경입니다. 경로를 복사해 파일 관리자에서 직접 여세요.",
            )
        elif not shutil.which("xdg-mime") or not shutil.which("xdg-open"):
            self._finish(
                False,
                "기본 파일 관리자를 사용할 수 없습니다. 파일 관리자 설치와 폴더 연결 설정을 확인하세요.",
            )
        else:
            self._start("xdg-mime", ["query", "default", "inode/directory"], "mime")

    def _start(self, program: str, arguments: list[str], stage: str) -> None:
        self.stage = stage
        self.output.clear()
        self.timed_out = False
        self.timer.start()
        self.process.start(program, arguments)

    def _drain(self) -> None:
        data = bytes(self.process.readAllStandardOutput())
        if self.stage in {"mime", "wslpath"}:
            self.output.extend(data[: max(0, 32768 - len(self.output))])

    def _discard_error(self) -> None:
        self.process.readAllStandardError()

    def _error(self, error: QProcess.ProcessError) -> None:
        if self.busy and error == QProcess.ProcessError.FailedToStart:
            self._finish(
                False,
                "파일 관리자 명령을 시작할 수 없습니다. 설치 상태와 실행 권한을 확인하세요.",
            )

    def _exited(self, code: int, status: QProcess.ExitStatus) -> None:
        if not self.busy:
            return
        self._drain()
        self.timer.stop()
        if self.timed_out:
            self._finish(
                False,
                "파일 관리자 응답 시간이 초과되었습니다. 경로를 복사해 직접 여세요.",
            )
            return
        if (
            self.stage == "explorer"
            and code == 1
            and status == QProcess.ExitStatus.NormalExit
        ):
            self._finish(
                False,
                "WSL Explorer가 종료 코드 1을 반환했습니다. 창이 열렸는지 확인하세요. 열리지 않았다면 경로를 복사해 직접 여세요.",
            )
            return
        if code != 0 or status != QProcess.ExitStatus.NormalExit:
            self._finish(
                False,
                "파일 관리자 호출이 실패했습니다. 폴더 연결 설정을 확인하거나 경로를 복사해 직접 여세요.",
            )
            return
        if self.stage == "mime":
            handler = self.output.decode("utf-8", errors="replace").strip()
            if not handler or "\n" in handler or not handler.endswith(".desktop"):
                self._finish(
                    False,
                    "폴더를 열 기본 파일 관리자가 연결되어 있지 않습니다. 파일 관리자 연결을 설정하거나 경로를 복사하세요.",
                )
                return
            self._start("xdg-open", [str(self.folder)], "open")
        elif self.stage == "wslpath":
            converted = self.output.decode("utf-8", errors="replace").strip()
            if (
                not converted
                or "\n" in converted
                or any(ord(c) < 32 for c in converted)
                or not (
                    converted.startswith("\\\\")
                    or len(converted) > 2
                    and converted[1:3] == ":\\"
                )
            ):
                self._finish(
                    False, "WSL 작업 폴더를 Windows 경로로 변환할 수 없습니다."
                )
                return
            self._start("explorer.exe", [converted], "explorer")
        else:
            self._finish(
                True,
                "파일 관리자에 작업 폴더 열기를 요청했습니다. 창 표시 여부는 OS에서 확인하세요.",
            )

    def _timeout(self) -> None:
        if self.busy:
            self.timed_out = True
            self.process.kill()

    def _finish(self, success: bool, message: str) -> None:
        self.timer.stop()
        self.busy = False
        self.busy_changed.emit(False)
        self.finished.emit(success, f"{message}\n작업 폴더: {self.folder}")
