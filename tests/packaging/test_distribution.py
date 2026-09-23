"""Provider-free distribution configuration and runtime boundary checks."""

import ast
import json
import os
import runpy
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from ai_agent_project.desktop_app.resources import application_version, resource_path
from ai_agent_project.paths import desktop_workspace, runtime_paths

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "packaging/pyinstaller/ai-agent.spec"


def test_spec_and_product_entrypoint():
    source = SPEC.read_text()
    ast.parse(source)
    assert 'name="AI-Agent"' in source
    assert "console=False" in source
    assert "COLLECT(" in source and "exclude_binaries=True" in source
    entry = (ROOT / "packaging/pyinstaller/entrypoint.py").read_text()
    assert "from ai_agent_project.desktop_app.main import main" in entry
    assert "cli" not in entry and "api.app" not in entry


def test_version_single_source():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert application_version() == config["project"]["version"]
    assert (
        config["project"]["scripts"]["ai-agent-desktop"]
        == "ai_agent_project.desktop_app.main:main"
    )
    assert "pyinstaller" not in str(config["project"]["dependencies"]).lower()
    assert "pyinstaller" in str(config["dependency-groups"]["build"]).lower()


def test_source_resource():
    assert resource_path("ai-agent.svg").is_file()
    with pytest.raises(ValueError):
        resource_path("../../.env")


def test_frozen_resource(monkeypatch, tmp_path):
    from ai_agent_project.desktop_app import resources

    fake = tmp_path / "bundle" / "ai_agent_project" / "desktop_app"
    monkeypatch.setattr(resources, "__file__", str(fake / "resources.py"))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert resource_path("ai-agent.svg") == fake / "assets" / "ai-agent.svg"


def test_windows_paths(tmp_path):
    env = {
        "APPDATA": str(tmp_path / "roaming"),
        "LOCALAPPDATA": str(tmp_path / "local"),
    }
    paths = runtime_paths(platform="win32", environ=env, home=tmp_path)
    assert paths.config == tmp_path / "roaming" / "ai-agent"
    assert paths.data == tmp_path / "local" / "ai-agent" / "data"
    assert paths.cache == tmp_path / "local" / "ai-agent" / "cache"
    assert paths.workspace == paths.data / "workspaces" / "default"


def test_windows_fallback(tmp_path):
    paths = runtime_paths(platform="win32", environ={}, home=tmp_path)
    assert paths.config == tmp_path / "AppData" / "Roaming" / "ai-agent"
    assert paths.data == tmp_path / "AppData" / "Local" / "ai-agent" / "data"


def test_linux_xdg(tmp_path):
    env = {
        key: str(tmp_path / key)
        for key in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME")
    }
    paths = runtime_paths(platform="linux", environ=env, home=tmp_path)
    assert paths.config == Path(env["XDG_CONFIG_HOME"]) / "ai-agent"
    assert paths.data == Path(env["XDG_DATA_HOME"]) / "ai-agent"
    assert paths.cache == Path(env["XDG_CACHE_HOME"]) / "ai-agent"


def test_linux_fallback_and_relative_env(tmp_path):
    paths = runtime_paths(
        platform="linux", environ={"XDG_DATA_HOME": "relative"}, home=tmp_path
    )
    assert paths.data == tmp_path / ".local" / "share" / "ai-agent"
    assert paths.config == tmp_path / ".config" / "ai-agent"


def test_frozen_workspace_outside_installation(monkeypatch, tmp_path):
    import ai_agent_project.paths as paths_module

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    expected = runtime_paths(platform="linux", environ={}, home=tmp_path / "user")
    monkeypatch.setattr(paths_module, "runtime_paths", lambda: expected)
    install = tmp_path / "install"
    install.mkdir()
    monkeypatch.chdir(install)
    workspace = desktop_workspace()
    assert workspace.is_dir() and not workspace.is_relative_to(install)
    assert list(install.iterdir()) == []


def test_source_workspace_preserved(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.chdir(tmp_path)
    assert desktop_workspace() == tmp_path


def test_first_run_and_credential_safety(tmp_path, monkeypatch):
    from ai_agent_project.desktop_app.application import build_desktop_application
    from ai_agent_project.llm.config import ProviderConfig

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    service = build_desktop_application(tmp_path / "fresh")
    assert service.get_dashboard().total_projects == 0
    secret = "packaging-test-only-secret"
    service.save_provider_config(
        ProviderConfig(
            base_url="https://example.test/v1", model="custom-model", api_key=secret
        )
    )
    saved = (tmp_path / "fresh/settings/llm.json").read_text()
    assert secret not in saved and "api_key" not in saved
    assert service.get_provider_config().base_url == "https://example.test/v1"
    assert secret not in repr(service.get_provider_config())


@pytest.mark.parametrize(
    "name",
    [
        "tests",
        "pytest",
        "fastapi",
        "starlette",
        "uv",
        "PyInstaller",
        "ai_agent_project.api",
    ],
)
def test_build_runtime_exclusions(name):
    tree = ast.parse(SPEC.read_text())
    analysis = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Analysis"
    )
    exclusions = ast.literal_eval(
        next(k.value for k in analysis.keywords if k.arg == "excludes")
    )
    assert name in exclusions


def test_data_allowlist():
    source = SPEC.read_text()
    tree = ast.parse(source)
    analysis = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Analysis"
    )
    datas = next(k.value for k in analysis.keywords if k.arg == "datas")
    assert len(datas.elts) == 3
    assert any(
        isinstance(node, ast.Constant) and node.value == "METADATA"
        for node in ast.walk(datas)
    )
    assert "ai-agent.svg" in source
    assert "collect_all" not in source
    assert (
        "direct_url.json" in source
    )  # Documented exclusion, not a bundled data entry.


def test_installer_shortcuts_and_preservation():
    source = (ROOT / "packaging/windows/installer/AI-Agent.iss").read_text()
    active = "\n".join(line for line in source.splitlines() if not line.startswith(";"))
    assert "PrivilegesRequired=lowest" in active
    assert "OutputBaseFilename=AI-Agent-Setup" in active
    assert "[UninstallDelete]" not in active
    assert "[Icons]" in active and 'Filename: "{app}\\AI-Agent.exe"' in active
    assert "Flags: unchecked" in active
    assert "DefaultDirName={localappdata}\\Programs\\AI Agent" in active
    assert "AppVersion={#AppVersion}" in active
    assert 'Source: "{#RepoRoot}\\dist\\AI-Agent\\*"' in active


def test_windows_script_and_ci():
    script = (ROOT / "packaging/windows/build.ps1").read_text()
    assert "uv sync --locked --group build --python 3.12" in script
    assert "packaging/pyinstaller/ai-agent.spec" in script
    assert "build\\windows-venv" in script
    assert "Remove-Item" not in script
    workflow = (ROOT / ".github/workflows/windows-package.yml").read_text()
    assert "workflow_dispatch:" in workflow
    assert "push:" not in workflow
    assert "windows-2022" in workflow
    assert "build.ps1 -Installer" in workflow
    assert "upload-artifact" in workflow
    assert "secrets." not in workflow


def test_original_icon_generation():
    make = runpy.run_path(str(ROOT / "packaging/assets/generate_icon.py"))["icon_bytes"]
    assert make() == make()
    assert make()[:6] == b"\x00\x00\x01\x00\x06\x00"


def test_source_gui_smoke(tmp_path):
    env = os.environ.copy()
    for name in (
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_MODEL",
        "OPENAI_TIMEOUT_SECONDS",
    ):
        env.pop(name, None)
    for name in (
        "APPDATA",
        "LOCALAPPDATA",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_CACHE_HOME",
    ):
        env[name] = str(tmp_path)
    env["QT_QPA_PLATFORM"] = "offscreen"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ai_agent_project.desktop_app.main",
            "--packaging-smoke",
        ],
        env=env,
        timeout=30,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    marker = (
        tmp_path
        / "ai-agent"
        / (
            "cache/packaging-smoke.json"
            if sys.platform == "win32"
            else "packaging-smoke.json"
        )
    )
    data = json.loads(marker.read_text())
    assert data["success"] and not data["frozen"]


def test_snapshot_lock_preserves_bootstrap_exclusivity(tmp_path):
    from uuid import uuid4

    from ai_agent_project.agent.project_session import (
        ProjectModeProposal,
        ProjectSession,
    )
    from ai_agent_project.agent.project_session_application import (
        ProjectSessionService,
        ProjectSessionStateError,
    )
    from ai_agent_project.agent.project_session_file_store import FileProjectStore
    from ai_agent_project.agent.research import WorkMode
    from ai_agent_project.agent.upgrade import ProjectMode

    store = FileProjectStore(tmp_path / "projects")
    pid = str(uuid4())
    store.create(
        pid,
        ProjectSession.awaiting_confirmation(
            project_id=pid,
            title="Packaging",
            original_request="Request",
            mode_proposal=ProjectModeProposal(
                proposed_work_mode=WorkMode.HYBRID,
                proposed_project_mode=ProjectMode.NEW,
                rationale="Test",
            ),
        ),
    )
    sessions = ProjectSessionService(store)
    sessions.confirm_project_mode(pid, WorkMode.HYBRID, ProjectMode.NEW)
    store.bind_developer_run_if_unbound(pid, "first")
    with pytest.raises(ProjectSessionStateError):
        store.bind_developer_run_if_unbound(pid, "second")
    assert store.get(pid).developer_run_id == "first"


def test_platform_export_no_overwrite(tmp_path):
    from ai_agent_project.agent.project_artifact_export import (
        ProjectArtifactExportError,
        _write_new_file_atomically,
    )

    target = tmp_path / "artifact.txt"
    _write_new_file_atomically(target, b"review only")
    with pytest.raises(ProjectArtifactExportError):
        _write_new_file_atomically(target, b"overwrite")
    assert target.read_bytes() == b"review only"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["artifact.txt"]
