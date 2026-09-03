"""Opt-in isolated production E2E for analysis of user-supplied results."""

import os

import pytest
from test_research_result_cli import _ready_run

from ai_agent_project.agent.research import (
    ResearchBaselineObservation,
    ResearchMeasurementStatus,
    ResearchMetricObservation,
    ResearchResultSubmission,
    ResearchStatus,
    ResearchTaskExecutionStatus,
    ResearchTaskResult,
)
from ai_agent_project.agent.research_application import (
    InMemoryResearchRunStore,
    ResearchApplicationService,
)
from ai_agent_project.llm.providers.openai_research_result_analyzer import (
    OpenAIResearchResultAnalyzer,
)


@pytest.mark.skipif(
    os.getenv("RUN_OPENAI_E2E") != "1", reason="requires explicit OpenAI E2E opt-in"
)
def test_production_result_analysis_preserves_user_empirical_data() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY is not configured")
    store = InMemoryResearchRunStore()
    original = _ready_run()
    store.create("run", original)
    service = ResearchApplicationService(
        object(),
        store,
        result_analyzer=OpenAIResearchResultAnalyzer(request_timeout_seconds=90),
    )
    service.prepare_result_submission("run")
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
                task_id="T2", execution_status=ResearchTaskExecutionStatus.NOT_EXECUTED
            ),
        ),
        metric_observations=(
            ResearchMetricObservation(
                metric_id="M", value=0.9123, status=ResearchMeasurementStatus.MEASURED
            ),
            ResearchMetricObservation(
                metric_id="M2", status=ResearchMeasurementStatus.NOT_MEASURED
            ),
        ),
        baseline_observations=(
            ResearchBaselineObservation(
                name="baseline",
                metrics=(
                    ResearchMetricObservation(
                        metric_id="M",
                        value=0.8,
                        status=ResearchMeasurementStatus.MEASURED,
                    ),
                ),
            ),
        ),
        user_observations=("T2 was not executed.",),
        missing_items=("M2",),
    )
    service.submit_results("run", submission)
    analyzed = service.analyze_results("run").research_run
    assert analyzed.status is ResearchStatus.RESEARCH_RESULTS_ANALYZED
    assert analyzed.result_submission == submission
    assert analyzed.result_submission.metric_observations[0].value == 0.9123
    assert (
        analyzed.result_submission.metric_observations[1].status
        is ResearchMeasurementStatus.NOT_MEASURED
    )
    assert (
        analyzed.result_submission.task_results[1].execution_status
        is ResearchTaskExecutionStatus.NOT_EXECUTED
    )
    assert analyzed.selected_direction_id == original.selected_direction_id
    assert analyzed.plan_revision_state == original.plan_revision_state
    assert analyzed.implementation_plan == original.implementation_plan
    assert analyzed.result_analysis is not None
    assert (
        analyzed.result_analysis.missing_evidence
        or analyzed.result_analysis.limitations
    )
