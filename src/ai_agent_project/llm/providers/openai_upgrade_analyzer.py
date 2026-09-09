"""OpenAI structured-output provider for upgrade impact analysis."""

import json

from pydantic import ValidationError

from ai_agent_project.agent.codebase_analysis import CodebaseAnalysis
from ai_agent_project.agent.upgrade import (
    UpgradeAnalyzer,
    UpgradeRequest,
    UpgradeSpecification,
)
from ai_agent_project.agent.workspace import WorkspaceSnapshot
from ai_agent_project.llm.config import ProviderConfig
from ai_agent_project.llm.providers.openai import OpenAIAPIClient
from ai_agent_project.llm.providers.structured_schema import openai_strict_json_schema
from ai_agent_project.llm.runtime import ConfiguredOpenAIProvider

UPGRADE_ANALYZER_INSTRUCTIONS = "Translate an existing-system upgrade into measurable requirements. Preserve current supported behavior as constraints, identify impacts and regression risks, do not invent files, and use IDs such as UPG-REQ-001. Return only structured UpgradeSpecification output."


class UpgradeAnalysisError(ValueError):
    """Raised when an OpenAI response cannot become an UpgradeSpecification."""


class OpenAIUpgradeAnalyzer(ConfiguredOpenAIProvider, UpgradeAnalyzer):
    def __init__(
        self,
        *,
        config: ProviderConfig | None = None,
        request_timeout_seconds: float | None = None,
        api_key: str | None = None,
        model: str | None = None,
        client: OpenAIAPIClient | None = None,
    ) -> None:
        self._configure(
            config=config,
            api_key=api_key,
            model=model,
            client=client,
            timeout_seconds=request_timeout_seconds,
        )

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
