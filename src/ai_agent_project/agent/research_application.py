"""Application-layer lifecycle and whole-snapshot storage for research runs."""

from typing import Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from ai_agent_project.agent.research import (
    ResearchDiscoveryReport,
    ResearchImplementationPackage,
    ResearchImplementationPlan,
    ResearchMetricAssessment,
    ResearchPaperMaterials,
    ResearchPaperMetricResult,
    ResearchPlanRevision,
    ResearchPlanRevisionState,
    ResearchRequest,
    ResearchResultAnalysis,
    ResearchResultSubmission,
    ResearchResultSynthesis,
    ResearchRun,
    ResearchStatus,
)
from ai_agent_project.agent.research_discovery import ResearchDiscoveryService
from ai_agent_project.agent.research_planning import (
    ResearchImplementationGenerator,
    ResearchImplementationPlanner,
    ResearchPaperMaterialsGenerator,
    ResearchPlanGenerator,
    ResearchResultAnalyzer,
    ResearchResultSynthesizer,
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
        result_synthesizer: ResearchResultSynthesizer | None = None,
        paper_materials_generator: ResearchPaperMaterialsGenerator | None = None,
    ) -> None:
        self._discovery_service = discovery_service
        self._store = store
        self._plan_generator = plan_generator
        self._implementation_planner = implementation_planner
        self._implementation_generator = implementation_generator
        self._result_analyzer = result_analyzer
        self._result_synthesizer = result_synthesizer
        self._paper_materials_generator = paper_materials_generator

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

    def generate_synthesis(self, research_run_id: str) -> StoredResearchRun:
        run = self._require_run(research_run_id)
        if run.status is not ResearchStatus.RESEARCH_RESULTS_ANALYZED:
            raise InvalidResearchStateError(
                "Research synthesis requires analyzed results"
            )
        if (
            self._result_synthesizer is None
            or run.plan_revision_state is None
            or run.implementation_plan is None
            or run.result_submission is None
            or run.result_analysis is None
        ):
            raise ResearchRunError("Research synthesis is not configured")
        try:
            payload = self._result_synthesizer.synthesize(
                self._selected_direction(run),
                run.plan_revision_state.active_plan,
                run.implementation_plan,
                run.result_submission,
                run.result_analysis,
            )
        except Exception as error:
            raise ResearchRunError("Research synthesis generation failed") from error
        synthesis = ResearchResultSynthesis(
            **payload.model_dump(),
            selected_direction_id=run.selected_direction_id,
            approved_plan_version=run.plan_revision_state.active_version,
            implementation_plan_version=run.implementation_plan.approved_plan_version,
        )
        self._validate_synthesis(run, synthesis)
        updated = run.model_copy(
            update={
                "status": ResearchStatus.RESEARCH_SYNTHESIS_READY,
                "result_synthesis": synthesis,
            }
        )
        self._store.replace(research_run_id, updated)
        return StoredResearchRun(id=research_run_id, research_run=updated)

    def get_synthesis(self, research_run_id: str) -> ResearchResultSynthesis:
        synthesis = self._require_run(research_run_id).result_synthesis
        if synthesis is None:
            raise InvalidResearchStateError("Research synthesis has not been generated")
        return synthesis

    def generate_paper_materials(self, research_run_id: str) -> StoredResearchRun:
        run = self._require_run(research_run_id)
        if run.status is not ResearchStatus.RESEARCH_SYNTHESIS_READY:
            raise InvalidResearchStateError(
                "Paper materials require completed research synthesis"
            )
        if (
            self._paper_materials_generator is None
            or run.plan_revision_state is None
            or run.implementation_plan is None
            or run.result_submission is None
            or run.result_analysis is None
            or run.result_synthesis is None
        ):
            raise ResearchRunError("Research paper materials are not configured")
        try:
            payload = self._paper_materials_generator.generate(
                self._selected_direction(run),
                run.report,
                run.plan_revision_state.active_plan,
                run.implementation_plan,
                run.result_submission,
                run.result_analysis,
                run.result_synthesis,
            )
        except Exception as error:
            raise ResearchRunError(
                "Research paper materials generation failed"
            ) from error
        unknown_key_metrics = sorted(
            set(payload.key_metric_ids)
            - {item.id for item in run.plan_revision_state.active_plan.metrics}
        )
        if unknown_key_metrics:
            raise ResearchRunError(
                "Research paper materials reference unknown metric IDs: "
                + ", ".join(unknown_key_metrics)
            )
        materials = ResearchPaperMaterials(
            **payload.model_dump(),
            selected_direction_id=run.selected_direction_id,
            approved_plan_version=run.plan_revision_state.active_version,
            implementation_plan_version=run.implementation_plan.approved_plan_version,
            key_results=self._paper_metric_results(run, payload.key_metric_ids),
        )
        self._validate_paper_materials(run, materials)
        updated = run.model_copy(
            update={
                "status": ResearchStatus.PAPER_MATERIALS_READY,
                "paper_materials": materials,
            }
        )
        self._store.replace(research_run_id, updated)
        return StoredResearchRun(id=research_run_id, research_run=updated)

    def get_paper_materials(self, research_run_id: str) -> ResearchPaperMaterials:
        materials = self._require_run(research_run_id).paper_materials
        if materials is None:
            raise InvalidResearchStateError(
                "Research paper materials have not been generated"
            )
        return materials

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
    def _validate_synthesis(
        run: ResearchRun, synthesis: ResearchResultSynthesis
    ) -> None:
        assert run.plan_revision_state is not None
        assert run.implementation_plan is not None
        assert run.result_analysis is not None
        objective_ids = {
            item.id for item in run.plan_revision_state.active_plan.objectives
        }
        task_ids = {item.task_id for item in run.implementation_plan.tasks}
        metric_ids = {item.id for item in run.plan_revision_state.active_plan.metrics}
        finding_ids = {item.finding_id for item in run.result_analysis.findings}
        evidence_refs = {
            *(
                f"metric:{item.metric_id}"
                for item in run.result_submission.metric_observations
            ),
            *(f"task:{item.task_id}" for item in run.result_submission.task_results),
            *(f"finding:{item.finding_id}" for item in run.result_analysis.findings),
        }
        conclusions = synthesis.objective_conclusions
        unknown_objectives = sorted(
            {item.objective_id for item in conclusions} - objective_ids
        )
        if unknown_objectives:
            raise ResearchRunError(
                "Research synthesis references unknown objective IDs: "
                + ", ".join(unknown_objectives)
            )
        referenced_evidence = {
            reference
            for conclusion in conclusions
            for reference in conclusion.evidence_refs
        }
        claims = (
            *synthesis.major_findings,
            *synthesis.inconclusive_findings,
            *synthesis.negative_findings,
            *synthesis.research_contributions,
        )
        unknown_claim_objectives = sorted(
            {
                reference
                for claim in claims
                for reference in claim.objective_ids
                if reference not in objective_ids
            }
        )
        if unknown_claim_objectives:
            raise ResearchRunError(
                "Research synthesis references unknown objective IDs: "
                + ", ".join(unknown_claim_objectives)
            )
        unknown_tasks = sorted(
            {
                reference
                for claim in claims
                for reference in claim.task_ids
                if reference not in task_ids
            }
        )
        if unknown_tasks:
            raise ResearchRunError(
                "Research synthesis references unknown task IDs: "
                + ", ".join(unknown_tasks)
            )
        unknown_metrics = sorted(
            {
                reference
                for claim in claims
                for reference in claim.metric_ids
                if reference not in metric_ids
            }
        )
        if unknown_metrics:
            raise ResearchRunError(
                "Research synthesis references unknown metric IDs: "
                + ", ".join(unknown_metrics)
            )
        unknown_findings = sorted(
            {
                reference
                for claim in claims
                for reference in claim.analysis_finding_ids
                if reference not in finding_ids
            }
        )
        if unknown_findings:
            raise ResearchRunError(
                "Research synthesis references unknown analysis finding IDs: "
                + ", ".join(unknown_findings)
            )
        referenced_evidence.update(
            reference for claim in claims for reference in claim.evidence_refs
        )
        unknown_evidence = sorted(referenced_evidence - evidence_refs)
        if unknown_evidence:
            raise ResearchRunError(
                "Research synthesis references unknown evidence: "
                + ", ".join(unknown_evidence)
            )

    @staticmethod
    def _paper_metric_results(
        run: ResearchRun, metric_ids: tuple[str, ...]
    ) -> tuple[ResearchPaperMetricResult, ...]:
        assert run.result_submission is not None
        observations = {
            item.metric_id: item for item in run.result_submission.metric_observations
        }
        missing_observations = sorted(set(metric_ids) - set(observations))
        if missing_observations:
            raise ResearchRunError(
                "Paper materials key results require submitted observations: "
                + ", ".join(missing_observations)
            )
        return tuple(
            ResearchPaperMetricResult(
                metric_id=metric_id,
                value=observations[metric_id].value,
                unit=observations[metric_id].unit,
                observation_status=observations[metric_id].status,
                notes=observations[metric_id].notes,
            )
            for metric_id in metric_ids
        )

    @staticmethod
    def _validate_paper_materials(
        run: ResearchRun, materials: ResearchPaperMaterials
    ) -> None:
        assert run.plan_revision_state is not None
        assert run.implementation_plan is not None
        assert run.result_analysis is not None
        assert run.result_synthesis is not None
        objective_ids = {
            item.id for item in run.plan_revision_state.active_plan.objectives
        }
        task_ids = {item.task_id for item in run.implementation_plan.tasks}
        metric_ids = {item.id for item in run.plan_revision_state.active_plan.metrics}
        source_ids = {item.id for item in run.report.sources}
        finding_ids = {item.finding_id for item in run.result_analysis.findings}
        synthesis_claim_ids = {
            item.claim_id
            for item in (
                *run.result_synthesis.major_findings,
                *run.result_synthesis.inconclusive_findings,
                *run.result_synthesis.negative_findings,
                *run.result_synthesis.research_contributions,
            )
        }
        synthesis_claims = {
            item.claim_id: item
            for item in (
                *run.result_synthesis.major_findings,
                *run.result_synthesis.inconclusive_findings,
                *run.result_synthesis.negative_findings,
                *run.result_synthesis.research_contributions,
            )
        }
        evidence_refs = {
            *(f"task:{item.task_id}" for item in run.result_submission.task_results),
            *(
                f"metric:{item.metric_id}"
                for item in run.result_submission.metric_observations
            ),
            *(f"finding:{item.finding_id}" for item in run.result_analysis.findings),
        }
        if not set(materials.citation_source_ids) <= source_ids:
            raise ResearchRunError(
                "Research paper materials reference unknown source IDs: "
                + ", ".join(sorted(set(materials.citation_source_ids) - source_ids))
            )
        if not set(materials.key_metric_ids) <= metric_ids:
            raise ResearchRunError(
                "Research paper materials reference unknown metric IDs: "
                + ", ".join(sorted(set(materials.key_metric_ids) - metric_ids))
            )
        claims = (
            *materials.contribution_candidates,
            *materials.usable_claims,
            *materials.prohibited_claims,
        )
        for claim in claims:
            if not set(claim.synthesis_claim_ids) <= synthesis_claim_ids:
                raise ResearchRunError(
                    "Research paper materials reference unknown synthesis claim IDs: "
                    + ", ".join(
                        sorted(set(claim.synthesis_claim_ids) - synthesis_claim_ids)
                    )
                )
            if not set(claim.objective_ids) <= objective_ids:
                raise ResearchRunError(
                    "Research paper materials reference unknown objective IDs: "
                    + ", ".join(sorted(set(claim.objective_ids) - objective_ids))
                )
            if not set(claim.task_ids) <= task_ids:
                raise ResearchRunError(
                    "Research paper materials reference unknown task IDs: "
                    + ", ".join(sorted(set(claim.task_ids) - task_ids))
                )
            if not set(claim.metric_ids) <= metric_ids:
                raise ResearchRunError(
                    "Research paper materials reference unknown metric IDs: "
                    + ", ".join(sorted(set(claim.metric_ids) - metric_ids))
                )
            if not set(claim.analysis_finding_ids) <= finding_ids:
                raise ResearchRunError(
                    "Research paper materials reference unknown analysis finding IDs: "
                    + ", ".join(sorted(set(claim.analysis_finding_ids) - finding_ids))
                )
            if not set(claim.evidence_refs) <= evidence_refs:
                raise ResearchRunError(
                    "Research paper materials reference unknown evidence refs: "
                    + ", ".join(sorted(set(claim.evidence_refs) - evidence_refs))
                )
            if claim.synthesis_claim_ids:
                allowed_transitions = {
                    "supported": {
                        "supported",
                        "partially_supported",
                        "inconclusive",
                        "unsupported",
                    },
                    "partially_supported": {
                        "partially_supported",
                        "inconclusive",
                        "unsupported",
                    },
                    "inconclusive": {"inconclusive", "unsupported"},
                    "unsupported": {"unsupported"},
                }
                if any(
                    claim.support_status.value
                    not in allowed_transitions[
                        synthesis_claims[item].support_status.value
                    ]
                    for item in claim.synthesis_claim_ids
                ):
                    raise ResearchRunError(
                        "Research paper materials cannot strengthen synthesis support"
                    )
        paper_claim_ids = {claim.claim_id for claim in claims}
        for suggestion in (*materials.table_suggestions, *materials.figure_suggestions):
            if not set(suggestion.paper_claim_ids) <= paper_claim_ids:
                raise ResearchRunError(
                    "Paper suggestion references unknown paper claim"
                )
            if not set(suggestion.metric_ids) <= metric_ids:
                raise ResearchRunError("Paper suggestion references unknown metric")
        for section in materials.section_materials:
            if not set(section.included_claim_ids) <= paper_claim_ids:
                raise ResearchRunError("Paper section references unknown paper claim")
            if not set(section.included_source_ids) <= source_ids:
                raise ResearchRunError("Paper section references unknown source")
            if not set(section.included_metric_ids) <= metric_ids:
                raise ResearchRunError("Paper section references unknown metric")

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
