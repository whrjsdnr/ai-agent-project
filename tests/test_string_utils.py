"""Tests for string_utils.reverse_string."""

from ai_agent_project.string_utils import reverse_string


def test_reverse_hello() -> None:
    assert reverse_string("hello") == "olleh"


def test_reverse_empty() -> None:
    assert reverse_string("") == ""
