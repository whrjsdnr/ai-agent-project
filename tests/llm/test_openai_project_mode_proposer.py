import json
from types import SimpleNamespace
from typing import Any

import pytest

from ai_agent_project.agent.project_session import ProjectModeProposal
from ai_agent_project.llm.providers.openai_project_mode_proposer import (
    OpenAIProjectModeProposer,
    ProjectModeProposalError,
)
from ai_agent_project.llm.runtime import ProviderRequestError


class _Responses:
    def __init__(self, result: object | Exception) -> None:
        self.result = result
        self.requests: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> object:
        self.requests.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class _Client:
    def __init__(self, result: object | Exception) -> None:
        self.responses = _Responses(result)


def test_mode_proposer_uses_strict_closed_schema() -> None:
    client = _Client(
        SimpleNamespace(
            output_text=json.dumps(
                {
                    "proposed_work_mode": "hybrid",
                    "proposed_project_mode": "upgrade",
                    "rationale": "Both axes are advisory.",
                }
            )
        )
    )
    proposal = OpenAIProjectModeProposer(client=client, model="test").propose("x")
    assert isinstance(proposal, ProjectModeProposal)
    request = client.responses.requests[0]
    assert request["text"]["format"]["strict"] is True
    assert "never activate" in request["instructions"]
    assert "developer, researcher, hybrid" in request["instructions"]
    assert "new, upgrade" in request["instructions"]


@pytest.mark.parametrize("output", ["bad", None])
def test_mode_proposer_rejects_malformed_output(output: str | None) -> None:
    with pytest.raises(ProjectModeProposalError):
        OpenAIProjectModeProposer(
            client=_Client(SimpleNamespace(output_text=output)), model="test"
        ).propose("x")


def test_mode_proposer_validates_timeout_and_sanitizes_client_error() -> None:
    with pytest.raises(ValueError, match="positive"):
        OpenAIProjectModeProposer(
            client=_Client(SimpleNamespace()), request_timeout_seconds=0
        )
    with pytest.raises(ProviderRequestError, match="LLM provider request failed"):
        OpenAIProjectModeProposer(client=_Client(RuntimeError()), model="test").propose(
            "x"
        )
