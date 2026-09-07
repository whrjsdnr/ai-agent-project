#!/usr/bin/env bash
set -euo pipefail

ORIGINAL_HOME="$HOME"
ACCEPTANCE_ROOT="$ORIGINAL_HOME/.local/share/ai-agent/4b1-action-routing-acceptance"
export HOME="$ACCEPTANCE_ROOT/home"
PROJECT_STORE="$ACCEPTANCE_ROOT/project-sessions"
DEVELOPER_STORE="$HOME/.local/share/ai-agent/project-runs"
RESEARCH_STORE="$HOME/.local/share/ai-agent/research-runs"
WORKSPACE="$ACCEPTANCE_ROOT/developer-workspace"
HARNESS_OUTPUT="$ACCEPTANCE_ROOT/harness-output"
IDS_FILE="$HARNESS_OUTPUT/ids.env"
WORKSPACE_SENTINEL="DEVELOPER_WORKSPACE_MUST_NOT_BE_READ_OR_EXECUTED_4B1"

rm -rf -- "$ACCEPTANCE_ROOT"
mkdir -p -- "$WORKSPACE" "$HARNESS_OUTPUT"
printf '%s\n' "$WORKSPACE_SENTINEL" > "$WORKSPACE/live-workspace-sentinel.txt"

fail() {
    echo "ACCEPTANCE FAILURE: $*" >&2
    exit 1
}

assert_file_contains() {
    local path="$1"
    local expected="$2"
    grep -Fq -- "$expected" "$path" \
        || fail "$path does not contain expected text: $expected"
}

project_session() {
    env -u OPENAI_API_KEY uv run ai-agent project-session \
        --store-root "$PROJECT_STORE" "$@"
}

expect_failure() {
    local label="$1"
    local expected="$2"
    shift 2
    local status
    set +e
    project_session "$@" \
        > "$HARNESS_OUTPUT/$label.stdout" \
        2> "$HARNESS_OUTPUT/$label.stderr"
    status=$?
    set -e
    (( status != 0 )) || fail "$label unexpectedly succeeded"
    assert_file_contains "$HARNESS_OUTPUT/$label.stderr" "$expected"
}

snapshot_digest() {
    local root="$1"
    find "$root" -type f -name '*.json' -print0 \
        | sort -z \
        | xargs -0 sha256sum \
        | sha256sum \
        | awk '{print $1}'
}

export PROJECT_STORE DEVELOPER_STORE RESEARCH_STORE WORKSPACE IDS_FILE
env -u OPENAI_API_KEY uv run python ./test_4b1_api_acceptance.py \
    --create-cli-fixture --root "$ACCEPTANCE_ROOT" --ids-file "$IDS_FILE"

# Fixture metadata contains only trusted IDs/paths and is shell-quoted by Python.
# shellcheck disable=SC1090
set -a
source "$IDS_FILE"
set +a

before_projects="$(snapshot_digest "$PROJECT_STORE")"
before_completed_run="$(sha256sum "$DEVELOPER_STORE/$COMPLETED_DEVELOPER_RUN_ID.json")"
before_hybrid_research="$(sha256sum "$RESEARCH_STORE/$HYBRID_RESEARCH_RUN_ID.json")"
before_workspace="$(sha256sum "$WORKSPACE/live-workspace-sentinel.txt")"
before_workspace_count="$(find "$WORKSPACE" -type f | wc -l)"

developer_success="$HARNESS_OUTPUT/developer-approval.stdout"
project_session approve-developer-plan "$DEVELOPER_PROJECT_ID" > "$developer_success"
for expected in \
    "Project ID: $DEVELOPER_PROJECT_ID" \
    "Action: approve_developer_plan" \
    "Previous pending action: approve_developer_plan" \
    "Next pending action: continue_developer" \
    "Source domain: developer" \
    "Source run: $DEVELOPER_RUN_ID" \
    "Source status: ready"; do
    assert_file_contains "$developer_success" "$expected"
done
developer_pending="$HARNESS_OUTPUT/developer-pending.stdout"
project_session pending-action "$DEVELOPER_PROJECT_ID" > "$developer_pending"
assert_file_contains "$developer_pending" "continue_developer"
expect_failure repeated-developer "current pending action: continue_developer" \
    approve-developer-plan "$DEVELOPER_PROJECT_ID"

expect_failure wrong-research-action "current pending action: select_research_direction" \
    approve-research-plan "$DIRECTION_PROJECT_ID"
expect_failure foreign-direction "Research direction not found: $FOREIGN_DIRECTION_ID" \
    select-research-direction "$DIRECTION_PROJECT_ID" "$FOREIGN_DIRECTION_ID"
direction_before_success="$(sha256sum "$RESEARCH_STORE/$DIRECTION_RUN_ID.json")"
direction_success="$HARNESS_OUTPUT/direction-selection.stdout"
project_session select-research-direction \
    "$DIRECTION_PROJECT_ID" "$SELECTED_DIRECTION_ID" > "$direction_success"
[[ "$direction_before_success" != "$(sha256sum "$RESEARCH_STORE/$DIRECTION_RUN_ID.json")" ]] \
    || fail "direction selection did not change the authoritative ResearchRun"
for expected in \
    "Project ID: $DIRECTION_PROJECT_ID" \
    "Action: select_research_direction" \
    "Previous pending action: select_research_direction" \
    "Next pending action: continue_researcher" \
    "Source domain: researcher" \
    "Source run: $DIRECTION_RUN_ID" \
    "Source status: direction_selected"; do
    assert_file_contains "$direction_success" "$expected"
done
expect_failure repeated-direction "current pending action: continue_researcher" \
    select-research-direction "$DIRECTION_PROJECT_ID" "$SELECTED_DIRECTION_ID"

plan_success="$HARNESS_OUTPUT/research-plan-approval.stdout"
project_session approve-research-plan "$PLAN_PROJECT_ID" > "$plan_success"
for expected in \
    "Project ID: $PLAN_PROJECT_ID" \
    "Action: approve_research_plan" \
    "Previous pending action: approve_research_plan" \
    "Next pending action: continue_researcher" \
    "Source domain: researcher" \
    "Source run: $PLAN_RUN_ID" \
    "Source status: research_plan_approved"; do
    assert_file_contains "$plan_success" "$expected"
done
expect_failure repeated-plan "current pending action: continue_researcher" \
    approve-research-plan "$PLAN_PROJECT_ID"

expect_failure completed-project "Completed project cannot perform action" \
    approve-developer-plan "$COMPLETED_PROJECT_ID"
expect_failure missing-run "Linked Developer run not found: $MISSING_RUN_ID" \
    approve-developer-plan "$MISSING_PROJECT_ID"

expect_failure hybrid-wrong-domain "current pending action: approve_developer_plan" \
    select-research-direction "$HYBRID_PROJECT_ID" "$SELECTED_DIRECTION_ID"
[[ "$before_hybrid_research" == "$(sha256sum "$RESEARCH_STORE/$HYBRID_RESEARCH_RUN_ID.json")" ]] \
    || fail "rejected Hybrid Researcher action mutated the run"
hybrid_success="$HARNESS_OUTPUT/hybrid-developer-approval.stdout"
project_session approve-developer-plan "$HYBRID_PROJECT_ID" > "$hybrid_success"
assert_file_contains "$hybrid_success" "Action: approve_developer_plan"
assert_file_contains "$hybrid_success" "Source run: $HYBRID_DEVELOPER_RUN_ID"
[[ "$before_hybrid_research" == "$(sha256sum "$RESEARCH_STORE/$HYBRID_RESEARCH_RUN_ID.json")" ]] \
    || fail "Hybrid Developer approval mutated the Researcher run"

export DEVELOPER_PROJECT_ID DEVELOPER_RUN_ID DIRECTION_PROJECT_ID DIRECTION_RUN_ID
export PLAN_PROJECT_ID PLAN_RUN_ID COMPLETED_PROJECT_ID COMPLETED_DEVELOPER_RUN_ID
export HYBRID_PROJECT_ID HYBRID_DEVELOPER_RUN_ID HYBRID_RESEARCH_RUN_ID
export SELECTED_DIRECTION_ID
env -u OPENAI_API_KEY uv run python - <<'PY'
import os
from pathlib import Path

from ai_agent_project.agent.plan_revision import PlanReviewStatus
from ai_agent_project.agent.project_execution import ProjectExecutionStatus
from ai_agent_project.agent.project_file_store import FileProjectRunStore
from ai_agent_project.agent.project_session import ProjectStatus
from ai_agent_project.agent.project_session_file_store import FileProjectStore
from ai_agent_project.agent.research import ResearchStatus
from ai_agent_project.agent.research_file_store import FileResearchRunStore

projects = FileProjectStore(Path(os.environ["PROJECT_STORE"]))
developers = FileProjectRunStore(Path(os.environ["DEVELOPER_STORE"]))
researchers = FileResearchRunStore(Path(os.environ["RESEARCH_STORE"]))

developer = developers.get(os.environ["DEVELOPER_RUN_ID"])
assert developer.plan_revision_state.status is PlanReviewStatus.APPROVED
assert developer.execution_state.status is ProjectExecutionStatus.READY
direction = researchers.get(os.environ["DIRECTION_RUN_ID"])
assert direction.status is ResearchStatus.DIRECTION_SELECTED
assert direction.selected_direction_id == os.environ["SELECTED_DIRECTION_ID"]
assert direction.plan_revision_state is None
plan = researchers.get(os.environ["PLAN_RUN_ID"])
assert plan.status is ResearchStatus.RESEARCH_PLAN_APPROVED
assert plan.plan_revision_state.approved is True
assert plan.implementation_plan is None
assert plan.implementation_package is None
hybrid_developer = developers.get(os.environ["HYBRID_DEVELOPER_RUN_ID"])
assert hybrid_developer.plan_revision_state.status is PlanReviewStatus.APPROVED
assert hybrid_developer.execution_state.status is ProjectExecutionStatus.READY
hybrid_research = researchers.get(os.environ["HYBRID_RESEARCH_RUN_ID"])
assert hybrid_research.status is ResearchStatus.AWAITING_DIRECTION_SELECTION
assert hybrid_research.selected_direction_id is None
assert projects.get(os.environ["COMPLETED_PROJECT_ID"]).status is ProjectStatus.COMPLETED
for project_id in (
    os.environ["DEVELOPER_PROJECT_ID"],
    os.environ["DIRECTION_PROJECT_ID"],
    os.environ["PLAN_PROJECT_ID"],
    os.environ["HYBRID_PROJECT_ID"],
):
    assert projects.get(project_id).status is ProjectStatus.ACTIVE
PY

after_projects="$(snapshot_digest "$PROJECT_STORE")"
[[ "$before_projects" == "$after_projects" ]] \
    || fail "ProjectSession snapshots changed during routed domain mutations"
[[ "$before_completed_run" == "$(sha256sum "$DEVELOPER_STORE/$COMPLETED_DEVELOPER_RUN_ID.json")" ]] \
    || fail "completed-project rejection mutated its Developer run"
[[ "$before_workspace" == "$(sha256sum "$WORKSPACE/live-workspace-sentinel.txt")" ]] \
    || fail "Developer workspace sentinel changed"
[[ "$before_workspace_count" == "$(find "$WORKSPACE" -type f | wc -l)" ]] \
    || fail "Developer workspace file count changed"

echo "PHASE_4B1_CLI_ACCEPTANCE=PASSED"
