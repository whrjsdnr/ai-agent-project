"""Tests for OpenAI project-plan revision without network requests."""

import json
from types import SimpleNamespace
from typing import Any

import pytest

from ai_agent_project.agent.plan import ImplementationPlan
from ai_agent_project.agent.project import (
    ProjectPhase,
    ProjectPlan,
    ProjectSpecification,
)
from ai_agent_project.agent.specification import Specification
from ai_agent_project.agent.workspace import WorkspaceSnapshot
from ai_agent_project.llm.providers.openai_project_plan_reviser import (
    OpenAIProjectPlanReviser,
    ProjectPlanRevisionError,
)


class FakeResponses:
    def __init__(self, response: object) -> None:
        self.response = response
        self.requests: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> object:
        self.requests.append(kwargs)
        return self.response


class FakeClient:
    def __init__(self, response: object) -> None:
        self.responses = FakeResponses(response)


def make_specification() -> ProjectSpecification:
    specification = Specification.model_validate(
        {"requirements": [{"id": "REQ-001", "description": "Build feature."}]}
    )
    return ProjectSpecification.from_specification(specification)


def make_plan() -> ProjectPlan:
    implementation_plan = ImplementationPlan.model_validate(
        {
            "tasks": [
                {
                    "id": "TASK-001",
                    "title": "Build",
                    "description": "Build feature.",
                    "requirement_ids": ["REQ-001"],
                    "files_to_inspect": ["src/example.py"],
                    "files_to_modify": ["src/example.py"],
                }
            ],
            "validation_commands": ["uv run pytest"],
        }
    )
    return ProjectPlan(
        project_title="Demo",
        phases=(
            ProjectPhase(
                id="PHASE-001",
                title="Build",
                objective="Build feature.",
                requirement_ids=("REQ-001",),
                task_ids=("TASK-001",),
            ),
        ),
        implementation_plan=implementation_plan,
    )


def test_reviser_uses_strict_schema_and_preserves_implementation_plan() -> None:
    current_plan = make_plan()
    revised = current_plan.model_copy(
        update={
            "phases": (
                current_plan.phases[0].model_copy(update={"title": "Clear build"}),
            )
        }
    )
    client = FakeClient(
        SimpleNamespace(output_text=json.dumps(revised.model_dump(mode="json")))
    )
    reviser = OpenAIProjectPlanReviser(client=client, model="test-model")
    workspace = WorkspaceSnapshot(files=["src/example.py"])

    result = reviser.revise(
        make_specification(), current_plan, "Clarify phases.", workspace
    )

    assert result == revised
    request = client.responses.requests[0]
    assert request["text"]["format"]["strict"] is True
    assert "Preserve the supplied ImplementationPlan exactly" in request["instructions"]
    assert "Clarify phases." in request["input"][0]["content"]
    assert "TASK-001" in request["input"][0]["content"]
    assert "src/example.py" in request["input"][0]["content"]


@pytest.mark.parametrize("output", ["{broken", None])
def test_reviser_rejects_malformed_output(output: str | None) -> None:
    reviser = OpenAIProjectPlanReviser(
        client=FakeClient(SimpleNamespace(output_text=output)), model="test-model"
    )

    with pytest.raises(ProjectPlanRevisionError):
        reviser.revise(make_specification(), make_plan(), "Clarify phases.")


def test_reviser_rejects_changed_implementation_plan() -> None:
    current_plan = make_plan()
    raw = current_plan.model_dump(mode="json")
    raw["implementation_plan"]["tasks"][0]["description"] = "Changed task"
    reviser = OpenAIProjectPlanReviser(
        client=FakeClient(SimpleNamespace(output_text=json.dumps(raw))),
        model="test-model",
    )

    with pytest.raises(ProjectPlanRevisionError, match="failed validation"):
        reviser.revise(make_specification(), current_plan, "Clarify phases.")
