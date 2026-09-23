from io import StringIO

from fastapi.testclient import TestClient

from ai_agent_project.agent.project_action_application import (
    ApproveDeveloperPlanCommand,
    ApproveResearchPlanCommand,
    ContinueDeveloperCommand,
    ContinueResearcherCommand,
    ProjectActionNotAllowedError,
    ProjectActionResult,
    ProjectActionSource,
    ProvideResearchResultsCommand,
    SelectResearchDirectionCommand,
)
from ai_agent_project.agent.project_session import (
    ProjectModeProposal,
    ProjectPendingAction,
    ProjectPendingActionType,
    ProjectStatus,
)
from ai_agent_project.agent.project_session_application import (
    InMemoryProjectSessionStore,
    ProjectSessionService,
)
from ai_agent_project.agent.research import ResearchResultSubmission, WorkMode
from ai_agent_project.agent.research_application import ResearchDirectionNotFoundError
from ai_agent_project.agent.upgrade import ProjectMode
from ai_agent_project.api.app import create_app
from ai_agent_project.cli import run_cli


class _Proposer:
    def propose(self, _request: str) -> ProjectModeProposal:
        return ProjectModeProposal(
            proposed_work_mode=WorkMode.DEVELOPER,
            proposed_project_mode=ProjectMode.NEW,
            rationale="Advisory",
        )


def _pending(
    action_type: ProjectPendingActionType,
    *,
    developer_run_id: str | None = None,
    research_run_id: str | None = None,
) -> ProjectPendingAction:
    return ProjectPendingAction(
        action_type=action_type,
        message="Explicit human checkpoint",
        suggested_action="explicit-command",
        developer_run_id=developer_run_id,
        research_run_id=research_run_id,
    )


def _result(
    action: ProjectPendingActionType,
    source: ProjectActionSource,
    run_id: str,
) -> ProjectActionResult:
    previous = _pending(
        action,
        developer_run_id=run_id if source is ProjectActionSource.DEVELOPER else None,
        research_run_id=run_id if source is ProjectActionSource.RESEARCHER else None,
    )
    return ProjectActionResult(
        project_id="P",
        action=action,
        source_domain=source,
        source_run_id=run_id,
        previous_pending_action=previous,
        next_pending_action=_pending(ProjectPendingActionType.CONTINUE_RESEARCHER)
        if source is ProjectActionSource.RESEARCHER
        else _pending(ProjectPendingActionType.CONTINUE_DEVELOPER),
        project_status=ProjectStatus.ACTIVE,
        source_status="ready",
    )


class _Actions:
    def __init__(self) -> None:
        self.commands: list[object] = []

    def approve_developer_plan(
        self, command: ApproveDeveloperPlanCommand
    ) -> ProjectActionResult:
        self.commands.append(command)
        return _result(
            ProjectPendingActionType.APPROVE_DEVELOPER_PLAN,
            ProjectActionSource.DEVELOPER,
            "D",
        )

    def select_research_direction(
        self, command: SelectResearchDirectionCommand
    ) -> ProjectActionResult:
        self.commands.append(command)
        if command.direction_id == "unknown":
            raise ResearchDirectionNotFoundError(
                "Research direction not found: unknown"
            )
        return _result(
            ProjectPendingActionType.SELECT_RESEARCH_DIRECTION,
            ProjectActionSource.RESEARCHER,
            "R",
        )

    def approve_research_plan(
        self, command: ApproveResearchPlanCommand
    ) -> ProjectActionResult:
        self.commands.append(command)
        if command.project_id == "blocked":
            raise ProjectActionNotAllowedError(
                "Project action is not currently allowed"
            )
        return _result(
            ProjectPendingActionType.APPROVE_RESEARCH_PLAN,
            ProjectActionSource.RESEARCHER,
            "R",
        )

    def continue_developer(
        self, command: ContinueDeveloperCommand
    ) -> ProjectActionResult:
        self.commands.append(command)
        return _result(
            ProjectPendingActionType.CONTINUE_DEVELOPER,
            ProjectActionSource.DEVELOPER,
            "D",
        )

    def continue_researcher(
        self, command: ContinueResearcherCommand
    ) -> ProjectActionResult:
        self.commands.append(command)
        return _result(
            ProjectPendingActionType.CONTINUE_RESEARCHER,
            ProjectActionSource.RESEARCHER,
            "R",
        )

    def provide_research_results(
        self, command: ProvideResearchResultsCommand
    ) -> ProjectActionResult:
        self.commands.append(command)
        return _result(
            ProjectPendingActionType.PROVIDE_RESEARCH_RESULTS,
            ProjectActionSource.RESEARCHER,
            "R",
        )


def test_cli_exposes_three_explicit_project_action_commands(tmp_path) -> None:
    actions = _Actions()

    def action_builder(*_args: object):
        return actions

    for arguments, expected in (
        (["approve-developer-plan", "P"], "approve_developer_plan"),
        (["select-research-direction", "P", "RD-2"], "select_research_direction"),
        (["approve-research-plan", "P"], "approve_research_plan"),
    ):
        output = StringIO()
        assert (
            run_cli(
                ["project-session", "--store-root", str(tmp_path), *arguments],
                project_session_service_builder=lambda _store: ProjectSessionService(
                    InMemoryProjectSessionStore(), _Proposer()
                ),
                project_action_service_builder=action_builder,  # type: ignore[arg-type]
                stdout=output,
            )
            == 0
        )
        assert f"Action: {expected}" in output.getvalue()
        assert "Previous pending action:" in output.getvalue()
        assert "Next pending action:" in output.getvalue()

    assert isinstance(actions.commands[0], ApproveDeveloperPlanCommand)
    assert actions.commands[1] == SelectResearchDirectionCommand(
        project_id="P", direction_id="RD-2"
    )
    assert isinstance(actions.commands[2], ApproveResearchPlanCommand)


def test_api_exposes_explicit_typed_routes_and_maps_validation_errors() -> None:
    actions = _Actions()
    sessions = ProjectSessionService(InMemoryProjectSessionStore(), _Proposer())
    client = TestClient(
        create_app(
            project_session_service=sessions,
            project_action_service=actions,  # type: ignore[arg-type]
        )
    )

    developer = client.post("/v1/projects/P/actions/approve-developer-plan")
    selected = client.post(
        "/v1/projects/P/actions/select-research-direction",
        json={"direction_id": "RD-2"},
    )
    approved = client.post("/v1/projects/P/actions/approve-research-plan")
    invalid_direction = client.post(
        "/v1/projects/P/actions/select-research-direction",
        json={"direction_id": "unknown"},
    )
    blocked = client.post("/v1/projects/blocked/actions/approve-research-plan")

    assert developer.status_code == 200
    assert developer.json()["action"] == "approve_developer_plan"
    assert selected.status_code == 200
    assert selected.json()["action"] == "select_research_direction"
    assert approved.status_code == 200
    assert approved.json()["action"] == "approve_research_plan"
    assert invalid_direction.status_code == 404
    assert invalid_direction.json()["detail"] == "Research direction not found: unknown"
    assert blocked.status_code == 409
    assert "not currently allowed" in blocked.json()["detail"]
    assert not any(route.path.endswith("/actions/next") for route in client.app.routes)


def test_cli_exposes_explicit_continuation_and_typed_result_commands(
    tmp_path,
) -> None:
    actions = _Actions()
    submission = ResearchResultSubmission(
        research_run_id="R",
        approved_plan_version=1,
        implementation_plan_version=1,
        user_observations=("Exact observation",),
    )
    result_path = tmp_path / "results.json"
    result_path.write_text(submission.model_dump_json(), encoding="utf-8")

    def action_builder(*_args: object):
        return actions

    for arguments, expected in (
        (["continue-developer", "P"], "continue_developer"),
        (["continue-researcher", "P"], "continue_researcher"),
        (
            ["provide-research-results", "P", "--input", str(result_path)],
            "provide_research_results",
        ),
    ):
        output = StringIO()
        assert (
            run_cli(
                ["project-session", "--store-root", str(tmp_path), *arguments],
                cwd=tmp_path,
                project_session_service_builder=lambda _store: ProjectSessionService(
                    InMemoryProjectSessionStore(), _Proposer()
                ),
                project_action_service_builder=action_builder,  # type: ignore[arg-type]
                stdout=output,
            )
            == 0
        )
        assert f"Action: {expected}" in output.getvalue()

    provided = actions.commands[-1]
    assert isinstance(provided, ProvideResearchResultsCommand)
    assert provided.submission == submission


def test_api_exposes_continuation_and_typed_result_routes() -> None:
    actions = _Actions()
    sessions = ProjectSessionService(InMemoryProjectSessionStore(), _Proposer())
    client = TestClient(
        create_app(
            project_session_service=sessions,
            project_action_service=actions,  # type: ignore[arg-type]
        )
    )
    submission = ResearchResultSubmission(
        research_run_id="R",
        approved_plan_version=1,
        implementation_plan_version=1,
        user_observations=("Exact observation",),
    )

    developer = client.post("/v1/projects/P/actions/continue-developer")
    researcher = client.post("/v1/projects/P/actions/continue-researcher")
    provided = client.post(
        "/v1/projects/P/actions/provide-research-results",
        json=submission.model_dump(mode="json"),
    )
    malformed = client.post(
        "/v1/projects/P/actions/provide-research-results",
        json={"research_run_id": "R"},
    )

    assert developer.status_code == 200
    assert developer.json()["action"] == "continue_developer"
    assert researcher.status_code == 200
    assert researcher.json()["action"] == "continue_researcher"
    assert provided.status_code == 200
    assert provided.json()["action"] == "provide_research_results"
    assert malformed.status_code == 422
    command = actions.commands[-1]
    assert isinstance(command, ProvideResearchResultsCommand)
    assert command.submission == submission
    assert not any("continue-all" in route.path for route in client.app.routes)
