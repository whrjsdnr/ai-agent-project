"""Persistent CLI and HTTP coverage for 3C-1 synthesis."""

import json
from io import StringIO
from pathlib import Path

from fastapi.testclient import TestClient
from test_research_synthesis import _analyzed_service

from ai_agent_project.agent.research import ResearchSynthesisPayload
from ai_agent_project.agent.research_application import ResearchApplicationService
from ai_agent_project.agent.research_file_store import FileResearchRunStore
from ai_agent_project.api.app import create_app
from ai_agent_project.cli import run_cli


class _Synthesizer:
    def __init__(self) -> None:
        self.calls = 0

    def synthesize(self, *args):
        self.calls += 1
        return ResearchSynthesisPayload(
            synthesis_summary="Evidence remains inconclusive.",
            limitations=("No threshold",),
            missing_evidence=("M2 not measured",),
        )


def test_synthesis_cli_persists_and_reads_without_provider(tmp_path: Path) -> None:
    synthesizer = _Synthesizer()
    _, source_store = _analyzed_service(synthesizer)
    run = source_store.get("run")
    assert run is not None
    run_id = "00000000-0000-4000-8000-000000000031"
    root = tmp_path / "runs"
    FileResearchRunStore(root).create(run_id, run)

    def writing_builder(_workspace: Path, store: FileResearchRunStore):
        return ResearchApplicationService(
            object(), store, result_synthesizer=synthesizer
        )

    output = StringIO()
    assert (
        run_cli(
            ["research", "--store-root", str(root), "synthesize", run_id],
            research_service_builder=writing_builder,
            stdout=output,
        )
        == 0
    )
    assert "research_synthesis_ready" in output.getvalue()
    assert synthesizer.calls == 1

    class RaisingSynthesizer:
        def synthesize(self, *args):
            raise AssertionError("read must not synthesize")

    def reading_builder(_workspace: Path, store: FileResearchRunStore):
        return ResearchApplicationService(
            object(), store, result_synthesizer=RaisingSynthesizer()
        )

    shown = StringIO()
    assert (
        run_cli(
            ["research", "--store-root", str(root), "show-synthesis", run_id],
            research_service_builder=reading_builder,
            stdout=shown,
        )
        == 0
    )
    assert "Evidence remains inconclusive." in shown.getvalue()


def test_synthesis_api_lifecycle_is_thin_and_pure_on_read() -> None:
    synthesizer = _Synthesizer()
    service, _ = _analyzed_service(synthesizer)
    client = TestClient(create_app(research_application_service=service))
    generated = client.post("/v1/research-runs/run/synthesis")
    assert generated.status_code == 200
    assert generated.json()["research_run"]["status"] == "research_synthesis_ready"
    assert synthesizer.calls == 1
    shown = client.get("/v1/research-runs/run/synthesis")
    assert shown.status_code == 200
    assert shown.json()["synthesis_summary"] == "Evidence remains inconclusive."
    assert synthesizer.calls == 1
    assert client.post("/v1/research-runs/missing/synthesis").status_code == 404
    assert client.post("/v1/research-runs/run/synthesis").status_code == 409


def test_synthesis_api_maps_provider_failure_to_503() -> None:
    class FailingSynthesizer:
        def synthesize(self, *args):
            raise RuntimeError("unavailable")

    service, _ = _analyzed_service(FailingSynthesizer())
    client = TestClient(create_app(research_application_service=service))
    assert client.post("/v1/research-runs/run/synthesis").status_code == 503


def test_synthesis_round_trip_survives_fresh_file_store(tmp_path: Path) -> None:
    synthesizer = _Synthesizer()
    _, source_store = _analyzed_service(synthesizer)
    run = source_store.get("run")
    assert run is not None
    run_id = "00000000-0000-4000-8000-000000000032"
    root = tmp_path / "runs"
    store = FileResearchRunStore(root)
    store.create(run_id, run)
    written = ResearchApplicationService(
        object(), store, result_synthesizer=synthesizer
    ).generate_synthesis(run_id)
    restored = FileResearchRunStore(root).get(run_id)
    assert restored == written.research_run
    assert restored is not None and restored.result_synthesis is not None


def test_legacy_snapshots_without_synthesis_field_load_without_rewrite(
    tmp_path: Path,
) -> None:
    """Raw historical JSON proves omitted 3C fields remain backward compatible."""
    _, source_store = _analyzed_service()
    analyzed = source_store.get("run")
    assert analyzed is not None
    base = analyzed.model_dump(mode="json")
    cases = (
        (
            "00000000-0000-4000-8000-000000000041",
            "awaiting_direction_selection",
            (
                "plan_revision_state",
                "implementation_plan",
                "implementation_package",
                "result_submission",
                "result_analysis",
            ),
        ),
        (
            "00000000-0000-4000-8000-000000000042",
            "research_plan_approved",
            (
                "implementation_plan",
                "implementation_package",
                "result_submission",
                "result_analysis",
            ),
        ),
        (
            "00000000-0000-4000-8000-000000000043",
            "implementation_package_ready",
            ("result_submission", "result_analysis"),
        ),
        ("00000000-0000-4000-8000-000000000044", "research_results_analyzed", ()),
    )
    root = tmp_path / "runs"
    root.mkdir()
    for run_id, status, omitted in cases:
        payload = dict(base)
        payload["status"] = status
        if status == "awaiting_direction_selection":
            payload["selected_direction_id"] = None
        for key in (*omitted, "result_synthesis"):
            payload.pop(key, None)
        path = root / f"{run_id}.json"
        path.write_text(
            json.dumps({"research_run_id": run_id, "research_run": payload}),
            encoding="utf-8",
        )
        before = path.read_bytes()
        loaded = FileResearchRunStore(root).get(run_id)
        assert loaded is not None
        assert loaded.result_synthesis is None
        assert path.read_bytes() == before
