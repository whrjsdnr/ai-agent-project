"""Offline strict-output tests for evidence-grounded result synthesis."""

import json
from types import SimpleNamespace
from typing import Any

import pytest

from ai_agent_project.agent.research import (
    ResearchFinding,
    ResearchImplementationPlan,
    ResearchImplementationTask,
    ResearchMeasurementStatus,
    ResearchMetric,
    ResearchMetricAssessment,
    ResearchMetricObservation,
    ResearchObjective,
    ResearchPlan,
    ResearchResultAnalysis,
    ResearchResultSubmission,
    ResearchSynthesisPayload,
)
from ai_agent_project.llm.providers.openai_research_result_synthesizer import (
    OpenAIResearchResultSynthesizer,
    ResearchResultSynthesisError,
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
    from ai_agent_project.agent.research import ResearchDirection

    direction = ResearchDirection(
        id="RD",
        title="Direction",
        research_question="Question",
        target_gap_ids=("G",),
        novelty="N",
        feasibility="F",
    )
    plan = ResearchPlan(
        id="P",
        selected_direction_id="RD",
        title="Plan",
        research_question="Question",
        objectives=(
            ResearchObjective(id="O", description="Objective", direction_id="RD"),
        ),
        metrics=(
            ResearchMetric(
                id="M", name="Metric", description="D", measurement_method="x"
            ),
        ),
    )
    implementation = ResearchImplementationPlan(
        selected_direction_id="RD",
        approved_plan_version=1,
        package_summary="x",
        tasks=(
            ResearchImplementationTask(
                task_id="T",
                title="Task",
                description="D",
                objective_ids=("O",),
                metric_ids=("M",),
            ),
        ),
    )
    submission = ResearchResultSubmission(
        research_run_id="run",
        approved_plan_version=1,
        implementation_plan_version=1,
        metric_observations=(
            ResearchMetricObservation(
                metric_id="M", value=0.9123, status=ResearchMeasurementStatus.MEASURED
            ),
        ),
    )
    analysis = ResearchResultAnalysis(
        metric_assessments=(
            ResearchMetricAssessment(
                metric_id="M",
                observed_value=0.9123,
                observation_status=ResearchMeasurementStatus.MEASURED,
                assessment="inconclusive",
                rationale="No threshold",
                evidence_refs=("metric:M",),
            ),
        ),
        missing_evidence=("No threshold",),
        limitations=("One observation",),
        findings=(
            ResearchFinding(
                finding_id="F1", statement="Observed M.", evidence_refs=("metric:M",)
            ),
        ),
    )
    return direction, plan, implementation, submission, analysis


def test_synthesizer_returns_interpretation_only_payload() -> None:
    context = _context()
    client = _Client(
        SimpleNamespace(
            output_text=json.dumps(
                {
                    "synthesis_summary": "The supplied observation is inconclusive.",
                    "objective_conclusions": [],
                    "major_findings": [],
                    "inconclusive_findings": [],
                    "negative_findings": [],
                    "limitations": ["No threshold"],
                    "missing_evidence": ["No threshold"],
                    "research_contributions": [],
                    "threats_to_validity": [],
                    "future_work": [],
                }
            )
        )
    )
    payload = OpenAIResearchResultSynthesizer(client=client, model="test").synthesize(
        *context
    )
    assert isinstance(payload, ResearchSynthesisPayload)
    schema = client.responses.requests[0]["text"]["format"]["schema"]
    properties = schema["properties"]
    assert "selected_direction_id" not in properties
    assert "submission" not in properties
    assert "implementation_plan" not in properties
    instructions = client.responses.requests[0]["instructions"]
    assert '"metric:M"' in instructions
    assert '"finding:F1"' in instructions
    assert '"objective_ids": ["O"]' in instructions
    assert '"task_ids": ["T"]' in instructions
    assert '"metric_ids": ["M"]' in instructions
    assert '"analysis_finding_ids": ["F1"]' in instructions
    assert "raw IDs" in instructions


@pytest.mark.parametrize(
    "result",
    [SimpleNamespace(output_text="not json"), SimpleNamespace(output_text=None)],
)
def test_synthesizer_rejects_malformed_output(result: object) -> None:
    with pytest.raises(ResearchResultSynthesisError):
        OpenAIResearchResultSynthesizer(
            client=_Client(result), model="test"
        ).synthesize(*_context())


def test_synthesizer_propagates_provider_error_and_validates_timeout() -> None:
    with pytest.raises(RuntimeError, match="down"):
        OpenAIResearchResultSynthesizer(
            client=_Client(RuntimeError("down")), model="test"
        ).synthesize(*_context())
    with pytest.raises(ValueError, match="positive"):
        OpenAIResearchResultSynthesizer(
            client=_Client(SimpleNamespace()), request_timeout_seconds=0
        )
