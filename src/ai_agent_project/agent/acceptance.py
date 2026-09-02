"""Provider-neutral acceptance-report domain models."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AcceptanceStatus(StrEnum):
    """Conservative result of acceptance validation."""

    PASSED = "passed"
    FAILED = "failed"
    UNKNOWN = "unknown"


class AcceptanceCriterionResult(BaseModel):
    """Evidence-backed result for one acceptance criterion."""

    model_config = ConfigDict(frozen=True)

    criterion: str
    status: AcceptanceStatus
    evidence: list[str] = Field(default_factory=list)
    notes: str | None = None


class RequirementValidationResult(BaseModel):
    """Evidence and result for one requirement."""

    model_config = ConfigDict(frozen=True)

    requirement_id: str
    status: AcceptanceStatus
    criteria: list[AcceptanceCriterionResult] = Field(default_factory=list)
    implemented_files: list[str] = Field(default_factory=list)
    test_files: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    notes: str | None = None


class AcceptanceReport(BaseModel):
    """Aggregated immutable traceability report for a coding run."""

    model_config = ConfigDict(frozen=True)

    status: AcceptanceStatus = AcceptanceStatus.UNKNOWN
    requirements: list[RequirementValidationResult] = Field(default_factory=list)
    validation_commands: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def aggregate_status(self) -> "AcceptanceReport":
        """Derive report status from individual requirement outcomes."""
        statuses = [requirement.status for requirement in self.requirements]
        if any(status is AcceptanceStatus.FAILED for status in statuses):
            status = AcceptanceStatus.FAILED
        elif statuses and all(status is AcceptanceStatus.PASSED for status in statuses):
            status = AcceptanceStatus.PASSED
        else:
            status = AcceptanceStatus.UNKNOWN
        object.__setattr__(self, "status", status)
        return self
