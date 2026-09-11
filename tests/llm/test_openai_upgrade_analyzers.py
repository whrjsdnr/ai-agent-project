"""Offline structured-output tests for existing-project upgrade providers."""

import json
from types import SimpleNamespace
from typing import Any

import pytest

from ai_agent_project.agent.codebase_analysis import CodebaseAnalysis
from ai_agent_project.agent.upgrade import UpgradeRequest
from ai_agent_project.agent.workspace import WorkspaceSnapshot
from ai_agent_project.llm.providers.openai_codebase_analyzer import (
    CodebaseAnalysisError,
    OpenAICodebaseAnalyzer,
)
from ai_agent_project.llm.providers.openai_upgrade_analyzer import (
    OpenAIUpgradeAnalyzer,
    UpgradeAnalysisError,
)


class _Responses:
    def __init__(self, responses: list[object]) -> None:
        self.responses = responses
        self.requests: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> object:
        self.requests.append(kwargs)
        return self.responses.pop(0)


class _Client:
    def __init__(self, responses: list[object]) -> None:
        self.responses = _Responses(responses)


def test_codebase_analyzer_uses_workspace_only_and_rejects_unknown_files() -> None:
    client = _Client(
        [
            SimpleNamespace(
                output_text=json.dumps(
                    {
                        "project_name": "Todo",
                        "project_type": "FastAPI",
                        "test_files": ["tests/test_app.py"],
                        "important_files": [
                            {"path": "src/app.py", "purpose": "application"}
                        ],
                        "summary": "Existing API",
                    }
                )
            )
        ]
    )
    workspace = WorkspaceSnapshot(files=["src/app.py", "tests/test_app.py"])

    result = OpenAICodebaseAnalyzer(client=client, model="test").analyze(workspace)

    assert result.project_type == "FastAPI"
    request = client.responses.requests[0]
    assert request["text"]["format"]["strict"] is True
    assert "src/app.py" in request["input"][0]["content"]
    schema = request["text"]["format"]["schema"]
    assert schema["required"] == list(schema["properties"])

    invalid = _Client(
        [SimpleNamespace(output_text=json.dumps({"test_files": ["outside.py"]}))]
    )
    with pytest.raises(CodebaseAnalysisError):
        OpenAICodebaseAnalyzer(client=invalid).analyze(workspace)


def test_upgrade_analyzer_includes_request_analysis_and_workspace() -> None:
    client = _Client(
        [
            SimpleNamespace(
                output_text=json.dumps(
                    {
                        "title": "Todo filtering",
                        "objective": "Add filtering.",
                        "current_system_summary": "Existing Todo API.",
                        "requirements": [
                            {
                                "id": "UPG-REQ-001",
                                "description": "Filter completed todos.",
                                "acceptance_criteria": [
                                    'filter_todos("completed") returns matching todos'
                                ],
                            }
                        ],
                        "constraints": ["Preserve CRUD."],
                        "acceptance_criteria": ["Existing tests pass."],
                        "impact": {"affected_files": ["src/app.py"]},
                    }
                )
            )
        ]
    )
    workspace = WorkspaceSnapshot(files=["src/app.py"])
    result = OpenAIUpgradeAnalyzer(client=client, model="test").analyze(
        CodebaseAnalysis(summary="Existing Todo API."),
        UpgradeRequest(request_text="Add filtering."),
        workspace,
    )

    assert result.requirements[0].id == "UPG-REQ-001"
    request = client.responses.requests[0]
    assert request["text"]["format"]["strict"] is True
    assert "Add filtering." in request["input"][0]["content"]
    assert "src/app.py" in request["input"][0]["content"]

    malformed = _Client([SimpleNamespace(output_text="not json")])
    with pytest.raises(UpgradeAnalysisError):
        OpenAIUpgradeAnalyzer(client=malformed).analyze(
            CodebaseAnalysis(), UpgradeRequest(request_text="Add filtering.")
        )
