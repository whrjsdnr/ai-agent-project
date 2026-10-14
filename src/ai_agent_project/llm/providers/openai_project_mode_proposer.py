"""Strict OpenAI advisory mode proposer for project sessions."""

import json

from pydantic import ValidationError

from ai_agent_project.agent.project_session import (
    ProjectModeProposal,
    ProjectModeProposer,
)
from ai_agent_project.llm.config import ProviderConfig
from ai_agent_project.llm.providers.openai import OpenAIAPIClient
from ai_agent_project.llm.providers.structured_schema import openai_strict_json_schema
from ai_agent_project.llm.runtime import ConfiguredOpenAIProvider


class ProjectModeProposalError(ValueError):
    """Raised for malformed mode-proposal provider output."""


class OpenAIProjectModeProposer(ConfiguredOpenAIProvider, ProjectModeProposer):
    """Propose closed-vocabulary modes without activating any workflow."""

    def __init__(
        self,
        *,
        config: ProviderConfig | None = None,
        api_key: str | None = None,
        model: str | None = None,
        client: OpenAIAPIClient | None = None,
        request_timeout_seconds: float | None = None,
    ) -> None:
        if request_timeout_seconds is not None and request_timeout_seconds <= 0:
            raise ValueError("Project mode proposal timeout must be positive")
        self._configure(
            config=config,
            api_key=api_key,
            model=model,
            client=client,
            timeout_seconds=request_timeout_seconds,
        )

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
