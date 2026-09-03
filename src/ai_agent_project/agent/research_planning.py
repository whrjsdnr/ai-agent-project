"""Provider-neutral planning of evidence-first research questions."""

from typing import Protocol

from ai_agent_project.agent.research import ResearchQuestion, ResearchRequest
from ai_agent_project.agent.workspace import WorkspaceSnapshot


class ResearchQuestionPlanner(Protocol):
    def plan(
        self, request: ResearchRequest, workspace: WorkspaceSnapshot | None = None
    ) -> tuple[ResearchQuestion, ...]: ...
