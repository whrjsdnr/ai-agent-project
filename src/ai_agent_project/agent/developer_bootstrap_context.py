"""Domain-neutral, bounded context supplied to Developer planning."""

import json

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_agent_project.agent.project_artifact import JsonValue

DEVELOPER_BOOTSTRAP_CONTEXT_SOURCE = "verified-research-handoff"
DEVELOPER_BOOTSTRAP_CONTEXT_MAX_BYTES = 131_072


class DeveloperBootstrapContext(BaseModel):
    """Immutable supporting data; it carries no workflow authority."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_label: str = Field(min_length=1)
    artifact_type: str = Field(min_length=1)
    source_version: str = Field(min_length=1)
    content: JsonValue

    @model_validator(mode="after")
    def enforce_size(self) -> "DeveloperBootstrapContext":
        encoded = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(encoded) > DEVELOPER_BOOTSTRAP_CONTEXT_MAX_BYTES:
            raise ValueError(
                "Developer bootstrap context exceeds the 131072-byte limit"
            )
        return self
