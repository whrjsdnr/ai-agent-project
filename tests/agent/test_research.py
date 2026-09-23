import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from ai_agent_project.agent.research import (
    PreliminaryResearchReport,
    RelatedStudy,
    RelatedWorkReport,
    ResearchDirection,
    ResearchDiscoveryReport,
    ResearchEvidence,
    ResearchEvolutionStage,
    ResearchGap,
    ResearchLandscape,
    ResearchMetric,
    ResearchObjective,
    ResearchPlan,
    ResearchQuestion,
    ResearchRequest,
    ResearchScope,
    ResearchSource,
    ResearchStatus,
    ResearchSuccessCriterion,
    ResearchSynthesis,
    SourceAuthority,
)
from ai_agent_project.agent.research_application import (
    InMemoryResearchRunStore,
    InvalidResearchStateError,
    ResearchApplicationService,
)
from ai_agent_project.agent.research_discovery import (
    ResearchDiscoveryError,
    ResearchDiscoveryService,
)
from ai_agent_project.agent.research_file_store import (
    FileResearchRunStore,
    ResearchRunStorageError,
)
from ai_agent_project.agent.research_sources import (
    ResearchSourceCandidate,
    RetrievedResearchSource,
)
from ai_agent_project.agent.workspace import FilesystemWorkspaceInspector


def test_evidence_first_research_traceability() -> None:
    report = ResearchDiscoveryReport(
        questions=(
            ResearchQuestion(
                id="Q1",
                question="What?",
                rationale="Why?",
                source_scope=ResearchScope.EXTERNAL,
            ),
        ),
        sources=(
            ResearchSource(
                id="S1",
                title="Official",
                locator="https://example.test",
                source_type="doc",
                authority=SourceAuthority.OFFICIAL,
            ),
        ),
        evidence=(
            ResearchEvidence(
                id="E1",
                source_id="S1",
                question_id="Q1",
                claim="claim",
                support_text="support",
                evidence_type="text",
            ),
        ),
        related_studies=(
            RelatedStudy(
                id="ST1",
                title="Study",
                research_problem="problem",
                evidence_ids=("E1",),
            ),
        ),
        gaps=(
            ResearchGap(
                id="G1",
                description="gap",
                supporting_study_ids=("ST1",),
                evidence_ids=("E1",),
                importance="high",
                feasibility="feasible",
            ),
        ),
        directions=(
            ResearchDirection(
                id="RD1",
                title="Direction",
                research_question="question",
                target_gap_ids=("G1",),
                novelty="new",
                feasibility="feasible",
            ),
        ),
    )
    assert report.directions[0].target_gap_ids == ("G1",)


def test_research_traceability_rejects_unknown_ids() -> None:
    with pytest.raises(ValidationError, match="unknown source or question"):
        ResearchDiscoveryReport(
            questions=(),
            sources=(),
            evidence=(
                ResearchEvidence(
                    id="E1",
                    source_id="missing",
                    question_id="missing",
                    claim="c",
                    support_text="s",
                    evidence_type="text",
                ),
            ),
        )


class _FakeQuestionPlanner:
    def plan(
        self, request: ResearchRequest, workspace: object | None = None
    ) -> tuple[ResearchQuestion, ...]:
        del request, workspace
        return (
            ResearchQuestion(
                id="RQ-001",
                question="Which lifecycle approaches exist?",
                rationale="Map established approaches.",
                source_scope=ResearchScope.EXTERNAL,
            ),
            ResearchQuestion(
                id="RQ-002",
                question="Which limitations recur?",
                rationale="Identify defensible gaps.",
                source_scope=ResearchScope.EXTERNAL,
            ),
            ResearchQuestion(
                id="RQ-003",
                question="Which directions are feasible?",
                rationale="Support direction selection.",
                source_scope=ResearchScope.MIXED,
            ),
        )


class _FakeSourceProvider:
    def search(
        self, question: ResearchQuestion, *, max_results: int
    ) -> tuple[ResearchSourceCandidate, ...]:
        del max_results
        shared = ResearchSourceCandidate(
            id="SRC-OFFICIAL",
            title="FastAPI lifespan documentation",
            locator="https://docs.example.test/lifespan",
            source_type="official documentation",
            authority=SourceAuthority.OFFICIAL,
        )
        sources = {
            "RQ-001": (
                shared,
                ResearchSourceCandidate(
                    id="SRC-PRIMARY",
                    title="Lifecycle engineering study",
                    locator="https://primary.example.test/lifecycle",
                    source_type="technical paper",
                    authority=SourceAuthority.PRIMARY,
                ),
            ),
            "RQ-002": (
                shared,
                ResearchSourceCandidate(
                    id="SRC-SECONDARY",
                    title="Operational lifecycle guide",
                    locator="https://secondary.example.test/lifecycle",
                    source_type="technical article",
                    authority=SourceAuthority.SECONDARY,
                ),
            ),
            "RQ-003": (shared,),
        }
        return sources[question.id]

    def fetch(self, candidate: ResearchSourceCandidate) -> RetrievedResearchSource:
        return RetrievedResearchSource(source=candidate, content=candidate.title)


class _FakeEvidenceExtractor:
    def extract(
        self, question: ResearchQuestion, source: RetrievedResearchSource
    ) -> tuple[ResearchEvidence, ...]:
        return (
            ResearchEvidence(
                id=f"E-{question.id}-{source.source.id}",
                source_id=source.source.id,
                question_id=question.id,
                claim=f"Evidence for {question.id}",
                support_text=source.content,
                evidence_type="retrieved_text",
            ),
        )


class _FakeSynthesizer:
    def synthesize(
        self,
        request: ResearchRequest,
        questions: tuple[ResearchQuestion, ...],
        sources: tuple[ResearchSource, ...],
        evidence: tuple[ResearchEvidence, ...],
    ) -> ResearchSynthesis:
        del request, questions, sources
        study_one_evidence, study_two_evidence = evidence[:2]
        studies = (
            RelatedStudy(
                id="ST-001",
                title="Lifecycle documentation",
                research_problem="Application startup shutdown management",
                evidence_ids=(study_one_evidence.id,),
            ),
            RelatedStudy(
                id="ST-002",
                title="Lifecycle operations",
                research_problem="Reliable resource ownership",
                evidence_ids=(study_two_evidence.id,),
            ),
        )
        return ResearchSynthesis(
            preliminary=PreliminaryResearchReport(
                topic="FastAPI lifespan management",
                research_domains=("web lifecycle",),
                evidence_ids=(study_one_evidence.id,),
            ),
            related_work=RelatedWorkReport(study_ids=("ST-001", "ST-002")),
            landscape=ResearchLandscape(
                stages=(
                    ResearchEvolutionStage(
                        id="EV-001",
                        title="Event hooks",
                        representative_study_ids=("ST-001",),
                    ),
                    ResearchEvolutionStage(
                        id="EV-002",
                        title="Explicit lifespan contexts",
                        representative_study_ids=("ST-002",),
                    ),
                ),
                current_frontier="Explicit resource ownership",
            ),
            related_studies=studies,
            gaps=(
                ResearchGap(
                    id="GAP-001",
                    description="Operational evidence remains fragmented.",
                    supporting_study_ids=("ST-001", "ST-002"),
                    evidence_ids=(study_one_evidence.id, study_two_evidence.id),
                    importance="high",
                    feasibility="feasible",
                ),
            ),
            directions=(
                ResearchDirection(
                    id="RD-001",
                    title="Lifecycle observability",
                    research_question="How can lifecycle failures be observed?",
                    target_gap_ids=("GAP-001",),
                    novelty="Unifies operational evidence.",
                    feasibility="feasible",
                ),
                ResearchDirection(
                    id="RD-002",
                    title="Resource ownership patterns",
                    research_question="Which ownership patterns are robust?",
                    target_gap_ids=("GAP-001",),
                    novelty="Compares explicit ownership patterns.",
                    feasibility="feasible",
                ),
            ),
        )


def test_discovery_service_builds_read_only_evidence_first_run(tmp_path) -> None:
    app = tmp_path / "app.py"
    readme = tmp_path / "README.md"
    app.write_text("print('unchanged')\n", encoding="utf-8")
    readme.write_text("# Research fixture\n", encoding="utf-8")
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}

    service = ResearchDiscoveryService(
        _FakeQuestionPlanner(),
        _FakeSourceProvider(),
        _FakeEvidenceExtractor(),
        _FakeSynthesizer(),
        FilesystemWorkspaceInspector(tmp_path),
    )
    run = service.discover(
        ResearchRequest(
            topic="Investigate modern approaches for FastAPI application lifespan management."
        )
    )

    assert run.status is ResearchStatus.AWAITING_DIRECTION_SELECTION
    assert run.selected_direction_id is None
    assert len(run.report.questions) == 3
    assert len(run.report.sources) == 3
    assert len(run.report.evidence) >= 3
    assert run.report.preliminary is not None
    assert run.report.related_work is not None
    assert len(run.report.related_studies) == 2
    assert run.report.landscape is not None and len(run.report.landscape.stages) == 2
    assert len(run.report.gaps) == 1
    assert len(run.report.directions) == 2
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before


def test_discovery_rejects_no_evidence() -> None:
    class NoEvidenceExtractor:
        def extract(
            self, question: ResearchQuestion, source: RetrievedResearchSource
        ) -> tuple[ResearchEvidence, ...]:
            del question, source
            return ()

    service = ResearchDiscoveryService(
        _FakeQuestionPlanner(),
        _FakeSourceProvider(),
        NoEvidenceExtractor(),
        _FakeSynthesizer(),
    )
    with pytest.raises(ResearchDiscoveryError, match="no useful evidence"):
        service.discover(ResearchRequest(topic="A bounded research topic"))


def test_discovery_rekeys_colliding_extractor_evidence_ids() -> None:
    class CollidingExtractor:
        def extract(
            self, question: ResearchQuestion, source: RetrievedResearchSource
        ) -> tuple[ResearchEvidence, ...]:
            return (
                ResearchEvidence(
                    id="E1",
                    source_id=source.source.id,
                    question_id=question.id,
                    claim="First grounded claim",
                    support_text=source.content,
                    evidence_type="retrieved_text",
                ),
                ResearchEvidence(
                    id="E2",
                    source_id=source.source.id,
                    question_id=question.id,
                    claim="Second grounded claim",
                    support_text=source.content,
                    evidence_type="retrieved_text",
                ),
            )

    run = ResearchDiscoveryService(
        _FakeQuestionPlanner(),
        _FakeSourceProvider(),
        CollidingExtractor(),
        _FakeSynthesizer(),
    ).discover(ResearchRequest(topic="A bounded research topic"))

    evidence_ids = [item.id for item in run.report.evidence]
    assert evidence_ids == [f"E{index}" for index in range(1, len(evidence_ids) + 1)]
    assert len(evidence_ids) == len(set(evidence_ids))
    assert {item.source_id for item in run.report.evidence} <= {
        source.id for source in run.report.sources
    }


def _discovery_service() -> ResearchDiscoveryService:
    return ResearchDiscoveryService(
        _FakeQuestionPlanner(),
        _FakeSourceProvider(),
        _FakeEvidenceExtractor(),
        _FakeSynthesizer(),
    )


def test_application_requires_explicit_single_direction_selection() -> None:
    application = ResearchApplicationService(
        _discovery_service(), InMemoryResearchRunStore()
    )
    created = application.create_research_run("FastAPI lifespan management")

    selected = application.select_research_direction(created.id, "RD-002")

    assert selected.research_run.status is ResearchStatus.DIRECTION_SELECTED
    assert selected.research_run.selected_direction_id == "RD-002"
    assert created.research_run.selected_direction_id is None
    with pytest.raises(InvalidResearchStateError, match="only allowed"):
        application.select_research_direction(created.id, "RD-001")


def test_file_store_round_trips_selected_direction(tmp_path) -> None:
    store_root = tmp_path / "research-runs"
    first_application = ResearchApplicationService(
        _discovery_service(), FileResearchRunStore(store_root)
    )
    created = first_application.create_research_run("FastAPI lifespan management")
    first_application.select_research_direction(created.id, "RD-002")

    reloaded = ResearchApplicationService(
        _discovery_service(), FileResearchRunStore(store_root)
    ).get_research_run(created.id)

    assert reloaded.research_run.status is ResearchStatus.DIRECTION_SELECTED
    assert reloaded.research_run.selected_direction_id == "RD-002"
    with pytest.raises(ResearchRunStorageError, match="canonical UUID"):
        FileResearchRunStore(store_root).get("../not-a-run")


def test_research_plan_lifecycle_preserves_selected_direction(tmp_path) -> None:
    class FakePlanGenerator:
        def generate(self, request, direction, report, *, revision_note=None):
            del request, report
            suffix = "2" if revision_note else "1"
            return ResearchPlan(
                id=f"PLAN-{suffix}",
                selected_direction_id=direction.id,
                title="Planning-only plan",
                research_question=direction.research_question,
                objectives=(
                    ResearchObjective(
                        id=f"OBJ-{suffix}",
                        description="Objective",
                        direction_id=direction.id,
                    ),
                ),
                metrics=(
                    ResearchMetric(
                        id=f"MET-{suffix}",
                        name="Quality",
                        description="Qualitative",
                        measurement_method="Review",
                    ),
                ),
                success_criteria=(
                    ResearchSuccessCriterion(
                        id=f"SC-{suffix}",
                        metric_id=f"MET-{suffix}",
                        target_description="Qualitatively useful",
                        rationale="Exploratory",
                    ),
                ),
            )

    workspace = tmp_path / "workspace"
    (workspace / "nested").mkdir(parents=True)
    (workspace / "README.md").write_text("planning only\n", encoding="utf-8")
    (workspace / "nested" / "data.txt").write_bytes(b"unchanged\n")
    before = {
        path.relative_to(workspace): path.read_bytes()
        for path in workspace.rglob("*")
        if path.is_file()
    }
    application = ResearchApplicationService(
        _discovery_service(), InMemoryResearchRunStore(), FakePlanGenerator()
    )
    created = application.create_research_run("FastAPI lifespan management")
    selected = application.select_research_direction(created.id, "RD-002")
    generated = application.generate_plan(created.id)
    revised = application.revise_plan(created.id, "Clarify methodology")
    approved = application.approve_plan(created.id)

    assert selected.research_run.selected_direction_id == "RD-002"
    assert (
        generated.research_run.status is ResearchStatus.AWAITING_RESEARCH_PLAN_APPROVAL
    )
    assert generated.research_run.plan_revision_state is not None
    assert generated.research_run.plan_revision_state.active_version == 1
    assert revised.research_run.plan_revision_state is not None
    assert revised.research_run.plan_revision_state.active_version == 2
    assert revised.research_run.plan_revision_state.revisions[0].plan.id == "PLAN-1"
    assert approved.research_run.status is ResearchStatus.RESEARCH_PLAN_APPROVED
    assert approved.research_run.selected_direction_id == "RD-002"
    after = {
        path.relative_to(workspace): path.read_bytes()
        for path in workspace.rglob("*")
        if path.is_file()
    }
    assert after == before
    with pytest.raises(InvalidResearchStateError):
        application.revise_plan(created.id, "Too late")


def test_file_store_persists_planning_state_and_loads_feature_3a_snapshots(
    tmp_path,
) -> None:
    class FakePlanGenerator:
        def generate(self, request, direction, report, *, revision_note=None):
            del request, report
            version = "2" if revision_note else "1"
            return ResearchPlan(
                id=f"PLAN-{version}",
                selected_direction_id=direction.id,
                title="Plan",
                research_question=direction.research_question,
                objectives=(
                    ResearchObjective(
                        id=f"OBJ-{version}",
                        description="Objective",
                        direction_id=direction.id,
                    ),
                ),
            )

    store_root = tmp_path / "research-runs"
    application = ResearchApplicationService(
        _discovery_service(), FileResearchRunStore(store_root), FakePlanGenerator()
    )
    created = application.create_research_run("FastAPI lifespan management")
    application.select_research_direction(created.id, "RD-002")
    application.generate_plan(created.id)
    application.revise_plan(created.id, "Clarify scope")
    approved = application.approve_plan(created.id)

    reloaded = ResearchApplicationService(
        _discovery_service(), FileResearchRunStore(store_root), FakePlanGenerator()
    ).get_research_run(created.id)
    assert reloaded.research_run == approved.research_run
    assert reloaded.research_run.status is ResearchStatus.RESEARCH_PLAN_APPROVED
    assert reloaded.research_run.selected_direction_id == "RD-002"
    assert reloaded.research_run.plan_revision_state is not None
    assert [
        item.note for item in reloaded.research_run.plan_revision_state.revisions
    ] == [
        None,
        "Clarify scope",
    ]
    assert reloaded.research_run.plan_revision_state.active_version == 2
    assert reloaded.research_run.plan_revision_state.approved is True

    legacy_id = str(uuid4())
    legacy_payload = reloaded.research_run.model_dump(mode="json")
    legacy_payload["status"] = ResearchStatus.DIRECTION_SELECTED.value
    legacy_payload.pop("plan_revision_state")
    (store_root / f"{legacy_id}.json").write_text(
        json.dumps({"research_run_id": legacy_id, "research_run": legacy_payload}),
        encoding="utf-8",
    )
    legacy = FileResearchRunStore(store_root).get(legacy_id)
    assert legacy is not None
    assert legacy.status is ResearchStatus.DIRECTION_SELECTED
    assert legacy.plan_revision_state is None


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update({"status": "research_plan_approved"}),
        lambda payload: payload["plan_revision_state"].update({"active_version": 9}),
        lambda payload: payload["plan_revision_state"]["revisions"][0]["plan"].update(
            {"selected_direction_id": "RD-001"}
        ),
    ],
)
def test_file_store_rejects_invalid_persisted_planning_state(tmp_path, mutate) -> None:
    store_root = tmp_path / "research-runs"
    application = ResearchApplicationService(
        _discovery_service(), FileResearchRunStore(store_root)
    )
    created = application.create_research_run("FastAPI lifespan management")
    selected = application.select_research_direction(created.id, "RD-002")
    payload = selected.research_run.model_dump(mode="json")
    payload["plan_revision_state"] = {
        "active_version": 1,
        "approved": False,
        "revisions": [
            {
                "version": 1,
                "plan": {
                    "id": "PLAN-1",
                    "selected_direction_id": "RD-002",
                    "title": "Plan",
                    "research_question": "Question",
                    "objectives": [],
                    "hypotheses": [],
                    "methodology": [],
                    "metrics": [],
                    "success_criteria": [],
                    "risks": [],
                    "assumptions": [],
                    "expected_outputs": [],
                },
                "note": None,
            }
        ],
    }
    mutate(payload)
    (store_root / f"{created.id}.json").write_text(
        json.dumps({"research_run_id": created.id, "research_run": payload}),
        encoding="utf-8",
    )

    with pytest.raises(ResearchRunStorageError, match="snapshot is invalid"):
        FileResearchRunStore(store_root).get(created.id)
