"""Read-only, bounded public workspace inspection, independent of agent tools."""

import os
import stat
from pathlib import Path

from ai_agent_project.agent.workspace import is_workspace_ignored_path
from ai_agent_project.desktop.errors import DesktopError, DesktopErrorCode
from ai_agent_project.execution_privacy import public_relative_path, sanitize_text

MAX_FILES = 500
MAX_ENTRIES = 5_000
MAX_CODE_BYTES = 200_000
_TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".txt",
    ".toml",
    ".json",
    ".yaml",
    ".yml",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".html",
    ".css",
    ".sql",
    ".rst",
    ".ini",
    ".cfg",
}


def denied() -> DesktopError:
    return DesktopError(
        DesktopErrorCode.ACTION_NOT_ALLOWED,
        "This workspace path is unavailable for public inspection.",
    )


def _is_link(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0) & 0x400
    )


def _open_directory(path: Path) -> int:
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            child = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def public_path(value: str) -> Path:
    try:
        return public_relative_path(value)
    except ValueError:
        raise denied() from None


def checked_root(root: Path) -> bool:
    # A stored root must not silently change into a symlink to another workspace.
    if not root.is_absolute() or any(_is_link(p) for p in (root, *root.parents)):
        raise denied()
    return root.is_dir()


def checked_file(root: Path, value: str) -> Path:
    relative = public_path(value)
    candidate = root
    for part in relative.parts:
        candidate /= part
        if _is_link(candidate):
            raise denied()
    if not candidate.resolve().is_relative_to(root):
        raise denied()
    return candidate


def inventory(root: Path) -> tuple[list[str], bool]:
    files: list[str] = []
    visited = 0
    pending = [root]
    while pending:
        directory = pending.pop()
        descriptor = _open_directory(directory) if os.name == "posix" else None
        try:
            entries = os.scandir(descriptor if descriptor is not None else directory)
        except BaseException:
            if descriptor is not None:
                os.close(descriptor)
            raise
        try:
            with entries:
                for entry in entries:
                    visited += 1
                    if visited > MAX_ENTRIES or len(files) >= MAX_FILES:
                        return sorted(files), True
                    path = directory / entry.name
                    relative = path.relative_to(root)
                    if _is_link(path) or is_workspace_ignored_path(relative):
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        # Validate directory names using a synthetic public filename.
                        try:
                            public_path((relative / "inspection.py").as_posix())
                        except DesktopError:
                            continue
                        pending.append(path)
                    elif entry.is_file(follow_symlinks=False):
                        try:
                            checked_file(root, relative.as_posix())
                        except DesktopError:
                            continue
                        files.append(relative.as_posix())
        finally:
            if descriptor is not None:
                os.close(descriptor)
    return sorted(files), False


def mask_content(content: str, *, secrets: tuple[str, ...] = ()) -> str:
    return sanitize_text(content, secrets=secrets)


def read_code(root: Path, value: str, *, secrets: tuple[str, ...] = ()) -> str:
    """Open without following links; on POSIX protect every path component."""
    if public_path(value).suffix.casefold() not in _TEXT_SUFFIXES:
        raise DesktopError(
            DesktopErrorCode.ACTION_NOT_ALLOWED,
            "This file type cannot be displayed as code.",
        )
    path = checked_file(root, value)
    descriptors: list[int] = []
    try:
        if os.name == "posix":
            descriptor = _open_directory(root)
            descriptors.append(descriptor)
            parts = public_path(value).parts
            for part in parts[:-1]:
                descriptor = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=descriptor,
                )
                descriptors.append(descriptor)
            descriptor = os.open(
                parts[-1],
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=descriptor,
            )
        else:
            descriptor = os.open(path, os.O_RDONLY | os.O_BINARY)
        descriptors.append(descriptor)
        if os.name == "nt":
            _check_windows_handle(descriptor, path)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_CODE_BYTES:
            raise denied()
        # Recheck after opening as well (including Windows reparse-point aliases).
        checked_file(root, value)
        if not os.path.samestat(metadata, path.stat()):
            raise denied()
        with os.fdopen(os.dup(descriptor), "rb") as stream:
            data = stream.read(MAX_CODE_BYTES + 1)
        if len(data) > MAX_CODE_BYTES or b"\x00" in data:
            raise denied()
        return mask_content(data.decode("utf-8"), secrets=secrets)
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _check_windows_handle(descriptor: int, expected: Path) -> None:
    """Verify the actual opened target, including ancestor reparse-point races."""
    import ctypes
    import msvcrt
    from ctypes import wintypes

    get_path = ctypes.WinDLL("kernel32", use_last_error=True).GetFinalPathNameByHandleW
    get_path.argtypes = [
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    get_path.restype = wintypes.DWORD
    buffer = ctypes.create_unicode_buffer(32_768)
    length = get_path(msvcrt.get_osfhandle(descriptor), buffer, len(buffer), 0)
    if not length or length >= len(buffer):
        raise denied()
    target = buffer.value
    if target.startswith("\\\\?\\UNC\\"):
        target = "\\\\" + target[8:]
    elif target.startswith("\\\\?\\"):
        target = target[4:]
    if Path(target) != expected:
        raise denied()
