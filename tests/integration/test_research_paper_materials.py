"""Offline lifecycle, traceability, and trusted projection tests for 3C-2."""

import json
from pathlib import Path

import pytest
from test_research_synthesis import _analyzed_service

from ai_agent_project.agent.research import (
    ResearchClaimSupportStatus,
    ResearchMeasurementStatus,
    ResearchPaperClaim,
    ResearchPaperMaterialsPayload,
    ResearchStatus,
    ResearchSynthesisClaim,
    ResearchSynthesisPayload,
    ResearchTaskExecutionStatus,
)
from ai_agent_project.agent.research_application import (
    InvalidResearchStateError,
    ResearchRunError,
)
from ai_agent_project.agent.research_file_store import FileResearchRunStore


class _SynthesisGenerator:
    def synthesize(self, *args):
        return ResearchSynthesisPayload(
            synthesis_summary="Inconclusive.",
            inconclusive_findings=(
                ResearchSynthesisClaim(
                    claim_id="SC1",
                    statement="M has no threshold.",
                    support_status="inconclusive",
                    objective_ids=("O",),
                    task_ids=("T",),
                    metric_ids=("M",),
                    evidence_refs=("metric:M",),
                    analysis_finding_ids=("F1",),
                ),
            ),
            limitations=("No threshold",),
            missing_evidence=("M2 not measured",),
        )


def _ready_service(generator: object | None = None):
    service, store = _analyzed_service(_SynthesisGenerator())
    service.generate_synthesis("run")
    service._paper_materials_generator = generator
    return service, store


def _payload(**update):
    value = ResearchPaperMaterialsPayload(
        research_problem="Problem facts",
        usable_claims=(
            ResearchPaperClaim(
                claim_id="PC1",
                kind="usable",
                statement="Observed metric is reportable but inconclusive.",
                support_status="inconclusive",
                synthesis_claim_ids=("SC1",),
                objective_ids=("O",),
                task_ids=("T",),
                metric_ids=("M",),
                analysis_finding_ids=("F1",),
                evidence_refs=("metric:M",),
            ),
        ),
        citation_source_ids=("S",),
        key_metric_ids=("M", "M2"),
    )
    return value.model_copy(update=update)


def test_paper_materials_lifecycle_projection_and_provider_free_read() -> None:
    calls = []

    class Generator:
        def generate(self, *args):
            calls.append(1)
            return _payload()

    service, store = _ready_service(Generator())
    before = store.get("run")
    generated = service.generate_paper_materials("run").research_run
    assert generated.status.value == "paper_materials_ready"
    assert generated.paper_materials is not None
    results = {item.metric_id: item for item in generated.paper_materials.key_results}
    assert results["M"].value == 0.9123
    assert results["M"].observation_status is ResearchMeasurementStatus.MEASURED
    assert results["M2"].value is None
    assert results["M2"].observation_status is ResearchMeasurementStatus.NOT_MEASURED
    assert (
        generated.result_submission.task_results[1].execution_status
        is ResearchTaskExecutionStatus.NOT_EXECUTED
    )
    assert generated.result_submission == before.result_submission
    assert generated.result_analysis == before.result_analysis
    assert service.get_paper_materials("run") == generated.paper_materials
    assert calls == [1]
    with pytest.raises(InvalidResearchStateError):
        service.generate_paper_materials("run")


@pytest.mark.parametrize(
    "field,value,diagnostic",
    [
        ("citation_source_ids", ("S999",), "unknown source IDs: S999"),
        ("key_metric_ids", ("M999",), "unknown metric IDs: M999"),
    ],
)
def test_paper_materials_closed_top_level_refs(field, value, diagnostic) -> None:
    class Generator:
        def generate(self, *args):
            return _payload(**{field: value})

    service, store = _ready_service(Generator())
    with pytest.raises(ResearchRunError, match=diagnostic):
        service.generate_paper_materials("run")
    assert store.get("run").status.value == "research_synthesis_ready"


@pytest.mark.parametrize(
    "field,value,diagnostic",
    [
        ("objective_ids", ("O999",), "unknown objective IDs: O999"),
        ("task_ids", ("T999",), "unknown task IDs: T999"),
        ("metric_ids", ("M999",), "unknown metric IDs: M999"),
        ("analysis_finding_ids", ("F999",), "unknown analysis finding IDs: F999"),
        ("synthesis_claim_ids", ("SC999",), "unknown synthesis claim IDs: SC999"),
        ("evidence_refs", ("metric:M999",), "unknown evidence refs: metric:M999"),
    ],
)
def test_paper_claim_closed_refs_and_support_escalation(
    field, value, diagnostic
) -> None:
    claim = _payload().usable_claims[0].model_copy(update={field: value})

    class Generator:
        def generate(self, *args):
            return _payload(usable_claims=(claim,))

    service, _ = _ready_service(Generator())
    with pytest.raises(ResearchRunError, match=diagnostic):
        service.generate_paper_materials("run")


def test_paper_materials_rejects_support_escalation_and_provider_failure() -> None:
    escalated = (
        _payload()
        .usable_claims[0]
        .model_copy(update={"support_status": ResearchClaimSupportStatus.SUPPORTED})
    )

    class Escalating:
        def generate(self, *args):
            return _payload(usable_claims=(escalated,))

    service, store = _ready_service(Escalating())
    with pytest.raises(ResearchRunError, match="cannot strengthen"):
        service.generate_paper_materials("run")
    assert store.get("run").status.value == "research_synthesis_ready"


def test_paper_material_schema_rejects_duplicate_ids_and_has_no_manuscript_fields() -> (
    None
):
    duplicate = _payload().usable_claims[0].model_copy(update={"claim_id": "PC1"})
    with pytest.raises(ValueError, match="Duplicate research paper claim"):
        ResearchPaperMaterialsPayload.model_validate(
            {
                **_payload().model_dump(),
                "usable_claims": [
                    _payload().usable_claims[0].model_dump(),
                    duplicate.model_dump(),
                ],
            }
        )
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
    }
    from ai_agent_project.agent.research import ResearchPaperMaterials

    assert not (forbidden & set(ResearchPaperMaterials.model_fields))
    assert not (forbidden & set(ResearchPaperMaterialsPayload.model_fields))

    class Failing:
        def generate(self, *args):
            raise RuntimeError("down")

    service, store = _ready_service(Failing())
    with pytest.raises(ResearchRunError, match="generation failed"):
        service.generate_paper_materials("run")
    assert store.get("run").status.value == "research_synthesis_ready"


def test_paper_materials_file_store_round_trip_and_legacy_read(tmp_path: Path) -> None:
    class Generator:
        def generate(self, *args):
            return _payload()

    service, memory_store = _ready_service(Generator())
    before = memory_store.get("run")
    assert before is not None and before.paper_materials is None
    generated = service.generate_paper_materials("run").research_run
    assert generated.status is ResearchStatus.PAPER_MATERIALS_READY
    assert generated.selected_direction_id == before.selected_direction_id
    assert generated.plan_revision_state == before.plan_revision_state
    assert generated.implementation_plan == before.implementation_plan
    assert generated.result_submission == before.result_submission
    assert generated.result_analysis == before.result_analysis
    assert generated.result_synthesis == before.result_synthesis

    root = tmp_path / "runs"
    run_id = "00000000-0000-4000-8000-000000000061"
    FileResearchRunStore(root).create(run_id, generated)
    loaded = FileResearchRunStore(root).get(run_id)
    assert loaded is not None and loaded.status is ResearchStatus.PAPER_MATERIALS_READY
    assert loaded.paper_materials == generated.paper_materials
    results = {item.metric_id: item for item in loaded.paper_materials.key_results}
    assert results["M"].value == 0.9123
    assert results["M"].observation_status is ResearchMeasurementStatus.MEASURED
    assert results["M2"].value is None
    assert results["M2"].observation_status is ResearchMeasurementStatus.NOT_MEASURED
    assert (
        loaded.result_submission.task_results[1].execution_status
        is ResearchTaskExecutionStatus.NOT_EXECUTED
    )

    legacy_id = "00000000-0000-4000-8000-000000000062"
    legacy = before.model_dump(mode="json")
    legacy.pop("paper_materials", None)
    path = root / f"{legacy_id}.json"
    path.write_text(
        json.dumps({"research_run_id": legacy_id, "research_run": legacy}),
        encoding="utf-8",
    )
    original = path.read_bytes()
    legacy_loaded = FileResearchRunStore(root).get(legacy_id)
    assert legacy_loaded is not None and legacy_loaded.paper_materials is None
    assert path.read_bytes() == original
