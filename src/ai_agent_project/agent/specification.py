"""Provider-neutral models representing a parsed project specification."""

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Priority(StrEnum):
    """Relative implementation priority for a requirement."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Requirement(BaseModel):
    """One independently verifiable requirement from a source document."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    title: str | None = None
    description: str = Field(min_length=1)
    acceptance_criteria: list[str] = Field(default_factory=list)
    priority: Priority | None = None
    source: str | None = None


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
            item.id
            if isinstance(item, Requirement)
            else item.get("id")
            for item in raw_requirements
            if isinstance(item, Requirement)
            or isinstance(item, Mapping) and isinstance(item.get("id"), str)
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
