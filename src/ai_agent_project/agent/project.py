"""Provider-neutral project-level specification and milestone planning models."""

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_agent_project.agent.plan import ImplementationPlan
from ai_agent_project.agent.specification import Requirement, Specification
from ai_agent_project.agent.workspace import WorkspaceSnapshot


class ProjectSpecification(BaseModel):
    model_config = ConfigDict(frozen=True)

    title: str
    objective: str
    requirements: tuple[Requirement, ...] = Field(min_length=1)
    constraints: tuple[str, ...] = ()
    acceptance_criteria: tuple[str, ...] = ()
    source_format: str | None = None

    @classmethod
    def from_specification(cls, specification: Specification) -> "ProjectSpecification":
        return cls(
            title=specification.project_name or "Untitled Project",
            objective=specification.summary or "",
            requirements=tuple(specification.requirements),
            constraints=tuple(specification.constraints),
        )


class ProjectPhase(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    title: str
    objective: str
    requirement_ids: tuple[str, ...]
    task_ids: tuple[str, ...]
    depends_on: tuple[str, ...] = ()
    acceptance_criteria: tuple[str, ...] = ()


class ProjectPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_title: str
    phases: tuple[ProjectPhase, ...]
    implementation_plan: ImplementationPlan

    @model_validator(mode="after")
    def validate_traceability(self) -> "ProjectPlan":
        """Validate phase IDs, the phase DAG, and complete task assignment."""
        phase_ids = [phase.id for phase in self.phases]
        if len(phase_ids) != len(set(phase_ids)):
            raise ValueError("Project phase IDs must be unique")

        task_ids = {task.id for task in self.implementation_plan.tasks}
        assigned = [task_id for phase in self.phases for task_id in phase.task_ids]
        unknown_task_ids = set(assigned) - task_ids
        if unknown_task_ids:
            raise ValueError("Project phase references unknown task IDs")
        duplicate_task_ids = {
            task_id for task_id in assigned if assigned.count(task_id) > 1
        }
        if duplicate_task_ids:
            raise ValueError(
                "Every implementation task must belong to exactly one phase"
            )
        missing_task_ids = task_ids - set(assigned)
        if missing_task_ids:
            raise ValueError(
                "Every implementation task must belong to exactly one phase"
            )

        known = set(phase_ids)
        for phase in self.phases:
            if any(dependency not in known for dependency in phase.depends_on):
                raise ValueError("Project phase depends on an unknown phase")
        _assert_acyclic({phase.id: phase.depends_on for phase in self.phases})
        return self

    def validate_against(self, specification: ProjectSpecification) -> "ProjectPlan":
        requirements = {requirement.id for requirement in specification.requirements}
        covered = {item for phase in self.phases for item in phase.requirement_ids}
        if not covered <= requirements:
            raise ValueError("Project phase references unknown requirement IDs")
        if covered != requirements:
            raise ValueError("Every requirement must be covered by a phase")
        return self


class ProjectPlanner(Protocol):
    def plan(
        self,
        specification: ProjectSpecification,
        implementation_plan: ImplementationPlan,
        workspace: WorkspaceSnapshot | None = None,
    ) -> ProjectPlan:
        """Group a validated implementation plan into project phases."""
        ...


def _assert_acyclic(dependencies: dict[str, tuple[str, ...]]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            raise ValueError("Project phase dependency cycle detected")
        if node in visited:
            return

        visiting.add(node)
        for dependency in dependencies[node]:
            visit(dependency)
        visiting.remove(node)
        visited.add(node)

    for node in dependencies:
        visit(node)
