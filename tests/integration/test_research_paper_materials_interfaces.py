"""Persistent CLI and HTTP coverage for 3C-2 paper materials."""

from io import StringIO
from pathlib import Path

from fastapi.testclient import TestClient
from test_research_paper_materials import _payload, _ready_service
from test_research_synthesis import _analyzed_service

from ai_agent_project.agent.research import (
    ResearchMeasurementStatus,
    ResearchStatus,
    ResearchTaskExecutionStatus,
)
from ai_agent_project.agent.research_application import ResearchApplicationService
from ai_agent_project.agent.research_file_store import FileResearchRunStore
from ai_agent_project.api.app import create_app
from ai_agent_project.cli import run_cli


class _Generator:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, *args: object) -> object:
        self.calls += 1
        return _payload()


class _FailingGenerator:
    def generate(self, *args: object) -> object:
        raise AssertionError("a read operation invoked the generator")


def _store_ready_run(root: Path, run_id: str, generator: object) -> None:
    _, source_store = _ready_service(generator)
    run = source_store.get("run")
    assert run is not None
    FileResearchRunStore(root).create(run_id, run)


def _cli_service_builder(generator: object):
    def build(
        _workspace: Path, store: FileResearchRunStore
    ) -> ResearchApplicationService:
        return ResearchApplicationService(
            object(), store, paper_materials_generator=generator
        )

    return build


def test_paper_materials_cli_persists_and_reads_without_provider(
    tmp_path: Path,
) -> None:
    generator = _Generator()
    root = tmp_path / "runs"
    run_id = "00000000-0000-4000-8000-000000000071"
    _store_ready_run(root, run_id, generator)
    before = FileResearchRunStore(root).get(run_id)
    assert before is not None

    generated_output = StringIO()
    assert (
        run_cli(
            ["research", "--store-root", str(root), "paper-materials", run_id],
            research_service_builder=_cli_service_builder(generator),
            stdout=generated_output,
        )
        == 0
    )
    assert "paper_materials_ready" in generated_output.getvalue()
    assert generator.calls == 1

    loaded = FileResearchRunStore(root).get(run_id)
    assert loaded is not None
    assert loaded.status is ResearchStatus.PAPER_MATERIALS_READY
    assert loaded.paper_materials is not None
    observations = {
        observation.metric_id: observation
        for observation in loaded.paper_materials.key_results
    }
    assert observations["M"].value == 0.9123
    assert observations["M2"].value is None
    assert (
        observations["M2"].observation_status is ResearchMeasurementStatus.NOT_MEASURED
    )
    assert (
        loaded.result_submission.task_results[1].execution_status
        is ResearchTaskExecutionStatus.NOT_EXECUTED
    )
    assert loaded.selected_direction_id == before.selected_direction_id
    assert loaded.plan_revision_state == before.plan_revision_state
    assert loaded.implementation_plan == before.implementation_plan
    assert loaded.result_submission == before.result_submission
    assert loaded.result_analysis == before.result_analysis
    assert loaded.result_synthesis == before.result_synthesis

    shown = StringIO()
    assert (
        run_cli(
            ["research", "--store-root", str(root), "show-paper-materials", run_id],
            research_service_builder=_cli_service_builder(_FailingGenerator()),
            stdout=shown,
        )
        == 0
    )
    assert "0.9123" in shown.getvalue()
    assert "not_measured" in shown.getvalue()
    assert FileResearchRunStore(root).get(run_id) == loaded


def test_paper_materials_cli_maps_generation_and_read_errors(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    ready_id = "00000000-0000-4000-8000-000000000072"
    _store_ready_run(root, ready_id, _Generator())
    errors = StringIO()

    assert (
        run_cli(
            [
                "research",
                "--store-root",
                str(root),
                "paper-materials",
                "00000000-0000-4000-8000-000000000099",
            ],
            research_service_builder=_cli_service_builder(_Generator()),
            stderr=errors,
        )
        == 1
    )
    assert "not found" in errors.getvalue().lower()

    errors = StringIO()
    assert (
        run_cli(
            ["research", "--store-root", str(root), "paper-materials", ready_id],
            research_service_builder=_cli_service_builder(None),
            stderr=errors,
        )
        == 1
    )
    assert "not configured" in errors.getvalue().lower()

    errors = StringIO()
    assert (
        run_cli(
            [
                "research",
                "--store-root",
                str(root),
                "show-paper-materials",
                ready_id,
            ],
            research_service_builder=_cli_service_builder(_FailingGenerator()),
            stderr=errors,
        )
        == 1
    )
    assert "not been generated" in errors.getvalue().lower()

    generator = _Generator()
    assert (
        run_cli(
            ["research", "--store-root", str(root), "paper-materials", ready_id],
            research_service_builder=_cli_service_builder(generator),
            stdout=StringIO(),
        )
        == 0
    )
    errors = StringIO()
    assert (
        run_cli(
            ["research", "--store-root", str(root), "paper-materials", ready_id],
            research_service_builder=_cli_service_builder(generator),
            stderr=errors,
        )
        == 1
    )
    assert "require completed research synthesis" in errors.getvalue().lower()

    _, source_store = _analyzed_service()
    wrong_state = source_store.get("run")
    assert wrong_state is not None
    wrong_id = "00000000-0000-4000-8000-000000000073"
    FileResearchRunStore(root).create(wrong_id, wrong_state)
    errors = StringIO()
    assert (
        run_cli(
            ["research", "--store-root", str(root), "paper-materials", wrong_id],
            research_service_builder=_cli_service_builder(_Generator()),
            stderr=errors,
        )
        == 1
    )
    assert "require completed research synthesis" in errors.getvalue().lower()


def test_paper_materials_api_persists_and_get_is_provider_free(tmp_path: Path) -> None:
    generator = _Generator()
    root = tmp_path / "runs"
    run_id = "00000000-0000-4000-8000-000000000074"
    _store_ready_run(root, run_id, generator)
    before = FileResearchRunStore(root).get(run_id)
    assert before is not None
    writing_service = ResearchApplicationService(
        object(), FileResearchRunStore(root), paper_materials_generator=generator
    )
    created = TestClient(create_app(research_application_service=writing_service)).post(
        f"/v1/research-runs/{run_id}/paper-materials"
    )
    assert created.status_code == 200
    assert created.json()["research_run"]["status"] == "paper_materials_ready"
    assert generator.calls == 1

    reading_service = ResearchApplicationService(
        object(),
        FileResearchRunStore(root),
        paper_materials_generator=_FailingGenerator(),
    )
    shown = TestClient(create_app(research_application_service=reading_service)).get(
        f"/v1/research-runs/{run_id}/paper-materials"
    )
    assert shown.status_code == 200
    assert shown.json()["key_results"] == [
        {
            "metric_id": "M",
            "value": 0.9123,
            "unit": None,
            "observation_status": "measured",
            "notes": None,
        },
        {
            "metric_id": "M2",
            "value": None,
            "unit": None,
            "observation_status": "not_measured",
            "notes": None,
        },
    ]
    assert generator.calls == 1

    loaded = FileResearchRunStore(root).get(run_id)
    assert loaded is not None
    assert loaded.status is ResearchStatus.PAPER_MATERIALS_READY
    assert loaded.paper_materials is not None
    assert loaded.result_submission.task_results[1].execution_status is (
        ResearchTaskExecutionStatus.NOT_EXECUTED
    )
    assert loaded.selected_direction_id == before.selected_direction_id
    assert loaded.plan_revision_state == before.plan_revision_state
    assert loaded.implementation_plan == before.implementation_plan
    assert loaded.result_submission == before.result_submission
    assert loaded.result_analysis == before.result_analysis
    assert loaded.result_synthesis == before.result_synthesis
    assert FileResearchRunStore(root).get(run_id) == loaded


def test_paper_materials_api_maps_lifecycle_configuration_and_read_errors() -> None:
    generator = _Generator()
    service, store = _ready_service(generator)
    client = TestClient(create_app(research_application_service=service))
    assert client.post("/v1/research-runs/missing/paper-materials").status_code == 404
    assert client.get("/v1/research-runs/missing/paper-materials").status_code == 404
    assert client.get("/v1/research-runs/run/paper-materials").status_code == 409

    unconfigured_service, _ = _ready_service()
    unconfigured_client = TestClient(
        create_app(research_application_service=unconfigured_service)
    )
    assert (
        unconfigured_client.post("/v1/research-runs/run/paper-materials").status_code
        == 503
    )

    generated = client.post("/v1/research-runs/run/paper-materials")
    assert generated.status_code == 200
    assert client.post("/v1/research-runs/run/paper-materials").status_code == 409

    _, analyzed_store = _analyzed_service()
    wrong_state = analyzed_store.get("run")
    assert wrong_state is not None
    store.create("wrong", wrong_state)
    assert client.post("/v1/research-runs/wrong/paper-materials").status_code == 409
