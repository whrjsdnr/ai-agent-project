"""Opt-in bounded E2E for planning after an explicit research direction selection."""

import os

import pytest

from ai_agent_project.agent.research import (
    RelatedStudy,
    ResearchDirection,
    ResearchDiscoveryReport,
    ResearchEvidence,
    ResearchGap,
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
from ai_agent_project.llm.providers.openai_research_plan_generator import (
    OpenAIResearchPlanGenerator,
)


@pytest.mark.skipif(
    os.getenv("RUN_OPENAI_E2E") != "1",
    reason="requires explicit OpenAI E2E opt-in",
)
def test_production_research_plan_generation_is_read_only(tmp_path) -> None:
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY is not configured")
    workspace_file = tmp_path / "workspace.txt"
    workspace_file.write_text("unchanged\n", encoding="utf-8")
    before = workspace_file.read_bytes()
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
                title="Source",
                locator="https://example.org/source",
                source_type="web",
            ),
        ),
        evidence=(
            ResearchEvidence(
                id="E1",
                source_id="S1",
                question_id="Q1",
                claim="Claim",
                support_text="Excerpt",
                evidence_type="citation",
            ),
        ),
        related_studies=(
            RelatedStudy(
                id="ST1",
                title="Study",
                research_problem="Problem",
                evidence_ids=("E1",),
            ),
        ),
        gaps=(
            ResearchGap(
                id="G1",
                description="Gap",
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
                research_question="Question",
                target_gap_ids=("G1",),
                novelty="Novel",
                feasibility="feasible",
            ),
        ),
    )
    run = ResearchRun(
        request=ResearchRequest(topic="Bounded planning topic"),
        status=ResearchStatus.DIRECTION_SELECTED,
        report=report,
        selected_direction_id="RD1",
    )
    store = InMemoryResearchRunStore()
    store.create("run", run)
    service = ResearchApplicationService(object(), store, OpenAIResearchPlanGenerator())

    planned = service.generate_plan("run")

    assert planned.research_run.status is ResearchStatus.AWAITING_RESEARCH_PLAN_APPROVAL
    assert planned.research_run.plan_revision_state is not None
    assert (
        planned.research_run.plan_revision_state.active_plan.selected_direction_id
        == "RD1"
    )
    assert workspace_file.read_bytes() == before
