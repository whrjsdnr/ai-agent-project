"""Opt-in diagnostic probe for Responses web-search provenance metadata."""

import os

import pytest


@pytest.mark.skipif(
    os.getenv("RUN_OPENAI_E2E") != "1",
    reason="requires explicit OpenAI E2E opt-in",
)
def test_responses_web_search_returns_citation_provenance() -> None:
    """Print bounded structural diagnostics, never prompts, keys, or full output."""
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY is not configured")
    from openai import OpenAI

    response = OpenAI().responses.create(
        model=os.getenv("OPENAI_MODEL", "gpt-5-mini"),
        input="Find one authoritative source about FastAPI lifespan startup shutdown. Cite it.",
        tools=[{"type": "web_search"}],
        include=["web_search_call.action.sources"],
    )
    calls = [item for item in response.output if item.type == "web_search_call"]
    citations = [
        (content.text, annotation)
        for item in response.output
        if item.type == "message"
        for content in item.content
        if content.type == "output_text"
        for annotation in content.annotations
        if annotation.type == "url_citation"
    ]
    print("output_types=", [item.type for item in response.output])
    print(
        "web_search_sources=",
        [
            source.url
            for call in calls
            if call.action.type == "search"
            for source in (call.action.sources or [])
        ],
    )
    print(
        "url_citations=",
        [
            {
                "url": citation.url,
                "title": citation.title,
                "start_index": citation.start_index,
                "end_index": citation.end_index,
            }
            for _, citation in citations
        ],
    )
    print(
        "citation_spans=",
        [
            {
                "url": citation.url,
                "span": text[citation.start_index : citation.end_index],
                "context": text[
                    max(0, citation.start_index - 120) : min(
                        len(text), citation.end_index + 120
                    )
                ],
            }
            for text, citation in citations
        ],
    )
    assert calls, "Responses web search produced no web_search_call"
    assert citations, "Responses web search produced no url_citation annotation"
