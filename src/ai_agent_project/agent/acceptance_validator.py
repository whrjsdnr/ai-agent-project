"""Provider-neutral acceptance-validator interface."""

from typing import Protocol

from ai_agent_project.agent.acceptance import (
    AcceptanceReport,
    AcceptanceStatus,
    RequirementValidationResult,
)
from ai_agent_project.agent.plan import ImplementationPlan
from ai_agent_project.agent.specification import Specification
from ai_agent_project.agent.state import AgentState


class AcceptanceValidator(Protocol):
    """Independently validate a coding run against its source specification."""

    def validate(
        self,
        specification: Specification,
        plan: ImplementationPlan,
        agent_state: AgentState,
    ) -> AcceptanceReport:
        """Return an evidence-backed acceptance report."""
        ...


class UnconfiguredAcceptanceValidator:
    """Conservative fallback for direct service construction without a workspace."""

    def validate(
        self,
        specification: Specification,
        plan: ImplementationPlan,
        agent_state: AgentState,
    ) -> AcceptanceReport:
        """Return UNKNOWN rather than trusting an unverified agent run."""
        del plan, agent_state
        return AcceptanceReport(
            requirements=[
                RequirementValidationResult(
                    requirement_id=requirement.id,
                    status=AcceptanceStatus.UNKNOWN,
                    notes="No workspace acceptance validator was configured.",
                )
                for requirement in specification.requirements
            ],
            notes=["Acceptance validation requires a configured workspace validator."],
        )
