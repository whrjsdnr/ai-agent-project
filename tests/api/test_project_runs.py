"""HTTP tests for explicit stored project-run lifecycle operations."""

from fastapi.testclient import TestClient

from ai_agent_project.agent.checkpoint import CheckpointDecision
from ai_agent_project.agent.plan import ImplementationPlan
from ai_agent_project.agent.plan_revision import PlanRevisionState
from ai_agent_project.agent.project import (
    ProjectPhase,
    ProjectPlan,
    ProjectSpecification,
)
from ai_agent_project.agent.project_application import (
    InMemoryProjectRunStore,
    ProjectApplicationService,
    ProjectRunNotFoundError,
    StoredProjectRun,
)
from ai_agent_project.agent.project_execution import (
    PhaseExecutionRecord,
    ProjectExecutionState,
    ProjectExecutionStatus,
)
from ai_agent_project.agent.project_runner import ProjectRun
from ai_agent_project.agent.specification import Specification
from ai_agent_project.agent.upgrade import (
    BaselineStatus,
    BaselineValidation,
    UpgradeContext,
    UpgradeImpact,
    UpgradeRequest,
    UpgradeSpecification,
)
from ai_agent_project.agent.workspace import WorkspaceSnapshot


def make_project_run(
    status: ProjectExecutionStatus = ProjectExecutionStatus.READY,
    current_phase_id: str | None = "PHASE-001",
) -> ProjectRun:
    specification = Specification.model_validate(
        {"requirements": [{"id": "REQ-001", "description": "Build feature."}]}
    )
    project_specification = ProjectSpecification.from_specification(specification)
    implementation_plan = ImplementationPlan.model_validate(
        {
            "tasks": [
                {
                    "id": "TASK-001",
                    "title": "Build",
                    "description": "Build feature.",
                    "requirement_ids": ["REQ-001"],
                }
            ]
        }
    )
    project_plan = ProjectPlan(
        project_title="Demo",
        phases=(
            ProjectPhase(
                id="PHASE-001",
                title="First",
                objective="Build first.",
                requirement_ids=("REQ-001",),
                task_ids=("TASK-001",),
            ),
        ),
        implementation_plan=implementation_plan,
    )
    return ProjectRun(
        specification=specification,
        project_specification=project_specification,
        workspace=WorkspaceSnapshot(files=["src/example.py"]),
        implementation_plan=implementation_plan,
        project_plan=project_plan,
        execution_state=ProjectExecutionState(
            project_title="Demo",
            status=status,
            current_phase_id=current_phase_id,
            phase_records=(PhaseExecutionRecord(phase_id="PHASE-001"),),
        ),
    )


class FakeProjectApplicationService:
    def __init__(self) -> None:
        self.created = make_project_run()
        self.execute_result = StoredProjectRun(
            id="run-1", project_run=make_project_run()
        )
        self.decision_result = StoredProjectRun(
            id="run-1", project_run=make_project_run()
        )
        self.create_calls: list[tuple[str, str | None, str | None]] = []
        self.get_calls: list[str] = []
        self.execute_calls: list[str] = []
        self.decision_calls: list[tuple[str, CheckpointDecision, str | None]] = []
        self.plan_calls: list[str] = []
        self.revision_calls: list[tuple[str, str]] = []
        self.approval_calls: list[str] = []
        self.upgrade_calls: list[tuple[str, str | None]] = []
        self.analysis_calls: list[str] = []
        self.get_error: Exception | None = None
        self.execute_error: Exception | None = None
        self.decision_error: Exception | None = None

    def create_project(
        self,
        source_text: str,
        *,
        project_title: str | None = None,
        source_format: str | None = None,
    ) -> StoredProjectRun:
        self.create_calls.append((source_text, project_title, source_format))
        return StoredProjectRun(id="run-1", project_run=self.created)

    def create_upgrade_project(
        self, request_text: str, *, project_title: str | None = None
    ) -> StoredProjectRun:
        self.upgrade_calls.append((request_text, project_title))
        return StoredProjectRun(id="upgrade-1", project_run=self.created)

    def get_analysis(self, project_run_id: str) -> UpgradeContext:
        self.analysis_calls.append(project_run_id)
        return UpgradeContext(
            request=UpgradeRequest(request_text="Add filtering."),
            codebase_analysis={"summary": "Existing API"},
            upgrade_specification=UpgradeSpecification(
                title="Upgrade",
                objective="Add filtering.",
                current_system_summary="Existing API",
                requirements=({"id": "UPG-REQ-001", "description": "Add filtering."},),
                impact=UpgradeImpact(),
            ),
            baseline_validation=BaselineValidation(status=BaselineStatus.UNAVAILABLE),
        )

    def get_project(self, project_run_id: str) -> StoredProjectRun:
        self.get_calls.append(project_run_id)
        if self.get_error:
            raise self.get_error
        return StoredProjectRun(id=project_run_id, project_run=self.created)

    def execute_current_phase(self, project_run_id: str) -> StoredProjectRun:
        self.execute_calls.append(project_run_id)
        if self.execute_error:
            raise self.execute_error
        return self.execute_result

    def get_plan(self, project_run_id: str) -> PlanRevisionState:
        self.plan_calls.append(project_run_id)
        assert self.created.plan_revision_state is not None
        return self.created.plan_revision_state

    def revise_plan(self, project_run_id: str, feedback: str) -> StoredProjectRun:
        self.revision_calls.append((project_run_id, feedback))
        return StoredProjectRun(id=project_run_id, project_run=self.created)

    def approve_plan(self, project_run_id: str) -> StoredProjectRun:
        self.approval_calls.append(project_run_id)
        return StoredProjectRun(id=project_run_id, project_run=self.created)

    def decide_current_phase(
        self,
        project_run_id: str,
        decision: CheckpointDecision,
        *,
        note: str | None = None,
    ) -> StoredProjectRun:
        self.decision_calls.append((project_run_id, decision, note))
        if self.decision_error:
            raise self.decision_error
        return self.decision_result


def make_client(service: FakeProjectApplicationService) -> TestClient:
    from ai_agent_project.api.app import create_app

    return TestClient(create_app(project_application_service=service))  # type: ignore[arg-type]


def test_create_project_run_forwards_metadata_and_does_not_execute() -> None:
    service = FakeProjectApplicationService()
    client = make_client(service)

    response = client.post(
        "/v1/project-runs",
        json={
            "source_text": "# Project",
            "project_title": "Demo",
            "source_format": "markdown",
        },
    )

    assert response.status_code == 201
    assert response.json()["id"] == "run-1"
    assert response.json()["project_run"]["execution_state"]["status"] == "ready"
    assert service.create_calls == [("# Project", "Demo", "markdown")]
    assert service.execute_calls == []


def test_create_project_run_rejects_blank_source_text() -> None:
    service = FakeProjectApplicationService()

    response = make_client(service).post("/v1/project-runs", json={"source_text": " "})

    assert response.status_code == 422
    assert service.create_calls == []


def test_upgrade_create_and_analysis_use_application_service() -> None:
    service = FakeProjectApplicationService()
    client = make_client(service)

    created = client.post(
        "/v1/project-runs/upgrades",
        json={"request_text": "Add filtering.", "project_title": "Todo upgrade"},
    )
    assert created.status_code == 201
    assert created.json()["id"] == "upgrade-1"
    assert service.upgrade_calls == [("Add filtering.", "Todo upgrade")]

    analysis = client.get("/v1/project-runs/upgrade-1/analysis")
    assert analysis.status_code == 200
    assert analysis.json()["codebase_analysis"]["summary"] == "Existing API"
    assert service.analysis_calls == ["upgrade-1"]


def test_get_project_run_is_read_only_and_maps_missing_to_404() -> None:
    service = FakeProjectApplicationService()
    client = make_client(service)

    response = client.get("/v1/project-runs/run-1")
    assert response.status_code == 200
    assert response.json()["id"] == "run-1"
    assert service.get_calls == ["run-1"]
    assert service.execute_calls == []
    assert service.decision_calls == []

    service.get_error = ProjectRunNotFoundError("missing")
    assert client.get("/v1/project-runs/missing").status_code == 404


def test_execute_project_run_forwards_id_and_maps_errors() -> None:
    service = FakeProjectApplicationService()
    service.execute_result = StoredProjectRun(
        id="run-1",
        project_run=make_project_run(ProjectExecutionStatus.AWAITING_CHECKPOINT),
    )
    client = make_client(service)

    response = client.post("/v1/project-runs/run-1/execute")

    assert response.status_code == 200
    assert (
        response.json()["project_run"]["execution_state"]["status"]
        == "awaiting_checkpoint"
    )
    assert service.execute_calls == ["run-1"]
    assert service.create_calls == []

    service.execute_error = ProjectRunNotFoundError("missing")
    assert client.post("/v1/project-runs/missing/execute").status_code == 404
    service.execute_error = ValueError("invalid transition")
    assert client.post("/v1/project-runs/run-1/execute").status_code == 409


def test_decision_endpoints_forward_all_decisions_without_auto_execution() -> None:
    service = FakeProjectApplicationService()
    ready_next_phase = make_project_run(ProjectExecutionStatus.READY)
    service.decision_result = StoredProjectRun(id="run-1", project_run=ready_next_phase)
    client = make_client(service)

    for decision in ("approve", "request_changes", "retry", "stop"):
        response = client.post(
            "/v1/project-runs/run-1/decisions",
            json={"decision": decision, "note": "review note"},
        )
        assert response.status_code == 200

    assert [call[1].value for call in service.decision_calls] == [
        "approve",
        "request_changes",
        "retry",
        "stop",
    ]
    assert all(call[2] == "review note" for call in service.decision_calls)
    assert service.execute_calls == []
    assert service.create_calls == []

    assert (
        client.post(
            "/v1/project-runs/run-1/decisions",
            json={"decision": "not-valid"},
        ).status_code
        == 422
    )
    service.decision_error = ProjectRunNotFoundError("missing")
    assert (
        client.post(
            "/v1/project-runs/missing/decisions",
            json={"decision": "stop"},
        ).status_code
        == 404
    )
    service.decision_error = ValueError("invalid lifecycle")
    assert (
        client.post(
            "/v1/project-runs/run-1/decisions",
            json={"decision": "stop"},
        ).status_code
        == 409
    )


def test_plan_review_endpoints_delegate_without_phase_execution() -> None:
    service = FakeProjectApplicationService()
    client = make_client(service)

    plan = client.get("/v1/project-runs/run-1/plan")
    revised = client.post(
        "/v1/project-runs/run-1/plan/revisions",
        json={"feedback": "Clarify phase responsibilities."},
    )
    approved = client.post("/v1/project-runs/run-1/plan/approve")

    assert plan.status_code == 200
    assert plan.json()["active_version"] == 1
    assert revised.status_code == 200
    assert approved.status_code == 200
    assert service.plan_calls == ["run-1"]
    assert service.revision_calls == [("run-1", "Clarify phase responsibilities.")]
    assert service.approval_calls == ["run-1"]
    assert service.execute_calls == []
    assert (
        client.post(
            "/v1/project-runs/run-1/plan/revisions",
            json={"feedback": " "},
        ).status_code
        == 422
    )


def test_app_scoped_in_memory_store_survives_create_then_get_requests() -> None:
    project_run = make_project_run()

    class FakeRunner:
        def start(self, *args: object, **kwargs: object) -> ProjectRun:
            del args, kwargs
            return project_run

    class FakeExecutionService:
        def execute_current_phase(self, *args: object) -> ProjectExecutionState:
            raise AssertionError("execute must not be called")

        def decide_current_phase(self, *args: object) -> ProjectExecutionState:
            raise AssertionError("decision must not be called")

    application_service = ProjectApplicationService(
        FakeRunner(),  # type: ignore[arg-type]
        FakeExecutionService(),  # type: ignore[arg-type]
        InMemoryProjectRunStore(),
    )
    client = make_client(application_service)  # type: ignore[arg-type]

    created = client.post("/v1/project-runs", json={"source_text": "# Project"})
    project_run_id = created.json()["id"]
    fetched = client.get(f"/v1/project-runs/{project_run_id}")

    assert created.status_code == 201
    assert fetched.status_code == 200
    assert fetched.json()["id"] == project_run_id
