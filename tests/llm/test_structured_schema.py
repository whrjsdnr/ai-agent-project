"""Tests for OpenAI strict Structured Outputs schema normalization."""

from typing import Any

from ai_agent_project.agent.plan import ImplementationPlan
from ai_agent_project.agent.specification import Specification
from ai_agent_project.llm.providers.structured_schema import openai_strict_json_schema


def _assert_strict_objects(value: object) -> None:
    """Assert strict object requirements recursively, including definitions."""
    if isinstance(value, list):
        for item in value:
            _assert_strict_objects(item)
        return
    if not isinstance(value, dict):
        return

    properties = value.get("properties")
    if isinstance(properties, dict):
        assert value["required"] == list(properties)
        assert value["additionalProperties"] is False
    for child in value.values():
        _assert_strict_objects(child)


def _allows_null(schema: dict[str, Any]) -> bool:
    """Return whether a JSON Schema property explicitly allows null."""
    if schema.get("type") == "null":
        return True
    branches = schema.get("anyOf")
    return isinstance(branches, list) and any(
        isinstance(branch, dict) and branch.get("type") == "null"
        for branch in branches
    )


def test_specification_schema_requires_all_root_and_nested_properties() -> None:
    schema = openai_strict_json_schema(Specification)
    requirement = schema["$defs"]["Requirement"]

    assert schema["required"] == list(schema["properties"])
    assert requirement["required"] == list(requirement["properties"])
    assert "title" in requirement["required"]
    assert _allows_null(requirement["properties"]["title"])
    _assert_strict_objects(schema)


def test_implementation_plan_schema_normalizes_nested_tasks() -> None:
    schema = openai_strict_json_schema(ImplementationPlan)
    task = schema["$defs"]["ImplementationTask"]

    assert schema["required"] == list(schema["properties"])
    assert task["required"] == list(task["properties"])
    assert "summary" in schema["required"]
    assert _allows_null(schema["properties"]["summary"])
    _assert_strict_objects(schema)
