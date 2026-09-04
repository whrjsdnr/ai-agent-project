"""Offline lifecycle and traceability coverage for 3C-1 result synthesis."""

import pytest
from test_research_result_cli import _ready_run

from ai_agent_project.agent.research import (
    ResearchFinding,
    ResearchMeasurementStatus,
    ResearchMetricAssessmentPayload,
    ResearchMetricObservation,
    ResearchResultAnalysisPayload,
    ResearchResultSubmission,
    ResearchSynthesisClaim,
    ResearchSynthesisPayload,
    ResearchTaskExecutionStatus,
    ResearchTaskResult,
)
from ai_agent_project.agent.research_application import (
    InMemoryResearchRunStore,
    InvalidResearchStateError,
    ResearchApplicationService,
    ResearchRunError,
)


def _analyzed_service(
    synthesizer: object | None = None,
) -> tuple[ResearchApplicationService, InMemoryResearchRunStore]:
    class Analyzer:
        def analyze(self, *args):
            return ResearchResultAnalysisPayload(
                metric_assessments=(
                    ResearchMetricAssessmentPayload(
                        metric_id="M",
                        assessment="inconclusive",
                        rationale="No threshold",
                        evidence_refs=("metric:M",),
                    ),
                ),
                findings=(
                    ResearchFinding(
                        finding_id="F1",
                        statement="M was supplied.",
                        evidence_refs=("metric:M",),
                    ),
                ),
                missing_evidence=("M2 missing",),
                limitations=("No threshold",),
            )

    store = InMemoryResearchRunStore()
    store.create("run", _ready_run())
    service = ResearchApplicationService(
        object(), store, result_analyzer=Analyzer(), result_synthesizer=synthesizer
    )
    service.prepare_result_submission("run")
    service.submit_results(
        "run",
        ResearchResultSubmission(
            research_run_id="run",
            approved_plan_version=1,
            implementation_plan_version=1,
            metric_observations=(
                ResearchMetricObservation(
                    metric_id="M",
                    value=0.9123,
                    status=ResearchMeasurementStatus.MEASURED,
                ),
            ),
            task_results=(
                ResearchTaskResult(
                    task_id="T",
                    objective_ids=("O",),
                    metric_ids=("M",),
                    execution_status=ResearchTaskExecutionStatus.EXECUTED,
                ),
            ),
        ),
    )
    service.analyze_results("run")
    return service, store


def test_synthesis_requires_analyzed_results_and_preserves_authority() -> None:
    calls: list[str] = []

    class Synthesizer:
        def synthesize(self, *args):
            calls.append("synthesize")
            return ResearchSynthesisPayload(
                synthesis_summary="Inconclusive.",
                inconclusive_findings=(
                    ResearchSynthesisClaim(
                        claim_id="C",
                        statement="M was observed without a threshold.",
                        support_status="inconclusive",
                        metric_ids=("M",),
                        evidence_refs=(),
                        analysis_finding_ids=(),
                    ),
                ),
                limitations=("No threshold",),
                missing_evidence=("M2 not measured",),
            )

    service, store = _analyzed_service(Synthesizer())
    before = store.get("run")
    generated = service.generate_synthesis("run")
    assert generated.research_run.result_synthesis is not None
    assert generated.research_run.selected_direction_id == before.selected_direction_id
    assert generated.research_run.result_submission == before.result_submission
    assert generated.research_run.result_analysis == before.result_analysis
    assert calls == ["synthesize"]
    assert service.get_synthesis("run") == generated.research_run.result_synthesis
    assert calls == ["synthesize"]
    with pytest.raises(InvalidResearchStateError):
        service.generate_synthesis("run")


@pytest.mark.parametrize(
    ("field", "value", "diagnostic"),
    (
        ("objective_ids", ("O999",), "unknown objective IDs: O999"),
        ("task_ids", ("T999",), "unknown task IDs: T999"),
        ("metric_ids", ("M999",), "unknown metric IDs: M999"),
        (
            "analysis_finding_ids",
            ("F999",),
            "unknown analysis finding IDs: F999",
        ),
        ("evidence_refs", ("metric:unknown",), "unknown evidence: metric:unknown"),
    ),
)
def test_synthesis_rejects_unknown_authoritative_reference(
    field: str, value: tuple[str, ...], diagnostic: str
) -> None:
    class Synthesizer:
        def synthesize(self, *args):
            references = {field: value}
            return ResearchSynthesisPayload(
                synthesis_summary="x",
                major_findings=(
                    ResearchSynthesisClaim(
                        claim_id="C",
                        statement="x",
                        support_status="supported",
                        **references,
                    ),
                ),
            )

    service, _ = _analyzed_service(Synthesizer())
    with pytest.raises(ResearchRunError, match=diagnostic):
        service.generate_synthesis("run")


def test_synthesis_failure_does_not_persist_partial_state() -> None:
    class FailingSynthesizer:
        def synthesize(self, *args):
            raise RuntimeError("provider unavailable")

    service, store = _analyzed_service(FailingSynthesizer())
    with pytest.raises(ResearchRunError, match="generation failed"):
        service.generate_synthesis("run")
    run = store.get("run")
    assert run is not None
    assert run.status.value == "research_results_analyzed"
    assert run.result_synthesis is None


@pytest.mark.parametrize(
    "reference",
    ("task:T", "metric:M", "finding:F1"),
)
def test_synthesis_accepts_only_existing_closed_evidence_references(
    reference: str,
) -> None:
    class Synthesizer:
        def synthesize(self, *args):
            return ResearchSynthesisPayload(
                synthesis_summary="x",
                objective_conclusions=(
                    {
                        "objective_id": "O",
                        "conclusion": "Inconclusive.",
                        "assessment": "inconclusive",
                        "evidence_refs": (reference,),
                    },
                ),
                inconclusive_findings=(
                    ResearchSynthesisClaim(
                        claim_id="C",
                        statement="x",
                        support_status="inconclusive",
                        evidence_refs=(reference,),
                    ),
                ),
            )

    service, _ = _analyzed_service(Synthesizer())
    assert service.generate_synthesis("run").research_run.result_synthesis is not None


def test_synthesis_accepts_partial_valid_typed_traceability() -> None:
    class Synthesizer:
        def synthesize(self, *args):
            return ResearchSynthesisPayload(
                synthesis_summary="x",
                major_findings=(
                    ResearchSynthesisClaim(
                        claim_id="C",
                        statement="x",
                        support_status="inconclusive",
                        objective_ids=("O",),
                        task_ids=("T",),
                        metric_ids=("M",),
                        analysis_finding_ids=("F1",),
                    ),
                ),
            )

    service, _ = _analyzed_service(Synthesizer())
    assert service.generate_synthesis("run").research_run.result_synthesis is not None


@pytest.mark.parametrize(
    "reference",
    (
        "task:HALLUCINATED",
        "metric:HALLUCINATED",
        "finding:HALLUCINATED",
        "source:HALLUCINATED",
    ),
)
def test_synthesis_rejects_unknown_or_arbitrary_evidence_namespaces(
    reference: str,
) -> None:
    class Synthesizer:
        def synthesize(self, *args):
            return ResearchSynthesisPayload(
                synthesis_summary="x",
                objective_conclusions=(
                    {
                        "objective_id": "O",
                        "conclusion": "x",
                        "assessment": "inconclusive",
                        "evidence_refs": (reference,),
                    },
                ),
            )

    service, _ = _analyzed_service(Synthesizer())
    with pytest.raises(ResearchRunError, match=reference):
        service.generate_synthesis("run")
