"""Thin command-line interface for explicit project lifecycle operations."""

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TextIO

from ai_agent_project.agent.checkpoint import CheckpointDecision
from ai_agent_project.agent.project_application import (
    ProjectApplicationService,
    ProjectRunError,
    StoredProjectRun,
)
from ai_agent_project.agent.project_file_store import (
    FileProjectRunStore,
    ProjectRunStorageError,
    default_project_run_store_root,
)


class CliError(Exception):
    """An expected user-facing CLI error."""


ProjectServiceBuilder = Callable[[Path, FileProjectRunStore], ProjectApplicationService]


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI entry point without requiring a subprocess in tests."""
    return run_cli(argv if argv is not None else sys.argv[1:])


def run_cli(
    argv: Sequence[str],
    *,
    cwd: Path | None = None,
    store_root: Path | None = None,
    service_builder: ProjectServiceBuilder | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Parse and execute one explicit project lifecycle command."""
    output = stdout or sys.stdout
    errors = stderr or sys.stderr
    parser = _build_parser()
    arguments = parser.parse_args(list(argv))
    current_directory = (cwd or Path.cwd()).resolve()
    resolved_store_root = _resolve_store_root(arguments.store_root, store_root)
    build_service = service_builder or _build_production_service

    try:
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
        OSError,
        UnicodeError,
        ValueError,
    ) as error:
        print(f"Error: {error}", file=errors)
        return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-agent")
    top_level = parser.add_subparsers(dest="top_level", required=True)
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
    from ai_agent_project.api.app import create_default_project_application_service

    return create_default_project_application_service(workspace, store=store)


def _resolve_path(path: Path, cwd: Path) -> Path:
    return (path if path.is_absolute() else cwd / path).expanduser().resolve()


def _resolve_store_root(
    argument_root: Path | None,
    injected_root: Path | None,
) -> Path:
    root = argument_root or injected_root or default_project_run_store_root()
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
