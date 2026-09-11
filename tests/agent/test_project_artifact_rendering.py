import pytest

from ai_agent_project.agent.project_artifact import (
    ProjectArtifactDescriptor,
    ProjectArtifactSource,
    ProjectArtifactType,
    ProjectArtifactView,
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

STRUCTURED_TYPES = tuple(
    item
    for item in ProjectArtifactType
    if item is not ProjectArtifactType.RESEARCH_GENERATED_FILE
)


def _view(
    artifact_type: ProjectArtifactType,
    content=None,
) -> ProjectArtifactView:
    return ProjectArtifactView(
        descriptor=ProjectArtifactDescriptor(
            artifact_id=f"developer:run:{artifact_type.value}:v1",
            artifact_type=artifact_type,
            source_domain=ProjectArtifactSource.DEVELOPER,
            source_run_id="run",
            source_version="v1",
            title="Title # * | ` < >",
            media_types=supported_media_types(artifact_type),
        ),
        content=(
            {
                "zero": 0,
                "false": False,
                "none": None,
                "empty_string": "",
                "empty_list": [],
                "empty_object": {},
                "status": "not_measured",
                "execution": "not_executed",
                "assessment": "inconclusive",
                "special": "# heading * star | pipe ` tick <tag>\nnext",
            }
            if content is None
            else content
        ),
    )


@pytest.mark.parametrize("artifact_type", STRUCTURED_TYPES)
def test_all_structured_artifacts_have_deterministic_exhaustive_markdown(
    artifact_type: ProjectArtifactType,
) -> None:
    view = _view(artifact_type)
    first = render_project_artifact(view, ProjectArtifactFormat.MARKDOWN)
    reloaded = ProjectArtifactView.model_validate(view.model_dump(mode="json"))
    second = render_project_artifact(reloaded, ProjectArtifactFormat.MARKDOWN)
    assert first == second
    assert first.endswith("\n")
    for expected in (
        "**zero:** 0",
        "**false:** false",
        "**none:** null",
        '**empty\\_string:** ""',
        "**empty\\_list:**\n  []",
        "**empty\\_object:**\n  {}",
        "not\\_measured",
        "not\\_executed",
        "inconclusive",
        "\\# heading \\* star \\| pipe \\` tick &lt;tag&gt;<br>\nnext",
    ):
        assert expected in first


def test_markdown_sorts_mapping_keys_and_preserves_list_order() -> None:
    rendered = render_project_artifact(
        _view(ProjectArtifactType.SPECIFICATION, {"z": ["second", "first"], "a": 1}),
        ProjectArtifactFormat.MARKDOWN,
    )
    assert rendered.index("**a:**") < rendered.index("**z:**")
    assert rendered.index("second") < rendered.index("first")


def test_generated_file_text_is_exact_and_capabilities_are_closed() -> None:
    exact = "  first line\nsecond line  "
    view = _view(
        ProjectArtifactType.RESEARCH_GENERATED_FILE,
        {
            "artifact_id": "A",
            "relative_path": "pkg/a.py",
            "content": exact,
            "task_id": "T",
        },
    )
    assert view.descriptor.media_types == (JSON_MEDIA_TYPE, TEXT_MEDIA_TYPE)
    assert render_project_artifact(view, ProjectArtifactFormat.TEXT) == exact
    assert not render_project_artifact(view, ProjectArtifactFormat.TEXT).endswith("\n")
    with pytest.raises(ProjectArtifactRenderingError, match="does not support"):
        render_project_artifact(view, ProjectArtifactFormat.MARKDOWN)

    structured = _view(ProjectArtifactType.SPECIFICATION)
    assert structured.descriptor.media_types == (
        JSON_MEDIA_TYPE,
        MARKDOWN_MEDIA_TYPE,
    )
    with pytest.raises(ProjectArtifactRenderingError, match="does not support"):
        render_project_artifact(structured, ProjectArtifactFormat.TEXT)


def test_package_markdown_is_manifest_without_generated_file_body() -> None:
    view = _view(
        ProjectArtifactType.RESEARCH_IMPLEMENTATION_PACKAGE,
        {
            "generated_not_executed": True,
            "artifacts": [
                {
                    "artifact_id": "A",
                    "relative_path": "pkg/a.py",
                    "content": "DO_NOT_DUPLICATE_BODY",
                }
            ],
        },
    )
    rendered = render_project_artifact(view, ProjectArtifactFormat.MARKDOWN)
    assert "A" in rendered
    assert "pkg/a\\.py" in rendered
    assert "DO_NOT_DUPLICATE_BODY" not in rendered


def test_json_rendering_remains_sorted_and_structurally_compatible() -> None:
    view = _view(ProjectArtifactType.RESEARCH_RESULTS, {"z": 0, "a": False})
    rendered = render_project_artifact(view, ProjectArtifactFormat.JSON)
    assert rendered == render_project_artifact(view, ProjectArtifactFormat.JSON)
    assert rendered.index('"a"') < rendered.index('"z"')
    assert '"descriptor"' in rendered and '"content"' in rendered
