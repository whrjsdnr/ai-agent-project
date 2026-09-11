"""Read-only source discovery abstraction."""

from typing import Protocol

from pydantic import BaseModel, ConfigDict

from ai_agent_project.agent.research import ResearchQuestion, ResearchSource


class ResearchSourceCandidate(ResearchSource):
    model_config = ConfigDict(frozen=True)


class RetrievedResearchSource(BaseModel):
    model_config = ConfigDict(frozen=True)
    source: ResearchSource
    content: str


class ResearchSourceProvider(Protocol):
    def search(
        self, question: ResearchQuestion, *, max_results: int
    ) -> tuple[ResearchSourceCandidate, ...]: ...
    def fetch(self, candidate: ResearchSourceCandidate) -> RetrievedResearchSource: ...
