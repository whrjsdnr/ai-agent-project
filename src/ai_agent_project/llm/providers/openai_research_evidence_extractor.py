"""OpenAI structured-output provider for source-grounded research evidence."""

import json
import os

from pydantic import ValidationError

from ai_agent_project.agent.research import (
    ResearchEvidence,
    ResearchEvidenceSet,
    ResearchQuestion,
)
from ai_agent_project.agent.research_discovery import ResearchEvidenceExtractor
from ai_agent_project.agent.research_sources import RetrievedResearchSource
from ai_agent_project.llm.providers.openai import DEFAULT_MODEL, OpenAIAPIClient
from ai_agent_project.llm.providers.structured_schema import openai_strict_json_schema

_INSTRUCTIONS = (
    "Extract only evidence directly supported by the supplied retrieved source content. "
    "Every source_id and question_id must copy the supplied authoritative IDs verbatim. "
    "Do not invent URLs, sources, questions, or unsupported claims. Return an empty evidence "
    "array if this source provides no useful support."
)


class ResearchEvidenceExtractionError(ValueError):
    """Raised when source evidence cannot be parsed or violates identity rules."""


class OpenAIResearchEvidenceExtractor(ResearchEvidenceExtractor):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        client: OpenAIAPIClient | None = None,
    ) -> None:
        self._model = model or os.getenv("OPENAI_MODEL", DEFAULT_MODEL)
        self._api_key = api_key or os.getenv("OPENAI_API_KEY")
        self._client = client

    def extract(
        self, question: ResearchQuestion, source: RetrievedResearchSource
    ) -> tuple[ResearchEvidence, ...]:
        response = self._get_client().responses.create(
            model=self._model,
            instructions=_INSTRUCTIONS,
            input=[
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "question": question.model_dump(mode="json"),
                            "source": source.source.model_dump(mode="json"),
                            "content": source.content,
                        }
                    ),
                }
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "research_evidence",
                    "schema": openai_strict_json_schema(ResearchEvidenceSet),
                    "strict": True,
                }
            },
        )
        output = getattr(response, "output_text", None)
        if not isinstance(output, str):
            raise ResearchEvidenceExtractionError(
                "OpenAI evidence extractor returned no output"
            )
        try:
            evidence = ResearchEvidenceSet.model_validate(json.loads(output)).evidence
        except (json.JSONDecodeError, ValidationError) as error:
            raise ResearchEvidenceExtractionError(
                "OpenAI evidence extractor returned invalid output"
            ) from error
        if any(
            item.source_id != source.source.id or item.question_id != question.id
            for item in evidence
        ):
            raise ResearchEvidenceExtractionError(
                f"OpenAI evidence extractor returned non-authoritative IDs for question {question.id} and source {source.source.id}"
            )
        return evidence

    def _get_client(self) -> OpenAIAPIClient:
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise ValueError("OPENAI_API_KEY must be configured")
        from openai import OpenAI

        self._client = OpenAI(api_key=self._api_key)
        return self._client
