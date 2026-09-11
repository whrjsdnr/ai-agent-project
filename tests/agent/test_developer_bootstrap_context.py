"""Tests for the bounded, neutral Developer bootstrap context."""

import pytest
from pydantic import ValidationError

from ai_agent_project.agent.developer_bootstrap_context import (
    DEVELOPER_BOOTSTRAP_CONTEXT_MAX_BYTES,
    DeveloperBootstrapContext,
)


def test_context_is_frozen_and_structured() -> None:
    context = DeveloperBootstrapContext(
        source_label="verified-research-handoff",
        artifact_type="research_synthesis",
        source_version="v1",
        content={"directions": ["use evidence"]},
    )
    with pytest.raises(ValidationError):
        context.source_label = "changed"


def test_context_rejects_oversized_canonical_json() -> None:
    with pytest.raises(ValidationError, match="131072"):
        DeveloperBootstrapContext(
            source_label="verified-research-handoff",
            artifact_type="research_generated_file",
            source_version="v1",
            content={"content": "x" * DEVELOPER_BOOTSTRAP_CONTEXT_MAX_BYTES},
        )
