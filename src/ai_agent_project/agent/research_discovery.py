"""Read-only provider-neutral Research Discovery orchestration."""

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from ai_agent_project.agent.research import (
    ResearchDiscoveryReport,
    ResearchEvidence,
    ResearchQuestion,
    ResearchRequest,
    ResearchRun,
    ResearchSource,
    ResearchStatus,
    ResearchSynthesis,
)
from ai_agent_project.agent.research_planning import ResearchQuestionPlanner
from ai_agent_project.agent.research_sources import (
    ResearchSourceCandidate,
    ResearchSourceProvider,
    RetrievedResearchSource,
)
from ai_agent_project.agent.workspace import WorkspaceInspector


class ResearchDiscoveryError(Exception):
    """Raised when evidence-first discovery cannot produce a valid report."""


class ResearchDiscoveryLimits(BaseModel):
    """Provider-neutral upper bounds for one bounded discovery pass."""

    model_config = ConfigDict(frozen=True)

    max_questions: int = Field(default=3, ge=1)
    max_sources_per_question: int = Field(default=3, ge=1)


class ResearchEvidenceExtractor(Protocol):
    def extract(
        self,
        question: ResearchQuestion,
        source: RetrievedResearchSource,
    ) -> tuple[ResearchEvidence, ...]:
        """Extract evidence only from one authoritative question and source."""
        ...


class ResearchDiscoverySynthesizer(Protocol):
    def synthesize(
        self,
        request: ResearchRequest,
        questions: tuple[ResearchQuestion, ...],
        sources: tuple[ResearchSource, ...],
        evidence: tuple[ResearchEvidence, ...],
    ) -> ResearchSynthesis:
        """Build only higher-level sections from authoritative inputs."""
        ...


class ResearchDiscoveryService:
    """Discover evidence and stop before research execution or selection."""

    def __init__(
        self,
        planner: ResearchQuestionPlanner,
        sources: ResearchSourceProvider,
        evidence_extractor: ResearchEvidenceExtractor,
        synthesizer: ResearchDiscoverySynthesizer,
        workspace_inspector: WorkspaceInspector | None = None,
        limits: ResearchDiscoveryLimits | None = None,
    ) -> None:
        self._planner = planner
        self._sources = sources
        self._evidence_extractor = evidence_extractor
        self._synthesizer = synthesizer
        self._workspace_inspector = workspace_inspector
        self._limits = limits or ResearchDiscoveryLimits()

    def discover(self, request: ResearchRequest) -> ResearchRun:
        """Return a validated snapshot without modifying the supplied workspace."""
        workspace = (
            self._workspace_inspector.inspect() if self._workspace_inspector else None
        )
        questions = self._planner.plan(request, workspace)[: self._limits.max_questions]
        self._validate_questions(questions)

        candidates_by_locator: dict[str, ResearchSourceCandidate] = {}
        question_candidates: list[tuple[ResearchQuestion, ResearchSourceCandidate]] = []
        for question in questions:
            for candidate in self._sources.search(
                question, max_results=self._limits.max_sources_per_question
            )[: self._limits.max_sources_per_question]:
                identity = candidate.canonical_locator or candidate.locator
                canonical = candidates_by_locator.setdefault(identity, candidate)
                question_candidates.append((question, canonical))
        if not candidates_by_locator:
            raise ResearchDiscoveryError("Research discovery found no sources")

        retrieved_by_locator = {
            locator: self._sources.fetch(candidate)
            for locator, candidate in candidates_by_locator.items()
        }
        canonical_sources = tuple(
            retrieved.source for retrieved in retrieved_by_locator.values()
        )
        self._validate_source_identity(candidates_by_locator, canonical_sources)

        evidence: list[ResearchEvidence] = []
        for question, candidate in question_candidates:
            source = retrieved_by_locator[
                candidate.canonical_locator or candidate.locator
            ]
            for extracted in self._evidence_extractor.extract(question, source):
                if (
                    extracted.source_id != source.source.id
                    or extracted.question_id != question.id
                ):
                    raise ResearchDiscoveryError(
                        "Evidence extractor returned evidence for a different source or question"
                    )
                evidence.append(
                    extracted.model_copy(
                        update={
                            "id": f"E{len(evidence) + 1}",
                            "source_id": source.source.id,
                            "question_id": question.id,
                        }
                    )
                )
        if not evidence:
            raise ResearchDiscoveryError("Research discovery found no useful evidence")

        synthesis = self._synthesizer.synthesize(
            request, questions, canonical_sources, tuple(evidence)
        )
        report = ResearchDiscoveryReport(
            questions=questions,
            sources=canonical_sources,
            evidence=tuple(evidence),
            preliminary=synthesis.preliminary,
            related_work=synthesis.related_work,
            landscape=synthesis.landscape,
            related_studies=synthesis.related_studies,
            gaps=synthesis.gaps,
            directions=synthesis.directions,
        )
        status = (
            ResearchStatus.AWAITING_DIRECTION_SELECTION
            if report.directions
            else ResearchStatus.COMPLETED_DISCOVERY
        )
        return ResearchRun(request=request, status=status, report=report)

    @staticmethod
    def _validate_questions(questions: tuple[ResearchQuestion, ...]) -> None:
        if not questions:
            raise ResearchDiscoveryError(
                "Research question planning produced no questions"
            )
        if len({question.id for question in questions}) != len(questions):
            raise ResearchDiscoveryError(
                "Research question planning produced duplicate IDs"
            )

    @staticmethod
    def _validate_source_identity(
        candidates_by_locator: dict[str, ResearchSourceCandidate],
        sources: tuple[ResearchSource, ...],
    ) -> None:
        if len(sources) != len(candidates_by_locator):
            raise ResearchDiscoveryError("Source retrieval did not return every source")
        if len({source.locator for source in sources}) != len(sources):
            raise ResearchDiscoveryError("Source retrieval returned duplicate locators")
