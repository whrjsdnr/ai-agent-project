"""Manual persisted/API acceptance helper for Phase 4B-1 action routing."""

from __future__ import annotations

import argparse
import shlex
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast
from uuid import uuid4

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "tests" / "agent"))
sys.path.insert(0, str(ROOT / "tests" / "integration"))

from test_project_artifact import _developer_run
from test_project_artifact_interfaces import _terminal_research_run

from ai_agent_project.agent.checkpoint import (
    PhaseCheckpointService,
    ProgressReporter,
)
from ai_agent_project.agent.coding_service import CodingAgentService
from ai_agent_project.agent.phase_execution import PhaseExecutionService
from ai_agent_project.agent.project_action_application import (
    ProjectActionService,
)
from ai_agent_project.agent.project_application import (
    ProjectApplicationService,
)
from ai_agent_project.agent.project_execution import (
    ProjectExecutionService,
)
from ai_agent_project.agent.project_file_store import FileProjectRunStore
from ai_agent_project.agent.project_runner import ProjectRunner
from ai_agent_project.agent.project_session import (
    ProjectModeProposal,
    ProjectSession,
)
from ai_agent_project.agent.project_session_application import (
    ProjectSessionService,
)
from ai_agent_project.agent.project_session_file_store import (
    FileProjectStore,
)
from ai_agent_project.agent.research import (
    ResearchRun,
    ResearchStatus,
    WorkMode,
)
from ai_agent_project.agent.research_application import (
    ResearchApplicationService,
)
from ai_agent_project.agent.research_discovery import (
    ResearchDiscoveryService,
)
from ai_agent_project.agent.research_file_store import (
    FileResearchRunStore,
)
from ai_agent_project.agent.service import AgentService
from ai_agent_project.agent.upgrade import ProjectMode
from ai_agent_project.api.app import create_app


class NoProvider:
    def propose(self, request: str) -> ProjectModeProposal:
        raise AssertionError(f"provider called: {request}")


def _id() -> str:
    return str(uuid4())


def _checkpoint_services(
    developer_store: FileProjectRunStore,
    research_store: FileResearchRunStore,
) -> tuple[ProjectApplicationService, ResearchApplicationService]:
    unavailable = object()
    execution = ProjectExecutionService(
        cast(PhaseExecutionService, unavailable),
        ProgressReporter(),
        PhaseCheckpointService(),
    )
    return (
        ProjectApplicationService(
            cast(ProjectRunner, unavailable), execution, developer_store
        ),
        ResearchApplicationService(
            cast(ResearchDiscoveryService, unavailable), research_store
        ),
    )


def _research_fixtures() -> tuple[ResearchRun, ResearchRun, ResearchRun, str, str]:
    terminal = _terminal_research_run()
    assert terminal.selected_direction_id is not None
    assert terminal.plan_revision_state is not None
    candidate_ids = tuple(item.id for item in terminal.report.directions)
    assert candidate_ids
    direction_run = ResearchRun(
        request=terminal.request,
        status=ResearchStatus.AWAITING_DIRECTION_SELECTION,
        report=terminal.report,
    )
    unapproved = terminal.plan_revision_state.model_copy(update={"approved": False})
    plan_run = ResearchRun(
        request=terminal.request,
        status=ResearchStatus.AWAITING_RESEARCH_PLAN_APPROVAL,
        report=terminal.report,
        selected_direction_id=terminal.selected_direction_id,
        plan_revision_state=unapproved,
    )
    foreign_direction = terminal.report.directions[0].model_copy(
        update={"id": f"FOREIGN-{terminal.report.directions[0].id}"}
    )
    foreign_report = terminal.report.model_copy(
        update={"directions": (foreign_direction,)}
    )
    foreign_run = ResearchRun(
        request=terminal.request,
        status=ResearchStatus.AWAITING_DIRECTION_SELECTION,
        report=foreign_report,
    )
    return direction_run, plan_run, foreign_run, candidate_ids[0], foreign_direction.id


def _create_project(
    store: FileProjectStore,
    sessions: ProjectSessionService,
    mode: WorkMode,
    title: str,
) -> str:
    project_id = _id()
    store.create(
        project_id,
        ProjectSession.awaiting_confirmation(
            project_id=project_id,
            title=title,
            original_request=f"Phase 4B-1 acceptance: {title}",
            mode_proposal=ProjectModeProposal(
                proposed_work_mode=mode,
                proposed_project_mode=ProjectMode.NEW,
                rationale="Trusted acceptance fixture",
            ),
        ),
    )
    sessions.confirm_project_mode(project_id, mode, ProjectMode.NEW)
    return project_id


def create_cli_fixture(root: Path, ids_file: Path) -> None:
    project_root = root / "project-sessions"
    developer_root = Path.home() / ".local/share/ai-agent/project-runs"
    research_root = Path.home() / ".local/share/ai-agent/research-runs"
    workspace = root / "developer-workspace"
    for path in (project_root, developer_root, research_root, workspace):
        path.mkdir(parents=True, exist_ok=True)
    developer_store = FileProjectRunStore(developer_root, workspace_root=workspace)
    research_store = FileResearchRunStore(research_root)
    project_store = FileProjectStore(project_root)

    developer_run_id = _id()
    completed_developer_run_id = _id()
    hybrid_developer_run_id = _id()
    direction_run_id = _id()
    plan_run_id = _id()
    hybrid_research_run_id = _id()
    foreign_research_run_id = _id()
    developer_store.create(developer_run_id, _developer_run(revisions=2))
    developer_store.create(completed_developer_run_id, _developer_run())
    developer_store.create(hybrid_developer_run_id, _developer_run())
    direction_run, plan_run, foreign_run, selected_id, foreign_id = _research_fixtures()
    research_store.create(direction_run_id, direction_run)
    research_store.create(plan_run_id, plan_run)
    research_store.create(hybrid_research_run_id, direction_run)
    research_store.create(foreign_research_run_id, foreign_run)

    sessions = ProjectSessionService(
        project_store, NoProvider(), developer_store, research_store
    )
    developer_project_id = _create_project(
        project_store, sessions, WorkMode.DEVELOPER, "Developer approval"
    )
    sessions.bind_developer_run(developer_project_id, developer_run_id)
    direction_project_id = _create_project(
        project_store, sessions, WorkMode.RESEARCHER, "Direction selection"
    )
    sessions.bind_research_run(direction_project_id, direction_run_id)
    plan_project_id = _create_project(
        project_store, sessions, WorkMode.RESEARCHER, "Research plan approval"
    )
    sessions.bind_research_run(plan_project_id, plan_run_id)
    completed_project_id = _create_project(
        project_store, sessions, WorkMode.DEVELOPER, "Completed project"
    )
    sessions.bind_developer_run(completed_project_id, completed_developer_run_id)
    sessions.complete_project(completed_project_id)
    hybrid_project_id = _create_project(
        project_store, sessions, WorkMode.HYBRID, "Hybrid ordering"
    )
    sessions.bind_developer_run(hybrid_project_id, hybrid_developer_run_id)
    sessions.bind_research_run(hybrid_project_id, hybrid_research_run_id)
    missing_run_id = _id()
    missing_project_id = _create_project(
        project_store, sessions, WorkMode.DEVELOPER, "Missing run"
    )
    sessions.bind_developer_run(missing_project_id, missing_run_id)

    values = {
        "PROJECT_STORE": str(project_root),
        "DEVELOPER_STORE": str(developer_root),
        "RESEARCH_STORE": str(research_root),
        "DEVELOPER_PROJECT_ID": developer_project_id,
        "DEVELOPER_RUN_ID": developer_run_id,
        "DIRECTION_PROJECT_ID": direction_project_id,
        "DIRECTION_RUN_ID": direction_run_id,
        "PLAN_PROJECT_ID": plan_project_id,
        "PLAN_RUN_ID": plan_run_id,
        "COMPLETED_PROJECT_ID": completed_project_id,
        "COMPLETED_DEVELOPER_RUN_ID": completed_developer_run_id,
        "HYBRID_PROJECT_ID": hybrid_project_id,
        "HYBRID_DEVELOPER_RUN_ID": hybrid_developer_run_id,
        "HYBRID_RESEARCH_RUN_ID": hybrid_research_run_id,
        "MISSING_PROJECT_ID": missing_project_id,
        "MISSING_RUN_ID": missing_run_id,
        "SELECTED_DIRECTION_ID": selected_id,
        "FOREIGN_DIRECTION_ID": foreign_id,
    }
    ids_file.write_text(
        "".join(
            f"{key}={shlex.quote(value)}\n" for key, value in sorted(values.items())
        ),
        encoding="utf-8",
    )


def run_api_acceptance() -> None:
    with TemporaryDirectory(prefix="ai-agent-4b1-api-") as temporary:
        root = Path(temporary)
        workspace = root / "workspace"
        workspace.mkdir()
        developer_store = FileProjectRunStore(
            root / "developers", workspace_root=workspace
        )
        research_store = FileResearchRunStore(root / "research")
        project_store = FileProjectStore(root / "projects")
        direction_run, plan_run, foreign_run, selected_id, foreign_id = (
            _research_fixtures()
        )
        developer_id, direction_id, plan_id, foreign_run_id = (
            _id(),
            _id(),
            _id(),
            _id(),
        )
        developer_store.create(developer_id, _developer_run())
        research_store.create(direction_id, direction_run)
        research_store.create(plan_id, plan_run)
        research_store.create(foreign_run_id, foreign_run)
        sessions = ProjectSessionService(
            project_store, NoProvider(), developer_store, research_store
        )
        developer_project = _create_project(
            project_store, sessions, WorkMode.DEVELOPER, "API Developer"
        )
        sessions.bind_developer_run(developer_project, developer_id)
        direction_project = _create_project(
            project_store, sessions, WorkMode.RESEARCHER, "API Direction"
        )
        sessions.bind_research_run(direction_project, direction_id)
        plan_project = _create_project(
            project_store, sessions, WorkMode.RESEARCHER, "API Plan"
        )
        sessions.bind_research_run(plan_project, plan_id)
        project_snapshots = {
            path.name: path.read_bytes() for path in (root / "projects").glob("*.json")
        }
        developer, researcher = _checkpoint_services(developer_store, research_store)
        actions = ProjectActionService(sessions, developer, researcher)
        client = TestClient(
            create_app(
                agent_service=cast(AgentService, object()),
                coding_agent_service=cast(CodingAgentService, object()),
                project_application_service=developer,
                research_application_service=researcher,
                project_session_service=sessions,
                project_action_service=actions,
            )
        )

        approved = client.post(
            f"/v1/projects/{developer_project}/actions/approve-developer-plan"
        )
        assert approved.status_code == 200, approved.text
        assert (
            approved.json()["next_pending_action"]["action_type"]
            == "continue_developer"
        )
        assert developer_store.get(developer_id).execution_state.status.value == "ready"
        assert (
            client.post(
                f"/v1/projects/{developer_project}/actions/approve-developer-plan"
            ).status_code
            == 409
        )

        invalid = client.post(
            f"/v1/projects/{direction_project}/actions/select-research-direction",
            json={"direction_id": foreign_id},
        )
        assert invalid.status_code == 404, invalid.text
        selected = client.post(
            f"/v1/projects/{direction_project}/actions/select-research-direction",
            json={"direction_id": selected_id},
        )
        assert selected.status_code == 200, selected.text
        assert research_store.get(direction_id).selected_direction_id == selected_id
        assert (
            research_store.get(direction_id).status is ResearchStatus.DIRECTION_SELECTED
        )
        assert (
            client.post(
                f"/v1/projects/{direction_project}/actions/select-research-direction",
                json={"direction_id": selected_id},
            ).status_code
            == 409
        )

        plan_approved = client.post(
            f"/v1/projects/{plan_project}/actions/approve-research-plan"
        )
        assert plan_approved.status_code == 200, plan_approved.text
        assert (
            plan_approved.json()["next_pending_action"]["action_type"]
            == "continue_researcher"
        )
        stored_plan = research_store.get(plan_id)
        assert stored_plan.status is ResearchStatus.RESEARCH_PLAN_APPROVED
        assert stored_plan.plan_revision_state.approved is True
        assert stored_plan.implementation_plan is None
        assert (
            client.post(
                f"/v1/projects/{plan_project}/actions/approve-research-plan"
            ).status_code
            == 409
        )

        assert project_snapshots == {
            path.name: path.read_bytes() for path in (root / "projects").glob("*.json")
        }
    print("PHASE_4B1_API_ACCEPTANCE=PASSED")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--create-cli-fixture", action="store_true")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--ids-file", type=Path)
    arguments = parser.parse_args()
    if arguments.create_cli_fixture:
        if arguments.root is None or arguments.ids_file is None:
            parser.error("--root and --ids-file are required for CLI fixture setup")
        create_cli_fixture(arguments.root, arguments.ids_file)
        return
    run_api_acceptance()


if __name__ == "__main__":
    main()
