"""Provider-neutral compact descriptions of an existing workspace."""

from pathlib import PurePosixPath
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ai_agent_project.agent.workspace import WorkspaceSnapshot


class CodebaseFile(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str = Field(min_length=1)
    purpose: str
    language: str | None = None
    category: str | None = None

    @field_validator("path")
    @classmethod
    def require_safe_relative_path(cls, value: str) -> str:
        _validate_relative_path(value)
        return value


class CodebaseDependency(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    version: str | None = None
    source: str


class CodebaseComponent(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    kind: str
    files: tuple[str, ...] = ()
    responsibilities: tuple[str, ...] = ()


class ExistingFeature(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    title: str
    description: str
    related_files: tuple[str, ...] = ()


class CodebaseAnalysis(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_name: str | None = None
    project_type: str | None = None
    languages: tuple[str, ...] = ()
    entry_points: tuple[str, ...] = ()
    dependencies: tuple[CodebaseDependency, ...] = ()
    components: tuple[CodebaseComponent, ...] = ()
    existing_features: tuple[ExistingFeature, ...] = ()
    test_files: tuple[str, ...] = ()
    config_files: tuple[str, ...] = ()
    important_files: tuple[CodebaseFile, ...] = ()
    summary: str = ""
    risks: tuple[str, ...] = ()

    @field_validator("entry_points", "test_files", "config_files")
    @classmethod
    def require_safe_relative_paths(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            _validate_relative_path(value)
        return values


def _validate_relative_path(value: str) -> None:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts:
        raise ValueError("codebase paths must be workspace-relative and safe")


class CodebaseAnalyzer(Protocol):
    def analyze(self, workspace: WorkspaceSnapshot) -> CodebaseAnalysis:
        """Describe the supplied relative-only workspace inventory."""
        ...
