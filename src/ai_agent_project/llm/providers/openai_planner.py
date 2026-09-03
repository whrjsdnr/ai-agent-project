"""OpenAI Responses structured-output implementation planner."""

import json
import os

from pydantic import ValidationError

from ai_agent_project.agent.plan import (
    IMPLEMENTATION_PLANNER_INSTRUCTIONS,
    ImplementationPlan,
    ImplementationPlanner,
    ImplementationPlanValidationError,
)
from ai_agent_project.agent.specification import Specification
from ai_agent_project.agent.workspace import WorkspaceSnapshot
from ai_agent_project.llm.providers.openai import (
    DEFAULT_MODEL,
    OpenAIAPIClient,
)
from ai_agent_project.llm.providers.structured_schema import openai_strict_json_schema


class ImplementationPlanningError(ValueError):
    """Raised when an OpenAI response cannot become a valid implementation plan."""


class OpenAIImplementationPlanner(ImplementationPlanner):
    """Create validated implementation plans with OpenAI structured output."""

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

    def plan(
        self,
        specification: Specification,
        workspace: WorkspaceSnapshot | None = None,
    ) -> ImplementationPlan:
        """Request an implementation plan and validate it against the specification."""
        response = self._get_client().responses.create(
            model=self._model,
            instructions=IMPLEMENTATION_PLANNER_INSTRUCTIONS,
            input=[
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "specification": specification.model_dump(mode="json"),
                            "workspace_files": workspace.files if workspace else [],
                            "workspace_truncated": workspace.truncated
                            if workspace
                            else False,
                        },
                        ensure_ascii=False,
                    )
                    + "\n\nAuthoritative requirement IDs (copy these verbatim and use no others): "
                    + ", ".join(
                        requirement.id for requirement in specification.requirements
                    )
                    + "\nEvery task must have one or more non-empty requirement_ids copied verbatim from that list. Never use an empty string as an infrastructure placeholder; infrastructure work must reference the requirement it supports.\nExisting workspace files are the source of truth. Put relevant existing files in files_to_inspect; put files to change or create in files_to_modify. Do not use absolute paths, .. paths, or .env files.",
                }
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "implementation_plan",
                    "schema": openai_strict_json_schema(ImplementationPlan),
                    "strict": True,
                }
            },
        )
        output_text = getattr(response, "output_text", None)
        if not isinstance(output_text, str):
            raise ImplementationPlanningError("OpenAI returned no implementation plan")

        try:
            parsed = json.loads(output_text)
        except json.JSONDecodeError as error:
            raise ImplementationPlanningError(
                "OpenAI returned invalid implementation plan JSON"
            ) from error

        try:
            plan = ImplementationPlan.model_validate(parsed)
            return plan.validate_traceability(specification)
        except (ImplementationPlanValidationError, ValidationError) as error:
            raise ImplementationPlanningError(
                "OpenAI returned an implementation plan that failed validation: "
                f"{_validation_error_detail(error)}; "
                f"{_traceability_context(specification, parsed)}"
            ) from error

    def _get_client(self) -> OpenAIAPIClient:
        """Create the SDK client only when planning needs it."""
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise ValueError("OPENAI_API_KEY must be configured")

        from openai import OpenAI

        self._client = OpenAI(api_key=self._api_key)
        return self._client


def _validation_error_detail(
    error: ImplementationPlanValidationError | ValidationError,
) -> str:
    """Expose safe, compact model-validation context without echoing model input."""
    if isinstance(error, ImplementationPlanValidationError):
        return str(error)
    details = []
    for item in error.errors(include_url=False):
        location = ".".join(str(part) for part in item["loc"]) or "plan"
        details.append(f"{location}: {item['msg']}")
    return "; ".join(details)


def _traceability_context(specification: Specification, parsed: object) -> str:
    """Render IDs only, so provider diagnostics remain useful and non-sensitive."""
    generated: list[str] = []
    if isinstance(parsed, dict) and isinstance(parsed.get("tasks"), list):
        for task in parsed["tasks"]:
            if isinstance(task, dict) and isinstance(task.get("requirement_ids"), list):
                generated.extend(
                    _display_id(value) for value in task["requirement_ids"]
                )
    return (
        "authoritative_requirement_ids="
        f"{[item.id for item in specification.requirements]!r}; "
        f"generated_task_requirement_ids={generated!r}"
    )


def _display_id(value: object) -> str:
    if not isinstance(value, str):
        return f"<{type(value).__name__}>"
    if not value:
        return "<empty>"
    if not value.strip():
        return "<whitespace>"
    return value
