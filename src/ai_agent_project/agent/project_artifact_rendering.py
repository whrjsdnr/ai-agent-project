"""Pure deterministic JSON, Markdown, and exact-text artifact rendering."""

import json
from enum import StrEnum

from ai_agent_project.agent.project_artifact import (
    JsonScalar,
    JsonValue,
    ProjectArtifactType,
    ProjectArtifactView,
)

JSON_MEDIA_TYPE = "application/json"
MARKDOWN_MEDIA_TYPE = "text/markdown"
TEXT_MEDIA_TYPE = "text/plain"


class ProjectArtifactFormat(StrEnum):
    JSON = "json"
    MARKDOWN = "markdown"
    TEXT = "text"


class ProjectArtifactRenderingError(ValueError):
    """Raised when an artifact does not support a requested rendering format."""


def canonical_artifact_content_bytes(content: JsonValue) -> bytes:
    """Hash input: content only, sorted compact JSON, UTF-8, no final newline.

    Uses ensure_ascii=False and separators=(",", ":"). Lists and exact string
    values (including generated-file whitespace/newlines) remain unchanged.
    Descriptors/rendered Markdown are excluded. Generated files include their
    whole stored artifact object, not just the text body. No content is archived.
    """
    return json.dumps(
        content, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def supported_media_types(
    artifact_type: ProjectArtifactType,
) -> tuple[str, ...]:
    if artifact_type is ProjectArtifactType.RESEARCH_GENERATED_FILE:
        return (JSON_MEDIA_TYPE, TEXT_MEDIA_TYPE)
    return (JSON_MEDIA_TYPE, MARKDOWN_MEDIA_TYPE)


def render_project_artifact(
    view: ProjectArtifactView, artifact_format: ProjectArtifactFormat
) -> str:
    """Render one immutable view without modifying or enriching its content."""
    supported = supported_formats(view.descriptor.artifact_type)
    if artifact_format not in supported:
        raise ProjectArtifactRenderingError(
            f"Artifact type {view.descriptor.artifact_type.value} does not support "
            f"format {artifact_format.value}"
        )
    if artifact_format is ProjectArtifactFormat.JSON:
        return json.dumps(
            view.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
        )
    if artifact_format is ProjectArtifactFormat.TEXT:
        return _generated_file_content(view)
    return _render_markdown(view)


def supported_formats(
    artifact_type: ProjectArtifactType,
) -> tuple[ProjectArtifactFormat, ...]:
    if artifact_type is ProjectArtifactType.RESEARCH_GENERATED_FILE:
        return (ProjectArtifactFormat.JSON, ProjectArtifactFormat.TEXT)
    return (ProjectArtifactFormat.JSON, ProjectArtifactFormat.MARKDOWN)


def _generated_file_content(view: ProjectArtifactView) -> str:
    if not isinstance(view.content, dict):
        raise ProjectArtifactRenderingError(
            "Generated research file content must be a JSON object"
        )
    content = view.content.get("content")
    if not isinstance(content, str):
        raise ProjectArtifactRenderingError(
            "Generated research file has no authoritative text content"
        )
    return content


def _render_markdown(view: ProjectArtifactView) -> str:
    descriptor = view.descriptor
    lines = [
        f"# {_escape_markdown(descriptor.title)}",
        "",
        f"- **Artifact ID:** {_escape_markdown(descriptor.artifact_id)}",
        f"- **Artifact type:** {_escape_markdown(descriptor.artifact_type.value)}",
        f"- **Source domain:** {_escape_markdown(descriptor.source_domain.value)}",
        f"- **Source run ID:** {_escape_markdown(descriptor.source_run_id)}",
        f"- **Source version:** {_escape_markdown(descriptor.source_version)}",
        "",
        "## Content",
        "",
    ]
    lines.extend(_render_value(_markdown_content(view), indent=0))
    return "\n".join(lines) + "\n"


def _markdown_content(view: ProjectArtifactView) -> JsonValue:
    if (
        view.descriptor.artifact_type
        is not ProjectArtifactType.RESEARCH_IMPLEMENTATION_PACKAGE
        or not isinstance(view.content, dict)
    ):
        return view.content
    package = dict(view.content)
    artifacts = package.get("artifacts")
    if isinstance(artifacts, list):
        package["artifacts"] = [
            {key: value for key, value in artifact.items() if key != "content"}
            if isinstance(artifact, dict)
            else artifact
            for artifact in artifacts
        ]
    return package


def _render_value(value: JsonValue, *, indent: int) -> list[str]:
    prefix = "  " * indent
    if isinstance(value, dict):
        if not value:
            return [f"{prefix}{{}}"]
        lines: list[str] = []
        for key in sorted(value):
            item = value[key]
            label = _escape_markdown(str(key))
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}- **{label}:**")
                lines.extend(_render_value(item, indent=indent + 1))
            else:
                lines.append(f"{prefix}- **{label}:** {_render_scalar(item)}")
        return lines
    if isinstance(value, list):
        if not value:
            return [f"{prefix}[]"]
        lines = []
        for item in value:
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}-")
                lines.extend(_render_value(item, indent=indent + 1))
            else:
                lines.append(f"{prefix}- {_render_scalar(item)}")
        return lines
    return [f"{prefix}{_render_scalar(value)}"]


def _render_scalar(value: JsonScalar) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return '""' if value == "" else _escape_markdown(value)
    return str(value)


def _escape_markdown(value: str) -> str:
    escaped = value.replace("\\", "\\\\")
    for character in (
        "`",
        "*",
        "_",
        "{",
        "}",
        "[",
        "]",
        "(",
        ")",
        "#",
        "+",
        "-",
        ".",
        "!",
        "|",
    ):
        escaped = escaped.replace(character, f"\\{character}")
    escaped = escaped.replace("<", "&lt;").replace(">", "&gt;")
    return escaped.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>\n")
