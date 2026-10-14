"""Provider-free API acceptance for Phase 5A.

The environment's TestClient hangs even on /health; route callables are exercised
directly after the app has registered the real endpoint definitions.
"""

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from ai_agent_project.agent.project_artifact import (
    ProjectArtifactDescriptor,
    ProjectArtifactSource,
    ProjectArtifactType,
    ProjectArtifactView,
)
from ai_agent_project.agent.project_session import ProjectStatus
from ai_agent_project.api.app import CreateProjectHandoffRequest, create_app
from tests.agent.test_project_handoff import _project, _service

service, _store = _service()
app = create_app(project_handoff_service=service)  # type: ignore[arg-type]
post = next(
    r.endpoint
    for r in app.routes
    if r.path == "/v1/projects/{project_id}/handoffs" and "POST" in r.methods
)
get = next(
    r.endpoint
    for r in app.routes
    if r.path == "/v1/projects/{project_id}/handoffs" and "GET" in r.methods
)

created = post(
    "project-1",
    CreateProjectHandoffRequest(
        artifact_id="artifact-1", purpose="developer-bootstrap-context"
    ),
)
assert created.project_id == "project-1"
assert created.source_domain.value == "researcher"
assert "content" not in created.model_dump()
assert (
    post(
        "project-1",
        CreateProjectHandoffRequest(
            artifact_id="artifact-1", purpose="developer-bootstrap-context"
        ),
    )
    == created
)
assert len(get("project-1").handoffs) == 1

for payload in (
    {
        "artifact_id": "artifact-1",
        "purpose": "developer-bootstrap-context",
        "to": "researcher",
    },
    {"artifact_id": "artifact-1", "purpose": "unsupported"},
    {
        "artifact_id": "artifact-1",
        "purpose": "developer-bootstrap-context",
        "source_run_id": "forged",
    },
    {
        "artifact_id": "artifact-1",
        "purpose": "developer-bootstrap-context",
        "source_domain": "developer",
    },
):
    with pytest.raises(ValidationError):
        CreateProjectHandoffRequest.model_validate(payload)

# Real service rejection paths: foreign/unowned and unsupported artifacts.
service._artifacts.entries["foreign"] = ProjectArtifactView(
    descriptor=ProjectArtifactDescriptor(
        artifact_id="foreign",
        artifact_type=ProjectArtifactType.RESEARCH_SYNTHESIS,
        source_domain=ProjectArtifactSource.RESEARCHER,
        source_run_id="other-run",
        source_version="v1",
        title="Foreign",
        media_types=("application/json",),
    ),
    content={"x": 1},
)
with pytest.raises(HTTPException) as foreign_error:
    post(
        "project-1",
        CreateProjectHandoffRequest(
            artifact_id="foreign", purpose="developer-bootstrap-context"
        ),
    )
assert foreign_error.value.status_code == 409
service._artifacts.entries["unsupported"] = ProjectArtifactView(
    descriptor=service._artifacts.entries["artifact-1"].descriptor.model_copy(
        update={
            "artifact_id": "unsupported",
            "artifact_type": ProjectArtifactType.EXECUTION_STATE,
        }
    ),
    content={"x": 1},
)
with pytest.raises(HTTPException) as unsupported_error:
    post(
        "project-1",
        CreateProjectHandoffRequest(
            artifact_id="unsupported", purpose="developer-bootstrap-context"
        ),
    )
assert unsupported_error.value.status_code == 409

# Completion blocks new registration while preserving the existing read model.
service._project_sessions._store.replace(
    "project-1", _project(status=ProjectStatus.COMPLETED)
)
assert len(get("project-1").handoffs) == 1
with pytest.raises(HTTPException) as completed_error:
    post(
        "project-1",
        CreateProjectHandoffRequest(
            artifact_id="artifact-1", purpose="developer-bootstrap-context"
        ),
    )
assert completed_error.value.status_code == 409

print("PHASE_5A_API_ACCEPTANCE=PASSED")
