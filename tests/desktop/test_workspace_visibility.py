"""Workspace reads must remain separate from execution and private artifacts."""

from unittest.mock import Mock

import pytest

from ai_agent_project.agent.plan_revision import PlanRevisionState
from ai_agent_project.agent.research import WorkMode
from ai_agent_project.desktop.errors import DesktopError
from ai_agent_project.desktop.workspace import MAX_CODE_BYTES, inventory, read_code
from ai_agent_project.desktop_app.application import build_desktop_application
from ai_agent_project.tools.file import FileTool


def planned_run(setup):
    pid = setup.ids[WorkMode.DEVELOPER]
    rid = setup.desktop.get_project_view(pid).developer.run_id
    run = setup.developers.get(rid)
    task = run.implementation_plan.tasks[0].model_copy(
        update={"files_to_modify": ["src/app.py"]}
    )
    plan = run.implementation_plan.model_copy(update={"tasks": [task]})
    project_plan = run.project_plan.model_copy(update={"implementation_plan": plan})
    run = run.model_copy(
        update={
            "implementation_plan": plan,
            "project_plan": project_plan,
            "plan_revision_state": PlanRevisionState.from_plan(project_plan),
        }
    )
    setup.developers.replace(rid, run)
    return pid, rid


def test_plan_disk_and_restart_are_distinct(setup):
    pid, rid = planned_run(setup)
    before = {p: p.read_bytes() for p in setup.root.rglob("*.json")}
    view = setup.desktop.get_developer_workspace(pid)
    assert view.absolute_path == str(setup.root.resolve())
    assert view.exists and view.run_id == rid
    assert [(f.path, f.exists, f.planned) for f in view.files] == [
        ("src/app.py", False, True)
    ]
    code = setup.desktop.get_developer_workspace_code(pid, "src/app.py")
    assert not code.exists and not code.content
    assert before == {p: p.read_bytes() for p in setup.root.rglob("*.json")}
    assert (
        FileTool(setup.root)
        .execute(
            {
                "operation": "write_file",
                "path": "src/app.py",
                "content": "print('saved')\n",
            }
        )
        .success
    )
    assert setup.desktop.get_developer_workspace(pid).files[0].exists
    fresh = build_desktop_application(setup.root, setup.root)
    assert fresh.get_developer_workspace(pid).absolute_path == view.absolute_path
    assert (
        fresh.get_developer_workspace_code(pid, "src/app.py").content
        == "print('saved')\n"
    )
    hybrid = fresh.get_developer_workspace(setup.ids[WorkMode.HYBRID])
    assert hybrid.absolute_path == view.absolute_path
    assert hybrid.files[0].exists and not hybrid.files[0].planned


@pytest.mark.parametrize(
    "path",
    [
        "../outside.py",
        "/tmp/outside.py",
        r"..\outside.py",
        "C:/outside.py",
        ".env",
        ".env.example",
        "settings/llm.json",
        "developers/run.json",
        ".aws/config.txt",
        "credentials.json",
        "id_rsa.txt",
        "private.pem",
    ],
)
def test_private_and_unsafe_paths_are_denied(setup, path):
    with pytest.raises(DesktopError):
        setup.desktop.get_developer_workspace_code(setup.ids[WorkMode.DEVELOPER], path)


def test_symlinks_and_directory_escape_are_denied(setup, tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}-outside.py"
    outside.write_text("outside content")
    (setup.root / "alias.py").symlink_to(outside)
    (setup.root / "linked").symlink_to(outside.parent, target_is_directory=True)
    pid = setup.ids[WorkMode.DEVELOPER]
    for value in ["alias.py", f"linked/{outside.name}"]:
        with pytest.raises(DesktopError):
            setup.desktop.get_developer_workspace_code(pid, value)
    assert not setup.desktop.get_developer_workspace(pid).files


def test_public_code_masks_sensitive_lines_and_does_not_expose_history(setup):
    pid = setup.ids[WorkMode.DEVELOPER]
    (setup.root / "app.py").write_text(
        'api_key = "synthetic-value"\nENV_VALUE = "synthetic-env"\nprint("public")\n# sk-syntheticKey123\nurl = "https://user:synthetic-pass@example.test"\n'
    )
    code = setup.desktop.get_developer_workspace_code(pid, "app.py")
    for secret in [
        "synthetic-value",
        "synthetic-env",
        "sk-syntheticKey123",
        "synthetic-pass",
    ]:
        assert secret not in code.content
    assert 'print("public")' in code.content
    assert [f.path for f in setup.desktop.get_developer_workspace(pid).files] == [
        "app.py"
    ]


def test_missing_workspace_researcher_and_unbound_project(setup, tmp_path, monkeypatch):
    pid = setup.ids[WorkMode.DEVELOPER]
    missing = tmp_path / "missing"
    monkeypatch.setattr(setup.developers, "workspace_root_for", lambda _: missing)
    view = setup.desktop.get_developer_workspace(pid)
    assert not view.exists and not view.files
    with pytest.raises(DesktopError):
        setup.desktop.get_developer_workspace_folder(pid)
    with pytest.raises(DesktopError):
        setup.desktop.get_developer_workspace(setup.ids[WorkMode.RESEARCHER])
    monkeypatch.setattr(setup.developers, "get", lambda _: None)
    with pytest.raises(DesktopError):
        setup.desktop.get_developer_workspace(pid)


def test_binary_large_files_and_bounds(tmp_path, monkeypatch):
    (tmp_path / "binary.py").write_bytes(b"\x00binary")
    (tmp_path / "large.py").write_text("x" * (MAX_CODE_BYTES + 1))
    for value in ("binary.py", "large.py"):
        with pytest.raises(DesktopError):
            read_code(tmp_path, value)
    monkeypatch.setattr("ai_agent_project.desktop.workspace.MAX_FILES", 1)
    files, truncated = inventory(tmp_path)
    assert len(files) == 1 and truncated


def test_symlink_root_is_not_followed(setup, tmp_path, monkeypatch):
    alias = tmp_path / "root-alias"
    alias.symlink_to(setup.root, target_is_directory=True)
    monkeypatch.setattr(setup.developers, "workspace_root_for", lambda _: alias)
    with pytest.raises(DesktopError):
        setup.desktop.get_developer_workspace(setup.ids[WorkMode.DEVELOPER])


def test_reads_and_folder_resolution_do_not_execute_or_approve(setup, monkeypatch):
    pid = setup.ids[WorkMode.DEVELOPER]
    forbidden = Mock(side_effect=AssertionError("Read attempted workflow execution"))
    monkeypatch.setattr(setup.desktop._actions, "continue_developer", forbidden)
    monkeypatch.setattr(setup.desktop._actions, "approve_developer_plan", forbidden)
    before = setup.desktop.get_project_view(pid)
    setup.desktop.get_developer_workspace(pid)
    setup.desktop.get_developer_workspace_code(pid, "missing.py")
    assert setup.desktop.get_developer_workspace_folder(pid) == setup.root.resolve()
    assert setup.desktop.get_project_view(pid) == before
    forbidden.assert_not_called()


def test_approved_developer_workflow_writes_real_file(setup, monkeypatch):
    from ai_agent_project.agent.acceptance import (
        AcceptanceReport,
        RequirementValidationResult,
    )
    from ai_agent_project.agent.checkpoint import (
        PhaseCheckpointService,
        ProgressReporter,
    )
    from ai_agent_project.agent.phase_execution import PhaseExecutionService
    from ai_agent_project.agent.project_execution import ProjectExecutionService
    from ai_agent_project.agent.service import AgentService
    from ai_agent_project.agent.state import ToolCall
    from ai_agent_project.llm.base import LLMResponse
    from ai_agent_project.tools.registry import ToolRegistry

    pid, _ = planned_run(setup)
    registry = ToolRegistry()
    registry.register(FileTool(setup.root))
    client = Mock()
    client.complete.side_effect = [
        LLMResponse(
            tool_call=ToolCall(
                name="file",
                arguments={
                    "operation": "write_file",
                    "path": "src/app.py",
                    "content": "print('executed')\n",
                },
            )
        ),
        LLMResponse(final_answer="Also created imaginary.py"),
    ]
    validator = Mock()
    validator.validate.return_value = AcceptanceReport(
        requirements=[
            RequirementValidationResult(requirement_id="REQ-1", status="passed")
        ]
    )
    phase = PhaseExecutionService(
        AgentService(client, registry), validator, max_repair_attempts=0
    )
    application = setup.desktop._actions._developer_plans
    monkeypatch.setattr(
        application,
        "_project_execution_service",
        ProjectExecutionService(phase, ProgressReporter(), PhaseCheckpointService()),
    )
    with pytest.raises(DesktopError):
        setup.desktop.continue_developer(pid)
    assert not (setup.root / "src" / "app.py").exists()
    setup.desktop.approve_developer_plan(pid)
    setup.desktop.continue_developer(pid)
    assert (setup.root / "src" / "app.py").read_text() == "print('executed')\n"
    assert setup.desktop.get_project_view(pid).developer.status == "awaiting_checkpoint"
    view = setup.desktop.get_developer_workspace(pid)
    assert [(f.path, f.exists) for f in view.files] == [("src/app.py", True)]
    assert not setup.desktop.get_developer_workspace_code(pid, "imaginary.py").exists
    restarted = build_desktop_application(setup.root, setup.root)
    assert (
        restarted.get_developer_workspace_code(pid, "src/app.py").content
        == "print('executed')\n"
    )
    assert restarted.get_project_view(pid).developer.status == "awaiting_checkpoint"


def test_runtime_credential_is_masked_even_without_key_label(setup, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-runtime-value")
    (setup.root / "app.py").write_text('print("synthetic-runtime-value")\n')
    code = setup.desktop.get_developer_workspace_code(
        setup.ids[WorkMode.DEVELOPER], "app.py"
    )
    assert "synthetic-runtime-value" not in code.content
    assert "[REDACTED]" in code.content


def test_parent_swap_before_open_is_rejected(tmp_path, monkeypatch):
    import os

    if os.name != "posix":
        pytest.skip("POSIX no-follow directory descriptors")
    root = tmp_path / "workspace"
    nested = root / "src"
    nested.mkdir(parents=True)
    (nested / "app.py").write_text("inside")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "app.py").write_text("outside")
    original_open = os.open
    swapped = False

    def swap_on_open(path, flags, *args, **kwargs):
        nonlocal swapped
        if not swapped and path == "src":
            nested.rename(root / "original")
            nested.symlink_to(outside, target_is_directory=True)
            swapped = True
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr("ai_agent_project.desktop.workspace.os.open", swap_on_open)
    with pytest.raises(OSError):
        read_code(root, "src/app.py")
    assert swapped


def test_windows_reparse_attribute_is_rejected(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from ai_agent_project.desktop.workspace import checked_root

    monkeypatch.setattr(
        type(tmp_path),
        "lstat",
        lambda _: SimpleNamespace(st_mode=0, st_file_attributes=0x400),
    )
    with pytest.raises(DesktopError):
        checked_root(tmp_path)


def test_non_code_file_presence_is_visible_without_reading_content(setup):
    (setup.root / "image.png").write_bytes(b"synthetic binary")
    pid = setup.ids[WorkMode.DEVELOPER]
    view = setup.desktop.get_developer_workspace(pid)
    assert [(f.path, f.exists) for f in view.files] == [("image.png", True)]
    with pytest.raises(DesktopError, match="cannot be displayed as code"):
        setup.desktop.get_developer_workspace_code(pid, "image.png")
