"""OpenAI structured-output provider for pre-execution project plan revisions."""

import json
import os

from pydantic import ValidationError

from ai_agent_project.agent.plan_revision import ProjectPlanReviser
from ai_agent_project.agent.project import ProjectPlan, ProjectSpecification
from ai_agent_project.agent.workspace import WorkspaceSnapshot
from ai_agent_project.llm.providers.openai import DEFAULT_MODEL, OpenAIAPIClient
from ai_agent_project.llm.providers.structured_schema import openai_strict_json_schema

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


class OpenAIProjectPlanReviser(ProjectPlanReviser):
    """Revise project phases while preserving the current implementation plan."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        client: OpenAIAPIClient | None = None,
    ) -> None:
        self._model = model or os.getenv("OPENAI_MODEL", DEFAULT_MODEL)
        self._client = client
        self._api_key = api_key or os.getenv("OPENAI_API_KEY")

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

    def _get_client(self) -> OpenAIAPIClient:
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise ValueError("OPENAI_API_KEY must be configured")
        from openai import OpenAI

        self._client = OpenAI(api_key=self._api_key)
        return self._client
