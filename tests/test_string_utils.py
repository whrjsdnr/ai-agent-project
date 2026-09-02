"""Tests for string_utils functions."""

from ai_agent_project.string_utils import (
    is_digits_only,
    is_palindrome,
    is_uppercase,
    reverse_string,
)


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


def test_is_uppercase_true() -> None:
    assert is_uppercase("ABC") is True


def test_is_uppercase_false() -> None:
    assert is_uppercase("AbC") is False


def test_is_digits_only_ascii_digits() -> None:
    assert is_digits_only("12345") is True


def test_is_digits_only_mixed_letters() -> None:
    assert is_digits_only("12a45") is False


def test_is_digits_only_empty() -> None:
    assert is_digits_only("") is False


def test_is_digits_only_full_width_digits() -> None:
    # Full-width Unicode digits should not be considered ASCII digits
    assert is_digits_only("１２３") is False
