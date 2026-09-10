"""Thin command-line interface for explicit project lifecycle operations."""

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TextIO, cast

from ai_agent_project.agent.checkpoint import CheckpointDecision
from ai_agent_project.agent.hybrid_coordination import HybridCoordinationView
from ai_agent_project.agent.hybrid_coordination_application import (
    HybridCoordinationError,
    HybridCoordinationService,
)
from ai_agent_project.agent.project_action_application import (
    ApproveDeveloperPlanCommand,
    ApproveResearchPlanCommand,
    ContinueDeveloperCommand,
    ContinueResearcherCommand,
    ProjectActionError,
    ProjectActionResult,
    ProjectActionService,
    ProvideResearchResultsCommand,
    SelectResearchDirectionCommand,
)
from ai_agent_project.agent.project_application import (
    ProjectApplicationService,
    ProjectRunError,
    StoredProjectRun,
)
from ai_agent_project.agent.project_artifact_application import (
    ProjectArtifactError,
    ProjectArtifactService,
)
from ai_agent_project.agent.project_artifact_export import (
    ProjectArtifactExportError,
    ProjectArtifactExportService,
)
from ai_agent_project.agent.project_artifact_rendering import (
    ProjectArtifactFormat,
    ProjectArtifactRenderingError,
    render_project_artifact,
)
from ai_agent_project.agent.project_developer_bootstrap_application import (
    ProjectDeveloperBootstrapService,
)
from ai_agent_project.agent.project_file_store import (
    FileProjectRunStore,
    ProjectRunStorageError,
    default_project_run_store_root,
)
from ai_agent_project.agent.project_handoff import ProjectHandoffPurpose
from ai_agent_project.agent.project_handoff_application import (
    ProjectHandoffError,
    ProjectHandoffService,
)
from ai_agent_project.agent.project_handoff_consumption import (
    ProjectHandoffConsumptionService,
)
from ai_agent_project.agent.project_handoff_file_store import FileProjectHandoffStore
from ai_agent_project.agent.project_session_application import (
    ProjectSessionError,
    ProjectSessionService,
)
from ai_agent_project.agent.project_session_file_store import (
    FileProjectStore,
    ProjectSessionStorageError,
    default_project_store_root,
)
from ai_agent_project.agent.research import ResearchResultSubmission, WorkMode
from ai_agent_project.agent.research_application import (
    ResearchApplicationService,
    ResearchRunError,
    StoredResearchRun,
)
from ai_agent_project.agent.research_file_store import (
    FileResearchRunStore,
    ResearchRunStorageError,
    default_research_run_store_root,
)
from ai_agent_project.agent.upgrade import ProjectMode
from ai_agent_project.llm.config import ProviderConfig, ProviderConfigService


class CliError(Exception):
    """An expected user-facing CLI error."""


ProjectServiceBuilder = Callable[[Path, FileProjectRunStore], ProjectApplicationService]
ResearchServiceBuilder = Callable[
    [Path, FileResearchRunStore], ResearchApplicationService
]
ProjectSessionServiceBuilder = Callable[[FileProjectStore], ProjectSessionService]
ProjectActionServiceBuilder = Callable[
    [ProjectSessionService, FileProjectRunStore, FileResearchRunStore, Path],
    ProjectActionService,
]


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI entry point without requiring a subprocess in tests."""
    return run_cli(argv if argv is not None else sys.argv[1:])


def run_cli(
    argv: Sequence[str],
    *,
    cwd: Path | None = None,
    store_root: Path | None = None,
    service_builder: ProjectServiceBuilder | None = None,
    research_service_builder: ResearchServiceBuilder | None = None,
    project_session_service_builder: ProjectSessionServiceBuilder | None = None,
    project_action_service_builder: ProjectActionServiceBuilder | None = None,
    improvement_service=None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Parse and execute one explicit project lifecycle command."""
    output = stdout or sys.stdout
    errors = stderr or sys.stderr
    parser = _build_parser()
    arguments = parser.parse_args(list(argv))
    current_directory = (cwd or Path.cwd()).resolve()
    default_store_root = (
        default_research_run_store_root()
        if arguments.top_level == "research"
        else (
            default_project_store_root()
            if arguments.top_level == "project-session"
            else default_project_run_store_root()
        )
    )
    resolved_store_root = _resolve_store_root(
        getattr(arguments, "store_root", None),
        store_root,
        default=default_store_root,
    )
    build_service = service_builder or _build_production_service

    try:
        if arguments.top_level == "improvement":
            from ai_agent_project.improvement.commands import run_command

            return run_command(arguments, output, improvement_service)
        if arguments.top_level == "config":
            return _run_llm_config_command(arguments, output)
        if arguments.top_level == "research":
            return _run_research_command(
                arguments,
                current_directory,
                resolved_store_root,
                research_service_builder or _build_production_research_service,
                output,
            )
        if arguments.top_level == "project-session":
            session_builder = project_session_service_builder
            if session_builder is None:
                session_builder = (
                    _build_production_project_session_service
                    if arguments.command == "create"
                    else _build_provider_free_project_session_service
                )
            return _run_project_session_command(
                arguments,
                resolved_store_root,
                session_builder,
                output,
                current_directory,
                project_action_service_builder,
            )
        if arguments.command == "create":
            return _create_project(
                arguments, current_directory, resolved_store_root, build_service, output
            )
        if arguments.command == "upgrade":
            return _create_upgrade(
                arguments, current_directory, resolved_store_root, build_service, output
            )
        return _run_existing_project_command(
            arguments,
            resolved_store_root,
            build_service,
            output,
        )
    except (
        CliError,
        ProjectRunError,
        ProjectRunStorageError,
        ResearchRunError,
        ResearchRunStorageError,
        ProjectSessionError,
        ProjectSessionStorageError,
        ProjectArtifactError,
        ProjectArtifactRenderingError,
        ProjectArtifactExportError,
        ProjectActionError,
        HybridCoordinationError,
        ProjectHandoffError,
        OSError,
        UnicodeError,
        ValueError,
    ) as error:
        print(f"Error: {error}", file=errors)
        return 1


def _run_llm_config_command(arguments: argparse.Namespace, output: TextIO) -> int:
    service = ProviderConfigService(arguments.config_file)
    if arguments.command == "test":
        result = service.test_connection()
        print(result.message, file=output)
        return 0 if result.success else 1
    config = service.resolve()
    if arguments.command == "set":
        updates = {
            name: getattr(arguments, name)
            for name in ("provider_type", "base_url", "model", "timeout_seconds")
            if getattr(arguments, name) is not None
        }
        config = ProviderConfig.model_validate({**config.model_dump(), **updates})
        service.save(config)
    print(config.model_dump_json(indent=2), file=output)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-agent")
    top_level = parser.add_subparsers(dest="top_level", required=True)
    from ai_agent_project.improvement.commands import add_parser

    add_parser(top_level)
    config = top_level.add_parser("config", help="Manage user settings")
    config_sections = config.add_subparsers(dest="section", required=True)
    llm = config_sections.add_parser("llm", help="OpenAI-compatible provider settings")
    llm.add_argument(
        "--config-file", type=Path, help="Override user configuration file"
    )
    llm_commands = llm.add_subparsers(dest="command", required=True)
    llm_commands.add_parser("show", help="Show effective settings without credentials")
    set_llm = llm_commands.add_parser("set", help="Save non-secret provider settings")
    set_llm.add_argument("--provider-type")
    set_llm.add_argument("--base-url")
    set_llm.add_argument("--model")
    set_llm.add_argument("--timeout-seconds", type=float)
    llm_commands.add_parser("test", help="Test configured provider connection")
    project = top_level.add_parser("project", help="Manage persisted project runs")
    project.add_argument(
        "--store-root",
        type=Path,
        help="Directory containing persisted project-run JSON snapshots",
    )
    commands = project.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create", help="Bootstrap a project from a plan")
    create.add_argument("plan_file", type=Path)
    create.add_argument("--workspace", type=Path, help="Workspace to plan and execute")
    create.add_argument("--title", help="Optional project title override")

    upgrade = commands.add_parser(
        "upgrade", help="Bootstrap an existing-project upgrade"
    )
    upgrade.add_argument("request_file", type=Path)
    upgrade.add_argument("--workspace", type=Path, required=True)
    upgrade.add_argument("--title", help="Optional project title override")

    status = commands.add_parser("status", help="Show a stored project run")
    status.add_argument("project_run_id")
    status.add_argument("--json", action="store_true", dest="as_json")

    plan = commands.add_parser("plan", help="Show the active project plan review")
    plan.add_argument("project_run_id")

    revise_plan = commands.add_parser(
        "revise-plan", help="Revise the phase plan before approval"
    )
    revise_plan.add_argument("project_run_id")
    revise_plan.add_argument("--note", required=True)

    approve_plan = commands.add_parser(
        "approve-plan", help="Approve the active project plan without executing"
    )
    approve_plan.add_argument("project_run_id")

    analysis = commands.add_parser("analysis", help="Show saved upgrade analysis")
    analysis.add_argument("project_run_id")

    execute = commands.add_parser("execute", help="Execute exactly the current phase")
    execute.add_argument("project_run_id")

    for command, decision, help_text in (
        ("approve", CheckpointDecision.APPROVE, "Approve the current checkpoint"),
        ("retry", CheckpointDecision.RETRY, "Request an explicit retry"),
        (
            "request-changes",
            CheckpointDecision.REQUEST_CHANGES,
            "Request changes to the current phase",
        ),
        ("stop", CheckpointDecision.STOP, "Stop the project lifecycle"),
    ):
        decision_parser = commands.add_parser(command, help=help_text)
        decision_parser.add_argument("project_run_id")
        decision_parser.add_argument("--note")
        decision_parser.set_defaults(decision=decision)

    research = top_level.add_parser(
        "research", help="Discover and review research directions"
    )
    research.add_argument("--store-root", type=Path)
    research_commands = research.add_subparsers(dest="command", required=True)

    session = top_level.add_parser(
        "project-session", help="Propose and confirm shallow project orchestration"
    )
    session.add_argument("--store-root", type=Path)
    session_commands = session.add_subparsers(dest="command", required=True)
    session_create = session_commands.add_parser("create", help="Propose project modes")
    session_create.add_argument("request")
    session_create.add_argument("--title")
    for name, help_text in (
        ("status", "Show a project session"),
        ("resume", "Show the next required project-session action"),
        ("pending-action", "Show required explicit human action(s)"),
        ("coordination", "Show independent Hybrid workflow coordination"),
        ("complete", "Complete an active project session"),
    ):
        command = session_commands.add_parser(name, help=help_text)
        command.add_argument("project_id")
    artifacts = session_commands.add_parser(
        "artifacts", help="List linked authoritative project artifacts"
    )
    artifacts.add_argument("project_id")
    artifact = session_commands.add_parser(
        "artifact", help="Inspect one linked authoritative project artifact"
    )
    artifact.add_argument("project_id")
    artifact.add_argument("artifact_id")
    artifact.add_argument(
        "--format",
        choices=tuple(item.value for item in ProjectArtifactFormat),
        default=ProjectArtifactFormat.JSON.value,
    )
    handoff_artifact = session_commands.add_parser(
        "handoff-artifact", help="Select one Researcher artifact for Developer context"
    )
    handoff_artifact.add_argument("project_id")
    handoff_artifact.add_argument("artifact_id")
    handoff_artifact.add_argument("--to", required=True, choices=("developer",))
    handoff_artifact.add_argument(
        "--purpose",
        required=True,
        choices=tuple(item.value for item in ProjectHandoffPurpose),
    )
    handoffs = session_commands.add_parser(
        "handoffs", help="List persisted artifact handoff references"
    )
    handoffs.add_argument("project_id")
    bootstrap = session_commands.add_parser(
        "bootstrap-developer",
        help="Bootstrap a Developer run from a Researcher handoff",
    )
    bootstrap.add_argument("project_id")
    bootstrap.add_argument("handoff_id")
    bootstrap.add_argument("--request", required=True)
    export_artifact = session_commands.add_parser(
        "export-artifact", help="Export one linked artifact to one new local file"
    )
    export_artifact.add_argument("project_id")
    export_artifact.add_argument("artifact_id")
    export_artifact.add_argument(
        "--format",
        required=True,
        choices=tuple(item.value for item in ProjectArtifactFormat),
    )
    export_artifact.add_argument("--output", required=True, type=Path)
    approve_developer = session_commands.add_parser(
        "approve-developer-plan", help="Explicitly approve the linked Developer plan"
    )
    approve_developer.add_argument("project_id")
    select_direction = session_commands.add_parser(
        "select-research-direction",
        help="Explicitly select a linked Researcher direction",
    )
    select_direction.add_argument("project_id")
    select_direction.add_argument("direction_id")
    approve_research = session_commands.add_parser(
        "approve-research-plan", help="Explicitly approve the linked Researcher plan"
    )
    approve_research.add_argument("project_id")
    continue_developer = session_commands.add_parser(
        "continue-developer", help="Explicitly advance one linked Developer phase"
    )
    continue_developer.add_argument("project_id")
    continue_researcher = session_commands.add_parser(
        "continue-researcher",
        help="Explicitly advance one linked Researcher lifecycle step",
    )
    continue_researcher.add_argument("project_id")
    provide_results = session_commands.add_parser(
        "provide-research-results",
        help="Submit authoritative user results to the linked Researcher run",
    )
    provide_results.add_argument("project_id")
    provide_results.add_argument("--input", required=True, type=Path)
    confirm = session_commands.add_parser("confirm-mode", help="Confirm project modes")
    confirm.add_argument("project_id")
    confirm.add_argument(
        "--work-mode", required=True, choices=[item.value for item in WorkMode]
    )
    confirm.add_argument(
        "--project-mode", required=True, choices=[item.value for item in ProjectMode]
    )
    for name, id_name, help_text in (
        ("bind-developer", "developer_run_id", "Bind a Developer run ID"),
        ("bind-research", "research_run_id", "Bind a Researcher run ID"),
    ):
        command = session_commands.add_parser(name, help=help_text)
        command.add_argument("project_id")
        command.add_argument(id_name)
    research_create = research_commands.add_parser(
        "create", help="Create a research discovery run"
    )
    research_create.add_argument("request_file", type=Path)
    research_create.add_argument("--workspace", type=Path)
    research_status = research_commands.add_parser("status", help="Show a research run")
    research_status.add_argument("research_run_id")
    research_report = research_commands.add_parser(
        "report", help="Show the structured discovery report"
    )
    research_report.add_argument("research_run_id")
    research_report.add_argument("--json", action="store_true", dest="as_json")
    research_directions = research_commands.add_parser(
        "directions", help="List selectable research directions"
    )
    research_directions.add_argument("research_run_id")
    research_select = research_commands.add_parser(
        "select-direction", help="Select one research direction"
    )
    research_select.add_argument("research_run_id")
    research_select.add_argument("direction_id")
    for name, help_text in (
        ("plan", "Generate the initial research plan"),
        ("show-plan", "Show the latest research plan"),
        ("approve-plan", "Approve the latest research plan"),
    ):
        command = research_commands.add_parser(name, help=help_text)
        command.add_argument("research_run_id")
    for name, help_text in (
        ("result-guide", "Show deterministic user result-submission guidance"),
        ("show-results", "Show submitted user research results"),
        ("analyze-results", "Analyze submitted user research results"),
        ("show-analysis", "Show persisted research result analysis"),
        ("synthesize", "Generate evidence-grounded research synthesis"),
        ("show-synthesis", "Show persisted research result synthesis"),
        ("paper-materials", "Generate structured research paper materials"),
        ("show-paper-materials", "Show persisted research paper materials"),
    ):
        command = research_commands.add_parser(name, help=help_text)
        command.add_argument("research_run_id")
    submit_results = research_commands.add_parser(
        "submit-results", help="Submit user-supplied result JSON"
    )
    submit_results.add_argument("research_run_id")
    submit_results.add_argument("result_json_file", type=Path)
    revise = research_commands.add_parser(
        "revise-plan", help="Revise the research plan"
    )
    revise.add_argument("research_run_id")
    revise.add_argument("--note", required=True)
    for name, help_text in (
        ("implementation-plan", "Generate a research implementation plan"),
        ("show-implementation-plan", "Show the generated implementation plan"),
        ("generate-package", "Generate a non-executed implementation package"),
        ("show-package", "Show the generated implementation package"),
    ):
        command = research_commands.add_parser(name, help=help_text)
        command.add_argument("research_run_id")
    return parser


def _create_project(
    arguments: argparse.Namespace,
    cwd: Path,
    store_root: Path,
    build_service: ProjectServiceBuilder,
    output: TextIO,
) -> int:
    plan_path = _resolve_path(arguments.plan_file, cwd)
    try:
        source_text = plan_path.read_text(encoding="utf-8")
    except OSError as error:
        raise CliError(f"Could not read plan file: {plan_path}") from error
    if not source_text.strip():
        raise CliError("Plan file must not be empty")
    workspace = _resolve_path(arguments.workspace, cwd) if arguments.workspace else cwd
    if not workspace.is_dir():
        raise CliError(f"Workspace is not a directory: {workspace}")

    store = FileProjectRunStore(store_root, workspace_root=workspace)
    stored = build_service(workspace, store).create_project(
        source_text,
        project_title=arguments.title,
        source_format=_source_format(plan_path),
    )
    _print_project_summary(stored, workspace, output)
    return 0


def _create_upgrade(
    arguments: argparse.Namespace,
    cwd: Path,
    store_root: Path,
    build_service: ProjectServiceBuilder,
    output: TextIO,
) -> int:
    request_path = _resolve_path(arguments.request_file, cwd)
    try:
        request_text = request_path.read_text(encoding="utf-8")
    except OSError as error:
        raise CliError(
            f"Could not read upgrade request file: {request_path}"
        ) from error
    if not request_text.strip():
        raise CliError("Upgrade request file must not be empty")
    workspace = _resolve_path(arguments.workspace, cwd)
    if not workspace.is_dir():
        raise CliError(f"Workspace is not a directory: {workspace}")
    store = FileProjectRunStore(store_root, workspace_root=workspace)
    stored = build_service(workspace, store).create_upgrade_project(
        request_text, project_title=arguments.title
    )
    _print_project_summary(stored, workspace, output)
    return 0


def _run_project_session_command(
    arguments: argparse.Namespace,
    store_root: Path,
    build_service: ProjectSessionServiceBuilder,
    output: TextIO,
    cwd: Path | None = None,
    build_action_service: ProjectActionServiceBuilder | None = None,
) -> int:
    store = FileProjectStore(store_root)
    service = build_service(store)
    developer_store = FileProjectRunStore(
        default_project_run_store_root(),
        workspace_root=cwd if cwd is not None else Path.cwd(),
    )
    research_store = FileResearchRunStore(default_research_run_store_root())
    artifact_service = ProjectArtifactService(
        service,
        developer_store,
        research_store,
    )
    handoff_store = FileProjectHandoffStore(store_root / "handoffs")
    handoff_service = ProjectHandoffService(
        service,
        artifact_service,
        handoff_store,
        research_reader=research_store,
    )
    coordination_service = HybridCoordinationService(
        service, developer_store, research_store
    )
    export_service = ProjectArtifactExportService(artifact_service)
    action_service = (build_action_service or _build_project_action_service)(
        service,
        developer_store,
        research_store,
        cwd if cwd is not None else Path.cwd(),
    )
    if arguments.command == "create":
        stored = service.create_project_request(
            arguments.request, title=arguments.title
        )
        _print_project_session(stored.project, output)
        return 0
    if arguments.command == "status":
        _print_project_session(
            service.get_project(arguments.project_id).project, output
        )
        return 0
    if arguments.command == "coordination":
        _print_hybrid_coordination(
            coordination_service.get_coordination(arguments.project_id), output
        )
        return 0
    if arguments.command == "artifacts":
        catalog = artifact_service.list_artifacts(arguments.project_id)
        print(f"Project ID: {catalog.project_id}", file=output)
        print("Artifacts:", file=output)
        if not catalog.artifacts:
            print("- none", file=output)
        for descriptor in catalog.artifacts:
            print(
                f"- {descriptor.artifact_id} | {descriptor.artifact_type} | "
                f"{descriptor.title} | {','.join(descriptor.media_types)}",
                file=output,
            )
        return 0
    if arguments.command == "handoff-artifact":
        handoff = handoff_service.register(
            arguments.project_id,
            arguments.artifact_id,
            ProjectHandoffPurpose(arguments.purpose),
        )
        print(f"Handoff ID: {handoff.handoff_id}", file=output)
        print(f"Project ID: {handoff.project_id}", file=output)
        print(f"Artifact ID: {handoff.artifact_id}", file=output)
        print(f"Source run ID: {handoff.source_run_id}", file=output)
        print(f"SHA-256: {handoff.content_sha256}", file=output)
        print(f"Purpose: {handoff.purpose}", file=output)
        return 0
    if arguments.command == "bootstrap-developer":
        bootstrap_service = ProjectDeveloperBootstrapService(
            service,
            ProjectHandoffConsumptionService(
                service, artifact_service, handoff_store, research_store
            ),
            _build_production_service(
                cwd if cwd is not None else Path.cwd(), developer_store
            ),
        )
        from ai_agent_project.improvement.context import project_context

        with project_context(arguments.project_id):
            result = bootstrap_service.bootstrap(
                arguments.project_id, arguments.handoff_id, arguments.request
            )
        print(f"Project ID: {result.project_id}", file=output)
        print(f"Handoff ID: {result.handoff_id}", file=output)
        print(f"Developer Run ID: {result.developer_run_id}", file=output)
        print(f"Developer Status: {result.developer_status}", file=output)
        print(f"Pending Action: {result.pending_action}", file=output)
        return 0
    if arguments.command == "handoffs":
        listing = handoff_service.list_handoffs(arguments.project_id)
        print(f"Project ID: {listing.project_id}", file=output)
        print("Handoffs:", file=output)
        if not listing.handoffs:
            print("- none", file=output)
        for view in listing.handoffs:
            print(
                f"- {view.handoff.handoff_id} | {view.handoff.artifact_id} | "
                f"{view.handoff.purpose} | {view.status}",
                file=output,
            )
        return 0
    if arguments.command == "artifact":
        view = artifact_service.get_artifact(
            arguments.project_id, arguments.artifact_id
        )
        artifact_format = ProjectArtifactFormat(arguments.format)
        rendered = render_project_artifact(view, artifact_format)
        output.write(rendered)
        if artifact_format is not ProjectArtifactFormat.TEXT and not rendered.endswith(
            "\n"
        ):
            output.write("\n")
        return 0
    if arguments.command == "export-artifact":
        requested = arguments.output
        destination = (
            requested
            if requested.is_absolute()
            else (cwd if cwd is not None else Path.cwd()) / requested
        )
        result = export_service.export_artifact(
            arguments.project_id,
            arguments.artifact_id,
            ProjectArtifactFormat(arguments.format),
            destination,
        )
        print(f"Exported artifact: {result.artifact_id}", file=output)
        print(f"Format: {result.format}", file=output)
        print(f"Output: {result.output_path}", file=output)
        print(f"Bytes: {result.bytes_written}", file=output)
        print(f"SHA-256: {result.sha256}", file=output)
        return 0
    if arguments.command == "approve-developer-plan":
        result = action_service.approve_developer_plan(
            ApproveDeveloperPlanCommand(project_id=arguments.project_id)
        )
        _print_project_action_result(result, output)
        return 0
    if arguments.command == "select-research-direction":
        result = action_service.select_research_direction(
            SelectResearchDirectionCommand(
                project_id=arguments.project_id,
                direction_id=arguments.direction_id,
            )
        )
        _print_project_action_result(result, output)
        return 0
    if arguments.command == "approve-research-plan":
        result = action_service.approve_research_plan(
            ApproveResearchPlanCommand(project_id=arguments.project_id)
        )
        _print_project_action_result(result, output)
        return 0
    if arguments.command == "continue-developer":
        result = action_service.continue_developer(
            ContinueDeveloperCommand(project_id=arguments.project_id)
        )
        _print_project_action_result(result, output)
        return 0
    if arguments.command == "continue-researcher":
        result = action_service.continue_researcher(
            ContinueResearcherCommand(project_id=arguments.project_id)
        )
        _print_project_action_result(result, output)
        return 0
    if arguments.command == "provide-research-results":
        result_path = _resolve_path(arguments.input, cwd or Path.cwd())
        try:
            submission = ResearchResultSubmission.model_validate_json(
                result_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as error:
            raise CliError(
                f"Could not read valid result JSON: {result_path}"
            ) from error
        result = action_service.provide_research_results(
            ProvideResearchResultsCommand(
                project_id=arguments.project_id, submission=submission
            )
        )
        _print_project_action_result(result, output)
        return 0
    if arguments.command == "confirm-mode":
        stored = service.confirm_project_mode(
            arguments.project_id,
            WorkMode(arguments.work_mode),
            ProjectMode(arguments.project_mode),
        )
        _print_project_session(stored.project, output)
        return 0
    if arguments.command == "bind-developer":
        stored = service.bind_developer_run(
            arguments.project_id, arguments.developer_run_id
        )
        _print_project_session(stored.project, output)
        return 0
    if arguments.command == "bind-research":
        stored = service.bind_research_run(
            arguments.project_id, arguments.research_run_id
        )
        _print_project_session(stored.project, output)
        return 0
    if arguments.command == "complete":
        _print_project_session(
            service.complete_project(arguments.project_id).project, output
        )
        return 0
    if arguments.command == "pending-action":
        project = service.get_project(arguments.project_id).project
        _print_project_session(project, output)
        _print_pending_actions(
            service.get_pending_actions(arguments.project_id), output
        )
        return 0
    resume = service.resume_project(arguments.project_id)
    _print_resume(resume, output)
    return 0


def _run_existing_project_command(
    arguments: argparse.Namespace,
    store_root: Path,
    build_service: ProjectServiceBuilder,
    output: TextIO,
) -> int:
    store = FileProjectRunStore(store_root)
    workspace = store.workspace_root_for(arguments.project_run_id)
    if not workspace.is_dir():
        raise CliError(f"Saved workspace is not available: {workspace}")
    service = build_service(workspace, store)

    if arguments.command == "status":
        stored = service.get_project(arguments.project_run_id)
        if arguments.as_json:
            print(
                json.dumps(
                    {
                        "workspace": str(workspace),
                        **stored.model_dump(mode="json"),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                file=output,
            )
        else:
            _print_project_status(stored, workspace, output)
        return 0

    if arguments.command == "plan":
        _print_plan_review(service.get_plan(arguments.project_run_id), output)
        return 0

    if arguments.command == "analysis":
        _print_upgrade_analysis(service.get_analysis(arguments.project_run_id), output)
        return 0

    if arguments.command == "revise-plan":
        before = service.get_plan(arguments.project_run_id)
        stored = service.revise_plan(arguments.project_run_id, arguments.note)
        _print_plan_revision(before.active_version, stored, workspace, output)
        return 0

    if arguments.command == "approve-plan":
        stored = service.approve_plan(arguments.project_run_id)
        _print_plan_approval(stored, workspace, output)
        return 0

    if arguments.command == "execute":
        stored = service.execute_current_phase(arguments.project_run_id)
        _print_execution_summary(stored, workspace, output)
        return 0

    stored = service.decide_current_phase(
        arguments.project_run_id,
        arguments.decision,
        note=arguments.note,
    )
    _print_decision_summary(stored, workspace, output)
    return 0


def _build_production_service(
    workspace: Path,
    store: FileProjectRunStore,
) -> ProjectApplicationService:
    """Reuse the production composition root while swapping only persistence."""
    from ai_agent_project.composition import create_default_project_application_service

    return create_default_project_application_service(workspace, store=store)


def _resolve_path(path: Path, cwd: Path) -> Path:
    return (path if path.is_absolute() else cwd / path).expanduser().resolve()


def _resolve_store_root(
    argument_root: Path | None,
    injected_root: Path | None,
    *,
    default: Path | None = None,
) -> Path:
    root = argument_root or injected_root or default or default_project_run_store_root()
    return root.expanduser().resolve()


def _source_format(plan_path: Path) -> str | None:
    if plan_path.suffix.lower() == ".md":
        return "markdown"
    if plan_path.suffix.lower() == ".txt":
        return "text"
    return None


def _print_project_summary(
    stored: StoredProjectRun,
    workspace: Path,
    output: TextIO,
) -> None:
    state = stored.project_run.execution_state
    print(f"Project run: {stored.id}", file=output)
    print(f"Project: {stored.project_run.project_specification.title}", file=output)
    print(f"Mode: {stored.project_run.mode}", file=output)
    print(f"Status: {state.status}", file=output)
    _print_plan_line(stored, output)
    print(f"Current phase: {state.current_phase_id or '-'}", file=output)
    print(f"Phases: {len(stored.project_run.project_plan.phases)}", file=output)
    print(f"Workspace: {workspace}", file=output)


def _print_project_status(
    stored: StoredProjectRun,
    workspace: Path,
    output: TextIO,
) -> None:
    state = stored.project_run.execution_state
    print(f"Project: {stored.project_run.project_specification.title}", file=output)
    print(f"Run ID: {stored.id}", file=output)
    print(f"Mode: {stored.project_run.mode}", file=output)
    print(f"Status: {state.status}", file=output)
    _print_plan_line(stored, output)
    print(f"Workspace: {workspace}", file=output)
    print(f"Current phase: {state.current_phase_id or '-'}", file=output)
    print("Phases:", file=output)
    records = {record.phase_id: record for record in state.phase_records}
    for phase in stored.project_run.project_plan.phases:
        record = records[phase.id]
        marker = "x" if phase.id in state.completed_phase_ids else " "
        detail = f"attempts={record.attempt_count}"
        if record.execution is not None:
            detail += f", execution={record.execution.status}"
        if record.progress_report is not None:
            detail += (
                ", requirements="
                f"passed:{len(record.progress_report.passed_requirement_ids)} "
                f"failed:{len(record.progress_report.failed_requirement_ids)} "
                f"unknown:{len(record.progress_report.unknown_requirement_ids)}"
            )
        if record.checkpoint is not None:
            detail += (
                f", checkpoint={record.checkpoint.status}"
                f"/{record.checkpoint.decision or '-'}"
            )
        print(f"[{marker}] {phase.id} {phase.title} ({detail})", file=output)


def _print_project_session(project: object, output: TextIO) -> None:
    from ai_agent_project.agent.project_session import ProjectSession

    if not isinstance(project, ProjectSession):
        raise CliError("Stored project session is invalid")
    print(f"Project ID: {project.project_id}", file=output)
    print(f"Status: {project.status}", file=output)
    print(
        "Mode proposal: "
        f"{project.mode_proposal.proposed_work_mode} + "
        f"{project.mode_proposal.proposed_project_mode}",
        file=output,
    )
    print(f"Work mode: {project.work_mode or '-'}", file=output)
    print(f"Project mode: {project.project_mode or '-'}", file=output)
    print(f"Developer run: {project.developer_run_id or '-'}", file=output)
    print(f"Research run: {project.research_run_id or '-'}", file=output)


def _print_pending_actions(actions: tuple[object, ...], output: TextIO) -> None:
    from ai_agent_project.agent.project_session import ProjectPendingAction

    print("Pending action(s):", file=output)
    if not actions:
        print("- none", file=output)
        return
    for action in actions:
        if not isinstance(action, ProjectPendingAction):
            raise CliError("Project pending action is invalid")
        print(f"- {action.action_type}: {action.message}", file=output)
        print(
            f"  Suggested explicit next command/action: {action.suggested_action}",
            file=output,
        )


def _print_resume(resume: object, output: TextIO) -> None:
    from ai_agent_project.agent.project_session_application import ProjectResumeView

    if not isinstance(resume, ProjectResumeView):
        raise CliError("Project resume view is invalid")
    print(f"Project ID: {resume.project_id}", file=output)
    print(f"Status: {resume.status}", file=output)
    print(f"Work mode: {resume.work_mode or '-'}", file=output)
    print(f"Project mode: {resume.project_mode or '-'}", file=output)
    print(f"Developer run: {resume.developer_run_id or '-'}", file=output)
    print(f"Research run: {resume.research_run_id or '-'}", file=output)
    _print_pending_actions(resume.pending_actions, output)


def _print_execution_summary(
    stored: StoredProjectRun,
    workspace: Path,
    output: TextIO,
) -> None:
    state = stored.project_run.execution_state
    if state.current_phase_id is None:
        raise CliError("Execution did not leave a current phase to report")
    phase = next(
        phase
        for phase in stored.project_run.project_plan.phases
        if phase.id == state.current_phase_id
    )
    record = next(
        record for record in state.phase_records if record.phase_id == phase.id
    )
    if (
        record.execution is None
        or record.progress_report is None
        or record.checkpoint is None
    ):
        raise CliError("Execution result is missing phase progress or checkpoint data")
    report = record.progress_report
    print(f"Phase: {phase.id} {phase.title}", file=output)
    print(f"Execution status: {record.execution.status}", file=output)
    print(
        "Requirements: "
        f"passed:{len(report.passed_requirement_ids)} "
        f"failed:{len(report.failed_requirement_ids)} "
        f"unknown:{len(report.unknown_requirement_ids)}",
        file=output,
    )
    print(f"Repairs: {len(record.execution.repair_attempts)}", file=output)
    print(f"Checkpoint: {record.checkpoint.status}", file=output)
    print(
        "Recommended decisions: "
        + ", ".join(decision.value for decision in report.recommended_decisions),
        file=output,
    )
    print(f"Workspace: {workspace}", file=output)


def _print_decision_summary(
    stored: StoredProjectRun,
    workspace: Path,
    output: TextIO,
) -> None:
    state = stored.project_run.execution_state
    print(f"Project status: {state.status}", file=output)
    print(f"Current phase: {state.current_phase_id or '-'}", file=output)
    print(f"Workspace: {workspace}", file=output)


def _print_plan_line(stored: StoredProjectRun, output: TextIO) -> None:
    revision_state = stored.project_run.plan_revision_state
    if revision_state is not None:
        print(
            f"Plan: version {revision_state.active_version} ({revision_state.status})",
            file=output,
        )


def _print_plan_review(revision_state: object, output: TextIO) -> None:
    from ai_agent_project.agent.plan_revision import PlanRevisionState

    if not isinstance(revision_state, PlanRevisionState):
        raise CliError("Stored project plan review is invalid")
    print(f"Plan version: {revision_state.active_version}", file=output)
    print(f"Review status: {revision_state.status}", file=output)
    print("Phases:", file=output)
    for phase in revision_state.active_plan.phases:
        print(f"- {phase.id}: {phase.title} — {phase.objective}", file=output)
    if len(revision_state.revisions) > 1:
        print("Revision history:", file=output)
        for revision in revision_state.revisions:
            feedback = revision.feedback or "initial plan"
            print(f"- v{revision.version}: {feedback}", file=output)


def _print_plan_revision(
    previous_version: int,
    stored: StoredProjectRun,
    workspace: Path,
    output: TextIO,
) -> None:
    revision_state = stored.project_run.plan_revision_state
    if revision_state is None:
        raise CliError("Revised project is missing plan review state")
    print(
        f"Plan revised: v{previous_version} -> v{revision_state.active_version}",
        file=output,
    )
    print(f"Review status: {revision_state.status}", file=output)
    for phase in revision_state.active_plan.phases:
        print(f"- {phase.id}: {phase.title}", file=output)
    print(f"Workspace: {workspace}", file=output)


def _print_plan_approval(
    stored: StoredProjectRun,
    workspace: Path,
    output: TextIO,
) -> None:
    revision_state = stored.project_run.plan_revision_state
    if revision_state is None:
        raise CliError("Approved project is missing plan review state")
    print(f"Project status: {stored.project_run.execution_state.status}", file=output)
    print(f"Plan version: {revision_state.active_version}", file=output)
    print(
        f"Current phase: {stored.project_run.execution_state.current_phase_id or '-'}",
        file=output,
    )
    print(f"Workspace: {workspace}", file=output)


def _print_upgrade_analysis(context: object, output: TextIO) -> None:
    """Render compact persisted upgrade context without dumping workspace contents."""
    from ai_agent_project.agent.upgrade import UpgradeContext

    if not isinstance(context, UpgradeContext):
        raise CliError("Stored upgrade analysis is invalid")
    analysis = context.codebase_analysis
    impact = context.upgrade_specification.impact
    print(f"Project type: {analysis.project_type or '-'}", file=output)
    print(f"Summary: {analysis.summary or '-'}", file=output)
    print(f"Baseline: {context.baseline_validation.status}", file=output)
    print("Components:", file=output)
    for component in analysis.components:
        print(f"- {component.name} ({component.kind})", file=output)
    print("Affected files:", file=output)
    for path in impact.affected_files:
        print(f"- {path}", file=output)
    if impact.regression_risks:
        print("Regression risks:", file=output)
        for risk in impact.regression_risks:
            print(f"- {risk}", file=output)


def _run_research_command(
    arguments: argparse.Namespace,
    cwd: Path,
    store_root: Path,
    build_service: ResearchServiceBuilder,
    output: TextIO,
) -> int:
    store = FileResearchRunStore(store_root)
    if arguments.command == "create":
        request_path = _resolve_path(arguments.request_file, cwd)
        try:
            topic = request_path.read_text(encoding="utf-8")
        except OSError as error:
            raise CliError(
                f"Could not read research request file: {request_path}"
            ) from error
        if not topic.strip():
            raise CliError("Research request file must not be empty")
        workspace = (
            _resolve_path(arguments.workspace, cwd) if arguments.workspace else cwd
        )
        if not workspace.is_dir():
            raise CliError(f"Workspace is not a directory: {workspace}")
        stored = build_service(workspace, store).create_research_run(topic)
        _print_research_summary(stored, workspace, output)
        return 0

    service = build_service(cwd, store)
    if arguments.command == "status":
        _print_research_status(
            service.get_research_run(arguments.research_run_id), output
        )
        return 0
    if arguments.command == "report":
        report = service.get_research_report(arguments.research_run_id)
        if arguments.as_json:
            print(
                json.dumps(report.model_dump(mode="json"), ensure_ascii=False),
                file=output,
            )
        else:
            _print_research_report(report, output)
        return 0
    if arguments.command == "directions":
        _print_research_directions(
            service.get_research_directions(arguments.research_run_id), output
        )
        return 0
    if arguments.command == "plan":
        _print_research_plan(service.generate_plan(arguments.research_run_id), output)
        return 0
    if arguments.command == "show-plan":
        _print_research_plan_state(service.get_plan(arguments.research_run_id), output)
        return 0
    if arguments.command == "revise-plan":
        _print_research_plan(
            service.revise_plan(arguments.research_run_id, arguments.note), output
        )
        return 0
    if arguments.command == "approve-plan":
        _print_research_plan(service.approve_plan(arguments.research_run_id), output)
        return 0
    if arguments.command == "implementation-plan":
        _print_implementation_plan(
            service.generate_implementation_plan(arguments.research_run_id), output
        )
        return 0
    if arguments.command == "show-implementation-plan":
        _print_implementation_plan_value(
            service.get_implementation_plan(arguments.research_run_id), output
        )
        return 0
    if arguments.command == "generate-package":
        _print_implementation_package(
            service.generate_implementation_package(arguments.research_run_id), output
        )
        return 0
    if arguments.command == "show-package":
        _print_implementation_package_value(
            service.get_implementation_package(arguments.research_run_id), output
        )
        return 0
    if arguments.command == "result-guide":
        print(service.prepare_result_submission(arguments.research_run_id), file=output)
        return 0
    if arguments.command == "submit-results":
        from ai_agent_project.agent.research import ResearchResultSubmission

        result_path = _resolve_path(arguments.result_json_file, cwd)
        try:
            submission = ResearchResultSubmission.model_validate_json(
                result_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as error:
            raise CliError(
                f"Could not read valid result JSON: {result_path}"
            ) from error
        stored = service.submit_results(arguments.research_run_id, submission)
        print(f"Status: {stored.research_run.status}", file=output)
        return 0
    if arguments.command == "show-results":
        print(
            json.dumps(
                service.get_results(arguments.research_run_id).model_dump(mode="json"),
                ensure_ascii=False,
            ),
            file=output,
        )
        return 0
    if arguments.command == "analyze-results":
        from ai_agent_project.agent.research_application import (
            ResearchResultsNotProvidedError,
        )

        try:
            stored = service.analyze_results(arguments.research_run_id)
        except ResearchResultsNotProvidedError as error:
            raise CliError(
                "Use result-guide and submit-results before analysis"
            ) from error
        print(f"Status: {stored.research_run.status}", file=output)
        return 0
    if arguments.command == "show-analysis":
        print(
            json.dumps(
                service.get_result_analysis(arguments.research_run_id).model_dump(
                    mode="json"
                ),
                ensure_ascii=False,
            ),
            file=output,
        )
        return 0
    if arguments.command == "synthesize":
        _print_research_synthesis(
            service.generate_synthesis(arguments.research_run_id), output
        )
        return 0
    if arguments.command == "show-synthesis":
        _print_research_synthesis_value(
            service.get_synthesis(arguments.research_run_id), output
        )
        return 0
    if arguments.command == "paper-materials":
        _print_research_paper_materials(
            service.generate_paper_materials(arguments.research_run_id), output
        )
        return 0
    if arguments.command == "show-paper-materials":
        _print_research_paper_materials_value(
            service.get_paper_materials(arguments.research_run_id), output
        )
        return 0
    stored = service.select_research_direction(
        arguments.research_run_id, arguments.direction_id
    )
    print(
        f"Selected direction: {stored.research_run.selected_direction_id}", file=output
    )
    print(f"Status: {stored.research_run.status}", file=output)
    return 0


def _build_production_research_service(
    workspace: Path, store: FileResearchRunStore
) -> ResearchApplicationService:
    """Reuse the API composition root with real web retrieval and CLI persistence."""
    from ai_agent_project.composition import create_default_research_application_service

    return create_default_research_application_service(workspace, store=store)


def _build_production_project_session_service(
    store: FileProjectStore,
) -> ProjectSessionService:
    from ai_agent_project.composition import create_default_project_session_service

    return create_default_project_session_service(
        store=store,
        developer_run_reader=FileProjectRunStore(default_project_run_store_root()),
        research_run_reader=FileResearchRunStore(default_research_run_store_root()),
    )


def _build_provider_free_project_session_service(
    store: FileProjectStore,
) -> ProjectSessionService:
    """Compose project-session reads and explicit transitions without a provider."""
    return ProjectSessionService(
        store,
        developer_run_reader=FileProjectRunStore(default_project_run_store_root()),
        research_run_reader=FileResearchRunStore(default_research_run_store_root()),
    )


class _CliDeveloperActions:
    def __init__(self, store: FileProjectRunStore) -> None:
        self._store = store
        self._checkpoint_service = _checkpoint_project_service(store)

    def approve_plan(self, run_id: str) -> StoredProjectRun:
        return self._checkpoint_service.approve_plan(run_id)

    def execute_current_phase(self, run_id: str) -> StoredProjectRun:
        workspace = self._store.workspace_root_for(run_id)
        return _build_production_service(workspace, self._store).execute_current_phase(
            run_id
        )


class _CliResearchActions:
    def __init__(self, store: FileResearchRunStore) -> None:
        self._store = store
        self._checkpoint_service = _checkpoint_research_service(store)

    def get_research_run(self, run_id: str) -> StoredResearchRun:
        return self._checkpoint_service.get_research_run(run_id)

    def select_research_direction(
        self, run_id: str, direction_id: str
    ) -> StoredResearchRun:
        return self._checkpoint_service.select_research_direction(run_id, direction_id)

    def approve_plan(self, run_id: str) -> StoredResearchRun:
        return self._checkpoint_service.approve_plan(run_id)

    def submit_results(
        self, run_id: str, submission: ResearchResultSubmission
    ) -> StoredResearchRun:
        return self._checkpoint_service.submit_results(run_id, submission)

    def generate_plan(self, run_id: str) -> StoredResearchRun:
        from ai_agent_project.llm.providers.openai_research_plan_generator import (
            OpenAIResearchPlanGenerator,
        )

        return self._production(
            plan_generator=OpenAIResearchPlanGenerator()
        ).generate_plan(run_id)

    def generate_implementation_plan(self, run_id: str) -> StoredResearchRun:
        from ai_agent_project.llm.providers.openai_research_implementation import (
            OpenAIResearchImplementationPlanner,
        )

        return self._production(
            implementation_planner=OpenAIResearchImplementationPlanner()
        ).generate_implementation_plan(run_id)

    def generate_implementation_package(self, run_id: str) -> StoredResearchRun:
        from ai_agent_project.llm.providers.openai_research_implementation import (
            OpenAIResearchImplementationGenerator,
        )

        return self._production(
            implementation_generator=OpenAIResearchImplementationGenerator()
        ).generate_implementation_package(run_id)

    def analyze_results(self, run_id: str) -> StoredResearchRun:
        from ai_agent_project.llm.providers.openai_research_result_analyzer import (
            OpenAIResearchResultAnalyzer,
        )

        return self._production(
            result_analyzer=OpenAIResearchResultAnalyzer()
        ).analyze_results(run_id)

    def generate_synthesis(self, run_id: str) -> StoredResearchRun:
        from ai_agent_project.llm.providers.openai_research_result_synthesizer import (
            OpenAIResearchResultSynthesizer,
        )

        return self._production(
            result_synthesizer=OpenAIResearchResultSynthesizer()
        ).generate_synthesis(run_id)

    def generate_paper_materials(self, run_id: str) -> StoredResearchRun:
        from ai_agent_project.llm.providers.openai_research_paper_materials import (
            OpenAIResearchPaperMaterialsGenerator,
        )

        return self._production(
            paper_materials_generator=OpenAIResearchPaperMaterialsGenerator()
        ).generate_paper_materials(run_id)

    def _production(self, **providers: object) -> ResearchApplicationService:
        from ai_agent_project.agent.research_discovery import ResearchDiscoveryService
        from ai_agent_project.improvement.context import ImprovementAwareApplication
        from ai_agent_project.improvement.service import build_improvement_service

        return ImprovementAwareApplication(
            ResearchApplicationService(
                cast(ResearchDiscoveryService, object()), self._store, **providers
            ),
            build_improvement_service(researcher_reader=self._store),
            "researcher",
        )


def _build_project_action_service(
    sessions: ProjectSessionService,
    developer_store: FileProjectRunStore,
    research_store: FileResearchRunStore,
    workspace: Path,
) -> ProjectActionService:
    """Compose lazy progression plus provider-free checkpoint domain services."""
    del workspace
    return ProjectActionService(
        sessions,
        _CliDeveloperActions(developer_store),
        _CliResearchActions(research_store),
    )


def _checkpoint_project_service(
    developer_store: FileProjectRunStore,
) -> ProjectApplicationService:
    from ai_agent_project.agent.checkpoint import (
        PhaseCheckpointService,
        ProgressReporter,
    )
    from ai_agent_project.agent.phase_execution import PhaseExecutionService
    from ai_agent_project.agent.project_execution import ProjectExecutionService
    from ai_agent_project.agent.project_runner import ProjectRunner

    unavailable = object()
    execution = ProjectExecutionService(
        cast(PhaseExecutionService, unavailable),
        ProgressReporter(),
        PhaseCheckpointService(),
    )
    return ProjectApplicationService(
        cast(ProjectRunner, unavailable), execution, developer_store
    )


def _checkpoint_research_service(
    research_store: FileResearchRunStore,
) -> ResearchApplicationService:
    from ai_agent_project.agent.research_discovery import ResearchDiscoveryService

    unavailable = object()
    return ResearchApplicationService(
        cast(ResearchDiscoveryService, unavailable), research_store
    )


def _print_project_action_result(result: ProjectActionResult, output: TextIO) -> None:
    next_action = (
        result.next_pending_action.action_type.value
        if result.next_pending_action is not None
        else "none"
    )
    print(f"Project ID: {result.project_id}", file=output)
    print(f"Action: {result.action.value}", file=output)
    print(
        f"Previous pending action: {result.previous_pending_action.action_type.value}",
        file=output,
    )
    print(f"Next pending action: {next_action}", file=output)
    print(f"Source domain: {result.source_domain.value}", file=output)
    print(f"Source run: {result.source_run_id}", file=output)
    print(f"Source status: {result.source_status}", file=output)


def _print_hybrid_coordination(view: HybridCoordinationView, output: TextIO) -> None:
    print(f"Project ID: {view.project_id}", file=output)
    print(f"Project status: {view.project_status}", file=output)
    for label, lane in (("Developer", view.developer), ("Researcher", view.researcher)):
        action = (
            lane.pending_action.action_type.value if lane.pending_action else "none"
        )
        print(f"{label} run ID: {lane.run_id or '-'}", file=output)
        print(f"{label} status: {lane.source_status or '-'}", file=output)
        print(f"{label} pending action: {action}", file=output)
        print(f"{label} terminal: {str(lane.terminal).lower()}", file=output)
    print("Actionable actions:", file=output)
    if not view.actionable_actions:
        print("- none", file=output)
    for action in view.actionable_actions:
        print(f"- {action.action_type.value}", file=output)
    print(
        f"Both workflows terminal: {str(view.both_workflows_terminal).lower()}",
        file=output,
    )


def _print_research_summary(
    stored: StoredResearchRun, workspace: Path, output: TextIO
) -> None:
    report = stored.research_run.report
    print(f"Research run: {stored.id}", file=output)
    print(f"Topic: {stored.research_run.request.topic}", file=output)
    print(f"Status: {stored.research_run.status}", file=output)
    print(f"Questions: {len(report.questions)}", file=output)
    print(f"Sources: {len(report.sources)}", file=output)
    print(f"Evidence: {len(report.evidence)}", file=output)
    print(f"Related studies: {len(report.related_studies)}", file=output)
    print(f"Research gaps: {len(report.gaps)}", file=output)
    print(f"Directions: {len(report.directions)}", file=output)
    print(f"Workspace: {workspace}", file=output)


def _print_research_status(stored: StoredResearchRun, output: TextIO) -> None:
    report = stored.research_run.report
    print(f"Research run: {stored.id}", file=output)
    print(f"Topic: {stored.research_run.request.topic}", file=output)
    print(f"Status: {stored.research_run.status}", file=output)
    print(
        f"Selected direction: {stored.research_run.selected_direction_id or '-'}",
        file=output,
    )
    for label, values in (
        ("Questions", report.questions),
        ("Sources", report.sources),
        ("Evidence", report.evidence),
        ("Related studies", report.related_studies),
        ("Gaps", report.gaps),
        ("Directions", report.directions),
    ):
        print(f"{label}: {len(values)}", file=output)


def _print_research_report(report: object, output: TextIO) -> None:
    from ai_agent_project.agent.research import ResearchDiscoveryReport

    if not isinstance(report, ResearchDiscoveryReport):
        raise CliError("Stored research report is invalid")
    print("Preliminary Research", file=output)
    print(report.preliminary.topic if report.preliminary else "-", file=output)
    print("Related Work", file=output)
    for study in report.related_studies:
        print(f"- {study.id}: {study.title}", file=output)
    print("Research Landscape", file=output)
    for stage in () if report.landscape is None else report.landscape.stages:
        print(f"- {stage.id}: {stage.title}", file=output)
    print("Research Gaps", file=output)
    for gap in report.gaps:
        print(f"- {gap.id}: {gap.description}", file=output)
    print("Research Directions", file=output)
    _print_research_directions(report.directions, output)


def _print_research_directions(directions: object, output: TextIO) -> None:
    from ai_agent_project.agent.research import ResearchDirection

    if not isinstance(directions, tuple):
        raise CliError("Stored research directions are invalid")
    if not directions:
        print(
            "No defensible research directions were identified from the available evidence.",
            file=output,
        )
        return
    for direction in directions:
        if not isinstance(direction, ResearchDirection):
            raise CliError("Stored research directions are invalid")
        print(f"{direction.id}\nTitle: {direction.title}", file=output)
        print(f"Research question: {direction.research_question}", file=output)
        print(f"Target gaps: {', '.join(direction.target_gap_ids)}", file=output)
        print(f"Novelty: {direction.novelty}", file=output)
        print(
            f"Expected contributions: {', '.join(direction.expected_contributions) or '-'}",
            file=output,
        )
        print(f"Feasibility: {direction.feasibility}", file=output)
        print(f"Risks: {', '.join(direction.risks) or '-'}", file=output)


def _print_research_plan(stored: StoredResearchRun, output: TextIO) -> None:
    state = stored.research_run.plan_revision_state
    if state is None:
        raise CliError("Research plan is missing")
    print(f"Status: {stored.research_run.status}", file=output)
    _print_research_plan_state(state, output)


def _print_research_plan_state(state: object, output: TextIO) -> None:
    from ai_agent_project.agent.research import ResearchPlanRevisionState

    if not isinstance(state, ResearchPlanRevisionState):
        raise CliError("Stored research plan is invalid")
    plan = state.active_plan
    print(f"Plan version: {state.active_version}", file=output)
    print(f"Approved: {state.approved}", file=output)
    print(f"Title: {plan.title}", file=output)
    print(f"Selected direction: {plan.selected_direction_id}", file=output)
    print(f"Objectives: {len(plan.objectives)}", file=output)
    print(f"Methodology steps: {len(plan.methodology)}", file=output)
    print(f"Metrics: {len(plan.metrics)}", file=output)
    print(f"Success criteria: {len(plan.success_criteria)}", file=output)


def _print_implementation_plan(stored: StoredResearchRun, output: TextIO) -> None:
    plan = stored.research_run.implementation_plan
    if plan is None:
        raise CliError("Research implementation plan is missing")
    print(f"Status: {stored.research_run.status}", file=output)
    _print_implementation_plan_value(plan, output)


def _print_implementation_plan_value(plan: object, output: TextIO) -> None:
    from ai_agent_project.agent.research import ResearchImplementationPlan

    if not isinstance(plan, ResearchImplementationPlan):
        raise CliError("Stored research implementation plan is invalid")
    print("Generated only; not executed.", file=output)
    print(f"Approved plan version: {plan.approved_plan_version}", file=output)
    print(f"Tasks: {len(plan.tasks)}", file=output)
    for task in plan.tasks:
        print(f"- {task.task_id}: {task.title}", file=output)


def _print_implementation_package(stored: StoredResearchRun, output: TextIO) -> None:
    package = stored.research_run.implementation_package
    if package is None:
        raise CliError("Research implementation package is missing")
    print(f"Status: {stored.research_run.status}", file=output)
    _print_implementation_package_value(package, output)


def _print_implementation_package_value(package: object, output: TextIO) -> None:
    from ai_agent_project.agent.research import ResearchImplementationPackage

    if not isinstance(package, ResearchImplementationPackage):
        raise CliError("Stored research implementation package is invalid")
    print("Generated only; not executed.", file=output)
    print(f"Artifacts: {len(package.artifacts)}", file=output)
    print("Execution guide:", file=output)
    print(package.execution_guide, file=output)


def _print_research_synthesis(stored: StoredResearchRun, output: TextIO) -> None:
    synthesis = stored.research_run.result_synthesis
    if synthesis is None:
        raise CliError("Research synthesis is missing")
    print(f"Status: {stored.research_run.status}", file=output)
    _print_research_synthesis_value(synthesis, output)


def _print_research_synthesis_value(synthesis: object, output: TextIO) -> None:
    from ai_agent_project.agent.research import ResearchResultSynthesis

    if not isinstance(synthesis, ResearchResultSynthesis):
        raise CliError("Stored research synthesis is invalid")
    print(f"Summary: {synthesis.synthesis_summary}", file=output)
    print("Objective conclusions:", file=output)
    for conclusion in synthesis.objective_conclusions:
        print(
            f"- {conclusion.objective_id}: {conclusion.assessment} — "
            f"{conclusion.conclusion}",
            file=output,
        )
    print("Findings:", file=output)
    for finding in (
        *synthesis.major_findings,
        *synthesis.inconclusive_findings,
        *synthesis.negative_findings,
    ):
        print(
            f"- {finding.claim_id} ({finding.support_status}): {finding.statement}",
            file=output,
        )
    print("Limitations:", file=output)
    for limitation in synthesis.limitations:
        print(f"- {limitation}", file=output)
    print("Missing evidence:", file=output)
    for missing in synthesis.missing_evidence:
        print(f"- {missing}", file=output)


def _print_research_paper_materials(stored: StoredResearchRun, output: TextIO) -> None:
    materials = stored.research_run.paper_materials
    if materials is None:
        raise CliError("Research paper materials are missing")
    print(f"Status: {stored.research_run.status}", file=output)
    _print_research_paper_materials_value(materials, output)


def _print_research_paper_materials_value(materials: object, output: TextIO) -> None:
    from ai_agent_project.agent.research import ResearchPaperMaterials

    if not isinstance(materials, ResearchPaperMaterials):
        raise CliError("Stored research paper materials are invalid")
    print(f"Research problem: {materials.research_problem}", file=output)
    print("Usable claims:", file=output)
    for claim in materials.usable_claims:
        print(f"- {claim.claim_id}: {claim.statement}", file=output)
    print("Prohibited claims:", file=output)
    for claim in materials.prohibited_claims:
        print(f"- {claim.claim_id}: {claim.statement}", file=output)
    print("Key results:", file=output)
    for result in materials.key_results:
        print(
            f"- {result.metric_id}: {result.value} ({result.observation_status})",
            file=output,
        )
