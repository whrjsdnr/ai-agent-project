"""Explicit input collection only; dialogs never invoke services."""

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from ai_agent_project.agent.research import WorkMode
from ai_agent_project.agent.upgrade import ProjectMode


class InputDialog(QDialog):
    def __init__(self, title: str, action: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(520, 360)
        self.layout = QVBoxLayout(self)
        self.form = QFormLayout()
        self.layout.addLayout(self.form)
        self.confirm = QPushButton(action)
        self.confirm.setProperty("primary", True)
        self.confirm.clicked.connect(self.accept)
        self.layout.addWidget(self.confirm)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self.layout.addWidget(cancel)


class CreateProjectDialog(InputDialog):
    def __init__(self, parent=None) -> None:
        super().__init__("New Project", "Request Mode Proposal", parent)
        self.title = QLineEdit()
        self.request = QPlainTextEdit()
        self.form.addRow("Title", self.title)
        self.form.addRow("Request / description", self.request)
        self.form.addRow(
            QLabel("A proposal is created first. Confirm its modes separately.")
        )
        self.confirm.setEnabled(False)
        self.request.textChanged.connect(
            lambda: self.confirm.setEnabled(bool(self.request.toPlainText().strip()))
        )


class ModeConfirmationDialog(InputDialog):
    def __init__(self, view, parent=None) -> None:
        super().__init__("Confirm Project Modes", "Confirm Project Modes", parent)
        self.work = QComboBox()
        self.work.addItems([v.value for v in WorkMode])
        self.work.setCurrentText(view.proposed_work_mode)
        self.mode = QComboBox()
        self.mode.addItems([v.value for v in ProjectMode])
        self.mode.setCurrentText(view.proposed_project_mode)
        self.form.addRow("Proposed WorkMode", self.work)
        self.form.addRow("Proposed ProjectMode", self.mode)


class DirectionSelectionDialog(InputDialog):
    def __init__(self, directions, parent=None) -> None:
        super().__init__("Research Direction", "Select Direction", parent)
        self.directions = directions
        self.choices = QListWidget()
        for d in directions:
            self.choices.addItem(f"{d.title}\n{d.question}")
        self.form.addRow(self.choices)
        self.confirm.setEnabled(False)
        self.choices.currentRowChanged.connect(
            lambda row: self.confirm.setEnabled(row >= 0)
        )

    @property
    def direction_id(self) -> str | None:
        row = self.choices.currentRow()
        return self.directions[row].direction_id if row >= 0 else None


class ResearchResultsDialog(InputDialog):
    def __init__(self, parent=None) -> None:
        super().__init__("Research Results", "Provide Research Results", parent)
        self.text = QPlainTextEdit()
        self.form.addRow("Your observations / results", self.text)
        self.form.addRow(
            QLabel(
                "Submitting records your observations. Analysis requires a separate action."
            )
        )
        self.confirm.setEnabled(False)
        self.text.textChanged.connect(
            lambda: self.confirm.setEnabled(bool(self.text.toPlainText().strip()))
        )


class TextInputDialog(InputDialog):
    def __init__(self, title, action, label, parent=None) -> None:
        super().__init__(title, action, parent)
        self.text = QPlainTextEdit()
        self.form.addRow(label, self.text)
        self.confirm.setEnabled(False)
        self.text.textChanged.connect(
            lambda: self.confirm.setEnabled(bool(self.text.toPlainText().strip()))
        )


class CreatedRunDialog(InputDialog):
    def __init__(self, domain: str, run_id: str, parent=None) -> None:
        super().__init__("Run Created", f"Bind {domain.title()} Run", parent)
        identity = QLineEdit(run_id)
        identity.setReadOnly(True)
        self.form.addRow("Run ID (copy to retain if you cancel)", identity)
        self.form.addRow(
            QLabel(
                "The run is saved. Binding requires your explicit confirmation below."
            )
        )


class DeveloperCheckpointDialog(InputDialog):
    """Collect an explicit decision; the existing checkpoint service authorizes it."""

    def __init__(self, parent=None):
        from ai_agent_project.agent.checkpoint import CheckpointDecision

        super().__init__(
            "Review Developer Checkpoint", "Submit Checkpoint Decision", parent
        )
        self.decision = QComboBox()
        self.decision.addItem("Choose a decision", None)
        for choice in CheckpointDecision:
            self.decision.addItem(choice.value.replace("_", " ").title(), choice.value)
        self.note = QPlainTextEdit()
        self.form.addRow(
            QLabel("Review phase progress and acceptance artifacts before deciding.")
        )
        self.form.addRow("Decision", self.decision)
        self.form.addRow("Optional note", self.note)
        self.confirm.setEnabled(False)
        self.decision.currentIndexChanged.connect(
            lambda _: self.confirm.setEnabled(self.decision.currentData() is not None)
        )
