"""Opt-in production contract test for advisory project mode proposals."""

import os

import pytest

from ai_agent_project.agent.project_session import ProjectStatus
from ai_agent_project.agent.project_session_application import ProjectSessionService
from ai_agent_project.agent.project_session_file_store import FileProjectStore
from ai_agent_project.agent.research import WorkMode
from ai_agent_project.agent.upgrade import ProjectMode
from ai_agent_project.llm.providers.openai_project_mode_proposer import (
    OpenAIProjectModeProposer,
)


class _CountingProjectModeProposer(OpenAIProjectModeProposer):
    def __init__(self) -> None:
        super().__init__(request_timeout_seconds=30.0)
        self.calls = 0

    def propose(self, original_request: str):
        self.calls += 1
        return super().propose(original_request)


def test_project_session_production_e2e(tmp_path) -> None:
    if os.getenv("RUN_OPENAI_E2E") != "1":
        pytest.skip("Set RUN_OPENAI_E2E=1 to run the OpenAI project-session E2E")
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY is required for the project-session E2E")

    request = (
        "Analyze an existing machine-learning repository, identify possible "
        "research improvements, and help plan experiments without executing them."
    )
    proposer = _CountingProjectModeProposer()
    root = tmp_path / "projects"
    service = ProjectSessionService(FileProjectStore(root), proposer)
    created = service.create_project_request(request, title="ML research review")

    assert proposer.calls == 1
    assert created.project.status is ProjectStatus.AWAITING_MODE_CONFIRMATION
    assert created.project.work_mode is None
    assert created.project.project_mode is None
    proposal = created.project.mode_proposal
    assert proposal.proposed_work_mode in set(WorkMode)
    assert proposal.proposed_project_mode in set(ProjectMode)
    assert proposal.rationale.strip()

    confirmed_work_mode = (
        WorkMode.RESEARCHER
        if proposal.proposed_work_mode is not WorkMode.RESEARCHER
        else WorkMode.DEVELOPER
    )
    confirmed_project_mode = (
        ProjectMode.NEW
        if proposal.proposed_project_mode is not ProjectMode.NEW
        else ProjectMode.UPGRADE
    )
    confirmed = service.confirm_project_mode(
        created.id, confirmed_work_mode, confirmed_project_mode
    )
    assert confirmed.project.status is ProjectStatus.ACTIVE
    assert confirmed.project.work_mode is confirmed_work_mode
    assert confirmed.project.project_mode is confirmed_project_mode
    assert confirmed.project.mode_proposal == proposal
    assert confirmed.project.developer_run_id is None
    assert confirmed.project.research_run_id is None
    assert proposer.calls == 1

    reloaded = FileProjectStore(root).get(created.id)
    assert reloaded is not None
    assert reloaded.original_request == request
    assert reloaded.mode_proposal == proposal
    assert reloaded.status is ProjectStatus.ACTIVE
    assert reloaded.work_mode is confirmed_work_mode
    assert reloaded.project_mode is confirmed_project_mode
    assert reloaded.developer_run_id is None
    assert reloaded.research_run_id is None
    assert proposer.calls == 1
