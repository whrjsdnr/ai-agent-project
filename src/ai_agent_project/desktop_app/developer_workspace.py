"""Public read-only workspace panel; every path is resolved by the facade."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QGroupBox,
    QPlainTextEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from ai_agent_project.desktop.errors import DesktopError
from ai_agent_project.desktop_app.strings import tr, value
from ai_agent_project.desktop_app.widgets import label


class DeveloperWorkspacePanel(QGroupBox):
    def __init__(self, window, project_id: str) -> None:
        super().__init__(tr("Workspace · current disk files"))
        self.setObjectName("developerWorkspace")
        self.window = window
        self.project_id = project_id
        layout = QVBoxLayout(self)
        try:
            view = window.service.get_developer_workspace(project_id)
        except DesktopError as error:
            layout.addWidget(label(tr(error.message)))
            return
        self.absolute_path = view.absolute_path
        path = label(view.absolute_path)
        path.setObjectName("workspacePath")
        layout.addWidget(path)
        layout.addWidget(
            label(tr(f"실행: {view.run_id} · 계획: {value(view.plan_status)}"))
        )
        layout.addWidget(
            label(
                tr(
                    "Plan entries are intentions. Present means a file exists now; shared workspace files cannot be attributed to this run."
                )
            )
        )
        button = QPushButton(tr("Open Workspace Folder"))
        button.setObjectName("openWorkspaceFolder")
        button.setEnabled(view.exists and not window.folder_opener.busy)
        button.clicked.connect(self.open_folder)
        layout.addWidget(button)
        self.open_button = button
        self.opener = window.folder_opener
        self.opener.busy_changed.connect(self.folder_busy_changed)
        self.opener.finished.connect(self.folder_result)
        copy = QPushButton("작업 폴더 경로 복사")
        copy.setObjectName("copyWorkspacePath")
        copy.clicked.connect(
            lambda: QApplication.clipboard().setText(view.absolute_path)
        )
        layout.addWidget(copy)
        self.tree = QTreeWidget()
        self.tree.setObjectName("workspaceFiles")
        self.tree.setHeaderLabels([tr(s) for s in ("File", "Disk", "Plan")])
        self.tree.setMinimumHeight(180)
        self.tree.setColumnWidth(0, 350)
        directories: dict[str, QTreeWidgetItem] = {}
        for entry in view.files:
            parts = entry.path.split("/")
            parent = self.tree.invisibleRootItem()
            for index, part in enumerate(parts[:-1]):
                key = "/".join(parts[: index + 1])
                if key not in directories:
                    directories[key] = QTreeWidgetItem(parent, [part])
                parent = directories[key]
            item = QTreeWidgetItem(
                parent,
                [
                    parts[-1],
                    tr("Present" if entry.exists else "No saved file"),
                    tr("Planned") if entry.planned else "—",
                ],
            )
            item.setData(0, Qt.ItemDataRole.UserRole, entry.path)
        self.tree.itemSelectionChanged.connect(self.inspect_selected)
        layout.addWidget(self.tree)
        if not view.exists:
            layout.addWidget(
                label(
                    tr(
                        "Workspace folder does not exist. Saved run history does not imply saved files."
                    )
                )
            )
        elif not any(entry.exists for entry in view.files):
            layout.addWidget(
                label(
                    tr(
                        "No public saved files found. Private and generated files are excluded."
                    )
                )
            )
        if view.truncated:
            layout.addWidget(
                label(tr("File listing is limited; some files are not shown."))
            )
        self.message = label(tr("Select a file to inspect its current disk content."))
        layout.addWidget(self.message)
        self.code = QPlainTextEdit()
        self.code.setObjectName("workspaceCode")
        self.code.setReadOnly(True)
        self.code.setMinimumHeight(220)
        layout.addWidget(self.code)

    def inspect_selected(self) -> None:
        self.code.clear()
        items = self.tree.selectedItems()
        path = items[0].data(0, Qt.ItemDataRole.UserRole) if items else None
        if not path:
            self.message.setText(
                tr("Select a file to inspect its current disk content.")
            )
            return
        try:
            view = self.window.service.get_developer_workspace_code(
                self.project_id, path
            )
            self.message.setText(tr(view.message))
            self.code.setPlainText(view.content)
        except DesktopError as error:
            self.message.setText(tr(error.message))

    def folder_busy_changed(self, busy: bool) -> None:
        self.open_button.setEnabled(not busy)

    def folder_result(self, success: bool, message: str) -> None:
        if success:
            self.window.statusBar().showMessage(message)
        else:
            self.window.show_error(message)

    def open_folder(self) -> None:
        if self.opener.busy:
            return
        try:
            folder = self.window.service.get_developer_workspace_folder(self.project_id)
            self.opener.open(folder)
        except DesktopError as error:
            self.window.show_error(
                f"{tr(error.message)}\n작업 폴더: {self.absolute_path}"
            )
