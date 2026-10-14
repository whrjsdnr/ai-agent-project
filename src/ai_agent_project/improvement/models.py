"""Separate immutable improvement records and proposal-only evaluator schema."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Domain = Literal["developer", "researcher"]
Category = Literal[
    "planning",
    "prompt_strategy",
    "tool_selection",
    "validation",
    "error_recovery",
    "research_strategy",
    "evidence_quality",
    "project_specific",
]
Scope = Literal["global", "developer", "researcher", "project"]
ShortText = Annotated[str, Field(min_length=1, max_length=500)]
RuleText = Annotated[str, Field(min_length=1, max_length=1600)]


class Model(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
        hide_input_in_errors=True,
    )


class EvidenceFact(Model):
    name: ShortText
    value: int | bool | str


class ImprovementEvidence(Model):
    evidence_id: str
    source_domain: Domain
    source_run_id: str
    project_id: str | None
    digest: str
    facts: tuple[EvidenceFact, ...]
    feedback_ids: tuple[str, ...] = ()
    collected_at: datetime


class CandidateProposal(Model):
    category: Category
    title: ShortText
    proposed_rule: RuleText
    rationale: ShortText
    confidence: float = Field(ge=0, le=1)

    @field_validator("title", "proposed_rule", "rationale")
    @classmethod
    def safe_text(cls, value: str) -> str:
        from ai_agent_project.improvement.context import validate_guidance

        validate_guidance(value)
        return value


class EvaluationProposal(Model):
    strengths: tuple[ShortText, ...] = Field(default=(), max_length=5)
    weaknesses: tuple[ShortText, ...] = Field(default=(), max_length=5)
    possible_causes: tuple[ShortText, ...] = Field(default=(), max_length=5)
    confidence: float = Field(ge=0, le=1)
    improvement_warranted: bool
    candidates: tuple[CandidateProposal, ...] = Field(default=(), max_length=5)


class ImprovementEvaluation(Model):
    evaluation_id: str
    evidence: ImprovementEvidence
    proposal: EvaluationProposal
    created_at: datetime


class ImprovementCandidate(CandidateProposal):
    candidate_id: str
    evaluation_id: str
    source_domain: Domain
    source_run_id: str
    project_id: str | None
    evidence_refs: tuple[str, ...]
    digest: str
    status: Literal["pending", "approved", "rejected"] = "pending"
    created_at: datetime


class ImprovementRule(Model):
    rule_id: str
    source_candidate_id: str
    scope: Scope
    domain: Domain | None
    project_id: str | None
    category: Category
    rule_text: RuleText
    evidence_refs: tuple[str, ...]
    approved_at: datetime
    approved_by: Literal["user"] = "user"
    enabled: bool = True
    version: int = Field(ge=1)


class ImprovementFeedback(Model):
    feedback_id: str
    target_type: Literal["developer", "researcher", "candidate", "rule"]
    target_id: str
    rating: Literal["helpful", "not_helpful"]
    text: str = Field(default="", max_length=500, repr=False)
    created_at: datetime


class ImprovementApplication(Model):
    application_id: str
    domain: Domain
    run_id: str
    project_id: str | None
    rule_ids: tuple[str, ...]
    rule_versions: tuple[int, ...]
    operation: str
    applied_at: datetime


class ImprovementEvent(Model):
    target_id: str
    action: str
    at: datetime


class ImprovementImpact(Model):
    rule_id: str
    times_applied: int
    applied_run_ids: tuple[str, ...]
    positive_feedback_count: int
    negative_feedback_count: int
    runs_evaluated_after_application: int


class ImprovementState(Model):
    evaluations: tuple[ImprovementEvaluation, ...] = ()
    candidates: tuple[ImprovementCandidate, ...] = ()
    rules: tuple[ImprovementRule, ...] = ()
    feedback: tuple[ImprovementFeedback, ...] = ()
    applications: tuple[ImprovementApplication, ...] = ()
    events: tuple[ImprovementEvent, ...] = ()
