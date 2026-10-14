"""Opt-in isolated production E2E for 3C-2 structured paper materials."""

import os

import pytest
from test_research_result_cli import _ready_run

from ai_agent_project.agent.research import (
    ResearchClaimSupportStatus,
    ResearchFinding,
    ResearchMeasurementStatus,
    ResearchMetricAssessment,
    ResearchMetricObservation,
    ResearchResultAnalysis,
    ResearchResultSubmission,
    ResearchResultSynthesis,
    ResearchStatus,
    ResearchSynthesisClaim,
    ResearchTaskExecutionStatus,
    ResearchTaskResult,
)
from ai_agent_project.agent.research_application import ResearchApplicationService
from ai_agent_project.agent.research_file_store import FileResearchRunStore
from ai_agent_project.llm.providers.openai_research_paper_materials import (
    OpenAIResearchPaperMaterialsGenerator,
)


class _CountingPaperMaterialsGenerator(OpenAIResearchPaperMaterialsGenerator):
    def __init__(self) -> None:
        super().__init__(request_timeout_seconds=90.0)
        self.calls = 0

    def generate(self, *args: object):
        self.calls += 1
        return super().generate(*args)


def _research_synthesis_ready_run():
    """Build final pre-3C-2 state without invoking any prior provider."""
    submission = ResearchResultSubmission(
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
        user_observations=("T2 was not executed.",),
        missing_items=("M2 was not measured.",),
    )
    analysis = ResearchResultAnalysis(
        metric_assessments=(
            ResearchMetricAssessment(
                metric_id="M",
                observed_value=0.9123,
                observation_status=ResearchMeasurementStatus.MEASURED,
                assessment="inconclusive",
                rationale="No success threshold or comparison was supplied.",
                evidence_refs=("metric:M",),
            ),
            ResearchMetricAssessment(
                metric_id="M2",
                observation_status=ResearchMeasurementStatus.NOT_MEASURED,
                assessment="not_measured",
                rationale="The metric was not measured.",
            ),
        ),
        findings=(
            ResearchFinding(
                finding_id="F1",
                statement="M was supplied as 0.9123 without a success threshold.",
                evidence_refs=("metric:M",),
            ),
        ),
        limitations=("No success threshold or comparison was supplied.",),
        missing_evidence=("M2 was not measured.",),
    )
    synthesis = ResearchResultSynthesis(
        synthesis_summary="The supplied evidence is inconclusive.",
        inconclusive_findings=(
            ResearchSynthesisClaim(
                claim_id="SC1",
                statement="M was measured at 0.9123, but success is not established.",
                support_status=ResearchClaimSupportStatus.INCONCLUSIVE,
                objective_ids=("O",),
                task_ids=("T",),
                metric_ids=("M",),
                evidence_refs=("metric:M", "finding:F1"),
                analysis_finding_ids=("F1",),
            ),
        ),
        limitations=("No success threshold or comparison was supplied.",),
        missing_evidence=("M2 was not measured and T2 was not executed.",),
        selected_direction_id="RD",
        approved_plan_version=1,
        implementation_plan_version=1,
    )
    return _ready_run().model_copy(
        update={
            "status": ResearchStatus.RESEARCH_SYNTHESIS_READY,
            "result_submission": submission,
            "result_analysis": analysis,
            "result_synthesis": synthesis,
        }
    )


def test_research_paper_materials_production_e2e(tmp_path) -> None:
    if os.getenv("RUN_OPENAI_E2E") != "1":
        pytest.skip("Set RUN_OPENAI_E2E=1 to run the OpenAI paper-materials E2E")
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY is required for the OpenAI paper-materials E2E")

    run_id = "00000000-0000-4000-8000-000000000081"
    store = FileResearchRunStore(tmp_path / "runs")
    before = _research_synthesis_ready_run()
    assert before.status is ResearchStatus.RESEARCH_SYNTHESIS_READY
    store.create(run_id, before)
    generator = _CountingPaperMaterialsGenerator()
    generated = (
        ResearchApplicationService(object(), store, paper_materials_generator=generator)
        .generate_paper_materials(run_id)
        .research_run
    )

    assert generator.calls == 1
    assert generated.status is ResearchStatus.PAPER_MATERIALS_READY
    assert generated.paper_materials is not None
    assert generated.selected_direction_id == before.selected_direction_id
    assert generated.plan_revision_state == before.plan_revision_state
    assert generated.implementation_plan == before.implementation_plan
    assert generated.implementation_package == before.implementation_package
    assert generated.result_submission == before.result_submission
    assert generated.result_analysis == before.result_analysis
    assert generated.result_synthesis == before.result_synthesis

    assert generated.result_submission is not None
    observations = {
        item.metric_id: item for item in generated.result_submission.metric_observations
    }
    assert observations["M"].value == 0.9123
    assert observations["M"].status is ResearchMeasurementStatus.MEASURED
    assert observations["M2"].value is None
    assert observations["M2"].status is ResearchMeasurementStatus.NOT_MEASURED

    for key_result in generated.paper_materials.key_results:
        assert key_result.metric_id in {"M", "M2"}
        if key_result.metric_id == "M":
            assert key_result.value == 0.9123
            assert key_result.observation_status is ResearchMeasurementStatus.MEASURED
        else:
            assert key_result.value is None
            assert (
                key_result.observation_status is ResearchMeasurementStatus.NOT_MEASURED
            )
    assert generated.result_submission.task_results[1].execution_status is (
        ResearchTaskExecutionStatus.NOT_EXECUTED
    )

    materials = generated.paper_materials
    claims = (
        *materials.contribution_candidates,
        *materials.usable_claims,
        *materials.prohibited_claims,
    )
    allowed_support = {
        ResearchClaimSupportStatus.INCONCLUSIVE: {
            ResearchClaimSupportStatus.INCONCLUSIVE,
            ResearchClaimSupportStatus.UNSUPPORTED,
        }
    }
    for claim in claims:
        assert set(claim.objective_ids) <= {"O"}
        assert set(claim.task_ids) <= {"T", "T2"}
        assert set(claim.metric_ids) <= {"M", "M2"}
        assert set(claim.analysis_finding_ids) <= {"F1"}
        assert set(claim.synthesis_claim_ids) <= {"SC1"}
        assert set(claim.evidence_refs) <= {
            "task:T",
            "task:T2",
            "metric:M",
            "metric:M2",
            "finding:F1",
        }
        if claim.synthesis_claim_ids:
            assert (
                claim.support_status
                in allowed_support[ResearchClaimSupportStatus.INCONCLUSIVE]
            )
    assert set(materials.citation_source_ids) <= {"S"}
    assert set(materials.key_metric_ids) <= {"M", "M2"}
    for suggestion in (*materials.table_suggestions, *materials.figure_suggestions):
        assert set(suggestion.metric_ids) <= {"M", "M2"}
        assert set(suggestion.paper_claim_ids) <= {claim.claim_id for claim in claims}
    for section in materials.section_materials:
        assert set(section.included_source_ids) <= {"S"}
        assert set(section.included_metric_ids) <= {"M", "M2"}
        assert set(section.included_claim_ids) <= {claim.claim_id for claim in claims}

    forbidden = {
        "abstract",
        "introduction",
        "related_work_prose",
        "methodology_prose",
        "results_prose",
        "discussion",
        "conclusion",
        "manuscript",
        "draft",
        "body_text",
        "paragraph",
        "paragraphs",
        "doi",
        "authors",
        "year",
        "url",
    }
    assert not (forbidden & set(type(materials).model_fields))

    reloaded = FileResearchRunStore(tmp_path / "runs").get(run_id)
    assert reloaded is not None
    assert reloaded.status is ResearchStatus.PAPER_MATERIALS_READY
    assert reloaded.paper_materials == materials
    assert reloaded.result_submission == before.result_submission
    assert reloaded.result_submission is not None
    reloaded_observations = {
        item.metric_id: item for item in reloaded.result_submission.metric_observations
    }
    assert reloaded_observations["M"].value == 0.9123
    assert reloaded_observations["M"].status is ResearchMeasurementStatus.MEASURED
    assert reloaded_observations["M2"].value is None
    assert reloaded_observations["M2"].status is ResearchMeasurementStatus.NOT_MEASURED
    for key_result in reloaded.paper_materials.key_results:
        assert key_result.metric_id in {"M", "M2"}
        if key_result.metric_id == "M":
            assert key_result.value == 0.9123
            assert key_result.observation_status is ResearchMeasurementStatus.MEASURED
        else:
            assert key_result.value is None
            assert (
                key_result.observation_status is ResearchMeasurementStatus.NOT_MEASURED
            )
    assert reloaded.result_submission.task_results[1].execution_status is (
        ResearchTaskExecutionStatus.NOT_EXECUTED
    )
