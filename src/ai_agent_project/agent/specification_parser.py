"""Provider-neutral interfaces and prompts for specification parsing."""

from typing import Protocol

from ai_agent_project.agent.specification import Specification

SPECIFICATION_PARSER_INSTRUCTIONS = """Parse the supplied specification document.
Return only data matching the provided JSON schema.
Do not invent functionality, requirements, constraints, or assumptions.
Preserve explicit requirement IDs exactly.
Extract acceptance criteria as testable statements when the source provides them.
Keep constraints separate from requirements and assumptions.
Only include assumptions explicitly stated as assumptions; preserve uncertainty rather
than converting it into an assumption.
Split independently verifiable requirements when the source clearly expresses them.
"""


class SpecificationParseError(ValueError):
    """Raised when specification text cannot become a valid Specification."""


class SpecificationParser(Protocol):
    """Parse raw Markdown or text into a provider-neutral Specification."""

    def parse(self, text: str) -> Specification:
        """Return a structured specification for non-empty source text."""
        ...


def validate_specification_text(text: str) -> str:
    """Reject empty source documents before invoking a provider."""
    if not text.strip():
        raise SpecificationParseError("Specification text must not be empty")
    return text
