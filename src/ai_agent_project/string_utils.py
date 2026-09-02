"""String utility functions."""


def reverse_string(value: str) -> str:
    """Return the reversed string of the given value.

    Args:
        value: The string to reverse.

    Returns:
        The reversed string.
    """
    # Using slicing to reverse the string
    return value[::-1]


def is_palindrome(value: str) -> bool:
    """Return True if the given string is a palindrome.

    A palindrome reads the same forwards and backwards. The empty string
    is considered a palindrome.

    Args:
        value: The string to check.

    Returns:
        True if value is a palindrome, False otherwise.
    """
    # Compare the string to its reverse
    return value == reverse_string(value)
