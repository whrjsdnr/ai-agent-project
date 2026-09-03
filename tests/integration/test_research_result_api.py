"""HTTP lifecycle tests for authoritative user research results."""

from fastapi.testclient import TestClient
from test_research_result_cli import _ready_run

from ai_agent_project.agent.research import ResearchResultAnalysisPayload
from ai_agent_project.agent.research_application import (
    InMemoryResearchRunStore,
    ResearchApplicationService,
)
from ai_agent_project.api.app import create_app


def test_result_api_lifecycle_and_conservative_errors() -> None:
    calls: list[str] = []

    class Analyzer:
        def analyze(self, *args):
            calls.append("analyze")
            return ResearchResultAnalysisPayload(
                findings=(), missing_evidence=("missing evidence",)
            )

    store = InMemoryResearchRunStore()
    store.create("run", _ready_run())
    service = ResearchApplicationService(object(), store, result_analyzer=Analyzer())
    client = TestClient(create_app(research_application_service=service))
    guide = client.get("/v1/research-runs/run/result-guide")
    assert guide.status_code == 200
    assert "not executed" in guide.json()["result_guide"]
    assert "not measured" in guide.json()["result_guide"]
    assert calls == []
    assert client.post("/v1/research-runs/run/analysis").status_code == 409
    payload = {
        "research_run_id": "run",
        "approved_plan_version": 1,
        "implementation_plan_version": 1,
        "task_results": [
            {
                "task_id": "T",
                "objective_ids": ["O"],
                "metric_ids": ["M"],
                "execution_status": "executed",
            }
        ],
        "metric_observations": [{"metric_id": "M", "value": 0.5, "status": "measured"}],
    }
    assert client.post("/v1/research-runs/run/results", json=payload).status_code == 200
    results = client.get("/v1/research-runs/run/results")
    assert (
        results.status_code == 200
        and results.json()["metric_observations"][0]["value"] == 0.5
    )
    assert calls == []
    assert client.post("/v1/research-runs/run/analysis").status_code == 200
    assert calls == ["analyze"]
    assert client.get("/v1/research-runs/run/analysis").status_code == 200
    assert calls == ["analyze"]
    assert client.get("/v1/research-runs/missing/result-guide").status_code == 404
    assert client.post("/v1/research-runs/run/results", json={}).status_code == 422
