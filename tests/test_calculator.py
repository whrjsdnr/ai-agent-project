"""Tests for calculator operations."""

import pytest

from ai_agent_project.calculator import add, divide, multiply, subtract


def test_add() -> None:
    assert add(2, 3) == 5


def test_subtract() -> None:
    assert subtract(7, 4) == 3


def test_multiply() -> None:
    assert multiply(3, 4) == 12


def test_divide() -> None:
    assert divide(10, 2) == 5


def test_divide_by_zero_raises_error() -> None:
    with pytest.raises(ZeroDivisionError, match="Cannot divide by zero"):
        divide(10, 0)
