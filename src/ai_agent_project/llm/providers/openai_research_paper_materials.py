"""Strict OpenAI generator for structured, non-manuscript paper materials."""

import json
import os

from pydantic import ValidationError

from ai_agent_project.agent.research import (
    ResearchDirection,
    ResearchDiscoveryReport,
    ResearchImplementationPlan,
    ResearchPaperMaterialsPayload,
    ResearchPlan,
    ResearchResultAnalysis,
    ResearchResultSubmission,
    ResearchResultSynthesis,
)
from ai_agent_project.agent.research_planning import ResearchPaperMaterialsGenerator
from ai_agent_project.llm.providers.openai import DEFAULT_MODEL, OpenAIAPIClient
from ai_agent_project.llm.providers.structured_schema import openai_strict_json_schema


class ResearchPaperMaterialsError(ValueError):
    """Raised for invalid structured paper-material output."""


class OpenAIResearchPaperMaterialsGenerator(ResearchPaperMaterialsGenerator):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        client: OpenAIAPIClient | None = None,
        request_timeout_seconds: float = 90.0,
    ) -> None:
        if request_timeout_seconds <= 0:
            raise ValueError("Research paper materials timeout must be positive")
        self._api_key = api_key or os.getenv("OPENAI_API_KEY")
        self._model = model or os.getenv("OPENAI_MODEL", DEFAULT_MODEL)
        self._client = client
        self._request_timeout_seconds = request_timeout_seconds

    def generate(
        self,
        direction: ResearchDirection,
        report: ResearchDiscoveryReport,
        approved_plan: ResearchPlan,
        implementation_plan: ResearchImplementationPlan,
        submission: ResearchResultSubmission,
        analysis: ResearchResultAnalysis,
        synthesis: ResearchResultSynthesis,
    ) -> ResearchPaperMaterialsPayload:
        allowed = {
            "objective_ids": sorted(item.id for item in approved_plan.objectives),
            "task_ids": sorted(item.task_id for item in implementation_plan.tasks),
            "metric_ids": sorted(item.id for item in approved_plan.metrics),
            "source_ids": sorted(item.id for item in report.sources),
            "synthesis_claim_ids": sorted(
                item.claim_id
                for item in (
                    *synthesis.major_findings,
                    *synthesis.inconclusive_findings,
                    *synthesis.negative_findings,
                    *synthesis.research_contributions,
                )
            ),
            "analysis_finding_ids": sorted(
                item.finding_id for item in analysis.findings
            ),
        }
        evidence_refs = sorted(
            {
                *(f"task:{item.task_id}" for item in submission.task_results),
                *(
                    f"metric:{item.metric_id}"
                    for item in submission.metric_observations
                ),
                *(f"finding:{item.finding_id}" for item in analysis.findings),
            }
        )
        response = self._get_client().responses.create(
            model=self._model,
            instructions=(
                "Generate structured research paper-support materials only, not an abstract, "
                "introduction, related-work, methods, results, discussion, conclusion, or full "
                "manuscript. Never execute anything or invent empirical values. Do not recreate "
                "authoritative state. Use only supplied raw IDs: "
                f"{json.dumps(allowed)}. Evidence refs may only be: {json.dumps(evidence_refs)}. "
                "Use empty lists when no reference applies. Mark unsupported claims as prohibited "
                "rather than converting missing evidence into a result."
            ),
            input=[
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "direction": direction.model_dump(mode="json"),
                            "report": report.model_dump(mode="json"),
                            "approved_plan": approved_plan.model_dump(mode="json"),
                            "implementation_plan": implementation_plan.model_dump(
                                mode="json"
                            ),
                            "submission": submission.model_dump(mode="json"),
                            "analysis": analysis.model_dump(mode="json"),
                            "synthesis": synthesis.model_dump(mode="json"),
                            "allowed": allowed,
                            "allowed_evidence_refs": evidence_refs,
                        }
                    ),
                }
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "research_paper_materials_payload",
                    "schema": openai_strict_json_schema(ResearchPaperMaterialsPayload),
                    "strict": True,
                }
            },
        )
        output = getattr(response, "output_text", None)
        if not isinstance(output, str):
            raise ResearchPaperMaterialsError(
                "OpenAI paper materials provider returned no output"
            )
        try:
            return ResearchPaperMaterialsPayload.model_validate(json.loads(output))
        except (json.JSONDecodeError, ValidationError) as error:
            raise ResearchPaperMaterialsError(
                "OpenAI paper materials provider returned invalid output"
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
