"""Explicit human review of immutable improvement views."""

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ai_agent_project.desktop_app.dialogs import InputDialog
from ai_agent_project.desktop_app.pages import Page, fill_table, table
from ai_agent_project.desktop_app.widgets import label


class FeedbackDialog(InputDialog):
    def __init__(self, parent=None):
        super().__init__("Run Feedback", "Save Feedback", parent)
        self.rating = QComboBox()
        self.rating.addItem("Helpful", "helpful")
        self.rating.addItem("Needs Improvement", "not_helpful")
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText(
            "Optional feedback (500 characters). Do not include credentials."
        )
        self.form.addRow("Rating", self.rating)
        self.form.addRow("Comment", self.text)


class ImprovementsPage(Page):
    def __init__(self, window):
        super().__init__("Agent Improvement")
        self.window = window
        self.summary = label("")
        self.layout.addWidget(self.summary)
        self.layout.addWidget(
            label(
                "User-approved experience-based guidance. Evaluation and approval are separate actions. Usage and outcomes are descriptive, not causal proof."
            )
        )
        self.tabs = QTabWidget()
        self.layout.addWidget(self.tabs)
        self.tables = {}
        for name, headers in [
            (
                "Candidates",
                ["Title", "Domain / project", "Category", "Status", "Confidence"],
            ),
            ("Approved Rules", ["Rule", "Scope", "Category", "Enabled", "Version"]),
            ("Evaluations", ["Domain", "Run", "Created", "Evidence"]),
            ("Feedback / Impact", ["Target", "Rating", "Created", "Comment"]),
        ]:
            body = QWidget()
            layout = QVBoxLayout(body)
            widget = table(headers)
            self.tables[name] = widget
            layout.addWidget(widget)
            self.tabs.addTab(body, name)
            widget.currentCellChanged.connect(self.preview_selected)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.layout.addWidget(self.preview)
        self.scope = QComboBox()
        self.scope.addItems(
            ["Source domain", "global", "developer", "researcher", "project"]
        )
        self.layout.addWidget(self.scope)
        row = QHBoxLayout()
        self.buttons = {}
        for title, command in [
            ("Approve Candidate", self.approve),
            ("Reject Candidate", self.reject),
            ("Enable Rule", self.enable),
            ("Disable Rule", self.disable),
        ]:
            button = QPushButton(title)
            button.clicked.connect(command)
            row.addWidget(button)
            self.buttons[title] = button
        self.layout.addLayout(row)
        self.tabs.currentChanged.connect(self.preview_selected)
        self.candidates = self.rules = self.evaluations = self.feedback = ()

    def refresh(self):
        service = self.window.service
        state = service.get_improvement_overview()
        self.candidates, self.rules = state.candidates, service.list_improvement_rules()
        self.evaluations, self.feedback = state.evaluations, state.feedback
        self.summary.setText(
            f"Pending Candidates: {sum(c.status == 'pending' for c in self.candidates)}   Active Rules: {sum(r.enabled for r in self.rules)}   Evaluations: {len(self.evaluations)}"
        )
        rows = {
            "Candidates": [
                (
                    c.title,
                    f"{c.source_domain} / {c.project_id or '—'}",
                    c.category,
                    c.status,
                    c.confidence,
                )
                for c in self.candidates
            ],
            "Approved Rules": [
                (
                    r.rule_text,
                    r.scope,
                    r.category,
                    "Yes" if r.enabled else "No",
                    r.version,
                )
                for r in self.rules
            ],
            "Evaluations": [
                (
                    e.evidence.source_domain,
                    e.evidence.source_run_id,
                    e.created_at.isoformat(),
                    e.evidence.digest[:12],
                )
                for e in self.evaluations
            ],
            "Feedback / Impact": [
                (f.target_type, f.rating, f.created_at.isoformat(), f.text)
                for f in self.feedback
            ],
        }
        for name, widget in self.tables.items():
            widget.blockSignals(True)
            fill_table(widget, rows[name])
            widget.clearSelection()
            widget.setCurrentCell(-1, -1)
            widget.blockSignals(False)
        self.preview_selected()

    def selected(self):
        name = self.tabs.tabText(self.tabs.currentIndex())
        row = self.tables[name].currentRow()
        values = {
            "Candidates": self.candidates,
            "Approved Rules": self.rules,
            "Evaluations": self.evaluations,
            "Feedback / Impact": self.feedback,
        }[name]
        return name, values[row] if 0 <= row < len(values) else None

    def preview_selected(self, *_):
        name, value = self.selected()
        for button in self.buttons.values():
            button.setEnabled(False)
        self.scope.setEnabled(name == "Candidates")
        if value is None:
            self.preview.setPlainText(
                "Select a record to inspect its provenance and available actions."
            )
            return
        self.preview.setPlainText(value.model_dump_json(indent=2))
        if name == "Candidates":
            self.buttons["Approve Candidate"].setEnabled(value.status == "pending")
            self.buttons["Reject Candidate"].setEnabled(value.status == "pending")
        elif name == "Approved Rules":
            self.buttons["Enable Rule"].setEnabled(not value.enabled)
            self.buttons["Disable Rule"].setEnabled(value.enabled)
            try:
                conflicts = self.window.service.get_improvement_conflicts(value.rule_id)
                if conflicts:
                    self.preview.appendPlainText(
                        "\nPossible conflicting rules: "
                        + ", ".join(conflicts)
                        + "\nWhen both apply, neither is injected. Review and explicitly disable one."
                    )
                impact = self.window.service.get_improvement_impact(value.rule_id)
                self.preview.appendPlainText(
                    "\nObserved usage / post-application outcomes:\n"
                    + impact.model_dump_json(indent=2)
                )
            except Exception:  # noqa: BLE001 -- safe UI boundary
                self.window.show_error("Cannot load improvement outcomes.")

    def approve(self):
        name, value = self.selected()
        if name == "Candidates" and value is not None:
            scope = self.scope.currentText()
            self.window.submit(
                lambda: self.window.service.approve_improvement_candidate(
                    value.candidate_id, None if scope == "Source domain" else scope
                )
            )

    def reject(self):
        name, value = self.selected()
        if name == "Candidates" and value is not None:
            self.window.submit(
                lambda: self.window.service.reject_improvement_candidate(
                    value.candidate_id
                )
            )

    def enable(self):
        name, value = self.selected()
        if name == "Approved Rules" and value is not None:
            self.window.submit(
                lambda: self.window.service.enable_improvement_rule(value.rule_id)
            )

    def disable(self):
        name, value = self.selected()
        if name == "Approved Rules" and value is not None:
            self.window.submit(
                lambda: self.window.service.disable_improvement_rule(value.rule_id)
            )


def evaluate_run(window, domain, run_id):
    command = (
        window.service.evaluate_developer_run
        if domain == "developer"
        else window.service.evaluate_researcher_run
    )
    window.submit(lambda: command(run_id), lambda _: window.navigate("Improvements"))


def feedback_run(window, domain, run_id):
    dialog = FeedbackDialog(window)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        rating, text = dialog.rating.currentData(), dialog.text.toPlainText()
        window.submit(
            lambda: window.service.submit_improvement_feedback(
                domain, run_id, rating, text
            )
        )
