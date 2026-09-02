"""Tests for the agent HTTP API."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

from ai_agent_project.agent.service import AgentService
from ai_agent_project.llm.base import LLMResponse
from ai_agent_project.tools.calculator import CalculatorTool
from ai_agent_project.tools.file import FileTool
from ai_agent_project.tools.registry import ToolRegistry
from ai_agent_project.tools.shell import ShellTool


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


def test_default_agent_registers_calculator_file_and_shell_tools(tmp_path: Path) -> None:
    from ai_agent_project.api.app import create_default_agent_service

    service = create_default_agent_service(workspace_root=tmp_path)

    assert isinstance(service._tool_registry.get("calculator"), CalculatorTool)
    assert isinstance(service._tool_registry.get("file"), FileTool)
    assert isinstance(service._tool_registry.get("shell"), ShellTool)


def test_create_app_injects_workspace_root_for_file_tool(tmp_path: Path) -> None:
    from ai_agent_project.api.app import create_app

    app = create_app(workspace_root=tmp_path)
    service = app.state.agent_service
    file_tool = service._tool_registry.get("file")
    shell_tool = service._tool_registry.get("shell")
    result = file_tool.execute(
        {"operation": "write_file", "path": "from_app.txt", "content": "ok"}
    )

    assert result.success is True
    assert app.title == "AI Agent Project"
    assert (tmp_path / "from_app.txt").read_text(encoding="utf-8") == "ok"
    assert file_tool._workspace_root == tmp_path.resolve()
    assert shell_tool._workspace_root == tmp_path.resolve()


def test_default_agent_sends_shell_schema_to_openai(tmp_path: Path) -> None:
    from ai_agent_project.api.app import create_default_agent_service

    class FakeResponses:
        def __init__(self) -> None:
            self.request: dict[str, Any] | None = None

        def create(self, **kwargs: Any) -> object:
            self.request = kwargs
            return SimpleNamespace(output=[], output_text="Done")

    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.responses = FakeResponses()

    service = create_default_agent_service(workspace_root=tmp_path)
    provider = service._llm_client
    fake_client = FakeOpenAIClient()
    provider._client = fake_client
    provider.complete([], service._tool_registry.definitions())

    assert fake_client.responses.request is not None
    shell_schema = next(
        tool
        for tool in fake_client.responses.request["tools"]
        if tool["name"] == "shell"
    )
    assert shell_schema["type"] == "function"
    assert shell_schema["parameters"] == ShellTool(tmp_path).definition().input_schema


def test_agent_run_endpoint() -> None:
    from ai_agent_project.api.app import create_app

    service = AgentService(FakeLLMClient(), ToolRegistry())
    client = TestClient(create_app(service))

    response = client.post("/v1/agent-runs", json={"user_message": "Hello"})

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["final_answer"] == "API response"
