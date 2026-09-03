"""Provider-neutral planning of evidence-first research questions."""

from typing import Protocol

from ai_agent_project.agent.research import (
    ResearchDirection,
    ResearchDiscoveryReport,
    ResearchImplementationPackage,
    ResearchImplementationPlan,
    ResearchPlan,
    ResearchQuestion,
    ResearchRequest,
    ResearchResultAnalysisPayload,
    ResearchResultSubmission,
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


class ResearchImplementationPlanner(Protocol):
    """Plan implementation artifacts without executing any research workload."""

    def plan(
        self,
        request: ResearchRequest,
        direction: ResearchDirection,
        approved_plan: ResearchPlan,
        approved_plan_version: int,
        report: ResearchDiscoveryReport,
    ) -> ResearchImplementationPlan: ...


class ResearchImplementationGenerator(Protocol):
    """Generate persisted artifact text only; never execute it."""

    def generate(
        self,
        request: ResearchRequest,
        direction: ResearchDirection,
        approved_plan: ResearchPlan,
        implementation_plan: ResearchImplementationPlan,
        report: ResearchDiscoveryReport,
    ) -> ResearchImplementationPackage: ...


class ResearchResultAnalyzer(Protocol):
    """Interpret supplied results only; it never executes a research workload."""

    def analyze(
        self,
        approved_plan: ResearchPlan,
        implementation_plan: ResearchImplementationPlan,
        submission: ResearchResultSubmission,
    ) -> ResearchResultAnalysisPayload: ...
