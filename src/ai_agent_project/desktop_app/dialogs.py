"""Explicit input collection only; dialogs never invoke services."""

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from ai_agent_project.agent.research import WorkMode
from ai_agent_project.agent.upgrade import ProjectMode
from ai_agent_project.desktop_app.strings import tr, value


def directory_dialog(parent, title: str, initial: str = "") -> QFileDialog:
    dialog = QFileDialog(parent, title, initial)
    dialog.setFileMode(QFileDialog.FileMode.Directory)
    dialog.setOption(QFileDialog.Option.ShowDirsOnly, True)
    dialog.setOption(QFileDialog.Option.DontResolveSymlinks, True)
    for name, text in (
        (QFileDialog.DialogLabel.LookIn, "찾을 위치"),
        (QFileDialog.DialogLabel.FileName, "프로젝트 폴더"),
        (QFileDialog.DialogLabel.FileType, "폴더 유형"),
        (QFileDialog.DialogLabel.Accept, "선택"),
        (QFileDialog.DialogLabel.Reject, "취소"),
    ):
        dialog.setLabelText(name, text)
    # Qt fallback's directory-type text comes from the host MIME database.
    # This column adds no information to a folder-only picker.
    for tree in dialog.findChildren(QTreeView):
        tree.hideColumn(2)
    return dialog


def choose_directory(parent, title: str) -> str:
    dialog = directory_dialog(parent, title)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        paths = dialog.selectedFiles()
        return paths[0] if paths else ""
    return ""


class InputDialog(QDialog):
    def __init__(self, title: str, action: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr(title))
        self.resize(640, 440)
        self.layout = QVBoxLayout(self)
        self.form = QFormLayout()
        self.layout.addLayout(self.form)
        self.confirm = QPushButton(tr(action))
        self.confirm.setProperty("primary", True)
        self.confirm.clicked.connect(self.accept)
        self.layout.addWidget(self.confirm)
        cancel = QPushButton(tr("Cancel"))
        cancel.clicked.connect(self.reject)
        self.layout.addWidget(cancel)


class CreateProjectDialog(InputDialog):
    def __init__(self, parent=None) -> None:
        super().__init__("New Project", "Request Mode Proposal", parent)
        self.title = QLineEdit()
        self.request = QPlainTextEdit()
        self.form.addRow(tr("Title"), self.title)
        self.parent_directory = QLineEdit()
        self.parent_directory.setReadOnly(True)
        self.parent_directory.setObjectName("projectParentDirectory")
        self.folder_name = QLineEdit()
        self.folder_name.setObjectName("projectFolderName")
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.parent_directory)
        browse = QPushButton("폴더 선택")
        browse.setObjectName("browseProjectParent")
        browse.clicked.connect(self.choose_parent)
        layout.addWidget(browse)
        self.form.addRow("저장할 상위 폴더", row)
        self.form.addRow("프로젝트 폴더명", self.folder_name)
        self.parent_directory.textChanged.connect(self.update_confirm)
        self.folder_name.textChanged.connect(self.update_confirm)
        self.form.addRow(tr("Request / description"), self.request)
        self.form.addRow(
            tr(QLabel(tr("A proposal is created first. Confirm its modes separately.")))
        )
        self.confirm.setEnabled(False)
        self.request.textChanged.connect(self.update_confirm)

    def update_confirm(self) -> None:
        self.confirm.setEnabled(
            bool(
                self.request.toPlainText().strip()
                and self.parent_directory.text()
                and self.folder_name.text().strip()
            )
        )

    def choose_parent(self) -> None:
        directory = choose_directory(self, "저장할 상위 폴더 선택")
        if directory:
            self.parent_directory.setText(directory)


class ModeConfirmationDialog(InputDialog):
    def __init__(self, view, parent=None) -> None:
        super().__init__("Confirm Project Modes", "Confirm Project Modes", parent)
        self.work = QComboBox()
        for mode in WorkMode:
            self.work.addItem(value(mode.value), mode.value)
        self.work.setCurrentIndex(self.work.findData(view.proposed_work_mode))
        self.mode = QComboBox()
        for mode in ProjectMode:
            self.mode.addItem(value(mode.value), mode.value)
        self.mode.setCurrentIndex(self.mode.findData(view.proposed_project_mode))
        self.form.addRow(tr("Proposed WorkMode"), self.work)
        self.form.addRow(tr("Proposed ProjectMode"), self.mode)


class DirectionSelectionDialog(InputDialog):
    def __init__(self, directions, parent=None) -> None:
        super().__init__("Research Direction", "Select Direction", parent)
        self.directions = directions
        self.choices = QListWidget()
        for d in directions:
            self.choices.addItem(tr(f"{d.title}\n{d.question}"))
        self.form.addRow(tr(self.choices))
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
        self.form.addRow(tr("Your observations / results"), self.text)
        self.form.addRow(
            tr(
                QLabel(
                    tr(
                        "Submitting records your observations. Analysis requires a separate action."
                    )
                )
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
        self.form.addRow(tr(label), self.text)
        self.confirm.setEnabled(False)
        self.text.textChanged.connect(
            lambda: self.confirm.setEnabled(bool(self.text.toPlainText().strip()))
        )


class CreatedRunDialog(InputDialog):
    def __init__(self, domain: str, run_id: str, parent=None) -> None:
        super().__init__("Run Created", f"연결: {value(domain)} 실행", parent)
        identity = QLineEdit(run_id)
        identity.setReadOnly(True)
        self.form.addRow(tr("Run ID (copy to retain if you cancel)"), identity)
        self.form.addRow(
            tr(
                QLabel(
                    tr(
                        "The run is saved. Binding requires your explicit confirmation below."
                    )
                )
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
        self.decision.addItem(tr("Choose a decision"), None)
        for choice in CheckpointDecision:
            self.decision.addItem(tr(value(choice.value)), choice.value)
        self.note = QPlainTextEdit()
        self.form.addRow(
            tr(
                QLabel(
                    tr(
                        "Review phase progress and acceptance artifacts before deciding."
                    )
                )
            )
        )
        self.form.addRow(tr("Decision"), self.decision)
        self.form.addRow(tr("Optional note"), self.note)
        self.confirm.setEnabled(False)
        self.decision.currentIndexChanged.connect(
            lambda _: self.confirm.setEnabled(self.decision.currentData() is not None)
        )
