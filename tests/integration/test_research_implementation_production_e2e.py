"""Opt-in OpenAI E2E for generated-only research implementation artifacts."""

import os

import pytest

from ai_agent_project.agent.research import (
    RelatedStudy,
    ResearchDirection,
    ResearchDiscoveryReport,
    ResearchEvidence,
    ResearchGap,
    ResearchMethodologyStep,
    ResearchMetric,
    ResearchObjective,
    ResearchPlan,
    ResearchPlanRevisionState,
    ResearchQuestion,
    ResearchRequest,
    ResearchRun,
    ResearchScope,
    ResearchSource,
    ResearchStatus,
)
from ai_agent_project.agent.research_application import (
    InMemoryResearchRunStore,
    ResearchApplicationService,
)
from ai_agent_project.llm.providers.openai_research_implementation import (
    OpenAIResearchImplementationGenerator,
    OpenAIResearchImplementationPlanner,
)


@pytest.mark.skipif(
    os.getenv("RUN_OPENAI_E2E") != "1", reason="requires explicit OpenAI E2E opt-in"
)
def test_production_implementation_generation_is_generated_only(tmp_path) -> None:
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY is not configured")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "unchanged.txt").write_bytes(b"unchanged\n")
    before = {
        path.relative_to(workspace): path.read_bytes()
        for path in workspace.rglob("*")
        if path.is_file()
    }
    direction = ResearchDirection(
        id="RD-1",
        title="Direction",
        research_question="How?",
        target_gap_ids=("G-1",),
        novelty="Novel",
        feasibility="Feasible",
    )
    report = ResearchDiscoveryReport(
        questions=(
            ResearchQuestion(
                id="Q-1",
                question="How?",
                rationale="R",
                source_scope=ResearchScope.EXTERNAL,
            ),
        ),
        sources=(
            ResearchSource(
                id="S-1",
                title="Source",
                locator="https://example.org",
                source_type="web",
            ),
        ),
        evidence=(
            ResearchEvidence(
                id="E-1",
                source_id="S-1",
                question_id="Q-1",
                claim="Claim",
                support_text="Excerpt",
                evidence_type="citation",
            ),
        ),
        related_studies=(
            RelatedStudy(
                id="ST-1",
                title="Study",
                research_problem="Problem",
                evidence_ids=("E-1",),
            ),
        ),
        gaps=(
            ResearchGap(
                id="G-1",
                description="Gap",
                supporting_study_ids=("ST-1",),
                evidence_ids=("E-1",),
                importance="High",
                feasibility="Feasible",
            ),
        ),
        directions=(direction,),
    )
    approved = ResearchPlan(
        id="PLAN-1",
        selected_direction_id="RD-1",
        title="Plan",
        research_question="How?",
        objectives=(
            ResearchObjective(id="OBJ-1", description="Objective", direction_id="RD-1"),
        ),
        methodology=(
            ResearchMethodologyStep(
                id="M-1", description="Method", objective_ids=("OBJ-1",)
            ),
        ),
        metrics=(
            ResearchMetric(
                id="MET-1",
                name="Quality",
                description="Quality",
                measurement_method="Review",
            ),
        ),
    )
    run = ResearchRun(
        request=ResearchRequest(topic="Bounded generated-only package"),
        status=ResearchStatus.RESEARCH_PLAN_APPROVED,
        report=report,
        selected_direction_id="RD-1",
        plan_revision_state=ResearchPlanRevisionState.from_plan(approved).model_copy(
            update={"approved": True}
        ),
    )
    store = InMemoryResearchRunStore()
    store.create("run", run)
    service = ResearchApplicationService(
        object(),
        store,
        implementation_planner=OpenAIResearchImplementationPlanner(
            request_timeout_seconds=90
        ),
        implementation_generator=OpenAIResearchImplementationGenerator(
            request_timeout_seconds=90
        ),
    )

    planned = service.generate_implementation_plan("run")
    packaged = service.generate_implementation_package("run")

    assert planned.research_run.implementation_plan is not None
    assert packaged.research_run.status is ResearchStatus.IMPLEMENTATION_PACKAGE_READY
    assert packaged.research_run.implementation_package is not None
    assert packaged.research_run.implementation_package.generated_not_executed
    assert packaged.research_run.selected_direction_id == "RD-1"
    assert {
        path.relative_to(workspace): path.read_bytes()
        for path in workspace.rglob("*")
        if path.is_file()
    } == before
