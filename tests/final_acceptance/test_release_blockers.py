import pytest

from ai_agent_project.agent.checkpoint import CheckpointDecision
from ai_agent_project.agent.project_execution import ProjectExecutionStatus
from ai_agent_project.agent.research import WorkMode
from ai_agent_project.desktop import DesktopError
from ai_agent_project.tools.file import FileTool


@pytest.mark.parametrize("path", [".env.local", "alias"])
def test_secret_file_aliases_are_inaccessible(tmp_path, path):
    secret = tmp_path / ".env.local"
    secret.write_text("synthetic-audit-only", encoding="utf-8")
    (tmp_path / "alias").symlink_to(secret)
    tool = FileTool(tmp_path)
    result = tool.execute({"operation": "read_file", "path": path})
    assert not result.success
    assert "synthetic-audit-only" not in str(result)
    assert not tool.execute(
        {"operation": "write_file", "path": path, "content": "changed"}
    ).success


def test_desktop_has_explicit_checkpoint_decision_boundary(setup):
    # No decision is valid before execution; this boundary must exist in the GUI facade.
    pid = setup.ids[WorkMode.DEVELOPER]
    with pytest.raises(DesktopError):
        setup.desktop.decide_developer_checkpoint(pid, CheckpointDecision.APPROVE)
    assert (
        setup.developers.get(
            setup.desktop.get_project_view(pid).developer.run_id
        ).execution_state.status
        is ProjectExecutionStatus.AWAITING_PLAN_APPROVAL
    )


def test_shell_path_cannot_escape_through_symlink(tmp_path, monkeypatch):
    from unittest.mock import Mock

    from ai_agent_project.tools.shell import ShellTool

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (workspace / "alias").symlink_to(outside, target_is_directory=True)
    launch = Mock()
    monkeypatch.setattr("ai_agent_project.tools.shell.subprocess.run", launch)
    assert not ShellTool(workspace).execute({"command": "uv run pytest alias"}).success
    launch.assert_not_called()


def test_shell_path_cannot_be_an_option():
    from ai_agent_project.command_policy import CommandPolicyError, parse_safe_command

    with pytest.raises(CommandPolicyError):
        parse_safe_command("uv run pytest --override-ini=testpaths=outside")


@pytest.mark.parametrize("target", [".env", "alias"])
def test_validation_tool_cannot_target_credentials(tmp_path, monkeypatch, target):
    from unittest.mock import Mock

    from ai_agent_project.tools.shell import ShellTool

    (tmp_path / ".env").write_text("synthetic-audit-only")
    (tmp_path / "alias").symlink_to(tmp_path / ".env")
    launch = Mock()
    monkeypatch.setattr("ai_agent_project.tools.shell.subprocess.run", launch)
    assert (
        not ShellTool(tmp_path)
        .execute({"command": f"uv run ruff check {target}"})
        .success
    )
    launch.assert_not_called()


@pytest.mark.parametrize("name", [".ENV", ".ENV.local", ".env::$DATA"])
def test_secret_path_guard_covers_windows_spelling(name, tmp_path):
    (tmp_path / name).write_text("synthetic-audit-only")
    result = FileTool(tmp_path).execute({"operation": "read_file", "path": name})
    assert not result.success
