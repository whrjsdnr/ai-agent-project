"""Tests for OpenAI project milestone planning without network requests."""

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
from ai_agent_project.llm.providers.openai_project_planner import (
    OpenAIProjectPlanner,
    ProjectPlanningError,
)


class FakeResponsesAPI:
    def __init__(self, responses: list[object]) -> None:
        self._responses = responses
        self.requests: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> object:
        self.requests.append(kwargs)
        return self._responses.pop(0)


class FakeOpenAIAPIClient:
    def __init__(self, responses: list[object]) -> None:
        self.responses = FakeResponsesAPI(responses)


def make_project_specification() -> ProjectSpecification:
    specification = Specification.model_validate(
        {
            "project_name": "Demo project",
            "summary": "Deliver the feature.",
            "requirements": [
                {
                    "id": "REQ-001",
                    "description": "Implement the feature.",
                    "acceptance_criteria": ["The feature works."],
                },
                {
                    "id": "REQ-002",
                    "description": "Test the feature.",
                    "acceptance_criteria": ["All tests pass."],
                },
            ],
            "constraints": ["Python 3.12"],
        }
    )
    return ProjectSpecification.from_specification(specification).model_copy(
        update={"acceptance_criteria": ("The project is accepted.",)}
    )


def make_implementation_plan() -> ImplementationPlan:
    return ImplementationPlan.model_validate(
        {
            "summary": "Implement and validate the feature.",
            "tasks": [
                {
                    "id": "TASK-001",
                    "title": "Implement",
                    "description": "Implement the feature.",
                    "requirement_ids": ["REQ-001"],
                    "files_to_inspect": ["src/example.py"],
                    "files_to_modify": ["src/example.py"],
                },
                {
                    "id": "TASK-002",
                    "title": "Test",
                    "description": "Test the feature.",
                    "requirement_ids": ["REQ-002"],
                    "depends_on": ["TASK-001"],
                    "files_to_inspect": ["tests/test_example.py"],
                    "files_to_modify": ["tests/test_example.py"],
                },
            ],
            "validation_commands": ["uv run pytest"],
        }
    )


def make_project_plan_data() -> dict[str, Any]:
    plan = ProjectPlan(
        project_title="Demo project",
        phases=(
            ProjectPhase(
                id="PHASE-001",
                title="Implementation",
                objective="Implement the feature.",
                requirement_ids=("REQ-001",),
                task_ids=("TASK-001",),
                acceptance_criteria=("The implementation is complete.",),
            ),
            ProjectPhase(
                id="PHASE-002",
                title="Validation",
                objective="Validate the feature.",
                requirement_ids=("REQ-002",),
                task_ids=("TASK-002",),
                depends_on=("PHASE-001",),
                acceptance_criteria=("Tests pass.",),
            ),
        ),
        implementation_plan=make_implementation_plan(),
    )
    return plan.model_dump(mode="json")


def test_openai_project_planner_uses_strict_schema_and_workspace_context() -> None:
    fake_client = FakeOpenAIAPIClient(
        [SimpleNamespace(output_text=json.dumps(make_project_plan_data()))]
    )
    planner = OpenAIProjectPlanner(client=fake_client, model="test-model")
    workspace = WorkspaceSnapshot(
        files=["src/example.py", "tests/test_example.py"], truncated=True
    )

    result = planner.plan(
        make_project_specification(), make_implementation_plan(), workspace
    )

    assert result.phases[1].depends_on == ("PHASE-001",)
    request = fake_client.responses.requests[0]
    assert request["model"] == "test-model"
    assert request["text"]["format"]["type"] == "json_schema"
    assert request["text"]["format"]["name"] == "project_plan"
    assert request["text"]["format"]["strict"] is True
    assert "Do not\ninvent task IDs" in request["instructions"]
    assert "exactly\none phase" in request["instructions"]

    prompt = request["input"][0]["content"]
    for expected in (
        "REQ-001",
        "REQ-002",
        "TASK-001",
        "TASK-002",
        "src/example.py",
        "tests/test_example.py",
        "uv run pytest",
        "The project is accepted.",
        '"truncated": true',
    ):
        assert expected in prompt

    schema = request["text"]["format"]["schema"]
    assert schema["required"] == list(schema["properties"])
    assert schema["additionalProperties"] is False
    phase = schema["$defs"]["ProjectPhase"]
    assert phase["required"] == list(phase["properties"])
    assert phase["additionalProperties"] is False


def test_openai_project_planner_marks_workspace_unavailable_when_omitted() -> None:
    fake_client = FakeOpenAIAPIClient(
        [SimpleNamespace(output_text=json.dumps(make_project_plan_data()))]
    )
    planner = OpenAIProjectPlanner(client=fake_client, model="test-model")

    planner.plan(make_project_specification(), make_implementation_plan())

    prompt = fake_client.responses.requests[0]["input"][0]["content"]
    assert '"workspace": null' in prompt


def test_openai_project_planner_rejects_unknown_task_from_structured_output() -> None:
    raw_project_plan = make_project_plan_data()
    raw_project_plan["phases"][1]["task_ids"] = ["TASK-999"]
    planner = OpenAIProjectPlanner(
        client=FakeOpenAIAPIClient(
            [SimpleNamespace(output_text=json.dumps(raw_project_plan))]
        ),
        model="test-model",
    )

    with pytest.raises(ProjectPlanningError, match="failed validation"):
        planner.plan(make_project_specification(), make_implementation_plan())
