"""Persisted 4B-3 acceptance. Every request runs in a fresh child process.

CLI uses the unmodified console entry point. API uses real services/stores;
only provider-dependent continuation boundaries use existing offline fixtures.
Shared historical helpers supply typed data, never acceptance expectations.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from ai_agent_project.agent.hybrid_coordination_application import (
    HybridCoordinationService,
)
from ai_agent_project.agent.project_application import ProjectApplicationService
from ai_agent_project.agent.project_artifact_application import ProjectArtifactService
from ai_agent_project.agent.project_execution import (
    ProjectExecutionService,
    ProjectExecutionStatus,
)
from ai_agent_project.agent.project_file_store import FileProjectRunStore
from ai_agent_project.agent.project_session_application import ProjectSessionService
from ai_agent_project.agent.project_session_file_store import FileProjectStore
from ai_agent_project.agent.research import ResearchRun, ResearchStatus, WorkMode
from ai_agent_project.agent.research_application import ResearchApplicationService
from ai_agent_project.agent.research_file_store import FileResearchRunStore
from ai_agent_project.api.app import create_app
from ai_agent_project.cli import main as cli_main
from test_4b2_api_acceptance import (
    NoProvider,
    _developer_run,
    _terminal_research_run,
    create_project,
    domain_services,
    identifier,
    research_at,
)

SCRIPT = Path(__file__).resolve()
ACTIONS = {
    "approve-developer-plan": "approve_plan",
    "select-research-direction": "select_research_direction",
    "approve-research-plan": "approve_plan",
    "continue-developer": "execute_current_phase",
    "continue-researcher": "generate_plan",
    "provide-research-results": "submit_results",
}


def stores(root: Path):
    base = root / "home/.local/share/ai-agent"
    return (
        FileProjectStore(root / "projects"),
        FileProjectRunStore(base / "project-runs", workspace_root=root / "workspace"),
        FileResearchRunStore(base / "research-runs"),
    )


def fixture(root: Path) -> dict:
    (root / "workspace").mkdir()
    (root / "workspace/SENTINEL.txt").write_text("Never read, write, or execute me.\n")
    ps, ds, rs = stores(root)
    sessions = ProjectSessionService(ps, NoProvider(), ds, rs)
    terminal = _terminal_research_run()
    pending = _developer_run()
    approver = ProjectApplicationService(
        object(), ProjectExecutionService(object(), object(), object()), ds
    )
    seed = identifier()
    ds.create(seed, pending)
    approver.approve_plan(seed)
    ready = ds.get(seed)
    done = ready.model_copy(
        update={
            "execution_state": ready.execution_state.model_copy(
                update={"status": ProjectExecutionStatus.COMPLETED}
            )
        }
    )
    selection = research_at(terminal, ResearchStatus.AWAITING_DIRECTION_SELECTION)
    approval = ResearchRun(
        request=terminal.request,
        report=terminal.report,
        status=ResearchStatus.AWAITING_RESEARCH_PLAN_APPROVAL,
        selected_direction_id=terminal.selected_direction_id,
        plan_revision_state=terminal.plan_revision_state.model_copy(
            update={"approved": False}
        ),
    )
    package = research_at(terminal, ResearchStatus.IMPLEMENTATION_PACKAGE_READY)
    result = {}

    def add(name, d=pending, r=selection, *, completed=False, mode=WorkMode.HYBRID):
        pid = create_project(ps, sessions, mode, name)
        did, rid = (
            identifier() if d is not None else None,
            identifier() if r is not None else None,
        )
        if did:
            if d != "missing":
                ds.create(did, d)
            sessions.bind_developer_run(pid, did)
        if rid:
            if r != "missing":
                rs.create(rid, r)
            sessions.bind_research_run(pid, rid)
        if completed:
            sessions.complete_project(pid)
        result[name] = {
            "project": pid,
            "developer": did,
            "researcher": rid,
            "ds": None
            if d is None or d == "missing"
            else d.execution_state.status.value,
            "rs": None if r is None or r == "missing" else r.status.value,
            "completed": completed,
        }

    add("A")
    add("B", done)
    add("C", r=terminal)
    add("D", done, terminal)
    add("E", None)
    add("F", r=None)
    add("G", "missing")
    add("H", r="missing")
    add("I", completed=True)
    add("J", done, terminal, completed=True)
    add("developer_only", r=None, mode=WorkMode.DEVELOPER)
    add("researcher_only", None, mode=WorkMode.RESEARCHER)
    add("unbound", None, None)
    for status in (ProjectExecutionStatus.FAILED, ProjectExecutionStatus.STOPPED):
        add(
            status.value,
            ready.model_copy(
                update={
                    "execution_state": ready.execution_state.model_copy(
                        update={"status": status}
                    )
                }
            ),
            terminal,
        )
    add(
        "research_failed",
        done,
        ResearchRun(
            request=terminal.request,
            report=terminal.report,
            status=ResearchStatus.FAILED,
        ),
    )
    add(
        "intermediate",
        done,
        research_at(terminal, ResearchStatus.RESEARCH_SYNTHESIS_READY),
    )
    add("approve-developer-plan")
    add("select-research-direction")
    add("approve-research-plan", r=approval)
    add("continue-developer", ready)
    add(
        "continue-researcher",
        r=research_at(terminal, ResearchStatus.DIRECTION_SELECTED),
    )
    add("provide-research-results", r=package)
    add("invalid_results", r=package)
    add("finish", done, research_at(terminal, ResearchStatus.RESEARCH_SYNTHESIS_READY))
    for label, mode in (
        ("artifact_developer", WorkMode.DEVELOPER),
        ("artifact_researcher", WorkMode.RESEARCHER),
    ):
        add(label, None, None, mode=mode)
        if mode is WorkMode.DEVELOPER:
            sessions.bind_developer_run(
                result[label]["project"], result["D"]["developer"]
            )
        else:
            sessions.bind_research_run(
                result[label]["project"], result["D"]["researcher"]
            )
    ds.create(identifier(), pending)
    rs.create(identifier(), terminal)
    for item in result.values():
        submission = terminal.result_submission.model_copy(
            update={"research_run_id": item["researcher"] or identifier()}
        )
        item["submission"] = submission.model_dump(mode="json")
        item["direction"] = terminal.selected_direction_id
    # Force deserialization through official stores before acceptance starts.
    for item in result.values():
        ps.get(item["project"])
        if item["developer"]:
            ds.get(item["developer"])
        if item["researcher"]:
            rs.get(item["researcher"])
    return result


def snapshot(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file()
    }


def worker(root: Path, transport: str, request: dict) -> None:
    calls = []

    # Audit applies only to application execution, not parent snapshots/fixture creation.
    def audit(event, args):
        if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
            path = Path(os.fsdecode(args[0])).absolute()
            if path.is_relative_to(root / "workspace"):
                raise AssertionError(
                    f"Application accessed unrelated workspace: {path}"
                )
        if event in {
            "subprocess.Popen",
            "os.system",
            "os.exec",
            "os.posix_spawn",
            "socket.connect",
        }:
            raise AssertionError(
                f"Application executed shell/process/network operation: {event}"
            )

    sys.addaudithook(audit)
    with contextlib.ExitStack() as stack:
        import openai

        for name in ("OpenAI", "AsyncOpenAI"):
            stack.enter_context(
                patch.object(
                    openai, name, side_effect=AssertionError("OpenAI constructed")
                )
            )
        for module_name, module in tuple(sys.modules.items()):
            if module_name.startswith("ai_agent_project.llm.providers."):
                for name, value in vars(module).items():
                    if name.startswith("OpenAI") and isinstance(value, type):
                        stack.enter_context(
                            patch.object(
                                value,
                                "__init__",
                                side_effect=AssertionError(
                                    "Production provider constructed"
                                ),
                            )
                        )
        for cls, methods in (
            (ProjectApplicationService, ["approve_plan", "execute_current_phase"]),
            (
                ResearchApplicationService,
                [
                    "select_research_direction",
                    "approve_plan",
                    "generate_plan",
                    "generate_implementation_plan",
                    "generate_implementation_package",
                    "submit_results",
                    "analyze_results",
                    "generate_synthesis",
                    "generate_paper_materials",
                ],
            ),
        ):
            for method in methods:
                original = getattr(cls, method)

                def wrapped(
                    self, *args, _original=original, _method=method, _cls=cls, **kwargs
                ):
                    calls.append([_cls.__name__, _method, args[0]])
                    return _original(self, *args, **kwargs)

                stack.enter_context(patch.object(cls, method, wrapped))
        action, pid = request["action"], request["project"]
        if transport == "cli":
            argv = [
                "project-session",
                "--store-root",
                str(root / "projects"),
                action,
                pid,
            ]
            if action == "select-research-direction":
                argv.append(request["direction"])
            if action == "provide-research-results":
                argv.extend(["--input", request["input"]])
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                status = cli_main(argv)
            response = {"status": status, "text": out.getvalue() + err.getvalue()}
        else:
            ps, ds, rs = stores(root)
            sessions = ProjectSessionService(ps, NoProvider(), ds, rs)
            developer, researcher = domain_services(ds, rs, _terminal_research_run())
            # Actual checkpoint approval uses real production execution service.
            if action != "continue-developer":
                developer = ProjectApplicationService(
                    object(), ProjectExecutionService(object(), object(), object()), ds
                )
            app = create_app(
                agent_service=object(),
                coding_agent_service=object(),
                project_application_service=developer,
                research_application_service=researcher,
                project_session_service=sessions,
                hybrid_coordination_service=HybridCoordinationService(sessions, ds, rs),
                project_artifact_service=ProjectArtifactService(sessions, ds, rs),
            )
            calls.clear()  # Exclude typed fixture provider setup above.
            with TestClient(app) as client:
                if action in ("coordination", "artifacts"):
                    res = client.get(f"/v1/projects/{pid}/{action}")
                elif action == "complete":
                    res = client.post(f"/v1/projects/{pid}/complete")
                else:
                    kwargs = {}
                    if action == "select-research-direction":
                        kwargs["json"] = {"direction_id": request["direction"]}
                    if action == "provide-research-results":
                        kwargs = {
                            "content": request["raw"],
                            "headers": {"Content-Type": "application/json"},
                        }
                    res = client.post(f"/v1/projects/{pid}/actions/{action}", **kwargs)
            response = {"status": res.status_code, "text": res.text, "body": res.json()}
        response["calls"] = calls
        print(json.dumps(response))


def run(transport: str, root: Path) -> None:
    data = fixture(root)
    initial = snapshot(root)
    initial_dirs = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_dir()}
    expected_files = set(initial)
    env = dict(os.environ, HOME=str(root / "home"), PYTHONDONTWRITEBYTECODE="1")
    env.pop("OPENAI_API_KEY", None)
    with TemporaryDirectory(prefix="ai-agent-4b3-inputs-") as inputs:

        def request(
            name,
            action="coordination",
            *,
            payload=None,
            success=True,
            error=None,
            operation=None,
        ):
            item = data[name]
            raw = json.dumps(item["submission"]) if payload is None else payload
            path = Path(inputs) / "submission.json"
            path.write_text(raw)
            req = dict(item, action=action, raw=raw, input=str(path))
            before = snapshot(root)
            child = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--worker",
                    transport,
                    "--root",
                    str(root),
                ],
                input=json.dumps(req),
                text=True,
                capture_output=True,
                env=env,
                cwd=SCRIPT.parent,
                timeout=60,
                check=False,
            )
            assert child.returncode == 0, child.stderr
            response = json.loads(child.stdout)
            status = response["status"]
            assert (status == (0 if transport == "cli" else 200)) == success, response
            if action == "coordination" and success:
                if transport == "cli":
                    assert response["text"].index("Developer run ID:") < response[
                        "text"
                    ].index("Researcher run ID:")
                else:
                    pending = response["body"]["actionable_actions"]
                    lanes = [
                        0
                        if (
                            a["developer_run_id"] is not None
                            or a["action_type"] == "bind_developer_run"
                        )
                        else 1
                        for a in pending
                    ]
                    assert lanes == sorted(lanes)
            if error:
                assert error.lower() in response["text"].lower(), response
            after = snapshot(root)
            changed = {
                p for p in set(before) | set(after) if before.get(p) != after.get(p)
            }
            if action == "complete" and success:
                assert changed == {f"projects/{item['project']}.json"}
                assert response["calls"] == []
            elif operation:
                lane = "developer" if "developer" in action else "researcher"
                store = "project-runs" if lane == "developer" else "research-runs"
                assert changed == {
                    f"home/.local/share/ai-agent/{store}/{item[lane]}.json"
                }, changed
                cls = (
                    "ProjectApplicationService"
                    if lane == "developer"
                    else "ResearchApplicationService"
                )
                assert response["calls"] == [[cls, operation, item[lane]]], response
            else:
                assert not changed, changed
                # Invalid typed result versions reach submit_results but cannot persist.
                if not (
                    action == "provide-research-results"
                    and error
                    and "different" in error
                ):
                    assert response["calls"] == [], response
            assert set(after) == expected_files, set(after) - expected_files
            return response

        expected_actions = {
            "A": ["approve_developer_plan", "select_research_direction"],
            "B": ["select_research_direction"],
            "C": ["approve_developer_plan"],
            "D": [],
            "E": ["bind_developer_run", "select_research_direction"],
            "F": ["approve_developer_plan", "bind_research_run"],
            "I": [],
            "J": [],
            "failed": ["continue_developer"],
            "stopped": ["continue_developer"],
            "research_failed": ["continue_researcher"],
            "intermediate": ["continue_researcher"],
        }
        for name, actions in expected_actions.items():
            item = data[name]
            res = request(name)
            both = item["ds"] == "completed" and item["rs"] == "paper_materials_ready"
            if transport == "api":
                view = res["body"]
                assert view["project_id"] == item["project"]
                assert view["project_status"] == (
                    "completed" if item["completed"] else "active"
                )
                assert [a["action_type"] for a in view["actionable_actions"]] == actions
                assert view["both_workflows_terminal"] is both
                for lane, key, terminal in [
                    ("developer", "ds", "completed"),
                    ("researcher", "rs", "paper_materials_ready"),
                ]:
                    value = view[lane]
                    assert value["source_domain"] == lane
                    assert (
                        value["run_id"] == item[lane]
                        and value["source_status"] == item[key]
                    )
                    assert value["terminal"] is (item[key] == terminal)
                    lane_actions = [
                        a
                        for a in actions
                        if ("developer" in a) == (lane == "developer")
                    ]
                    assert (
                        value["pending_action"]["action_type"]
                        if value["pending_action"]
                        else None
                    ) == (lane_actions[0] if lane_actions else None)
            else:
                text = res["text"]
                assert text.index("Developer run ID:") < text.index(
                    "Researcher run ID:"
                )
                assert (
                    f"Project status: {'completed' if item['completed'] else 'active'}"
                    in text
                )
                for label, key, terminal in [
                    ("Developer", "ds", "completed"),
                    ("Researcher", "rs", "paper_materials_ready"),
                ]:
                    assert f"{label} run ID: {item[label.lower()] or '-'}" in text
                    assert f"{label} status: {item[key] or '-'}" in text
                    assert (
                        f"{label} terminal: {str(item[key] == terminal).lower()}"
                        in text
                    )
                    lane_actions = [
                        a
                        for a in actions
                        if ("developer" in a) == (label == "Developer")
                    ]
                    assert (
                        f"{label} pending action: {lane_actions[0] if lane_actions else 'none'}"
                        in text
                    )
                assert (
                    "Actionable actions:\n"
                    + "".join(f"- {a}\n" for a in (actions or ["none"]))
                    in text
                )
                assert f"Both workflows terminal: {str(both).lower()}" in text
        print(f"{transport}: coordination matrix passed", flush=True)
        for name, error in [
            ("G", "Linked Developer run not found"),
            ("H", "Linked Researcher run not found"),
            ("developer_only", "not Hybrid"),
            ("researcher_only", "not Hybrid"),
        ]:
            res = request(name, success=False, error=error)
            if transport == "api":
                assert res["status"] == 409 and "developer" not in res["body"]
            else:
                assert "Developer run ID:" not in res["text"]
        data["not_found"] = dict(data["A"], project=identifier())
        res = request("not_found", success=False, error="not found")
        if transport == "api":
            assert res["status"] == 404
        for name in ("I", "J", "unbound", "D"):
            for action in ACTIONS:
                res = request(
                    name,
                    action,
                    success=False,
                    error="Completed project"
                    if name in ("I", "J")
                    else "not currently allowed",
                )
                if transport == "api":
                    assert res["status"] == 409
        # Wrong own-lane action while the OTHER lane still has pending work.
        for action in ACTIONS:
            wrong = "continue-developer" if action == "approve-developer-plan" else "A"
            if action == "select-research-direction":
                wrong = "approve-research-plan"
            request(wrong, action, success=False, error="not currently allowed")
        for raw, error in [
            ("{bad", None),
            ("{}", None),
            (
                json.dumps(
                    dict(
                        data["invalid_results"]["submission"], approved_plan_version=999
                    )
                ),
                "different approved plan",
            ),
            (
                json.dumps(
                    dict(
                        data["invalid_results"]["submission"],
                        implementation_plan_version=999,
                    )
                ),
                "different implementation plan",
            ),
        ]:
            res = request(
                "invalid_results",
                "provide-research-results",
                payload=raw,
                success=False,
                error=error,
            )
            if transport == "api":
                assert res["status"] == (409 if error else 422)
        print(f"{transport}: rejection matrix passed", flush=True)
        selected = (
            list(ACTIONS)
            if transport == "api"
            else [a for a in ACTIONS if not a.startswith("continue-")]
        )
        targets = {
            "approve-developer-plan": "ready",
            "select-research-direction": "direction_selected",
            "approve-research-plan": "research_plan_approved",
            "continue-developer": "awaiting_checkpoint",
            "continue-researcher": "awaiting_research_plan_approval",
            "provide-research-results": "research_results_submitted",
        }
        ps, ds, rs = stores(root)
        for action in selected:
            request(action)  # Developer remains first immediately before mutation.
            request(action, action, operation=ACTIONS[action])
            item = data[action]
            if "developer" in action:
                assert (
                    ds.get(item["developer"]).execution_state.status.value
                    == targets[action]
                )
            else:
                run_value = rs.get(item["researcher"])
                assert run_value.status.value == targets[action]
                if action == "provide-research-results":
                    assert (
                        run_value.result_submission.model_dump(mode="json")
                        == item["submission"]
                    )
                    assert (
                        run_value.result_analysis
                        is run_value.result_synthesis
                        is run_value.paper_materials
                        is None
                    )
            if not action.startswith("continue-"):
                request(action, action, success=False, error="not currently allowed")
        request("E", "select-research-direction", operation="select_research_direction")
        request("F", "approve-developer-plan", operation="approve_plan")
        assert ps.get(data["E"]["project"]).developer_run_id is None
        assert ps.get(data["F"]["project"]).research_run_id is None
        if transport == "api":
            request(
                "finish", "continue-researcher", operation="generate_paper_materials"
            )
            assert request("finish")["body"]["both_workflows_terminal"] is True
        assert ps.get(data["D"]["project"]).status.value == "active"
        assert ps.get(data["finish"]["project"]).status.value == "active"
        # Artifact catalog must be exact concatenation of each authoritative lane.
        sessions = ProjectSessionService(ps, NoProvider(), ds, rs)
        artifacts = ProjectArtifactService(sessions, ds, rs)
        before = snapshot(root)
        catalog = artifacts.list_artifacts(data["D"]["project"])
        domains = [a.source_domain.value for a in catalog.artifacts]
        assert "developer" in domains and "researcher" in domains
        assert domains == sorted(domains)
        for a in catalog.artifacts:
            assert a.source_run_id == data["D"][a.source_domain.value]
        separate = tuple(
            a
            for label in ("artifact_developer", "artifact_researcher")
            for a in artifacts.list_artifacts(data[label]["project"]).artifacts
        )
        assert catalog.artifacts == separate
        for label in ("artifact_developer", "artifact_researcher"):
            for descriptor in artifacts.list_artifacts(
                data[label]["project"]
            ).artifacts:
                assert (
                    artifacts.get_artifact(
                        data["D"]["project"], descriptor.artifact_id
                    ).content
                    == artifacts.get_artifact(
                        data[label]["project"], descriptor.artifact_id
                    ).content
                )
        assert snapshot(root) == before
        request("D", "artifacts")
        assert set(snapshot(root)) == expected_files
        assert {
            str(p.relative_to(root)) for p in root.rglob("*") if p.is_dir()
        } == initial_dirs
        assert all(
            snapshot(root)[p] == digest
            for p, digest in initial.items()
            if p.startswith(("projects/", "workspace/"))
        )
        request("D", "complete")
        assert ps.get(data["D"]["project"]).status.value == "completed"
        request("D")
    print(f"PHASE_4B3_{transport.upper()}_ACCEPTANCE=PASSED")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", choices=["cli", "api"])
    parser.add_argument("--cli", action="store_true")
    parser.add_argument("--root", type=Path)
    args = parser.parse_args()
    if args.worker:
        worker(args.root, args.worker, json.load(sys.stdin))
    elif args.root:
        run("cli" if args.cli else "api", args.root)
    else:
        with TemporaryDirectory(prefix="ai-agent-4b3-api-") as directory:
            run("cli" if args.cli else "api", Path(directory))


if __name__ == "__main__":
    main()
