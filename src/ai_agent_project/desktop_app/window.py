"""Main window and explicit service command routing."""

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QThreadPool, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
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

from ai_agent_project.agent.checkpoint import CheckpointDecision
from ai_agent_project.agent.research import ResearchResultSubmission, WorkMode
from ai_agent_project.agent.upgrade import ProjectMode
from ai_agent_project.desktop import DesktopService
from ai_agent_project.desktop.errors import DesktopError
from ai_agent_project.desktop.models import DesktopConnectionView
from ai_agent_project.desktop_app.application import PresentationState
from ai_agent_project.desktop_app.dialogs import (
    CreatedRunDialog,
    CreateProjectDialog,
    DeveloperCheckpointDialog,
    DirectionSelectionDialog,
    ModeConfirmationDialog,
    ResearchResultsDialog,
    TextInputDialog,
    choose_directory,
)
from ai_agent_project.desktop_app.pages import (
    ArtifactsPage,
    ProjectPage,
    ProjectsPage,
    SettingsPage,
)
from ai_agent_project.desktop_app.strings import install_qt_translation, tr, value
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
        "Improvements",
        "Settings",
    )

    def __init__(self, service: DesktopService) -> None:
        super().__init__()
        install_qt_translation(QApplication.instance())
        self.service = service
        self.state = PresentationState()
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self._worker = None
        from ai_agent_project.desktop_app.folder_opener import FolderOpener

        self.folder_opener = FolderOpener(self)
        self._on_success = None
        self._mutation_buttons: list[QPushButton] = []
        self.setWindowTitle(tr("AI Agent — Local Workspace"))
        self.resize(1200, 760)
        self.setMinimumSize(900, 600)
        self.setStyleSheet(STYLESHEET)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        self.topbar = label(tr("AI Agent  /  Local Workspace"))
        top = QHBoxLayout()
        top.addWidget(self.topbar, 1)
        refresh = QPushButton(tr("Refresh"))
        refresh.clicked.connect(self.refresh)
        top.addWidget(refresh)
        layout.addLayout(top)
        body = QHBoxLayout()
        layout.addLayout(body)
        self.sidebar = QListWidget()
        self.sidebar.addItems([tr(name) for name in self.NAVIGATION])
        self.sidebar.setMinimumWidth(210)
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
        from ai_agent_project.desktop_app.improvements import ImprovementsPage

        self.pages["Improvements"] = ImprovementsPage(self)
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
        try:
            self.pages[self.state.current_page].refresh()
            self._set_mutation_controls()
            provider = self.service.get_provider_config()
            self.topbar.setText(
                tr(
                    f"AI Agent / 작업 폴더     |     {provider.model} · API Key {('설정됨' if provider.credential_configured else '없음 — 설정에서 입력하세요')}"
                )
            )
        except DesktopError as error:
            self.show_error(tr(error.message))
        except Exception:  # noqa: BLE001 -- UI boundary never exposes raw errors
            self.show_error(
                tr("Unable to load this view. Check local configuration and refresh.")
            )

    def show_error(self, message: str) -> None:
        self.statusBar().showMessage(tr(message))
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
        self._set_mutation_controls()
        self.busy_indicator.show()
        self.statusBar().showMessage(tr("Working on your requested operation…"))
        self.pool.start(self._worker)

    def _set_mutation_controls(self) -> None:
        # All action buttons are disabled while reads/navigation remain available.
        read_buttons = {
            "openWorkspaceFolder",
            "copyWorkspacePath",
            "refreshWorkspace",
            "timelineEarlier",
            "timelineLive",
            "olderSnapshots",
        }
        for button in self.centralWidget().findChildren(QPushButton):
            if button.text() == tr("Refresh") or button.objectName() in read_buttons:
                continue
            if self.busy and button.isEnabled():
                button.setEnabled(False)
                self._mutation_buttons.append(button)
        if not self.busy:
            for button in self._mutation_buttons:
                try:
                    button.setEnabled(True)
                except RuntimeError:
                    pass  # The page may have been rebuilt during execution.
            self._mutation_buttons.clear()

    def _finish(self):
        callback = self._on_success
        self._worker = None
        self._on_success = None
        self._set_mutation_controls()
        self.busy_indicator.hide()
        self.refresh()
        return callback

    @Slot(object)
    def _succeeded(self, result) -> None:
        callback = self._finish()
        self.statusBar().showMessage(tr("Requested operation completed."))
        if callback:
            callback(result)

    @Slot(str)
    def _failed(self, message) -> None:
        self._finish()
        self.show_error(tr(message))

    def connection_result(self, result: DesktopConnectionView) -> None:
        # The facade supplies normalized text; never display provider exceptions.
        self.statusBar().showMessage(
            tr(f"{('성공' if result.success else '실패')}: {tr(result.message)}")
        )

    def create_project(self) -> None:
        if self.busy:
            return
        dialog = CreateProjectDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            request, title = dialog.request.toPlainText(), dialog.title.text()
            parent_directory = Path(dialog.parent_directory.text())
            folder_name = dialog.folder_name.text()
            self.submit(
                lambda: self.service.create_project(
                    request,
                    title=title or None,
                    parent_directory=parent_directory,
                    folder_name=folder_name,
                ),
                self.select_project,
            )

    def open_existing_project(self) -> None:
        if self.busy:
            return
        directory = choose_directory(self, "기존 프로젝트 폴더 선택")
        if not directory:
            return
        # Reopening a registered folder requires no new proposal or execution.
        try:
            project_id = self.service.find_project_directory(Path(directory))
        except DesktopError as error:
            self.show_error(tr(error.message))
            return
        if project_id:
            self.select_project(project_id)
            return
        dialog = TextInputDialog(
            "기존 프로젝트 등록",
            "등록",
            "기존 파일을 변경하지 않습니다. 향후 작업 요청을 입력하세요.",
            self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            request = dialog.text.toPlainText()
            self.submit(
                lambda: self.service.open_existing_project(Path(directory), request),
                self.select_project,
            )

    def change_project_directory(self) -> None:
        if self.busy or not self.state.selected_project_id:
            return
        project_id = self.state.selected_project_id
        directory = choose_directory(self, "작업 폴더 변경")
        if directory:
            self.submit(
                lambda: self.service.set_project_workspace(project_id, Path(directory))
            )

    def create_run(self, domain: str) -> None:
        if self.busy:
            return
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
                        WorkMode(dialog.work.currentData()),
                        ProjectMode(dialog.mode.currentData()),
                    )
                    self.submit(
                        lambda: self.service.confirm_project_mode(pid, work, mode)
                    )
            elif action in ("bind_developer_run", "bind_research_run"):
                dialog = TextInputDialog("Bind Run", value(action), "Run ID", self)
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
            elif (
                action == "continue_developer"
                and view.developer.status == "awaiting_checkpoint"
            ):
                dialog = DeveloperCheckpointDialog(self)
                if (
                    dialog.exec() == QDialog.DialogCode.Accepted
                    and dialog.decision.currentData()
                ):
                    decision = CheckpointDecision(dialog.decision.currentData())
                    note = dialog.note.toPlainText().strip() or None
                    self.submit(
                        lambda: self.service.decide_developer_checkpoint(
                            pid, decision, note
                        )
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
                self.show_error(
                    tr("This action is unavailable in this desktop version.")
                )
        except DesktopError as error:
            self.show_error(tr(error.message))
        except Exception:  # noqa: BLE001 -- UI boundary never exposes raw errors
            self.show_error(
                tr(
                    "Unable to prepare this action. Refresh and check its required input."
                )
            )

    def bootstrap(self, handoff_id: str) -> None:
        if self.busy:
            return
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
                tr("Wait for the requested operation to finish before closing.")
            )
            event.ignore()
            return
        self.pool.waitForDone()
        event.accept()
