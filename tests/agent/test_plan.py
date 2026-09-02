"""Tests for provider-neutral implementation plan models."""

import pytest
from pydantic import ValidationError

from ai_agent_project.agent.plan import (
    ImplementationPlan,
    ImplementationPlanValidationError,
)
from ai_agent_project.agent.specification import Specification


def make_specification() -> Specification:
    """Create a two-requirement specification for traceability tests."""
    return Specification.model_validate(
        {
            "requirements": [
                {"id": "REQ-001", "description": "회원가입을 제공한다."},
                {"id": "REQ-002", "description": "로그인을 제공한다."},
            ]
        }
    )


def test_plan_validates_requirement_traceability_and_dependency_dag() -> None:
    plan = ImplementationPlan.model_validate(
        {
            "tasks": [
                {
                    "id": "TASK-001",
                    "title": "회원가입 구현",
                    "description": "회원가입 endpoint를 구현한다.",
                    "requirement_ids": ["REQ-001"],
                },
                {
                    "id": "TASK-002",
                    "title": "로그인 구현",
                    "description": "로그인 endpoint를 구현한다.",
                    "requirement_ids": ["REQ-002"],
                    "depends_on": ["TASK-001"],
                },
            ],
            "validation_commands": ["uv run pytest", "uv run ruff check ."],
        }
    )

    assert plan.validate_traceability(make_specification()) is plan


@pytest.mark.parametrize(
    "tasks",
    [
        [
            {
                "id": "TASK-001",
                "title": "순환 A",
                "description": "A",
                "requirement_ids": ["REQ-001"],
                "depends_on": ["TASK-002"],
            },
            {
                "id": "TASK-002",
                "title": "순환 B",
                "description": "B",
                "requirement_ids": ["REQ-002"],
                "depends_on": ["TASK-001"],
            },
        ],
        [
            {
                "id": "TASK-001",
                "title": "미지 dependency",
                "description": "의존성을 확인한다.",
                "requirement_ids": ["REQ-001"],
                "depends_on": ["TASK-999"],
            }
        ],
    ],
)
def test_plan_rejects_invalid_dependency_dags(tasks: list[dict[str, object]]) -> None:
    with pytest.raises(ValidationError):
        ImplementationPlan.model_validate({"tasks": tasks})


def test_plan_rejects_unknown_or_uncovered_requirement_ids() -> None:
    unknown = ImplementationPlan.model_validate(
        {
            "tasks": [
                {
                    "id": "TASK-001",
                    "title": "알 수 없음",
                    "description": "요구사항을 구현한다.",
                    "requirement_ids": ["REQ-999"],
                }
            ]
        }
    )
    uncovered = ImplementationPlan.model_validate(
        {
            "tasks": [
                {
                    "id": "TASK-001",
                    "title": "부분 구현",
                    "description": "첫 요구사항만 구현한다.",
                    "requirement_ids": ["REQ-001"],
                }
            ]
        }
    )

    with pytest.raises(ImplementationPlanValidationError, match="unknown requirement"):
        unknown.validate_traceability(make_specification())
    with pytest.raises(ImplementationPlanValidationError, match="no task"):
        uncovered.validate_traceability(make_specification())


def test_plan_rejects_unsafe_validation_commands() -> None:
    with pytest.raises(ValidationError, match="Unsafe validation command"):
        ImplementationPlan.model_validate(
            {
                "tasks": [],
                "validation_commands": ["rm -rf ."],
            }
        )
