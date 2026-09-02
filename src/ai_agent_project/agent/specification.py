"""Provider-neutral models representing a parsed project specification."""

import re
from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Priority(StrEnum):
    """Relative implementation priority for a requirement."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


_REQUIREMENT_ID_PREFIX = re.compile(r"^req-(\d+)(?=$|[\s:-])", re.IGNORECASE)


def canonicalize_requirement_id(value: str) -> str | None:
    """Return a canonical REQ identifier only when it is an explicit safe token."""
    match = _REQUIREMENT_ID_PREFIX.match(value.strip())
    if match is None:
        return None
    return f"REQ-{match.group(1)}"


class Requirement(BaseModel):
    """One independently verifiable requirement from a source document."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    title: str | None = None
    description: str = Field(min_length=1)
    acceptance_criteria: list[str] = Field(default_factory=list)
    priority: Priority | None = None
    source: str | None = None

    @model_validator(mode="before")
    @classmethod
    def canonicalize_explicit_id(cls, value: Any) -> Any:
        """Strip heading text from explicit REQ identifiers without guessing IDs."""
        if not isinstance(value, Mapping):
            return value
        canonical_id = canonicalize_requirement_id(value.get("id", ""))
        if canonical_id is None:
            return value
        return {**value, "id": canonical_id}


class Specification(BaseModel):
    """An immutable, structured representation of one specification document."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_name: str | None = None
    summary: str | None = None
    requirements: list[Requirement] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def assign_missing_requirement_ids(cls, value: Any) -> Any:
        """Assign deterministic IDs only where the source omitted one."""
        if not isinstance(value, Mapping):
            return value

        raw_requirements = value.get("requirements")
        if not isinstance(raw_requirements, list):
            return value

        requirements: list[Any] = []
        used_ids = {
            canonicalize_requirement_id(raw_id) or raw_id
            for item in raw_requirements
            if isinstance(item, Requirement)
            or isinstance(item, Mapping) and isinstance(item.get("id"), str)
            for raw_id in [item.id if isinstance(item, Requirement) else item["id"]]
        }
        next_number = 1
        for item in raw_requirements:
            if isinstance(item, Requirement):
                requirements.append(item)
                continue
            if not isinstance(item, Mapping):
                requirements.append(item)
                continue

            requirement = dict(item)
            if not requirement.get("id"):
                while (generated_id := f"REQ-{next_number:03d}") in used_ids:
                    next_number += 1
                requirement["id"] = generated_id
                used_ids.add(generated_id)
                next_number += 1
            requirements.append(requirement)

        return {**value, "requirements": requirements}

    @model_validator(mode="after")
    def reject_duplicate_requirement_ids(self) -> "Specification":
        """Reject duplicate IDs after explicit REQ IDs have been canonicalized."""
        ids = [requirement.id for requirement in self.requirements]
        if len(ids) != len(set(ids)):
            raise ValueError("Requirement IDs must be unique")
        return self
