"""Read-only project-level descriptors for authoritative linked-run artifacts."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]


class ProjectArtifactSource(StrEnum):
    DEVELOPER = "developer"
    RESEARCHER = "researcher"


class ProjectArtifactType(StrEnum):
    SPECIFICATION = "specification"
    PROJECT_SPECIFICATION = "project_specification"
    IMPLEMENTATION_PLAN = "implementation_plan"
    PROJECT_PLAN = "project_plan"
    PROJECT_PLAN_REVISION = "project_plan_revision"
    PLAN_REVISION_HISTORY = "plan_revision_history"
    EXECUTION_STATE = "execution_state"
    UPGRADE_CONTEXT = "upgrade_context"

    RESEARCH_REQUEST = "research_request"
    DISCOVERY_REPORT = "discovery_report"
    SELECTED_DIRECTION = "selected_direction"
    RESEARCH_PLAN = "research_plan"
    RESEARCH_PLAN_REVISION = "research_plan_revision"
    RESEARCH_PLAN_HISTORY = "research_plan_history"
    RESEARCH_IMPLEMENTATION_PLAN = "research_implementation_plan"
    RESEARCH_IMPLEMENTATION_PACKAGE = "research_implementation_package"
    RESEARCH_GENERATED_FILE = "research_generated_file"
    RESEARCH_RESULTS = "research_results"
    RESEARCH_RESULT_ANALYSIS = "research_result_analysis"
    RESEARCH_SYNTHESIS = "research_synthesis"
    PAPER_MATERIALS = "paper_materials"


class ProjectArtifactDescriptor(BaseModel):
    model_config = ConfigDict(frozen=True)

    artifact_id: str = Field(min_length=1)
    artifact_type: ProjectArtifactType
    source_domain: ProjectArtifactSource
    source_run_id: str = Field(min_length=1)
    source_version: str = Field(min_length=1)
    title: str = Field(min_length=1)
    media_types: tuple[str, ...]


class ProjectArtifactCatalog(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_id: str = Field(min_length=1)
    artifacts: tuple[ProjectArtifactDescriptor, ...]


class ProjectArtifactView(BaseModel):
    model_config = ConfigDict(frozen=True)

    descriptor: ProjectArtifactDescriptor
    content: JsonValue
