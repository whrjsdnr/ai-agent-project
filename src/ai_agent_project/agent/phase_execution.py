"""Provider-neutral execution of one already-planned project phase."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from ai_agent_project.agent.acceptance import AcceptanceReport, AcceptanceStatus
from ai_agent_project.agent.acceptance_validator import AcceptanceValidator
from ai_agent_project.agent.coding_service import (
    RepairAttempt,
    build_coding_instruction,
    build_repair_instruction,
)
from ai_agent_project.agent.plan import ImplementationPlan, ImplementationTask
from ai_agent_project.agent.project import (
    ProjectPhase,
    ProjectPlan,
    ProjectSpecification,
)
from ai_agent_project.agent.service import AgentService
from ai_agent_project.agent.specification import Specification
from ai_agent_project.agent.state import AgentState, AgentStatus


class PhaseExecutionStatus(StrEnum):
    """Outcome of one phase execution and its independent acceptance check."""

    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    UNKNOWN = "unknown"


class PhaseExecutionResult(BaseModel):
    """Immutable evidence-backed result for one ProjectPhase."""

    model_config = ConfigDict(frozen=True)

    phase_id: str
    status: PhaseExecutionStatus
    requirement_ids: tuple[str, ...]
    task_ids: tuple[str, ...]
    agent_run: AgentState
    acceptance_report: AcceptanceReport
    repair_attempts: tuple[RepairAttempt, ...] = ()
    summary: str | None = None


class PhaseExecutionService:
    """Execute, validate, and boundedly repair one pre-planned project phase."""

    def __init__(
        self,
        agent_service: AgentService,
        acceptance_validator: AcceptanceValidator,
        *,
        max_repair_attempts: int = 2,
    ) -> None:
        if max_repair_attempts < 0:
            raise ValueError("max_repair_attempts must be zero or greater")
        self._agent_service = agent_service
        self._acceptance_validator = acceptance_validator
        self._max_repair_attempts = max_repair_attempts

    def execute(
        self,
        specification: Specification,
        project_specification: ProjectSpecification,
        project_plan: ProjectPlan,
        phase_id: str,
    ) -> PhaseExecutionResult:
        """Execute only ``phase_id`` from an already validated project plan.

        Phase dependencies remain context only: this service has no execution history,
        so it neither runs dependencies nor claims they have completed.
        """
        project_plan.validate_against(project_specification)
        phase = _find_phase(project_plan, phase_id)
        scoped_specification = build_phase_specification(specification, phase)
        scoped_plan = build_phase_implementation_plan(project_plan, phase)
        scoped_plan.validate_traceability(scoped_specification)

        agent_run = self._agent_service.run(
            build_phase_coding_instruction(phase, scoped_specification, scoped_plan)
        )
        acceptance_report = self._validate(scoped_specification, scoped_plan, agent_run)
        repair_attempts: list[RepairAttempt] = []

        for attempt in range(1, self._max_repair_attempts + 1):
            failed_requirements = _failed_requirement_ids(
                acceptance_report, phase.requirement_ids
            )
            if not failed_requirements or agent_run.status is AgentStatus.FAILED:
                break

            repair_instruction = build_repair_instruction(
                scoped_specification,
                scoped_plan,
                acceptance_report,
                attempt,
            )
            agent_run = self._agent_service.run(
                _phase_prefix(phase) + "\n\n" + repair_instruction
            )
            acceptance_report = self._validate(
                scoped_specification, scoped_plan, agent_run
            )
            repair_attempts.append(
                RepairAttempt(
                    attempt=attempt,
                    failed_requirement_ids=failed_requirements,
                    agent_run=agent_run,
                    acceptance_report=acceptance_report,
                )
            )

        return PhaseExecutionResult(
            phase_id=phase.id,
            status=_phase_status(phase, agent_run, acceptance_report),
            requirement_ids=phase.requirement_ids,
            task_ids=phase.task_ids,
            agent_run=agent_run,
            acceptance_report=acceptance_report,
            repair_attempts=tuple(repair_attempts),
            summary=agent_run.final_answer,
        )

    def _validate(
        self,
        specification: Specification,
        plan: ImplementationPlan,
        agent_run: AgentState,
    ) -> AcceptanceReport:
        return self._acceptance_validator.validate(specification, plan, agent_run)


def build_phase_specification(
    specification: Specification,
    phase: ProjectPhase,
) -> Specification:
    """Return the selected phase requirements with global context unchanged."""
    requirements = [
        requirement
        for requirement in specification.requirements
        if requirement.id in phase.requirement_ids
    ]
    if len(requirements) != len(phase.requirement_ids):
        raise ValueError("Phase references requirement IDs absent from Specification")
    return specification.model_copy(update={"requirements": requirements})


def build_phase_implementation_plan(
    project_plan: ProjectPlan,
    phase: ProjectPhase,
) -> ImplementationPlan:
    """Return selected tasks while retaining only same-phase dependencies.

    Dependencies on tasks in other phases stay in the original ProjectPlan but are
    omitted from the scoped plan, where they are treated as external prerequisites.
    This service does not prove that those prerequisites are complete.
    """
    task_ids = set(phase.task_ids)
    selected_tasks = [
        _scoped_task(task, task_ids)
        for task in project_plan.implementation_plan.tasks
        if task.id in task_ids
    ]
    if len(selected_tasks) != len(phase.task_ids):
        raise ValueError("Phase references task IDs absent from ImplementationPlan")

    phase_requirement_ids = set(phase.requirement_ids)
    unexpected_requirement_ids = {
        requirement_id
        for task in selected_tasks
        for requirement_id in task.requirement_ids
        if requirement_id not in phase_requirement_ids
    }
    if unexpected_requirement_ids:
        raise ValueError(
            "Phase tasks reference requirements outside the selected phase"
        )

    scoped_plan = ImplementationPlan(
        summary=project_plan.implementation_plan.summary,
        tasks=selected_tasks,
        validation_commands=list(project_plan.implementation_plan.validation_commands),
    )
    return scoped_plan


def build_phase_coding_instruction(
    phase: ProjectPhase,
    specification: Specification,
    plan: ImplementationPlan,
) -> str:
    """Add concise phase boundaries around the existing generic coding instruction."""
    return "\n".join(
        [
            _phase_prefix(phase),
            "Implement only this phase. Do not implement future phase tasks or unrelated requirements.",
            "Follow the scoped implementation plan and run its allowed validation commands.",
            "",
            build_coding_instruction(specification, plan),
        ]
    )


def _find_phase(project_plan: ProjectPlan, phase_id: str) -> ProjectPhase:
    for phase in project_plan.phases:
        if phase.id == phase_id:
            return phase
    raise ValueError(f"Unknown project phase ID: {phase_id}")


def _scoped_task(
    task: ImplementationTask, selected_task_ids: set[str]
) -> ImplementationTask:
    return task.model_copy(
        update={
            "depends_on": [
                dependency
                for dependency in task.depends_on
                if dependency in selected_task_ids
            ]
        }
    )


def _phase_prefix(phase: ProjectPhase) -> str:
    lines = [
        f"Current phase: {phase.id} — {phase.title}",
        f"Phase objective: {phase.objective}",
        f"Assigned requirement IDs: {', '.join(phase.requirement_ids)}",
        f"Assigned task IDs: {', '.join(phase.task_ids)}",
    ]
    if phase.depends_on:
        lines.append(
            "Phase dependencies (context only; completion is not asserted): "
            + ", ".join(phase.depends_on)
        )
    if phase.acceptance_criteria:
        lines.append("Phase acceptance criteria:")
        lines.extend(f"- {criterion}" for criterion in phase.acceptance_criteria)
    return "\n".join(lines)


def _failed_requirement_ids(
    report: AcceptanceReport,
    phase_requirement_ids: tuple[str, ...],
) -> list[str]:
    phase_ids = set(phase_requirement_ids)
    return [
        requirement.requirement_id
        for requirement in report.requirements
        if requirement.requirement_id in phase_ids
        and requirement.status is AcceptanceStatus.FAILED
    ]


def _phase_status(
    phase: ProjectPhase,
    agent_run: AgentState,
    report: AcceptanceReport,
) -> PhaseExecutionStatus:
    if agent_run.status is AgentStatus.FAILED:
        return PhaseExecutionStatus.FAILED

    statuses = {
        requirement.requirement_id: requirement.status
        for requirement in report.requirements
        if requirement.requirement_id in phase.requirement_ids
    }
    if any(status is AcceptanceStatus.FAILED for status in statuses.values()):
        return PhaseExecutionStatus.FAILED
    if all(
        statuses.get(requirement_id) is AcceptanceStatus.PASSED
        for requirement_id in phase.requirement_ids
    ):
        return PhaseExecutionStatus.COMPLETED
    return PhaseExecutionStatus.UNKNOWN
