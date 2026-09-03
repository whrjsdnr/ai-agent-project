"""Strict OpenAI interpretation provider for user-supplied research results."""

import json
import os

from pydantic import ValidationError

from ai_agent_project.agent.research import (
    ResearchImplementationPlan,
    ResearchPlan,
    ResearchResultAnalysisPayload,
    ResearchResultSubmission,
)
from ai_agent_project.agent.research_planning import ResearchResultAnalyzer
from ai_agent_project.llm.providers.openai import DEFAULT_MODEL, OpenAIAPIClient
from ai_agent_project.llm.providers.structured_schema import openai_strict_json_schema


class ResearchResultAnalysisError(ValueError):
    """Raised for invalid structured interpretation output."""


class OpenAIResearchResultAnalyzer(ResearchResultAnalyzer):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        client: OpenAIAPIClient | None = None,
        request_timeout_seconds: float = 90.0,
    ) -> None:
        if request_timeout_seconds <= 0:
            raise ValueError("Research result analysis timeout must be positive")
        self._api_key = api_key or os.getenv("OPENAI_API_KEY")
        self._model = model or os.getenv("OPENAI_MODEL", DEFAULT_MODEL)
        self._client = client
        self._request_timeout_seconds = request_timeout_seconds

    def analyze(
        self,
        approved_plan: ResearchPlan,
        implementation_plan: ResearchImplementationPlan,
        submission: ResearchResultSubmission,
    ) -> ResearchResultAnalysisPayload:
        response = self._get_client().responses.create(
            model=self._model,
            instructions=(
                "Interpret only supplied user empirical results. Never execute anything and never "
                "infer, estimate, or fabricate measurements. Do not reproduce the authoritative "
                "submission or plans. Metrics marked not_measured must remain not_measured; missing "
                "success-criterion evidence is inconclusive. Evidence references may only use "
                "metric:<metric-id> or task:<task-id> from the supplied submission."
            ),
            input=[
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "approved_plan": approved_plan.model_dump(mode="json"),
                            "implementation_plan": implementation_plan.model_dump(
                                mode="json"
                            ),
                            "user_result_submission": submission.model_dump(
                                mode="json"
                            ),
                        }
                    ),
                }
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "research_result_analysis_payload",
                    "schema": openai_strict_json_schema(ResearchResultAnalysisPayload),
                    "strict": True,
                }
            },
        )
        output = getattr(response, "output_text", None)
        if not isinstance(output, str):
            raise ResearchResultAnalysisError(
                "OpenAI result analyzer returned no output"
            )
        try:
            return ResearchResultAnalysisPayload.model_validate(json.loads(output))
        except (json.JSONDecodeError, ValidationError) as error:
            raise ResearchResultAnalysisError(
                "OpenAI result analyzer returned invalid output"
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
