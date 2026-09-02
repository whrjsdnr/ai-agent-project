"""Tests for OpenAI specification parsing without network requests."""

import json
from types import SimpleNamespace
from typing import Any

import pytest

from ai_agent_project.agent.specification_parser import SpecificationParseError
from ai_agent_project.llm.providers.openai_specification import (
    OpenAISpecificationParser,
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
    """Expose a fake Responses API compatible with the parser."""

    def __init__(self, responses: list[object]) -> None:
        self.responses = FakeResponsesAPI(responses)


def test_openai_parser_requests_structured_specification_and_validates_result() -> None:
    response = SimpleNamespace(
        output_text=json.dumps(
            {
                "project_name": "회원 서비스",
                "requirements": [
                    {
                        "id": "REQ-001",
                        "description": "사용자는 회원가입할 수 있어야 한다.",
                        "acceptance_criteria": ["중복 이메일이면 409"],
                    }
                ],
                "constraints": ["Python 3.12를 사용해야 한다."],
                "assumptions": ["이메일 서버는 외부 시스템에서 제공된다고 가정한다."],
            }
        )
    )
    fake_client = FakeOpenAIAPIClient([response])
    parser = OpenAISpecificationParser(client=fake_client, model="test-model")

    specification = parser.parse("# 요구사항\n\n회원가입을 구현한다.")

    assert specification.requirements[0].id == "REQ-001"
    assert specification.requirements[0].acceptance_criteria == ["중복 이메일이면 409"]
    assert specification.constraints == ["Python 3.12를 사용해야 한다."]
    assert specification.assumptions == ["이메일 서버는 외부 시스템에서 제공된다고 가정한다."]
    request = fake_client.responses.requests[0]
    assert request["model"] == "test-model"
    assert request["text"]["format"]["type"] == "json_schema"
    assert request["text"]["format"]["name"] == "specification"
    assert request["text"]["format"]["strict"] is True
    assert "Do not invent functionality" in request["instructions"]
    schema = request["text"]["format"]["schema"]
    requirement = schema["$defs"]["Requirement"]
    assert schema["required"] == list(schema["properties"])
    assert requirement["required"] == list(requirement["properties"])
    assert requirement["additionalProperties"] is False
    assert any(
        branch.get("type") == "null" for branch in requirement["properties"]["title"]["anyOf"]
    )


def test_openai_parser_assigns_stable_ids_to_missing_requirement_ids() -> None:
    output = {"requirements": [{"description": "첫 요구사항"}, {"description": "둘째 요구사항"}]}
    parser = OpenAISpecificationParser(
        client=FakeOpenAIAPIClient([SimpleNamespace(output_text=json.dumps(output))]),
        model="test-model",
    )

    specification = parser.parse("두 요구사항")

    assert [requirement.id for requirement in specification.requirements] == [
        "REQ-001",
        "REQ-002",
    ]


@pytest.mark.parametrize(
    "output_text",
    ["not json", json.dumps({"requirements": [{"id": "REQ-001"}]})],
)
def test_openai_parser_rejects_malformed_structured_responses(output_text: str) -> None:
    parser = OpenAISpecificationParser(
        client=FakeOpenAIAPIClient([SimpleNamespace(output_text=output_text)]),
        model="test-model",
    )

    with pytest.raises(SpecificationParseError):
        parser.parse("유효한 입력")


def test_openai_parser_rejects_empty_input_without_calling_provider() -> None:
    fake_client = FakeOpenAIAPIClient([])
    parser = OpenAISpecificationParser(client=fake_client, model="test-model")

    with pytest.raises(SpecificationParseError, match="must not be empty"):
        parser.parse("   ")

    assert fake_client.responses.requests == []
