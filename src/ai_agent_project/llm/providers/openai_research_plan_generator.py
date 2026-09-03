"""OpenAI strict structured-output provider for planning after direction selection."""

import json
import os

from pydantic import ValidationError

from ai_agent_project.agent.research import (
    ResearchDirection,
    ResearchDiscoveryReport,
    ResearchPlan,
    ResearchRequest,
)
from ai_agent_project.agent.research_planning import ResearchPlanGenerator
from ai_agent_project.llm.providers.openai import DEFAULT_MODEL, OpenAIAPIClient
from ai_agent_project.llm.providers.structured_schema import openai_strict_json_schema

_INSTRUCTIONS = (
    "Create a planning-only research plan for the supplied authoritative selected direction. "
    "Use its ID exactly; do not replace the direction. Use only supplied gap, study, and "
    "evidence context. IDs must be nonblank and unique. Objectives must reference the selected "
    "direction; internal references must resolve. Qualitative metrics and zero hypotheses are valid. "
    "Do not include research execution, code, shell commands, or workspace changes."
)


class ResearchPlanGenerationError(ValueError):
    """Raised when structured research-plan output is invalid."""


class OpenAIResearchPlanGenerator(ResearchPlanGenerator):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        client: OpenAIAPIClient | None = None,
        request_timeout_seconds: float = 90.0,
    ) -> None:
        if request_timeout_seconds <= 0:
            raise ValueError("Research plan request timeout must be positive")
        self._model = model or os.getenv("OPENAI_MODEL", DEFAULT_MODEL)
        self._api_key = api_key or os.getenv("OPENAI_API_KEY")
        self._client = client
        self._request_timeout_seconds = request_timeout_seconds

    def generate(
        self,
        request: ResearchRequest,
        direction: ResearchDirection,
        report: ResearchDiscoveryReport,
        *,
        revision_note: str | None = None,
    ) -> ResearchPlan:
        response = self._get_client().responses.create(
            model=self._model,
            instructions=_INSTRUCTIONS,
            input=[
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "request": request.model_dump(mode="json"),
                            "selected_direction": direction.model_dump(mode="json"),
                            "report": report.model_dump(mode="json"),
                            "revision_note": revision_note,
                        }
                    ),
                }
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "research_plan",
                    "schema": openai_strict_json_schema(ResearchPlan),
                    "strict": True,
                }
            },
        )
        output = getattr(response, "output_text", None)
        if not isinstance(output, str):
            raise ResearchPlanGenerationError(
                "OpenAI research plan generator returned no output"
            )
        try:
            plan = ResearchPlan.model_validate(json.loads(output))
        except (json.JSONDecodeError, ValidationError) as error:
            raise ResearchPlanGenerationError(
                "OpenAI research plan generator returned invalid output"
            ) from error
        if plan.selected_direction_id != direction.id:
            raise ResearchPlanGenerationError(
                "OpenAI research plan changed the selected direction"
            )
        if direction.id not in {item.id for item in report.directions}:
            raise ResearchPlanGenerationError(
                "Selected direction is absent from discovery report"
            )
        return plan

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
