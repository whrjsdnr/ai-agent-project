"""Strict OpenAI advisory mode proposer for project sessions."""

import json
import os

from pydantic import ValidationError

from ai_agent_project.agent.project_session import (
    ProjectModeProposal,
    ProjectModeProposer,
)
from ai_agent_project.llm.providers.openai import DEFAULT_MODEL, OpenAIAPIClient
from ai_agent_project.llm.providers.structured_schema import openai_strict_json_schema


class ProjectModeProposalError(ValueError):
    """Raised for malformed mode-proposal provider output."""


class OpenAIProjectModeProposer(ProjectModeProposer):
    """Propose closed-vocabulary modes without activating any workflow."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        client: OpenAIAPIClient | None = None,
        request_timeout_seconds: float = 30.0,
    ) -> None:
        if request_timeout_seconds <= 0:
            raise ValueError("Project mode proposal timeout must be positive")
        self._api_key = api_key or os.getenv("OPENAI_API_KEY")
        self._model = model or os.getenv("OPENAI_MODEL", DEFAULT_MODEL)
        self._client = client
        self._request_timeout_seconds = request_timeout_seconds

    def propose(self, original_request: str) -> ProjectModeProposal:
        response = self._get_client().responses.create(
            model=self._model,
            instructions=(
                "Propose, but never activate, a project mode. Work mode is exactly one "
                "of developer, researcher, hybrid. Project mode is independently exactly "
                "one of new, upgrade. Return a concise rationale."
            ),
            input=[{"role": "user", "content": original_request}],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "project_mode_proposal",
                    "schema": openai_strict_json_schema(ProjectModeProposal),
                    "strict": True,
                }
            },
        )
        output = getattr(response, "output_text", None)
        if not isinstance(output, str):
            raise ProjectModeProposalError("OpenAI mode proposer returned no output")
        try:
            return ProjectModeProposal.model_validate(json.loads(output))
        except (json.JSONDecodeError, ValidationError) as error:
            raise ProjectModeProposalError(
                "OpenAI mode proposer returned invalid output"
            ) from error

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
