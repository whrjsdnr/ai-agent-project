"""Tool-grounded OpenAI Responses web-search source provider."""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Iterable
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ai_agent_project.agent.research import (
    ResearchQuestion,
    RetrievalGranularity,
    RetrievalProvenance,
    SourceAuthority,
)
from ai_agent_project.agent.research_sources import (
    ResearchSourceCandidate,
    ResearchSourceProvider,
    RetrievedResearchSource,
)
from ai_agent_project.llm.providers.openai import DEFAULT_MODEL, OpenAIAPIClient

_SENTENCE_BOUNDARIES = re.compile(r"[.!?]\s|\n\n")


class WebResearchSourceError(ValueError):
    """Raised when tool-grounded web search cannot yield usable source excerpts."""


class OpenAIWebResearchSourceProvider(ResearchSourceProvider):
    """Use only Responses web-search metadata plus URL-citation annotations.

    The provider deliberately stores citation-linked generated text as a bounded
    grounded search excerpt; it never represents that text as downloaded page content.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        client: OpenAIAPIClient | None = None,
        max_excerpt_characters: int = 800,
        request_timeout_seconds: float = 90.0,
    ) -> None:
        if max_excerpt_characters < 80:
            raise ValueError("max_excerpt_characters must be at least 80")
        if request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds must be positive")
        self._model = model or os.getenv("OPENAI_MODEL", DEFAULT_MODEL)
        self._api_key = api_key or os.getenv("OPENAI_API_KEY")
        self._client = client
        self._max_excerpt_characters = max_excerpt_characters
        self._request_timeout_seconds = request_timeout_seconds
        self._retrieved: dict[str, RetrievedResearchSource] = {}

    def search(
        self, question: ResearchQuestion, *, max_results: int
    ) -> tuple[ResearchSourceCandidate, ...]:
        if max_results < 1:
            raise ValueError("max_results must be at least one")
        response = self._get_client().responses.create(
            model=self._model,
            input=(
                "Use web search to answer this research question in short, factual "
                "sentences. Cite every externally grounded statement.\n\n"
                f"Question: {question.question}"
            ),
            tools=[{"type": "web_search"}],
            include=["web_search_call.action.sources"],
            max_tool_calls=1,
        )
        tool_urls = _tool_backed_urls(getattr(response, "output", ()))
        citations = _url_citations(getattr(response, "output", ()))
        candidates: list[ResearchSourceCandidate] = []
        seen: set[str] = set()
        for url, title, excerpt, granularity in citations:
            canonical_url = canonicalize_locator(url)
            if url not in tool_urls or canonical_url in seen:
                continue
            seen.add(canonical_url)
            source = ResearchSourceCandidate(
                id=_source_id(url),
                title=title or url,
                locator=url,
                canonical_locator=canonical_url,
                source_type="web search result",
                authority=_classify_authority(url),
                provenance=RetrievalProvenance(
                    provider="openai",
                    retrieval_type="web_search_citation",
                    tool_grounded=True,
                    content_granularity=granularity,
                ),
            )
            self._retrieved[canonical_url] = RetrievedResearchSource(
                source=source, content=excerpt
            )
            candidates.append(source)
            if len(candidates) == max_results:
                break
        return tuple(candidates)

    def fetch(self, candidate: ResearchSourceCandidate) -> RetrievedResearchSource:
        retrieved = self._retrieved.get(
            candidate.canonical_locator or candidate.locator
        )
        if retrieved is None or retrieved.source != candidate:
            raise WebResearchSourceError(
                "No tool-grounded excerpt is available for source"
            )
        return retrieved

    def _get_client(self) -> OpenAIAPIClient:
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise ValueError("OPENAI_API_KEY must be configured")
        from openai import OpenAI

        self._client = OpenAI(
            api_key=self._api_key, timeout=self._request_timeout_seconds
        )
        return self._client


def _tool_backed_urls(items: Iterable[Any]) -> set[str]:
    urls: set[str] = set()
    for item in items:
        if _value(item, "type") != "web_search_call":
            continue
        action = _value(item, "action")
        if _value(action, "type") != "search":
            continue
        for source in _value(action, "sources") or ():
            url = _value(source, "url")
            if isinstance(url, str):
                urls.add(url)
    return urls


def _url_citations(
    items: Iterable[Any],
) -> tuple[tuple[str, str, str, RetrievalGranularity], ...]:
    citations: list[tuple[str, str, str, RetrievalGranularity]] = []
    for item in items:
        if _value(item, "type") != "message":
            continue
        for content in _value(item, "content") or ():
            if _value(content, "type") != "output_text":
                continue
            text = _value(content, "text")
            if not isinstance(text, str):
                continue
            for annotation in _value(content, "annotations") or ():
                if _value(annotation, "type") != "url_citation":
                    continue
                url, title = _value(annotation, "url"), _value(annotation, "title")
                start, end = (
                    _value(annotation, "start_index"),
                    _value(annotation, "end_index"),
                )
                if not isinstance(url, str) or not isinstance(title, str):
                    continue
                if (
                    not isinstance(start, int)
                    or not isinstance(end, int)
                    or start < 0
                    or end < start
                ):
                    continue
                excerpt = _preceding_claim(text, start, end)
                granularity = RetrievalGranularity.GROUNDED_SEARCH_EXCERPT
                if excerpt:
                    citations.append((url, title, excerpt, granularity))
    return tuple(citations)


def _preceding_claim(text: str, start: int, end: int) -> str:
    """Return only the sentence immediately before a citation marker."""
    if end > len(text) or start > len(text):
        return ""
    prefix = text[:start].strip()
    left = max(
        (
            match.end()
            for match in _SENTENCE_BOUNDARIES.finditer(prefix)
            if match.end() < len(prefix)
        ),
        default=0,
    )
    claim = prefix[left:].strip()
    if not claim or claim.startswith("["):
        return ""
    return claim[-800:]


def canonicalize_locator(url: str) -> str:
    """Drop only `utm_*` tracking keys for stable source identity."""
    parsed = urlsplit(url)
    query = urlencode(
        [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.lower().startswith("utm_")
        ],
        doseq=True,
    )
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, query, parsed.fragment)
    )


def _source_id(url: str) -> str:
    return f"SRC-{hashlib.sha256(url.encode()).hexdigest()[:12]}"


def _classify_authority(url: str) -> SourceAuthority:
    host = url.split("/", 3)[2].lower()
    if host.endswith((".gov", ".edu")) or host.startswith("docs."):
        return SourceAuthority.OFFICIAL
    return SourceAuthority.UNKNOWN


def _value(item: Any, name: str) -> Any:
    return item.get(name) if isinstance(item, dict) else getattr(item, name, None)
