"""Opt-in frozen bootstrap acceptance; no provider or workflow mutation."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from ai_agent_project.desktop_app.application import build_desktop_application
from ai_agent_project.desktop_app.resources import application_version, resource_path
from ai_agent_project.desktop_app.window import MainWindow
from ai_agent_project.paths import is_frozen, runtime_paths


def run_smoke(app: QApplication) -> int:
    with TemporaryDirectory(prefix="ai-agent-smoke-") as temporary:
        window = MainWindow(build_desktop_application(Path(temporary)))
        errors = []
        window.show_error = errors.append
        window.show()
        result = {}

        def check() -> None:
            try:
                for name in ("Dashboard", "Projects", "Settings"):
                    window.navigate(name)
                    assert window.state.current_page == name
                assert not errors
                assert resource_path("ai-agent.svg").is_file()
                result.update(
                    success=True,
                    frozen=is_frozen(),
                    version=application_version(),
                    pages=["Dashboard", "Projects", "Settings"],
                )
            except Exception:  # noqa: BLE001 -- smoke output contains only fixed metadata
                result.update(success=False)
            finally:
                window.close()

        QTimer.singleShot(0, check)
        app.exec()
        target = runtime_paths().cache / "packaging-smoke.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result), encoding="utf-8")
        return 0 if result.get("success") else 1
