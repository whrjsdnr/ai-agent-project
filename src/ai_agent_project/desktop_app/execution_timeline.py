"""Incremental public timeline polling; polling never creates execution events."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QGroupBox,
    QHeaderView,
    QPlainTextEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from ai_agent_project.desktop.errors import DesktopError
from ai_agent_project.desktop_app.strings import event_name, tr, value
from ai_agent_project.desktop_app.widgets import label

MAX_VISIBLE_EVENTS = 500


class ExecutionTimelinePanel(QGroupBox):
    def __init__(self, window, project_id: str) -> None:
        super().__init__(tr("Execution Timeline · recorded events"))
        self.setObjectName("executionTimeline")
        self.window = window
        self.project_id = project_id
        self.sequence = 0
        self.history = False
        self.status = label(
            tr("No recorded execution events. Saved workflow state is shown above.")
        )
        self.status.setObjectName("executionEventStatus")
        self.tree = QTreeWidget()
        self.tree.setObjectName("executionEvents")
        self.tree.setHeaderLabels(
            [tr(s) for s in ("Sequence / time", "Phase / attempt", "Event", "Status")]
        )
        self.tree.setMinimumHeight(180)
        self.tree.header().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.tree.itemSelectionChanged.connect(self.inspect_selected)
        self.logs = QPlainTextEdit()
        self.logs.setObjectName("executionLogs")
        self.logs.setReadOnly(True)
        self.logs.setMinimumHeight(180)
        layout = QVBoxLayout(self)
        layout.addWidget(self.status)
        layout.addWidget(
            label(
                tr(
                    "Agent completed means the Agent returned. Tool and Validation results provide execution evidence. File changes are observations with unconfirmed cause."
                )
            )
        )
        layout.addWidget(self.tree)
        self.earlier = QPushButton(tr("Load earlier events"))
        self.earlier.setObjectName("timelineEarlier")
        self.earlier.clicked.connect(self.load_earlier)
        layout.addWidget(self.earlier)
        self.live = QPushButton(tr("Return to live events"))
        self.live.setObjectName("timelineLive")
        self.live.clicked.connect(self.return_to_live)
        layout.addWidget(self.live)
        layout.addWidget(self.logs)
        self.timer = QTimer(self)
        self.timer.setInterval(400)
        self.timer.timeout.connect(self.poll)
        self.poll()
        self.timer.start()

    def poll(self) -> None:
        if not self.isVisible() and self.sequence:
            return
        try:
            events = (
                ()
                if self.history
                else self.window.service.get_developer_events(
                    self.project_id, after_sequence=self.sequence, limit=200
                )
            )
            for event in events:
                self.add_event(event)
            while self.tree.topLevelItemCount() > MAX_VISIBLE_EVENTS:
                self.tree.takeTopLevelItem(0)
            execution = self.window.service.get_developer_execution_view(
                self.project_id
            )
            recovery = self.window.service.get_developer_recovery(self.project_id)
            latest = execution.last_event
            if latest:
                phase_status = (
                    execution.last_phase_event.status
                    if execution.last_phase_event
                    else "no recorded execution"
                )
                self.status.setText(
                    tr(
                        f"현재 단계: {execution.current_phase or '—'} · 저장된 작업 상태: {value(execution.workflow_status)} · 마지막 실행 기록: {value(phase_status)}\n마지막 기록 단계: {latest.phase_id or '—'} · #{latest.sequence} {event_name(latest.kind)} · {value(latest.status)}\n{latest.occurred_at.astimezone().isoformat(timespec='seconds')} · 마지막 관측 기록이며 현재 실행 중임을 보장하지 않습니다."
                        + (
                            f"\n복구 상태: {value(recovery.attempts[0].status)} · {tr(recovery.attempts[0].message)}"
                            if recovery.attempts
                            else ""
                        )
                    )
                )
            if events and not self.tree.selectedItems():
                self.tree.setCurrentItem(
                    self.tree.topLevelItem(self.tree.topLevelItemCount() - 1)
                )
            first = self.tree.topLevelItem(0)
            self.earlier.setEnabled(
                bool(first and first.data(0, Qt.ItemDataRole.UserRole).sequence > 1)
            )
            self.live.setEnabled(self.history)
        except DesktopError as error:
            self.status.setText(tr(error.message))

    def add_event(self, event) -> None:
        details = event_name(event.kind)
        if event.tool:
            details += f" · {event.tool}"
        if event.path:
            details += f" · {value(event.change)}: {event.path} (변경 원인 미확정)"
        item = QTreeWidgetItem(
            self.tree,
            [
                f"{event.sequence} · {event.occurred_at.astimezone().isoformat(timespec='seconds')}",
                f"{event.phase_id or '—'} · {event.attempt_id[:8]} / 수정 시도 {event.repair_attempt}",
                details,
                value(event.status),
            ],
        )
        item.setData(0, Qt.ItemDataRole.UserRole, event)
        for column in range(4):
            item.setToolTip(column, item.text(column))
        self.sequence = event.sequence

    def load_earlier(self) -> None:
        first = self.tree.topLevelItem(0)
        if not first:
            return
        sequence = first.data(0, Qt.ItemDataRole.UserRole).sequence
        if sequence <= 1:
            return
        try:
            events = self.window.service.get_developer_events(
                self.project_id,
                after_sequence=max(0, sequence - 201),
                limit=min(200, sequence - 1),
            )
            self.history = True
            self.tree.clear()
            for event in events:
                self.add_event(event)
            self.poll()
        except DesktopError as error:
            self.status.setText(tr(error.message))

    def return_to_live(self) -> None:
        try:
            latest = self.window.service.get_developer_last_event(self.project_id)
            self.history = False
            self.sequence = max(0, latest.sequence - 200) if latest else 0
            self.tree.clear()
            self.poll()
        except DesktopError as error:
            self.status.setText(tr(error.message))

    def inspect_selected(self) -> None:
        self.logs.clear()
        items = self.tree.selectedItems()
        if not items:
            return
        event = items[0].data(0, Qt.ItemDataRole.UserRole)
        lines = [
            f"이벤트: {event_name(event.kind)} · {value(event.status)}",
            f"실행: {event.run_id}",
            f"단계: {event.phase_id or '—'}",
            f"시도: {event.attempt_id} · 수정 시도: {event.repair_attempt}",
        ]
        if event.command:
            lines.append(f"명령어: {event.command}")
        if event.tool == "shell":
            lines.append(
                f"종료 코드: {(event.exit_code if event.exit_code is not None else tr('not available (rejected, timed out or not completed)'))}"
            )
        if event.error:
            lines.append(f"오류: {value(event.error)}")
        if event.stdout:
            lines.extend(["", "표준 출력(stdout):", event.stdout])
        if event.stderr:
            lines.extend(["", "표준 오류(stderr):", event.stderr])
        if event.path:
            lines.append(
                f"관측: {value(event.change)} {event.path} · 변경 원인: 미확정"
            )
        self.logs.setPlainText("\n".join(lines))
