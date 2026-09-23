"""Persistent CLI lifecycle coverage for user-supplied research results."""

import json
from io import StringIO
from pathlib import Path

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
    ResearchMetric,
    ResearchObjective,
    ResearchPlan,
    ResearchPlanRevisionState,
    ResearchQuestion,
    ResearchRequest,
    ResearchResultAnalysisPayload,
    ResearchRun,
    ResearchScope,
    ResearchSource,
    ResearchStatus,
)
from ai_agent_project.agent.research_application import ResearchApplicationService
from ai_agent_project.agent.research_file_store import FileResearchRunStore
from ai_agent_project.cli import run_cli


def _ready_run() -> ResearchRun:
    direction = ResearchDirection(
        id="RD",
        title="D",
        research_question="Q",
        target_gap_ids=("G",),
        novelty="N",
        feasibility="F",
    )
    report = ResearchDiscoveryReport(
        questions=(
            ResearchQuestion(
                id="Q", question="Q", rationale="R", source_scope=ResearchScope.EXTERNAL
            ),
        ),
        sources=(
            ResearchSource(
                id="S", title="S", locator="https://example.org", source_type="web"
            ),
        ),
        evidence=(
            ResearchEvidence(
                id="E",
                source_id="S",
                question_id="Q",
                claim="C",
                support_text="T",
                evidence_type="citation",
            ),
        ),
        related_studies=(
            RelatedStudy(
                id="ST", title="ST", research_problem="P", evidence_ids=("E",)
            ),
        ),
        gaps=(
            ResearchGap(
                id="G",
                description="G",
                supporting_study_ids=("ST",),
                evidence_ids=("E",),
                importance="I",
                feasibility="F",
            ),
        ),
        directions=(direction,),
    )
    plan = ResearchPlan(
        id="P",
        selected_direction_id="RD",
        title="P",
        research_question="Q",
        objectives=(ResearchObjective(id="O", description="O", direction_id="RD"),),
        metrics=(
            ResearchMetric(id="M", name="M", description="D", measurement_method="x"),
            ResearchMetric(id="M2", name="M2", description="D", measurement_method="x"),
        ),
    )
    implementation = ResearchImplementationPlan(
        selected_direction_id="RD",
        approved_plan_version=1,
        package_summary="x",
        tasks=(
            ResearchImplementationTask(
                task_id="T",
                title="T",
                description="D",
                objective_ids=("O",),
                metric_ids=("M",),
                expected_artifact_paths=("pkg/a.py",),
            ),
            ResearchImplementationTask(task_id="T2", title="T2", description="D"),
        ),
    )
    package = ResearchImplementationPackage(
        implementation_plan=implementation,
        execution_guide="Generated only",
        artifacts=(
            ResearchGeneratedArtifact(
                artifact_id="A",
                task_id="T",
                relative_path="pkg/a.py",
                artifact_type=ResearchArtifactType.SOURCE,
                content="x",
                objective_ids=("O",),
                metric_ids=("M",),
            ),
        ),
    )
    return ResearchRun(
        request=ResearchRequest(topic="Topic"),
        status=ResearchStatus.IMPLEMENTATION_PACKAGE_READY,
        report=report,
        selected_direction_id="RD",
        plan_revision_state=ResearchPlanRevisionState.from_plan(plan).model_copy(
            update={"approved": True}
        ),
        implementation_plan=implementation,
        implementation_package=package,
    )


def test_result_cli_lifecycle_uses_persistent_store_without_execution(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runs"
    run_id = "00000000-0000-4000-8000-000000000010"
    FileResearchRunStore(root).create(run_id, _ready_run())
    calls: list[str] = []

    class Analyzer:
        def analyze(self, *args):
            calls.append("analyze")
            return ResearchResultAnalysisPayload(
                findings=(), missing_evidence=("missing",)
            )

    def builder(_workspace: Path, store: FileResearchRunStore):
        return ResearchApplicationService(object(), store, result_analyzer=Analyzer())

    guide = StringIO()
    assert (
        run_cli(
            ["research", "--store-root", str(root), "result-guide", run_id],
            research_service_builder=builder,
            stdout=guide,
        )
        == 0
    )
    assert "not executed" in guide.getvalue() and "not measured" in guide.getvalue()
    assert (
        FileResearchRunStore(root).get(run_id).status
        is ResearchStatus.AWAITING_USER_RESULTS
    )
    result = {
        "research_run_id": run_id,
        "approved_plan_version": 1,
        "implementation_plan_version": 1,
        "task_results": [
            {
                "task_id": "T",
                "objective_ids": ["O"],
                "metric_ids": ["M"],
                "execution_status": "executed",
            }
        ],
        "metric_observations": [{"metric_id": "M", "value": 0.5, "status": "measured"}],
    }
    path = tmp_path / "result.json"
    path.write_text(json.dumps(result), encoding="utf-8")
    assert (
        run_cli(
            [
                "research",
                "--store-root",
                str(root),
                "submit-results",
                run_id,
                str(path),
            ],
            research_service_builder=builder,
            stdout=StringIO(),
        )
        == 0
    )
    shown = StringIO()
    assert (
        run_cli(
            ["research", "--store-root", str(root), "show-results", run_id],
            research_service_builder=builder,
            stdout=shown,
        )
        == 0
    )
    assert '"measured"' in shown.getvalue()
    assert (
        run_cli(
            ["research", "--store-root", str(root), "analyze-results", run_id],
            research_service_builder=builder,
            stdout=StringIO(),
        )
        == 0
    )
    assert calls == ["analyze"]
    assert (
        FileResearchRunStore(root).get(run_id).status
        is ResearchStatus.RESEARCH_RESULTS_ANALYZED
    )


def test_legacy_snapshots_without_result_fields_load_unchanged(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    base = _ready_run().model_dump(mode="json")
    cases = (
        (
            "00000000-0000-4000-8000-000000000021",
            "awaiting_direction_selection",
            ("plan_revision_state", "implementation_plan", "implementation_package"),
        ),
        (
            "00000000-0000-4000-8000-000000000022",
            "research_plan_approved",
            ("implementation_plan", "implementation_package"),
        ),
        ("00000000-0000-4000-8000-000000000023", "implementation_package_ready", ()),
    )
    root.mkdir()
    for run_id, status, remove in cases:
        payload = dict(base)
        payload["status"] = status
        if status == "awaiting_direction_selection":
            payload["selected_direction_id"] = None
        for key in (*remove, "result_submission", "result_analysis"):
            payload.pop(key, None)
        (root / f"{run_id}.json").write_text(
            json.dumps({"research_run_id": run_id, "research_run": payload}),
            encoding="utf-8",
        )
        loaded = FileResearchRunStore(root).get(run_id)
        assert loaded is not None
        assert loaded.result_submission is None
        assert loaded.result_analysis is None
