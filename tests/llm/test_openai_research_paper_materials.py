"""Isolated strict-output tests for structured paper materials."""

import json
from types import SimpleNamespace
from typing import Any

import pytest

from ai_agent_project.agent.research import (
    ResearchDirection,
    ResearchDiscoveryReport,
    ResearchEvidence,
    ResearchFinding,
    ResearchImplementationPlan,
    ResearchImplementationTask,
    ResearchMeasurementStatus,
    ResearchMetric,
    ResearchMetricObservation,
    ResearchObjective,
    ResearchPaperMaterialsPayload,
    ResearchPlan,
    ResearchQuestion,
    ResearchResultAnalysis,
    ResearchResultSubmission,
    ResearchResultSynthesis,
    ResearchScope,
    ResearchSource,
    ResearchSynthesisClaim,
)
from ai_agent_project.llm.providers.openai_research_paper_materials import (
    OpenAIResearchPaperMaterialsGenerator,
    ResearchPaperMaterialsError,
)
from ai_agent_project.llm.runtime import ProviderRequestError


class _Responses:
    def __init__(self, result: object | Exception):
        self.result, self.requests = result, []

    def create(self, **kwargs: Any):
        self.requests.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class _Client:
    def __init__(self, result: object | Exception):
        self.responses = _Responses(result)


def _context():
    direction = ResearchDirection(
        id="RD",
        title="D",
        research_question="Q",
        target_gap_ids=("G",),
        novelty="N",
        feasibility="F",
    )
    report = ResearchDiscoveryReport(
        questions=(
            ResearchQuestion(
                id="Q", question="Q", rationale="R", source_scope=ResearchScope.EXTERNAL
            ),
        ),
        sources=(
            ResearchSource(
                id="S", title="S", locator="https://example.org", source_type="web"
            ),
        ),
        evidence=(
            ResearchEvidence(
                id="E",
                source_id="S",
                question_id="Q",
                claim="C",
                support_text="T",
                evidence_type="citation",
            ),
        ),
    )
    plan = ResearchPlan(
        id="P",
        selected_direction_id="RD",
        title="P",
        research_question="Q",
        objectives=(ResearchObjective(id="O", description="O", direction_id="RD"),),
        metrics=(
            ResearchMetric(id="M", name="M", description="D", measurement_method="x"),
            ResearchMetric(id="M2", name="M2", description="D", measurement_method="x"),
        ),
    )
    implementation = ResearchImplementationPlan(
        selected_direction_id="RD",
        approved_plan_version=1,
        package_summary="x",
        tasks=(
            ResearchImplementationTask(task_id="T", title="T", description="D"),
            ResearchImplementationTask(task_id="T2", title="T2", description="D"),
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
            ResearchMetricObservation(
                metric_id="M2", status=ResearchMeasurementStatus.NOT_MEASURED
            ),
        ),
    )
    analysis = ResearchResultAnalysis(
        findings=(
            ResearchFinding(
                finding_id="F1", statement="F", evidence_refs=("metric:M",)
            ),
        )
    )
    synthesis = ResearchResultSynthesis(
        synthesis_summary="S",
        inconclusive_findings=(
            ResearchSynthesisClaim(
                claim_id="SC1", statement="S", support_status="inconclusive"
            ),
        ),
        selected_direction_id="RD",
        approved_plan_version=1,
        implementation_plan_version=1,
    )
    return direction, report, plan, implementation, submission, analysis, synthesis


def test_provider_has_closed_vocabularies_and_payload_only_schema():
    response = SimpleNamespace(
        output_text=json.dumps(
            {
                "research_problem": "facts",
                "contribution_candidates": [],
                "usable_claims": [],
                "prohibited_claims": [],
                "related_work_positioning": [],
                "citation_source_ids": [],
                "key_metric_ids": [],
                "table_suggestions": [],
                "figure_suggestions": [],
                "section_materials": [],
                "limitations": [],
                "missing_evidence": [],
                "additional_validation_needed": [],
            }
        )
    )
    client = _Client(response)
    payload = OpenAIResearchPaperMaterialsGenerator(
        client=client, model="test"
    ).generate(*_context())
    assert isinstance(payload, ResearchPaperMaterialsPayload)
    request = client.responses.requests[0]
    prompt = request["instructions"]
    for value in (
        '"source_ids": ["S"]',
        '"objective_ids": ["O"]',
        '"task_ids": ["T", "T2"]',
        '"metric_ids": ["M", "M2"]',
        '"analysis_finding_ids": ["F1"]',
        '"synthesis_claim_ids": ["SC1"]',
        '"metric:M"',
    ):
        assert value in prompt
    assert "raw IDs" in prompt and "Never execute" in prompt
    schema = json.dumps(request["text"]["format"]["schema"])
    for forbidden in (
        '"value"',
        '"baseline"',
        '"unit"',
        '"measurement_status"',
        '"execution_status"',
    ):
        assert forbidden not in schema


@pytest.mark.parametrize(
    "result", [SimpleNamespace(output_text="bad"), SimpleNamespace(output_text=None)]
)
def test_provider_rejects_malformed_output(result):
    with pytest.raises(ResearchPaperMaterialsError):
        OpenAIResearchPaperMaterialsGenerator(
            client=_Client(result), model="test"
        ).generate(*_context())


def test_provider_sanitizes_client_failure_and_validates_timeout():
    with pytest.raises(ProviderRequestError, match="LLM provider request failed"):
        OpenAIResearchPaperMaterialsGenerator(
            client=_Client(RuntimeError()), model="test"
        ).generate(*_context())
    with pytest.raises(ValueError, match="positive"):
        OpenAIResearchPaperMaterialsGenerator(
            client=_Client(SimpleNamespace()), request_timeout_seconds=0
        )
