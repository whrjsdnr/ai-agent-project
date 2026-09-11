"""Synchronous facade composed from application services; no workflow engine.

Construct with the same services/readers used by the local application. Reads
only inspect snapshots. Mutations invoke one explicitly named application command.
"""

from pathlib import Path

from ai_agent_project.agent.checkpoint import CheckpointDecision
from ai_agent_project.agent.hybrid_coordination_application import (
    HybridCoordinationService,
)
from ai_agent_project.agent.project_action_application import (
    ApproveDeveloperPlanCommand,
    ApproveResearchPlanCommand,
    ContinueDeveloperCommand,
    ContinueResearcherCommand,
    DecideDeveloperCheckpointCommand,
    ProjectActionService,
    ProvideResearchResultsCommand,
    SelectResearchDirectionCommand,
)
from ai_agent_project.agent.project_artifact_application import ProjectArtifactService
from ai_agent_project.agent.project_artifact_export import ProjectArtifactExportService
from ai_agent_project.agent.project_artifact_rendering import (
    ProjectArtifactFormat,
    render_project_artifact,
)
from ai_agent_project.agent.project_developer_bootstrap_application import (
    ProjectDeveloperBootstrapService,
)
from ai_agent_project.agent.project_handoff import (
    SUPPORTED_HANDOFF_ARTIFACTS,
    ProjectHandoffPurpose,
)
from ai_agent_project.agent.project_handoff_application import ProjectHandoffService
from ai_agent_project.agent.project_session import ProjectPendingAction, ProjectSession
from ai_agent_project.agent.project_session_application import (
    DeveloperRunReader,
    ProjectSessionService,
    ResearchRunReader,
)
from ai_agent_project.agent.research import ResearchResultSubmission, WorkMode
from ai_agent_project.agent.upgrade import ProjectMode
from ai_agent_project.desktop.errors import (
    DesktopError,
    DesktopErrorCode,
    desktop_boundary,
)
from ai_agent_project.desktop.models import (
    DesktopArtifactSummary,
    DesktopArtifactView,
    DesktopConnectionView,
    DesktopDashboardView,
    DesktopDirectionView,
    DesktopHandoffSummary,
    DesktopHybridView,
    DesktopLaneView,
    DesktopPendingActionView,
    DesktopProjectSummary,
    DesktopProjectView,
    DesktopProviderView,
)
from ai_agent_project.llm.config import ProviderConfig, ProviderConfigService


def _pending(action: ProjectPendingAction) -> DesktopPendingActionView:
    name = action.action_type.value
    domain = (
        "developer"
        if "developer" in name
        else "researcher"
        if "research" in name
        else "project"
    )
    payload = {
        "confirm_mode": "work_mode_and_project_mode",
        "bind_developer_run": "run_id",
        "bind_research_run": "run_id",
        "select_research_direction": "direction_id",
        "provide_research_results": "research_result_submission",
    }.get(name)
    return DesktopPendingActionView(
        action_type=name,
        domain=domain,
        title="Review Developer checkpoint"
        if name == "continue_developer"
        and action.source_status == "awaiting_checkpoint"
        else name.replace("_", " ").capitalize(),
        description=action.message,
        requires_payload=payload is not None,
        payload_kind=payload,
    )


class DesktopService:
    def __init__(
        self,
        *,
        project_sessions: ProjectSessionService,
        actions: ProjectActionService,
        artifacts: ProjectArtifactService,
        handoffs: ProjectHandoffService,
        coordination: HybridCoordinationService,
        provider_config: ProviderConfigService,
        developer_reader: DeveloperRunReader,
        research_reader: ResearchRunReader,
        bootstrap: ProjectDeveloperBootstrapService | None = None,
        improvements=None,
        developer_application=None,
        research_application=None,
    ) -> None:
        from ai_agent_project.improvement.service import build_improvement_service

        self._improvements = improvements or build_improvement_service(
            developer_reader=developer_reader,
            researcher_reader=research_reader,
            projects=project_sessions,
        )
        self._sessions = project_sessions
        self._actions = actions
        self._artifacts = artifacts
        self._handoffs = handoffs
        self._coordination = coordination
        self._provider = provider_config
        self._developers = developer_reader
        self._researchers = research_reader
        self._bootstrap = bootstrap
        self._developer_application = developer_application
        self._research_application = research_application

    def _summary(self, project: ProjectSession) -> DesktopProjectSummary:
        return DesktopProjectSummary(
            project_id=project.project_id,
            display_title=project.title,
            status=project.status,
            work_mode=project.work_mode,
            project_mode=project.project_mode,
            created_at=project.created_at,
            developer_run_id=project.developer_run_id,
            researcher_run_id=project.research_run_id,
            pending_actions=tuple(
                _pending(a)
                for a in self._sessions.get_pending_actions(project.project_id)
            ),
        )

    @desktop_boundary
    def list_projects(self) -> tuple[DesktopProjectSummary, ...]:
        return tuple(
            self._summary(stored.project) for stored in self._sessions.list_projects()
        )

    @desktop_boundary
    def get_dashboard(self) -> DesktopDashboardView:
        projects = self.list_projects()
        return DesktopDashboardView(
            total_projects=len(projects),
            active_projects=sum(p.status == "active" for p in projects),
            completed_projects=sum(p.status == "completed" for p in projects),
            awaiting_user_action_count=sum(bool(p.pending_actions) for p in projects),
            recent_projects=projects[:10],
            provider=self.get_provider_config(),
        )

    def _lane(
        self,
        domain: str,
        run_id: str | None,
        actions: tuple[DesktopPendingActionView, ...],
    ) -> DesktopLaneView:
        pending = next((a for a in actions if a.domain == domain), None)
        status = phase = None
        details = {}
        if run_id is not None:
            reader = self._developers if domain == "developer" else self._researchers
            run = reader.get(run_id)
            if run is None:
                raise DesktopError(
                    DesktopErrorCode.NOT_FOUND, "Linked run was not found."
                )
            if domain == "developer":
                status = run.execution_state.status.value
                phase = run.execution_state.current_phase_id
            else:
                status = run.status.value
                phase = status
                details = {
                    "selected_direction": run.selected_direction_id,
                    "directions": tuple(
                        DesktopDirectionView(
                            direction_id=d.id,
                            title=d.title,
                            question=d.research_question,
                        )
                        for d in run.report.directions
                    ),
                    "approved_plan_version": run.plan_revision_state.active_version
                    if run.plan_revision_state
                    else None,
                    "implementation_plan_version": run.implementation_plan.approved_plan_version
                    if run.implementation_plan
                    else None,
                    "result_state": "Provided"
                    if run.result_submission
                    else "Not provided",
                    "synthesis_state": "Materials available"
                    if run.paper_materials
                    else "Synthesis available"
                    if run.result_synthesis
                    else "Not generated",
                }
        return DesktopLaneView(
            **details,
            domain=domain,
            bound=run_id is not None,
            run_id=run_id,
            status=status,
            phase=phase,
            pending_action=pending,
            available_actions=() if pending is None else (pending.action_type,),
        )

    @desktop_boundary
    def get_project_view(self, project_id: str) -> DesktopProjectView:
        project = self._sessions.get_project(project_id).project
        summary = self._summary(project)
        developer = researcher = hybrid = None
        if project.work_mode in {WorkMode.DEVELOPER, WorkMode.HYBRID}:
            developer = self._lane(
                "developer", project.developer_run_id, summary.pending_actions
            )
        if project.work_mode in {WorkMode.RESEARCHER, WorkMode.HYBRID}:
            researcher = self._lane(
                "researcher", project.research_run_id, summary.pending_actions
            )
        if project.work_mode is WorkMode.HYBRID:
            coordination = self._coordination.get_coordination(project_id)
            hybrid = DesktopHybridView(
                both_workflows_terminal=coordination.both_workflows_terminal,
                actionable_actions=tuple(
                    _pending(a) for a in coordination.actionable_actions
                ),
            )
        return DesktopProjectView(
            project=summary,
            proposed_work_mode=project.mode_proposal.proposed_work_mode,
            proposed_project_mode=project.mode_proposal.proposed_project_mode,
            developer=developer,
            researcher=researcher,
            hybrid=hybrid,
            artifacts=self.list_project_artifacts(project_id),
            handoffs=self.list_handoffs(project_id) if hybrid is not None else (),
        )

    @desktop_boundary
    def list_project_artifacts(
        self, project_id: str
    ) -> tuple[DesktopArtifactSummary, ...]:
        return tuple(
            DesktopArtifactSummary(**d.model_dump())
            for d in self._artifacts.list_artifacts(project_id).artifacts
        )

    @desktop_boundary
    def get_artifact_view(
        self,
        project_id: str,
        artifact_id: str,
        artifact_format: ProjectArtifactFormat = ProjectArtifactFormat.JSON,
    ) -> DesktopArtifactView:
        view = self._artifacts.get_artifact(project_id, artifact_id)
        return DesktopArtifactView(
            summary=DesktopArtifactSummary(**view.descriptor.model_dump()),
            format=artifact_format,
            content=render_project_artifact(view, artifact_format),
        )

    @desktop_boundary
    def list_handoffs(self, project_id: str) -> tuple[DesktopHandoffSummary, ...]:
        project = self._sessions.get_project(project_id).project
        return tuple(
            DesktopHandoffSummary(
                bootstrap_available=(
                    self._bootstrap is not None
                    and project.status == "active"
                    and project.work_mode == WorkMode.HYBRID
                    and project.project_mode == ProjectMode.NEW
                    and project.developer_run_id is None
                    and project.research_run_id is not None
                    and v.status == "available"
                ),
                handoff_id=v.handoff.handoff_id,
                source_domain=v.handoff.source_domain,
                artifact_id=v.handoff.artifact_id,
                artifact_type=v.source_artifact.artifact_type
                if v.source_artifact
                else None,
                purpose=v.handoff.purpose,
                created_at=v.handoff.created_at,
                status=v.status,
            )
            for v in self._handoffs.list_handoffs(project_id).handoffs
        )

    @desktop_boundary
    def get_provider_config(self) -> DesktopProviderView:
        config = self._provider.resolve()
        return DesktopProviderView(
            provider_type=config.provider_type,
            base_url=config.base_url,
            model=config.model,
            timeout_seconds=config.timeout_seconds,
            credential_configured=config.api_key is not None,
        )

    @desktop_boundary
    def save_provider_config(self, config: ProviderConfig) -> None:
        """Persist Phase 6A non-secret settings; credentials remain runtime/env only."""
        self._provider.save(config)

    @desktop_boundary
    def test_provider_connection(
        self, config: ProviderConfig | None = None
    ) -> DesktopConnectionView:
        result = self._provider.test_connection(config)
        return DesktopConnectionView(success=result.success, message=result.message)

    @desktop_boundary
    def create_project(self, request: str, *, title: str | None = None) -> str:
        return self._sessions.create_project_request(request, title=title).id

    @desktop_boundary
    def confirm_project_mode(
        self, project_id: str, work_mode: WorkMode, project_mode: ProjectMode
    ) -> None:
        self._sessions.confirm_project_mode(project_id, work_mode, project_mode)

    @desktop_boundary
    def bind_developer_run(self, project_id: str, run_id: str) -> None:
        self._sessions.bind_developer_run(project_id, run_id)

    @desktop_boundary
    def bind_research_run(self, project_id: str, run_id: str) -> None:
        self._sessions.bind_research_run(project_id, run_id)

    @desktop_boundary
    def complete_project(self, project_id: str) -> None:
        self._sessions.complete_project(project_id)

    @desktop_boundary
    def approve_developer_plan(self, project_id: str) -> None:
        self._actions.approve_developer_plan(
            ApproveDeveloperPlanCommand(project_id=project_id)
        )

    @desktop_boundary
    def continue_developer(self, project_id: str) -> None:
        self._actions.continue_developer(
            ContinueDeveloperCommand(project_id=project_id)
        )

    @desktop_boundary
    def decide_developer_checkpoint(
        self, project_id: str, decision: CheckpointDecision, note: str | None = None
    ) -> None:
        self._actions.decide_developer_checkpoint(
            DecideDeveloperCheckpointCommand(
                project_id=project_id, decision=decision, note=note
            )
        )

    @desktop_boundary
    def select_research_direction(self, project_id: str, direction_id: str) -> None:
        self._actions.select_research_direction(
            SelectResearchDirectionCommand(
                project_id=project_id, direction_id=direction_id
            )
        )

    @desktop_boundary
    def approve_research_plan(self, project_id: str) -> None:
        self._actions.approve_research_plan(
            ApproveResearchPlanCommand(project_id=project_id)
        )

    @desktop_boundary
    def provide_research_results(
        self, project_id: str, submission: ResearchResultSubmission
    ) -> None:
        self._actions.provide_research_results(
            ProvideResearchResultsCommand(project_id=project_id, submission=submission)
        )

    @desktop_boundary
    def continue_researcher(self, project_id: str) -> None:
        self._actions.continue_researcher(
            ContinueResearcherCommand(project_id=project_id)
        )

    @desktop_boundary
    def create_handoff(
        self,
        project_id: str,
        artifact_id: str,
        purpose: ProjectHandoffPurpose = ProjectHandoffPurpose.DEVELOPER_BOOTSTRAP_CONTEXT,
    ) -> str:
        return self._handoffs.create(project_id, artifact_id, purpose).handoff_id

    @desktop_boundary
    def bootstrap_developer_from_handoff(
        self, project_id: str, handoff_id: str, request: str
    ) -> str:
        if self._bootstrap is None:
            raise DesktopError(
                DesktopErrorCode.CONFIGURATION_ERROR,
                "Developer bootstrap service is not configured.",
            )
        from ai_agent_project.improvement.context import project_context

        with project_context(project_id):
            return self._bootstrap.bootstrap(
                project_id, handoff_id, request
            ).developer_run_id

    @desktop_boundary
    def create_developer_run(self, project_id: str) -> str:
        """Create only; binding is a separate explicit command."""
        project = self._sessions.get_project(project_id).project
        if self._developer_application is None or project.work_mode not in {
            WorkMode.DEVELOPER,
            WorkMode.HYBRID,
        }:
            raise DesktopError(
                DesktopErrorCode.INVALID_STATE,
                "Confirm a Developer or Hybrid mode first.",
            )
        from ai_agent_project.improvement.context import project_context

        with project_context(project_id):
            if project.project_mode == ProjectMode.UPGRADE:
                return self._developer_application.create_upgrade_project(
                    project.original_request
                ).id
            return self._developer_application.create_project(
                project.original_request
            ).id

    @desktop_boundary
    def create_research_run(self, project_id: str) -> str:
        """Discover only; selection and binding remain explicit."""
        project = self._sessions.get_project(project_id).project
        if self._research_application is None or project.work_mode not in {
            WorkMode.RESEARCHER,
            WorkMode.HYBRID,
        }:
            raise DesktopError(
                DesktopErrorCode.INVALID_STATE,
                "Confirm a Researcher or Hybrid mode first.",
            )
        from ai_agent_project.improvement.context import project_context

        with project_context(project_id):
            return self._research_application.create_research_run(
                project.original_request
            ).id

    @desktop_boundary
    def export_artifact(
        self, project_id: str, artifact_id: str, destination: Path
    ) -> None:
        """Use existing ownership-checked, no-overwrite, no-symlink export."""
        ProjectArtifactExportService(self._artifacts).export_artifact(
            project_id, artifact_id, ProjectArtifactFormat.JSON, destination
        )

    @desktop_boundary
    def can_create_handoff(self, project_id: str, artifact_id: str) -> bool:
        project = self._sessions.get_project(project_id).project
        artifact = self._artifacts.get_artifact(project_id, artifact_id)
        return (
            project.work_mode == WorkMode.HYBRID
            and artifact.descriptor.artifact_type in SUPPORTED_HANDOFF_ARTIFACTS
        )

    @desktop_boundary
    def get_improvement_overview(self):
        return self._improvements.overview()

    @desktop_boundary
    def list_improvement_candidates(self):
        return self._improvements.list_candidates()

    @desktop_boundary
    def list_improvement_rules(self):
        return self._improvements.list_rules()

    @desktop_boundary
    def get_improvement_candidate(self, identity):
        return self._improvements.get_candidate(identity)

    @desktop_boundary
    def get_improvement_rule(self, identity):
        return self._improvements.get_rule(identity)

    @desktop_boundary
    def evaluate_developer_run(self, run_id):
        return self._improvements.evaluate("developer", run_id)

    @desktop_boundary
    def evaluate_researcher_run(self, run_id):
        return self._improvements.evaluate("researcher", run_id)

    @desktop_boundary
    def approve_improvement_candidate(self, identity, scope=None):
        return self._improvements.approve_candidate(identity, scope)

    @desktop_boundary
    def reject_improvement_candidate(self, identity):
        self._improvements.reject_candidate(identity)

    @desktop_boundary
    def enable_improvement_rule(self, identity):
        self._improvements.set_enabled(identity, True)

    @desktop_boundary
    def disable_improvement_rule(self, identity):
        self._improvements.set_enabled(identity, False)

    @desktop_boundary
    def submit_improvement_feedback(self, target_type, target_id, rating, text=""):
        return self._improvements.submit_feedback(target_type, target_id, rating, text)

    @desktop_boundary
    def get_improvement_impact(self, identity):
        return self._improvements.impact(identity)

    @desktop_boundary
    def get_improvement_conflicts(self, identity):
        return self._improvements.conflicts(identity)
