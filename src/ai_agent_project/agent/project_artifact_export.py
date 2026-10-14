"""Safe atomic single-file export for ownership-checked project artifacts."""

import hashlib
import os
import stat
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from ai_agent_project.agent.project_artifact import ProjectArtifactType
from ai_agent_project.agent.project_artifact_application import ProjectArtifactService
from ai_agent_project.agent.project_artifact_rendering import (
    JSON_MEDIA_TYPE,
    MARKDOWN_MEDIA_TYPE,
    TEXT_MEDIA_TYPE,
    ProjectArtifactFormat,
    render_project_artifact,
)


class ProjectArtifactExportError(Exception):
    """Raised when a local single-file export cannot be completed safely."""


class ProjectArtifactExportResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_id: str = Field(min_length=1)
    artifact_id: str = Field(min_length=1)
    artifact_type: ProjectArtifactType
    format: ProjectArtifactFormat
    media_type: str = Field(min_length=1)
    output_path: str = Field(min_length=1)
    bytes_written: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ProjectArtifactExportService:
    """Render and atomically create one explicit local file without overwrite."""

    def __init__(self, artifact_service: ProjectArtifactService) -> None:
        self._artifact_service = artifact_service

    def export_artifact(
        self,
        project_id: str,
        artifact_id: str,
        artifact_format: ProjectArtifactFormat,
        output_path: Path,
    ) -> ProjectArtifactExportResult:
        view = self._artifact_service.get_artifact(project_id, artifact_id)
        rendered = render_project_artifact(view, artifact_format)
        content = rendered.encode("utf-8")
        destination = _absolute_without_symlink_resolution(output_path)
        _write_new_file_atomically(destination, content)
        return ProjectArtifactExportResult(
            project_id=project_id,
            artifact_id=artifact_id,
            artifact_type=view.descriptor.artifact_type,
            format=artifact_format,
            media_type=_media_type(artifact_format),
            output_path=str(destination),
            bytes_written=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
        )


def _absolute_without_symlink_resolution(path: Path) -> Path:
    if not str(path):
        raise ProjectArtifactExportError("Artifact output path must not be empty")
    return Path(os.path.abspath(path.expanduser()))


def _write_new_file_atomically(destination: Path, content: bytes) -> None:
    _validate_destination(destination)
    if os.name == "nt":
        _write_windows_file(destination, content)
        return
    parent_fd = _open_parent_without_symlinks(destination.parent)
    temporary_name = f".{destination.name}.{uuid4().hex}.tmp"
    temporary_fd: int | None = None
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        temporary_fd = os.open(temporary_name, flags, 0o600, dir_fd=parent_fd)
        _write_all(temporary_fd, content)
        os.fsync(temporary_fd)
        os.close(temporary_fd)
        temporary_fd = None
        try:
            os.link(
                temporary_name,
                destination.name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
                follow_symlinks=False,
            )
        except FileExistsError as error:
            raise ProjectArtifactExportError(
                f"Artifact output already exists: {destination}"
            ) from error
    except ProjectArtifactExportError:
        raise
    except OSError as error:
        raise ProjectArtifactExportError(
            f"Could not export artifact to: {destination}"
        ) from error
    finally:
        if temporary_fd is not None:
            os.close(temporary_fd)
        try:
            os.unlink(temporary_name, dir_fd=parent_fd)
        except FileNotFoundError:
            pass
        finally:
            os.close(parent_fd)


def _write_all(file_descriptor: int, content: bytes) -> None:
    offset = 0
    while offset < len(content):
        written = os.write(file_descriptor, content[offset:])
        if written <= 0:
            raise OSError("Artifact export write made no progress")
        offset += written


def _validate_destination(destination: Path) -> None:
    if not destination.name:
        raise ProjectArtifactExportError("Artifact output path must name a file")
    try:
        metadata = destination.lstat()
    except (FileNotFoundError, NotADirectoryError):
        return
    if stat.S_ISLNK(metadata.st_mode):
        raise ProjectArtifactExportError(
            f"Artifact output must not be a symlink: {destination}"
        )
    if stat.S_ISDIR(metadata.st_mode):
        raise ProjectArtifactExportError(
            f"Artifact output must not be a directory: {destination}"
        )
    raise ProjectArtifactExportError(f"Artifact output already exists: {destination}")


def _open_parent_without_symlinks(parent: Path) -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(parent.anchor, flags)
    traversed = Path(parent.anchor)
    try:
        for part in parent.parts[1:]:
            traversed /= part
            try:
                metadata = os.stat(part, dir_fd=descriptor, follow_symlinks=False)
                if stat.S_ISLNK(metadata.st_mode):
                    raise ProjectArtifactExportError(
                        f"Artifact output parent must not be a symlink: {traversed}"
                    )
                if not stat.S_ISDIR(metadata.st_mode):
                    raise ProjectArtifactExportError(
                        f"Artifact output parent is not a directory: {traversed}"
                    )
                child = os.open(part, flags, dir_fd=descriptor)
            except FileNotFoundError as error:
                raise ProjectArtifactExportError(
                    f"Artifact output parent does not exist: {traversed}"
                ) from error
            except NotADirectoryError as error:
                raise ProjectArtifactExportError(
                    f"Artifact output parent is not a directory: {traversed}"
                ) from error
            except OSError as error:
                if error.errno == getattr(os, "ELOOP", 40):
                    raise ProjectArtifactExportError(
                        f"Artifact output parent must not be a symlink: {traversed}"
                    ) from error
                raise
            os.close(descriptor)
            descriptor = child
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _media_type(artifact_format: ProjectArtifactFormat) -> str:
    if artifact_format is ProjectArtifactFormat.JSON:
        return JSON_MEDIA_TYPE
    if artifact_format is ProjectArtifactFormat.MARKDOWN:
        return MARKDOWN_MEDIA_TYPE
    return TEXT_MEDIA_TYPE


def _write_windows_file(destination: Path, content: bytes) -> None:
    """Same atomic no-overwrite policy using protected Windows parent handles."""
    from tempfile import NamedTemporaryFile

    from ai_agent_project.windows_files import protected_directory_chain

    temporary = None
    try:
        with protected_directory_chain(destination.parent):
            try:
                with NamedTemporaryFile(dir=destination.parent, delete=False) as stream:
                    temporary = Path(stream.name)
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.link(temporary, destination)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
    except OSError:
        raise ProjectArtifactExportError(
            "Cannot export to this destination; use a new file in a writable folder without links."
        ) from None
