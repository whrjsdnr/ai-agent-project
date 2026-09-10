"""Launch with uv run ai-agent-desktop."""

import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from ai_agent_project.desktop_app.application import build_desktop_application
from ai_agent_project.desktop_app.window import MainWindow


def main() -> int:
    try:
        service = build_desktop_application()
    except Exception:  # noqa: BLE001 -- startup errors can contain private filesystem data
        app = QApplication(sys.argv)
        QMessageBox.critical(
            None,
            "AI Agent",
            "Cannot open local application storage. Check directory access and try again.",
        )
        return 1
    app = QApplication(sys.argv)
    app.setApplicationName("AI Agent")
    window = MainWindow(service)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
