"""Read-only snapshot history, observed file changes and recovery evidence."""

from datetime import UTC, datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QPlainTextEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from ai_agent_project.desktop.errors import DesktopError
from ai_agent_project.desktop_app.strings import event_name, tr, value
from ai_agent_project.desktop_app.widgets import label


def _modified_time(value: int | None) -> str:
    if value is None:
        return tr("unavailable")
    try:
        return (
            datetime.fromtimestamp(value / 1_000_000_000, tz=UTC)
            .astimezone()
            .isoformat(timespec="seconds")
        )
    except (OverflowError, ValueError, OSError):
        return tr("unavailable")


class CodeChangesPanel(QGroupBox):
    def __init__(self, window, project_id: str) -> None:
        super().__init__(tr("Code Changes / Diff · Observed Change"))
        self.setObjectName("codeChanges")
        self.window = window
        self.project_id = project_id
        self.snapshot_ids: set[str] = set()
        self.status = label(tr("Historical Diff Unavailable: no recorded snapshots."))
        self.status.setObjectName("codeChangesStatus")
        self.recovery = label(tr("Recovery is read-only."))
        self.recovery.setObjectName("executionRecovery")
        self.snapshots = QComboBox()
        self.snapshots.setObjectName("snapshotHistory")
        self.snapshots.currentIndexChanged.connect(self.select_snapshot)
        self.comparison = QComboBox()
        self.comparison.setObjectName("snapshotComparison")
        self.comparison.addItem(tr("Phase baseline"), None)
        self.comparison.addItem(tr("Previous recorded snapshot"), "previous")
        self.comparison.currentIndexChanged.connect(self.select_snapshot)
        self.follow = QCheckBox(tr("Follow latest recorded snapshot"))
        self.follow.setChecked(True)
        self.older = QPushButton(tr("Load older snapshots"))
        self.older.setObjectName("olderSnapshots")
        self.older.clicked.connect(self.load_older)
        self.files = QTreeWidget()
        self.files.setObjectName("changedFiles")
        self.files.setHeaderLabels([tr(s) for s in ("File", "Status", "Attribution")])
        self.files.setColumnWidth(0, 350)
        self.files.setMinimumHeight(150)
        self.files.itemSelectionChanged.connect(self.inspect_file)
        self.diff = QPlainTextEdit()
        self.diff.setObjectName("unifiedDiff")
        self.diff.setReadOnly(True)
        self.diff.setMinimumHeight(220)
        layout = QVBoxLayout(self)
        for widget in (
            self.recovery,
            self.status,
            self.snapshots,
            self.follow,
            self.comparison,
            self.older,
            self.files,
            self.diff,
        ):
            layout.addWidget(widget)
        self.refresh()
        self.timer = QTimer(self)
        self.timer.setInterval(800)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()

    def _add_history(self, snapshots) -> None:
        self.snapshots.blockSignals(True)
        for snapshot in snapshots:
            if snapshot.snapshot_id in self.snapshot_ids:
                continue
            self.snapshot_ids.add(snapshot.snapshot_id)
            self.snapshots.addItem(
                tr(
                    f"#{snapshot.sequence} · {snapshot.captured_at.astimezone().isoformat(timespec='seconds')} · {snapshot.phase_id or '—'} / {snapshot.attempt_id[:8]} · {value(snapshot.stage)} / 수정 시도 {snapshot.repair_attempt}"
                ),
                snapshot,
            )
        self.snapshots.blockSignals(False)

    def refresh(self) -> None:
        if not self.isVisible() and self.snapshot_ids:
            return
        try:
            snapshots = self.window.service.list_developer_snapshots(self.project_id)
            previous = len(self.snapshot_ids)
            self._add_history(snapshots)
            if not previous and self.snapshots.count():
                self.select_snapshot()
            elif (
                len(self.snapshot_ids) != previous
                and self.follow.isChecked()
                and snapshots
            ):
                for index in range(self.snapshots.count()):
                    if (
                        self.snapshots.itemData(index).snapshot_id
                        == snapshots[0].snapshot_id
                    ):
                        self.snapshots.setCurrentIndex(index)
                        break
            recovery = self.window.service.get_developer_recovery(self.project_id)
            if recovery.attempts:
                attempt = recovery.attempts[0]
                event = attempt.last_event
                self.recovery.setText(
                    tr(
                        f"실행: {value(attempt.status)} · 단계: {attempt.phase_id or '—'} · 시도: {attempt.attempt_id}\n마지막 확인 기록: #{event.sequence} {event_name(event.kind)} · {event.occurred_at.astimezone().isoformat(timespec='seconds')}\n{tr(attempt.message)}\n{tr(recovery.message)}"
                    )
                )
            else:
                self.recovery.setText(tr(recovery.message))
            self.older.setEnabled(bool(snapshots))
        except DesktopError as error:
            self.status.setText(tr(error.message))

    def load_older(self) -> None:
        summaries = [
            self.snapshots.itemData(index) for index in range(self.snapshots.count())
        ]
        if not summaries:
            return
        try:
            snapshots = self.window.service.list_developer_snapshots(
                self.project_id,
                before_sequence=min(item.sequence for item in summaries),
            )
            self._add_history(snapshots)
            self.older.setEnabled(bool(snapshots))
        except DesktopError as error:
            self.status.setText(tr(error.message))

    def select_snapshot(self, *_args) -> None:
        self.files.clear()
        self.diff.clear()
        snapshot = self.snapshots.currentData()
        if snapshot is None:
            return
        try:
            view = self.window.service.get_developer_code_changes(
                self.project_id,
                after_snapshot_id=snapshot.snapshot_id,
                comparison="previous"
                if self.comparison.currentData() == "previous"
                else "baseline",
            )
            start = (
                f"#{view.before.sequence} {value(view.before.stage)}"
                if view.before
                else tr("unavailable")
            )
            end = (
                f"#{view.after.sequence} {value(view.after.stage)}"
                if view.after
                else tr("unavailable")
            )
            self.status.setText(
                tr(
                    f"실행: {self.window.service.get_developer_execution_view(self.project_id).run_id}\n스냅샷: {start} → {end}\n{tr(view.message)}"
                )
            )
            for change in view.changes:
                item = QTreeWidgetItem(
                    self.files,
                    [change.path, value(change.status), value(change.attribution)],
                )
                item.setData(0, Qt.ItemDataRole.UserRole, change)
            if view.changes:
                self.files.setCurrentItem(self.files.topLevelItem(0))
            else:
                self.diff.setPlainText(
                    tr(view.message)
                    + (
                        tr("\nNo public file changes were observed in this comparison.")
                        if view.before
                        and view.after
                        and view.before.complete
                        and view.after.complete
                        else ""
                    )
                )
        except DesktopError as error:
            self.status.setText(tr(error.message))

    def inspect_file(self) -> None:
        self.diff.clear()
        items = self.files.selectedItems()
        if not items:
            return
        change = items[0].data(0, Qt.ItemDataRole.UserRole)
        self.diff.setPlainText(
            f"{change.path} · {value(change.status)} · {value(change.attribution)}\n{tr(change.reason)}\n크기: {(change.before_size if change.before_size is not None else tr('absent/unknown'))} → {(change.after_size if change.after_size is not None else tr('absent/unknown'))} 바이트\n변경 시각: {_modified_time(change.before_modified_ns)} → {_modified_time(change.after_modified_ns)}\n\n{change.diff}"
        )
