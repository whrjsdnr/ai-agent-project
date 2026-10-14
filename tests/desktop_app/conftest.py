import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"

# Reuse the real persisted, provider-free Phase 6B seed.
import importlib.util
import sys
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

_spec = importlib.util.spec_from_file_location(
    "desktop_seed", Path(__file__).parents[1] / "desktop" / "conftest.py"
)
_seed = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _seed
_spec.loader.exec_module(_seed)
setup = _seed.setup


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def nonblocking_errors(monkeypatch):
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Ok
    )
    monkeypatch.setattr(
        QMessageBox, "information", lambda *args: QMessageBox.StandardButton.Ok
    )


@pytest.fixture
def research_seed():
    spec = importlib.util.spec_from_file_location(
        "implementation_seed",
        Path(__file__).parents[1] / "agent" / "test_research_implementation.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def developer_seed():
    return _seed._developer_run
