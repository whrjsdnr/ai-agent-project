"""OpenAI structured-output provider for pre-execution project plan revisions."""

import json

from pydantic import ValidationError

from ai_agent_project.agent.plan_revision import ProjectPlanReviser
from ai_agent_project.agent.project import ProjectPlan, ProjectSpecification
from ai_agent_project.agent.workspace import WorkspaceSnapshot
from ai_agent_project.llm.config import ProviderConfig
from ai_agent_project.llm.providers.openai import OpenAIAPIClient
from ai_agent_project.llm.providers.structured_schema import openai_strict_json_schema
from ai_agent_project.llm.runtime import ConfiguredOpenAIProvider

PROJECT_PLAN_REVISION_INSTRUCTIONS = """Revise the supplied project plan according
to explicit user feedback. Return only data matching the supplied JSON schema.

Reorganize phases only. Preserve the supplied ImplementationPlan exactly: do not add,
remove, or alter implementation tasks. Do not invent requirement IDs or task IDs.
Every implementation task must remain assigned exactly once, every requirement must
remain covered, and phase dependencies must remain valid and acyclic. You may regroup
tasks, reorder valid phases, revise phase titles, objectives, acceptance criteria, and
dependencies. Return only the structured ProjectPlan output.
"""


class ProjectPlanRevisionError(ValueError):
    """Raised when OpenAI output cannot become a valid project plan revision."""


class OpenAIProjectPlanReviser(ConfiguredOpenAIProvider, ProjectPlanReviser):
    """Revise project phases while preserving the current implementation plan."""

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

    def revise(
        self,
        specification: ProjectSpecification,
        current_plan: ProjectPlan,
        feedback: str,
        workspace: WorkspaceSnapshot | None = None,
    ) -> ProjectPlan:
        """Request a structured regrouping and validate its strict invariants."""
        response = self._get_client().responses.create(
            model=self._model,
            instructions=PROJECT_PLAN_REVISION_INSTRUCTIONS,
            input=[
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "project": specification.model_dump(mode="json"),
                            "current_plan": current_plan.model_dump(mode="json"),
                            "feedback": feedback,
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
                    "name": "project_plan_revision",
                    "schema": openai_strict_json_schema(ProjectPlan),
                    "strict": True,
                }
            },
        )
        output_text = getattr(response, "output_text", None)
        if not isinstance(output_text, str):
            raise ProjectPlanRevisionError("OpenAI returned no revised project plan")
        try:
            raw_plan = json.loads(output_text)
            revised_plan = ProjectPlan.model_validate(raw_plan)
            if revised_plan.implementation_plan != current_plan.implementation_plan:
                raise ValueError("Revised plan changed the implementation plan")
            return revised_plan.validate_against(specification)
        except json.JSONDecodeError as error:
            raise ProjectPlanRevisionError(
                "OpenAI returned invalid revised project plan JSON"
            ) from error
        except (ValidationError, ValueError) as error:
            raise ProjectPlanRevisionError(
                "OpenAI returned a revised project plan that failed validation"
            ) from error
