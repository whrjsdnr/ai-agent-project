"""OpenAI structured-output provider for Research Discovery questions."""

import json

from pydantic import ValidationError

from ai_agent_project.agent.research import (
    ResearchQuestion,
    ResearchQuestionSet,
    ResearchRequest,
)
from ai_agent_project.agent.research_planning import ResearchQuestionPlanner
from ai_agent_project.agent.workspace import WorkspaceSnapshot
from ai_agent_project.llm.config import ProviderConfig
from ai_agent_project.llm.providers.openai import OpenAIAPIClient
from ai_agent_project.llm.providers.structured_schema import openai_strict_json_schema
from ai_agent_project.llm.runtime import ConfiguredOpenAIProvider

_INSTRUCTIONS = (
    "Generate concise research questions, not search-engine queries. Cover established "
    "approaches, methods, datasets/metrics when relevant, recurring limitations, unresolved "
    "problems, and feasibility. Use nonblank unique IDs and only workspace, external, or mixed "
    "source_scope. Return only the structured question set."
)


class ResearchQuestionPlanningError(ValueError):
    """Raised when question-planning structured output is invalid."""


class OpenAIResearchQuestionPlanner(ConfiguredOpenAIProvider, ResearchQuestionPlanner):
    def __init__(
        self,
        *,
        config: ProviderConfig | None = None,
        request_timeout_seconds: float | None = None,
        api_key: str | None = None,
        model: str | None = None,
        client: OpenAIAPIClient | None = None,
    ) -> None:
        self._configure(
            config=config,
            api_key=api_key,
            model=model,
            client=client,
            timeout_seconds=request_timeout_seconds,
        )

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
