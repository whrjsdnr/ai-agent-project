"""Tests for string_utils functions."""

from ai_agent_project.string_utils import is_palindrome, reverse_string


def test_reverse_hello() -> None:
    assert reverse_string("hello") == "olleh"


def test_reverse_empty() -> None:
    assert reverse_string("") == ""


def test_is_palindrome_level() -> None:
    assert is_palindrome("level") is True


def test_is_palindrome_hello() -> None:
    assert is_palindrome("hello") is False


def test_is_palindrome_empty() -> None:
    assert is_palindrome("") is True
