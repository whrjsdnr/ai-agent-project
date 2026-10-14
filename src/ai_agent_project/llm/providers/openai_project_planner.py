"""OpenAI Responses structured-output project milestone planner."""

import json

from pydantic import ValidationError

from ai_agent_project.agent.plan import ImplementationPlan
from ai_agent_project.agent.project import (
    ProjectPlan,
    ProjectPlanner,
    ProjectSpecification,
)
from ai_agent_project.agent.workspace import WorkspaceSnapshot
from ai_agent_project.llm.config import ProviderConfig
from ai_agent_project.llm.providers.openai import OpenAIAPIClient
from ai_agent_project.llm.providers.structured_schema import openai_strict_json_schema
from ai_agent_project.llm.runtime import ConfiguredOpenAIProvider

PROJECT_PLANNER_INSTRUCTIONS = """Create a project milestone plan from the supplied
project specification and implementation plan. Return only data matching the supplied
JSON schema.

Group the existing implementation tasks into meaningful development phases. Do not
invent task IDs or requirement IDs. Every implementation task must appear in exactly
one phase, and every requirement must be covered by at least one phase. Phase
dependencies must reference phases in this response and preserve dependency order.
Phases must be independently implementable and verifiable. Their acceptance criteria
must state what must be true before moving to the next phase. Prefer approximately two
to six phases for ordinary projects, but do not force a count.

The supplied implementation plan is authoritative: preserve it exactly in the output.
Use only workspace-relative paths supplied in the workspace snapshot. Return no prose
outside the structured output expected by the schema.
"""


class ProjectPlanningError(ValueError):
    """Raised when an OpenAI response cannot become a valid ProjectPlan."""


class OpenAIProjectPlanner(ConfiguredOpenAIProvider, ProjectPlanner):
    """Create a validated project phase plan with OpenAI structured output."""

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
        self,
        specification: ProjectSpecification,
        implementation_plan: ImplementationPlan,
        workspace: WorkspaceSnapshot | None = None,
    ) -> ProjectPlan:
        """Request phase groupings and validate all project traceability rules."""
        response = self._get_client().responses.create(
            model=self._model,
            instructions=PROJECT_PLANNER_INSTRUCTIONS,
            input=[
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "project": specification.model_dump(mode="json"),
                            "implementation_plan": implementation_plan.model_dump(
                                mode="json"
                            ),
                            "workspace": (
                                workspace.model_dump(mode="json")
                                if workspace is not None
                                else None
                            ),
                        },
                        ensure_ascii=False,
                    ),
                }
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "project_plan",
                    "schema": openai_strict_json_schema(ProjectPlan),
                    "strict": True,
                }
            },
        )
        output_text = getattr(response, "output_text", None)
        if not isinstance(output_text, str):
            raise ProjectPlanningError("OpenAI returned no project plan")

        try:
            raw_project_plan = json.loads(output_text)
        except json.JSONDecodeError as error:
            raise ProjectPlanningError(
                "OpenAI returned invalid project plan JSON"
            ) from error

        try:
            project_plan = ProjectPlan.model_validate(raw_project_plan)
            if project_plan.implementation_plan != implementation_plan:
                raise ValueError(
                    "OpenAI returned a project plan with a changed implementation plan"
                )
            return project_plan.validate_against(specification)
        except (ValidationError, ValueError) as error:
            raise ProjectPlanningError(
                "OpenAI returned a project plan that failed validation"
            ) from error
