"""OpenAI structured-output analysis of a safe workspace inventory."""

import json

from pydantic import ValidationError

from ai_agent_project.agent.codebase_analysis import CodebaseAnalysis, CodebaseAnalyzer
from ai_agent_project.agent.workspace import WorkspaceSnapshot
from ai_agent_project.llm.config import ProviderConfig
from ai_agent_project.llm.providers.openai import OpenAIAPIClient
from ai_agent_project.llm.providers.structured_schema import openai_strict_json_schema
from ai_agent_project.llm.runtime import ConfiguredOpenAIProvider

CODEBASE_ANALYZER_INSTRUCTIONS = """Analyze only the workspace-relative file list
provided. Identify likely framework, structure, tests, dependencies, current features,
and safe extension points. Do not invent files absent from the snapshot. Return only
the structured CodebaseAnalysis output."""


class CodebaseAnalysisError(ValueError):
    """Raised when an OpenAI response cannot become CodebaseAnalysis."""


class OpenAICodebaseAnalyzer(ConfiguredOpenAIProvider, CodebaseAnalyzer):
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

    def analyze(self, workspace: WorkspaceSnapshot) -> CodebaseAnalysis:
        response = self._get_client().responses.create(
            model=self._model,
            instructions=CODEBASE_ANALYZER_INSTRUCTIONS,
            input=[
                {
                    "role": "user",
                    "content": json.dumps(workspace.model_dump(mode="json")),
                }
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "codebase_analysis",
                    "schema": openai_strict_json_schema(CodebaseAnalysis),
                    "strict": True,
                }
            },
        )
        output = getattr(response, "output_text", None)
        if not isinstance(output, str):
            raise CodebaseAnalysisError("OpenAI returned no codebase analysis")
        try:
            analysis = CodebaseAnalysis.model_validate(json.loads(output))
        except (json.JSONDecodeError, ValidationError) as error:
            raise CodebaseAnalysisError(
                "OpenAI returned invalid codebase analysis"
            ) from error
        known = set(workspace.files)
        referenced = (
            {path for component in analysis.components for path in component.files}
            | {item.path for item in analysis.important_files}
            | set(analysis.test_files)
            | set(analysis.config_files)
        )
        if not referenced <= known:
            raise CodebaseAnalysisError(
                "OpenAI analysis references files outside workspace snapshot"
            )
        return analysis
