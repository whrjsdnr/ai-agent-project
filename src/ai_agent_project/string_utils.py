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
