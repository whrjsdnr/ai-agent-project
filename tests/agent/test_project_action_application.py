from types import SimpleNamespace

import pytest

from ai_agent_project.agent.plan_revision import PlanReviewStatus
from ai_agent_project.agent.project_action_application import (
    ApproveDeveloperPlanCommand,
    ApproveResearchPlanCommand,
    ProjectActionCompletedError,
    ProjectActionNotAllowedError,
    ProjectActionService,
    ProjectActionSource,
    SelectResearchDirectionCommand,
)
from ai_agent_project.agent.project_execution import ProjectExecutionStatus
from ai_agent_project.agent.project_session import (
    ProjectModeProposal,
    ProjectPendingActionType,
)
from ai_agent_project.agent.project_session_application import (
    InMemoryProjectSessionStore,
    ProjectSessionError,
    ProjectSessionService,
)
from ai_agent_project.agent.research import ResearchStatus, WorkMode
from ai_agent_project.agent.research_application import ResearchDirectionNotFoundError
from ai_agent_project.agent.upgrade import ProjectMode


class _Proposer:
    def propose(self, _request: str) -> ProjectModeProposal:
        return ProjectModeProposal(
            proposed_work_mode=WorkMode.DEVELOPER,
            proposed_project_mode=ProjectMode.NEW,
            rationale="Advisory",
        )


class _DeveloperService:
    def __init__(self, runs: dict[str, object]) -> None:
        self.runs = runs
        self.approvals: list[str] = []

    def get(self, run_id: str):
        return self.runs.get(run_id)

    def approve_plan(self, run_id: str):
        self.approvals.append(run_id)
        run = self.runs[run_id]
        run.plan_revision_state.status = PlanReviewStatus.APPROVED
        run.execution_state.status = ProjectExecutionStatus.READY
        return SimpleNamespace(project_run=run)


class _ResearchService:
    def __init__(
        self, runs: dict[str, object], directions: dict[str, set[str]] | None = None
    ) -> None:
        self.runs = runs
        self.directions = directions or {}
        self.selections: list[tuple[str, str]] = []
        self.approvals: list[str] = []

    def get(self, run_id: str):
        return self.runs.get(run_id)

    def select_research_direction(self, run_id: str, direction_id: str):
        if direction_id not in self.directions.get(run_id, set()):
            raise ResearchDirectionNotFoundError(
                f"Research direction not found: {direction_id}"
            )
        self.selections.append((run_id, direction_id))
        run = self.runs[run_id]
        run.status = ResearchStatus.DIRECTION_SELECTED
        run.selected_direction_id = direction_id
        return SimpleNamespace(research_run=run)

    def approve_plan(self, run_id: str):
        self.approvals.append(run_id)
        run = self.runs[run_id]
        run.status = ResearchStatus.RESEARCH_PLAN_APPROVED
        return SimpleNamespace(research_run=run)


def _developer_run():
    return SimpleNamespace(
        plan_revision_state=SimpleNamespace(status=PlanReviewStatus.AWAITING_APPROVAL),
        execution_state=SimpleNamespace(
            status=ProjectExecutionStatus.AWAITING_PLAN_APPROVAL
        ),
    )


def _research_run(status: ResearchStatus):
    return SimpleNamespace(status=status, selected_direction_id=None)


def _services(
    mode: WorkMode,
    *,
    developer_runs: dict[str, object] | None = None,
    research_runs: dict[str, object] | None = None,
    directions: dict[str, set[str]] | None = None,
):
    developer = _DeveloperService(developer_runs or {})
    research = _ResearchService(research_runs or {}, directions)
    sessions = ProjectSessionService(
        InMemoryProjectSessionStore(), _Proposer(), developer, research
    )
    project_id = sessions.create_project_request("Request").id
    sessions.confirm_project_mode(project_id, mode, ProjectMode.NEW)
    actions = ProjectActionService(sessions, developer, research)
    return sessions, actions, developer, research, project_id


def test_routes_one_developer_approval_and_rejects_repetition() -> None:
    run = _developer_run()
    sessions, actions, developer, _, project_id = _services(
        WorkMode.DEVELOPER, developer_runs={"D": run}
    )
    before_project = sessions.bind_developer_run(project_id, "D").project

    result = actions.approve_developer_plan(
        ApproveDeveloperPlanCommand(project_id=project_id)
    )

    assert developer.approvals == ["D"]
    assert result.source_domain is ProjectActionSource.DEVELOPER
    assert result.source_run_id == "D"
    assert result.previous_pending_action.action_type is (
        ProjectPendingActionType.APPROVE_DEVELOPER_PLAN
    )
    assert result.next_pending_action is not None
    assert result.next_pending_action.action_type is (
        ProjectPendingActionType.CONTINUE_DEVELOPER
    )
    assert sessions.get_project(project_id).project == before_project
    with pytest.raises(ProjectActionNotAllowedError, match="current pending action"):
        actions.approve_developer_plan(
            ApproveDeveloperPlanCommand(project_id=project_id)
        )
    assert developer.approvals == ["D"]


def test_developer_wrong_action_missing_run_and_completed_are_rejected() -> None:
    sessions, actions, developer, _, project_id = _services(WorkMode.DEVELOPER)
    sessions.bind_developer_run(project_id, "missing")
    with pytest.raises(ProjectSessionError, match="Linked Developer run not found"):
        actions.approve_developer_plan(
            ApproveDeveloperPlanCommand(project_id=project_id)
        )
    assert developer.approvals == []

    run = _developer_run()
    sessions, actions, developer, _, project_id = _services(
        WorkMode.DEVELOPER, developer_runs={"D": run}
    )
    sessions.bind_developer_run(project_id, "D")
    sessions.complete_project(project_id)
    with pytest.raises(ProjectActionCompletedError, match="Completed project"):
        actions.approve_developer_plan(
            ApproveDeveloperPlanCommand(project_id=project_id)
        )
    assert developer.approvals == []


def test_routes_exact_research_direction_and_rejects_unknown_or_repeated() -> None:
    run = _research_run(ResearchStatus.AWAITING_DIRECTION_SELECTION)
    sessions, actions, _, research, project_id = _services(
        WorkMode.RESEARCHER,
        research_runs={"R": run},
        directions={"R": {"RD-1", "RD-2"}},
    )
    before_project = sessions.bind_research_run(project_id, "R").project

    with pytest.raises(ResearchDirectionNotFoundError, match="FOREIGN"):
        actions.select_research_direction(
            SelectResearchDirectionCommand(
                project_id=project_id, direction_id="FOREIGN"
            )
        )
    assert research.selections == []
    result = actions.select_research_direction(
        SelectResearchDirectionCommand(project_id=project_id, direction_id="RD-2")
    )
    assert run.selected_direction_id == "RD-2"
    assert research.selections == [("R", "RD-2")]
    assert result.next_pending_action is not None
    assert result.next_pending_action.action_type is (
        ProjectPendingActionType.CONTINUE_RESEARCHER
    )
    assert sessions.get_project(project_id).project == before_project
    with pytest.raises(ProjectActionNotAllowedError):
        actions.select_research_direction(
            SelectResearchDirectionCommand(project_id=project_id, direction_id="RD-1")
        )
    assert research.selections == [("R", "RD-2")]


def test_routes_research_plan_approval_and_rejects_wrong_or_repeated() -> None:
    run = _research_run(ResearchStatus.AWAITING_RESEARCH_PLAN_APPROVAL)
    sessions, actions, developer, research, project_id = _services(
        WorkMode.RESEARCHER, research_runs={"R": run}
    )
    sessions.bind_research_run(project_id, "R")
    with pytest.raises(ProjectActionNotAllowedError):
        actions.approve_developer_plan(
            ApproveDeveloperPlanCommand(project_id=project_id)
        )
    assert developer.approvals == []

    result = actions.approve_research_plan(
        ApproveResearchPlanCommand(project_id=project_id)
    )
    assert research.approvals == ["R"]
    assert result.next_pending_action is not None
    assert result.next_pending_action.action_type is (
        ProjectPendingActionType.CONTINUE_RESEARCHER
    )
    with pytest.raises(ProjectActionNotAllowedError):
        actions.approve_research_plan(ApproveResearchPlanCommand(project_id=project_id))
    assert research.approvals == ["R"]


def test_missing_research_run_is_explicit() -> None:
    sessions, actions, _, research, project_id = _services(WorkMode.RESEARCHER)
    sessions.bind_research_run(project_id, "missing")
    with pytest.raises(ProjectSessionError, match="Linked Researcher run not found"):
        actions.select_research_direction(
            SelectResearchDirectionCommand(project_id=project_id, direction_id="RD")
        )
    assert research.selections == []


def test_hybrid_routes_either_independently_pending_domain() -> None:
    developer_run = _developer_run()
    research_run = _research_run(ResearchStatus.AWAITING_DIRECTION_SELECTION)
    sessions, actions, developer, research, project_id = _services(
        WorkMode.HYBRID,
        developer_runs={"D": developer_run},
        research_runs={"R": research_run},
        directions={"R": {"RD"}},
    )
    sessions.bind_developer_run(project_id, "D")
    sessions.bind_research_run(project_id, "R")

    before_project = sessions.get_project(project_id).project
    actions.select_research_direction(
        SelectResearchDirectionCommand(project_id=project_id, direction_id="RD")
    )
    assert research.selections == [("R", "RD")]
    assert developer.approvals == []
    actions.approve_developer_plan(ApproveDeveloperPlanCommand(project_id=project_id))
    assert developer.approvals == ["D"]
    assert research.selections == [("R", "RD")]
    assert sessions.get_project(project_id).project == before_project


def test_hybrid_mode_alone_does_not_authorize_absent_lane_action() -> None:
    developer_run = _developer_run()
    research_run = _research_run(ResearchStatus.AWAITING_RESEARCH_PLAN_APPROVAL)
    sessions, actions, developer, research, project_id = _services(
        WorkMode.HYBRID,
        developer_runs={"D": developer_run},
        research_runs={"R": research_run},
    )
    sessions.bind_developer_run(project_id, "D")
    sessions.bind_research_run(project_id, "R")

    with pytest.raises(ProjectActionNotAllowedError, match="select_research_direction"):
        actions.select_research_direction(
            SelectResearchDirectionCommand(project_id=project_id, direction_id="RD")
        )
    assert developer.approvals == []
    assert research.selections == []


def test_hybrid_research_plan_approval_is_independent_of_developer_action() -> None:
    developer_run = _developer_run()
    research_run = _research_run(ResearchStatus.AWAITING_RESEARCH_PLAN_APPROVAL)
    sessions, actions, developer, research, project_id = _services(
        WorkMode.HYBRID,
        developer_runs={"D": developer_run},
        research_runs={"R": research_run},
    )
    sessions.bind_developer_run(project_id, "D")
    before = sessions.bind_research_run(project_id, "R").project

    actions.approve_research_plan(ApproveResearchPlanCommand(project_id=project_id))

    assert research.approvals == ["R"]
    assert developer.approvals == []
    assert sessions.get_project(project_id).project == before
