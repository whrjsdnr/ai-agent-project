from types import SimpleNamespace

import pytest

from ai_agent_project.agent.research import ResearchQuestion, ResearchScope
from ai_agent_project.agent.research_sources import ResearchSourceCandidate
from ai_agent_project.llm.providers.openai_web_research import (
    OpenAIWebResearchSourceProvider,
    WebResearchSourceError,
)


class _Responses:
    def __init__(self, response: object | Exception) -> None:
        self._response = response

    def create(self, **kwargs: object) -> object:
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


def _item(**kwargs: object) -> SimpleNamespace:
    return SimpleNamespace(**kwargs)


def _response(
    *,
    tool_urls: tuple[str, ...],
    citations: tuple[tuple[str, str, int, int], ...],
    text: str = "Grounded fact. [citation]",
) -> object:
    return _item(
        output=[
            _item(
                type="web_search_call",
                action=_item(
                    type="search",
                    sources=[_item(url=url) for url in tool_urls],
                ),
            ),
            _item(
                type="message",
                content=[
                    _item(
                        type="output_text",
                        text=text,
                        annotations=[
                            _item(
                                type="url_citation",
                                url=url,
                                title=title,
                                start_index=start,
                                end_index=end,
                            )
                            for url, title, start, end in citations
                        ],
                    )
                ],
            ),
        ]
    )


def _provider(response: object | Exception) -> OpenAIWebResearchSourceProvider:
    return OpenAIWebResearchSourceProvider(
        client=_item(responses=_Responses(response)), max_excerpt_characters=80
    )


def _question() -> ResearchQuestion:
    return ResearchQuestion(
        id="RQ-001",
        question="What is grounded?",
        rationale="Test provenance.",
        source_scope=ResearchScope.EXTERNAL,
    )


def test_accepts_only_matching_tool_url_and_citation() -> None:
    url = "https://example.org/paper"
    provider = _provider(
        _response(tool_urls=(url,), citations=((url, "Paper", 15, 25),))
    )

    candidates = provider.search(_question(), max_results=3)

    assert len(candidates) == 1
    retrieved = provider.fetch(candidates[0])
    assert retrieved.content
    assert retrieved.source.provenance is not None
    assert retrieved.source.provenance.tool_grounded is True


def test_rejects_free_form_or_unmatched_citation_urls() -> None:
    provider = _provider(
        _response(
            tool_urls=("https://tool.example/source",),
            citations=(("https://text.example/invented", "Invented", 15, 25),),
        )
    )

    assert provider.search(_question(), max_results=3) == ()


def test_deduplicates_same_url_and_bounds_excerpt() -> None:
    url = "https://example.org/paper?utm_source=openai"
    text = "A" * 1000
    provider = _provider(
        _response(
            tool_urls=(url,),
            citations=((url, "Paper", 1000, 1010), (url, "Paper", 1000, 1010)),
            text=f"{text}[citation]",
        )
    )

    candidates = provider.search(_question(), max_results=3)

    assert len(candidates) == 1
    assert candidates[0].canonical_locator == "https://example.org/paper"
    assert len(provider.fetch(candidates[0]).content) <= 800


def test_fetch_unknown_candidate_never_falls_back_to_model() -> None:
    provider = _provider(_response(tool_urls=(), citations=()))
    unknown = ResearchSourceCandidate(
        id="SRC-UNKNOWN",
        title="Unknown",
        locator="https://example.org/unknown",
        source_type="web search result",
    )

    with pytest.raises(WebResearchSourceError, match="No tool-grounded excerpt"):
        provider.fetch(unknown)


def test_provider_exception_propagates() -> None:
    provider = _provider(RuntimeError("provider unavailable"))

    with pytest.raises(RuntimeError, match="provider unavailable"):
        provider.search(_question(), max_results=1)
