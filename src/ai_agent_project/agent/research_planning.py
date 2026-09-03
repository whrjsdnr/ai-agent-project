"""Provider-neutral planning of evidence-first research questions."""

from typing import Protocol

from ai_agent_project.agent.research import (
    ResearchDirection,
    ResearchDiscoveryReport,
    ResearchPlan,
    ResearchQuestion,
    ResearchRequest,
)
from ai_agent_project.agent.workspace import WorkspaceSnapshot


class ResearchQuestionPlanner(Protocol):
    def plan(
        self, request: ResearchRequest, workspace: WorkspaceSnapshot | None = None
    ) -> tuple[ResearchQuestion, ...]: ...


class ResearchPlanGenerator(Protocol):
    """Generate a planning-only plan for one authoritative selected direction."""

    def generate(
        self,
        request: ResearchRequest,
        direction: ResearchDirection,
        report: ResearchDiscoveryReport,
        *,
        revision_note: str | None = None,
    ) -> ResearchPlan: ...
