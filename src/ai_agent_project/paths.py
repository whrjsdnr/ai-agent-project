"""User-owned runtime locations; no installation-directory writes."""

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimePaths:
    config: Path
    data: Path
    cache: Path

    @property
    def workspace(self) -> Path:
        return self.data / "workspaces" / "default"


def runtime_paths(
    *,
    platform: str | None = None,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> RuntimePaths:
    platform = platform or sys.platform
    env = os.environ if environ is None else environ
    home = home or Path.home()

    def root(variable: str, fallback: Path) -> Path:
        value = env.get(variable)
        return Path(value) if value and Path(value).is_absolute() else fallback

    if platform == "win32":
        local = root("LOCALAPPDATA", home / "AppData" / "Local") / "ai-agent"
        return RuntimePaths(
            root("APPDATA", home / "AppData" / "Roaming") / "ai-agent",
            local / "data",
            local / "cache",
        )
    return RuntimePaths(
        root("XDG_CONFIG_HOME", home / ".config") / "ai-agent",
        root("XDG_DATA_HOME", home / ".local" / "share") / "ai-agent",
        root("XDG_CACHE_HOME", home / ".cache") / "ai-agent",
    )


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def desktop_workspace() -> Path:
    if not is_frozen():
        return Path.cwd()
    workspace = runtime_paths().workspace
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace
