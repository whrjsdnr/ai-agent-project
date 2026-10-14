import hashlib
import os
from pathlib import Path

import pytest

import ai_agent_project.agent.project_artifact_export as export_module
from ai_agent_project.agent.project_artifact import (
    ProjectArtifactDescriptor,
    ProjectArtifactSource,
    ProjectArtifactType,
    ProjectArtifactView,
)
from ai_agent_project.agent.project_artifact_application import (
    ProjectArtifactError,
    ProjectArtifactNotFoundError,
)
from ai_agent_project.agent.project_artifact_export import (
    ProjectArtifactExportError,
    ProjectArtifactExportService,
)
from ai_agent_project.agent.project_artifact_rendering import (
    JSON_MEDIA_TYPE,
    MARKDOWN_MEDIA_TYPE,
    TEXT_MEDIA_TYPE,
    ProjectArtifactFormat,
    ProjectArtifactRenderingError,
    render_project_artifact,
    supported_media_types,
)


def _view(
    artifact_type: ProjectArtifactType = ProjectArtifactType.SPECIFICATION,
    content=None,
) -> ProjectArtifactView:
    return ProjectArtifactView(
        descriptor=ProjectArtifactDescriptor(
            artifact_id=f"developer:run:{artifact_type.value}:v1",
            artifact_type=artifact_type,
            source_domain=ProjectArtifactSource.DEVELOPER,
            source_run_id="run",
            source_version="v1",
            title="Artifact",
            media_types=supported_media_types(artifact_type),
        ),
        content={"title": "한글", "zero": 0} if content is None else content,
    )


class _Artifacts:
    def __init__(
        self, view: ProjectArtifactView, error: Exception | None = None
    ) -> None:
        self.view = view
        self.error = error
        self.calls: list[tuple[str, str]] = []

    def get_artifact(self, project_id: str, artifact_id: str) -> ProjectArtifactView:
        self.calls.append((project_id, artifact_id))
        if self.error is not None:
            raise self.error
        return self.view


@pytest.mark.parametrize(
    ("artifact_format", "media_type", "suffix"),
    (
        (ProjectArtifactFormat.JSON, JSON_MEDIA_TYPE, ".json"),
        (ProjectArtifactFormat.MARKDOWN, MARKDOWN_MEDIA_TYPE, ".md"),
    ),
)
def test_structured_single_file_export_is_exact(
    tmp_path: Path,
    artifact_format: ProjectArtifactFormat,
    media_type: str,
    suffix: str,
) -> None:
    view = _view()
    service = ProjectArtifactExportService(_Artifacts(view))  # type: ignore[arg-type]
    destination = tmp_path / f"artifact{suffix}"
    expected = render_project_artifact(view, artifact_format).encode()

    result = service.export_artifact(
        "project", "artifact", artifact_format, destination
    )

    assert destination.read_bytes() == expected
    assert result.bytes_written == len(expected)
    assert result.sha256 == hashlib.sha256(expected).hexdigest()
    assert result.media_type == media_type
    assert result.output_path == str(destination)


def test_generated_file_text_export_preserves_every_byte(tmp_path: Path) -> None:
    exact = "line one\n  indented\n\n# * | ` < >\nno final newline"
    view = _view(
        ProjectArtifactType.RESEARCH_GENERATED_FILE,
        {"artifact_id": "A", "relative_path": "pkg/a.py", "content": exact},
    )
    service = ProjectArtifactExportService(_Artifacts(view))  # type: ignore[arg-type]
    destination = tmp_path / "generated.py"
    result = service.export_artifact(
        "project", "artifact", ProjectArtifactFormat.TEXT, destination
    )
    assert destination.read_bytes() == exact.encode("utf-8")
    assert not destination.read_bytes().endswith(b"\n")
    assert result.media_type == TEXT_MEDIA_TYPE


def test_existing_file_directory_and_final_symlinks_are_rejected(
    tmp_path: Path,
) -> None:
    view = _view()
    service = ProjectArtifactExportService(_Artifacts(view))  # type: ignore[arg-type]
    existing = tmp_path / "existing"
    existing.write_bytes(b"unchanged")
    directory = tmp_path / "directory"
    directory.mkdir()
    target = tmp_path / "target"
    target.write_bytes(b"target")
    symlink = tmp_path / "link"
    symlink.symlink_to(target)
    dangling = tmp_path / "dangling"
    dangling.symlink_to(tmp_path / "absent")

    for destination in (existing, directory, symlink, dangling):
        with pytest.raises(ProjectArtifactExportError):
            service.export_artifact(
                "project", "artifact", ProjectArtifactFormat.JSON, destination
            )
    assert existing.read_bytes() == b"unchanged"
    assert target.read_bytes() == b"target"


def test_missing_file_and_symlink_parents_are_rejected(tmp_path: Path) -> None:
    service = ProjectArtifactExportService(_Artifacts(_view()))  # type: ignore[arg-type]
    missing = tmp_path / "missing" / "out"
    parent_file = tmp_path / "parent-file"
    parent_file.write_bytes(b"parent")
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    nested = tmp_path / "outer"
    nested.mkdir()
    nested_link = nested / "link"
    nested_link.symlink_to(real, target_is_directory=True)

    for destination in (
        missing,
        parent_file / "out",
        link / "out",
        nested_link / "out",
    ):
        with pytest.raises(ProjectArtifactExportError):
            service.export_artifact(
                "project", "artifact", ProjectArtifactFormat.JSON, destination
            )
        assert not destination.exists()


@pytest.mark.parametrize(
    "error",
    (
        ProjectArtifactNotFoundError("Project artifact not found: foreign"),
        ProjectArtifactError("Linked Developer run not found: missing"),
    ),
)
def test_lookup_failures_create_no_output(tmp_path: Path, error: Exception) -> None:
    destination = tmp_path / "out"
    service = ProjectArtifactExportService(_Artifacts(_view(), error))  # type: ignore[arg-type]
    with pytest.raises(type(error), match=str(error)):
        service.export_artifact(
            "project", "artifact", ProjectArtifactFormat.JSON, destination
        )
    assert not destination.exists()


def test_unsupported_format_creates_no_output(tmp_path: Path) -> None:
    destination = tmp_path / "out"
    service = ProjectArtifactExportService(_Artifacts(_view()))  # type: ignore[arg-type]
    with pytest.raises(ProjectArtifactRenderingError, match="does not support"):
        service.export_artifact(
            "project", "artifact", ProjectArtifactFormat.TEXT, destination
        )
    assert not destination.exists()


def test_write_failure_cleans_temporary_and_final_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "out"
    service = ProjectArtifactExportService(_Artifacts(_view()))  # type: ignore[arg-type]

    def fail_write(_descriptor: int, _content: bytes) -> int:
        raise OSError("simulated write failure")

    monkeypatch.setattr(export_module.os, "write", fail_write)
    with pytest.raises(ProjectArtifactExportError, match="Could not export"):
        service.export_artifact(
            "project", "artifact", ProjectArtifactFormat.JSON, destination
        )
    assert not destination.exists()
    assert list(tmp_path.iterdir()) == []


def test_destination_race_never_overwrites_and_cleans_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "out"
    service = ProjectArtifactExportService(_Artifacts(_view()))  # type: ignore[arg-type]
    real_link = os.link

    def race_link(source: str, target: str, **kwargs: object) -> None:
        directory_fd = kwargs["dst_dir_fd"]
        descriptor = os.open(
            target,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
            dir_fd=directory_fd,
        )
        os.write(descriptor, b"racer")
        os.close(descriptor)
        real_link(source, target, **kwargs)

    monkeypatch.setattr(export_module.os, "link", race_link)
    with pytest.raises(ProjectArtifactExportError, match="already exists"):
        service.export_artifact(
            "project", "artifact", ProjectArtifactFormat.JSON, destination
        )
    assert destination.read_bytes() == b"racer"
    assert list(tmp_path.iterdir()) == [destination]
