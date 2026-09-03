"""OpenAI structured-output provider for upgrade impact analysis."""

import json
import os

from pydantic import ValidationError

from ai_agent_project.agent.codebase_analysis import CodebaseAnalysis
from ai_agent_project.agent.upgrade import (
    UpgradeAnalyzer,
    UpgradeRequest,
    UpgradeSpecification,
)
from ai_agent_project.agent.workspace import WorkspaceSnapshot
from ai_agent_project.llm.providers.openai import DEFAULT_MODEL, OpenAIAPIClient
from ai_agent_project.llm.providers.structured_schema import openai_strict_json_schema

UPGRADE_ANALYZER_INSTRUCTIONS = "Translate an existing-system upgrade into measurable requirements. Preserve current supported behavior as constraints, identify impacts and regression risks, do not invent files, and use IDs such as UPG-REQ-001. Return only structured UpgradeSpecification output."


class UpgradeAnalysisError(ValueError):
    """Raised when an OpenAI response cannot become an UpgradeSpecification."""


class OpenAIUpgradeAnalyzer(UpgradeAnalyzer):
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

    def analyze(
        self,
        codebase: CodebaseAnalysis,
        request: UpgradeRequest,
        workspace: WorkspaceSnapshot | None = None,
    ) -> UpgradeSpecification:
        response = self._get_client().responses.create(
            model=self._model,
            instructions=UPGRADE_ANALYZER_INSTRUCTIONS,
            input=[
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "codebase": codebase.model_dump(mode="json"),
                            "request": request.model_dump(mode="json"),
                            "workspace": workspace.model_dump(mode="json")
                            if workspace
                            else None,
                        }
                    ),
                }
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "upgrade_specification",
                    "schema": openai_strict_json_schema(UpgradeSpecification),
                    "strict": True,
                }
            },
        )
        output = getattr(response, "output_text", None)
        if not isinstance(output, str):
            raise UpgradeAnalysisError("OpenAI returned no upgrade specification")
        try:
            return UpgradeSpecification.model_validate(json.loads(output))
        except (json.JSONDecodeError, ValidationError) as error:
            raise UpgradeAnalysisError(
                "OpenAI returned invalid upgrade specification"
            ) from error

    def _get_client(self) -> OpenAIAPIClient:
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise ValueError("OPENAI_API_KEY must be configured")
        from openai import OpenAI

        self._client = OpenAI(api_key=self._api_key)
        return self._client
