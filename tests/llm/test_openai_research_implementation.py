"""Strict-output tests for generated-only implementation providers."""

import json
from types import SimpleNamespace
from typing import Any

import pytest

from ai_agent_project.agent.research import (
    RelatedStudy,
    ResearchArtifactType,
    ResearchDirection,
    ResearchDiscoveryReport,
    ResearchEvidence,
    ResearchGap,
    ResearchGeneratedArtifact,
    ResearchImplementationPackage,
    ResearchImplementationPlan,
    ResearchImplementationTask,
    ResearchMethodologyStep,
    ResearchMetric,
    ResearchObjective,
    ResearchPlan,
    ResearchQuestion,
    ResearchRequest,
    ResearchScope,
    ResearchSource,
)
from ai_agent_project.llm.providers.openai_research_implementation import (
    OpenAIResearchImplementationGenerator,
    OpenAIResearchImplementationPlanner,
    ResearchImplementationGenerationError,
)


class _Responses:
    def __init__(self, result: object | Exception) -> None:
        self.result = result
        self.requests: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> object:
        self.requests.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class _Client:
    def __init__(self, result: object | Exception) -> None:
        self.responses = _Responses(result)


def _context():
    direction = ResearchDirection(
        id="RD-1",
        title="D",
        research_question="Q",
        target_gap_ids=("G-1",),
        novelty="N",
        feasibility="F",
    )
    approved = ResearchPlan(
        id="P-1",
        selected_direction_id="RD-1",
        title="P",
        research_question="Q",
        objectives=(
            ResearchObjective(id="OBJ-1", description="O", direction_id="RD-1"),
        ),
        methodology=(
            ResearchMethodologyStep(
                id="METHOD-1", description="M", objective_ids=("OBJ-1",)
            ),
        ),
        metrics=(
            ResearchMetric(
                id="MET-1", name="Metric", description="D", measurement_method="Review"
            ),
        ),
    )
    report = ResearchDiscoveryReport(
        questions=(
            ResearchQuestion(
                id="Q-1",
                question="Q",
                rationale="R",
                source_scope=ResearchScope.EXTERNAL,
            ),
        ),
        sources=(
            ResearchSource(
                id="S-1", title="S", locator="https://example.org", source_type="web"
            ),
        ),
        evidence=(
            ResearchEvidence(
                id="E-1",
                source_id="S-1",
                question_id="Q-1",
                claim="C",
                support_text="S",
                evidence_type="citation",
            ),
        ),
        related_studies=(
            RelatedStudy(
                id="ST-1", title="ST", research_problem="P", evidence_ids=("E-1",)
            ),
        ),
        gaps=(
            ResearchGap(
                id="G-1",
                description="G",
                supporting_study_ids=("ST-1",),
                evidence_ids=("E-1",),
                importance="H",
                feasibility="F",
            ),
        ),
        directions=(direction,),
    )
    return (ResearchRequest(topic="Topic"), direction, approved, report)


def _implementation_plan() -> ResearchImplementationPlan:
    return ResearchImplementationPlan(
        selected_direction_id="RD-1",
        approved_plan_version=1,
        package_summary="Summary",
        tasks=(
            ResearchImplementationTask(
                task_id="TASK-1",
                title="T",
                description="D",
                objective_ids=("OBJ-1",),
                methodology_step_ids=("METHOD-1",),
                metric_ids=("MET-1",),
                expected_artifact_paths=("pkg/main.py",),
            ),
        ),
    )


def _package(plan: ResearchImplementationPlan) -> ResearchImplementationPackage:
    return ResearchImplementationPackage(
        implementation_plan=plan,
        execution_guide="Generated only; not executed.",
        artifacts=(
            ResearchGeneratedArtifact(
                artifact_id="ART-1",
                task_id="TASK-1",
                relative_path="pkg/main.py",
                artifact_type=ResearchArtifactType.SOURCE,
                content="x",
                objective_ids=("OBJ-1",),
                methodology_step_ids=("METHOD-1",),
                metric_ids=("MET-1",),
            ),
        ),
    )


def _package_payload() -> dict[str, object]:
    return {
        "artifacts": [
            {
                "task_id": "TASK-1",
                "relative_path": "pkg/main.py",
                "artifact_type": "source",
                "content": "x",
            }
        ],
        "execution_guide": "Generated only; not executed.",
        "environment_assumptions": [],
        "unresolved_user_inputs": [],
        "warnings": [],
    }


def test_implementation_planner_uses_strict_schema_and_validates_refs() -> None:
    request, direction, approved, report = _context()
    client = _Client(
        SimpleNamespace(
            output_text=json.dumps(_implementation_plan().model_dump(mode="json"))
        )
    )
    provider = OpenAIResearchImplementationPlanner(client=client, model="test")

    plan = provider.plan(request, direction, approved, 1, report)

    assert plan.selected_direction_id == "RD-1"
    schema = client.responses.requests[0]["text"]["format"]["schema"]
    assert schema["required"] == list(schema["properties"])


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update({"selected_direction_id": "wrong"}),
        lambda value: value.update({"approved_plan_version": 9}),
        lambda value: value["tasks"][0].update({"objective_ids": ["missing"]}),
    ],
)
def test_implementation_planner_rejects_wrong_authoritative_context(mutate) -> None:
    request, direction, approved, report = _context()
    payload = _implementation_plan().model_dump(mode="json")
    mutate(payload)
    provider = OpenAIResearchImplementationPlanner(
        client=_Client(SimpleNamespace(output_text=json.dumps(payload))), model="test"
    )
    with pytest.raises(ResearchImplementationGenerationError):
        provider.plan(request, direction, approved, 1, report)


def test_implementation_generator_composes_authoritative_plan_from_payload() -> None:
    request, direction, approved, report = _context()
    plan = _implementation_plan()
    payload = _package_payload()
    provider = OpenAIResearchImplementationGenerator(
        client=_Client(SimpleNamespace(output_text=json.dumps(payload))), model="test"
    )

    package = provider.generate(request, direction, approved, plan, report)

    assert package.implementation_plan is plan
    assert package.artifacts[0].artifact_id == "ART-1"
    assert package.artifacts[0].objective_ids == ("OBJ-1",)
    assert package.generated_not_executed is True
    schema = provider._client.responses.requests[0]["text"]["format"]["schema"]
    assert "implementation_plan" not in schema["properties"]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["artifacts"][0].update({"task_id": "missing"}),
        lambda value: value["artifacts"][0].update({"relative_path": "other.py"}),
    ],
)
def test_implementation_generator_rejects_invalid_artifact_payload(mutate) -> None:
    request, direction, approved, report = _context()
    plan = _implementation_plan()
    payload = _package_payload()
    mutate(payload)
    provider = OpenAIResearchImplementationGenerator(
        client=_Client(SimpleNamespace(output_text=json.dumps(payload))), model="test"
    )
    with pytest.raises(ResearchImplementationGenerationError):
        provider.generate(request, direction, approved, plan, report)


def test_implementation_generator_propagates_provider_failure() -> None:
    request, direction, approved, report = _context()
    plan = _implementation_plan()
    failure = OpenAIResearchImplementationGenerator(
        client=_Client(RuntimeError("down")), model="test"
    )
    with pytest.raises(RuntimeError, match="down"):
        failure.generate(request, direction, approved, plan, report)


def test_implementation_package_model_is_generated_only() -> None:
    payload = _package(_implementation_plan()).model_dump(mode="json")
    payload["generated_not_executed"] = False
    with pytest.raises(ValueError, match="generated only"):
        ResearchImplementationPackage.model_validate(payload)
