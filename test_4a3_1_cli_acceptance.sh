#!/usr/bin/env bash
set -euo pipefail

ORIGINAL_HOME="$HOME"
ACCEPTANCE_ROOT="$ORIGINAL_HOME/.local/share/ai-agent/4a3-1-cli-acceptance"
export HOME="$ACCEPTANCE_ROOT/home"
PROJECT_STORE="$ACCEPTANCE_ROOT/project-sessions"
DEVELOPER_STORE="$HOME/.local/share/ai-agent/project-runs"
RESEARCH_STORE="$HOME/.local/share/ai-agent/research-runs"
WORKSPACE="$ACCEPTANCE_ROOT/developer-workspace"
EXPORT_OUTPUT="$ACCEPTANCE_ROOT/export-output"
IDS_FILE="$ACCEPTANCE_ROOT/ids.env"
WORKSPACE_SENTINEL="DEVELOPER_LIVE_WORKSPACE_CONTENT_MUST_NOT_BE_READ_4A3_1"
GENERATED_SENTINEL="RESEARCH_GENERATED_ARTIFACT_EXACT_CONTENT_4A3_1"

rm -rf -- "$ACCEPTANCE_ROOT"
mkdir -p -- \
    "$PROJECT_STORE" "$DEVELOPER_STORE" "$RESEARCH_STORE" \
    "$WORKSPACE" "$EXPORT_OUTPUT"
printf '%s\n' "$WORKSPACE_SENTINEL" > "$WORKSPACE/live-secret-sentinel.txt"

fail() {
    echo "ACCEPTANCE FAILURE: $*" >&2
    exit 1
}

assert_contains() {
    local value="$1"
    local expected="$2"
    [[ "$value" == *"$expected"* ]] || fail "expected output containing: $expected"
}

assert_not_contains() {
    local value="$1"
    local prohibited="$2"
    [[ "$value" != *"$prohibited"* ]] || fail "unexpected output containing: $prohibited"
}

project_session() {
    env -u OPENAI_API_KEY uv run ai-agent project-session \
        --store-root "$PROJECT_STORE" "$@"
}

inspect_artifact() {
    local project_id="$1"
    local artifact_id="$2"
    project_session artifact "$project_id" "$artifact_id" --format json
}

snapshot_digest() {
    find "$PROJECT_STORE" "$DEVELOPER_STORE" "$RESEARCH_STORE" \
        -type f -name '*.json' -print0 \
        | sort -z \
        | xargs -0 sha256sum \
        | sha256sum \
        | awk '{print $1}'
}

export PROJECT_STORE DEVELOPER_STORE RESEARCH_STORE WORKSPACE IDS_FILE
export GENERATED_SENTINEL

env -u OPENAI_API_KEY uv run python - <<'PY'
import os
import shlex
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path.cwd() / "tests" / "integration"))

from test_research_paper_materials import _payload, _ready_service

from ai_agent_project.agent.plan import ImplementationPlan
from ai_agent_project.agent.plan_revision import PlanRevisionState
from ai_agent_project.agent.project import ProjectPhase, ProjectPlan, ProjectSpecification
from ai_agent_project.agent.project_artifact import ProjectArtifactType
from ai_agent_project.agent.project_artifact_application import ProjectArtifactService
from ai_agent_project.agent.project_execution import (
    PhaseExecutionRecord,
    ProjectExecutionState,
    ProjectExecutionStatus,
)
from ai_agent_project.agent.project_file_store import FileProjectRunStore
from ai_agent_project.agent.project_runner import ProjectRun
from ai_agent_project.agent.project_session import ProjectModeProposal, ProjectSession
from ai_agent_project.agent.project_session_application import ProjectSessionService
from ai_agent_project.agent.project_session_file_store import FileProjectStore
from ai_agent_project.agent.research import ResearchRun, ResearchStatus, WorkMode
from ai_agent_project.agent.research_file_store import FileResearchRunStore
from ai_agent_project.agent.specification import Specification
from ai_agent_project.agent.upgrade import ProjectMode
from ai_agent_project.agent.workspace import WorkspaceSnapshot


class NoProvider:
    def propose(self, request: str) -> ProjectModeProposal:
        raise AssertionError(f"provider called during fixture setup: {request}")


class PaperGenerator:
    def generate(self, *args: object) -> object:
        return _payload()


def new_id() -> str:
    return str(uuid4())


def make_plan(implementation_plan: ImplementationPlan, title: str) -> ProjectPlan:
    return ProjectPlan(
        project_title="Phase 4A-3.1 Developer Fixture",
        phases=(
            ProjectPhase(
                id="PHASE-1",
                title=title,
                objective="Preserve authoritative artifact state",
                requirement_ids=("REQ-1",),
                task_ids=("TASK-1",),
            ),
        ),
        implementation_plan=implementation_plan,
    )


def make_developer_run(title: str) -> ProjectRun:
    specification = Specification.model_validate(
        {
            "project_name": title,
            "summary": "Authoritative developer acceptance specification",
            "requirements": [
                {
                    "id": "REQ-1",
                    "description": "Catalog persisted artifacts without workspace reads",
                }
            ],
        }
    )
    project_specification = ProjectSpecification.from_specification(specification)
    implementation_plan = ImplementationPlan.model_validate(
        {
            "summary": "Persisted implementation plan",
            "tasks": [
                {
                    "id": "TASK-1",
                    "title": "Catalog artifacts",
                    "description": "Read only the persisted ProjectRun",
                    "requirement_ids": ["REQ-1"],
                    "files_to_modify": ["src/catalog.py"],
                }
            ],
        }
    )
    initial_plan = make_plan(implementation_plan, "Initial catalog plan")
    revised_plan = make_plan(implementation_plan, "Revised catalog plan")
    revisions = PlanRevisionState.from_plan(initial_plan).revise(
        revised_plan, "Retain a second immutable revision"
    )
    return ProjectRun(
        specification=specification,
        project_specification=project_specification,
        workspace=WorkspaceSnapshot(files=["live-secret-sentinel.txt"]),
        implementation_plan=implementation_plan,
        project_plan=revised_plan,
        execution_state=ProjectExecutionState(
            project_title=title,
            status=ProjectExecutionStatus.AWAITING_PLAN_APPROVAL,
            current_phase_id="PHASE-1",
            phase_records=(PhaseExecutionRecord(phase_id="PHASE-1"),),
        ),
        plan_revision_state=revisions,
    )


project_store = FileProjectStore(Path(os.environ["PROJECT_STORE"]))
developer_store = FileProjectRunStore(
    Path(os.environ["DEVELOPER_STORE"]),
    workspace_root=Path(os.environ["WORKSPACE"]),
)
research_store = FileResearchRunStore(Path(os.environ["RESEARCH_STORE"]))
session_service = ProjectSessionService(project_store, NoProvider())


def make_project(name: str, mode: WorkMode) -> str:
    project_id = new_id()
    project_store.create(
        project_id,
        ProjectSession.awaiting_confirmation(
            project_id=project_id,
            title=name,
            original_request=f"Phase 4A-3.1 acceptance: {name}",
            mode_proposal=ProjectModeProposal(
                proposed_work_mode=mode,
                proposed_project_mode=ProjectMode.NEW,
                rationale="Offline trusted acceptance fixture",
            ),
        ),
    )
    session_service.confirm_project_mode(project_id, mode, ProjectMode.NEW)
    return project_id


ids: dict[str, str] = {}
ids["DEVELOPER_RUN_ID"] = new_id()
developer_store.create(
    ids["DEVELOPER_RUN_ID"],
    make_developer_run("Linked Developer Run"),
)
ids["FOREIGN_DEVELOPER_RUN_ID"] = new_id()
developer_store.create(
    ids["FOREIGN_DEVELOPER_RUN_ID"],
    make_developer_run("Foreign Developer Run"),
)

paper_service, _ = _ready_service(PaperGenerator())
research_run = paper_service.generate_paper_materials("run").research_run
assert research_run.status is ResearchStatus.PAPER_MATERIALS_READY
assert research_run.implementation_package is not None
assert research_run.implementation_package.artifacts
first_artifact = research_run.implementation_package.artifacts[0].model_copy(
    update={"content": os.environ["GENERATED_SENTINEL"]}
)
package = research_run.implementation_package.model_copy(
    update={
        "artifacts": (
            first_artifact,
            *research_run.implementation_package.artifacts[1:],
        )
    }
)
research_run = ResearchRun.model_validate(
    research_run.model_copy(update={"implementation_package": package}).model_dump()
)
ids["RESEARCH_RUN_ID"] = new_id()
research_store.create(ids["RESEARCH_RUN_ID"], research_run)

ids["DEVELOPER_PROJECT_ID"] = make_project("Developer project", WorkMode.DEVELOPER)
session_service.bind_developer_run(
    ids["DEVELOPER_PROJECT_ID"], ids["DEVELOPER_RUN_ID"]
)
ids["RESEARCH_PROJECT_ID"] = make_project("Research project", WorkMode.RESEARCHER)
session_service.bind_research_run(ids["RESEARCH_PROJECT_ID"], ids["RESEARCH_RUN_ID"])
ids["FOREIGN_PROJECT_ID"] = make_project("Foreign project", WorkMode.DEVELOPER)
session_service.bind_developer_run(
    ids["FOREIGN_PROJECT_ID"], ids["FOREIGN_DEVELOPER_RUN_ID"]
)
ids["HYBRID_PROJECT_ID"] = make_project("Hybrid project", WorkMode.HYBRID)
session_service.bind_developer_run(ids["HYBRID_PROJECT_ID"], ids["DEVELOPER_RUN_ID"])
session_service.bind_research_run(ids["HYBRID_PROJECT_ID"], ids["RESEARCH_RUN_ID"])
ids["MISSING_RUN_ID"] = new_id()
ids["MISSING_PROJECT_ID"] = make_project("Missing run project", WorkMode.DEVELOPER)
session_service.bind_developer_run(ids["MISSING_PROJECT_ID"], ids["MISSING_RUN_ID"])

catalog_service = ProjectArtifactService(
    session_service, developer_store, research_store
)


def artifact_id(project_id: str, kind: ProjectArtifactType) -> str:
    matches = [
        item.artifact_id
        for item in catalog_service.list_artifacts(project_id).artifacts
        if item.artifact_type is kind
    ]
    assert len(matches) == 1, (kind, matches)
    return matches[0]


ids["DEV_SPEC_ID"] = artifact_id(
    ids["DEVELOPER_PROJECT_ID"], ProjectArtifactType.SPECIFICATION
)
ids["DEV_PLAN_ID"] = artifact_id(
    ids["DEVELOPER_PROJECT_ID"], ProjectArtifactType.PROJECT_PLAN
)
ids["DEV_EXECUTION_ID"] = artifact_id(
    ids["DEVELOPER_PROJECT_ID"], ProjectArtifactType.EXECUTION_STATE
)
ids["RESEARCH_FILE_ID"] = artifact_id(
    ids["RESEARCH_PROJECT_ID"], ProjectArtifactType.RESEARCH_GENERATED_FILE
)
ids["SELECTED_DIRECTION_ID"] = artifact_id(
    ids["RESEARCH_PROJECT_ID"], ProjectArtifactType.SELECTED_DIRECTION
)
ids["FOREIGN_ARTIFACT_ID"] = artifact_id(
    ids["FOREIGN_PROJECT_ID"], ProjectArtifactType.SPECIFICATION
)
ids["AUTHORITATIVE_GENERATED_ID"] = first_artifact.artifact_id
ids["AUTHORITATIVE_GENERATED_PATH"] = first_artifact.relative_path
ids["AUTHORITATIVE_TASK_ID"] = first_artifact.task_id
ids["AUTHORITATIVE_DIRECTION_ID"] = research_run.selected_direction_id or ""

Path(os.environ["IDS_FILE"]).write_text(
    "".join(
        f"{key}={shlex.quote(value)}\n" for key, value in sorted(ids.items())
    ),
    encoding="utf-8",
)
PY

# Values are generated UUIDs and trusted descriptor/model metadata, shell-quoted by Python.
# shellcheck disable=SC1090
set -a
source "$IDS_FILE"
set +a

before_all="$(snapshot_digest)"
before_project="$(sha256sum "$PROJECT_STORE/$DEVELOPER_PROJECT_ID.json")"
before_developer="$(sha256sum "$DEVELOPER_STORE/$DEVELOPER_RUN_ID.json")"
before_research="$(sha256sum "$RESEARCH_STORE/$RESEARCH_RUN_ID.json")"

developer_catalog_1="$(project_session artifacts "$DEVELOPER_PROJECT_ID")"
developer_catalog_2="$(project_session artifacts "$DEVELOPER_PROJECT_ID")"
[[ "$developer_catalog_1" == "$developer_catalog_2" ]] \
    || fail "Developer catalog changed across fresh processes"
for artifact_type in \
    specification project_specification implementation_plan project_plan \
    project_plan_revision plan_revision_history execution_state; do
    assert_contains "$developer_catalog_1" "| $artifact_type |"
done
assert_contains "$developer_catalog_1" "$DEV_EXECUTION_ID"
assert_contains "$DEV_EXECUTION_ID" ":execution_state:sha256-"

for excluded in \
    agent_state tool_call phase_execution repair_attempt progress_report \
    checkpoint acceptance_report workspace_file; do
    assert_not_contains "$developer_catalog_1" "| $excluded |"
done
assert_not_contains "$developer_catalog_1" "$WORKSPACE_SENTINEL"

developer_specification="$(inspect_artifact "$DEVELOPER_PROJECT_ID" "$DEV_SPEC_ID")"
assert_contains "$developer_specification" \
    '"description": "Catalog persisted artifacts without workspace reads"'
developer_plan="$(inspect_artifact "$DEVELOPER_PROJECT_ID" "$DEV_PLAN_ID")"
assert_contains "$developer_plan" '"title": "Revised catalog plan"'
developer_execution_1="$(inspect_artifact "$DEVELOPER_PROJECT_ID" "$DEV_EXECUTION_ID")"
developer_execution_2="$(inspect_artifact "$DEVELOPER_PROJECT_ID" "$DEV_EXECUTION_ID")"
[[ "$developer_execution_1" == "$developer_execution_2" ]] \
    || fail "Developer execution inspection changed across fresh processes"
assert_contains "$developer_execution_1" '"status": "awaiting_plan_approval"'
assert_not_contains "$developer_specification$developer_plan$developer_execution_1" \
    "$WORKSPACE_SENTINEL"

research_catalog_1="$(project_session artifacts "$RESEARCH_PROJECT_ID")"
research_catalog_2="$(project_session artifacts "$RESEARCH_PROJECT_ID")"
[[ "$research_catalog_1" == "$research_catalog_2" ]] \
    || fail "Researcher catalog changed across fresh processes"
for artifact_type in \
    research_request discovery_report selected_direction research_plan \
    research_plan_revision research_plan_history research_implementation_plan \
    research_implementation_package research_generated_file research_results \
    research_result_analysis research_synthesis paper_materials; do
    assert_contains "$research_catalog_1" "| $artifact_type |"
done

generated_json="$(inspect_artifact "$RESEARCH_PROJECT_ID" "$RESEARCH_FILE_ID")"
GENERATED_JSON="$generated_json" env -u OPENAI_API_KEY uv run python - <<'PY'
import json
import os

value = json.loads(os.environ["GENERATED_JSON"])["content"]
assert value["artifact_id"] == os.environ["AUTHORITATIVE_GENERATED_ID"]
assert value["relative_path"] == os.environ["AUTHORITATIVE_GENERATED_PATH"]
assert value["content"] == os.environ["GENERATED_SENTINEL"]
assert value["task_id"] == os.environ["AUTHORITATIVE_TASK_ID"]
assert "objective_ids" in value
assert "methodology_step_ids" in value
assert "metric_ids" in value
PY
assert_not_contains "$research_catalog_1" "$GENERATED_SENTINEL"
[[ ! -e "$EXPORT_OUTPUT/$AUTHORITATIVE_GENERATED_PATH" ]] \
    || fail "generated research file was unexpectedly materialized"

direction_json="$(inspect_artifact "$RESEARCH_PROJECT_ID" "$SELECTED_DIRECTION_ID")"
DIRECTION_JSON="$direction_json" env -u OPENAI_API_KEY uv run python - <<'PY'
import json
import os

value = json.loads(os.environ["DIRECTION_JSON"])["content"]
assert value["id"] == os.environ["AUTHORITATIVE_DIRECTION_ID"]
for field in (
    "title",
    "research_question",
    "target_gap_ids",
    "novelty",
    "expected_contributions",
    "feasibility",
    "risks",
):
    assert field in value
PY

set +e
foreign_output="$(inspect_artifact \
    "$DEVELOPER_PROJECT_ID" "$FOREIGN_ARTIFACT_ID" 2>&1)"
foreign_status=$?
set -e
(( foreign_status != 0 )) || fail "foreign artifact lookup unexpectedly succeeded"
assert_contains "$foreign_output" "Project artifact not found: $FOREIGN_ARTIFACT_ID"
assert_not_contains "$foreign_output" "Linked Developer run not found"

set +e
missing_output="$(project_session artifacts "$MISSING_PROJECT_ID" 2>&1)"
missing_status=$?
set -e
(( missing_status != 0 )) || fail "missing linked run catalog unexpectedly succeeded"
assert_contains "$missing_output" "Linked Developer run not found: $MISSING_RUN_ID"

hybrid_catalog_1="$(project_session artifacts "$HYBRID_PROJECT_ID")"
hybrid_catalog_2="$(project_session artifacts "$HYBRID_PROJECT_ID")"
[[ "$hybrid_catalog_1" == "$hybrid_catalog_2" ]] \
    || fail "Hybrid catalog changed across fresh processes"
developer_lines="$(grep '^- developer:' <<<"$developer_catalog_1")"
research_lines="$(grep '^- researcher:' <<<"$research_catalog_1")"
hybrid_lines="$(grep '^- ' <<<"$hybrid_catalog_1")"
[[ "$hybrid_lines" == "$developer_lines"$'\n'"$research_lines" ]] \
    || fail "Hybrid catalog was merged, ranked, synthesized, or reordered"
hybrid_developer="$(inspect_artifact "$HYBRID_PROJECT_ID" "$DEV_SPEC_ID")"
hybrid_research="$(inspect_artifact "$HYBRID_PROJECT_ID" "$RESEARCH_FILE_ID")"
assert_contains "$hybrid_developer" '"project_name": "Linked Developer Run"'
assert_contains "$hybrid_research" "$GENERATED_SENTINEL"

after_project="$(sha256sum "$PROJECT_STORE/$DEVELOPER_PROJECT_ID.json")"
after_developer="$(sha256sum "$DEVELOPER_STORE/$DEVELOPER_RUN_ID.json")"
after_research="$(sha256sum "$RESEARCH_STORE/$RESEARCH_RUN_ID.json")"
after_all="$(snapshot_digest)"
[[ "$before_project" == "$after_project" ]] || fail "ProjectSession snapshot changed"
[[ "$before_developer" == "$after_developer" ]] || fail "Developer snapshot changed"
[[ "$before_research" == "$after_research" ]] || fail "Researcher snapshot changed"
[[ "$before_all" == "$after_all" ]] || fail "an authoritative store snapshot changed"

[[ -z "$(find "$EXPORT_OUTPUT" -mindepth 1 -print -quit)" ]] \
    || fail "artifact export output was created"
[[ "$(find "$WORKSPACE" -type f | wc -l)" -eq 1 ]] \
    || fail "Developer workspace was modified"
[[ "$(<"$WORKSPACE/live-secret-sentinel.txt")" == "$WORKSPACE_SENTINEL" ]] \
    || fail "Developer workspace sentinel changed"

echo "PHASE_4A3_1_CLI_ACCEPTANCE=PASSED"
