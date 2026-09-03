"""Application-layer lifecycle and whole-snapshot storage for research runs."""

from typing import Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from ai_agent_project.agent.research import (
    ResearchDiscoveryReport,
    ResearchImplementationPackage,
    ResearchImplementationPlan,
    ResearchMetricAssessment,
    ResearchPlanRevision,
    ResearchPlanRevisionState,
    ResearchRequest,
    ResearchResultAnalysis,
    ResearchResultSubmission,
    ResearchRun,
    ResearchStatus,
)
from ai_agent_project.agent.research_discovery import ResearchDiscoveryService
from ai_agent_project.agent.research_planning import (
    ResearchImplementationGenerator,
    ResearchImplementationPlanner,
    ResearchPlanGenerator,
    ResearchResultAnalyzer,
)


class ResearchRunError(Exception):
    """Base error for provider-neutral research-run operations."""


class ResearchRunNotFoundError(ResearchRunError):
    """Raised when a requested research run is absent from storage."""


class ResearchRunAlreadyExistsError(ResearchRunError):
    """Raised when storage creation would overwrite a research run."""


class ResearchDirectionNotFoundError(ResearchRunError):
    """Raised when a direction ID is not part of the stored report."""


class InvalidResearchStateError(ResearchRunError):
    """Raised when a research lifecycle transition is not permitted."""


class ResearchResultsNotProvidedError(ResearchRunError):
    """Raised when analysis is requested without authoritative user results."""


class ResearchRunStore(Protocol):
    """Persist immutable research snapshots through whole replacement only."""

    def create(self, research_run_id: str, research_run: ResearchRun) -> None: ...

    def get(self, research_run_id: str) -> ResearchRun | None: ...

    def replace(self, research_run_id: str, research_run: ResearchRun) -> None: ...


class InMemoryResearchRunStore:
    """Small process-local store used by deterministic application tests."""

    def __init__(self) -> None:
        self._runs: dict[str, ResearchRun] = {}

    def create(self, research_run_id: str, research_run: ResearchRun) -> None:
        if research_run_id in self._runs:
            raise ResearchRunAlreadyExistsError(
                f"Research run already exists: {research_run_id}"
            )
        self._runs[research_run_id] = research_run

    def get(self, research_run_id: str) -> ResearchRun | None:
        return self._runs.get(research_run_id)

    def replace(self, research_run_id: str, research_run: ResearchRun) -> None:
        if research_run_id not in self._runs:
            raise ResearchRunNotFoundError(f"Research run not found: {research_run_id}")
        self._runs[research_run_id] = research_run


class StoredResearchRun(BaseModel):
    """Immutable application result pairing a stable ID with a run snapshot."""

    model_config = ConfigDict(frozen=True)

    id: str
    research_run: ResearchRun


class ResearchApplicationService:
    """Create, retrieve, and explicitly select directions for research discovery."""

    def __init__(
        self,
        discovery_service: ResearchDiscoveryService,
        store: ResearchRunStore,
        plan_generator: ResearchPlanGenerator | None = None,
        implementation_planner: ResearchImplementationPlanner | None = None,
        implementation_generator: ResearchImplementationGenerator | None = None,
        result_analyzer: ResearchResultAnalyzer | None = None,
    ) -> None:
        self._discovery_service = discovery_service
        self._store = store
        self._plan_generator = plan_generator
        self._implementation_planner = implementation_planner
        self._implementation_generator = implementation_generator
        self._result_analyzer = result_analyzer

    def create_research_run(
        self, topic: str, *, user_context: str | None = None
    ) -> StoredResearchRun:
        if not topic.strip():
            raise ResearchRunError("Research topic must not be blank")
        run = self._discovery_service.discover(
            ResearchRequest(topic=topic, user_context=user_context)
        )
        run_id = str(uuid4())
        self._store.create(run_id, run)
        return StoredResearchRun(id=run_id, research_run=run)

    def get_research_run(self, research_run_id: str) -> StoredResearchRun:
        return StoredResearchRun(
            id=research_run_id,
            research_run=self._require_run(research_run_id),
        )

    def get_research_report(self, research_run_id: str) -> ResearchDiscoveryReport:
        return self._require_run(research_run_id).report

    def get_research_directions(self, research_run_id: str):
        return self._require_run(research_run_id).report.directions

    def select_research_direction(
        self, research_run_id: str, direction_id: str
    ) -> StoredResearchRun:
        run = self._require_run(research_run_id)
        if run.status is not ResearchStatus.AWAITING_DIRECTION_SELECTION:
            raise InvalidResearchStateError(
                "Research direction selection is only allowed while awaiting selection"
            )
        if direction_id not in {direction.id for direction in run.report.directions}:
            raise ResearchDirectionNotFoundError(
                f"Research direction not found: {direction_id}"
            )
        updated = run.model_copy(
            update={
                "status": ResearchStatus.DIRECTION_SELECTED,
                "selected_direction_id": direction_id,
            }
        )
        self._store.replace(research_run_id, updated)
        return StoredResearchRun(id=research_run_id, research_run=updated)

    def generate_plan(self, research_run_id: str) -> StoredResearchRun:
        run = self._require_run(research_run_id)
        if run.status is not ResearchStatus.DIRECTION_SELECTED:
            raise InvalidResearchStateError(
                "Research plan generation requires a selected direction"
            )
        if self._plan_generator is None:
            raise ResearchRunError("Research plan generation is not configured")
        direction = self._selected_direction(run)
        plan = self._plan_generator.generate(run.request, direction, run.report)
        if plan.selected_direction_id != direction.id:
            raise ResearchRunError(
                "Generated research plan changed the selected direction"
            )
        updated = run.model_copy(
            update={
                "status": ResearchStatus.AWAITING_RESEARCH_PLAN_APPROVAL,
                "plan_revision_state": ResearchPlanRevisionState.from_plan(plan),
            }
        )
        self._store.replace(research_run_id, updated)
        return StoredResearchRun(id=research_run_id, research_run=updated)

    def get_plan(self, research_run_id: str) -> ResearchPlanRevisionState:
        state = self._require_run(research_run_id).plan_revision_state
        if state is None:
            raise InvalidResearchStateError("Research plan has not been generated")
        return state

    def revise_plan(self, research_run_id: str, note: str) -> StoredResearchRun:
        run = self._require_run(research_run_id)
        if run.status is not ResearchStatus.AWAITING_RESEARCH_PLAN_APPROVAL:
            raise InvalidResearchStateError(
                "Research plan revision is not allowed in this state"
            )
        if not note.strip():
            raise ResearchRunError("Research plan revision note must not be blank")
        if self._plan_generator is None or run.plan_revision_state is None:
            raise ResearchRunError("Research plan revision is not configured")
        direction = self._selected_direction(run)
        plan = self._plan_generator.generate(
            run.request, direction, run.report, revision_note=note
        )
        if plan.selected_direction_id != direction.id:
            raise ResearchRunError(
                "Generated research plan changed the selected direction"
            )
        revisions = (
            *run.plan_revision_state.revisions,
            ResearchPlanRevision(
                version=len(run.plan_revision_state.revisions) + 1, plan=plan, note=note
            ),
        )
        updated = run.model_copy(
            update={
                "plan_revision_state": ResearchPlanRevisionState(
                    active_version=len(revisions), revisions=revisions
                )
            }
        )
        self._store.replace(research_run_id, updated)
        return StoredResearchRun(id=research_run_id, research_run=updated)

    def approve_plan(self, research_run_id: str) -> StoredResearchRun:
        run = self._require_run(research_run_id)
        if (
            run.status is not ResearchStatus.AWAITING_RESEARCH_PLAN_APPROVAL
            or run.plan_revision_state is None
        ):
            raise InvalidResearchStateError(
                "Research plan approval is not allowed in this state"
            )
        updated = run.model_copy(
            update={
                "status": ResearchStatus.RESEARCH_PLAN_APPROVED,
                "plan_revision_state": run.plan_revision_state.model_copy(
                    update={"approved": True}
                ),
            }
        )
        self._store.replace(research_run_id, updated)
        return StoredResearchRun(id=research_run_id, research_run=updated)

    def generate_implementation_plan(self, research_run_id: str) -> StoredResearchRun:
        run = self._require_run(research_run_id)
        if run.status is not ResearchStatus.RESEARCH_PLAN_APPROVED:
            raise InvalidResearchStateError(
                "Implementation planning requires an approved research plan"
            )
        if self._implementation_planner is None or run.plan_revision_state is None:
            raise ResearchRunError("Research implementation planning is not configured")
        direction = self._selected_direction(run)
        approved_plan = run.plan_revision_state.active_plan
        implementation_plan = self._implementation_planner.plan(
            run.request,
            direction,
            approved_plan,
            run.plan_revision_state.active_version,
            run.report,
        )
        try:
            implementation_plan.validate_against(approved_plan)
        except ValueError as error:
            raise ResearchRunError(
                "Generated implementation plan is invalid"
            ) from error
        if (
            implementation_plan.approved_plan_version
            != run.plan_revision_state.active_version
        ):
            raise ResearchRunError("Generated implementation plan changed plan version")
        updated = run.model_copy(
            update={
                "status": ResearchStatus.IMPLEMENTATION_GENERATION_STARTED,
                "implementation_plan": implementation_plan,
            }
        )
        self._store.replace(research_run_id, updated)
        return StoredResearchRun(id=research_run_id, research_run=updated)

    def get_implementation_plan(
        self, research_run_id: str
    ) -> ResearchImplementationPlan:
        plan = self._require_run(research_run_id).implementation_plan
        if plan is None:
            raise InvalidResearchStateError(
                "Research implementation plan has not been generated"
            )
        return plan

    def generate_implementation_package(
        self, research_run_id: str
    ) -> StoredResearchRun:
        run = self._require_run(research_run_id)
        if run.status is not ResearchStatus.IMPLEMENTATION_GENERATION_STARTED:
            raise InvalidResearchStateError(
                "Implementation package generation requires an implementation plan"
            )
        if (
            self._implementation_generator is None
            or run.implementation_plan is None
            or run.plan_revision_state is None
        ):
            raise ResearchRunError(
                "Research implementation generation is not configured"
            )
        package = self._implementation_generator.generate(
            run.request,
            self._selected_direction(run),
            run.plan_revision_state.active_plan,
            run.implementation_plan,
            run.report,
        )
        try:
            package.validate_against(
                run.implementation_plan, run.plan_revision_state.active_plan
            )
        except ValueError as error:
            raise ResearchRunError(
                "Generated implementation package is invalid"
            ) from error
        updated = run.model_copy(
            update={
                "status": ResearchStatus.IMPLEMENTATION_PACKAGE_READY,
                "implementation_package": package,
            }
        )
        self._store.replace(research_run_id, updated)
        return StoredResearchRun(id=research_run_id, research_run=updated)

    def get_implementation_package(
        self, research_run_id: str
    ) -> ResearchImplementationPackage:
        package = self._require_run(research_run_id).implementation_package
        if package is None:
            raise InvalidResearchStateError(
                "Research implementation package has not been generated"
            )
        return package

    def prepare_result_submission(self, research_run_id: str) -> str:
        run = self._require_run(research_run_id)
        if run.status is ResearchStatus.IMPLEMENTATION_PACKAGE_READY:
            updated = run.model_copy(
                update={"status": ResearchStatus.AWAITING_USER_RESULTS}
            )
            self._store.replace(research_run_id, updated)
            run = updated
        if run.status is not ResearchStatus.AWAITING_USER_RESULTS:
            raise InvalidResearchStateError(
                "Result guidance requires a ready implementation package"
            )
        return self._result_guide(research_run_id, run)

    def submit_results(
        self, research_run_id: str, submission: ResearchResultSubmission
    ) -> StoredResearchRun:
        run = self._require_run(research_run_id)
        if run.status is not ResearchStatus.AWAITING_USER_RESULTS:
            raise InvalidResearchStateError(
                "Result submission is not allowed in this state"
            )
        self._validate_submission(research_run_id, run, submission)
        updated = run.model_copy(
            update={
                "status": ResearchStatus.RESEARCH_RESULTS_SUBMITTED,
                "result_submission": submission,
            }
        )
        self._store.replace(research_run_id, updated)
        return StoredResearchRun(id=research_run_id, research_run=updated)

    def get_results(self, research_run_id: str) -> ResearchResultSubmission:
        submission = self._require_run(research_run_id).result_submission
        if submission is None:
            raise ResearchResultsNotProvidedError(
                "Research results have not been submitted"
            )
        return submission

    def analyze_results(self, research_run_id: str) -> StoredResearchRun:
        run = self._require_run(research_run_id)
        if run.result_submission is None:
            raise ResearchResultsNotProvidedError(
                "Submit user execution results before requesting analysis"
            )
        if run.status is not ResearchStatus.RESEARCH_RESULTS_SUBMITTED:
            raise InvalidResearchStateError("Research results analysis is not allowed")
        if (
            self._result_analyzer is None
            or run.implementation_plan is None
            or run.plan_revision_state is None
        ):
            raise ResearchRunError("Research results analysis is not configured")
        payload = self._result_analyzer.analyze(
            run.plan_revision_state.active_plan,
            run.implementation_plan,
            run.result_submission,
        )
        analysis = self._compose_analysis(run, payload)
        updated = run.model_copy(
            update={
                "status": ResearchStatus.RESEARCH_RESULTS_ANALYZED,
                "result_analysis": analysis,
            }
        )
        self._store.replace(research_run_id, updated)
        return StoredResearchRun(id=research_run_id, research_run=updated)

    def get_result_analysis(self, research_run_id: str) -> ResearchResultAnalysis:
        analysis = self._require_run(research_run_id).result_analysis
        if analysis is None:
            raise InvalidResearchStateError("Research results have not been analyzed")
        return analysis

    @staticmethod
    def _result_guide(research_run_id: str, run: ResearchRun) -> str:
        version = (
            run.plan_revision_state.active_version if run.plan_revision_state else "-"
        )
        return "\n".join(
            (
                "# Research Execution Result",
                "",
                "## 1. Execution Metadata",
                f"- Research Run ID: {research_run_id}",
                f"- Approved Plan Version: {version}",
                "- Executed By:",
                "- Execution Date:",
                "- Environment:",
                "- OS:",
                "- Python Version:",
                "- GPU / Accelerator:",
                "- Framework:",
                "",
                "## 2. Executed Tasks",
                "- Task ID / Objective IDs / Methodology Step IDs / Metric IDs / Execution Status:",
                "",
                "## 3. Execution Command",
                "## 4. Configuration",
                "## 5. Results",
                "Metric ID | Value | Unit | Status | Notes",
                "## 6. Baseline Comparison",
                "## 7. Logs / Errors",
                "## 8. Generated Outputs",
                "## 9. User Observations",
                "## 10. Missing / Unexecuted Items",
                "",
                'Write "not executed" for experiments that were not run.',
                'Write "not measured" for metrics that were not measured.',
                "Do not estimate missing values or report predicted values as measured results.",
            )
        )

    @staticmethod
    def _validate_submission(
        research_run_id: str, run: ResearchRun, submission: ResearchResultSubmission
    ) -> None:
        if run.implementation_plan is None or run.plan_revision_state is None:
            raise InvalidResearchStateError(
                "Research implementation package is missing"
            )
        if submission.research_run_id != research_run_id:
            raise ResearchRunError(
                "Result submission references a different research run"
            )
        if submission.approved_plan_version != run.plan_revision_state.active_version:
            raise ResearchRunError(
                "Result submission references a different approved plan"
            )
        if (
            submission.implementation_plan_version
            != run.implementation_plan.approved_plan_version
        ):
            raise ResearchRunError(
                "Result submission references a different implementation plan"
            )
        tasks = {task.task_id: task for task in run.implementation_plan.tasks}
        objective_ids = {
            item.id for item in run.plan_revision_state.active_plan.objectives
        }
        methodology_ids = {
            item.id for item in run.plan_revision_state.active_plan.methodology
        }
        metric_ids = {item.id for item in run.plan_revision_state.active_plan.metrics}
        for result in submission.task_results:
            task = tasks.get(result.task_id)
            if task is None:
                raise ResearchRunError(
                    "Result submission references unknown implementation task"
                )
            if not set(result.objective_ids) <= objective_ids:
                raise ResearchRunError("Result submission references unknown objective")
            if not set(result.methodology_step_ids) <= methodology_ids:
                raise ResearchRunError(
                    "Result submission references unknown methodology"
                )
            if not set(result.metric_ids) <= metric_ids:
                raise ResearchRunError("Result submission references unknown metric")
            if result.execution_status.value == "not_executed" and result.metric_ids:
                raise ResearchRunError(
                    "Not-executed task results must not claim metrics"
                )
        observations = (
            *submission.metric_observations,
            *(
                item
                for baseline in submission.baseline_observations
                for item in baseline.metrics
            ),
        )
        if any(item.metric_id not in metric_ids for item in observations):
            raise ResearchRunError("Result submission references unknown metric")

    @staticmethod
    def _compose_analysis(run: ResearchRun, payload) -> ResearchResultAnalysis:
        assert run.result_submission is not None
        assert run.plan_revision_state is not None
        metric_values = {
            item.metric_id: item for item in run.result_submission.metric_observations
        }
        metric_ids = {item.id for item in run.plan_revision_state.active_plan.metrics}
        objective_ids = {
            item.id for item in run.plan_revision_state.active_plan.objectives
        }
        criterion_ids = {
            item.id for item in run.plan_revision_state.active_plan.success_criteria
        }
        evidence_refs = {
            *(
                f"metric:{item.metric_id}"
                for item in run.result_submission.metric_observations
            ),
            *(f"task:{item.task_id}" for item in run.result_submission.task_results),
        }
        if any(item.metric_id not in metric_ids for item in payload.metric_assessments):
            raise ResearchRunError("Result analysis references unknown metric")
        if any(
            item.objective_id not in objective_ids
            for item in payload.objective_assessments
        ):
            raise ResearchRunError("Result analysis references unknown objective")
        if any(
            item.criterion_id not in criterion_ids
            for item in payload.success_criterion_assessments
        ):
            raise ResearchRunError(
                "Result analysis references unknown success criterion"
            )
        all_refs = (
            *(item.evidence_refs for item in payload.metric_assessments),
            *(item.evidence_refs for item in payload.objective_assessments),
            *(item.evidence_refs for item in payload.findings),
        )
        if any(not set(refs) <= evidence_refs for refs in all_refs):
            raise ResearchRunError(
                "Result analysis references unknown empirical evidence"
            )
        assessments = tuple(
            ResearchMetricAssessment(
                metric_id=item.metric_id,
                observed_value=metric_values[item.metric_id].value
                if item.metric_id in metric_values
                else None,
                observation_status=metric_values[item.metric_id].status
                if item.metric_id in metric_values
                else "not_measured",
                assessment="not_measured"
                if item.metric_id not in metric_values
                or metric_values[item.metric_id].status.value == "not_measured"
                else item.assessment,
                rationale=item.rationale,
                evidence_refs=item.evidence_refs,
            )
            for item in payload.metric_assessments
        )
        return ResearchResultAnalysis(
            metric_assessments=assessments,
            success_criterion_assessments=payload.success_criterion_assessments,
            objective_assessments=payload.objective_assessments,
            findings=payload.findings,
            anomalies=payload.anomalies,
            limitations=payload.limitations,
            missing_evidence=payload.missing_evidence,
            recommended_next_steps=payload.recommended_next_steps,
        )

    @staticmethod
    def _selected_direction(run: ResearchRun):
        if run.selected_direction_id is None:
            raise InvalidResearchStateError("Research run has no selected direction")
        return next(
            direction
            for direction in run.report.directions
            if direction.id == run.selected_direction_id
        )

    def _require_run(self, research_run_id: str) -> ResearchRun:
        run = self._store.get(research_run_id)
        if run is None:
            raise ResearchRunNotFoundError(f"Research run not found: {research_run_id}")
        return run
