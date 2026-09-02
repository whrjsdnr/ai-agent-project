"""Provider-neutral orchestration from specification to coding-agent run."""

from pydantic import BaseModel, ConfigDict

from ai_agent_project.agent.acceptance import AcceptanceReport
from ai_agent_project.agent.acceptance_validator import (
    AcceptanceValidator,
    UnconfiguredAcceptanceValidator,
)
from ai_agent_project.agent.plan import ImplementationPlan, ImplementationPlanner
from ai_agent_project.agent.service import AgentService
from ai_agent_project.agent.specification import Specification
from ai_agent_project.agent.specification_parser import SpecificationParser
from ai_agent_project.agent.state import AgentState


class CodingRunResult(BaseModel):
    """The successful parse and plan context for one coding-agent run."""

    model_config = ConfigDict(frozen=True)

    specification: Specification
    plan: ImplementationPlan
    agent_run: AgentState
    acceptance_report: AcceptanceReport


class CodingAgentService:
    """Coordinate parsing, planning, and one generic AgentService execution."""

    def __init__(
        self,
        specification_parser: SpecificationParser,
        planner: ImplementationPlanner,
        agent_service: AgentService,
        acceptance_validator: AcceptanceValidator | None = None,
    ) -> None:
        self._specification_parser = specification_parser
        self._planner = planner
        self._agent_service = agent_service
        self._acceptance_validator = acceptance_validator or UnconfiguredAcceptanceValidator()

    def run_from_specification(self, specification_text: str) -> CodingRunResult:
        """Parse and plan source text, then execute the full plan in one agent run."""
        specification = self._specification_parser.parse(specification_text)
        plan = self._planner.plan(specification)
        instruction = build_coding_instruction(specification, plan)
        agent_run = self._agent_service.run(instruction)
        acceptance_report = self._acceptance_validator.validate(
            specification,
            plan,
            agent_run,
        )
        return CodingRunResult(
            specification=specification,
            plan=plan,
            agent_run=agent_run,
            acceptance_report=acceptance_report,
        )


def build_coding_instruction(
    specification: Specification,
    plan: ImplementationPlan,
) -> str:
    """Render provider-neutral specification and plan context for the coding agent."""
    lines = [
        "Implement the following specification and implementation plan.",
        "",
        "Specification:",
    ]
    if specification.project_name:
        lines.append(f"Project: {specification.project_name}")
    if specification.summary:
        lines.append(f"Summary: {specification.summary}")
    for requirement in specification.requirements:
        title = f" — {requirement.title}" if requirement.title else ""
        lines.extend(
            [
                f"\nRequirement {requirement.id}{title}",
                requirement.description,
            ]
        )
        if requirement.acceptance_criteria:
            lines.append("Acceptance criteria:")
            lines.extend(f"- {criterion}" for criterion in requirement.acceptance_criteria)

    if specification.constraints:
        lines.extend(["\nConstraints:", *[f"- {item}" for item in specification.constraints]])
    if specification.assumptions:
        lines.extend(["\nAssumptions:", *[f"- {item}" for item in specification.assumptions]])

    lines.extend(["\nImplementation Plan:"])
    if plan.summary:
        lines.append(f"Summary: {plan.summary}")
    for task in plan.tasks:
        lines.extend(
            [
                f"\nTask {task.id}: {task.title}",
                f"Requirements: {', '.join(task.requirement_ids)}",
                f"Description: {task.description}",
            ]
        )
        if task.depends_on:
            lines.append(f"Dependencies: {', '.join(task.depends_on)}")
        _append_paths(lines, "Files to inspect", task.files_to_inspect)
        _append_paths(lines, "Files to modify", task.files_to_modify)
        _append_paths(lines, "Files to inspect or modify", task.files)

    if plan.validation_commands:
        lines.extend(["\nValidation commands:"])
        lines.extend(f"- {command}" for command in plan.validation_commands)

    lines.extend(
        [
            "\nAgent execution rules:",
            "- Inspect the actual project before modifying files.",
            "- Treat the plan as guidance; actual project structure takes precedence.",
            "- Make the smallest changes that satisfy the requirements.",
            "- Add or update tests when needed.",
            "- Run the validation commands after changes; investigate failures, fix them, and rerun validation.",
            "- Summarize the completed work and validation results in the final answer.",
        ]
    )
    return "\n".join(lines)


def _append_paths(lines: list[str], heading: str, paths: list[str]) -> None:
    """Append a labeled path list only when the planner supplied one."""
    if paths:
        lines.append(f"{heading}:")
        lines.extend(f"- {path}" for path in paths)
