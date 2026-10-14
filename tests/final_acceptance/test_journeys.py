"""Cross-feature journeys using real services/stores and deterministic model boundaries."""

import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

from ai_agent_project.agent.acceptance import (
    AcceptanceReport,
    RequirementValidationResult,
)
from ai_agent_project.agent.checkpoint import PhaseCheckpointService, ProgressReporter
from ai_agent_project.agent.coding_service import RepairAttempt
from ai_agent_project.agent.phase_execution import PhaseExecutionResult
from ai_agent_project.agent.project_action_application import ProjectActionService
from ai_agent_project.agent.project_application import ProjectApplicationService
from ai_agent_project.agent.project_execution import ProjectExecutionService
from ai_agent_project.agent.project_session import ProjectModeProposal
from ai_agent_project.agent.research import (
    ResearchPaperMaterialsPayload,
    ResearchResultAnalysisPayload,
    ResearchResultSubmission,
    ResearchStatus,
    ResearchSynthesisPayload,
    WorkMode,
)
from ai_agent_project.agent.research_application import ResearchApplicationService
from ai_agent_project.agent.state import AgentMessage, AgentState
from ai_agent_project.agent.upgrade import ProjectMode
from ai_agent_project.desktop import DesktopError
from ai_agent_project.desktop_app.application import build_desktop_application
from ai_agent_project.desktop_app.dialogs import DeveloperCheckpointDialog
from ai_agent_project.desktop_app.window import MainWindow
from ai_agent_project.llm.config import ProviderConfig


def snapshot(root):
    return {
        str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()
    }


@pytest.fixture
def product(tmp_path, seeds, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    for key in (
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_MODEL",
        "OPENAI_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(key, raising=False)
    forbidden = Mock(side_effect=AssertionError("Unexpected live provider / process"))
    monkeypatch.setattr("ai_agent_project.llm.runtime.build_openai_client", forbidden)
    root = tmp_path / "data"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    service = build_desktop_application(root, workspace)
    dev_seed, research_seed = seeds
    phase_calls = []

    def execute(*args):
        phase_calls.append(args[-1])
        (workspace / "result.txt").write_text("Implementation fixture")
        return PhaseExecutionResult(
            phase_id="PHASE-1",
            status="completed",
            requirement_ids=("REQ-1",),
            task_ids=("TASK-1",),
            agent_run=AgentState(
                status="completed",
                messages=[
                    AgentMessage(role="tool", content="PRIVATE_TRANSCRIPT_SENTINEL")
                ],
            ),
            repair_attempts=(
                RepairAttempt(
                    attempt=1,
                    failed_requirement_ids=["REQ-1"],
                    agent_run=AgentState(
                        status="completed",
                        messages=[
                            AgentMessage(role="tool", content="PRIVATE_REPAIR_SENTINEL")
                        ],
                    ),
                    acceptance_report=AcceptanceReport(requirements=[]),
                ),
            ),
            acceptance_report=AcceptanceReport(
                requirements=[
                    RequirementValidationResult(
                        requirement_id="REQ-1",
                        status="passed",
                        evidence=["Fixture validated"],
                    )
                ]
            ),
        )

    developer = ProjectApplicationService(
        SimpleNamespace(start=lambda *args, **kwargs: dev_seed._developer_run()),
        ProjectExecutionService(
            SimpleNamespace(execute=execute),
            ProgressReporter(),
            PhaseCheckpointService(),
        ),
        service._developers,
    )
    source = research_seed._approved_run()
    discovery = source.model_copy(
        update={
            "status": ResearchStatus.AWAITING_DIRECTION_SELECTION,
            "selected_direction_id": None,
            "plan_revision_state": None,
        }
    )
    researcher = ResearchApplicationService(
        SimpleNamespace(
            discover=lambda request: discovery.model_copy(update={"request": request})
        ),
        service._researchers,
        SimpleNamespace(
            generate=lambda *args, **kwargs: source.plan_revision_state.active_plan
        ),
        research_seed._ImplementationPlanner(),
        research_seed._ImplementationGenerator(),
        SimpleNamespace(
            analyze=lambda *args: ResearchResultAnalysisPayload(
                limitations=("No measured experiment",)
            )
        ),
        SimpleNamespace(
            synthesize=lambda *args: ResearchSynthesisPayload(
                synthesis_summary="Insufficient measured evidence."
            )
        ),
        SimpleNamespace(
            generate=lambda *args: ResearchPaperMaterialsPayload(
                research_problem="Unmeasured question",
                limitations=("External validation required",),
            )
        ),
    )
    service._developer_application = developer
    service._research_application = researcher
    service._actions = ProjectActionService(service._sessions, developer, researcher)
    service._bootstrap._project_application = developer

    def project(mode):
        service._sessions._mode_proposer = SimpleNamespace(
            propose=lambda *args, **kwargs: ProjectModeProposal(
                proposed_work_mode=mode,
                proposed_project_mode=ProjectMode.NEW,
                rationale="Explicit fixture proposal",
            )
        )
        pid = service.create_project(
            "Build a small local application", title=mode.value
        )
        assert service.get_project_view(pid).project.work_mode is None
        assert service.get_project_view(pid).developer is None
        service.confirm_project_mode(pid, mode, ProjectMode.NEW)
        return pid

    return SimpleNamespace(
        service=service,
        root=root,
        workspace=workspace,
        phase_calls=phase_calls,
        project=project,
        forbidden=forbidden,
    )


def test_fresh_frozen_paths_no_provider_or_workflow(tmp_path, monkeypatch):
    from ai_agent_project.paths import runtime_paths

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    for key in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
        monkeypatch.setenv(key, str(tmp_path / key))
    for key in (
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_MODEL",
        "OPENAI_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr("ai_agent_project.paths.is_frozen", lambda: True)
    blocked = Mock(side_effect=AssertionError("Provider called on startup"))
    monkeypatch.setattr("ai_agent_project.llm.runtime.build_openai_client", blocked)
    app = QApplication.instance() or QApplication([])
    service = build_desktop_application()
    win = MainWindow(service)
    win.show()
    for name in win.NAVIGATION:
        win.navigate(name)
    assert runtime_paths().workspace.is_dir()
    assert service.get_dashboard().total_projects == 0
    assert not service.get_improvement_overview().evaluations
    service.save_provider_config(
        ProviderConfig(
            base_url="https://custom.example.test/v1",
            model="custom-model",
            api_key="synthetic-audit-only",
        )
    )
    assert (
        "synthetic-audit-only" not in (runtime_paths().config / "llm.json").read_text()
    )
    assert win.close()
    app.processEvents()
    fresh = build_desktop_application()
    assert not fresh.get_provider_config().credential_configured
    assert fresh.get_provider_config().model == "custom-model"
    blocked.assert_not_called()


def test_developer_gui_journey_completion_and_restart(product, monkeypatch):
    app = QApplication.instance() or QApplication([])
    errors = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: errors.append(args[2]))
    service = product.service
    pid = product.project(WorkMode.DEVELOPER)
    rid = service.create_developer_run(pid)
    assert not service.get_project_view(pid).developer.bound
    service.bind_developer_run(pid, rid)
    assert not list(product.workspace.iterdir())
    win = MainWindow(service)
    win.select_project(pid)
    win.navigate("Developer")

    def click():
        button = win.pages["Developer"].findChild(QPushButton, "continue_developer")
        button.click()
        deadline = time.monotonic() + 5
        while win.busy and time.monotonic() < deadline:
            app.processEvents()
            QTest.qWait(5)
        assert not win.busy

    with pytest.raises(DesktopError):
        service.continue_developer(pid)
    service.approve_developer_plan(pid)
    win.refresh()
    click()
    assert service.get_project_view(pid).developer.status == "awaiting_checkpoint"
    assert product.phase_calls == ["PHASE-1"]
    dialog = DeveloperCheckpointDialog()
    assert dialog.decision.currentData() is None and not dialog.confirm.isEnabled()

    def approve(dialog):
        dialog.decision.setCurrentIndex(dialog.decision.findData("approve"))
        return dialog.DialogCode.Accepted

    monkeypatch.setattr(DeveloperCheckpointDialog, "exec", approve)
    click()
    assert not errors
    assert service.get_project_view(pid).developer.status == "completed"
    assert product.phase_calls == ["PHASE-1"]
    assert service.list_project_artifacts(pid)
    service.complete_project(pid)
    before = snapshot(product.root)
    win.close()
    fresh = build_desktop_application(product.root, product.workspace)
    assert fresh.get_project_view(pid).project.status == "completed"
    assert snapshot(product.root) == before


def test_execution_artifact_excludes_private_agent_state(product):
    service = product.service
    pid = product.project(WorkMode.DEVELOPER)
    rid = service.create_developer_run(pid)
    service.bind_developer_run(pid, rid)
    service.approve_developer_plan(pid)
    service.continue_developer(pid)
    before = snapshot(product.root)
    artifact = next(
        a
        for a in service.list_project_artifacts(pid)
        if a.artifact_type == "execution_state"
    )
    preview = service.get_artifact_view(pid, artifact.artifact_id).content
    assert "PRIVATE_TRANSCRIPT_SENTINEL" not in preview
    assert "PRIVATE_REPAIR_SENTINEL" not in preview
    assert '"agent_run"' not in preview
    assert '"messages"' not in preview
    assert '"tool_calls"' not in preview
    assert "awaiting_checkpoint" in preview
    destination = product.workspace / "execution.json"
    service.export_artifact(pid, artifact.artifact_id, destination)
    assert "PRIVATE_TRANSCRIPT_SENTINEL" not in destination.read_text()
    assert snapshot(product.root) == before


def research_to_artifacts(product, mode):
    service = product.service
    pid = product.project(mode)
    rid = service.create_research_run(pid)
    service.bind_research_run(pid, rid)
    view = service.get_project_view(pid)
    assert view.researcher.pending_action.action_type == "select_research_direction"
    service.select_research_direction(pid, view.researcher.directions[0].direction_id)
    assert service.get_project_view(pid).researcher.status == "direction_selected"
    service.continue_researcher(pid)
    assert (
        service.get_project_view(pid).researcher.pending_action.action_type
        == "approve_research_plan"
    )
    service.approve_research_plan(pid)
    service.continue_researcher(pid)
    service.continue_researcher(pid)
    assert (
        service.get_project_view(pid).researcher.pending_action.action_type
        == "provide_research_results"
    )
    return pid, rid


@pytest.mark.parametrize("mode", [WorkMode.RESEARCHER, WorkMode.HYBRID])
def test_research_hybrid_full_journey_no_execution(product, mode, monkeypatch):
    launch = Mock(side_effect=AssertionError("Researcher attempted execution"))
    monkeypatch.setattr("subprocess.run", launch)
    pid, rid = research_to_artifacts(product, mode)
    service = product.service
    assert not list(product.workspace.iterdir())
    assert not product.phase_calls
    if mode == WorkMode.HYBRID:
        artifact = next(
            a
            for a in service.list_project_artifacts(pid)
            if a.artifact_type == "research_plan_revision"
        )
        before = service._researchers.get(rid)
        handoff = service.create_handoff(pid, artifact.artifact_id)
        assert not service.get_project_view(pid).developer.bound
        did = service.bootstrap_developer_from_handoff(
            pid, handoff, "Implement approved research"
        )
        assert (
            service.get_project_view(pid).developer.status == "awaiting_plan_approval"
        )
        assert service._developers.get(did).research_bootstrap.handoff_id == handoff
        assert service._researchers.get(rid) == before
        developer_before = service._developers.get(did)
    service.provide_research_results(
        pid,
        ResearchResultSubmission(
            research_run_id=rid,
            approved_plan_version=1,
            implementation_plan_version=1,
            user_observations=(
                "External manual review only; no experiments executed.",
            ),
        ),
    )
    assert service._researchers.get(rid).result_analysis is None
    for expected in (
        "research_results_analyzed",
        "research_synthesis_ready",
        "paper_materials_ready",
    ):
        service.continue_researcher(pid)
        assert service.get_project_view(pid).researcher.status == expected
    if mode == WorkMode.HYBRID:
        assert service._developers.get(did) == developer_before
        service.approve_developer_plan(pid)
        assert service._researchers.get(rid).status.value == "paper_materials_ready"
    assert not list(product.workspace.iterdir())
    launch.assert_not_called()
    artifacts = service.list_project_artifacts(pid)
    exported = product.workspace / "artifact.json"
    service.export_artifact(pid, artifacts[-1].artifact_id, exported)
    with pytest.raises(DesktopError):
        service.export_artifact(pid, artifacts[-1].artifact_id, exported)
    before = snapshot(product.root)
    fresh = build_desktop_application(product.root, product.workspace)
    assert fresh.get_project_view(pid) == service.get_project_view(pid)
    assert fresh.list_handoffs(pid) == service.list_handoffs(pid)
    assert snapshot(product.root) == before


def test_provider_failure_before_creation_keeps_project_unbound(product):
    service = product.service
    pid = product.project(WorkMode.DEVELOPER)
    service._developer_application._project_runner.start = Mock(
        side_effect=ValueError("synthetic-provider-failure")
    )
    before = snapshot(product.root)
    with pytest.raises(ValueError):
        service.create_developer_run(pid)
    assert snapshot(product.root) == before
    assert not service.get_project_view(pid).developer.bound
    assert not list(product.workspace.iterdir())


@pytest.mark.parametrize("failure", ["digest", "rebound"])
def test_invalid_handoff_keeps_workflows_unchanged(product, failure):
    import json

    service = product.service
    pid, rid = research_to_artifacts(product, WorkMode.HYBRID)
    artifact = next(
        a
        for a in service.list_project_artifacts(pid)
        if a.artifact_type == "research_plan_revision"
    )
    hid = service.create_handoff(pid, artifact.artifact_id)
    if failure == "digest":
        path = product.root / "handoffs" / f"{hid}.json"
        data = json.loads(path.read_text())
        data["content_sha256"] = "0" * 64
        path.write_text(json.dumps(data))
    else:
        replacement = service.create_research_run(pid)
        service.bind_research_run(pid, replacement)
    before = snapshot(product.root)
    with pytest.raises(DesktopError):
        service.bootstrap_developer_from_handoff(pid, hid, "Build it")
    assert snapshot(product.root) == before
    assert not service.get_project_view(pid).developer.bound
    assert service._researchers.get(rid).implementation_package is not None
