"""HTTP interface tests for Phase 5A's metadata-only handoff surface."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from ai_agent_project.agent.project_artifact import ProjectArtifactSource
from ai_agent_project.agent.project_handoff import (
    ProjectHandoff,
    ProjectHandoffList,
    ProjectHandoffPurpose,
)
from ai_agent_project.api.app import CreateProjectHandoffRequest, create_app
from ai_agent_project.cli import _build_parser


class _HandoffAPI:
    def __init__(self) -> None:
        self.handoff = ProjectHandoff(
            handoff_id="00000000-0000-0000-0000-000000000001",
            project_id="p",
            source_domain=ProjectArtifactSource.RESEARCHER,
            source_run_id="r",
            artifact_id="a",
            content_sha256="0" * 64,
            purpose=ProjectHandoffPurpose.DEVELOPER_BOOTSTRAP_CONTEXT,
            created_at=datetime.now(UTC),
        )

    def register(
        self, project_id: str, artifact_id: str, purpose: ProjectHandoffPurpose
    ) -> ProjectHandoff:
        assert project_id == "p"
        assert artifact_id == "a"
        assert purpose is ProjectHandoffPurpose.DEVELOPER_BOOTSTRAP_CONTEXT
        return self.handoff

    def list_handoffs(self, project_id: str) -> ProjectHandoffList:
        return ProjectHandoffList(project_id=project_id, handoffs=())


def test_handoff_endpoints_are_metadata_only_and_provider_free() -> None:
    api = _HandoffAPI()
    app = create_app(project_handoff_service=api)  # type: ignore[arg-type]
    create_route = next(
        route
        for route in app.routes
        if route.path == "/v1/projects/{project_id}/handoffs"
        and "POST" in route.methods
    )
    list_route = next(
        route
        for route in app.routes
        if route.path == "/v1/projects/{project_id}/handoffs" and "GET" in route.methods
    )
    created = create_route.endpoint(
        "p",
        CreateProjectHandoffRequest(
            artifact_id="a", purpose=ProjectHandoffPurpose.DEVELOPER_BOOTSTRAP_CONTEXT
        ),
    )
    assert created.source_domain is ProjectArtifactSource.RESEARCHER
    assert "content" not in created.model_dump()
    assert list_route.endpoint("p").handoffs == ()
    with pytest.raises(ValidationError):
        CreateProjectHandoffRequest.model_validate(
            {
                "artifact_id": "a",
                "purpose": "developer-bootstrap-context",
                "to": "researcher",
            }
        )
    with pytest.raises(ValidationError):
        CreateProjectHandoffRequest.model_validate(
            {
                "artifact_id": "a",
                "purpose": "developer-bootstrap-context",
                "source_run_id": "forged",
            }
        )


def test_cli_exposes_only_explicit_handoff_commands() -> None:
    parser = _build_parser()
    parsed = parser.parse_args(
        [
            "project-session",
            "handoff-artifact",
            "p",
            "a",
            "--to",
            "developer",
            "--purpose",
            "developer-bootstrap-context",
        ]
    )
    assert parsed.command == "handoff-artifact"
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "project-session",
                "handoff-artifact",
                "p",
                "a",
                "--to",
                "researcher",
                "--purpose",
                "developer-bootstrap-context",
            ]
        )
