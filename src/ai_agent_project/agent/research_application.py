"""Application-layer lifecycle and whole-snapshot storage for research runs."""

from typing import Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from ai_agent_project.agent.research import (
    ResearchDiscoveryReport,
    ResearchRequest,
    ResearchRun,
    ResearchStatus,
)
from ai_agent_project.agent.research_discovery import ResearchDiscoveryService


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
    ) -> None:
        self._discovery_service = discovery_service
        self._store = store

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

    def _require_run(self, research_run_id: str) -> ResearchRun:
        run = self._store.get(research_run_id)
        if run is None:
            raise ResearchRunNotFoundError(f"Research run not found: {research_run_id}")
        return run
