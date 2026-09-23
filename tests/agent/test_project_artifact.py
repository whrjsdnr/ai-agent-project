import pytest

from ai_agent_project.agent.plan import ImplementationPlan
from ai_agent_project.agent.plan_revision import PlanRevisionState
from ai_agent_project.agent.project import (
    ProjectPhase,
    ProjectPlan,
    ProjectSpecification,
)
from ai_agent_project.agent.project_application import InMemoryProjectRunStore
from ai_agent_project.agent.project_artifact import (
    ProjectArtifactSource,
    ProjectArtifactType,
)
from ai_agent_project.agent.project_artifact_application import (
    ProjectArtifactError,
    ProjectArtifactNotFoundError,
    ProjectArtifactService,
)
from ai_agent_project.agent.project_execution import (
    PhaseExecutionRecord,
    ProjectExecutionState,
    ProjectExecutionStatus,
)
from ai_agent_project.agent.project_runner import ProjectRun
from ai_agent_project.agent.project_session import ProjectModeProposal, ProjectStatus
from ai_agent_project.agent.project_session_application import (
    InMemoryProjectSessionStore,
    ProjectSessionService,
)
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
from ai_agent_project.agent.research_application import InMemoryResearchRunStore
from ai_agent_project.agent.specification import Specification
from ai_agent_project.agent.upgrade import (
    BaselineStatus,
    BaselineValidation,
    ProjectMode,
    UpgradeContext,
    UpgradeImpact,
    UpgradeRequest,
    UpgradeSpecification,
)
from ai_agent_project.agent.workspace import WorkspaceSnapshot


def _proposal() -> ProjectModeProposal:
    return ProjectModeProposal(
        proposed_work_mode=WorkMode.DEVELOPER,
        proposed_project_mode=ProjectMode.NEW,
        rationale="Advisory",
    )


class _Proposer:
    def propose(self, _request: str) -> ProjectModeProposal:
        return _proposal()


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


def _developer_run(*, upgrade: bool = False, revisions: int = 1) -> ProjectRun:
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
    if revisions == 2:
        plan = _project_plan(implementation_plan, "Revised")
        revision_state = revision_state.revise(plan, "Make it clearer")
    context = None
    if upgrade:
        context = UpgradeContext(
            request=UpgradeRequest(request_text="Upgrade it"),
            codebase_analysis={"summary": "Existing system"},
            upgrade_specification=UpgradeSpecification(
                title="Upgrade",
                objective="Upgrade it",
                current_system_summary="Existing system",
                requirements=tuple(specification.requirements),
                impact=UpgradeImpact(affected_files=("src/app.py",)),
            ),
            baseline_validation=BaselineValidation(status=BaselineStatus.UNAVAILABLE),
        )
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
        mode=ProjectMode.UPGRADE if upgrade else ProjectMode.NEW,
        upgrade_context=context,
    )


def _services() -> tuple[
    ProjectSessionService,
    ProjectArtifactService,
    InMemoryProjectRunStore,
    InMemoryResearchRunStore,
]:
    sessions = InMemoryProjectSessionStore()
    developers = InMemoryProjectRunStore()
    researchers = InMemoryResearchRunStore()
    session_service = ProjectSessionService(
        sessions, _Proposer(), developers, researchers
    )
    return (
        session_service,
        ProjectArtifactService(session_service, developers, researchers),
        developers,
        researchers,
    )


def _active_project(service: ProjectSessionService, mode: WorkMode) -> str:
    project_id = service.create_project_request("Request").id
    service.confirm_project_mode(project_id, mode, ProjectMode.NEW)
    return project_id


def test_awaiting_and_unbound_projects_have_explicit_empty_catalogs() -> None:
    sessions, artifacts, _, _ = _services()
    awaiting = sessions.create_project_request("Awaiting").id
    assert sessions.get_project(awaiting).project.status is (
        ProjectStatus.AWAITING_MODE_CONFIRMATION
    )
    assert artifacts.list_artifacts(awaiting).artifacts == ()

    developer = _active_project(sessions, WorkMode.DEVELOPER)
    researcher = _active_project(sessions, WorkMode.RESEARCHER)
    assert artifacts.list_artifacts(developer).artifacts == ()
    assert artifacts.list_artifacts(researcher).artifacts == ()


def test_developer_catalog_is_semantic_versioned_and_excludes_internals() -> None:
    sessions, artifacts, developers, _ = _services()
    run = _developer_run(upgrade=True, revisions=2)
    developers.create("developer-run", run)
    project_id = _active_project(sessions, WorkMode.DEVELOPER)
    before = sessions.bind_developer_run(project_id, "developer-run").project

    catalog = artifacts.list_artifacts(project_id)
    types = tuple(item.artifact_type for item in catalog.artifacts)
    assert types == (
        ProjectArtifactType.SPECIFICATION,
        ProjectArtifactType.PROJECT_SPECIFICATION,
        ProjectArtifactType.IMPLEMENTATION_PLAN,
        ProjectArtifactType.PROJECT_PLAN,
        ProjectArtifactType.PROJECT_PLAN_REVISION,
        ProjectArtifactType.PROJECT_PLAN_REVISION,
        ProjectArtifactType.PLAN_REVISION_HISTORY,
        ProjectArtifactType.EXECUTION_STATE,
        ProjectArtifactType.UPGRADE_CONTEXT,
    )
    revisions = [
        item
        for item in catalog.artifacts
        if item.artifact_type is ProjectArtifactType.PROJECT_PLAN_REVISION
    ]
    assert [item.source_version for item in revisions] == ["v1", "v2"]
    assert all(
        item.source_domain is ProjectArtifactSource.DEVELOPER for item in revisions
    )
    assert not {"agent_state", "phase_execution", "workspace_file"} & {
        item.artifact_type.value for item in catalog.artifacts
    }
    assert sessions.get_project(project_id).project == before
    assert developers.get("developer-run") == run

    plan_view = artifacts.get_artifact(project_id, catalog.artifacts[3].artifact_id)
    assert plan_view.content == run.project_plan.model_dump(mode="json")
    assert developers.get("developer-run") == run


def test_foreign_artifact_and_missing_linked_runs_are_rejected() -> None:
    sessions, artifacts, developers, researchers = _services()
    developers.create("run-one", _developer_run())
    developers.create("run-two", _developer_run())
    first = _active_project(sessions, WorkMode.DEVELOPER)
    second = _active_project(sessions, WorkMode.DEVELOPER)
    sessions.bind_developer_run(first, "run-one")
    sessions.bind_developer_run(second, "run-two")
    foreign_id = artifacts.list_artifacts(second).artifacts[0].artifact_id
    with pytest.raises(ProjectArtifactNotFoundError):
        artifacts.get_artifact(first, foreign_id)

    missing_developer = _active_project(sessions, WorkMode.DEVELOPER)
    sessions.bind_developer_run(missing_developer, "missing-developer")
    with pytest.raises(ProjectArtifactError, match="Linked Developer run not found"):
        artifacts.list_artifacts(missing_developer)

    missing_research = _active_project(sessions, WorkMode.RESEARCHER)
    sessions.bind_research_run(missing_research, "missing-research")
    with pytest.raises(ProjectArtifactError, match="Linked Researcher run not found"):
        artifacts.list_artifacts(missing_research)
    assert researchers.get("missing-research") is None


def test_hybrid_catalog_keeps_stable_domain_order_without_merging() -> None:
    sessions, artifacts, developers, researchers = _services()
    developer = _developer_run()
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
    developers.create("developer", developer)
    researchers.create("researcher", research)
    project_id = _active_project(sessions, WorkMode.HYBRID)
    sessions.bind_developer_run(project_id, "developer")
    before = sessions.bind_research_run(project_id, "researcher").project

    catalog = artifacts.list_artifacts(project_id)
    domains = tuple(item.source_domain for item in catalog.artifacts)
    first_researcher = domains.index(ProjectArtifactSource.RESEARCHER)
    assert all(
        item is ProjectArtifactSource.DEVELOPER for item in domains[:first_researcher]
    )
    assert all(
        item is ProjectArtifactSource.RESEARCHER for item in domains[first_researcher:]
    )
    assert len({item.artifact_id for item in catalog.artifacts}) == len(
        catalog.artifacts
    )
    assert sessions.get_project(project_id).project == before
    assert developers.get("developer") == developer
    assert researchers.get("researcher") == research
