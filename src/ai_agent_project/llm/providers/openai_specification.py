"""OpenAI Responses structured-output parser for specifications."""

import json
import os

from pydantic import ValidationError

from ai_agent_project.agent.specification import Specification
from ai_agent_project.agent.specification_parser import (
    SPECIFICATION_PARSER_INSTRUCTIONS,
    SpecificationParseError,
    SpecificationParser,
    validate_specification_text,
)
from ai_agent_project.llm.providers.openai import (
    DEFAULT_MODEL,
    OpenAIAPIClient,
)
from ai_agent_project.llm.providers.structured_schema import openai_strict_json_schema


class OpenAISpecificationParser(SpecificationParser):
    """Parse text with OpenAI Responses JSON-schema structured output."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        client: OpenAIAPIClient | None = None,
    ) -> None:
        self._model = model or os.getenv("OPENAI_MODEL", DEFAULT_MODEL)
        self._client = client
        self._api_key = api_key or os.getenv("OPENAI_API_KEY")

    def parse(self, text: str) -> Specification:
        """Request and validate one structured specification without tool calls."""
        source_text = validate_specification_text(text)
        response = self._get_client().responses.create(
            model=self._model,
            instructions=SPECIFICATION_PARSER_INSTRUCTIONS,
            input=[{"role": "user", "content": source_text}],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "specification",
                    "schema": openai_strict_json_schema(Specification),
                    "strict": True,
                }
            },
        )
        output_text = getattr(response, "output_text", None)
        if not isinstance(output_text, str):
            raise SpecificationParseError("OpenAI returned no structured specification")

        try:
            parsed = json.loads(output_text)
        except json.JSONDecodeError as error:
            raise SpecificationParseError(
                "OpenAI returned invalid specification JSON"
            ) from error

        try:
            return Specification.model_validate(parsed)
        except ValidationError as error:
            raise SpecificationParseError(
                "OpenAI returned a specification that failed validation"
            ) from error

    def _get_client(self) -> OpenAIAPIClient:
        """Create the SDK client only when parsing needs it."""
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise ValueError("OPENAI_API_KEY must be configured")

        from openai import OpenAI

        self._client = OpenAI(api_key=self._api_key)
        return self._client
