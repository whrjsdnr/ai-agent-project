"""Tests for provider-neutral specification domain models."""

import pytest
from pydantic import ValidationError

from ai_agent_project.agent.specification import Requirement, Specification
from ai_agent_project.agent.specification_parser import (
    SpecificationParseError,
    validate_specification_text,
)


def test_explicit_requirement_ids_and_acceptance_criteria_are_preserved() -> None:
    specification = Specification.model_validate(
        {
            "requirements": [
                {
                    "id": "REQ-001",
                    "title": "회원 생성",
                    "description": "사용자는 이메일과 비밀번호로 회원가입할 수 있어야 한다.",
                    "acceptance_criteria": [
                        "올바른 이메일이면 회원 생성",
                        "중복 이메일이면 409",
                    ],
                },
                {
                    "id": "FR-02",
                    "description": "사용자는 로그인할 수 있어야 한다.",
                    "acceptance_criteria": [],
                },
            ]
        }
    )

    assert [requirement.id for requirement in specification.requirements] == [
        "REQ-001",
        "FR-02",
    ]
    assert specification.requirements[0].acceptance_criteria == [
        "올바른 이메일이면 회원 생성",
        "중복 이메일이면 409",
    ]


def test_constraints_and_explicit_assumptions_are_separate() -> None:
    specification = Specification.model_validate(
        {
            "requirements": [],
            "constraints": ["Python 3.12를 사용해야 한다."],
            "assumptions": ["이메일 서버는 외부 시스템에서 제공된다고 가정한다."],
        }
    )

    assert specification.constraints == ["Python 3.12를 사용해야 한다."]
    assert specification.assumptions == ["이메일 서버는 외부 시스템에서 제공된다고 가정한다."]


def test_missing_requirement_ids_are_stable_and_do_not_replace_explicit_ids() -> None:
    source = {
        "requirements": [
            {"description": "첫 번째 요구사항"},
            {"id": "REQ-002", "description": "명시적 요구사항"},
            {"description": "세 번째 요구사항"},
        ]
    }

    first = Specification.model_validate(source)
    second = Specification.model_validate(source)

    assert [requirement.id for requirement in first.requirements] == [
        "REQ-001",
        "REQ-002",
        "REQ-003",
    ]
    assert first == second


def test_empty_specification_text_is_rejected() -> None:
    with pytest.raises(SpecificationParseError, match="must not be empty"):
        validate_specification_text(" \n\t ")


def test_requirement_models_are_frozen() -> None:
    requirement = Requirement(id="REQ-001", description="변경 불가")

    with pytest.raises(ValidationError):
        requirement.description = "변경됨"
