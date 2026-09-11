"""Opt-in production wiring test for the repair-loop orchestration."""

import os
from pathlib import Path

import pytest

from ai_agent_project.agent.acceptance import (
    AcceptanceCriterionResult,
    AcceptanceReport,
    AcceptanceStatus,
    RequirementValidationResult,
)
from ai_agent_project.agent.coding_service import CodingAgentService
from ai_agent_project.agent.workspace import FilesystemWorkspaceInspector
from ai_agent_project.agent.workspace_acceptance import WorkspaceAcceptanceValidator
from ai_agent_project.api.app import create_default_agent_service
from ai_agent_project.llm.providers.openai_planner import OpenAIImplementationPlanner
from ai_agent_project.llm.providers.openai_specification import (
    OpenAISpecificationParser,
)


class FailOnceAcceptanceValidator:
    """Test-only wrapper that makes the first report repairable, then delegates."""

    def __init__(self, delegate: WorkspaceAcceptanceValidator) -> None:
        self._delegate = delegate
        self.call_count = 0

    def validate(
        self, specification: object, plan: object, agent_state: object
    ) -> AcceptanceReport:
        self.call_count += 1
        if self.call_count > 1:
            return self._delegate.validate(specification, plan, agent_state)  # type: ignore[arg-type]
        requirement = specification.requirements[0]  # type: ignore[union-attr]
        return AcceptanceReport(
            requirements=[
                RequirementValidationResult(
                    requirement_id=requirement.id,
                    status=AcceptanceStatus.FAILED,
                    criteria=[
                        AcceptanceCriterionResult(
                            criterion="All tests must pass.",
                            status=AcceptanceStatus.FAILED,
                            evidence=[
                                "Forced initial acceptance failure for repair-loop E2E validation."
                            ],
                        )
                    ],
                    evidence=[
                        "Forced initial acceptance failure for repair-loop E2E validation."
                    ],
                )
            ]
        )


@pytest.mark.skipif(
    os.getenv("RUN_OPENAI_E2E") != "1",
    reason="requires explicit OpenAI E2E opt-in",
)
def test_production_repair_loop_revalidates_workspace() -> None:
    root = Path(__file__).resolve().parents[2]
    delegate = WorkspaceAcceptanceValidator(root)
    validator = FailOnceAcceptanceValidator(delegate)
    service = CodingAgentService(
        OpenAISpecificationParser(),
        OpenAIImplementationPlanner(),
        create_default_agent_service(root),
        validator,
        max_repair_attempts=1,
        workspace_inspector=FilesystemWorkspaceInspector(root),
    )
    result = service.run_from_specification(
        """# Requirements
## REQ-REPAIR-E2E Digit validation
Ensure is_digits_only has these acceptance criteria:
- is_digits_only(\"12345\") returns True
- is_digits_only(\"12a45\") returns False
- is_digits_only(\"\") returns False
- is_digits_only(\"１２３\") returns False
- Pytest tests are added that cover the above cases and the updated behavior.
- All tests must pass.
"""
    )

    assert len(result.repair_attempts) == 1
    assert result.repair_attempts[0].attempt == 1
    # The requirement id may include a human-readable title. Accept any id
    # that contains the requirement short id "REQ-REPAIR-E2E" to be robust.
    assert any(
        "REQ-REPAIR-E2E" in rid
        for rid in result.repair_attempts[0].failed_requirement_ids
    )
    assert result.repair_attempts[0].agent_run.status.value == "completed"
    assert result.acceptance_report.status is AcceptanceStatus.PASSED
    assert validator.call_count == 2
