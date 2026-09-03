"""Offline strict-output tests for empirical-result interpretation only."""

import json
from types import SimpleNamespace
from typing import Any

import pytest

from ai_agent_project.agent.research import (
    ResearchImplementationPlan,
    ResearchImplementationTask,
    ResearchMeasurementStatus,
    ResearchMetric,
    ResearchMetricObservation,
    ResearchObjective,
    ResearchPlan,
    ResearchResultSubmission,
)
from ai_agent_project.llm.providers.openai_research_result_analyzer import (
    OpenAIResearchResultAnalyzer,
    ResearchResultAnalysisError,
)


class _Responses:
    def __init__(self, result: object | Exception) -> None:
        self.result = result
        self.requests: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> object:
        self.requests.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class _Client:
    def __init__(self, result: object | Exception) -> None:
        self.responses = _Responses(result)


def _context():
    plan = ResearchPlan(
        id="P",
        selected_direction_id="RD",
        title="P",
        research_question="Q",
        objectives=(ResearchObjective(id="O1", description="O", direction_id="RD"),),
        metrics=(
            ResearchMetric(id="M1", name="M1", description="D", measurement_method="x"),
            ResearchMetric(id="M2", name="M2", description="D", measurement_method="x"),
        ),
    )
    implementation = ResearchImplementationPlan(
        selected_direction_id="RD",
        approved_plan_version=1,
        package_summary="x",
        tasks=(
            ResearchImplementationTask(task_id="T1", title="T", description="D"),
            ResearchImplementationTask(task_id="T2", title="T", description="D"),
        ),
    )
    submission = ResearchResultSubmission(
        research_run_id="run",
        approved_plan_version=1,
        implementation_plan_version=1,
        metric_observations=(
            ResearchMetricObservation(
                metric_id="M1", value=0.75, status=ResearchMeasurementStatus.MEASURED
            ),
            ResearchMetricObservation(
                metric_id="M2", status=ResearchMeasurementStatus.NOT_MEASURED
            ),
        ),
    )
    return plan, implementation, submission


def test_analyzer_returns_interpretation_only_strict_payload() -> None:
    plan, implementation, submission = _context()
    client = _Client(
        SimpleNamespace(
            output_text=json.dumps(
                {
                    "metric_assessments": [
                        {
                            "metric_id": "M1",
                            "assessment": "met",
                            "rationale": "Observed",
                            "evidence_refs": ["metric:M1"],
                        }
                    ],
                    "success_criterion_assessments": [],
                    "objective_assessments": [],
                    "findings": [],
                    "anomalies": [],
                    "limitations": [],
                    "missing_evidence": [],
                    "recommended_next_steps": [],
                }
            )
        )
    )
    analyzer = OpenAIResearchResultAnalyzer(client=client, model="test")
    payload = analyzer.analyze(plan, implementation, submission)
    assert payload.metric_assessments[0].metric_id == "M1"
    schema = client.responses.requests[0]["text"]["format"]["schema"]
    assert "user_result_submission" not in schema["properties"]
    assert (
        "value" not in schema["$defs"]["ResearchMetricAssessmentPayload"]["properties"]
    )


@pytest.mark.parametrize(
    "result",
    [SimpleNamespace(output_text="not json"), SimpleNamespace(output_text=None)],
)
def test_analyzer_rejects_malformed_output(result: object) -> None:
    plan, implementation, submission = _context()
    with pytest.raises(ResearchResultAnalysisError):
        OpenAIResearchResultAnalyzer(client=_Client(result), model="test").analyze(
            plan, implementation, submission
        )


def test_analyzer_propagates_provider_failure_and_requires_positive_timeout() -> None:
    plan, implementation, submission = _context()
    with pytest.raises(RuntimeError, match="down"):
        OpenAIResearchResultAnalyzer(
            client=_Client(RuntimeError("down")), model="test"
        ).analyze(plan, implementation, submission)
    with pytest.raises(ValueError, match="positive"):
        OpenAIResearchResultAnalyzer(
            client=_Client(SimpleNamespace()), request_timeout_seconds=0
        )
