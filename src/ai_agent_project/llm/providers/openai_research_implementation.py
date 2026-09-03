"""Strict, non-executing OpenAI providers for research implementation artifacts."""

import json
import os

from pydantic import ValidationError

from ai_agent_project.agent.research import (
    ResearchDirection,
    ResearchDiscoveryReport,
    ResearchGeneratedArtifact,
    ResearchImplementationPackage,
    ResearchImplementationPackagePayload,
    ResearchImplementationPlan,
    ResearchPlan,
    ResearchRequest,
)
from ai_agent_project.agent.research_planning import (
    ResearchImplementationGenerator,
    ResearchImplementationPlanner,
)
from ai_agent_project.llm.providers.openai import DEFAULT_MODEL, OpenAIAPIClient
from ai_agent_project.llm.providers.structured_schema import openai_strict_json_schema


class ResearchImplementationGenerationError(ValueError):
    """Raised when strict implementation-generation output is invalid."""


class _OpenAIResearchImplementationBase:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        client: OpenAIAPIClient | None = None,
        request_timeout_seconds: float = 90.0,
    ) -> None:
        if request_timeout_seconds <= 0:
            raise ValueError("Research implementation request timeout must be positive")
        self._model = model or os.getenv("OPENAI_MODEL", DEFAULT_MODEL)
        self._api_key = api_key or os.getenv("OPENAI_API_KEY")
        self._client = client
        self._request_timeout_seconds = request_timeout_seconds

    def _create(self, *, instructions: str, payload: dict[str, object], schema: type):
        response = self._get_client().responses.create(
            model=self._model,
            instructions=instructions,
            input=[{"role": "user", "content": json.dumps(payload)}],
            text={
                "format": {
                    "type": "json_schema",
                    "name": schema.__name__.lower(),
                    "schema": openai_strict_json_schema(schema),
                    "strict": True,
                }
            },
        )
        output = getattr(response, "output_text", None)
        if not isinstance(output, str):
            raise ResearchImplementationGenerationError(
                "OpenAI implementation provider returned no output"
            )
        try:
            return schema.model_validate(json.loads(output))
        except (json.JSONDecodeError, ValidationError) as error:
            raise ResearchImplementationGenerationError(
                "OpenAI implementation provider returned invalid output"
            ) from error

    def _get_client(self) -> OpenAIAPIClient:
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise ValueError("OPENAI_API_KEY must be configured")
        from openai import OpenAI

        self._client = OpenAI(
            api_key=self._api_key, timeout=self._request_timeout_seconds
        )
        return self._client


class OpenAIResearchImplementationPlanner(
    _OpenAIResearchImplementationBase, ResearchImplementationPlanner
):
    """Generate only a traceable artifact plan, never execution instructions."""

    def plan(
        self,
        request: ResearchRequest,
        direction: ResearchDirection,
        approved_plan: ResearchPlan,
        approved_plan_version: int,
        report: ResearchDiscoveryReport,
    ) -> ResearchImplementationPlan:
        result = self._create(
            instructions=(
                "Produce a generated-only research implementation plan. Do not execute, "
                "run, install, train, or validate anything. Preserve the supplied selected "
                "direction and approved plan version exactly. Use only approved objective, "
                "methodology, and metric IDs. Artifact paths must be safe relative paths."
            ),
            payload={
                "request": request.model_dump(mode="json"),
                "selected_direction": direction.model_dump(mode="json"),
                "approved_plan": approved_plan.model_dump(mode="json"),
                "approved_plan_version": approved_plan_version,
                "report": report.model_dump(mode="json"),
            },
            schema=ResearchImplementationPlan,
        )
        if result.selected_direction_id != direction.id:
            raise ResearchImplementationGenerationError(
                "OpenAI implementation plan changed the selected direction"
            )
        if result.approved_plan_version != approved_plan_version:
            raise ResearchImplementationGenerationError(
                "OpenAI implementation plan changed the approved plan version"
            )
        try:
            result.validate_against(approved_plan)
        except ValueError as error:
            raise ResearchImplementationGenerationError(
                "OpenAI implementation plan has invalid approved-plan references"
            ) from error
        return result


class OpenAIResearchImplementationGenerator(
    _OpenAIResearchImplementationBase, ResearchImplementationGenerator
):
    """Generate package text only; artifacts remain persisted metadata."""

    def generate(
        self,
        request: ResearchRequest,
        direction: ResearchDirection,
        approved_plan: ResearchPlan,
        implementation_plan: ResearchImplementationPlan,
        report: ResearchDiscoveryReport,
    ) -> ResearchImplementationPackage:
        payload = self._create(
            instructions=(
                "Generate a research implementation package as text only. Never execute code, "
                "shell commands, package installation, training, evaluation, or remote work. "
                "The supplied implementation plan is immutable authoritative context: do not "
                "reproduce or modify it. Generate only package payload content. Generate artifacts "
                "only for declared relative artifact paths and task IDs. Use configurable paths and "
                "environment assumptions; artifacts are generated, not executed."
            ),
            payload={
                "request": request.model_dump(mode="json"),
                "selected_direction": direction.model_dump(mode="json"),
                "approved_plan": approved_plan.model_dump(mode="json"),
                "implementation_plan": implementation_plan.model_dump(mode="json"),
                "report": report.model_dump(mode="json"),
            },
            schema=ResearchImplementationPackagePayload,
        )
        tasks = {task.task_id: task for task in implementation_plan.tasks}
        artifacts: list[ResearchGeneratedArtifact] = []
        for index, artifact in enumerate(payload.artifacts, start=1):
            task = tasks.get(artifact.task_id)
            if task is None:
                raise ResearchImplementationGenerationError(
                    "OpenAI implementation package references an unknown task"
                )
            artifacts.append(
                ResearchGeneratedArtifact(
                    artifact_id=f"ART-{index}",
                    task_id=artifact.task_id,
                    relative_path=artifact.relative_path,
                    artifact_type=artifact.artifact_type,
                    content=artifact.content,
                    objective_ids=task.objective_ids,
                    methodology_step_ids=task.methodology_step_ids,
                    metric_ids=task.metric_ids,
                )
            )
        result = ResearchImplementationPackage(
            implementation_plan=implementation_plan,
            artifacts=tuple(artifacts),
            execution_guide=payload.execution_guide,
            environment_assumptions=payload.environment_assumptions,
            unresolved_user_inputs=payload.unresolved_user_inputs,
            warnings=payload.warnings,
            generated_not_executed=True,
        )
        try:
            result.validate_against(implementation_plan, approved_plan)
        except ValueError as error:
            raise ResearchImplementationGenerationError(
                "OpenAI implementation package has invalid traceability"
            ) from error
        return result
