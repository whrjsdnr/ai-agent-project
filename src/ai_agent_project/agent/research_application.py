"""Application-layer lifecycle and whole-snapshot storage for research runs."""

from typing import Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from ai_agent_project.agent.research import (
    ResearchDiscoveryReport,
    ResearchPlanRevision,
    ResearchPlanRevisionState,
    ResearchRequest,
    ResearchRun,
    ResearchStatus,
)
from ai_agent_project.agent.research_discovery import ResearchDiscoveryService
from ai_agent_project.agent.research_planning import ResearchPlanGenerator


class ResearchRunError(Exception):
    """Base error for provider-neutral research-run operations."""


class ResearchRunNotFoundError(ResearchRunError):
    """Raised when a requested research run is absent from storage."""


class ResearchRunAlreadyExistsError(ResearchRunError):
    """Raised when storage creation would overwrite a research run."""


class ResearchDirectionNotFoundError(ResearchRunError):
    """Raised when a direction ID is not part of the stored report."""


class InvalidResearchStateError(ResearchRunError):
    """Raised when a research lifecycle transition is not permitted."""


class ResearchRunStore(Protocol):
    """Persist immutable research snapshots through whole replacement only."""

    def create(self, research_run_id: str, research_run: ResearchRun) -> None: ...

    def get(self, research_run_id: str) -> ResearchRun | None: ...

    def replace(self, research_run_id: str, research_run: ResearchRun) -> None: ...


class InMemoryResearchRunStore:
    """Small process-local store used by deterministic application tests."""

    def __init__(self) -> None:
        self._runs: dict[str, ResearchRun] = {}

    def create(self, research_run_id: str, research_run: ResearchRun) -> None:
        if research_run_id in self._runs:
            raise ResearchRunAlreadyExistsError(
                f"Research run already exists: {research_run_id}"
            )
        self._runs[research_run_id] = research_run

    def get(self, research_run_id: str) -> ResearchRun | None:
        return self._runs.get(research_run_id)

    def replace(self, research_run_id: str, research_run: ResearchRun) -> None:
        if research_run_id not in self._runs:
            raise ResearchRunNotFoundError(f"Research run not found: {research_run_id}")
        self._runs[research_run_id] = research_run


class StoredResearchRun(BaseModel):
    """Immutable application result pairing a stable ID with a run snapshot."""

    model_config = ConfigDict(frozen=True)

    id: str
    research_run: ResearchRun


class ResearchApplicationService:
    """Create, retrieve, and explicitly select directions for research discovery."""

    def __init__(
        self,
        discovery_service: ResearchDiscoveryService,
        store: ResearchRunStore,
        plan_generator: ResearchPlanGenerator | None = None,
    ) -> None:
        self._discovery_service = discovery_service
        self._store = store
        self._plan_generator = plan_generator

    def create_research_run(
        self, topic: str, *, user_context: str | None = None
    ) -> StoredResearchRun:
        if not topic.strip():
            raise ResearchRunError("Research topic must not be blank")
        run = self._discovery_service.discover(
            ResearchRequest(topic=topic, user_context=user_context)
        )
        run_id = str(uuid4())
        self._store.create(run_id, run)
        return StoredResearchRun(id=run_id, research_run=run)

    def get_research_run(self, research_run_id: str) -> StoredResearchRun:
        return StoredResearchRun(
            id=research_run_id,
            research_run=self._require_run(research_run_id),
        )

    def get_research_report(self, research_run_id: str) -> ResearchDiscoveryReport:
        return self._require_run(research_run_id).report

    def get_research_directions(self, research_run_id: str):
        return self._require_run(research_run_id).report.directions

    def select_research_direction(
        self, research_run_id: str, direction_id: str
    ) -> StoredResearchRun:
        run = self._require_run(research_run_id)
        if run.status is not ResearchStatus.AWAITING_DIRECTION_SELECTION:
            raise InvalidResearchStateError(
                "Research direction selection is only allowed while awaiting selection"
            )
        if direction_id not in {direction.id for direction in run.report.directions}:
            raise ResearchDirectionNotFoundError(
                f"Research direction not found: {direction_id}"
            )
        updated = run.model_copy(
            update={
                "status": ResearchStatus.DIRECTION_SELECTED,
                "selected_direction_id": direction_id,
            }
        )
        self._store.replace(research_run_id, updated)
        return StoredResearchRun(id=research_run_id, research_run=updated)

    def generate_plan(self, research_run_id: str) -> StoredResearchRun:
        run = self._require_run(research_run_id)
        if run.status is not ResearchStatus.DIRECTION_SELECTED:
            raise InvalidResearchStateError(
                "Research plan generation requires a selected direction"
            )
        if self._plan_generator is None:
            raise ResearchRunError("Research plan generation is not configured")
        direction = self._selected_direction(run)
        plan = self._plan_generator.generate(run.request, direction, run.report)
        if plan.selected_direction_id != direction.id:
            raise ResearchRunError(
                "Generated research plan changed the selected direction"
            )
        updated = run.model_copy(
            update={
                "status": ResearchStatus.AWAITING_RESEARCH_PLAN_APPROVAL,
                "plan_revision_state": ResearchPlanRevisionState.from_plan(plan),
            }
        )
        self._store.replace(research_run_id, updated)
        return StoredResearchRun(id=research_run_id, research_run=updated)

    def get_plan(self, research_run_id: str) -> ResearchPlanRevisionState:
        state = self._require_run(research_run_id).plan_revision_state
        if state is None:
            raise InvalidResearchStateError("Research plan has not been generated")
        return state

    def revise_plan(self, research_run_id: str, note: str) -> StoredResearchRun:
        run = self._require_run(research_run_id)
        if run.status is not ResearchStatus.AWAITING_RESEARCH_PLAN_APPROVAL:
            raise InvalidResearchStateError(
                "Research plan revision is not allowed in this state"
            )
        if not note.strip():
            raise ResearchRunError("Research plan revision note must not be blank")
        if self._plan_generator is None or run.plan_revision_state is None:
            raise ResearchRunError("Research plan revision is not configured")
        direction = self._selected_direction(run)
        plan = self._plan_generator.generate(
            run.request, direction, run.report, revision_note=note
        )
        if plan.selected_direction_id != direction.id:
            raise ResearchRunError(
                "Generated research plan changed the selected direction"
            )
        revisions = (
            *run.plan_revision_state.revisions,
            ResearchPlanRevision(
                version=len(run.plan_revision_state.revisions) + 1, plan=plan, note=note
            ),
        )
        updated = run.model_copy(
            update={
                "plan_revision_state": ResearchPlanRevisionState(
                    active_version=len(revisions), revisions=revisions
                )
            }
        )
        self._store.replace(research_run_id, updated)
        return StoredResearchRun(id=research_run_id, research_run=updated)

    def approve_plan(self, research_run_id: str) -> StoredResearchRun:
        run = self._require_run(research_run_id)
        if (
            run.status is not ResearchStatus.AWAITING_RESEARCH_PLAN_APPROVAL
            or run.plan_revision_state is None
        ):
            raise InvalidResearchStateError(
                "Research plan approval is not allowed in this state"
            )
        updated = run.model_copy(
            update={
                "status": ResearchStatus.RESEARCH_PLAN_APPROVED,
                "plan_revision_state": run.plan_revision_state.model_copy(
                    update={"approved": True}
                ),
            }
        )
        self._store.replace(research_run_id, updated)
        return StoredResearchRun(id=research_run_id, research_run=updated)

    @staticmethod
    def _selected_direction(run: ResearchRun):
        if run.selected_direction_id is None:
            raise InvalidResearchStateError("Research run has no selected direction")
        return next(
            direction
            for direction in run.report.directions
            if direction.id == run.selected_direction_id
        )

    def _require_run(self, research_run_id: str) -> ResearchRun:
        run = self._store.get(research_run_id)
        if run is None:
            raise ResearchRunNotFoundError(f"Research run not found: {research_run_id}")
        return run
