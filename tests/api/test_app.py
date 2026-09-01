"""Tests for the agent HTTP API."""

from fastapi.testclient import TestClient

from ai_agent_project.agent.service import AgentService
from ai_agent_project.llm.base import LLMResponse
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


def test_agent_run_endpoint() -> None:
    from ai_agent_project.api.app import create_app

    service = AgentService(FakeLLMClient(), ToolRegistry())
    client = TestClient(create_app(service))

    response = client.post("/v1/agent-runs", json={"user_message": "Hello"})

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["final_answer"] == "API response"
