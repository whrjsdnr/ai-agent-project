"""Directory-descriptor operations that never follow pathname aliases."""

import os
from pathlib import Path


def open_directory_nofollow(path: Path) -> int:
    if os.name != "posix" or not path.is_absolute():
        raise OSError("Verified directory-descriptor access is unavailable")
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:]:
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
            )
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def open_parent_nofollow(root: Path, relative: Path, *, create: bool = False) -> int:
    descriptor = open_directory_nofollow(root)
    try:
        for part in relative.parent.parts:
            if part == "..":
                raise OSError("Workspace traversal is forbidden")
            if create:
                try:
                    os.mkdir(part, dir_fd=descriptor)
                except FileExistsError:
                    pass
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
            )
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _verify_file(root: Path, relative: Path, parent_fd: int, file_fd: int) -> None:
    import stat

    parent = open_directory_nofollow(root / relative.parent)
    try:
        metadata = os.fstat(file_fd)
        named = os.stat(relative.name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            not os.path.samestat(os.fstat(parent), os.fstat(parent_fd))
            or not os.path.samestat(metadata, named)
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
        ):
            raise OSError("Unsafe or replaced workspace file")
    finally:
        os.close(parent)


def read_text_nofollow(root: Path, relative: Path) -> str:
    parent = open_parent_nofollow(root, relative)
    try:
        descriptor = os.open(
            relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent
        )
        try:
            _verify_file(root, relative, parent, descriptor)
            metadata = os.fstat(descriptor)
            with os.fdopen(os.dup(descriptor), "r", encoding="utf-8") as stream:
                content = stream.read()
            _verify_file(root, relative, parent, descriptor)
            after = os.fstat(descriptor)
            if (metadata.st_size, metadata.st_mtime_ns, metadata.st_ctime_ns) != (
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ):
                raise OSError("Workspace file changed during read")
            return content
        finally:
            os.close(descriptor)
    finally:
        os.close(parent)


def write_text_nofollow(root: Path, relative: Path, content: str) -> None:
    parent = open_parent_nofollow(root, relative, create=True)
    try:
        descriptor = os.open(
            relative.name,
            os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
            0o600,
            dir_fd=parent,
        )
        try:
            _verify_file(root, relative, parent, descriptor)
            os.ftruncate(descriptor, 0)
            with os.fdopen(os.dup(descriptor), "w", encoding="utf-8") as stream:
                stream.write(content)
        finally:
            os.close(descriptor)
    finally:
        os.close(parent)
