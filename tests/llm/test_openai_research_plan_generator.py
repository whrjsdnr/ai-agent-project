"""Offline contract tests for strict OpenAI research-plan generation."""

import json
from types import SimpleNamespace
from typing import Any

import pytest

from ai_agent_project.agent.research import (
    RelatedStudy,
    ResearchDirection,
    ResearchDiscoveryReport,
    ResearchEvidence,
    ResearchGap,
    ResearchQuestion,
    ResearchRequest,
    ResearchScope,
    ResearchSource,
)
from ai_agent_project.llm.providers.openai_research_plan_generator import (
    OpenAIResearchPlanGenerator,
    ResearchPlanGenerationError,
)


class _Responses:
    def __init__(self, response: object | Exception) -> None:
        self._response = response
        self.requests: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> object:
        self.requests.append(kwargs)
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


class _Client:
    def __init__(self, response: object | Exception) -> None:
        self.responses = _Responses(response)


def _context() -> tuple[ResearchRequest, ResearchDirection, ResearchDiscoveryReport]:
    direction = ResearchDirection(
        id="RD-1",
        title="Direction",
        research_question="Question?",
        target_gap_ids=("G-1",),
        novelty="Novel",
        feasibility="Feasible",
    )
    report = ResearchDiscoveryReport(
        questions=(
            ResearchQuestion(
                id="Q-1",
                question="Question?",
                rationale="Rationale",
                source_scope=ResearchScope.EXTERNAL,
            ),
        ),
        sources=(
            ResearchSource(
                id="S-1",
                title="Source",
                locator="https://example.org/source",
                source_type="web",
            ),
        ),
        evidence=(
            ResearchEvidence(
                id="E-1",
                source_id="S-1",
                question_id="Q-1",
                claim="Claim",
                support_text="Excerpt",
                evidence_type="citation",
            ),
        ),
        related_studies=(
            RelatedStudy(
                id="ST-1",
                title="Study",
                research_problem="Problem",
                evidence_ids=("E-1",),
            ),
        ),
        gaps=(
            ResearchGap(
                id="G-1",
                description="Gap",
                supporting_study_ids=("ST-1",),
                evidence_ids=("E-1",),
                importance="High",
                feasibility="Feasible",
            ),
        ),
        directions=(direction,),
    )
    return ResearchRequest(topic="Planning topic"), direction, report


def _plan_payload(**updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": "PLAN-1",
        "selected_direction_id": "RD-1",
        "title": "Plan",
        "research_question": "Question?",
        "objectives": [
            {"id": "OBJ-1", "description": "Objective", "direction_id": "RD-1"}
        ],
        "hypotheses": [],
        "methodology": [
            {"id": "M-1", "description": "Method", "objective_ids": ["OBJ-1"]}
        ],
        "metrics": [
            {
                "id": "MET-1",
                "name": "Quality",
                "description": "Qualitative assessment",
                "measurement_method": "Expert review",
            }
        ],
        "success_criteria": [
            {
                "id": "SC-1",
                "metric_id": "MET-1",
                "target_description": "A useful qualitative outcome",
                "rationale": "Exploratory research",
            }
        ],
    }
    payload.update(updates)
    return payload


def _generator(
    payload: object | Exception,
) -> tuple[OpenAIResearchPlanGenerator, _Client]:
    response = (
        payload
        if isinstance(payload, Exception)
        else SimpleNamespace(output_text=json.dumps(payload))
    )
    client = _Client(response)
    return OpenAIResearchPlanGenerator(client=client, model="test-model"), client


def test_strict_plan_generator_accepts_qualitative_plan_with_zero_hypotheses() -> None:
    generator, client = _generator(_plan_payload())
    request, direction, report = _context()

    plan = generator.generate(request, direction, report)

    assert plan.selected_direction_id == direction.id
    assert plan.hypotheses == ()
    assert plan.success_criteria[0].target_description.startswith("A useful")
    schema = client.responses.requests[0]["text"]["format"]["schema"]
    assert schema["required"] == list(schema["properties"])


@pytest.mark.parametrize(
    "updates",
    [
        {"selected_direction_id": "RD-other"},
        {
            "objectives": [
                {"id": "OBJ-1", "description": "a", "direction_id": "RD-1"},
                {"id": "OBJ-1", "description": "b", "direction_id": "RD-1"},
            ]
        },
        {
            "hypotheses": [
                {"id": "H-1", "statement": "a"},
                {"id": "H-1", "statement": "b"},
            ]
        },
        {
            "methodology": [
                {"id": "M-1", "description": "a"},
                {"id": "M-1", "description": "b"},
            ]
        },
        {
            "metrics": [
                {
                    "id": "MET-1",
                    "name": "a",
                    "description": "a",
                    "measurement_method": "a",
                },
                {
                    "id": "MET-1",
                    "name": "b",
                    "description": "b",
                    "measurement_method": "b",
                },
            ]
        },
        {
            "success_criteria": [
                {
                    "id": "SC-1",
                    "metric_id": "unknown",
                    "target_description": "x",
                    "rationale": "x",
                }
            ]
        },
        {
            "methodology": [
                {"id": "M-1", "description": "Method", "objective_ids": ["unknown"]}
            ]
        },
    ],
)
def test_strict_plan_generator_rejects_invalid_structured_plan(
    updates: dict[str, object],
) -> None:
    generator, _ = _generator(_plan_payload(**updates))
    request, direction, report = _context()

    with pytest.raises(ResearchPlanGenerationError):
        generator.generate(request, direction, report)


@pytest.mark.parametrize("output", ["not json", None])
def test_strict_plan_generator_rejects_malformed_output(output: str | None) -> None:
    response = SimpleNamespace(output_text=output)
    generator = OpenAIResearchPlanGenerator(client=_Client(response), model="test")
    request, direction, report = _context()

    with pytest.raises(ResearchPlanGenerationError):
        generator.generate(request, direction, report)


def test_strict_plan_generator_propagates_provider_failure() -> None:
    generator, _ = _generator(RuntimeError("provider unavailable"))
    request, direction, report = _context()

    with pytest.raises(RuntimeError, match="provider unavailable"):
        generator.generate(request, direction, report)
