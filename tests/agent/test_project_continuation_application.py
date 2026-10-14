from types import SimpleNamespace
from typing import ClassVar

import pytest
from pydantic import ValidationError

from ai_agent_project.agent.plan_revision import PlanReviewStatus
from ai_agent_project.agent.project_action_application import (
    ContinueDeveloperCommand,
    ContinueResearcherCommand,
    ProjectActionCompletedError,
    ProjectActionNotAllowedError,
    ProjectActionService,
    ProvideResearchResultsCommand,
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
from ai_agent_project.agent.research import (
    ResearchResultSubmission,
    ResearchStatus,
    WorkMode,
)
from ai_agent_project.agent.research_application import ResearchRunError
from ai_agent_project.agent.upgrade import ProjectMode


class _Proposer:
    def propose(self, _request: str) -> ProjectModeProposal:
        return ProjectModeProposal(
            proposed_work_mode=WorkMode.HYBRID,
            proposed_project_mode=ProjectMode.NEW,
            rationale="Advisory",
        )


class _Developer:
    def __init__(self, runs: dict[str, object]) -> None:
        self.runs = runs
        self.executions: list[str] = []

    def get(self, run_id: str):
        return self.runs.get(run_id)

    def approve_plan(self, _run_id: str):
        raise AssertionError("approval was not requested")

    def execute_current_phase(self, run_id: str):
        self.executions.append(run_id)
        run = self.runs[run_id]
        run.execution_state.status = ProjectExecutionStatus.AWAITING_CHECKPOINT
        return SimpleNamespace(project_run=run)


class _Researcher:
    _NEXT: ClassVar[dict[str, ResearchStatus]] = {
        "generate_plan": ResearchStatus.AWAITING_RESEARCH_PLAN_APPROVAL,
        "generate_implementation_plan": ResearchStatus.IMPLEMENTATION_GENERATION_STARTED,
        "generate_implementation_package": ResearchStatus.IMPLEMENTATION_PACKAGE_READY,
        "analyze_results": ResearchStatus.RESEARCH_RESULTS_ANALYZED,
        "generate_synthesis": ResearchStatus.RESEARCH_SYNTHESIS_READY,
        "generate_paper_materials": ResearchStatus.PAPER_MATERIALS_READY,
    }

    def __init__(self, runs: dict[str, object]) -> None:
        self.runs = runs
        self.calls: list[tuple[str, str]] = []
        self.submissions: list[tuple[str, ResearchResultSubmission]] = []

    def get(self, run_id: str):
        return self.runs.get(run_id)

    def get_research_run(self, run_id: str):
        return SimpleNamespace(research_run=self.runs[run_id])

    def approve_plan(self, _run_id: str):
        raise AssertionError("approval was not requested")

    def select_research_direction(self, _run_id: str, _direction_id: str):
        raise AssertionError("selection was not requested")

    def submit_results(self, run_id: str, submission: ResearchResultSubmission):
        if submission.research_run_id != run_id:
            raise ResearchRunError(
                "Result submission references a different research run"
            )
        self.submissions.append((run_id, submission))
        run = self.runs[run_id]
        run.status = ResearchStatus.RESEARCH_RESULTS_SUBMITTED
        run.result_submission = submission
        return SimpleNamespace(research_run=run)

    def _progress(self, name: str, run_id: str):
        self.calls.append((name, run_id))
        run = self.runs[run_id]
        run.status = self._NEXT[name]
        return SimpleNamespace(research_run=run)

    def generate_plan(self, run_id: str):
        return self._progress("generate_plan", run_id)

    def generate_implementation_plan(self, run_id: str):
        return self._progress("generate_implementation_plan", run_id)

    def generate_implementation_package(self, run_id: str):
        return self._progress("generate_implementation_package", run_id)

    def analyze_results(self, run_id: str):
        return self._progress("analyze_results", run_id)

    def generate_synthesis(self, run_id: str):
        return self._progress("generate_synthesis", run_id)

    def generate_paper_materials(self, run_id: str):
        return self._progress("generate_paper_materials", run_id)


def _developer_run(status: ProjectExecutionStatus = ProjectExecutionStatus.READY):
    return SimpleNamespace(
        plan_revision_state=SimpleNamespace(status=PlanReviewStatus.APPROVED),
        execution_state=SimpleNamespace(status=status),
    )


def _research_run(status: ResearchStatus):
    return SimpleNamespace(status=status, result_submission=None)


def _services(
    mode: WorkMode,
    developers: dict[str, object] | None = None,
    researchers: dict[str, object] | None = None,
):
    developer = _Developer(developers or {})
    researcher = _Researcher(researchers or {})
    sessions = ProjectSessionService(
        InMemoryProjectSessionStore(), _Proposer(), developer, researcher
    )
    project_id = sessions.create_project_request("Request").id
    sessions.confirm_project_mode(project_id, mode, ProjectMode.NEW)
    actions = ProjectActionService(sessions, developer, researcher)
    return sessions, actions, developer, researcher, project_id


def _submission(run_id: str) -> ResearchResultSubmission:
    return ResearchResultSubmission(
        research_run_id=run_id,
        approved_plan_version=1,
        implementation_plan_version=1,
        user_observations=("Exact user observation",),
    )


def test_continue_developer_executes_exactly_one_phase_and_keeps_session() -> None:
    run = _developer_run()
    sessions, actions, developer, _, project_id = _services(
        WorkMode.DEVELOPER, {"D": run}
    )
    before = sessions.bind_developer_run(project_id, "D").project

    result = actions.continue_developer(ContinueDeveloperCommand(project_id=project_id))

    assert developer.executions == ["D"]
    assert run.execution_state.status is ProjectExecutionStatus.AWAITING_CHECKPOINT
    assert result.previous_pending_action.action_type is (
        ProjectPendingActionType.CONTINUE_DEVELOPER
    )
    assert result.next_pending_action.action_type is (
        ProjectPendingActionType.CONTINUE_DEVELOPER
    )
    assert sessions.get_project(project_id).project == before


def test_continue_developer_rejects_wrong_missing_and_completed() -> None:
    awaiting = _developer_run(ProjectExecutionStatus.AWAITING_PLAN_APPROVAL)
    awaiting.plan_revision_state.status = PlanReviewStatus.AWAITING_APPROVAL
    sessions, actions, developer, _, project_id = _services(
        WorkMode.DEVELOPER, {"D": awaiting}
    )
    sessions.bind_developer_run(project_id, "D")
    with pytest.raises(ProjectActionNotAllowedError):
        actions.continue_developer(ContinueDeveloperCommand(project_id=project_id))
    assert developer.executions == []

    sessions, actions, developer, _, project_id = _services(WorkMode.DEVELOPER)
    sessions.bind_developer_run(project_id, "missing")
    with pytest.raises(ProjectSessionError, match="Linked Developer run not found"):
        actions.continue_developer(ContinueDeveloperCommand(project_id=project_id))
    assert developer.executions == []

    run = _developer_run()
    sessions, actions, developer, _, project_id = _services(
        WorkMode.DEVELOPER, {"D": run}
    )
    sessions.bind_developer_run(project_id, "D")
    sessions.complete_project(project_id)
    with pytest.raises(ProjectActionCompletedError):
        actions.continue_developer(ContinueDeveloperCommand(project_id=project_id))
    assert developer.executions == []


@pytest.mark.parametrize(
    ("status", "operation", "next_status"),
    (
        (
            ResearchStatus.DIRECTION_SELECTED,
            "generate_plan",
            ResearchStatus.AWAITING_RESEARCH_PLAN_APPROVAL,
        ),
        (
            ResearchStatus.RESEARCH_PLAN_APPROVED,
            "generate_implementation_plan",
            ResearchStatus.IMPLEMENTATION_GENERATION_STARTED,
        ),
        (
            ResearchStatus.IMPLEMENTATION_GENERATION_STARTED,
            "generate_implementation_package",
            ResearchStatus.IMPLEMENTATION_PACKAGE_READY,
        ),
        (
            ResearchStatus.RESEARCH_RESULTS_SUBMITTED,
            "analyze_results",
            ResearchStatus.RESEARCH_RESULTS_ANALYZED,
        ),
        (
            ResearchStatus.RESEARCH_RESULTS_ANALYZED,
            "generate_synthesis",
            ResearchStatus.RESEARCH_SYNTHESIS_READY,
        ),
        (
            ResearchStatus.RESEARCH_SYNTHESIS_READY,
            "generate_paper_materials",
            ResearchStatus.PAPER_MATERIALS_READY,
        ),
    ),
)
def test_continue_researcher_dispatches_exactly_one_nonexecuting_step(
    status: ResearchStatus, operation: str, next_status: ResearchStatus
) -> None:
    run = _research_run(status)
    sessions, actions, _, researcher, project_id = _services(
        WorkMode.RESEARCHER, researchers={"R": run}
    )
    before = sessions.bind_research_run(project_id, "R").project

    result = actions.continue_researcher(
        ContinueResearcherCommand(project_id=project_id)
    )

    assert researcher.calls == [(operation, "R")]
    assert run.status is next_status
    assert result.source_status == next_status.value
    assert sessions.get_project(project_id).project == before


def test_continue_researcher_rejects_unbounded_and_missing_states() -> None:
    run = _research_run(ResearchStatus.DISCOVERING)
    sessions, actions, _, researcher, project_id = _services(
        WorkMode.RESEARCHER, researchers={"R": run}
    )
    sessions.bind_research_run(project_id, "R")
    with pytest.raises(ProjectActionNotAllowedError, match="no bounded progression"):
        actions.continue_researcher(ContinueResearcherCommand(project_id=project_id))
    assert researcher.calls == []

    sessions, actions, _, researcher, project_id = _services(WorkMode.RESEARCHER)
    sessions.bind_research_run(project_id, "missing")
    with pytest.raises(ProjectSessionError, match="Linked Researcher run not found"):
        actions.continue_researcher(ContinueResearcherCommand(project_id=project_id))
    assert researcher.calls == []


@pytest.mark.parametrize(
    "initial_status",
    (
        ResearchStatus.IMPLEMENTATION_PACKAGE_READY,
        ResearchStatus.AWAITING_USER_RESULTS,
    ),
)
def test_provide_results_preserves_payload_and_does_not_analyze(
    initial_status: ResearchStatus,
) -> None:
    run = _research_run(initial_status)
    sessions, actions, _, researcher, project_id = _services(
        WorkMode.RESEARCHER, researchers={"R": run}
    )
    before = sessions.bind_research_run(project_id, "R").project
    submission = _submission("R")

    result = actions.provide_research_results(
        ProvideResearchResultsCommand(project_id=project_id, submission=submission)
    )

    assert researcher.submissions == [("R", submission)]
    assert run.result_submission is submission
    assert run.status is ResearchStatus.RESEARCH_RESULTS_SUBMITTED
    assert researcher.calls == []
    assert result.next_pending_action.action_type is (
        ProjectPendingActionType.CONTINUE_RESEARCHER
    )
    assert sessions.get_project(project_id).project == before
    with pytest.raises(ProjectActionNotAllowedError):
        actions.provide_research_results(
            ProvideResearchResultsCommand(project_id=project_id, submission=submission)
        )


def test_provide_results_rejects_foreign_and_malformed_payloads() -> None:
    run = _research_run(ResearchStatus.AWAITING_USER_RESULTS)
    sessions, actions, _, researcher, project_id = _services(
        WorkMode.RESEARCHER, researchers={"R": run}
    )
    sessions.bind_research_run(project_id, "R")
    with pytest.raises(ResearchRunError, match="different research run"):
        actions.provide_research_results(
            ProvideResearchResultsCommand(
                project_id=project_id, submission=_submission("FOREIGN")
            )
        )
    assert researcher.submissions == []
    with pytest.raises(ValidationError):
        ProvideResearchResultsCommand.model_validate(
            {"project_id": project_id, "submission": {"research_run_id": "R"}}
        )


def test_hybrid_either_continuation_runs_without_cross_domain_chaining() -> None:
    developer_run = _developer_run()
    research_run = _research_run(ResearchStatus.DIRECTION_SELECTED)
    sessions, actions, developer, researcher, project_id = _services(
        WorkMode.HYBRID,
        {"D": developer_run},
        {"R": research_run},
    )
    sessions.bind_developer_run(project_id, "D")
    sessions.bind_research_run(project_id, "R")

    before_project = sessions.get_project(project_id).project
    actions.continue_researcher(ContinueResearcherCommand(project_id=project_id))
    assert researcher.calls == [("generate_plan", "R")]
    assert developer.executions == []
    actions.continue_developer(ContinueDeveloperCommand(project_id=project_id))
    assert developer.executions == ["D"]
    assert researcher.calls == [("generate_plan", "R")]
    assert sessions.get_project(project_id).project == before_project


def test_hybrid_result_intake_is_independent_and_does_not_continue() -> None:
    developer_run = _developer_run()
    research_run = _research_run(ResearchStatus.AWAITING_USER_RESULTS)
    sessions, actions, developer, researcher, project_id = _services(
        WorkMode.HYBRID,
        {"D": developer_run},
        {"R": research_run},
    )
    sessions.bind_developer_run(project_id, "D")
    before = sessions.bind_research_run(project_id, "R").project
    submission = _submission("R")

    actions.provide_research_results(
        ProvideResearchResultsCommand(project_id=project_id, submission=submission)
    )

    assert researcher.submissions == [("R", submission)]
    assert researcher.calls == []
    assert developer.executions == []
    assert sessions.get_project(project_id).project == before
