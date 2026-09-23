import json
from io import StringIO
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from test_research_paper_materials import _payload, _ready_service

from ai_agent_project.agent.project_artifact import ProjectArtifactType
from ai_agent_project.agent.project_artifact_application import ProjectArtifactService
from ai_agent_project.agent.project_session import ProjectModeProposal
from ai_agent_project.agent.project_session_application import ProjectSessionService
from ai_agent_project.agent.project_session_file_store import FileProjectStore
from ai_agent_project.agent.research import ResearchStatus, WorkMode
from ai_agent_project.agent.research_file_store import (
    FileResearchRunStore,
    default_research_run_store_root,
)
from ai_agent_project.agent.upgrade import ProjectMode
from ai_agent_project.api.app import create_app
from ai_agent_project.cli import run_cli


class _PaperGenerator:
    def generate(self, *args: object) -> object:
        return _payload()


class _Proposer:
    def __init__(self) -> None:
        self.calls = 0

    def propose(self, _request: str) -> ProjectModeProposal:
        self.calls += 1
        return ProjectModeProposal(
            proposed_work_mode=WorkMode.RESEARCHER,
            proposed_project_mode=ProjectMode.NEW,
            rationale="Advisory",
        )


class _FailingProposer:
    def propose(self, _request: str) -> ProjectModeProposal:
        raise AssertionError("artifact read called a provider")


def _terminal_research_run():
    service, _ = _ready_service(_PaperGenerator())
    run = service.generate_paper_materials("run").research_run
    assert run.status is ResearchStatus.PAPER_MATERIALS_READY
    return run


def test_research_catalog_and_exact_inspection_are_provider_free(
    tmp_path: Path, monkeypatch
) -> None:
    isolated_home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(isolated_home))
    project_root = tmp_path / "projects"
    research_store = FileResearchRunStore(default_research_run_store_root())
    run_id = str(uuid4())
    run = _terminal_research_run()
    research_store.create(run_id, run)

    proposer = _Proposer()
    setup = ProjectSessionService(FileProjectStore(project_root), proposer)
    project_id = setup.create_project_request("Research project").id
    setup.confirm_project_mode(project_id, WorkMode.RESEARCHER, ProjectMode.NEW)
    before = setup.bind_research_run(project_id, run_id).project

    read_service = ProjectSessionService(
        FileProjectStore(project_root),
        _FailingProposer(),
        research_run_reader=FileResearchRunStore(default_research_run_store_root()),
    )
    artifact_service = ProjectArtifactService(
        read_service,
        research_reader=FileResearchRunStore(default_research_run_store_root()),
    )
    catalog = artifact_service.list_artifacts(project_id)
    types = tuple(item.artifact_type for item in catalog.artifacts)
    assert types == (
        ProjectArtifactType.RESEARCH_REQUEST,
        ProjectArtifactType.DISCOVERY_REPORT,
        ProjectArtifactType.SELECTED_DIRECTION,
        ProjectArtifactType.RESEARCH_PLAN,
        ProjectArtifactType.RESEARCH_PLAN_REVISION,
        ProjectArtifactType.RESEARCH_PLAN_HISTORY,
        ProjectArtifactType.RESEARCH_IMPLEMENTATION_PLAN,
        ProjectArtifactType.RESEARCH_IMPLEMENTATION_PACKAGE,
        *(
            ProjectArtifactType.RESEARCH_GENERATED_FILE
            for _ in run.implementation_package.artifacts
        ),
        ProjectArtifactType.RESEARCH_RESULTS,
        ProjectArtifactType.RESEARCH_RESULT_ANALYSIS,
        ProjectArtifactType.RESEARCH_SYNTHESIS,
        ProjectArtifactType.PAPER_MATERIALS,
    )
    generated = [
        item
        for item in catalog.artifacts
        if item.artifact_type is ProjectArtifactType.RESEARCH_GENERATED_FILE
    ]
    assert [item.source_version.rsplit(":", 1)[-1] for item in generated] == [
        item.artifact_id for item in run.implementation_package.artifacts
    ]
    view = artifact_service.get_artifact(project_id, generated[0].artifact_id)
    assert view.content == run.implementation_package.artifacts[0].model_dump(
        mode="json"
    )
    selected = next(
        item
        for item in catalog.artifacts
        if item.artifact_type is ProjectArtifactType.SELECTED_DIRECTION
    )
    assert artifact_service.get_artifact(
        project_id, selected.artifact_id
    ).content == next(
        item.model_dump(mode="json")
        for item in run.report.directions
        if item.id == run.selected_direction_id
    )

    def builder(store: FileProjectStore) -> ProjectSessionService:
        return ProjectSessionService(store, _FailingProposer())

    cli_catalog = StringIO()
    assert (
        run_cli(
            [
                "project-session",
                "--store-root",
                str(project_root),
                "artifacts",
                project_id,
            ],
            project_session_service_builder=builder,
            stdout=cli_catalog,
        )
        == 0
    )
    assert generated[0].artifact_id in cli_catalog.getvalue()

    cli_view = StringIO()
    assert (
        run_cli(
            [
                "project-session",
                "--store-root",
                str(project_root),
                "artifact",
                project_id,
                generated[0].artifact_id,
                "--format",
                "json",
            ],
            project_session_service_builder=builder,
            stdout=cli_view,
        )
        == 0
    )
    assert json.loads(cli_view.getvalue())["content"]["content"] == (
        run.implementation_package.artifacts[0].content
    )
    cli_text = StringIO()
    assert (
        run_cli(
            [
                "project-session",
                "--store-root",
                str(project_root),
                "artifact",
                project_id,
                generated[0].artifact_id,
                "--format",
                "text",
            ],
            project_session_service_builder=builder,
            stdout=cli_text,
        )
        == 0
    )
    assert cli_text.getvalue() == run.implementation_package.artifacts[0].content

    cli_markdown = StringIO()
    assert (
        run_cli(
            [
                "project-session",
                "--store-root",
                str(project_root),
                "artifact",
                project_id,
                selected.artifact_id,
                "--format",
                "markdown",
            ],
            project_session_service_builder=builder,
            stdout=cli_markdown,
        )
        == 0
    )
    assert cli_markdown.getvalue().startswith("# Selected research direction:")

    errors = StringIO()
    assert (
        run_cli(
            [
                "project-session",
                "--store-root",
                str(project_root),
                "artifact",
                project_id,
                selected.artifact_id,
                "--format",
                "text",
            ],
            project_session_service_builder=builder,
            stderr=errors,
        )
        == 1
    )
    assert "does not support format text" in errors.getvalue()

    client = TestClient(
        create_app(
            project_session_service=read_service,
            project_artifact_service=artifact_service,
        )
    )
    response = client.get(f"/v1/projects/{project_id}/artifacts")
    assert response.status_code == 200
    colon_id = generated[0].artifact_id
    assert ":" in colon_id
    inspected = client.get(f"/v1/projects/{project_id}/artifacts/{colon_id}")
    assert inspected.status_code == 200
    assert inspected.json()["descriptor"]["artifact_id"] == colon_id
    assert inspected.json()["content"]["content"] == (
        run.implementation_package.artifacts[0].content
    )
    markdown = client.get(
        f"/v1/projects/{project_id}/artifacts/{selected.artifact_id}",
        params={"format": "markdown"},
    )
    assert markdown.status_code == 200
    assert markdown.headers["content-type"] == "text/markdown; charset=utf-8"
    assert markdown.text.startswith("# Selected research direction:")
    text = client.get(
        f"/v1/projects/{project_id}/artifacts/{colon_id}",
        params={"format": "text"},
    )
    assert text.status_code == 200
    assert text.headers["content-type"] == "text/plain; charset=utf-8"
    assert text.text == run.implementation_package.artifacts[0].content
    assert (
        client.get(
            f"/v1/projects/{project_id}/artifacts/{colon_id}",
            params={"format": "markdown"},
        ).status_code
        == 422
    )

    markdown_output = tmp_path / "selected.txt"
    export_summary = StringIO()
    assert (
        run_cli(
            [
                "project-session",
                "--store-root",
                str(project_root),
                "export-artifact",
                project_id,
                selected.artifact_id,
                "--format",
                "markdown",
                "--output",
                str(markdown_output),
            ],
            project_session_service_builder=builder,
            stdout=export_summary,
        )
        == 0
    )
    assert markdown_output.read_text(encoding="utf-8").startswith(
        "# Selected research direction:"
    )
    assert "SHA-256:" in export_summary.getvalue()

    generated_output = tmp_path / "generated.py"
    assert (
        run_cli(
            [
                "project-session",
                "--store-root",
                str(project_root),
                "export-artifact",
                project_id,
                colon_id,
                "--format",
                "text",
                "--output",
                str(generated_output),
            ],
            project_session_service_builder=builder,
            stdout=StringIO(),
        )
        == 0
    )
    assert generated_output.read_bytes() == (
        run.implementation_package.artifacts[0].content.encode("utf-8")
    )

    existing_errors = StringIO()
    assert (
        run_cli(
            [
                "project-session",
                "--store-root",
                str(project_root),
                "export-artifact",
                project_id,
                selected.artifact_id,
                "--format",
                "markdown",
                "--output",
                str(markdown_output),
            ],
            project_session_service_builder=builder,
            stderr=existing_errors,
        )
        == 1
    )
    assert "already exists" in existing_errors.getvalue()

    unsupported_output = tmp_path / "unsupported"
    assert (
        run_cli(
            [
                "project-session",
                "--store-root",
                str(project_root),
                "export-artifact",
                project_id,
                selected.artifact_id,
                "--format",
                "text",
                "--output",
                str(unsupported_output),
            ],
            project_session_service_builder=builder,
            stderr=StringIO(),
        )
        == 1
    )
    assert not unsupported_output.exists()

    foreign_output = tmp_path / "foreign"
    foreign_id = selected.artifact_id.replace(run_id, str(uuid4()))
    assert (
        run_cli(
            [
                "project-session",
                "--store-root",
                str(project_root),
                "export-artifact",
                project_id,
                foreign_id,
                "--format",
                "markdown",
                "--output",
                str(foreign_output),
            ],
            project_session_service_builder=builder,
            stderr=StringIO(),
        )
        == 1
    )
    assert not foreign_output.exists()
    assert not any("export" in route.path for route in client.app.routes)
    assert (
        client.get(
            f"/v1/projects/{project_id}/artifacts/{selected.artifact_id}",
            params={"format": "yaml"},
        ).status_code
        == 422
    )

    assert proposer.calls == 1
    assert FileProjectStore(project_root).get(project_id) == before
    assert FileResearchRunStore(default_research_run_store_root()).get(run_id) == run
