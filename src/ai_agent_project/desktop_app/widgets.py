"""Reusable metadata and explicit pending-action presentation."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGroupBox, QLabel, QPushButton, QVBoxLayout


def label(text: str) -> QLabel:
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(True)
    widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return widget


class PendingActionWidget(QGroupBox):
    requested = Signal(str)

    def __init__(self, action, parent=None) -> None:
        super().__init__("Pending human action", parent)
        layout = QVBoxLayout(self)
        layout.addWidget(label(f"{action.title} · {action.domain}"))
        layout.addWidget(label(action.description))
        required = {
            "work_mode_and_project_mode": "Confirm WorkMode and ProjectMode",
            "run_id": "Run ID to bind",
            "direction_id": "Choose a research direction",
            "research_result_submission": "Your research observations / results",
        }.get(action.payload_kind, "Explicit confirmation")
        layout.addWidget(label(f"Required input: {required}"))
        self.button = QPushButton(action.title.title())
        self.button.setObjectName(action.action_type)
        self.button.setProperty("primary", True)
        self.button.clicked.connect(lambda: self.requested.emit(action.action_type))
        layout.addWidget(self.button)
