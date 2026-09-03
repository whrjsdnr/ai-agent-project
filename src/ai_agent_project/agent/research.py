"""Evidence-first, read-only Research Discovery domain models."""

from enum import StrEnum
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _nonblank_identifier(value: str) -> str:
    if not value.strip():
        raise ValueError("Research IDs must not be blank")
    return value


class WorkMode(StrEnum):
    DEVELOPER = "developer"
    RESEARCHER = "researcher"
    HYBRID = "hybrid"


class ResearchStatus(StrEnum):
    DISCOVERING = "discovering"
    AWAITING_DIRECTION_SELECTION = "awaiting_direction_selection"
    DIRECTION_SELECTED = "direction_selected"
    FAILED = "failed"
    COMPLETED_DISCOVERY = "completed_discovery"
    AWAITING_RESEARCH_PLAN_APPROVAL = "awaiting_research_plan_approval"
    RESEARCH_PLAN_APPROVED = "research_plan_approved"


class ResearchScope(StrEnum):
    WORKSPACE = "workspace"
    EXTERNAL = "external"
    MIXED = "mixed"


class SourceAuthority(StrEnum):
    OFFICIAL = "official"
    PRIMARY = "primary"
    SECONDARY = "secondary"
    UNKNOWN = "unknown"


class RetrievalGranularity(StrEnum):
    CITATION_SPAN = "citation_span"
    GROUNDED_SEARCH_EXCERPT = "grounded_search_excerpt"


class RetrievalProvenance(BaseModel):
    """Minimal typed evidence that a source came from an external retrieval tool."""

    model_config = ConfigDict(frozen=True)

    provider: str
    retrieval_type: str
    tool_grounded: bool
    content_granularity: RetrievalGranularity


class ResearchRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    topic: str = Field(min_length=1)
    user_context: str | None = None


class ResearchQuestion(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str = Field(min_length=1)
    question: str
    rationale: str
    source_scope: ResearchScope

    _validate_id = field_validator("id")(_nonblank_identifier)


class ResearchSource(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str = Field(min_length=1)
    title: str
    locator: str
    canonical_locator: str | None = None
    source_type: str
    authority: SourceAuthority = SourceAuthority.UNKNOWN
    provenance: RetrievalProvenance | None = None

    _validate_id = field_validator("id")(_nonblank_identifier)

    @field_validator("locator")
    @classmethod
    def validate_external_locator(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Research source locator must be an external HTTP(S) URL")
        return value


class ResearchEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str = Field(min_length=1)
    source_id: str
    question_id: str
    claim: str
    support_text: str
    locator: str | None = None
    evidence_type: str

    _validate_id = field_validator("id")(_nonblank_identifier)


class RelatedStudy(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str = Field(min_length=1)
    title: str
    research_problem: str
    method: str | None = None
    limitations: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = Field(min_length=1)

    _validate_id = field_validator("id")(_nonblank_identifier)


class ResearchGap(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str = Field(min_length=1)
    description: str
    supporting_study_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    importance: str
    feasibility: str

    _validate_id = field_validator("id")(_nonblank_identifier)


class ResearchDirection(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str = Field(min_length=1)
    title: str
    research_question: str
    target_gap_ids: tuple[str, ...] = Field(min_length=1)
    novelty: str
    expected_contributions: tuple[str, ...] = ()
    feasibility: str
    risks: tuple[str, ...] = ()

    _validate_id = field_validator("id")(_nonblank_identifier)


class PreliminaryResearchReport(BaseModel):
    model_config = ConfigDict(frozen=True)
    topic: str
    research_domains: tuple[str, ...] = ()
    major_methods: tuple[str, ...] = ()
    common_datasets: tuple[str, ...] = ()
    common_metrics: tuple[str, ...] = ()
    open_problems: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()


class RelatedWorkReport(BaseModel):
    model_config = ConfigDict(frozen=True)
    study_ids: tuple[str, ...] = ()
    common_methods: tuple[str, ...] = ()
    recurring_limitations: tuple[str, ...] = ()
    unresolved_problems: tuple[str, ...] = ()


class ResearchEvolutionStage(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str = Field(min_length=1)
    title: str
    representative_study_ids: tuple[str, ...] = ()
    representative_methods: tuple[str, ...] = ()
    remaining_problems: tuple[str, ...] = ()

    _validate_id = field_validator("id")(_nonblank_identifier)


class ResearchLandscape(BaseModel):
    model_config = ConfigDict(frozen=True)
    stages: tuple[ResearchEvolutionStage, ...] = ()
    current_frontier: str = ""
    recurring_limitations: tuple[str, ...] = ()


class ResearchSynthesis(BaseModel):
    """Provider-generated sections that reference service-owned evidence."""

    model_config = ConfigDict(frozen=True)

    preliminary: PreliminaryResearchReport | None = None
    related_work: RelatedWorkReport | None = None
    landscape: ResearchLandscape | None = None
    related_studies: tuple[RelatedStudy, ...] = ()
    gaps: tuple[ResearchGap, ...] = ()
    directions: tuple[ResearchDirection, ...] = ()


class ResearchObjective(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str = Field(min_length=1)
    description: str
    direction_id: str

    _validate_id = field_validator("id")(_nonblank_identifier)


class ResearchHypothesis(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str = Field(min_length=1)
    statement: str
    objective_ids: tuple[str, ...] = ()

    _validate_id = field_validator("id")(_nonblank_identifier)


class ResearchMethodologyStep(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str = Field(min_length=1)
    description: str
    objective_ids: tuple[str, ...] = ()
    hypothesis_ids: tuple[str, ...] = ()

    _validate_id = field_validator("id")(_nonblank_identifier)


class ResearchMetric(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str = Field(min_length=1)
    name: str
    description: str
    measurement_method: str
    direction: str | None = None

    _validate_id = field_validator("id")(_nonblank_identifier)


class ResearchSuccessCriterion(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str = Field(min_length=1)
    metric_id: str | None = None
    target_description: str
    rationale: str

    _validate_id = field_validator("id")(_nonblank_identifier)


class ResearchPlan(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str = Field(min_length=1)
    selected_direction_id: str
    title: str
    research_question: str
    objectives: tuple[ResearchObjective, ...] = ()
    hypotheses: tuple[ResearchHypothesis, ...] = ()
    methodology: tuple[ResearchMethodologyStep, ...] = ()
    metrics: tuple[ResearchMetric, ...] = ()
    success_criteria: tuple[ResearchSuccessCriterion, ...] = ()
    risks: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    expected_outputs: tuple[str, ...] = ()

    _validate_id = field_validator("id")(_nonblank_identifier)

    @model_validator(mode="after")
    def validate_traceability(self) -> "ResearchPlan":
        groups = (
            ("objective", self.objectives),
            ("hypothesis", self.hypotheses),
            ("methodology step", self.methodology),
            ("metric", self.metrics),
            ("success criterion", self.success_criteria),
        )
        for name, items in groups:
            if len({item.id for item in items}) != len(items):
                raise ValueError(f"Duplicate research {name} IDs are not allowed")
        objective_ids = {item.id for item in self.objectives}
        hypothesis_ids = {item.id for item in self.hypotheses}
        metric_ids = {item.id for item in self.metrics}
        if any(
            item.direction_id != self.selected_direction_id for item in self.objectives
        ):
            raise ValueError(
                "Research objectives must reference the selected direction"
            )
        if any(
            not set(item.objective_ids) <= objective_ids for item in self.hypotheses
        ):
            raise ValueError("Research hypothesis references unknown objective")
        if any(
            not set(item.objective_ids) <= objective_ids
            or not set(item.hypothesis_ids) <= hypothesis_ids
            for item in self.methodology
        ):
            raise ValueError(
                "Research methodology references unknown objective or hypothesis"
            )
        if any(
            item.metric_id is not None and item.metric_id not in metric_ids
            for item in self.success_criteria
        ):
            raise ValueError("Research success criterion references unknown metric")
        return self


class ResearchPlanRevision(BaseModel):
    model_config = ConfigDict(frozen=True)
    version: int = Field(ge=1)
    plan: ResearchPlan
    note: str | None = None


class ResearchPlanRevisionState(BaseModel):
    model_config = ConfigDict(frozen=True)
    active_version: int = Field(ge=1)
    approved: bool = False
    revisions: tuple[ResearchPlanRevision, ...]

    @model_validator(mode="after")
    def validate_revision_state(self) -> "ResearchPlanRevisionState":
        if not self.revisions:
            raise ValueError("Research plan revision history must not be empty")
        expected_versions = tuple(range(1, len(self.revisions) + 1))
        actual_versions = tuple(revision.version for revision in self.revisions)
        if actual_versions != expected_versions:
            raise ValueError("Research plan revision versions must be ordered from 1")
        if self.active_version != self.revisions[-1].version:
            raise ValueError("Research plan active version must be the latest revision")
        return self

    @classmethod
    def from_plan(cls, plan: ResearchPlan) -> "ResearchPlanRevisionState":
        return cls(
            active_version=1, revisions=(ResearchPlanRevision(version=1, plan=plan),)
        )

    @property
    def active_plan(self) -> ResearchPlan:
        return self.revisions[-1].plan


class ResearchQuestionSet(BaseModel):
    """Fixed-schema structured-output envelope for question planning."""

    model_config = ConfigDict(frozen=True)

    questions: tuple[ResearchQuestion, ...]

    @model_validator(mode="after")
    def validate_unique_ids(self) -> "ResearchQuestionSet":
        if len({question.id for question in self.questions}) != len(self.questions):
            raise ValueError("Duplicate research question IDs are not allowed")
        return self


class ResearchEvidenceSet(BaseModel):
    """Fixed-schema structured-output envelope for evidence extraction."""

    model_config = ConfigDict(frozen=True)

    evidence: tuple[ResearchEvidence, ...] = ()

    @model_validator(mode="after")
    def validate_unique_ids(self) -> "ResearchEvidenceSet":
        if len({item.id for item in self.evidence}) != len(self.evidence):
            raise ValueError("Duplicate research evidence IDs are not allowed")
        return self


class ResearchDiscoveryReport(BaseModel):
    """Typed Source → Evidence → Study → Gap → Direction traceability graph."""

    model_config = ConfigDict(frozen=True)
    questions: tuple[ResearchQuestion, ...] = ()
    sources: tuple[ResearchSource, ...] = ()
    evidence: tuple[ResearchEvidence, ...] = ()
    related_studies: tuple[RelatedStudy, ...] = ()
    preliminary: PreliminaryResearchReport | None = None
    related_work: RelatedWorkReport | None = None
    landscape: ResearchLandscape | None = None
    gaps: tuple[ResearchGap, ...] = ()
    directions: tuple[ResearchDirection, ...] = ()

    @model_validator(mode="after")
    def validate_traceability(self) -> "ResearchDiscoveryReport":
        question_ids = {item.id for item in self.questions}
        source_ids = {item.id for item in self.sources}
        evidence_ids = {item.id for item in self.evidence}
        study_ids = {item.id for item in self.related_studies}
        gap_ids = {item.id for item in self.gaps}
        reference_ids = (
            *(item.source_id for item in self.evidence),
            *(item.question_id for item in self.evidence),
            *(
                reference
                for item in self.related_studies
                for reference in item.evidence_ids
            ),
            *(reference for item in self.gaps for reference in item.evidence_ids),
            *(
                reference
                for item in self.gaps
                for reference in item.supporting_study_ids
            ),
            *(
                reference
                for item in self.directions
                for reference in item.target_gap_ids
            ),
            *(() if self.preliminary is None else self.preliminary.evidence_ids),
            *(() if self.related_work is None else self.related_work.study_ids),
            *(
                reference
                for stage in (() if self.landscape is None else self.landscape.stages)
                for reference in stage.representative_study_ids
            ),
        )
        if any(not reference.strip() for reference in reference_ids):
            raise ValueError("Research references must not contain blank IDs")
        for name, values, items in (
            ("question", question_ids, self.questions),
            ("source", source_ids, self.sources),
            ("evidence", evidence_ids, self.evidence),
            ("study", study_ids, self.related_studies),
            ("gap", gap_ids, self.gaps),
            ("direction", {item.id for item in self.directions}, self.directions),
        ):
            expected = len(items)
            if len(values) != expected:
                raise ValueError(f"Duplicate research {name} IDs are not allowed")
        if any(
            item.source_id not in source_ids or item.question_id not in question_ids
            for item in self.evidence
        ):
            raise ValueError(
                "Research evidence references an unknown source or question"
            )
        if any(
            not set(item.evidence_ids) <= evidence_ids for item in self.related_studies
        ):
            raise ValueError("Related study references unknown evidence")
        if any(
            not set(item.evidence_ids) <= evidence_ids
            or not set(item.supporting_study_ids) <= study_ids
            for item in self.gaps
        ):
            raise ValueError("Research gap references unknown evidence or study")
        if any(not set(item.target_gap_ids) <= gap_ids for item in self.directions):
            raise ValueError("Research direction references unknown gap")
        if self.preliminary and not set(self.preliminary.evidence_ids) <= evidence_ids:
            raise ValueError("Preliminary research references unknown evidence")
        if self.related_work and not set(self.related_work.study_ids) <= study_ids:
            raise ValueError("Related work references unknown study")
        if self.landscape and any(
            not set(stage.representative_study_ids) <= study_ids
            for stage in self.landscape.stages
        ):
            raise ValueError("Research landscape references unknown study")
        return self


class ResearchRun(BaseModel):
    model_config = ConfigDict(frozen=True)
    work_mode: WorkMode = WorkMode.RESEARCHER
    request: ResearchRequest
    status: ResearchStatus
    report: ResearchDiscoveryReport
    selected_direction_id: str | None = None
    plan_revision_state: ResearchPlanRevisionState | None = None

    @model_validator(mode="after")
    def validate_selection(self) -> "ResearchRun":
        direction_ids = {item.id for item in self.report.directions}
        if (
            self.selected_direction_id is not None
            and self.selected_direction_id not in direction_ids
        ):
            raise ValueError("Selected research direction does not exist")
        if (
            self.status
            in {
                ResearchStatus.DIRECTION_SELECTED,
                ResearchStatus.AWAITING_RESEARCH_PLAN_APPROVAL,
                ResearchStatus.RESEARCH_PLAN_APPROVED,
            }
            and self.selected_direction_id is None
        ):
            raise ValueError("Direction-selected run requires selected_direction_id")
        if self.plan_revision_state is not None and (
            self.plan_revision_state.active_plan.selected_direction_id
            != self.selected_direction_id
        ):
            raise ValueError("Research plan must preserve the selected direction")
        if self.plan_revision_state is not None and self.status not in {
            ResearchStatus.AWAITING_RESEARCH_PLAN_APPROVAL,
            ResearchStatus.RESEARCH_PLAN_APPROVED,
        }:
            raise ValueError("Research plan state requires a planning lifecycle status")
        if self.status is ResearchStatus.AWAITING_RESEARCH_PLAN_APPROVAL and (
            self.plan_revision_state is None or self.plan_revision_state.approved
        ):
            raise ValueError(
                "Awaiting plan approval requires an unapproved research plan"
            )
        if self.status is ResearchStatus.RESEARCH_PLAN_APPROVED and (
            self.plan_revision_state is None or not self.plan_revision_state.approved
        ):
            raise ValueError("Approved research-plan status requires an approved plan")
        return self
