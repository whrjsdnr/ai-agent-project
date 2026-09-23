"""Opt-in isolated production E2E for 3C-1 result synthesis."""

import os

import pytest
from test_research_result_cli import _ready_run

from ai_agent_project.agent.research import (
    ResearchFinding,
    ResearchMeasurementStatus,
    ResearchMetricAssessment,
    ResearchMetricObservation,
    ResearchResultAnalysis,
    ResearchResultSubmission,
    ResearchStatus,
    ResearchTaskExecutionStatus,
    ResearchTaskResult,
)
from ai_agent_project.agent.research_application import (
    InMemoryResearchRunStore,
    ResearchApplicationService,
)
from ai_agent_project.llm.providers.openai_research_result_synthesizer import (
    OpenAIResearchResultSynthesizer,
)


def test_research_synthesis_production_e2e() -> None:
    if os.getenv("RUN_OPENAI_E2E") != "1":
        pytest.skip("Set RUN_OPENAI_E2E=1 to run the OpenAI synthesis E2E")
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY is required for the OpenAI synthesis E2E")

    # Build deterministic authoritative state directly: no discovery, planning,
    # implementation generation, execution, or result-analysis provider call.
    source = _ready_run().model_copy(
        update={
            "status": ResearchStatus.RESEARCH_RESULTS_ANALYZED,
            "result_submission": ResearchResultSubmission(
                research_run_id="run",
                approved_plan_version=1,
                implementation_plan_version=1,
                task_results=(
                    ResearchTaskResult(
                        task_id="T",
                        objective_ids=("O",),
                        metric_ids=("M",),
                        execution_status=ResearchTaskExecutionStatus.EXECUTED,
                    ),
                    ResearchTaskResult(
                        task_id="T2",
                        execution_status=ResearchTaskExecutionStatus.NOT_EXECUTED,
                    ),
                ),
                metric_observations=(
                    ResearchMetricObservation(
                        metric_id="M",
                        value=0.9123,
                        status=ResearchMeasurementStatus.MEASURED,
                    ),
                    ResearchMetricObservation(
                        metric_id="M2",
                        status=ResearchMeasurementStatus.NOT_MEASURED,
                    ),
                ),
                user_observations=("Only one measured metric was supplied.",),
                missing_items=("M2 was not measured.",),
            ),
            "result_analysis": ResearchResultAnalysis(
                metric_assessments=(
                    ResearchMetricAssessment(
                        metric_id="M",
                        observed_value=0.9123,
                        observation_status=ResearchMeasurementStatus.MEASURED,
                        assessment="inconclusive",
                        rationale="No success threshold was supplied.",
                        evidence_refs=("metric:M",),
                    ),
                    ResearchMetricAssessment(
                        metric_id="M2",
                        observation_status=ResearchMeasurementStatus.NOT_MEASURED,
                        assessment="not_measured",
                        rationale="It was not measured.",
                    ),
                ),
                findings=(
                    ResearchFinding(
                        finding_id="F1",
                        statement="M was supplied as 0.9123.",
                        evidence_refs=("metric:M",),
                    ),
                ),
                limitations=("No success threshold was supplied.",),
                missing_evidence=("M2 was not measured.",),
            ),
        }
    )
    assert source.status is ResearchStatus.RESEARCH_RESULTS_ANALYZED
    before = source

    store = InMemoryResearchRunStore()
    store.create("run", source)
    service = ResearchApplicationService(
        object(),
        store,
        result_synthesizer=OpenAIResearchResultSynthesizer(
            request_timeout_seconds=90.0
        ),
    )
    generated = service.generate_synthesis("run").research_run

    assert generated.status is ResearchStatus.RESEARCH_SYNTHESIS_READY
    assert generated.selected_direction_id == before.selected_direction_id
    assert generated.plan_revision_state == before.plan_revision_state
    assert generated.implementation_plan == before.implementation_plan
    assert generated.implementation_package == before.implementation_package
    assert generated.result_submission == before.result_submission
    assert generated.result_analysis == before.result_analysis
    assert generated.result_submission is not None
    observations = {
        item.metric_id: item for item in generated.result_submission.metric_observations
    }
    assert observations["M"].value == 0.9123
    assert observations["M2"].status is ResearchMeasurementStatus.NOT_MEASURED
    task_results = {
        item.task_id: item for item in generated.result_submission.task_results
    }
    assert (
        task_results["T2"].execution_status is ResearchTaskExecutionStatus.NOT_EXECUTED
    )
    assert generated.result_synthesis is not None
    synthesis = generated.result_synthesis
    assert synthesis.missing_evidence or synthesis.limitations
    assert synthesis.synthesis_summary.strip()
    for claim in (
        *synthesis.major_findings,
        *synthesis.inconclusive_findings,
        *synthesis.negative_findings,
        *synthesis.research_contributions,
    ):
        assert set(claim.objective_ids) <= {"O"}
        assert set(claim.task_ids) <= {"T", "T2"}
        assert set(claim.metric_ids) <= {"M", "M2"}
        assert set(claim.evidence_refs) <= {
            "task:T",
            "task:T2",
            "metric:M",
            "metric:M2",
            "finding:F1",
        }
        assert not (claim.metric_ids == ("M2",) and claim.support_status == "supported")
        assert not (claim.task_ids == ("T2",) and claim.support_status == "supported")
