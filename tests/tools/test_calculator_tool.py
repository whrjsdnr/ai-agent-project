"""Tests for the calculator tool adapter and registry."""

import pytest

from ai_agent_project.tools.calculator import CalculatorTool
from ai_agent_project.tools.registry import ToolNotFoundError, ToolRegistry


def test_calculator_tool_reuses_calculator_operations() -> None:
    result = CalculatorTool().execute({"operation": "multiply", "a": 6, "b": 7})

    assert result.success is True
    assert result.data == {"result": 42}


def test_registry_raises_for_unknown_tool() -> None:
    registry = ToolRegistry()

    with pytest.raises(ToolNotFoundError, match="Tool not found: missing"):
        registry.get("missing")
