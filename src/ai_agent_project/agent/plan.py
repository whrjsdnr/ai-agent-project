"""Provider-neutral implementation planning models and validation."""

from pathlib import PurePosixPath
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ai_agent_project.agent.specification import RequirementId, Specification
from ai_agent_project.agent.workspace import WorkspaceSnapshot
from ai_agent_project.command_policy import (
    CommandPolicyError,
    parse_safe_command,
    validation_command_instructions,
)

IMPLEMENTATION_PLANNER_INSTRUCTIONS = """Create an implementation plan from the
provided structured specification. Return only data matching the supplied JSON schema.
Do not invent requirements, files, dependencies, or validation commands that are not
supported by the source specification. Every task must reference the requirement IDs it
implements. Use dependencies only when one task must finish before another. List files
to inspect and files to modify separately when the source supports identifying them.
Validation commands must use the project's safe development command allowlist.
When a command directly validates one task's requirement(s), put it in that task's
validation_commands as well as (or instead of) the plan-wide commands. Do not attach
an unrelated suite command to a task merely to claim requirement evidence.
For a targeted pytest check use exactly `uv run pytest <one relative test path or node
id>`; do not add `-q`, `-k`, extra paths, or other pytest options.
Do not use git, grep, cat, find, or other shell inspection commands as validation.
For required document text use required_file_contents; for phase-local mutation limits use
allowed_changed_files. These are deterministic structured workspace validations.
""" + validation_command_instructions()


class ImplementationPlanValidationError(ValueError):
    """Raised when a plan cannot safely or completely implement a specification."""


class FileContentValidation(BaseModel):
    """One deterministic required-content assertion for a workspace file."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str = Field(min_length=1)
    required_fragments: list[str] = Field(default_factory=list)

    @field_validator("path")
    @classmethod
    def reject_unsafe_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("file content validation paths must be safe and relative")
        return value


class ImplementationTask(BaseModel):
    """One independently executable implementation step."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    title: str
    description: str = Field(min_length=1)
    requirement_ids: list[RequirementId] = Field(min_length=1)
    depends_on: list[str] = Field(default_factory=list)
    files_to_inspect: list[str] = Field(default_factory=list)
    files_to_modify: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)
    validation_commands: list[str] = Field(default_factory=list)
    required_file_contents: list[FileContentValidation] = Field(default_factory=list)
    allowed_changed_files: list[str] = Field(default_factory=list)

    @field_validator("requirement_ids")
    @classmethod
    def reject_blank_requirement_ids(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError(
                "ImplementationTask requirement_ids must not contain blank IDs"
            )
        return values

    @field_validator("allowed_changed_files")
    @classmethod
    def reject_unsafe_change_paths(cls, values: list[str]) -> list[str]:
        for value in values:
            path = PurePosixPath(value)
            if not value or path.is_absolute() or ".." in path.parts:
                raise ValueError(
                    "allowed_changed_files must contain safe relative paths"
                )
        return values


class ImplementationPlan(BaseModel):
    """A dependency-validated plan with requirement-to-task traceability."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    summary: str | None = None
    tasks: list[ImplementationTask] = Field(default_factory=list)
    validation_commands: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_dependencies_and_commands(self) -> "ImplementationPlan":
        """Require an acyclic task DAG and ShellTool-safe validation commands."""
        task_ids = [task.id for task in self.tasks]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("Implementation task IDs must be unique")

        known_task_ids = set(task_ids)
        dependencies = {task.id: task.depends_on for task in self.tasks}
        for task in self.tasks:
            for dependency in task.depends_on:
                if dependency not in known_task_ids:
                    raise ValueError(
                        f"Task {task.id!r} depends on unknown task {dependency!r}"
                    )
                if dependency == task.id:
                    raise ValueError(f"Task {task.id!r} cannot depend on itself")
        _validate_acyclic_dependencies(dependencies)

        for command in self.validation_commands:
            if command.startswith("git "):
                raise ValueError("Git commands are not executable validation commands")
            try:
                parse_safe_command(command)
            except CommandPolicyError as error:
                raise ValueError(
                    f"Unsafe validation command {command!r}: {error}"
                ) from error
        for task in self.tasks:
            for command in task.validation_commands:
                if command.startswith("git "):
                    raise ValueError(
                        "Git commands are not executable task validation commands"
                    )
                try:
                    parse_safe_command(command)
                except CommandPolicyError as error:
                    raise ValueError(
                        f"Unsafe validation command {command!r} for task {task.id!r}: {error}"
                    ) from error
        return self

    def validate_traceability(
        self, specification: Specification
    ) -> "ImplementationPlan":
        """Ensure every source requirement maps to at least one valid task."""
        source_ids = {requirement.id for requirement in specification.requirements}
        referenced_ids = {
            requirement_id
            for task in self.tasks
            for requirement_id in task.requirement_ids
        }
        unknown_ids = referenced_ids - source_ids
        if unknown_ids:
            raise ImplementationPlanValidationError(
                "Plan references unknown requirement IDs: "
                f"{', '.join(_display_requirement_id(item) for item in sorted(unknown_ids))}"
            )
        missing_ids = source_ids - referenced_ids
        if missing_ids:
            raise ImplementationPlanValidationError(
                "Plan has no task for requirement IDs: "
                f"{', '.join(sorted(missing_ids))}"
            )
        return self


def _display_requirement_id(value: str) -> str:
    return "<empty>" if not value else repr(value)


class ImplementationPlanner(Protocol):
    """Convert a parsed Specification into a validated ImplementationPlan."""

    def plan(
        self,
        specification: Specification,
        workspace: WorkspaceSnapshot | None = None,
    ) -> ImplementationPlan:
        """Return a plan with validated traceability and dependencies."""
        ...


def _validate_acyclic_dependencies(dependencies: dict[str, list[str]]) -> None:
    """Raise a clear error when the task dependency graph contains a cycle."""
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str) -> None:
        if task_id in visiting:
            raise ValueError(f"Task dependency cycle detected at {task_id!r}")
        if task_id in visited:
            return

        visiting.add(task_id)
        for dependency in dependencies[task_id]:
            visit(dependency)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in dependencies:
        visit(task_id)
