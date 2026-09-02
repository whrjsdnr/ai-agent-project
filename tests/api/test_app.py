"""Tests for the agent HTTP API."""

from pathlib import Path

from fastapi.testclient import TestClient

from ai_agent_project.agent.service import AgentService
from ai_agent_project.llm.base import LLMResponse
from ai_agent_project.tools.calculator import CalculatorTool
from ai_agent_project.tools.file import FileTool
from ai_agent_project.tools.registry import ToolRegistry


class FakeLLMClient:
    """Return one final response for the API test."""

    def complete(self, messages: list[object], tools: list[object]) -> LLMResponse:
        del messages, tools
        return LLMResponse(final_answer="API response")


def test_health_endpoint() -> None:
    from ai_agent_project.api.app import create_app

    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_default_agent_registers_calculator_and_file_tools(tmp_path: Path) -> None:
    from ai_agent_project.api.app import create_default_agent_service

    service = create_default_agent_service(workspace_root=tmp_path)

    assert isinstance(service._tool_registry.get("calculator"), CalculatorTool)
    assert isinstance(service._tool_registry.get("file"), FileTool)


def test_create_app_injects_workspace_root_for_file_tool(tmp_path: Path) -> None:
    from ai_agent_project.api.app import create_app

    app = create_app(workspace_root=tmp_path)
    service = app.state.agent_service
    file_tool = service._tool_registry.get("file")
    result = file_tool.execute(
        {"operation": "write_file", "path": "from_app.txt", "content": "ok"}
    )

    assert result.success is True
    assert app.title == "AI Agent Project"
    assert (tmp_path / "from_app.txt").read_text(encoding="utf-8") == "ok"


def test_agent_run_endpoint() -> None:
    from ai_agent_project.api.app import create_app

    service = AgentService(FakeLLMClient(), ToolRegistry())
    client = TestClient(create_app(service))

    response = client.post("/v1/agent-runs", json={"user_message": "Hello"})

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["final_answer"] == "API response"
