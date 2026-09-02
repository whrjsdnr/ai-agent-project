"""Tests for OpenAI implementation planning without network requests."""

import json
from types import SimpleNamespace
from typing import Any

import pytest

from ai_agent_project.agent.specification import Specification
from ai_agent_project.llm.providers.openai_planner import (
    ImplementationPlanningError,
    OpenAIImplementationPlanner,
)


class FakeResponsesAPI:
    """Capture structured-output requests and return predefined responses."""

    def __init__(self, responses: list[object]) -> None:
        self._responses = responses
        self.requests: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> object:
        self.requests.append(kwargs)
        return self._responses.pop(0)


class FakeOpenAIAPIClient:
    """Expose a fake Responses API compatible with the planner."""

    def __init__(self, responses: list[object]) -> None:
        self.responses = FakeResponsesAPI(responses)


def make_specification() -> Specification:
    """Create a source specification for planner tests."""
    return Specification.model_validate(
        {
            "project_name": "회원 서비스",
            "requirements": [
                {"id": "REQ-001", "description": "회원가입을 제공한다."}
            ],
        }
    )


def test_openai_planner_requests_structured_plan_and_preserves_traceability() -> None:
    response = SimpleNamespace(
        output_text=json.dumps(
            {
                "summary": "회원가입 구현 계획",
                "tasks": [
                    {
                        "id": "TASK-001",
                        "title": "회원가입 구현",
                        "description": "회원가입 endpoint와 검증을 구현한다.",
                        "requirement_ids": ["REQ-001"],
                        "files": ["src/app.py"],
                    }
                ],
                "validation_commands": ["uv run pytest", "uv run ruff check ."],
            }
        )
    )
    fake_client = FakeOpenAIAPIClient([response])
    planner = OpenAIImplementationPlanner(client=fake_client, model="test-model")

    plan = planner.plan(make_specification())

    assert plan.tasks[0].requirement_ids == ["REQ-001"]
    request = fake_client.responses.requests[0]
    assert request["model"] == "test-model"
    assert request["text"]["format"]["type"] == "json_schema"
    assert request["text"]["format"]["name"] == "implementation_plan"
    assert request["text"]["format"]["strict"] is True
    assert "Every task must reference" in request["instructions"]
    assert "uv run pytest" in request["instructions"]
    assert "pytest -q" in request["instructions"]
    schema = request["text"]["format"]["schema"]
    task = schema["$defs"]["ImplementationTask"]
    assert schema["required"] == list(schema["properties"])
    assert task["required"] == list(task["properties"])
    assert schema["additionalProperties"] is False
    assert task["additionalProperties"] is False


@pytest.mark.parametrize(
    "output_text",
    [
        "not json",
        json.dumps(
            {
                "tasks": [
                    {
                        "id": "TASK-001",
                        "title": "알 수 없는 요구사항",
                        "description": "구현한다.",
                        "requirement_ids": ["REQ-999"],
                    }
                ]
            }
        ),
    ],
)
def test_openai_planner_rejects_malformed_or_untraceable_output(output_text: str) -> None:
    planner = OpenAIImplementationPlanner(
        client=FakeOpenAIAPIClient([SimpleNamespace(output_text=output_text)]),
        model="test-model",
    )

    with pytest.raises(ImplementationPlanningError):
        planner.plan(make_specification())


@pytest.mark.parametrize(
    ("validation_commands", "raises"),
    [(["uv run pytest"], False), (["pytest -q"], True)],
)
def test_openai_planner_enforces_shared_validation_command_policy(
    validation_commands: list[str],
    raises: bool,
) -> None:
    output = {
        "tasks": [
            {
                "id": "TASK-001",
                "title": "회원가입 구현",
                "description": "회원가입 endpoint를 구현한다.",
                "requirement_ids": ["REQ-001"],
            }
        ],
        "validation_commands": validation_commands,
    }
    planner = OpenAIImplementationPlanner(
        client=FakeOpenAIAPIClient([SimpleNamespace(output_text=json.dumps(output))]),
        model="test-model",
    )

    if raises:
        with pytest.raises(ImplementationPlanningError, match="failed validation"):
            planner.plan(make_specification())
    else:
        assert planner.plan(make_specification()).validation_commands == ["uv run pytest"]
