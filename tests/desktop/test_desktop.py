"""Provider-free desktop acceptance and boundary regressions."""

import json
from datetime import UTC, datetime
from unittest.mock import Mock
from uuid import uuid4

import pytest
from openai import OpenAIError
from pydantic import SecretStr, ValidationError

from ai_agent_project.agent.project_artifact_rendering import (
    ProjectArtifactFormat,
    render_project_artifact,
)
from ai_agent_project.agent.project_handoff import ProjectHandoff, ProjectHandoffPurpose
from ai_agent_project.agent.project_session import ProjectStatus
from ai_agent_project.agent.research import WorkMode
from ai_agent_project.desktop import DesktopError, DesktopErrorCode
from ai_agent_project.llm.config import ProviderConfig, ProviderConfigError


def test_phase_6b_acceptance(setup, monkeypatch, capsys):
    desktop = setup.desktop
    credential = str(uuid4())
    monkeypatch.setenv("OPENAI_API_KEY", credential)
    before = setup.snapshot()
    dashboard = desktop.get_dashboard()
    listing = desktop.list_projects()
    views = tuple(desktop.get_project_view(p.project_id) for p in listing)
    assert dashboard.total_projects == dashboard.active_projects == 3
    assert dashboard.completed_projects == 0
    assert dashboard.awaiting_user_action_count == 3
    assert listing == tuple(
        sorted(listing, key=lambda p: (p.created_at, p.project_id), reverse=True)
    )
    for view in views:
        assert view.project.status == "active"
        assert view.project.project_mode == "new"
        assert view.project.project_id == setup.ids[WorkMode(view.project.work_mode)]
        authoritative = setup.sessions.get_pending_actions(view.project.project_id)
        assert tuple(a.action_type for a in view.project.pending_actions) == tuple(
            a.action_type.value for a in authoritative
        )
    hybrid = desktop.get_project_view(setup.ids[WorkMode.HYBRID])
    assert hybrid.developer.pending_action.action_type == "approve_developer_plan"
    assert hybrid.researcher.pending_action.action_type == "select_research_direction"
    assert len(hybrid.hybrid.actionable_actions) == 2
    for _ in range(3):
        assert desktop.get_dashboard() == dashboard
        assert desktop.list_projects() == listing
        assert tuple(desktop.get_project_view(p.project_id) for p in listing) == views
        for project in listing:
            artifacts = desktop.list_project_artifacts(project.project_id)
            assert artifacts
            content = desktop.get_artifact_view(
                project.project_id, artifacts[0].artifact_id
            )
            assert (
                json.loads(content.content)["descriptor"]["artifact_id"]
                == artifacts[0].artifact_id
            )
        assert desktop.get_provider_config().credential_configured
    assert setup.snapshot() == before
    assert credential not in repr((dashboard, listing, views))
    assert "api_key" not in desktop.get_provider_config().model_dump_json()
    # Researcher selection is allowed even while Developer approval is pending.
    desktop.select_research_direction(hybrid.project.project_id, "DIRECTION:1")
    after = setup.snapshot()
    changed = [name for name in before if before[name] != after[name]]
    assert changed == [f"researchers/{hybrid.researcher.run_id}.json"]
    updated = desktop.get_project_view(hybrid.project.project_id)
    assert updated.researcher.status == "direction_selected"
    assert updated.developer == hybrid.developer
    assert updated.project.status == "active"
    print("PHASE_6B_DESKTOP_UX_LAYER=PASSED")
    assert "PHASE_6B_DESKTOP_UX_LAYER=PASSED" in capsys.readouterr().out


def test_artifact_delegation_and_no_private_internals(setup, monkeypatch):
    project_id = setup.ids[WorkMode.DEVELOPER]
    spy = Mock(wraps=setup.artifacts.list_artifacts)
    monkeypatch.setattr(setup.artifacts, "list_artifacts", spy)
    artifacts = setup.desktop.list_project_artifacts(project_id)
    spy.assert_called_once_with(project_id)
    for artifact in artifacts:
        result = setup.desktop.get_artifact_view(project_id, artifact.artifact_id)
        assert result.content == render_project_artifact(
            setup.artifacts.get_artifact(project_id, artifact.artifact_id),
            ProjectArtifactFormat.JSON,
        )
        assert not {
            "agent_state",
            "workspace",
            "tool_calls",
            "provider_context",
            "messages",
        } & set(json.loads(result.content)["content"])
    foreign = setup.desktop.list_project_artifacts(setup.ids[WorkMode.HYBRID])[0]
    with pytest.raises(DesktopError) as exc:
        setup.desktop.get_artifact_view(project_id, foreign.artifact_id)
    assert exc.value.code == DesktopErrorCode.NOT_FOUND
    with pytest.raises(DesktopError) as exc:
        setup.desktop.get_artifact_view(
            project_id, artifacts[0].artifact_id, ProjectArtifactFormat.TEXT
        )
    assert exc.value.code == DesktopErrorCode.VALIDATION_ERROR


def test_handoff_derived_status_is_read_only(setup):
    project_id = setup.ids[WorkMode.HYBRID]
    run_id = setup.sessions.get_project(project_id).project.research_run_id
    handoff = ProjectHandoff(
        handoff_id=str(uuid4()),
        project_id=project_id,
        source_domain="researcher",
        source_run_id=run_id,
        artifact_id="missing",
        content_sha256="0" * 64,
        purpose=ProjectHandoffPurpose.DEVELOPER_BOOTSTRAP_CONTEXT,
        created_at=datetime.now(UTC),
    )
    setup.handoff_store.create(handoff)
    before = setup.snapshot()
    first = setup.desktop.list_handoffs(project_id)
    assert first[0].status == "artifact_missing"
    assert first[0].artifact_type is None
    assert first[0].handoff_id == handoff.handoff_id
    assert setup.desktop.get_project_view(project_id).handoffs == first
    assert setup.desktop.list_handoffs(project_id) == first
    assert setup.snapshot() == before


@pytest.mark.parametrize(
    "method", ["continue_developer", "continue_researcher", "approve_research_plan"]
)
def test_invalid_action_authoritative_rejection(setup, method):
    before = setup.snapshot()
    with pytest.raises(DesktopError) as exc:
        getattr(setup.desktop, method)(setup.ids[WorkMode.HYBRID])
    assert exc.value.code == DesktopErrorCode.ACTION_NOT_ALLOWED
    assert setup.snapshot() == before


def test_explicit_developer_approval_does_not_execute(setup):
    project_id = setup.ids[WorkMode.HYBRID]
    before = setup.desktop.get_project_view(project_id)
    snapshot = setup.snapshot()
    setup.desktop.approve_developer_plan(project_id)
    after = setup.desktop.get_project_view(project_id)
    assert after.developer.status == "ready"
    assert after.researcher == before.researcher
    assert [p for p, value in setup.snapshot().items() if snapshot[p] != value] == [
        f"developers/{before.developer.run_id}.json"
    ]
    with pytest.raises(DesktopError) as exc:
        setup.desktop.approve_developer_plan(project_id)
    assert exc.value.code == DesktopErrorCode.ACTION_NOT_ALLOWED


@pytest.mark.parametrize(
    "method",
    ["get_project_view", "list_project_artifacts", "list_handoffs", "complete_project"],
)
def test_missing_project_is_normalized(setup, method):
    with pytest.raises(DesktopError) as exc:
        getattr(setup.desktop, method)(str(uuid4()))
    assert exc.value.code == DesktopErrorCode.NOT_FOUND


def test_provider_settings_are_separate_and_secret_free(setup, monkeypatch):
    credential = str(uuid4())
    config = ProviderConfig(model="local-test", api_key=SecretStr(credential))
    before = setup.snapshot()
    setup.desktop.save_provider_config(config)
    assert setup.desktop.get_provider_config().model == "local-test"
    assert not setup.desktop.get_provider_config().credential_configured
    assert all(setup.snapshot()[name] == value for name, value in before.items())
    assert credential not in repr(config)
    assert credential not in str(config)
    assert credential.encode() not in (setup.root / "settings/llm.json").read_bytes()
    monkeypatch.setenv("OPENAI_API_KEY", credential)
    assert setup.desktop.get_provider_config().credential_configured
    assert credential not in setup.desktop.get_provider_config().model_dump_json()


@pytest.mark.parametrize(
    "error, code",
    [
        (OpenAIError, DesktopErrorCode.PROVIDER_ERROR),
        (ProviderConfigError, DesktopErrorCode.CONFIGURATION_ERROR),
    ],
)
def test_error_strings_do_not_leak_provider_secrets(setup, monkeypatch, error, code):
    credential = str(uuid4())
    monkeypatch.setattr(
        setup.desktop._provider, "resolve", Mock(side_effect=error(credential))
    )
    with pytest.raises(DesktopError) as exc:
        setup.desktop.get_provider_config()
    assert exc.value.code == code
    assert credential not in repr(exc.value) + str(exc.value)
    assert exc.value.__suppress_context__


def test_connection_test_delegates_and_sanitizes(setup, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", str(uuid4()))
    # Phase 6A catches the deliberately blocked client construction.
    before = setup.snapshot()
    result = setup.desktop.test_provider_connection()
    assert not result.success
    assert "Unexpected provider call" not in result.message
    assert setup.snapshot() == before


def test_programming_errors_are_not_hidden(setup, monkeypatch):
    monkeypatch.setattr(
        setup.desktop._sessions, "list_projects", Mock(side_effect=TypeError("bug"))
    )
    with pytest.raises(TypeError, match="bug"):
        setup.desktop.list_projects()


def test_views_are_immutable(setup):
    view = setup.desktop.get_project_view(setup.ids[WorkMode.HYBRID])
    with pytest.raises(ValidationError):
        view.project.status = "completed"
    with pytest.raises(ValidationError):
        view.developer.pending_action.title = "Changed"
    assert isinstance(view.artifacts, tuple)


def test_completed_project_has_no_actions(setup):
    project_id = setup.ids[WorkMode.HYBRID]
    setup.desktop.complete_project(project_id)
    view = setup.desktop.get_project_view(project_id)
    assert view.project.status == ProjectStatus.COMPLETED
    assert view.project.pending_actions == ()
    assert view.developer.pending_action is view.researcher.pending_action is None
    assert setup.desktop.get_dashboard().completed_projects == 1


def test_create_keeps_mode_unconfirmed_and_lanes_unbound(setup, monkeypatch):
    from ai_agent_project.agent.project_session import ProjectModeProposal
    from ai_agent_project.agent.upgrade import ProjectMode

    proposer = Mock()
    proposer.propose.return_value = ProjectModeProposal(
        proposed_work_mode=WorkMode.HYBRID,
        proposed_project_mode=ProjectMode.NEW,
        rationale="Advisory only",
    )
    monkeypatch.setattr(setup.sessions, "_mode_proposer", proposer)
    project_id = setup.desktop.create_project("New request", title="New project")
    proposer.propose.assert_called_once_with("New request")
    before = setup.snapshot()
    view = setup.desktop.get_project_view(project_id)
    assert view.project.work_mode is None
    assert view.project.project_mode is None
    assert view.developer is view.researcher is None
    assert view.project.pending_actions[0].action_type == "confirm_mode"
    assert view.project.pending_actions[0].requires_payload
    assert setup.snapshot() == before
    setup.desktop.confirm_project_mode(project_id, WorkMode.HYBRID, ProjectMode.NEW)
    view = setup.desktop.get_project_view(project_id)
    assert not view.developer.bound and not view.researcher.bound
    assert view.developer.pending_action.action_type == "bind_developer_run"
    assert view.researcher.pending_action.action_type == "bind_research_run"
    assert view.artifacts == view.handoffs == ()


def test_invalid_direction_does_not_change_any_lane(setup):
    before = setup.snapshot()
    with pytest.raises(DesktopError) as exc:
        setup.desktop.select_research_direction(setup.ids[WorkMode.HYBRID], "unknown")
    assert exc.value.code == DesktopErrorCode.NOT_FOUND
    assert setup.snapshot() == before


def test_handoff_creation_uses_authoritative_validation(setup):
    project_id = setup.ids[WorkMode.HYBRID]
    artifact = setup.desktop.list_project_artifacts(project_id)[0]
    before = setup.snapshot()
    with pytest.raises(DesktopError) as exc:
        setup.desktop.create_handoff(project_id, artifact.artifact_id)
    assert exc.value.code == DesktopErrorCode.INVALID_STATE
    assert setup.snapshot() == before


def test_provider_generation_error_is_normalized(setup, monkeypatch):
    from ai_agent_project.llm.providers.openai_project_mode_proposer import (
        ProjectModeProposalError,
    )

    credential = str(uuid4())
    monkeypatch.setattr(
        setup.sessions,
        "create_project_request",
        Mock(side_effect=ProjectModeProposalError(credential)),
    )
    with pytest.raises(DesktopError) as exc:
        setup.desktop.create_project("Request")
    assert exc.value.code == DesktopErrorCode.PROVIDER_ERROR
    assert credential not in str(exc.value)


def test_store_listing_tie_breaker_and_empty_reads(tmp_path):
    from ai_agent_project.agent.project_session import (
        ProjectModeProposal,
        ProjectSession,
    )
    from ai_agent_project.agent.project_session_application import (
        InMemoryProjectSessionStore,
    )
    from ai_agent_project.agent.project_session_file_store import FileProjectStore
    from ai_agent_project.agent.upgrade import ProjectMode

    stores = (InMemoryProjectSessionStore(), FileProjectStore(tmp_path))
    now = datetime.now(UTC)
    ids = sorted(str(uuid4()) for _ in range(3))
    for store in stores:
        assert store.list_projects() == ()
        for project_id in ids:
            store.create(
                project_id,
                ProjectSession(
                    project_id=project_id,
                    title="Tie",
                    original_request="Request",
                    status=ProjectStatus.AWAITING_MODE_CONFIRMATION,
                    mode_proposal=ProjectModeProposal(
                        proposed_work_mode=WorkMode.DEVELOPER,
                        proposed_project_mode=ProjectMode.NEW,
                        rationale="Advisory",
                    ),
                    created_at=now,
                    updated_at=now,
                ),
            )
        assert tuple(p.project_id for p in store.list_projects()) == tuple(
            reversed(ids)
        )
        assert store.list_projects() == store.list_projects()
    (tmp_path / "ignored.tmp").write_text("incomplete")
    (tmp_path / "ignored.lock").touch()
    assert len(stores[1].list_projects()) == 3
