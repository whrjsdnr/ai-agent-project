from dataclasses import dataclass
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest

from ai_agent_project.agent.hybrid_coordination_application import (
    HybridCoordinationService,
)
from ai_agent_project.agent.plan import ImplementationPlan
from ai_agent_project.agent.plan_revision import PlanRevisionState
from ai_agent_project.agent.project import (
    ProjectPhase,
    ProjectPlan,
    ProjectSpecification,
)
from ai_agent_project.agent.project_action_application import ProjectActionService
from ai_agent_project.agent.project_application import ProjectApplicationService
from ai_agent_project.agent.project_artifact_application import (
    ProjectArtifactService,
)
from ai_agent_project.agent.project_execution import (
    PhaseExecutionRecord,
    ProjectExecutionService,
    ProjectExecutionState,
    ProjectExecutionStatus,
)
from ai_agent_project.agent.project_file_store import FileProjectRunStore
from ai_agent_project.agent.project_handoff_application import ProjectHandoffService
from ai_agent_project.agent.project_handoff_file_store import FileProjectHandoffStore
from ai_agent_project.agent.project_runner import ProjectRun
from ai_agent_project.agent.project_session import ProjectModeProposal
from ai_agent_project.agent.project_session_application import (
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
from ai_agent_project.agent.research_application import ResearchApplicationService
from ai_agent_project.agent.research_file_store import FileResearchRunStore
from ai_agent_project.agent.specification import Specification
from ai_agent_project.agent.upgrade import (
    ProjectMode,
)
from ai_agent_project.agent.workspace import WorkspaceSnapshot
from ai_agent_project.desktop import DesktopService
from ai_agent_project.llm.config import ProviderConfigService


def _project_plan(
    implementation_plan: ImplementationPlan, title: str = "Initial"
) -> ProjectPlan:
    return ProjectPlan(
        project_title="Demo",
        phases=(
            ProjectPhase(
                id="PHASE-1",
                title=title,
                objective="Build it",
                requirement_ids=("REQ-1",),
                task_ids=("TASK-1",),
            ),
        ),
        implementation_plan=implementation_plan,
    )


def _developer_run() -> ProjectRun:
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
    plan = _project_plan(implementation_plan)
    revision_state = PlanRevisionState.from_plan(plan)
    return ProjectRun(
        specification=specification,
        project_specification=project_specification,
        workspace=WorkspaceSnapshot(files=["src/app.py"]),
        implementation_plan=implementation_plan,
        project_plan=plan,
        execution_state=ProjectExecutionState(
            project_title="Demo",
            status=ProjectExecutionStatus.AWAITING_PLAN_APPROVAL,
            current_phase_id="PHASE-1",
            phase_records=(PhaseExecutionRecord(phase_id="PHASE-1"),),
        ),
        plan_revision_state=revision_state,
        mode=ProjectMode.NEW,
    )


def research_run() -> ResearchRun:
    research = ResearchRun(
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
                    id="SOURCE-1",
                    title="Source",
                    locator="https://example.test/source",
                    source_type="article",
                ),
            ),
            evidence=(
                ResearchEvidence(
                    id="EVIDENCE-1",
                    source_id="SOURCE-1",
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
                    evidence_ids=("EVIDENCE-1",),
                    importance="High",
                    feasibility="Feasible",
                ),
            ),
            directions=(
                ResearchDirection(
                    id="DIRECTION:1",
                    title="Direction",
                    research_question="Question?",
                    target_gap_ids=("GAP-1",),
                    novelty="Novel",
                    feasibility="Feasible",
                ),
            ),
        ),
    )
    return research


@dataclass
class DesktopFixture:
    desktop: DesktopService
    sessions: ProjectSessionService
    developers: FileProjectRunStore
    researchers: FileResearchRunStore
    handoff_store: FileProjectHandoffStore
    artifacts: ProjectArtifactService
    ids: dict[WorkMode, str]
    root: Path

    def snapshot(self) -> dict[str, tuple[bytes, int]]:
        return {
            str(p.relative_to(self.root)): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in self.root.rglob("*")
            if p.is_file()
        }


@pytest.fixture
def setup(tmp_path, monkeypatch) -> DesktopFixture:
    # Block network client construction even when a credential exists.
    monkeypatch.setattr(
        "ai_agent_project.llm.runtime.build_openai_client",
        Mock(side_effect=AssertionError("Unexpected provider call")),
    )
    for variable in (
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_MODEL",
        "OPENAI_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(variable, raising=False)
    developers = FileProjectRunStore(tmp_path / "developers", workspace_root=tmp_path)
    researchers = FileResearchRunStore(tmp_path / "researchers")
    sessions = ProjectSessionService(
        FileProjectStore(tmp_path / "projects"),
        developer_run_reader=developers,
        research_run_reader=researchers,
    )
    from ai_agent_project.agent.project_session import ProjectSession

    ids = {}
    for mode in WorkMode:
        project_id = str(uuid4())
        project = ProjectSession.awaiting_confirmation(
            project_id=project_id,
            title=mode.value,
            original_request="Build a demo",
            mode_proposal=ProjectModeProposal(
                proposed_work_mode=mode,
                proposed_project_mode=ProjectMode.NEW,
                rationale="Fixture",
            ),
        )
        # Seeding is explicit and outside the facade reads under test.
        sessions._store.create(project_id, project)
        sessions.confirm_project_mode(project_id, mode, ProjectMode.NEW)
        if mode in {WorkMode.DEVELOPER, WorkMode.HYBRID}:
            run_id = str(uuid4())
            developers.create(run_id, _developer_run())
            sessions.bind_developer_run(project_id, run_id)
        if mode in {WorkMode.RESEARCHER, WorkMode.HYBRID}:
            run_id = str(uuid4())
            researchers.create(run_id, research_run())
            sessions.bind_research_run(project_id, run_id)
        ids[mode] = project_id
    forbidden = Mock(side_effect=AssertionError("Unexpected workflow execution"))
    developer_app = ProjectApplicationService(
        forbidden, ProjectExecutionService(forbidden, forbidden, forbidden), developers
    )
    research_app = ResearchApplicationService(forbidden, researchers)
    artifacts = ProjectArtifactService(sessions, developers, researchers)
    handoff_store = FileProjectHandoffStore(tmp_path / "handoffs")
    desktop = DesktopService(
        project_sessions=sessions,
        actions=ProjectActionService(sessions, developer_app, research_app),
        artifacts=artifacts,
        handoffs=ProjectHandoffService(sessions, artifacts, handoff_store, researchers),
        coordination=HybridCoordinationService(sessions, developers, researchers),
        provider_config=ProviderConfigService(tmp_path / "settings" / "llm.json"),
        developer_reader=developers,
        research_reader=researchers,
    )
    return DesktopFixture(
        desktop,
        sessions,
        developers,
        researchers,
        handoff_store,
        artifacts,
        ids,
        tmp_path,
    )
