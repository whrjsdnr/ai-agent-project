"""Explicit user folder selection; never resolve aliases into a different workspace."""

import os
import re
from pathlib import Path

from ai_agent_project.desktop.errors import DesktopError, DesktopErrorCode
from ai_agent_project.workspace_io import open_directory_nofollow


def checked_directory(directory: Path) -> Path:
    if (
        not directory.is_absolute()
        or ".." in directory.parts
        or any(
            part.casefold() in {".git", ".ssh", ".aws", ".codex", ".agents"}
            or part.casefold() == ".env"
            or part.casefold().startswith(".env.")
            for part in directory.parts
        )
    ):
        raise DesktopError(
            DesktopErrorCode.VALIDATION_ERROR,
            "절대경로의 폴더를 선택하세요. 상위 경로 이동은 허용되지 않습니다.",
        )
    try:
        for path in (directory, *directory.parents):
            if path.is_symlink() or path.is_junction():
                raise OSError
        if not directory.is_dir() or not os.access(
            directory, os.R_OK | os.W_OK | os.X_OK
        ):
            raise OSError
        if os.name == "posix":
            descriptor = open_directory_nofollow(directory)
            os.close(descriptor)
        else:
            from ai_agent_project.windows_files import protected_directory_chain

            with protected_directory_chain(directory):
                pass
    except OSError:
        raise DesktopError(
            DesktopErrorCode.VALIDATION_ERROR,
            "작업 폴더가 없거나 접근할 수 없습니다. 링크가 아닌 읽기·쓰기 가능한 폴더를 선택하세요.",
        ) from None
    return directory


def create_directory(parent: Path, name: str) -> Path:
    if (
        not name
        or name != name.strip()
        or name.casefold()
        in {".", "..", ".git", ".ssh", ".aws", ".codex", ".agents", ".env"}
        or name.casefold().startswith(".env.")
        or re.search(r'[\\/:<>"|?*\x00-\x1f]', name)
        or name.endswith(".")
        or name.split(".")[0].upper()
        in {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            *(f"COM{i}" for i in range(1, 10)),
            *(f"LPT{i}" for i in range(1, 10)),
        }
    ):
        raise DesktopError(
            DesktopErrorCode.VALIDATION_ERROR,
            "프로젝트 폴더명에는 경로 구분자나 예약 문자를 사용할 수 없습니다.",
        )
    parent = checked_directory(parent)
    try:
        if os.name == "posix":
            descriptor = open_directory_nofollow(parent)
            try:
                os.mkdir(name, mode=0o700, dir_fd=descriptor)
            finally:
                os.close(descriptor)
        else:
            from ai_agent_project.windows_files import protected_directory_chain

            with protected_directory_chain(parent):
                (parent / name).mkdir()
    except FileExistsError:
        raise DesktopError(
            DesktopErrorCode.VALIDATION_ERROR,
            "같은 이름의 폴더가 이미 있습니다. 다른 이름을 입력하거나 기존 프로젝트 열기를 사용하세요.",
        ) from None
    except OSError:
        raise DesktopError(
            DesktopErrorCode.VALIDATION_ERROR,
            "프로젝트 폴더를 만들 수 없습니다. 경로와 접근 권한을 확인하세요.",
        ) from None
    return checked_directory(parent / name)
