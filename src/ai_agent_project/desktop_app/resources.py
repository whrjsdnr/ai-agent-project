"""Read-only packaged resources and installed package version."""

from importlib.metadata import version
from pathlib import Path


def resource_path(name: str) -> Path:
    if name not in {"ai-agent.svg", "ai-agent.ico"}:
        raise ValueError("Unknown application resource")
    # PyInstaller preserves __file__ relative to its bundle root.
    return Path(__file__).resolve().parent / "assets" / name


def application_version() -> str:
    return version("ai-agent-project")
