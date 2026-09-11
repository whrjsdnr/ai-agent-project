"""Opt-in production E2E for tool-grounded Research Discovery."""

import os
import time
from urllib.parse import urlparse

import pytest

from ai_agent_project.agent.research import ResearchRequest
from ai_agent_project.agent.research_discovery import (
    ResearchDiscoveryLimits,
    ResearchDiscoveryService,
)
from ai_agent_project.llm.providers.openai_research_discovery_synthesizer import (
    OpenAIResearchDiscoverySynthesizer,
)
from ai_agent_project.llm.providers.openai_research_evidence_extractor import (
    OpenAIResearchEvidenceExtractor,
)
from ai_agent_project.llm.providers.openai_research_question_planner import (
    OpenAIResearchQuestionPlanner,
)
from ai_agent_project.llm.providers.openai_web_research import (
    OpenAIWebResearchSourceProvider,
)


@pytest.mark.skipif(
    os.getenv("RUN_OPENAI_E2E") != "1",
    reason="requires explicit OpenAI E2E opt-in",
)
def test_production_research_discovery_is_tool_grounded() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY is not configured")
    limits = ResearchDiscoveryLimits(max_questions=1, max_sources_per_question=1)
    service = ResearchDiscoveryService(
        OpenAIResearchQuestionPlanner(),
        OpenAIWebResearchSourceProvider(),
        OpenAIResearchEvidenceExtractor(),
        OpenAIResearchDiscoverySynthesizer(),
        limits=limits,
    )
    started = time.monotonic()
    run = service.discover(
        ResearchRequest(topic="FastAPI lifespan context manager startup shutdown")
    )

    report = run.report
    print("planned_question_count=<=", limits.max_questions)
    print("processed_question_count=", len(report.questions))
    print("source_count=", len(report.sources))
    print("evidence_count=", len(report.evidence))
    print("study_count=", len(report.related_studies))
    print("gap_count=", len(report.gaps))
    print("direction_count=", len(report.directions))
    print("elapsed_seconds=", round(time.monotonic() - started, 2))
    assert report.sources
    assert all(
        urlparse(source.locator).scheme in {"http", "https"}
        and urlparse(source.locator).netloc
        for source in report.sources
    )
    assert all(
        source.provenance is not None and source.provenance.tool_grounded
        for source in report.sources
    )
    evidence_source_ids = {item.source_id for item in report.evidence}
    sources_by_id = {item.id: item for item in report.sources}
    assert evidence_source_ids <= set(sources_by_id)
    assert all(sources_by_id[item].locator for item in evidence_source_ids)
    report.validate_traceability()
