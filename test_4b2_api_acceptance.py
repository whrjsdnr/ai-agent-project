"""Manual persisted API acceptance for Phase 4B-2 continuation routing."""

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

from ai_agent_project.agent.coding_service import CodingAgentService
from ai_agent_project.agent.phase_execution import PhaseExecutionService
from ai_agent_project.agent.project_action_application import ProjectActionService
from ai_agent_project.agent.project_application import ProjectApplicationService
from ai_agent_project.agent.project_execution import (
    ProjectExecutionService,
    ProjectExecutionStatus,
)
from ai_agent_project.agent.project_file_store import FileProjectRunStore
from ai_agent_project.agent.project_runner import ProjectRunner
from ai_agent_project.agent.project_session import ProjectModeProposal, ProjectSession
from ai_agent_project.agent.project_session_application import ProjectSessionService
from ai_agent_project.agent.project_session_file_store import FileProjectStore
from ai_agent_project.agent.research import (
    ResearchPaperMaterialsPayload,
    ResearchResultAnalysisPayload,
    ResearchRun,
    ResearchStatus,
    ResearchSynthesisPayload,
    WorkMode,
)
from ai_agent_project.agent.research_application import ResearchApplicationService
from ai_agent_project.agent.research_discovery import ResearchDiscoveryService
from ai_agent_project.agent.research_file_store import FileResearchRunStore
from ai_agent_project.agent.service import AgentService
from ai_agent_project.agent.upgrade import ProjectMode
from ai_agent_project.api.app import create_app


class NoProvider:
    def propose(self, request: str) -> ProjectModeProposal:
        raise AssertionError(f"provider called while routing: {request}")


def identifier() -> str:
    return str(uuid4())


def research_at(terminal: ResearchRun, status: ResearchStatus) -> ResearchRun:
    selected = status is not ResearchStatus.AWAITING_DIRECTION_SELECTION
    plan = status not in {
        ResearchStatus.AWAITING_DIRECTION_SELECTION,
        ResearchStatus.DIRECTION_SELECTED,
    }
    implementation = status not in {
        ResearchStatus.AWAITING_DIRECTION_SELECTION,
        ResearchStatus.DIRECTION_SELECTED,
        ResearchStatus.RESEARCH_PLAN_APPROVED,
    }
    package = status in {
        ResearchStatus.IMPLEMENTATION_PACKAGE_READY,
        ResearchStatus.AWAITING_USER_RESULTS,
        ResearchStatus.RESEARCH_RESULTS_SUBMITTED,
        ResearchStatus.RESEARCH_RESULTS_ANALYZED,
        ResearchStatus.RESEARCH_SYNTHESIS_READY,
    }
    results = status in {
        ResearchStatus.RESEARCH_RESULTS_SUBMITTED,
        ResearchStatus.RESEARCH_RESULTS_ANALYZED,
        ResearchStatus.RESEARCH_SYNTHESIS_READY,
    }
    analysis = status in {
        ResearchStatus.RESEARCH_RESULTS_ANALYZED,
        ResearchStatus.RESEARCH_SYNTHESIS_READY,
    }
    synthesis = status is ResearchStatus.RESEARCH_SYNTHESIS_READY
    return ResearchRun(
        request=terminal.request,
        status=status,
        report=terminal.report,
        selected_direction_id=terminal.selected_direction_id if selected else None,
        plan_revision_state=terminal.plan_revision_state if plan else None,
        implementation_plan=terminal.implementation_plan if implementation else None,
        implementation_package=terminal.implementation_package if package else None,
        result_submission=terminal.result_submission if results else None,
        result_analysis=terminal.result_analysis if analysis else None,
        result_synthesis=terminal.result_synthesis if synthesis else None,
    )


class OfflineExecution:
    def execute_current_phase(self, state, specification, project_specification, plan):
        del specification, project_specification, plan
        return state.model_copy(
            update={"status": ProjectExecutionStatus.AWAITING_CHECKPOINT}
        )


class PlanProvider:
    def __init__(self, terminal: ResearchRun) -> None:
        self._value = terminal.plan_revision_state.active_plan

    def generate(self, *_args, **_kwargs):
        return self._value


class ImplementationPlanProvider:
    def __init__(self, terminal: ResearchRun) -> None:
        self._value = terminal.implementation_plan

    def plan(self, *_args):
        return self._value


class PackageProvider:
    def __init__(self, terminal: ResearchRun) -> None:
        self._value = terminal.implementation_package

    def generate(self, *_args):
        return self._value


class AnalysisProvider:
    def __init__(self, terminal: ResearchRun) -> None:
        self._value = ResearchResultAnalysisPayload.model_validate(
            terminal.result_analysis.model_dump()
        )

    def analyze(self, *_args):
        return self._value


class SynthesisProvider:
    def __init__(self, terminal: ResearchRun) -> None:
        self._value = ResearchSynthesisPayload.model_validate(
            terminal.result_synthesis.model_dump()
        )

    def synthesize(self, *_args):
        return self._value


class PaperProvider:
    def __init__(self, terminal: ResearchRun) -> None:
        self._value = ResearchPaperMaterialsPayload.model_validate(
            terminal.paper_materials.model_dump()
        )

    def generate(self, *_args):
        return self._value


def domain_services(developers, researchers, terminal):
    unavailable = object()
    developer = ProjectApplicationService(
        cast(ProjectRunner, unavailable),
        cast(ProjectExecutionService, OfflineExecution()),
        developers,
    )
    researcher = ResearchApplicationService(
        cast(ResearchDiscoveryService, unavailable),
        researchers,
        plan_generator=PlanProvider(terminal),
        implementation_planner=ImplementationPlanProvider(terminal),
        implementation_generator=PackageProvider(terminal),
        result_analyzer=AnalysisProvider(terminal),
        result_synthesizer=SynthesisProvider(terminal),
        paper_materials_generator=PaperProvider(terminal),
    )
    return developer, researcher


def create_project(store, sessions, mode, title, *, completed=False):
    project_id = identifier()
    store.create(
        project_id,
        ProjectSession.awaiting_confirmation(
            project_id=project_id,
            title=title,
            original_request=f"4B-2 acceptance: {title}",
            mode_proposal=ProjectModeProposal(
                proposed_work_mode=mode,
                proposed_project_mode=ProjectMode.NEW,
                rationale="Trusted fixture",
            ),
        ),
    )
    sessions.confirm_project_mode(project_id, mode, ProjectMode.NEW)
    if completed:
        sessions.complete_project(project_id)
    return project_id


def build_fixture(
    root: Path,
    *,
    developer_root: Path | None = None,
    research_root: Path | None = None,
):
    workspace = root / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "DO_NOT_READ_OR_EXECUTE_4B2.txt").write_text(
        "DEVELOPER_WORKSPACE_SENTINEL_4B2", encoding="utf-8"
    )
    project_store = FileProjectStore(root / "projects")
    developers = FileProjectRunStore(
        developer_root or root / "developers", workspace_root=workspace
    )
    researchers = FileResearchRunStore(research_root or root / "researchers")
    terminal = _terminal_research_run()

    raw_developer_id = identifier()
    developers.create(raw_developer_id, _developer_run())
    unavailable = object()
    approval_service = ProjectApplicationService(
        cast(ProjectRunner, unavailable),
        ProjectExecutionService(
            cast(PhaseExecutionService, unavailable),
            cast(object, unavailable),
            cast(object, unavailable),
        ),
        developers,
    )
    approval_service.approve_plan(raw_developer_id)

    sessions = ProjectSessionService(
        project_store, NoProvider(), developers, researchers
    )
    projects: dict[str, str] = {}
    runs: dict[str, str] = {"developer_ready": raw_developer_id}
    projects["developer_ready"] = create_project(
        project_store, sessions, WorkMode.DEVELOPER, "Developer ready"
    )
    sessions.bind_developer_run(projects["developer_ready"], raw_developer_id)

    for name, status in (
        ("direction", ResearchStatus.DIRECTION_SELECTED),
        ("plan_approved", ResearchStatus.RESEARCH_PLAN_APPROVED),
        ("implementation_started", ResearchStatus.IMPLEMENTATION_GENERATION_STARTED),
        ("package_ready", ResearchStatus.IMPLEMENTATION_PACKAGE_READY),
        ("awaiting_results", ResearchStatus.AWAITING_USER_RESULTS),
        ("results_submitted", ResearchStatus.RESEARCH_RESULTS_SUBMITTED),
        ("results_analyzed", ResearchStatus.RESEARCH_RESULTS_ANALYZED),
        ("synthesis_ready", ResearchStatus.RESEARCH_SYNTHESIS_READY),
    ):
        run_id = identifier()
        researchers.create(run_id, research_at(terminal, status))
        project_id = create_project(project_store, sessions, WorkMode.RESEARCHER, name)
        sessions.bind_research_run(project_id, run_id)
        runs[name] = run_id
        projects[name] = project_id
    return project_store, developers, researchers, terminal, sessions, projects, runs


def create_cli_fixture(root: Path, ids_file: Path) -> None:
    project_store, developers, researchers, terminal, sessions, projects, runs = (
        build_fixture(
            root,
            developer_root=Path.home() / ".local/share/ai-agent/project-runs",
            research_root=Path.home() / ".local/share/ai-agent/research-runs",
        )
    )
    running_id = identifier()
    ready = developers.get(runs["developer_ready"])
    running = ready.model_copy(
        update={
            "execution_state": ready.execution_state.model_copy(
                update={"status": ProjectExecutionStatus.RUNNING}
            )
        }
    )
    developers.create(running_id, running)
    running_project = create_project(
        project_store, sessions, WorkMode.DEVELOPER, "Developer running"
    )
    sessions.bind_developer_run(running_project, running_id)

    unsupported_id = identifier()
    researchers.create(
        unsupported_id,
        ResearchRun(
            request=terminal.request,
            status=ResearchStatus.DISCOVERING,
            report=terminal.report,
        ),
    )
    unsupported_project = create_project(
        project_store, sessions, WorkMode.RESEARCHER, "Research discovering"
    )
    sessions.bind_research_run(unsupported_project, unsupported_id)

    invalid_projects: dict[str, str] = {}
    invalid_runs: dict[str, str] = {}
    for name in (
        "foreign",
        "wrong_plan",
        "wrong_implementation",
        "foreign_task",
        "malformed",
        "schema_invalid",
    ):
        run_id = identifier()
        researchers.create(
            run_id,
            research_at(terminal, ResearchStatus.IMPLEMENTATION_PACKAGE_READY),
        )
        project_id = create_project(
            project_store, sessions, WorkMode.RESEARCHER, f"Invalid {name}"
        )
        sessions.bind_research_run(project_id, run_id)
        invalid_projects[name], invalid_runs[name] = project_id, run_id

    hybrid_developer_id = identifier()
    developers.create(hybrid_developer_id, ready)
    hybrid_research_id = identifier()
    researchers.create(
        hybrid_research_id, research_at(terminal, ResearchStatus.DIRECTION_SELECTED)
    )
    hybrid_project = create_project(project_store, sessions, WorkMode.HYBRID, "Hybrid")
    sessions.bind_developer_run(hybrid_project, hybrid_developer_id)
    sessions.bind_research_run(hybrid_project, hybrid_research_id)

    completed_project = create_project(
        project_store, sessions, WorkMode.HYBRID, "Completed"
    )
    sessions.bind_developer_run(completed_project, runs["developer_ready"])
    sessions.bind_research_run(completed_project, runs["package_ready"])
    sessions.complete_project(completed_project)
    missing_developer_id, missing_researcher_id = identifier(), identifier()
    missing_developer_project = create_project(
        project_store, sessions, WorkMode.DEVELOPER, "Missing Developer"
    )
    sessions.bind_developer_run(missing_developer_project, missing_developer_id)
    missing_researcher_project = create_project(
        project_store, sessions, WorkMode.RESEARCHER, "Missing Researcher"
    )
    sessions.bind_research_run(missing_researcher_project, missing_researcher_id)

    result_dir = root / "result-inputs"
    result_dir.mkdir()
    submission = terminal.result_submission.model_copy(
        update={"research_run_id": runs["package_ready"]}
    )
    awaiting_submission = terminal.result_submission.model_copy(
        update={"research_run_id": runs["awaiting_results"]}
    )
    paths: dict[str, Path] = {}
    variants = {
        "valid_package": submission,
        "valid_awaiting": awaiting_submission,
        "foreign": submission.model_copy(update={"research_run_id": identifier()}),
        "wrong_plan": submission.model_copy(
            update={
                "research_run_id": invalid_runs["wrong_plan"],
                "approved_plan_version": 999,
            }
        ),
        "wrong_implementation": submission.model_copy(
            update={
                "research_run_id": invalid_runs["wrong_implementation"],
                "implementation_plan_version": 999,
            }
        ),
        "foreign_task": submission.model_copy(
            update={
                "research_run_id": invalid_runs["foreign_task"],
                "task_results": (
                    submission.task_results[0].model_copy(
                        update={"task_id": "FOREIGN-TASK"}
                    ),
                    *submission.task_results[1:],
                ),
            }
        ),
    }
    for name, value in variants.items():
        path = result_dir / f"{name}.json"
        path.write_text(value.model_dump_json(), encoding="utf-8")
        paths[name] = path
    malformed = result_dir / "malformed.json"
    malformed.write_text("{not json", encoding="utf-8")
    schema_invalid = result_dir / "schema-invalid.json"
    schema_invalid.write_text('{"research_run_id":"x"}', encoding="utf-8")
    paths["malformed"], paths["schema_invalid"] = malformed, schema_invalid

    values = {
        "PROJECT_STORE": str(root / "projects"),
        "DEVELOPER_STORE": str(Path.home() / ".local/share/ai-agent/project-runs"),
        "RESEARCH_STORE": str(Path.home() / ".local/share/ai-agent/research-runs"),
        "WORKSPACE": str(root / "workspace"),
        "DEV_PROJECT": projects["developer_ready"],
        "DEV_RUN": runs["developer_ready"],
        "RUNNING_PROJECT": running_project,
        "RUNNING_RUN": running_id,
        "UNSUPPORTED_RESEARCH_PROJECT": unsupported_project,
        "UNSUPPORTED_RESEARCH_RUN": unsupported_id,
        "PACKAGE_PROJECT": projects["package_ready"],
        "PACKAGE_RUN": runs["package_ready"],
        "AWAITING_PROJECT": projects["awaiting_results"],
        "AWAITING_RUN": runs["awaiting_results"],
        "DIRECTION_PROJECT": projects["direction"],
        "DIRECTION_RUN": runs["direction"],
        "HYBRID_PROJECT": hybrid_project,
        "HYBRID_DEV_RUN": hybrid_developer_id,
        "HYBRID_RESEARCH_RUN": hybrid_research_id,
        "COMPLETED_PROJECT": completed_project,
        "MISSING_DEV_PROJECT": missing_developer_project,
        "MISSING_DEV_RUN": missing_developer_id,
        "MISSING_RESEARCH_PROJECT": missing_researcher_project,
        "MISSING_RESEARCH_RUN": missing_researcher_id,
        **{
            f"INVALID_{key.upper()}_PROJECT": value
            for key, value in invalid_projects.items()
        },
        **{f"INVALID_{key.upper()}_RUN": value for key, value in invalid_runs.items()},
        **{f"RESULT_{key.upper()}": str(value) for key, value in paths.items()},
    }
    ids_file.write_text(
        "".join(
            f"{key}={shlex.quote(value)}\n" for key, value in sorted(values.items())
        ),
        encoding="utf-8",
    )


def run_api_acceptance() -> None:
    with TemporaryDirectory(prefix="ai-agent-4b2-api-") as temporary:
        root = Path(temporary)
        project_store, developers, researchers, terminal, sessions, projects, runs = (
            build_fixture(root)
        )
        developer, researcher = domain_services(developers, researchers, terminal)
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
        invalid_run = identifier()
        researchers.create(
            invalid_run,
            research_at(terminal, ResearchStatus.IMPLEMENTATION_PACKAGE_READY),
        )
        invalid_project = create_project(
            project_store, sessions, WorkMode.RESEARCHER, "Invalid API submission"
        )
        sessions.bind_research_run(invalid_project, invalid_run)
        project_before = {
            path.name: path.read_bytes() for path in (root / "projects").glob("*.json")
        }
        research_before = {
            path.name: path.read_bytes()
            for path in (root / "researchers").glob("*.json")
        }

        invalid_path = root / "researchers" / f"{invalid_run}.json"
        invalid_before = invalid_path.read_bytes()
        foreign = terminal.result_submission.model_copy(
            update={"research_run_id": identifier()}
        )
        invalid = client.post(
            f"/v1/projects/{invalid_project}/actions/provide-research-results",
            json=foreign.model_dump(mode="json"),
        )
        assert invalid.status_code == 409
        assert "different research run" in invalid.text
        wrong_version = terminal.result_submission.model_copy(
            update={"research_run_id": invalid_run, "approved_plan_version": 999}
        )
        invalid = client.post(
            f"/v1/projects/{invalid_project}/actions/provide-research-results",
            json=wrong_version.model_dump(mode="json"),
        )
        assert invalid.status_code == 409
        assert "different approved plan" in invalid.text
        assert invalid_path.read_bytes() == invalid_before

        developer_project_path = (
            root / "projects" / f"{projects['developer_ready']}.json"
        )
        developer_run_path = root / "developers" / f"{runs['developer_ready']}.json"
        old_project = developer_project_path.read_bytes()
        old_run = developer_run_path.read_bytes()
        developer_response = client.post(
            f"/v1/projects/{projects['developer_ready']}/actions/continue-developer"
        )
        assert developer_response.status_code == 200, developer_response.text
        developer_payload = developer_response.json()
        assert developer_payload["previous_pending_action"]["action_type"] == (
            "continue_developer"
        )
        assert developer_payload["source_status"] == "awaiting_checkpoint"
        assert developers.get(runs["developer_ready"]).execution_state.status is (
            ProjectExecutionStatus.AWAITING_CHECKPOINT
        )
        assert developer_project_path.read_bytes() == old_project
        assert developer_run_path.read_bytes() != old_run
        assert research_before == {
            path.name: path.read_bytes()
            for path in (root / "researchers").glob("*.json")
        }

        expected = {
            "direction": ResearchStatus.AWAITING_RESEARCH_PLAN_APPROVAL,
            "plan_approved": ResearchStatus.IMPLEMENTATION_GENERATION_STARTED,
            "implementation_started": ResearchStatus.IMPLEMENTATION_PACKAGE_READY,
            "results_submitted": ResearchStatus.RESEARCH_RESULTS_ANALYZED,
            "results_analyzed": ResearchStatus.RESEARCH_SYNTHESIS_READY,
            "synthesis_ready": ResearchStatus.PAPER_MATERIALS_READY,
        }
        for name, target in expected.items():
            project_path = root / "projects" / f"{projects[name]}.json"
            run_path = root / "researchers" / f"{runs[name]}.json"
            old_project, old_run = project_path.read_bytes(), run_path.read_bytes()
            response = client.post(
                f"/v1/projects/{projects[name]}/actions/continue-researcher"
            )
            assert response.status_code == 200, (name, response.text)
            payload = response.json()
            assert payload["previous_pending_action"]["action_type"] == (
                "continue_researcher"
            )
            assert payload["source_status"] == target.value
            assert researchers.get(runs[name]).status is target
            assert project_path.read_bytes() == old_project
            assert run_path.read_bytes() != old_run

        for name in ("package_ready", "awaiting_results"):
            submission = terminal.result_submission.model_copy(
                update={"research_run_id": runs[name]}
            )
            project_path = root / "projects" / f"{projects[name]}.json"
            old_project = project_path.read_bytes()
            submitted = client.post(
                f"/v1/projects/{projects[name]}/actions/provide-research-results",
                json=submission.model_dump(mode="json"),
            )
            assert submitted.status_code == 200, submitted.text
            assert submitted.json()["source_status"] == "research_results_submitted"
            assert submitted.json()["next_pending_action"]["action_type"] == (
                "continue_researcher"
            )
            stored = researchers.get(runs[name])
            assert stored.status is ResearchStatus.RESEARCH_RESULTS_SUBMITTED
            assert stored.result_submission == submission
            assert stored.result_analysis is None
            assert stored.result_synthesis is None
            assert stored.paper_materials is None
            assert project_path.read_bytes() == old_project

        package_path = root / "researchers" / f"{runs['package_ready']}.json"
        repeat_before = package_path.read_bytes()
        repeated = client.post(
            f"/v1/projects/{projects['package_ready']}/actions/provide-research-results",
            json=terminal.result_submission.model_copy(
                update={"research_run_id": runs["package_ready"]}
            ).model_dump(mode="json"),
        )
        assert repeated.status_code == 409
        assert package_path.read_bytes() == repeat_before

        malformed = client.post(
            f"/v1/projects/{projects['direction']}/actions/provide-research-results",
            json={"research_run_id": runs["direction"]},
        )
        assert malformed.status_code == 422
        wrong_pending = client.post(
            f"/v1/projects/{projects['direction']}/actions/provide-research-results",
            json=terminal.result_submission.model_copy(
                update={"research_run_id": runs["direction"]}
            ).model_dump(mode="json"),
        )
        assert wrong_pending.status_code == 409
        completed = create_project(
            project_store, sessions, WorkMode.RESEARCHER, "Completed API project"
        )
        sessions.bind_research_run(completed, runs["direction"])
        sessions.complete_project(completed)
        completed_path = root / "projects" / f"{completed}.json"
        completed_before = completed_path.read_bytes()
        assert (
            client.post(
                f"/v1/projects/{completed}/actions/continue-researcher"
            ).status_code
            == 409
        )
        assert completed_path.read_bytes() == completed_before

        missing_run = identifier()
        missing = create_project(
            project_store, sessions, WorkMode.RESEARCHER, "Missing API run"
        )
        sessions.bind_research_run(missing, missing_run)
        missing_response = client.post(
            f"/v1/projects/{missing}/actions/continue-researcher"
        )
        assert missing_response.status_code == 409
        assert "Linked Researcher run not found" in missing_response.text

        assert project_before == {
            name: (root / "projects" / name).read_bytes() for name in project_before
        }
    print("PHASE_4B2_API_ACCEPTANCE=PASSED")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--create-cli-fixture", action="store_true")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--ids-file", type=Path)
    arguments = parser.parse_args()
    if arguments.create_cli_fixture:
        if arguments.root is None or arguments.ids_file is None:
            parser.error("--root and --ids-file are required")
        create_cli_fixture(arguments.root, arguments.ids_file)
        return
    run_api_acceptance()


if __name__ == "__main__":
    main()
