"""OpenAI structured-output provider for Research Discovery questions."""

import json
import os

from pydantic import ValidationError

from ai_agent_project.agent.research import (
    ResearchQuestion,
    ResearchQuestionSet,
    ResearchRequest,
)
from ai_agent_project.agent.research_planning import ResearchQuestionPlanner
from ai_agent_project.agent.workspace import WorkspaceSnapshot
from ai_agent_project.llm.providers.openai import DEFAULT_MODEL, OpenAIAPIClient
from ai_agent_project.llm.providers.structured_schema import openai_strict_json_schema

_INSTRUCTIONS = (
    "Generate concise research questions, not search-engine queries. Cover established "
    "approaches, methods, datasets/metrics when relevant, recurring limitations, unresolved "
    "problems, and feasibility. Use nonblank unique IDs and only workspace, external, or mixed "
    "source_scope. Return only the structured question set."
)


class ResearchQuestionPlanningError(ValueError):
    """Raised when question-planning structured output is invalid."""


class OpenAIResearchQuestionPlanner(ResearchQuestionPlanner):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        client: OpenAIAPIClient | None = None,
    ) -> None:
        self._model = model or os.getenv("OPENAI_MODEL", DEFAULT_MODEL)
        self._api_key = api_key or os.getenv("OPENAI_API_KEY")
        self._client = client

    def plan(
        self, request: ResearchRequest, workspace: WorkspaceSnapshot | None = None
    ) -> tuple[ResearchQuestion, ...]:
        response = self._get_client().responses.create(
            model=self._model,
            instructions=_INSTRUCTIONS,
            input=[
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "request": request.model_dump(mode="json"),
                            "workspace": workspace.model_dump(mode="json")
                            if workspace
                            else None,
                        }
                    ),
                }
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "research_questions",
                    "schema": openai_strict_json_schema(ResearchQuestionSet),
                    "strict": True,
                }
            },
        )
        output = getattr(response, "output_text", None)
        if not isinstance(output, str):
            raise ResearchQuestionPlanningError(
                "OpenAI question planner returned no output"
            )
        try:
            return ResearchQuestionSet.model_validate(json.loads(output)).questions
        except (json.JSONDecodeError, ValidationError) as error:
            raise ResearchQuestionPlanningError(
                "OpenAI question planner returned invalid output"
            ) from error

    def _get_client(self) -> OpenAIAPIClient:
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise ValueError("OPENAI_API_KEY must be configured")
        from openai import OpenAI

        self._client = OpenAI(api_key=self._api_key)
        return self._client
