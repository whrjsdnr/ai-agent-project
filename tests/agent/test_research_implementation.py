"""Offline tests for generated-only Researcher implementation packages."""

import pytest
from pydantic import ValidationError

from ai_agent_project.agent.research import (
    RelatedStudy,
    ResearchArtifactType,
    ResearchDirection,
    ResearchDiscoveryReport,
    ResearchEvidence,
    ResearchGap,
    ResearchGeneratedArtifact,
    ResearchImplementationPackage,
    ResearchImplementationPlan,
    ResearchImplementationTask,
    ResearchMethodologyStep,
    ResearchMetric,
    ResearchObjective,
    ResearchPlan,
    ResearchPlanRevisionState,
    ResearchQuestion,
    ResearchRequest,
    ResearchRun,
    ResearchScope,
    ResearchSource,
    ResearchStatus,
)
from ai_agent_project.agent.research_application import (
    InMemoryResearchRunStore,
    InvalidResearchStateError,
    ResearchApplicationService,
)


def _report() -> ResearchDiscoveryReport:
    direction = ResearchDirection(
        id="RD-1",
        title="Direction",
        research_question="Question",
        target_gap_ids=("G-1",),
        novelty="Novel",
        feasibility="Feasible",
    )
    return ResearchDiscoveryReport(
        questions=(
            ResearchQuestion(
                id="Q-1",
                question="Q",
                rationale="R",
                source_scope=ResearchScope.EXTERNAL,
            ),
        ),
        sources=(
            ResearchSource(
                id="S-1", title="S", locator="https://example.org", source_type="web"
            ),
        ),
        evidence=(
            ResearchEvidence(
                id="E-1",
                source_id="S-1",
                question_id="Q-1",
                claim="C",
                support_text="E",
                evidence_type="citation",
            ),
        ),
        related_studies=(
            RelatedStudy(
                id="ST-1", title="Study", research_problem="P", evidence_ids=("E-1",)
            ),
        ),
        gaps=(
            ResearchGap(
                id="G-1",
                description="Gap",
                supporting_study_ids=("ST-1",),
                evidence_ids=("E-1",),
                importance="high",
                feasibility="feasible",
            ),
        ),
        directions=(direction,),
    )


def _approved_run() -> ResearchRun:
    plan = ResearchPlan(
        id="PLAN-1",
        selected_direction_id="RD-1",
        title="Plan",
        research_question="Question",
        objectives=(
            ResearchObjective(id="OBJ-1", description="Objective", direction_id="RD-1"),
        ),
        methodology=(
            ResearchMethodologyStep(
                id="METHOD-1", description="Method", objective_ids=("OBJ-1",)
            ),
        ),
        metrics=(
            ResearchMetric(
                id="MET-1", name="Quality", description="D", measurement_method="Review"
            ),
        ),
    )
    return ResearchRun(
        request=ResearchRequest(topic="Topic"),
        status=ResearchStatus.RESEARCH_PLAN_APPROVED,
        report=_report(),
        selected_direction_id="RD-1",
        plan_revision_state=ResearchPlanRevisionState.from_plan(plan).model_copy(
            update={"approved": True}
        ),
    )


def _implementation_plan() -> ResearchImplementationPlan:
    return ResearchImplementationPlan(
        selected_direction_id="RD-1",
        approved_plan_version=1,
        package_summary="Package",
        tasks=(
            ResearchImplementationTask(
                task_id="TASK-1",
                title="Implement",
                description="D",
                objective_ids=("OBJ-1",),
                methodology_step_ids=("METHOD-1",),
                metric_ids=("MET-1",),
                expected_artifact_paths=("research_pkg/main.py",),
            ),
        ),
    )


def _package(plan: ResearchImplementationPlan) -> ResearchImplementationPackage:
    return ResearchImplementationPackage(
        implementation_plan=plan,
        artifacts=(
            ResearchGeneratedArtifact(
                artifact_id="ART-1",
                task_id="TASK-1",
                relative_path="research_pkg/main.py",
                artifact_type=ResearchArtifactType.SOURCE,
                content="print('generated only')\n",
                objective_ids=("OBJ-1",),
                methodology_step_ids=("METHOD-1",),
                metric_ids=("MET-1",),
            ),
        ),
        execution_guide="Generated only; not executed.",
    )


class _ImplementationPlanner:
    def plan(self, request, direction, approved_plan, approved_plan_version, report):
        del request, direction, approved_plan, approved_plan_version, report
        return _implementation_plan()


class _ImplementationGenerator:
    def generate(self, request, direction, approved_plan, implementation_plan, report):
        del request, direction, approved_plan, report
        return _package(implementation_plan)


def test_implementation_lifecycle_is_generated_only_and_preserves_approved_state(
    tmp_path,
) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "nested").mkdir(parents=True)
    (workspace / "README.md").write_text("unchanged\n", encoding="utf-8")
    (workspace / "nested" / "file.txt").write_bytes(b"unchanged")
    before = {
        path.relative_to(workspace): path.read_bytes()
        for path in workspace.rglob("*")
        if path.is_file()
    }
    store = InMemoryResearchRunStore()
    store.create("run", _approved_run())
    service = ResearchApplicationService(
        object(),
        store,
        implementation_planner=_ImplementationPlanner(),
        implementation_generator=_ImplementationGenerator(),
    )

    planned = service.generate_implementation_plan("run")
    packaged = service.generate_implementation_package("run")

    assert (
        planned.research_run.status is ResearchStatus.IMPLEMENTATION_GENERATION_STARTED
    )
    assert packaged.research_run.status is ResearchStatus.IMPLEMENTATION_PACKAGE_READY
    assert packaged.research_run.selected_direction_id == "RD-1"
    assert (
        packaged.research_run.plan_revision_state == _approved_run().plan_revision_state
    )
    assert packaged.research_run.implementation_package is not None
    assert packaged.research_run.implementation_package.generated_not_executed is True
    after = {
        path.relative_to(workspace): path.read_bytes()
        for path in workspace.rglob("*")
        if path.is_file()
    }
    assert after == before
    with pytest.raises(InvalidResearchStateError):
        service.generate_implementation_plan("run")
    with pytest.raises(InvalidResearchStateError):
        service.generate_implementation_package("run")


@pytest.mark.parametrize(
    "path", ["/absolute.py", "../escape.py", "C:\\work\\escape.py"]
)
def test_generated_artifact_paths_must_be_portable_relative_paths(path: str) -> None:
    with pytest.raises(ValidationError, match="safe relative"):
        ResearchGeneratedArtifact(
            artifact_id="A",
            task_id="T",
            relative_path=path,
            artifact_type=ResearchArtifactType.SOURCE,
            content="x",
        )


def test_implementation_plan_rejects_duplicate_dependencies_cycles_and_unknown_approved_refs() -> (
    None
):
    with pytest.raises(ValidationError, match="acyclic"):
        ResearchImplementationPlan(
            selected_direction_id="RD-1",
            approved_plan_version=1,
            package_summary="x",
            tasks=(
                ResearchImplementationTask(
                    task_id="A", title="a", description="a", dependencies=("B",)
                ),
                ResearchImplementationTask(
                    task_id="B", title="b", description="b", dependencies=("A",)
                ),
            ),
        )
    with pytest.raises(ValueError, match="unknown objective"):
        ResearchImplementationPlan(
            selected_direction_id="RD-1",
            approved_plan_version=1,
            package_summary="x",
            tasks=(
                ResearchImplementationTask(
                    task_id="A", title="a", description="a", objective_ids=("missing",)
                ),
            ),
        ).validate_against(_approved_run().plan_revision_state.active_plan)


def test_package_rejects_duplicate_paths_and_orphan_artifact() -> None:
    plan = _implementation_plan()
    with pytest.raises(
        ValidationError, match="Duplicate research generated artifact paths"
    ):
        ResearchImplementationPackage(
            implementation_plan=plan,
            execution_guide="x",
            artifacts=(
                ResearchGeneratedArtifact(
                    artifact_id="A1",
                    task_id="TASK-1",
                    relative_path="same.py",
                    artifact_type=ResearchArtifactType.SOURCE,
                    content="x",
                ),
                ResearchGeneratedArtifact(
                    artifact_id="A2",
                    task_id="TASK-1",
                    relative_path="same.py",
                    artifact_type=ResearchArtifactType.TEST,
                    content="x",
                ),
            ),
        )
    with pytest.raises(ValueError, match="unknown implementation task"):
        ResearchImplementationPackage(
            implementation_plan=plan,
            execution_guide="x",
            artifacts=(
                ResearchGeneratedArtifact(
                    artifact_id="A",
                    task_id="missing",
                    relative_path="x.py",
                    artifact_type=ResearchArtifactType.SOURCE,
                    content="x",
                ),
            ),
        ).validate_against(plan, _approved_run().plan_revision_state.active_plan)
