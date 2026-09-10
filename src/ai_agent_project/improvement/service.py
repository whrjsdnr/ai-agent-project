"""Trusted evidence, approval, deterministic retrieval and descriptive outcomes."""

import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

from ai_agent_project.improvement.context import (
    MAX_CONTEXT_BYTES,
    MAX_RULES,
    ContextRule,
    ImprovementContext,
    normalize,
    validate_guidance,
)
from ai_agent_project.improvement.errors import ImprovementError
from ai_agent_project.improvement.file_store import FileImprovementStore
from ai_agent_project.improvement.models import (
    CandidateProposal,
    Domain,
    EvaluationProposal,
    EvidenceFact,
    ImprovementApplication,
    ImprovementCandidate,
    ImprovementEvaluation,
    ImprovementEvent,
    ImprovementEvidence,
    ImprovementFeedback,
    ImprovementImpact,
    ImprovementRule,
    ImprovementState,
)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def now():
    return datetime.now(UTC)


class ImprovementService:
    def __init__(
        self,
        store: FileImprovementStore,
        *,
        developer_reader=None,
        researcher_reader=None,
        projects=None,
        evaluator_factory=None,
    ):
        self.store = store
        self.developers = developer_reader
        self.researchers = researcher_reader
        self.projects = projects
        self.evaluator_factory = evaluator_factory

    def overview(self) -> ImprovementState:
        return self.store.read()

    def list_candidates(self):
        return self.store.read().candidates

    def list_rules(self):
        return self._current_rules(self.store.read())

    @staticmethod
    def _current_rules(state):
        current = {}
        for rule in state.rules:
            current[rule.rule_id] = rule
        return tuple(current.values())

    def get_candidate(self, candidate_id):
        return self._find(self.list_candidates(), "candidate_id", candidate_id)

    def get_rule(self, rule_id):
        return self._find(self.list_rules(), "rule_id", rule_id)

    @staticmethod
    def _find(values, field, identity):
        result = next((v for v in values if getattr(v, field) == identity), None)
        if result is None:
            raise ImprovementError("Improvement record not found.")
        return result

    def project_for_run(self, domain, run_id):
        if not run_id or self.projects is None:
            return None
        field = "developer_run_id" if domain == "developer" else "research_run_id"
        matches = [
            p.project.project_id
            for p in self.projects.list_projects()
            if getattr(p.project, field) == run_id
        ]
        # A run may be rebound/shared. Never guess a project scope if ambiguous.
        return matches[0] if len(matches) == 1 else None

    def evidence(self, domain: Domain, run_id: str) -> ImprovementEvidence:
        if domain not in ("developer", "researcher"):
            raise ImprovementError("Unknown evidence domain.")
        reader = self.developers if domain == "developer" else self.researchers
        try:
            run = reader.get(run_id) if reader is not None else None
        except Exception:  # noqa: BLE001 -- storage failures must not expose raw data
            raise ImprovementError("Cannot read source run.") from None
        if run is None:
            raise ImprovementError("Source run not found.")
        if domain == "developer":
            execution = run.execution_state
            facts = {
                "status": execution.status.value,
                "phase_count": len(execution.phase_records),
                "completed_phases": len(execution.completed_phase_ids),
                "attempts": sum(p.attempt_count for p in execution.phase_records),
                "failed_phases": sum(
                    p.execution is not None and p.execution.status.value == "failed"
                    for p in execution.phase_records
                ),
                "repair_attempts": sum(
                    len(p.execution.repair_attempts)
                    for p in execution.phase_records
                    if p.execution
                ),
                "plan_revisions": len(run.plan_revision_state.revisions) - 1,
                "plan_approved": run.plan_revision_state.status.value == "approved",
            }
        else:
            facts = {
                "status": run.status.value,
                "direction_selected": run.selected_direction_id is not None,
                "plan_revisions": len(run.plan_revision_state.revisions) - 1
                if run.plan_revision_state
                else 0,
                "plan_approved": bool(
                    run.plan_revision_state and run.plan_revision_state.approved
                ),
                "result_submitted": run.result_submission is not None,
                "analysis_completed": run.result_analysis is not None,
                "synthesis_completed": run.result_synthesis is not None,
                "materials_generated": run.paper_materials is not None,
                "evidence_count": len(run.report.evidence),
                "source_count": len(run.report.sources),
            }
        feedback = tuple(
            f
            for f in self.store.read().feedback
            if f.target_type == domain and f.target_id == run_id
        )
        facts.update(
            helpful_feedback=sum(f.rating == "helpful" for f in feedback),
            negative_feedback=sum(f.rating == "not_helpful" for f in feedback),
        )
        project_id = self.project_for_run(domain, run_id)
        fingerprint = digest(
            run.model_dump_json()
            + json.dumps([(f.feedback_id, f.rating) for f in feedback])
            + str(project_id)
        )
        return ImprovementEvidence(
            evidence_id=str(uuid4()),
            source_domain=domain,
            source_run_id=run_id,
            project_id=project_id,
            digest=fingerprint,
            facts=tuple(EvidenceFact(name=k, value=v) for k, v in facts.items()),
            feedback_ids=tuple(f.feedback_id for f in feedback[-50:]),
            collected_at=now(),
        )

    def evaluate(self, domain: Domain, run_id: str) -> ImprovementEvaluation:
        evidence = self.evidence(domain, run_id)

        def existing(state):
            return next(
                (
                    e
                    for e in state.evaluations
                    if e.evidence.source_domain == domain
                    and e.evidence.source_run_id == run_id
                    and e.evidence.digest == evidence.digest
                ),
                None,
            )

        cached = existing(self.store.read())
        if cached:
            return cached
        if self.evaluator_factory is None:
            raise ImprovementError("Improvement evaluator is not configured.")
        try:
            from ai_agent_project.llm.runtime import provider_client_scope

            with provider_client_scope():
                proposal = self.evaluator_factory().evaluate(evidence)
            # Revalidate even injected evaluator objects; IDs/status are never proposal fields.
            proposal = EvaluationProposal.model_validate(proposal.model_dump())
            for text in (
                *proposal.strengths,
                *proposal.weaknesses,
                *proposal.possible_causes,
            ):
                validate_guidance(text)
            if not proposal.improvement_warranted and proposal.candidates:
                raise ValueError("Inconsistent evaluation")
        except Exception:  # noqa: BLE001 -- never retain provider error/output text
            raise ImprovementError(
                "Evaluation failed or returned unsafe guidance. No improvement was activated."
            ) from None
        evaluation = ImprovementEvaluation(
            evaluation_id=str(uuid4()),
            evidence=evidence,
            proposal=proposal,
            created_at=now(),
        )

        def save(state):
            if existing(state):
                return state
            candidates = list(state.candidates)
            for proposed in proposal.candidates:
                if (
                    proposed.category == "project_specific"
                    and evidence.project_id is None
                ):
                    continue
                fingerprint = digest(
                    normalize(proposed.proposed_rule)
                    + domain
                    + str(evidence.project_id)
                )
                if any(c.digest == fingerprint for c in candidates):
                    continue
                candidates.append(
                    ImprovementCandidate(
                        **proposed.model_dump(),
                        candidate_id=str(uuid4()),
                        evaluation_id=evaluation.evaluation_id,
                        source_domain=domain,
                        source_run_id=run_id,
                        project_id=evidence.project_id,
                        evidence_refs=(evidence.evidence_id,),
                        digest=fingerprint,
                        created_at=now(),
                    )
                )
            return state.model_copy(
                update={
                    "evaluations": (*state.evaluations, evaluation),
                    "candidates": tuple(candidates),
                }
            )

        state = self.store.transact(save)
        return existing(state)

    def approve_candidate(
        self, candidate_id: str, scope=None, *, domain=None
    ) -> ImprovementRule:
        def approve(state):
            candidate = self._find(state.candidates, "candidate_id", candidate_id)
            if candidate.status != "pending":
                raise ImprovementError("Only pending candidates can be approved.")
            try:
                CandidateProposal.model_validate(
                    {k: getattr(candidate, k) for k in CandidateProposal.model_fields}
                )
                selected = scope or (
                    "project"
                    if candidate.category == "project_specific"
                    else candidate.source_domain
                )
                project_id = candidate.project_id if selected == "project" else None
                if selected == "project" and not project_id:
                    raise ValueError("Missing project")
                if candidate.category == "project_specific" and selected != "project":
                    raise ValueError("Project-specific guidance requires project scope")
                rule = ImprovementRule(
                    rule_id=str(uuid4()),
                    source_candidate_id=candidate_id,
                    scope=selected,
                    domain=domain
                    if selected == "project"
                    else selected
                    if selected in ("developer", "researcher")
                    else None,
                    project_id=project_id,
                    category=candidate.category,
                    rule_text=candidate.proposed_rule,
                    evidence_refs=candidate.evidence_refs,
                    approved_at=now(),
                    version=1,
                )
            except ValueError:
                raise ImprovementError(
                    "Invalid or protected rule scope/content."
                ) from None
            if any(
                normalize(r.rule_text) == normalize(rule.rule_text)
                and (r.scope, r.domain, r.project_id)
                == (rule.scope, rule.domain, rule.project_id)
                for r in self._current_rules(state)
            ):
                raise ImprovementError(
                    "An identical rule already exists in this scope."
                )
            return state.model_copy(
                update={
                    "candidates": tuple(
                        c.model_copy(update={"status": "approved"})
                        if c.candidate_id == candidate_id
                        else c
                        for c in state.candidates
                    ),
                    "rules": (*state.rules, rule),
                    "events": (
                        *state.events,
                        ImprovementEvent(
                            target_id=candidate_id, action="approved_by_user", at=now()
                        ),
                    ),
                }
            )

        state = self.store.transact(approve)
        return next(r for r in state.rules if r.source_candidate_id == candidate_id)

    def reject_candidate(self, candidate_id: str) -> None:
        def reject(state):
            candidate = self._find(state.candidates, "candidate_id", candidate_id)
            if candidate.status != "pending":
                raise ImprovementError("Only pending candidates can be rejected.")
            return state.model_copy(
                update={
                    "candidates": tuple(
                        c.model_copy(update={"status": "rejected"})
                        if c.candidate_id == candidate_id
                        else c
                        for c in state.candidates
                    ),
                    "events": (
                        *state.events,
                        ImprovementEvent(
                            target_id=candidate_id, action="rejected_by_user", at=now()
                        ),
                    ),
                }
            )

        self.store.transact(reject)

    def set_enabled(self, rule_id: str, enabled: bool) -> None:
        def toggle(state):
            rule = self._find(self._current_rules(state), "rule_id", rule_id)
            if rule.enabled == enabled:
                return state
            return state.model_copy(
                update={
                    "rules": (
                        *state.rules,
                        rule.model_copy(
                            update={"enabled": enabled, "version": rule.version + 1}
                        ),
                    ),
                    "events": (
                        *state.events,
                        ImprovementEvent(
                            target_id=rule_id,
                            action="enabled_by_user" if enabled else "disabled_by_user",
                            at=now(),
                        ),
                    ),
                }
            )

        self.store.transact(toggle)

    def submit_feedback(
        self, target_type, target_id, rating, text=""
    ) -> ImprovementFeedback:
        if target_type in ("developer", "researcher"):
            self.evidence(target_type, target_id)
        elif target_type == "candidate":
            self.get_candidate(target_id)
        elif target_type == "rule":
            self.get_rule(target_id)
        try:
            validate_guidance(text)
            feedback = ImprovementFeedback(
                feedback_id=str(uuid4()),
                target_type=target_type,
                target_id=target_id,
                rating=rating,
                text=text,
                created_at=now(),
            )
        except ValueError:
            raise ImprovementError(
                "Invalid or sensitive feedback. Do not include credentials."
            ) from None
        self.store.transact(
            lambda state: state.model_copy(
                update={"feedback": (*state.feedback, feedback)}
            )
        )
        return feedback

    def conflicts(self, rule_id: str) -> tuple[str, ...]:
        """Flag simple opposite wording for human inspection, never semantic merging."""
        import re

        rule = self.get_rule(rule_id)

        def signature(text):
            tokens = re.findall(r"\w+", normalize(text))
            negative = any(t in {"not", "never", "avoid"} for t in tokens)
            return tuple(
                t for t in tokens if t not in {"not", "never", "avoid", "always", "do"}
            ), negative

        words, negative = signature(rule.rule_text)
        return tuple(
            other.rule_id
            for other in self.list_rules()
            if other.rule_id != rule_id
            and other.enabled
            and signature(other.rule_text) == (words, not negative)
        )

    def resolve_context(
        self, domain: Domain, project_id: str | None = None
    ) -> ImprovementContext:
        rules = [
            r
            for r in self.list_rules()
            if r.enabled
            and (
                r.scope == "global"
                or r.scope == domain
                or (
                    r.scope == "project"
                    and r.project_id == project_id
                    and (r.domain is None or r.domain == domain)
                )
            )
        ]

        conflicting = {
            r.rule_id
            for r in rules
            if any(other.rule_id in self.conflicts(r.rule_id) for other in rules)
        }
        # Both sides stay visible in history/UI, neither wins by model preference.
        rules = [r for r in rules if r.rule_id not in conflicting]

        def priority(r):
            return (
                0
                if r.scope == "project" and r.domain
                else 1
                if r.scope == "project"
                else 3
                if r.scope == "global"
                else 2,
                -r.approved_at.timestamp(),
                r.rule_id,
            )

        context = ImprovementContext(domain=domain, project_id=project_id)
        for rule in sorted(rules, key=priority):
            try:
                validate_guidance(rule.rule_text)
            except ValueError:
                raise ImprovementError(
                    "Stored guidance violates protected constraints. Disable it before proceeding."
                ) from None
            if len(context.rules) >= MAX_RULES:
                break
            proposed = context.model_copy(
                update={
                    "rules": (
                        *context.rules,
                        ContextRule(
                            rule_id=rule.rule_id,
                            version=rule.version,
                            text=rule.rule_text,
                        ),
                    )
                }
            )
            if len(proposed.prompt().encode("utf-8")) <= MAX_CONTEXT_BYTES:
                context = proposed
        return context

    def record_application(
        self, context: ImprovementContext, run_id: str, operation: str
    ) -> None:
        if not context.rules:
            return
        application = ImprovementApplication(
            application_id=str(uuid4()),
            domain=context.domain,
            run_id=run_id,
            project_id=context.project_id,
            rule_ids=tuple(r.rule_id for r in context.rules),
            rule_versions=tuple(r.version for r in context.rules),
            operation=operation,
            applied_at=now(),
        )
        self.store.transact(
            lambda state: state.model_copy(
                update={"applications": (*state.applications, application)}
            )
        )

    def impact(self, rule_id: str) -> ImprovementImpact:
        self.get_rule(rule_id)
        state = self.store.read()
        applications = [a for a in state.applications if rule_id in a.rule_ids]
        outcomes = [
            f
            for f in state.feedback
            if (f.target_type == "rule" and f.target_id == rule_id)
            or any(
                f.target_type == a.domain
                and f.target_id == a.run_id
                and f.created_at >= a.applied_at
                for a in applications
            )
        ]
        evaluated = {
            (e.evidence.source_domain, e.evidence.source_run_id)
            for e in state.evaluations
            if any(
                e.evidence.source_domain == a.domain
                and e.evidence.source_run_id == a.run_id
                and e.created_at >= a.applied_at
                for a in applications
            )
        }
        return ImprovementImpact(
            rule_id=rule_id,
            times_applied=len(applications),
            applied_run_ids=tuple(sorted({a.run_id for a in applications})),
            positive_feedback_count=sum(f.rating == "helpful" for f in outcomes),
            negative_feedback_count=sum(f.rating == "not_helpful" for f in outcomes),
            runs_evaluated_after_application=len(evaluated),
        )


def build_improvement_service(
    *,
    root=None,
    developer_reader=None,
    researcher_reader=None,
    projects=None,
    provider_config=None,
) -> ImprovementService:
    from ai_agent_project.agent.project_file_store import (
        FileProjectRunStore,
        default_project_run_store_root,
    )
    from ai_agent_project.agent.project_session_application import ProjectSessionService
    from ai_agent_project.agent.project_session_file_store import (
        FileProjectStore,
        default_project_store_root,
    )
    from ai_agent_project.agent.research_file_store import (
        FileResearchRunStore,
        default_research_run_store_root,
    )
    from ai_agent_project.improvement.evaluator import OpenAIImprovementEvaluator

    class LazyReader:
        def __init__(self, factory, path):
            self.factory, self.path = factory, path

        def get(self, identity):
            return self.factory(self.path).get(identity) if self.path.exists() else None

    class LazyProjects:
        def list_projects(self):
            path = default_project_store_root()
            return (
                ProjectSessionService(FileProjectStore(path)).list_projects()
                if path.exists()
                else ()
            )

    return ImprovementService(
        FileImprovementStore(root),
        developer_reader=developer_reader
        or LazyReader(FileProjectRunStore, default_project_run_store_root()),
        researcher_reader=researcher_reader
        or LazyReader(FileResearchRunStore, default_research_run_store_root()),
        projects=projects or LazyProjects(),
        evaluator_factory=lambda: OpenAIImprovementEvaluator(
            config=provider_config() if callable(provider_config) else provider_config
        ),
    )
