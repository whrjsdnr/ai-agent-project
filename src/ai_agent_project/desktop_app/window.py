"""Main window and explicit service command routing."""

from collections.abc import Callable

from PySide6.QtCore import QThreadPool, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ai_agent_project.agent.research import ResearchResultSubmission, WorkMode
from ai_agent_project.agent.upgrade import ProjectMode
from ai_agent_project.desktop import DesktopService
from ai_agent_project.desktop.errors import DesktopError
from ai_agent_project.desktop.models import DesktopConnectionView
from ai_agent_project.desktop_app.application import PresentationState
from ai_agent_project.desktop_app.dialogs import (
    CreatedRunDialog,
    CreateProjectDialog,
    DirectionSelectionDialog,
    ModeConfirmationDialog,
    ResearchResultsDialog,
    TextInputDialog,
)
from ai_agent_project.desktop_app.pages import (
    ArtifactsPage,
    ProjectPage,
    ProjectsPage,
    SettingsPage,
)
from ai_agent_project.desktop_app.theme import STYLESHEET
from ai_agent_project.desktop_app.widgets import label
from ai_agent_project.desktop_app.worker import OperationWorker


class MainWindow(QMainWindow):
    NAVIGATION = (
        "Dashboard",
        "Projects",
        "Developer",
        "Researcher",
        "Hybrid",
        "Artifacts",
        "Settings",
    )

    def __init__(self, service: DesktopService) -> None:
        super().__init__()
        self.service = service
        self.state = PresentationState()
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self._worker = None
        self._on_success = None
        self.setWindowTitle("AI Agent — Local Workspace")
        self.resize(1200, 760)
        self.setMinimumSize(900, 600)
        self.setStyleSheet(STYLESHEET)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        self.topbar = label("AI Agent  /  Local Workspace")
        top = QHBoxLayout()
        top.addWidget(self.topbar, 1)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        top.addWidget(refresh)
        layout.addLayout(top)
        body = QHBoxLayout()
        layout.addLayout(body)
        self.sidebar = QListWidget()
        self.sidebar.addItems(self.NAVIGATION)
        self.sidebar.setFixedWidth(180)
        body.addWidget(self.sidebar)
        self.stack = QStackedWidget()
        body.addWidget(self.stack, 1)
        self.pages = {
            "Dashboard": ProjectsPage(self, True),
            "Projects": ProjectsPage(self),
        }
        self.pages.update(
            {
                name: ProjectPage(self, name)
                for name in ("Developer", "Researcher", "Hybrid", "Project Detail")
            }
        )
        self.pages["Artifacts"] = ArtifactsPage(self)
        self.pages["Settings"] = SettingsPage(self)
        self.page_indices = {}
        for name, page in self.pages.items():
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(page)
            self.page_indices[name] = self.stack.addWidget(scroll)
        self.busy_indicator = QProgressBar()
        self.busy_indicator.setRange(0, 0)
        self.busy_indicator.hide()
        self.statusBar().addPermanentWidget(self.busy_indicator)
        self.sidebar.currentRowChanged.connect(
            lambda row: self.navigate(self.NAVIGATION[row]) if row >= 0 else None
        )
        self.sidebar.setCurrentRow(0)

    @property
    def busy(self) -> bool:
        return self._worker is not None

    def navigate(self, name: str) -> None:
        if self.busy:
            return
        self.sidebar.blockSignals(True)
        self.sidebar.setCurrentRow(
            self.NAVIGATION.index(name)
            if name in self.NAVIGATION
            else self.NAVIGATION.index("Projects")
        )
        self.sidebar.blockSignals(False)
        self.state.current_page = name
        self.stack.setCurrentIndex(self.page_indices[name])
        self.refresh()

    def select_project(self, project_id: str) -> None:
        self.state.selected_project_id = project_id
        self.navigate("Project Detail")

    def refresh(self) -> None:
        if self.busy:
            return
        try:
            self.pages[self.state.current_page].refresh()
            provider = self.service.get_provider_config()
            self.topbar.setText(
                f"AI Agent  /  Local Workspace     |     {provider.model} · Credential {'configured' if provider.credential_configured else 'missing — open Settings'}"
            )
        except DesktopError as error:
            self.show_error(error.message)
        except Exception:  # noqa: BLE001 -- UI boundary never exposes raw errors
            self.show_error(
                "Unable to load this view. Check local configuration and refresh."
            )

    def show_error(self, message: str) -> None:
        self.statusBar().showMessage(message)
        QMessageBox.warning(self, "AI Agent", message)

    def submit(
        self,
        operation: Callable[[], object],
        on_success: Callable[[object], None] | None = None,
    ) -> None:
        if self.busy:
            return
        self._on_success = on_success
        self._worker = OperationWorker(operation)
        self._worker.signals.succeeded.connect(self._succeeded)
        self._worker.signals.failed.connect(self._failed)
        self.centralWidget().setEnabled(False)
        self.busy_indicator.show()
        self.statusBar().showMessage("Working on your requested operation…")
        self.pool.start(self._worker)

    def _finish(self):
        callback = self._on_success
        self._worker = None
        self._on_success = None
        self.centralWidget().setEnabled(True)
        self.busy_indicator.hide()
        self.refresh()
        return callback

    @Slot(object)
    def _succeeded(self, result) -> None:
        callback = self._finish()
        self.statusBar().showMessage("Requested operation completed.")
        if callback:
            callback(result)

    @Slot(str)
    def _failed(self, message) -> None:
        self._finish()
        self.show_error(message)

    def connection_result(self, result: DesktopConnectionView) -> None:
        # The facade supplies normalized text; never display provider exceptions.
        self.statusBar().showMessage(
            f"{'Success' if result.success else 'Failure'}: {result.message}"
        )

    def create_project(self) -> None:
        dialog = CreateProjectDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            request, title = dialog.request.toPlainText(), dialog.title.text()
            self.submit(
                lambda: self.service.create_project(request, title=title or None),
                self.select_project,
            )

    def create_run(self, domain: str) -> None:
        pid = self.state.selected_project_id
        command = (
            self.service.create_developer_run
            if domain == "developer"
            else self.service.create_research_run
        )
        self.submit(
            lambda: command(pid),
            lambda run_id: self.offer_binding(domain, pid, run_id),
        )

    def offer_binding(self, domain: str, project_id: str, run_id: str) -> None:
        dialog = CreatedRunDialog(domain, run_id, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            command = (
                self.service.bind_developer_run
                if domain == "developer"
                else self.service.bind_research_run
            )
            self.submit(lambda: command(project_id, run_id))

    def request_action(self, action: str) -> None:
        pid = self.state.selected_project_id
        if not pid or self.busy:
            return
        try:
            view = self.service.get_project_view(pid)
            if action == "confirm_mode":
                dialog = ModeConfirmationDialog(view, self)
                if dialog.exec() == QDialog.DialogCode.Accepted:
                    work, mode = (
                        WorkMode(dialog.work.currentText()),
                        ProjectMode(dialog.mode.currentText()),
                    )
                    self.submit(
                        lambda: self.service.confirm_project_mode(pid, work, mode)
                    )
            elif action in ("bind_developer_run", "bind_research_run"):
                dialog = TextInputDialog(
                    "Bind Run", action.replace("_", " ").title(), "Run ID", self
                )
                if dialog.exec() == QDialog.DialogCode.Accepted:
                    run_id = dialog.text.toPlainText().strip()
                    command = getattr(self.service, action)
                    self.submit(lambda: command(pid, run_id))
            elif action == "select_research_direction":
                dialog = DirectionSelectionDialog(view.researcher.directions, self)
                if dialog.exec() == QDialog.DialogCode.Accepted and dialog.direction_id:
                    direction = dialog.direction_id
                    self.submit(
                        lambda: self.service.select_research_direction(pid, direction)
                    )
            elif action == "provide_research_results":
                dialog = ResearchResultsDialog(self)
                if dialog.exec() == QDialog.DialogCode.Accepted:
                    lane = view.researcher
                    submission = ResearchResultSubmission(
                        research_run_id=lane.run_id,
                        approved_plan_version=lane.approved_plan_version,
                        implementation_plan_version=lane.implementation_plan_version,
                        user_observations=(dialog.text.toPlainText(),),
                    )
                    self.submit(
                        lambda: self.service.provide_research_results(pid, submission)
                    )
            elif action in (
                "approve_developer_plan",
                "continue_developer",
                "approve_research_plan",
                "continue_researcher",
                "complete_project",
            ):
                command = getattr(self.service, action)
                self.submit(lambda: command(pid))
            else:
                self.show_error("This action is unavailable in this desktop version.")
        except DesktopError as error:
            self.show_error(error.message)
        except Exception:  # noqa: BLE001 -- UI boundary never exposes raw errors
            self.show_error(
                "Unable to prepare this action. Refresh and check its required input."
            )

    def bootstrap(self, handoff_id: str) -> None:
        dialog = TextInputDialog(
            "Developer From Research",
            "Create Developer Run From Research",
            "Developer request",
            self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            pid, request = self.state.selected_project_id, dialog.text.toPlainText()
            self.submit(
                lambda: self.service.bootstrap_developer_from_handoff(
                    pid, handoff_id, request
                )
            )

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.busy:
            self.statusBar().showMessage(
                "Wait for the requested operation to finish before closing."
            )
            event.ignore()
            return
        self.pool.waitForDone()
        event.accept()
