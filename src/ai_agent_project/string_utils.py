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


def is_uppercase(value: str) -> bool:
    """Return True if the given string is uppercase.

    This function returns whether the cased characters in the string are
    all uppercase. Non-cased characters (digits, punctuation, whitespace)
    are ignored for the purpose of this check, matching the behavior of
    str.isupper().

    Args:
        value: The string to check.

    Returns:
        True if value is uppercase, False otherwise.
    """
    # Leverage the built-in str.isupper which checks cased characters
    return value.isupper()
