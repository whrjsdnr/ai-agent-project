"""Launch with uv run ai-agent-desktop."""

import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from ai_agent_project.desktop_app.application import build_desktop_application
from ai_agent_project.desktop_app.resources import application_version, resource_path
from ai_agent_project.desktop_app.window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("AI Agent")
    try:
        app.setApplicationVersion(application_version())
        app.setWindowIcon(QIcon(str(resource_path("ai-agent.svg"))))
        if "--packaging-smoke" in sys.argv:
            from ai_agent_project.desktop_app.packaging_smoke import run_smoke

            return run_smoke(app)
        service = build_desktop_application()
        window = MainWindow(service)
        window.show()
        return app.exec()
    except Exception:  # noqa: BLE001 -- no private exception text in windowed startup
        from ai_agent_project.paths import runtime_paths

        try:
            diagnostic = runtime_paths().data / "logs" / "startup.log"
            diagnostic.parent.mkdir(parents=True, exist_ok=True)
            diagnostic.write_text(
                "Application startup failed. Check installation and user-directory access.\n",
                encoding="utf-8",
            )
        except OSError:
            pass  # The GUI message below remains available if logging is unavailable.
        QMessageBox.critical(
            None,
            "AI Agent",
            "Cannot start AI Agent. Check installation and user-directory access.",
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
