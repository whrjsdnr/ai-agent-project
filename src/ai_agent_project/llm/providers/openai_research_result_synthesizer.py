"""Strict, interpretation-only OpenAI provider for post-result synthesis."""

import json
import os

from pydantic import ValidationError

from ai_agent_project.agent.research import (
    ResearchDirection,
    ResearchImplementationPlan,
    ResearchPlan,
    ResearchResultAnalysis,
    ResearchResultSubmission,
    ResearchSynthesisPayload,
)
from ai_agent_project.agent.research_planning import ResearchResultSynthesizer
from ai_agent_project.llm.providers.openai import DEFAULT_MODEL, OpenAIAPIClient
from ai_agent_project.llm.providers.structured_schema import openai_strict_json_schema


class ResearchResultSynthesisError(ValueError):
    pass


class OpenAIResearchResultSynthesizer(ResearchResultSynthesizer):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        client: OpenAIAPIClient | None = None,
        request_timeout_seconds: float = 90.0,
    ) -> None:
        if request_timeout_seconds <= 0:
            raise ValueError("Research synthesis timeout must be positive")
        self._api_key = api_key or os.getenv("OPENAI_API_KEY")
        self._model = model or os.getenv("OPENAI_MODEL", DEFAULT_MODEL)
        self._client = client
        self._request_timeout_seconds = request_timeout_seconds

    def synthesize(
        self,
        direction: ResearchDirection,
        approved_plan: ResearchPlan,
        implementation_plan: ResearchImplementationPlan,
        submission: ResearchResultSubmission,
        analysis: ResearchResultAnalysis,
    ) -> ResearchSynthesisPayload:
        allowed_typed_ids = {
            "objective_ids": tuple(
                sorted(item.id for item in approved_plan.objectives)
            ),
            "task_ids": tuple(
                sorted(item.task_id for item in implementation_plan.tasks)
            ),
            "metric_ids": tuple(sorted(item.id for item in approved_plan.metrics)),
            "analysis_finding_ids": tuple(
                sorted(item.finding_id for item in analysis.findings)
            ),
        }
        allowed_evidence_refs = tuple(
            sorted(
                {
                    *(f"task:{item.task_id}" for item in submission.task_results),
                    *(
                        f"metric:{item.metric_id}"
                        for item in submission.metric_observations
                    ),
                    *(f"finding:{item.finding_id}" for item in analysis.findings),
                }
            )
        )
        response = self._get_client().responses.create(
            model=self._model,
            instructions=(
                "Synthesize only supplied empirical results and analysis. Never execute "
                "anything, invent measurements, generalize unsupported claims, or recreate "
                "authoritative plans/results. Label missing evidence and limitations "
                "conservatively. Use only supplied IDs. Allowed raw typed IDs are: "
                f"{json.dumps(allowed_typed_ids)}. Allowed namespaced evidence_refs are: "
                f"{json.dumps(allowed_evidence_refs)}. Use empty lists where a claim has no "
                "applicable reference. Never invent or derive IDs. Typed fields use raw IDs "
                "only (for example M in metric_ids); evidence_refs use only the supplied "
                "namespaced values (for example metric:M)."
            ),
            input=[
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "direction": direction.model_dump(mode="json"),
                            "approved_plan": approved_plan.model_dump(mode="json"),
                            "implementation_plan": implementation_plan.model_dump(
                                mode="json"
                            ),
                            "submission": submission.model_dump(mode="json"),
                            "analysis": analysis.model_dump(mode="json"),
                            "allowed_typed_ids": allowed_typed_ids,
                            "allowed_evidence_refs": allowed_evidence_refs,
                        }
                    ),
                }
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "research_synthesis_payload",
                    "schema": openai_strict_json_schema(ResearchSynthesisPayload),
                    "strict": True,
                }
            },
        )
        output = getattr(response, "output_text", None)
        if not isinstance(output, str):
            raise ResearchResultSynthesisError(
                "OpenAI synthesis provider returned no output"
            )
        try:
            return ResearchSynthesisPayload.model_validate(json.loads(output))
        except (json.JSONDecodeError, ValidationError) as error:
            raise ResearchResultSynthesisError(
                "OpenAI synthesis provider returned invalid output"
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
