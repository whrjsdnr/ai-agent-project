from io import StringIO
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from ai_agent_project.agent.plan import ImplementationPlan
from ai_agent_project.agent.project import (
    ProjectPhase,
    ProjectPlan,
    ProjectSpecification,
)
from ai_agent_project.agent.project_execution import (
    PhaseExecutionRecord,
    ProjectExecutionState,
    ProjectExecutionStatus,
)
from ai_agent_project.agent.project_file_store import FileProjectRunStore
from ai_agent_project.agent.project_runner import ProjectRun
from ai_agent_project.agent.project_session import (
    ProjectModeProposal,
    ProjectPendingActionType,
    ProjectStatus,
)
from ai_agent_project.agent.project_session_application import (
    InMemoryProjectSessionStore,
    ProjectSessionService,
)
from ai_agent_project.agent.project_session_file_store import FileProjectStore
from ai_agent_project.agent.research import (
    ResearchDirection,
    ResearchDiscoveryReport,
    ResearchEvidence,
    ResearchGap,
    ResearchQuestion,
    ResearchRequest,
    ResearchRun,
    ResearchScope,
    ResearchSource,
    ResearchStatus,
    WorkMode,
)
from ai_agent_project.agent.research_file_store import FileResearchRunStore
from ai_agent_project.agent.specification import Specification
from ai_agent_project.agent.upgrade import ProjectMode
from ai_agent_project.agent.workspace import WorkspaceSnapshot
from ai_agent_project.api.app import create_app
from ai_agent_project.cli import run_cli


class _Proposer:
    def __init__(self) -> None:
        self.calls = 0

    def propose(self, _request: str) -> ProjectModeProposal:
        self.calls += 1
        return ProjectModeProposal(
            proposed_work_mode=WorkMode.HYBRID,
            proposed_project_mode=ProjectMode.UPGRADE,
            rationale="Advisory proposal.",
        )


class _FailingProposer:
    def propose(self, _request: str) -> ProjectModeProposal:
        raise AssertionError("read invoked the proposer")


def _builder(proposer: object):
    def build(store: FileProjectStore) -> ProjectSessionService:
        return ProjectSessionService(store, proposer)  # type: ignore[arg-type]

    return build


def test_project_session_cli_persists_and_reads_without_proposer(
    tmp_path: Path,
) -> None:
    root = tmp_path / "projects"
    proposer = _Proposer()
    created = StringIO()
    assert (
        run_cli(
            ["project-session", "--store-root", str(root), "create", "Study request"],
            project_session_service_builder=_builder(proposer),
            stdout=created,
        )
        == 0
    )
    assert "awaiting_mode_confirmation" in created.getvalue()
    project_id = next(root.glob("*.json")).stem
    assert (
        run_cli(
            [
                "project-session",
                "--store-root",
                str(root),
                "confirm-mode",
                project_id,
                "--work-mode",
                "researcher",
                "--project-mode",
                "new",
            ],
            project_session_service_builder=_builder(proposer),
            stdout=StringIO(),
        )
        == 0
    )
    shown = StringIO()
    assert (
        run_cli(
            ["project-session", "--store-root", str(root), "resume", project_id],
            project_session_service_builder=_builder(_FailingProposer()),
            stdout=shown,
        )
        == 0
    )
    assert "active" in shown.getvalue()
    assert "bind_research_run" in shown.getvalue()
    assert FileProjectStore(root).get(project_id).status is ProjectStatus.ACTIVE


def test_project_session_cli_reports_invalid_lifecycle(tmp_path: Path) -> None:
    root = tmp_path / "projects"
    project_id = "00000000-0000-4000-8000-000000000101"
    project = ProjectSessionService(
        FileProjectStore(root), _Proposer()
    ).create_project_request("x")
    errors = StringIO()
    assert (
        run_cli(
            [
                "project-session",
                "--store-root",
                str(root),
                "bind-research",
                project.id,
                "R",
            ],
            project_session_service_builder=_builder(_Proposer()),
            stderr=errors,
        )
        == 1
    )
    assert "confirmed" in errors.getvalue().lower()
    assert project_id != project.id


def test_project_session_api_confirmation_binding_and_provider_free_reads() -> None:
    proposer = _Proposer()
    store = InMemoryProjectSessionStore()
    service = ProjectSessionService(store, proposer)
    client = TestClient(create_app(project_session_service=service))
    created = client.post("/v1/projects", json={"original_request": "Study"})
    assert created.status_code == 201
    project_id = created.json()["id"]
    assert created.json()["project"]["status"] == "awaiting_mode_confirmation"
    assert proposer.calls == 1
    pending = client.get(f"/v1/projects/{project_id}/pending-action")
    assert pending.status_code == 200
    assert pending.json()["pending_actions"][0]["action_type"] == "confirm_mode"
    confirmed = client.post(
        f"/v1/projects/{project_id}/confirm-mode",
        json={"work_mode": "hybrid", "project_mode": "new"},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["project"]["work_mode"] == "hybrid"
    assert (
        client.post(
            f"/v1/projects/{project_id}/developer-run", json={"run_id": "D"}
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/v1/projects/{project_id}/research-run", json={"run_id": "R"}
        ).status_code
        == 200
    )
    assert client.get(f"/v1/projects/{project_id}").status_code == 200
    resume = client.get(f"/v1/projects/{project_id}/resume")
    assert resume.status_code == 409
    assert proposer.calls == 1
    assert (
        client.post(
            f"/v1/projects/{project_id}/confirm-mode",
            json={"work_mode": "developer", "project_mode": "upgrade"},
        ).status_code
        == 409
    )
    assert client.get("/v1/projects/missing").status_code == 404


def test_pending_actions_resolve_from_fresh_file_stores(tmp_path: Path) -> None:
    session_root = tmp_path / "sessions"
    developer_root = tmp_path / "developers"
    research_root = tmp_path / "research"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    developer_id = str(uuid4())
    research_id = str(uuid4())

    specification = Specification.model_validate(
        {"requirements": [{"id": "REQ-1", "description": "Build it"}]}
    )
    project_specification = ProjectSpecification.from_specification(specification)
    implementation_plan = ImplementationPlan.model_validate(
        {
            "tasks": [
                {
                    "id": "TASK-1",
                    "title": "Build",
                    "description": "Build it",
                    "requirement_ids": ["REQ-1"],
                }
            ]
        }
    )
    project_plan = ProjectPlan(
        project_title="Demo",
        phases=(
            ProjectPhase(
                id="PHASE-1",
                title="Build",
                objective="Build it",
                requirement_ids=("REQ-1",),
                task_ids=("TASK-1",),
            ),
        ),
        implementation_plan=implementation_plan,
    )
    developer_run = ProjectRun(
        specification=specification,
        project_specification=project_specification,
        workspace=WorkspaceSnapshot(files=[]),
        implementation_plan=implementation_plan,
        project_plan=project_plan,
        execution_state=ProjectExecutionState(
            project_title="Demo",
            status=ProjectExecutionStatus.AWAITING_PLAN_APPROVAL,
            current_phase_id="PHASE-1",
            phase_records=(PhaseExecutionRecord(phase_id="PHASE-1"),),
        ),
    )
    research_run = ResearchRun(
        request=ResearchRequest(topic="Topic"),
        status=ResearchStatus.AWAITING_DIRECTION_SELECTION,
        report=ResearchDiscoveryReport(
            questions=(
                ResearchQuestion(
                    id="Q-1",
                    question="Question?",
                    rationale="Needed",
                    source_scope=ResearchScope.EXTERNAL,
                ),
            ),
            sources=(
                ResearchSource(
                    id="S-1",
                    title="Source",
                    locator="https://example.test/source",
                    source_type="article",
                ),
            ),
            evidence=(
                ResearchEvidence(
                    id="E-1",
                    source_id="S-1",
                    question_id="Q-1",
                    claim="Claim",
                    support_text="Support",
                    evidence_type="text",
                ),
            ),
            gaps=(
                ResearchGap(
                    id="GAP-1",
                    description="Gap",
                    evidence_ids=("E-1",),
                    importance="High",
                    feasibility="Feasible",
                ),
            ),
            directions=(
                ResearchDirection(
                    id="DIRECTION-1",
                    title="Direction",
                    research_question="Question?",
                    target_gap_ids=("GAP-1",),
                    novelty="Novel",
                    feasibility="Feasible",
                ),
            ),
        ),
    )
    FileProjectRunStore(developer_root, workspace_root=workspace).create(
        developer_id, developer_run
    )
    FileResearchRunStore(research_root).create(research_id, research_run)
    initial = ProjectSessionService(FileProjectStore(session_root), _Proposer())
    project_id = initial.create_project_request("Request").id
    initial.confirm_project_mode(project_id, WorkMode.HYBRID, ProjectMode.NEW)
    initial.bind_developer_run(project_id, developer_id)
    initial.bind_research_run(project_id, research_id)

    reopened = ProjectSessionService(
        FileProjectStore(session_root),
        _FailingProposer(),  # type: ignore[arg-type]
        FileProjectRunStore(developer_root),
        FileResearchRunStore(research_root),
    )
    actions = reopened.get_pending_actions(project_id)
    assert tuple(action.action_type for action in actions) == (
        ProjectPendingActionType.APPROVE_DEVELOPER_PLAN,
        ProjectPendingActionType.SELECT_RESEARCH_DIRECTION,
    )
    assert FileProjectStore(session_root).get(project_id).updated_at == (
        initial.get_project(project_id).project.updated_at
    )
