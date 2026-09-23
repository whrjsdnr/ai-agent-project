"""Build-time bundle/PE audit and isolated frozen GUI acceptance."""

import argparse
import json
import os
import struct
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import CodeType


def verify_bundle(bundle: Path, *, smoke: bool = False) -> None:
    windows = sys.platform == "win32"
    executable = bundle / ("AI-Agent.exe" if windows else "AI-Agent")
    header = executable.read_bytes()
    if windows:
        assert header[:2] == b"MZ", "Not a Windows PE executable"
        offset = struct.unpack_from("<I", header, 0x3C)[0]
        assert header[offset : offset + 4] == b"PE\0\0"
        assert struct.unpack_from("<H", header, offset + 4)[0] == 0x8664, "Expected x64"
        assert struct.unpack_from("<H", header, offset + 24 + 68)[0] == 2, (
            "Expected Windows GUI subsystem"
        )
        assert list(bundle.rglob("qwindows.dll")), "Windows Qt platform plugin missing"
    else:
        assert header[:4] == b"\x7fELF", "Linux smoke requires ELF"
    forbidden = {
        ".env",
        ".git",
        "tests",
        "pytest",
        ".pytest_cache",
        "project-runs",
        "research-runs",
        "handoffs",
        "projects",
        "llm.json",
        "direct_url.json",
    }
    for path in bundle.rglob("*"):
        assert not forbidden.intersection(path.relative_to(bundle).parts), (
            "Unexpected private/development data in bundle"
        )
    assert list(bundle.rglob("ai-agent.svg"))
    assert list(bundle.rglob("ai-agent.ico"))
    # Inspect the embedded Python archive, not just loose bundle files.
    from PyInstaller.archive.readers import CArchiveReader

    archive = CArchiveReader(str(executable))
    modules = archive.open_embedded_archive("PYZ.pyz")
    denied = {"tests", "pytest", "fastapi", "starlette", "uv", "PyInstaller"}
    assert not any(name.split(".")[0] in denied for name in modules.toc)

    def audit_code(code: CodeType) -> None:
        assert not Path(code.co_filename).is_absolute(), (
            "Absolute build path in Python code"
        )
        for constant in code.co_consts:
            if isinstance(constant, CodeType):
                audit_code(constant)
            elif isinstance(constant, str):
                assert "packaging-test-only-secret" not in constant
                assert "synthetic-desktop-credential" not in constant

    for name in modules.toc:
        if name.startswith("ai_agent_project"):
            code = modules.extract(name)
            if code is not None:
                audit_code(code)
    if smoke:
        with TemporaryDirectory(prefix="ai-agent-acceptance-") as temporary:
            root = Path(temporary)
            env = os.environ.copy()
            for key in (
                "OPENAI_API_KEY",
                "OPENAI_BASE_URL",
                "OPENAI_MODEL",
                "OPENAI_TIMEOUT_SECONDS",
            ):
                env.pop(key, None)
            for key in (
                "APPDATA",
                "LOCALAPPDATA",
                "XDG_CONFIG_HOME",
                "XDG_DATA_HOME",
                "XDG_CACHE_HOME",
            ):
                env[key] = str(root)
            env["QT_QPA_PLATFORM"] = (
                "offscreen"  # Acceptance only; never normal launch.
            )
            completed = subprocess.run(
                [str(executable.resolve()), "--packaging-smoke"],
                cwd=root,
                env=env,
                timeout=60,
                capture_output=True,
                check=False,
            )
            assert completed.returncode == 0, (
                "Frozen GUI smoke failed (raw output withheld)"
            )
            marker = (
                root
                / "ai-agent"
                / ("cache/packaging-smoke.json" if windows else "packaging-smoke.json")
            )
            result = json.loads(marker.read_text(encoding="utf-8"))
            assert result["success"] and result["frozen"]
            assert result["pages"] == ["Dashboard", "Projects", "Settings"]
    print(
        (
            "WINDOWS_FROZEN_ACCEPTANCE=PASSED"
            if windows
            else "LINUX_PACKAGING_SMOKE=PASSED"
        )
        if smoke
        else "BUNDLE_STRUCTURE_VERIFIED"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    verify_bundle(args.bundle, smoke=args.smoke)
