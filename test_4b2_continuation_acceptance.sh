#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ORIGINAL_HOME="${HOME:?HOME must be set}"
ACCEPTANCE_ROOT="$ORIGINAL_HOME/.local/share/ai-agent/4b2-continuation-acceptance"
ISOLATED_HOME="$ACCEPTANCE_ROOT/home"
HARNESS_OUTPUT="$ACCEPTANCE_ROOT/harness-output"
IDS_FILE="$ACCEPTANCE_ROOT/fixture-ids.sh"
UV_CACHE_DIR_4B2="$(mktemp -d /tmp/ai-agent-4b2-uv-cache.XXXXXX)"

cleanup() {
  rm -rf -- "$UV_CACHE_DIR_4B2"
}
trap cleanup EXIT
export UV_CACHE_DIR="$UV_CACHE_DIR_4B2"

rm -rf -- "$ACCEPTANCE_ROOT"
mkdir -p -- "$ISOLATED_HOME" "$HARNESS_OUTPUT"
export HOME="$ISOLATED_HOME"
cd "$REPO_ROOT"

env -u OPENAI_API_KEY uv run python ./test_4b2_api_acceptance.py \
  --create-cli-fixture --root "$ACCEPTANCE_ROOT" --ids-file "$IDS_FILE"
# shellcheck disable=SC1090
source "$IDS_FILE"
WORKSPACE_SENTINEL="$WORKSPACE/DO_NOT_READ_OR_EXECUTE_4B2.txt"

project_session() {
  env -u OPENAI_API_KEY uv run ai-agent project-session \
    --store-root "$PROJECT_STORE" "$@"
}

sha() {
  sha256sum "$1" | cut -d' ' -f1
}

tree_sha() {
  local root="$1"
  find "$root" -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -d' ' -f1
}

workspace_digest() {
  tree_sha "$WORKSPACE"
}

assert_contains() {
  local file="$1" expected="$2"
  grep -Fq -- "$expected" "$file" || {
    echo "Expected '$expected' in $file" >&2
    exit 1
  }
}

expect_failure() {
  local output="$1"
  shift
  set +e
  "$@" >"$output" 2>&1
  local status=$?
  set -e
  if [[ $status -eq 0 ]]; then
    echo "Expected command to fail: $*" >&2
    exit 1
  fi
}

assert_research_status() {
  local run_id="$1" expected="$2"
  env -u OPENAI_API_KEY uv run python - "$RESEARCH_STORE/$run_id.json" "$expected" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert payload["research_run"]["status"] == sys.argv[2], payload["research_run"]["status"]
PY
}

assert_exact_submission_only() {
  local run_id="$1" input="$2"
  env -u OPENAI_API_KEY uv run python - "$RESEARCH_STORE/$run_id.json" "$input" <<'PY'
import json
import sys
from pathlib import Path

stored = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["research_run"]
submitted = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
assert stored["status"] == "research_results_submitted"
assert stored["result_submission"] == submitted
assert stored["result_analysis"] is None
assert stored["result_synthesis"] is None
assert stored["paper_materials"] is None
PY
}

# Fresh read processes are provider-free and byte-preserving.
workspace_before="$(workspace_digest)"
READ_PROJECT_PATH="$PROJECT_STORE/$PACKAGE_PROJECT.json"
READ_RUN_PATH="$RESEARCH_STORE/$PACKAGE_RUN.json"
read_project_before="$(sha "$READ_PROJECT_PATH")"
read_run_before="$(sha "$READ_RUN_PATH")"
project_session pending-action "$PACKAGE_PROJECT" >"$HARNESS_OUTPUT/pending-before.txt"
project_session resume "$PACKAGE_PROJECT" >"$HARNESS_OUTPUT/resume-before.txt"
[[ "$(sha "$READ_PROJECT_PATH")" == "$read_project_before" ]]
[[ "$(sha "$READ_RUN_PATH")" == "$read_run_before" ]]
assert_contains "$HARNESS_OUTPUT/pending-before.txt" "provide_research_results"

# PACKAGE_READY result intake: exactly one mutation, no analysis/synthesis/paper step.
package_project_before="$(sha "$READ_PROJECT_PATH")"
package_run_before="$(sha "$READ_RUN_PATH")"
developer_tree_before="$(tree_sha "$DEVELOPER_STORE")"
project_session provide-research-results "$PACKAGE_PROJECT" \
  --input "$RESULT_VALID_PACKAGE" >"$HARNESS_OUTPUT/package-submit.txt"
[[ "$(sha "$READ_PROJECT_PATH")" == "$package_project_before" ]]
[[ "$(sha "$READ_RUN_PATH")" != "$package_run_before" ]]
[[ "$(tree_sha "$DEVELOPER_STORE")" == "$developer_tree_before" ]]
assert_contains "$HARNESS_OUTPUT/package-submit.txt" "Previous pending action: provide_research_results"
assert_contains "$HARNESS_OUTPUT/package-submit.txt" "Next pending action: continue_researcher"
assert_contains "$HARNESS_OUTPUT/package-submit.txt" "Source status: research_results_submitted"
assert_exact_submission_only "$PACKAGE_RUN" "$RESULT_VALID_PACKAGE"

# Repeating the same user action is rejected and changes nothing.
all_projects_before="$(tree_sha "$PROJECT_STORE")"
all_developers_before="$(tree_sha "$DEVELOPER_STORE")"
all_research_before="$(tree_sha "$RESEARCH_STORE")"
expect_failure "$HARNESS_OUTPUT/repeated-submit.txt" project_session \
  provide-research-results "$PACKAGE_PROJECT" --input "$RESULT_VALID_PACKAGE"
assert_contains "$HARNESS_OUTPUT/repeated-submit.txt" "not currently allowed"
[[ "$(tree_sha "$PROJECT_STORE")" == "$all_projects_before" ]]
[[ "$(tree_sha "$DEVELOPER_STORE")" == "$all_developers_before" ]]
[[ "$(tree_sha "$RESEARCH_STORE")" == "$all_research_before" ]]

# AWAITING_USER_RESULTS accepts the same typed intake boundary and also stops.
awaiting_project_path="$PROJECT_STORE/$AWAITING_PROJECT.json"
awaiting_run_path="$RESEARCH_STORE/$AWAITING_RUN.json"
awaiting_project_before="$(sha "$awaiting_project_path")"
awaiting_run_before="$(sha "$awaiting_run_path")"
project_session provide-research-results "$AWAITING_PROJECT" \
  --input "$RESULT_VALID_AWAITING" >"$HARNESS_OUTPUT/awaiting-submit.txt"
[[ "$(sha "$awaiting_project_path")" == "$awaiting_project_before" ]]
[[ "$(sha "$awaiting_run_path")" != "$awaiting_run_before" ]]
assert_exact_submission_only "$AWAITING_RUN" "$RESULT_VALID_AWAITING"
assert_contains "$HARNESS_OUTPUT/awaiting-submit.txt" "Next pending action: continue_researcher"

# Invalid ownership/version/traceability and malformed/schema-invalid JSON are atomic.
for case_name in FOREIGN WRONG_PLAN WRONG_IMPLEMENTATION FOREIGN_TASK MALFORMED SCHEMA_INVALID; do
  project_variable="INVALID_${case_name}_PROJECT"
  run_variable="INVALID_${case_name}_RUN"
  result_variable="RESULT_${case_name}"
  project_id="${!project_variable}"
  run_id="${!run_variable}"
  result_path="${!result_variable}"
  project_path="$PROJECT_STORE/$project_id.json"
  run_path="$RESEARCH_STORE/$run_id.json"
  before_project="$(sha "$project_path")"
  before_run="$(sha "$run_path")"
  before_developers="$(tree_sha "$DEVELOPER_STORE")"
  before_research="$(tree_sha "$RESEARCH_STORE")"
  before_projects="$(tree_sha "$PROJECT_STORE")"
  expect_failure "$HARNESS_OUTPUT/invalid-${case_name,,}.txt" project_session \
    provide-research-results "$project_id" --input "$result_path"
  [[ "$(sha "$project_path")" == "$before_project" ]]
  [[ "$(sha "$run_path")" == "$before_run" ]]
  [[ "$(tree_sha "$DEVELOPER_STORE")" == "$before_developers" ]]
  [[ "$(tree_sha "$RESEARCH_STORE")" == "$before_research" ]]
  [[ "$(tree_sha "$PROJECT_STORE")" == "$before_projects" ]]
done
assert_contains "$HARNESS_OUTPUT/invalid-foreign.txt" "different research run"
assert_contains "$HARNESS_OUTPUT/invalid-wrong_plan.txt" "different approved plan"
assert_contains "$HARNESS_OUTPUT/invalid-wrong_implementation.txt" \
  "different implementation plan"
assert_contains "$HARNESS_OUTPUT/invalid-foreign_task.txt" \
  "unknown implementation task"
assert_contains "$HARNESS_OUTPUT/invalid-malformed.txt" "Could not read valid result JSON"
assert_contains "$HARNESS_OUTPUT/invalid-schema_invalid.txt" "Could not read valid result JSON"

# The Project layer exposes but does not invent unsupported domain transitions.
running_project_path="$PROJECT_STORE/$RUNNING_PROJECT.json"
running_run_path="$DEVELOPER_STORE/$RUNNING_RUN.json"
before_project="$(sha "$running_project_path")"
before_run="$(sha "$running_run_path")"
before_research_tree="$(tree_sha "$RESEARCH_STORE")"
expect_failure "$HARNESS_OUTPUT/unsupported-developer.txt" project_session \
  continue-developer "$RUNNING_PROJECT"
[[ "$(sha "$running_project_path")" == "$before_project" ]]
[[ "$(sha "$running_run_path")" == "$before_run" ]]
[[ "$(tree_sha "$RESEARCH_STORE")" == "$before_research_tree" ]]
assert_contains "$HARNESS_OUTPUT/unsupported-developer.txt" \
  "Current project state does not allow phase execution"

unsupported_project_path="$PROJECT_STORE/$UNSUPPORTED_RESEARCH_PROJECT.json"
unsupported_run_path="$RESEARCH_STORE/$UNSUPPORTED_RESEARCH_RUN.json"
before_project="$(sha "$unsupported_project_path")"
before_run="$(sha "$unsupported_run_path")"
before_developer_tree="$(tree_sha "$DEVELOPER_STORE")"
expect_failure "$HARNESS_OUTPUT/unsupported-researcher.txt" project_session \
  continue-researcher "$UNSUPPORTED_RESEARCH_PROJECT"
[[ "$(sha "$unsupported_project_path")" == "$before_project" ]]
[[ "$(sha "$unsupported_run_path")" == "$before_run" ]]
[[ "$(tree_sha "$DEVELOPER_STORE")" == "$before_developer_tree" ]]
assert_contains "$HARNESS_OUTPUT/unsupported-researcher.txt" \
  "Researcher continuation has no bounded progression for status: discovering"

# Hybrid ordering rejects the second domain without touching either linked run.
hybrid_project_path="$PROJECT_STORE/$HYBRID_PROJECT.json"
hybrid_dev_path="$DEVELOPER_STORE/$HYBRID_DEV_RUN.json"
hybrid_research_path="$RESEARCH_STORE/$HYBRID_RESEARCH_RUN.json"
before_project="$(sha "$hybrid_project_path")"
before_dev="$(sha "$hybrid_dev_path")"
before_research="$(sha "$hybrid_research_path")"
expect_failure "$HARNESS_OUTPUT/hybrid-wrong-domain.txt" project_session \
  continue-researcher "$HYBRID_PROJECT"
assert_contains "$HARNESS_OUTPUT/hybrid-wrong-domain.txt" "not currently allowed"
[[ "$(sha "$hybrid_project_path")" == "$before_project" ]]
[[ "$(sha "$hybrid_dev_path")" == "$before_dev" ]]
[[ "$(sha "$hybrid_research_path")" == "$before_research" ]]

# Completed projects reject every 4B-2 action before a domain invocation.
for command in continue-developer continue-researcher; do
  before_projects="$(tree_sha "$PROJECT_STORE")"
  before_developers="$(tree_sha "$DEVELOPER_STORE")"
  before_research="$(tree_sha "$RESEARCH_STORE")"
  expect_failure "$HARNESS_OUTPUT/completed-$command.txt" project_session \
    "$command" "$COMPLETED_PROJECT"
  assert_contains "$HARNESS_OUTPUT/completed-$command.txt" \
    "Completed project cannot perform action"
  [[ "$(tree_sha "$PROJECT_STORE")" == "$before_projects" ]]
  [[ "$(tree_sha "$DEVELOPER_STORE")" == "$before_developers" ]]
  [[ "$(tree_sha "$RESEARCH_STORE")" == "$before_research" ]]
done
before_projects="$(tree_sha "$PROJECT_STORE")"
before_research="$(tree_sha "$RESEARCH_STORE")"
expect_failure "$HARNESS_OUTPUT/completed-results.txt" project_session \
  provide-research-results "$COMPLETED_PROJECT" --input "$RESULT_VALID_PACKAGE"
assert_contains "$HARNESS_OUTPUT/completed-results.txt" \
  "Completed project cannot perform action"
[[ "$(tree_sha "$PROJECT_STORE")" == "$before_projects" ]]
[[ "$(tree_sha "$RESEARCH_STORE")" == "$before_research" ]]

# Missing bindings preserve the established explicit errors and session bytes.
before_missing="$(sha "$PROJECT_STORE/$MISSING_DEV_PROJECT.json")"
expect_failure "$HARNESS_OUTPUT/missing-developer.txt" project_session \
  continue-developer "$MISSING_DEV_PROJECT"
assert_contains "$HARNESS_OUTPUT/missing-developer.txt" \
  "Linked Developer run not found: $MISSING_DEV_RUN"
[[ "$(sha "$PROJECT_STORE/$MISSING_DEV_PROJECT.json")" == "$before_missing" ]]

before_missing="$(sha "$PROJECT_STORE/$MISSING_RESEARCH_PROJECT.json")"
expect_failure "$HARNESS_OUTPUT/missing-researcher.txt" project_session \
  continue-researcher "$MISSING_RESEARCH_PROJECT"
assert_contains "$HARNESS_OUTPUT/missing-researcher.txt" \
  "Linked Researcher run not found: $MISSING_RESEARCH_RUN"
[[ "$(sha "$PROJECT_STORE/$MISSING_RESEARCH_PROJECT.json")" == "$before_missing" ]]

# Post-mutation reads are still read-only.
post_project_before="$(tree_sha "$PROJECT_STORE")"
post_developer_before="$(tree_sha "$DEVELOPER_STORE")"
post_research_before="$(tree_sha "$RESEARCH_STORE")"
project_session pending-action "$PACKAGE_PROJECT" >"$HARNESS_OUTPUT/pending-after.txt"
project_session resume "$AWAITING_PROJECT" >"$HARNESS_OUTPUT/resume-after.txt"
[[ "$(tree_sha "$PROJECT_STORE")" == "$post_project_before" ]]
[[ "$(tree_sha "$DEVELOPER_STORE")" == "$post_developer_before" ]]
[[ "$(tree_sha "$RESEARCH_STORE")" == "$post_research_before" ]]
[[ "$(workspace_digest)" == "$workspace_before" ]]
[[ "$(sha "$WORKSPACE_SENTINEL")" == \
  "$(printf '%s' 'DEVELOPER_WORKSPACE_SENTINEL_4B2' | sha256sum | cut -d' ' -f1)" ]]

# Researcher routes persist data/artifacts only; they never materialize or execute them.
[[ -z "$(find "$ACCEPTANCE_ROOT" -type f ! -path "$PROJECT_STORE/*" \
  ! -path "$DEVELOPER_STORE/*" ! -path "$RESEARCH_STORE/*" \
  ! -path "$HARNESS_OUTPUT/*" ! -path "$ACCEPTANCE_ROOT/result-inputs/*" \
  ! -path "$IDS_FILE" ! -path "$ACCEPTANCE_ROOT/workspace/*" -print -quit)" ]]

echo "PHASE_4B2_CLI_ACCEPTANCE=PASSED"

# Optional production-composition proof for provider-backed transitions.
if [[ "${RUN_OPENAI_E2E:-0}" == "1" ]]; then
  : "${OPENAI_API_KEY:?RUN_OPENAI_E2E=1 requires OPENAI_API_KEY}"
  before_project="$(sha "$PROJECT_STORE/$DEV_PROJECT.json")"
  before_research="$(sha "$hybrid_research_path")"
  uv run ai-agent project-session --store-root "$PROJECT_STORE" \
    continue-developer "$DEV_PROJECT" >"$HARNESS_OUTPUT/openai-developer.txt"
  [[ "$(sha "$PROJECT_STORE/$DEV_PROJECT.json")" == "$before_project" ]]
  [[ "$(sha "$hybrid_research_path")" == "$before_research" ]]
  assert_contains "$HARNESS_OUTPUT/openai-developer.txt" "Source status: awaiting_checkpoint"

  before_project="$(sha "$PROJECT_STORE/$DIRECTION_PROJECT.json")"
  uv run ai-agent project-session --store-root "$PROJECT_STORE" \
    continue-researcher "$DIRECTION_PROJECT" >"$HARNESS_OUTPUT/openai-researcher.txt"
  [[ "$(sha "$PROJECT_STORE/$DIRECTION_PROJECT.json")" == "$before_project" ]]
  assert_research_status "$DIRECTION_RUN" "awaiting_research_plan_approval"
  assert_contains "$HARNESS_OUTPUT/openai-researcher.txt" \
    "Source status: awaiting_research_plan_approval"
  echo "PHASE_4B2_OPENAI_E2E=PASSED"
fi
