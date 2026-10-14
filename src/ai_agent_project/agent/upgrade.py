"""Provider-neutral upgrade request, impact, and specification models."""

from enum import StrEnum
from pathlib import PurePosixPath
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ai_agent_project.agent.codebase_analysis import CodebaseAnalysis
from ai_agent_project.agent.specification import Requirement
from ai_agent_project.agent.workspace import WorkspaceSnapshot


class ProjectMode(StrEnum):
    NEW = "new"
    UPGRADE = "upgrade"


class UpgradeRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    request_text: str = Field(min_length=1)
    title: str | None = None


class UpgradeImpact(BaseModel):
    model_config = ConfigDict(frozen=True)

    affected_components: tuple[str, ...] = ()
    affected_files: tuple[str, ...] = ()
    affected_features: tuple[str, ...] = ()
    new_dependencies: tuple[str, ...] = ()
    migration_risks: tuple[str, ...] = ()
    regression_risks: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @field_validator("affected_files")
    @classmethod
    def require_safe_relative_paths(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            path = PurePosixPath(value)
            if not value or path.is_absolute() or ".." in path.parts:
                raise ValueError("affected files must be workspace-relative and safe")
        return values


class UpgradeSpecification(BaseModel):
    model_config = ConfigDict(frozen=True)

    title: str
    objective: str
    current_system_summary: str
    requirements: tuple[Requirement, ...] = Field(min_length=1)
    constraints: tuple[str, ...] = ()
    acceptance_criteria: tuple[str, ...] = ()
    impact: UpgradeImpact


class BaselineStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


class BaselineValidation(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: BaselineStatus
    commands: tuple[str, ...] = ()
    details: tuple[str, ...] = ()


class UpgradeContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    request: UpgradeRequest
    codebase_analysis: CodebaseAnalysis
    upgrade_specification: UpgradeSpecification
    baseline_validation: BaselineValidation


class UpgradeAnalyzer(Protocol):
    def analyze(
        self,
        codebase: CodebaseAnalysis,
        request: UpgradeRequest,
        workspace: WorkspaceSnapshot | None = None,
    ) -> UpgradeSpecification:
        """Translate an upgrade request into measurable requirements and risks."""
        ...
