"""OpenAI structured-output provider for evidence-first research synthesis."""

import json
import os

from pydantic import ValidationError

from ai_agent_project.agent.research import (
    ResearchEvidence,
    ResearchQuestion,
    ResearchRequest,
    ResearchSource,
    ResearchSynthesis,
)
from ai_agent_project.agent.research_discovery import ResearchDiscoverySynthesizer
from ai_agent_project.llm.providers.openai import DEFAULT_MODEL, OpenAIAPIClient
from ai_agent_project.llm.providers.structured_schema import openai_strict_json_schema

_INSTRUCTIONS = (
    "Synthesize only the requested high-level research sections from authoritative inputs. "
    "Do not regenerate questions, sources, or evidence. Use evidence IDs verbatim; generated "
    "studies must reference supplied evidence IDs, gaps must reference supplied evidence and "
    "generated study IDs, and directions must reference generated gap IDs. Omit unsupported "
    "studies, gaps, and directions instead of fabricating them. Return only structured synthesis."
)


class ResearchSynthesisError(ValueError):
    """Raised when structured synthesis is malformed or violates traceability."""


class OpenAIResearchDiscoverySynthesizer(ResearchDiscoverySynthesizer):
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

    def synthesize(
        self,
        request: ResearchRequest,
        questions: tuple[ResearchQuestion, ...],
        sources: tuple[ResearchSource, ...],
        evidence: tuple[ResearchEvidence, ...],
    ) -> ResearchSynthesis:
        response = self._get_client().responses.create(
            model=self._model,
            instructions=_INSTRUCTIONS,
            input=[
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "request": request.model_dump(mode="json"),
                            "authoritative_questions": [
                                item.model_dump(mode="json") for item in questions
                            ],
                            "authoritative_sources": [
                                item.model_dump(mode="json") for item in sources
                            ],
                            "authoritative_evidence": [
                                item.model_dump(mode="json") for item in evidence
                            ],
                        }
                    ),
                }
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "research_synthesis",
                    "schema": openai_strict_json_schema(ResearchSynthesis),
                    "strict": True,
                }
            },
        )
        output = getattr(response, "output_text", None)
        if not isinstance(output, str):
            raise ResearchSynthesisError(
                "OpenAI research synthesizer returned no output"
            )
        try:
            return ResearchSynthesis.model_validate(json.loads(output))
        except (json.JSONDecodeError, ValidationError) as error:
            raise ResearchSynthesisError(
                "OpenAI research synthesizer returned invalid output"
            ) from error

    def _get_client(self) -> OpenAIAPIClient:
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise ValueError("OPENAI_API_KEY must be configured")
        from openai import OpenAI

        self._client = OpenAI(api_key=self._api_key)
        return self._client
