"""Pages render immutable facade views; all mutations belong to the controller."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ai_agent_project.desktop.models import DesktopProjectView
from ai_agent_project.desktop_app.strings import artifact_title, tr, value
from ai_agent_project.desktop_app.widgets import PendingActionWidget, label


class Page(QWidget):
    def __init__(self, title: str) -> None:
        super().__init__()
        self.setObjectName("desktopPage")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.layout = QVBoxLayout(self)
        self.layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.layout.setContentsMargins(24, 20, 24, 20)
        heading = label(tr(title))
        heading.setProperty("heading", True)
        self.layout.addWidget(heading)


def table(headers):
    widget = QTableWidget(0, len(headers))
    widget.setHorizontalHeaderLabels([tr(h) for h in headers])
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    widget.setWordWrap(True)
    widget.verticalHeader().hide()
    return widget


def fill_table(widget, rows):
    widget.setRowCount(len(rows))
    for row, values in enumerate(rows):
        for col, cell in enumerate(values):
            item = QTableWidgetItem(str(cell or "—"))
            item.setToolTip(str(cell or "—"))
            widget.setItem(row, col, item)
    widget.resizeRowsToContents()


class ProjectsPage(Page):
    def __init__(self, window, dashboard=False) -> None:
        super().__init__("Dashboard" if dashboard else "Projects")
        self.window = window
        self.dashboard = dashboard
        self.metrics = []
        if dashboard:
            metric_row = QHBoxLayout()
            for title in ("Total projects", "Active", "Completed", "Awaiting user"):
                card = QGroupBox(tr(title))
                card_layout = QVBoxLayout(card)
                value = label(tr("0"))
                value.setProperty("heading", True)
                self.metrics.append(value)
                card_layout.addWidget(value)
                metric_row.addWidget(card)
            self.layout.addLayout(metric_row)
        self.summary = label(tr(""))
        self.layout.addWidget(self.summary)
        self.improvement_summary = label(tr(""))
        self.layout.addWidget(self.improvement_summary)
        self.table = table(
            [
                "Project",
                "WorkMode",
                "ProjectMode",
                "Status",
                "Pending action",
                "Created",
            ]
        )
        self.layout.addWidget(self.table)
        actions = QHBoxLayout()
        for title, callback in [
            ("New Project", window.create_project),
            ("Open Project", self.open_selected),
            ("기존 프로젝트 열기", window.open_existing_project),
            ("Refresh", window.refresh),
        ]:
            button = QPushButton(tr(title))
            button.clicked.connect(callback)
            actions.addWidget(button)
        self.layout.addLayout(actions)
        self.table.cellDoubleClicked.connect(lambda *_: self.open_selected())
        self.projects = ()

    def refresh(self) -> None:
        if self.dashboard:
            view = self.window.service.get_dashboard()
            state = self.window.service.get_improvement_overview()
            rules = self.window.service.list_improvement_rules()
            self.improvement_summary.setText(
                tr(
                    f"개선 후보: {sum(c.status == 'pending' for c in state.candidates)} · 사용 중인 규칙: {sum(r.enabled for r in rules)}"
                )
            )
            self.projects = view.recent_projects
            for widget, metric_value in zip(
                self.metrics,
                (
                    view.total_projects,
                    view.active_projects,
                    view.completed_projects,
                    view.awaiting_user_action_count,
                ),
                strict=True,
            ):
                widget.setText(str(metric_value))
            self.summary.setText(
                tr(
                    f"제공자: {view.provider.model} · API Key 설정: {('예' if view.provider.credential_configured else '없음 — 설정에서 입력하세요')}"
                )
            )
        else:
            self.projects = self.window.service.list_projects()
            self.summary.setText(
                tr(
                    f"{len(self.projects)}개 프로젝트"
                    if self.projects
                    else "No projects yet. Create a project to request a mode proposal."
                )
            )
        fill_table(
            self.table,
            [
                (
                    p.display_title,
                    value(p.work_mode),
                    value(p.project_mode),
                    value(p.status),
                    ", ".join(value(a.action_type) for a in p.pending_actions),
                    p.created_at.astimezone().strftime("%Y-%m-%d %H:%M"),
                )
                for p in self.projects
            ],
        )

    def open_selected(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self.window.select_project(self.projects[row].project_id)


class ProjectPage(Page):
    def __init__(self, window, domain) -> None:
        super().__init__(domain)
        self.window = window
        self.domain = domain
        self.body = QVBoxLayout()
        self.layout.addLayout(self.body)
        self.layout.addStretch()

    def refresh(self) -> None:
        while self.body.count():
            item = self.body.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        project_id = self.window.state.selected_project_id
        if not project_id:
            self.body.addWidget(
                label(tr("No project selected. Open a project from Projects."))
            )
            return
        view = self.window.service.get_project_view(project_id)
        p = view.project
        self.body.addWidget(
            label(
                tr(
                    f"{p.display_title}\n{p.project_id}\n{value(p.work_mode) if p.work_mode else tr('Awaiting mode confirmation')} · {value(p.project_mode)} · {value(p.status)}\n결과물: {len(view.artifacts)}"
                )
            )
        )
        self.body.addWidget(
            label(
                f"프로젝트 폴더: {p.workspace_root or '설정되지 않음(기존 Run 경로 유지)'}"
            )
        )
        change = QPushButton("작업 폴더 변경")
        change.setObjectName("changeProjectDirectory")
        change.setEnabled(not p.developer_run_id and not self.window.busy)
        change.clicked.connect(self.window.change_project_directory)
        self.body.addWidget(change)
        for action in p.pending_actions:
            if action.domain == "project":
                self.add_pending(self.body, action)
        lanes = QWidget()
        lane_layout = QHBoxLayout(lanes)
        for name in ("developer", "researcher"):
            if self.domain not in ("Project Detail", "Hybrid", name.title()):
                continue
            lane = getattr(view, name)
            box = QGroupBox(value(name))
            layout = QVBoxLayout(box)
            if lane is None or not lane.bound:
                layout.addWidget(
                    label(
                        tr(
                            "Lane not bound. Create a run, then explicitly bind its run ID."
                        )
                    )
                )
                if lane is not None:
                    if lane.pending_action:
                        self.add_pending(layout, lane.pending_action)
                    button = QPushButton(tr(f"생성: {value(name)} 실행"))
                    button.clicked.connect(
                        lambda checked=False, n=name: self.window.create_run(n)
                    )
                    layout.addWidget(button)
            else:
                layout.addWidget(
                    label(
                        tr(
                            f"상태: {value(lane.status)}\n단계: {value(lane.phase) if name == 'researcher' else lane.phase or '—'}\n실행: {lane.run_id}"
                        )
                    )
                )
                if name == "researcher":
                    layout.addWidget(
                        label(
                            tr(
                                f"방향: {lane.selected_direction or tr('Not selected')}\n결과: {value(lane.result_state)}\n종합 / 자료: {value(lane.synthesis_state)}\n리서치 결과물은 조회와 복사만 가능합니다."
                            )
                        )
                    )
                from ai_agent_project.desktop_app.improvements import (
                    evaluate_run,
                    feedback_run,
                )

                evaluate = QPushButton(tr("Evaluate Run"))
                evaluate.setObjectName(f"evaluate_{name}")
                evaluate.clicked.connect(
                    lambda checked=False, n=name, r=lane.run_id: evaluate_run(
                        self.window, n, r
                    )
                )
                layout.addWidget(evaluate)
                feedback = QPushButton(tr("Give Feedback"))
                feedback.clicked.connect(
                    lambda checked=False, n=name, r=lane.run_id: feedback_run(
                        self.window, n, r
                    )
                )
                layout.addWidget(feedback)
                if lane.pending_action:
                    self.add_pending(layout, lane.pending_action)
                layout.addWidget(
                    label(
                        tr(
                            "결과물: "
                            + (
                                ", ".join(
                                    artifact_title(a.title)
                                    for a in view.artifacts
                                    if a.source_domain == name
                                )
                                or "None"
                            )
                        )
                    )
                )
            lane_layout.addWidget(box)
        self.body.addWidget(lanes)
        if self.domain == "Developer" and view.developer and view.developer.bound:
            from ai_agent_project.desktop_app.code_changes import CodeChangesPanel
            from ai_agent_project.desktop_app.developer_workspace import (
                DeveloperWorkspacePanel,
            )
            from ai_agent_project.desktop_app.execution_timeline import (
                ExecutionTimelinePanel,
            )

            self.body.addWidget(ExecutionTimelinePanel(self.window, project_id))
            self.body.addWidget(CodeChangesPanel(self.window, project_id))
            self.body.addWidget(DeveloperWorkspacePanel(self.window, project_id))
        if self.domain in ("Hybrid", "Project Detail") and view.hybrid:
            self.render_handoffs(view)

    def add_pending(self, layout, action) -> None:
        widget = PendingActionWidget(action)
        widget.requested.connect(self.window.request_action)
        layout.addWidget(widget)

    def render_handoffs(self, view: DesktopProjectView) -> None:
        box = QGroupBox(tr("Research → Developer Handoffs"))
        layout = QVBoxLayout(box)
        layout.addWidget(
            label(
                tr(
                    "Select a Researcher artifact in Artifacts to create a context handoff."
                )
            )
        )
        for handoff in view.handoffs:
            layout.addWidget(
                label(
                    tr(
                        f"{value(handoff.artifact_type)} · {value(handoff.purpose)}\n{value(handoff.status)} · {handoff.created_at.isoformat(timespec='minutes')}"
                    )
                )
            )
            button = QPushButton(tr("Create Developer Run From Research"))
            button.setEnabled(handoff.bootstrap_available)
            button.clicked.connect(
                lambda checked=False, h=handoff.handoff_id: self.window.bootstrap(h)
            )
            layout.addWidget(button)
        if not view.handoffs:
            layout.addWidget(label(tr("No handoffs created.")))
        self.body.addWidget(box)


class ArtifactsPage(Page):
    def __init__(self, window) -> None:
        super().__init__("Artifacts")
        self.window = window
        self.artifacts = ()
        self.table = table(["Title / type", "Domain", "Source run", "Version", "Media"])
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.table)
        splitter.addWidget(self.preview)
        self.layout.addWidget(splitter)
        copy = QPushButton(tr("Copy Preview"))
        copy.clicked.connect(
            lambda: QApplication.clipboard().setText(self.preview.toPlainText())
        )
        self.layout.addWidget(copy)
        export = QPushButton(tr("Export JSON…"))
        export.clicked.connect(self.export_selected)
        self.layout.addWidget(export)
        self.handoff = QPushButton(tr("Create Developer Context Handoff"))
        self.handoff.clicked.connect(self.create_handoff)
        self.layout.addWidget(self.handoff)
        self.table.currentCellChanged.connect(self.select_artifact)

    def refresh(self) -> None:
        self.table.blockSignals(True)
        pid = self.window.state.selected_project_id
        self.artifacts = self.window.service.list_project_artifacts(pid) if pid else ()
        fill_table(
            self.table,
            [
                (
                    f"{artifact_title(a.title)}\n{value(a.artifact_type)}",
                    value(a.source_domain),
                    a.source_run_id,
                    a.source_version,
                    ", ".join(a.media_types),
                )
                for a in self.artifacts
            ],
        )
        self.table.clearSelection()
        self.table.setCurrentCell(-1, -1)
        self.table.blockSignals(False)
        self.preview.setPlainText(
            tr("Select an artifact to preview.")
            if pid
            else tr("No project selected. Open a project from Projects.")
        )
        self.handoff.setEnabled(False)

    def select_artifact(self, row, *_) -> None:
        if row < 0:
            return
        try:
            artifact = self.artifacts[row]
            view = self.window.service.get_artifact_view(
                self.window.state.selected_project_id, artifact.artifact_id
            )
            self.preview.setPlainText(view.content)
            self.handoff.setEnabled(
                self.window.service.can_create_handoff(
                    self.window.state.selected_project_id, artifact.artifact_id
                )
            )
        except Exception:  # noqa: BLE001 -- UI boundary never exposes raw errors
            self.window.show_error(
                tr("Artifact preview unavailable. Refresh and try again.")
            )

    def export_selected(self) -> None:
        from pathlib import Path

        from PySide6.QtWidgets import QFileDialog

        row = self.table.currentRow()
        if row < 0:
            return
        destination, _ = QFileDialog.getSaveFileName(
            self,
            tr("Export to a new file (existing files are never overwritten)"),
            "artifact.json",
            "JSON (*.json)",
        )
        if destination:
            pid = self.window.state.selected_project_id
            aid = self.artifacts[row].artifact_id
            self.window.submit(
                lambda: self.window.service.export_artifact(pid, aid, Path(destination))
            )

    def create_handoff(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            pid = self.window.state.selected_project_id
            aid = self.artifacts[row].artifact_id
            self.window.submit(lambda: self.window.service.create_handoff(pid, aid))


class SettingsPage(Page):
    def __init__(self, window) -> None:
        super().__init__("Provider Settings")
        self.window = window
        form = QFormLayout()
        self.layout.addLayout(form)
        form.addRow(tr("Provider Type"), label(tr("OpenAI-compatible")))
        self.url = QLineEdit()
        self.model = QLineEdit()
        self.timeout = QDoubleSpinBox()
        self.timeout.setRange(0.1, 3600)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText(
            tr("Enter session API key; leave blank to retain current credential")
        )
        for name, field in [
            ("Base URL", self.url),
            ("Model", self.model),
            ("Timeout (seconds)", self.timeout),
            ("API key", self.key),
        ]:
            form.addRow(tr(name), field)
        self.credential = label(tr(""))
        self.layout.addWidget(self.credential)
        self.layout.addWidget(
            label(
                tr(
                    "API key is used for this application session and is not saved in the normal configuration file. OS credential storage is deferred."
                )
            )
        )
        for title, callback in [
            ("Save Settings", lambda: self.apply(False)),
            ("Test Connection", lambda: self.apply(True)),
        ]:
            button = QPushButton(tr(title))
            button.clicked.connect(callback)
            self.layout.addWidget(button)
        self.layout.addStretch()

    def refresh(self) -> None:
        config = self.window.service.get_provider_config()
        self.url.setText(config.base_url)
        self.model.setText(config.model)
        self.timeout.setValue(config.timeout_seconds)
        self.key.clear()
        self.credential.setText(
            tr(f"API Key 설정: {('예' if config.credential_configured else '아니요')}")
        )

    def apply(self, test) -> None:
        from ai_agent_project.llm.config import ProviderConfig

        try:
            config = ProviderConfig(
                base_url=self.url.text(),
                model=self.model.text(),
                timeout_seconds=self.timeout.value(),
                api_key=self.key.text() or None,
            )
        except ValueError:
            self.window.show_error(
                tr("Check URL, model, timeout and credential input.")
            )
            return
        self.key.clear()
        if test:
            self.window.submit(
                lambda: self.window.service.test_provider_connection(config),
                self.window.connection_result,
            )
        else:
            self.window.submit(lambda: self.window.service.save_provider_config(config))
