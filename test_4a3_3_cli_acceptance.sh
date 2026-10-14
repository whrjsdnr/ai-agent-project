#!/usr/bin/env bash
set -euo pipefail

ORIGINAL_HOME="$HOME"
ACCEPTANCE_ROOT="$ORIGINAL_HOME/.local/share/ai-agent/4a3-3-cli-acceptance"
export HOME="$ACCEPTANCE_ROOT/home"
PROJECT_STORE="$ACCEPTANCE_ROOT/project-sessions"
DEVELOPER_STORE="$HOME/.local/share/ai-agent/project-runs"
RESEARCH_STORE="$HOME/.local/share/ai-agent/research-runs"
WORKSPACE="$ACCEPTANCE_ROOT/developer-workspace"
EXPORT_ROOT="$ACCEPTANCE_ROOT/exports"
HARNESS_OUTPUT="$ACCEPTANCE_ROOT/harness-output"
IDS_FILE="$HARNESS_OUTPUT/ids.env"
REFERENCE_CONTENT="$HARNESS_OUTPUT/authoritative-generated-content.bin"
WORKSPACE_SENTINEL="DEVELOPER_LIVE_WORKSPACE_MUST_NOT_BE_READ_4A3_3"

rm -rf -- "$ACCEPTANCE_ROOT"
mkdir -p -- \
    "$PROJECT_STORE" "$DEVELOPER_STORE" "$RESEARCH_STORE" \
    "$WORKSPACE" "$EXPORT_ROOT" "$HARNESS_OUTPUT"
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

assert_absent() {
    [[ ! -e "$1" && ! -L "$1" ]] || fail "unexpected destination exists: $1"
}

project_session() {
    env -u OPENAI_API_KEY uv run ai-agent project-session \
        --store-root "$PROJECT_STORE" "$@"
}

render_to() {
    local project_id="$1"
    local artifact_id="$2"
    local format="$3"
    local output_path="$4"
    project_session artifact "$project_id" "$artifact_id" \
        --format "$format" > "$output_path"
}

expect_export_failure() {
    local label="$1"
    local project_id="$2"
    local artifact_id="$3"
    local format="$4"
    local output_path="$5"
    local expected_error="$6"
    local stderr_path="$HARNESS_OUTPUT/$label.stderr"
    local stdout_path="$HARNESS_OUTPUT/$label.stdout"
    local status

    set +e
    project_session export-artifact \
        "$project_id" "$artifact_id" --format "$format" --output "$output_path" \
        > "$stdout_path" 2> "$stderr_path"
    status=$?
    set -e
    (( status != 0 )) || fail "$label unexpectedly succeeded"
    assert_file_contains "$stderr_path" "$expected_error"
    [[ -z "$(find "$EXPORT_ROOT" -maxdepth 1 -type f -name '.*.tmp' -print -quit)" ]] \
        || fail "$label leaked a temporary export file"
}

snapshot_digest() {
    find "$PROJECT_STORE" "$DEVELOPER_STORE" "$RESEARCH_STORE" \
        -type f -name '*.json' -print0 \
        | sort -z \
        | xargs -0 sha256sum \
        | sha256sum \
        | awk '{print $1}'
}

directory_inventory() {
    find "$EXPORT_ROOT" -mindepth 1 -printf '%P|%y|%l\n' | sort
}

export PROJECT_STORE DEVELOPER_STORE RESEARCH_STORE WORKSPACE IDS_FILE
export REFERENCE_CONTENT

env -u OPENAI_API_KEY uv run python - <<'PY'
import os
import shlex
import sys
from pathlib import Path
from uuid import uuid4

root = Path.cwd()
sys.path.insert(0, str(root / "tests" / "agent"))
sys.path.insert(0, str(root / "tests" / "integration"))

from test_project_artifact import _developer_run
from test_project_artifact_interfaces import _terminal_research_run

from ai_agent_project.agent.project_artifact import ProjectArtifactType
from ai_agent_project.agent.project_artifact_application import ProjectArtifactService
from ai_agent_project.agent.project_file_store import FileProjectRunStore
from ai_agent_project.agent.project_runner import ProjectRun
from ai_agent_project.agent.project_session import ProjectModeProposal, ProjectSession
from ai_agent_project.agent.project_session_application import ProjectSessionService
from ai_agent_project.agent.project_session_file_store import FileProjectStore
from ai_agent_project.agent.research import ResearchRun, ResearchStatus, WorkMode
from ai_agent_project.agent.research_file_store import FileResearchRunStore
from ai_agent_project.agent.upgrade import ProjectMode


class NoProvider:
    def propose(self, request: str) -> ProjectModeProposal:
        raise AssertionError(f"provider called during fixture setup: {request}")


def identifier() -> str:
    return str(uuid4())


project_store = FileProjectStore(Path(os.environ["PROJECT_STORE"]))
developer_store = FileProjectRunStore(
    Path(os.environ["DEVELOPER_STORE"]),
    workspace_root=Path(os.environ["WORKSPACE"]),
)
research_store = FileResearchRunStore(Path(os.environ["RESEARCH_STORE"]))
session_service = ProjectSessionService(project_store, NoProvider())

developer = _developer_run(revisions=2)
foreign_developer = _developer_run()
research = _terminal_research_run()
assert research.status is ResearchStatus.PAPER_MATERIALS_READY
assert research.implementation_package is not None
assert research.implementation_package.artifacts
exact_content = (
    "line one\n"
    "  indented # heading * star | pipe `code`\n"
    "\n"
    "한글 UTF-8 line\n"
    "final line"
)
generated = research.implementation_package.artifacts[0].model_copy(
    update={"content": exact_content}
)
package = research.implementation_package.model_copy(
    update={
        "artifacts": (
            generated,
            *research.implementation_package.artifacts[1:],
        )
    }
)
research = ResearchRun.model_validate(
    research.model_copy(update={"implementation_package": package}).model_dump()
)

developer_run_id = identifier()
foreign_run_id = identifier()
research_run_id = identifier()
developer_store.create(developer_run_id, developer)
developer_store.create(foreign_run_id, foreign_developer)
research_store.create(research_run_id, research)


def project(name: str, mode: WorkMode) -> str:
    project_id = identifier()
    project_store.create(
        project_id,
        ProjectSession.awaiting_confirmation(
            project_id=project_id,
            title=name,
            original_request=f"Phase 4A-3.3 acceptance: {name}",
            mode_proposal=ProjectModeProposal(
                proposed_work_mode=mode,
                proposed_project_mode=ProjectMode.NEW,
                rationale="Trusted offline fixture",
            ),
        ),
    )
    session_service.confirm_project_mode(project_id, mode, ProjectMode.NEW)
    return project_id


developer_project_id = project("Developer export", WorkMode.DEVELOPER)
session_service.bind_developer_run(developer_project_id, developer_run_id)
research_project_id = project("Researcher export", WorkMode.RESEARCHER)
session_service.bind_research_run(research_project_id, research_run_id)
foreign_project_id = project("Foreign Developer export", WorkMode.DEVELOPER)
session_service.bind_developer_run(foreign_project_id, foreign_run_id)
missing_run_id = identifier()
missing_project_id = project("Missing Developer export", WorkMode.DEVELOPER)
session_service.bind_developer_run(missing_project_id, missing_run_id)

catalog = ProjectArtifactService(session_service, developer_store, research_store)


def one(project_id: str, artifact_type: ProjectArtifactType) -> str:
    matches = [
        item.artifact_id
        for item in catalog.list_artifacts(project_id).artifacts
        if item.artifact_type is artifact_type
    ]
    assert len(matches) == 1, (artifact_type, matches)
    return matches[0]


values = {
    "DEVELOPER_PROJECT_ID": developer_project_id,
    "DEVELOPER_RUN_ID": developer_run_id,
    "RESEARCH_PROJECT_ID": research_project_id,
    "RESEARCH_RUN_ID": research_run_id,
    "MISSING_PROJECT_ID": missing_project_id,
    "MISSING_RUN_ID": missing_run_id,
    "DEVELOPER_PLAN_ID": one(
        developer_project_id, ProjectArtifactType.PROJECT_PLAN
    ),
    "GENERATED_FILE_ID": one(
        research_project_id, ProjectArtifactType.RESEARCH_GENERATED_FILE
    ),
    "FOREIGN_ARTIFACT_ID": one(
        foreign_project_id, ProjectArtifactType.SPECIFICATION
    ),
}
Path(os.environ["IDS_FILE"]).write_text(
    "".join(
        f"{key}={shlex.quote(value)}\n" for key, value in sorted(values.items())
    ),
    encoding="utf-8",
)
Path(os.environ["REFERENCE_CONTENT"]).write_bytes(exact_content.encode("utf-8"))
PY

# Trusted fixture setup generated and shell-quoted all dynamic identifiers.
# shellcheck disable=SC1090
set -a
source "$IDS_FILE"
set +a

before_all="$(snapshot_digest)"
before_projects="$(find "$PROJECT_STORE" -type f -name '*.json' -print0 | sort -z | xargs -0 sha256sum)"
before_developer="$(sha256sum "$DEVELOPER_STORE/$DEVELOPER_RUN_ID.json")"
before_research="$(sha256sum "$RESEARCH_STORE/$RESEARCH_RUN_ID.json")"
before_workspace_hash="$(sha256sum "$WORKSPACE/live-workspace-sentinel.txt")"
before_workspace_count="$(find "$WORKSPACE" -type f | wc -l)"

developer_output="$EXPORT_ROOT/developer-plan.md"
developer_summary="$HARNESS_OUTPUT/developer-export.stdout"
project_session export-artifact \
    "$DEVELOPER_PROJECT_ID" "$DEVELOPER_PLAN_ID" \
    --format markdown --output "$developer_output" > "$developer_summary"
[[ -f "$developer_output" && ! -L "$developer_output" ]] \
    || fail "Developer export is not a regular non-symlink file"
[[ -s "$developer_output" ]] || fail "Developer export is empty"
[[ "$(find "$EXPORT_ROOT" -mindepth 1 -maxdepth 1 -print | wc -l)" -eq 1 ]] \
    || fail "Developer export created more than its one requested destination"
assert_file_contains "$developer_output" "Developer project plan v2"
assert_file_contains "$developer_output" "Revised"
assert_file_contains "$developer_output" "Build it"
assert_file_contains "$developer_summary" "Exported artifact: $DEVELOPER_PLAN_ID"
assert_file_contains "$developer_summary" "Format: markdown"
assert_file_contains "$developer_summary" "Output: $developer_output"
render_to "$DEVELOPER_PROJECT_ID" "$DEVELOPER_PLAN_ID" markdown \
    "$HARNESS_OUTPUT/developer-plan-rendered.md"
cmp -s "$developer_output" "$HARNESS_OUTPUT/developer-plan-rendered.md" \
    || fail "Developer exported bytes differ from fresh renderer stdout"
developer_bytes="$(wc -c < "$developer_output" | tr -d ' ')"
developer_sha="$(sha256sum "$developer_output" | awk '{print $1}')"
assert_file_contains "$developer_summary" "Bytes: $developer_bytes"
assert_file_contains "$developer_summary" "SHA-256: $developer_sha"

generated_output="$EXPORT_ROOT/generated-file.txt"
generated_summary="$HARNESS_OUTPUT/generated-export.stdout"
project_session export-artifact \
    "$RESEARCH_PROJECT_ID" "$GENERATED_FILE_ID" \
    --format text --output "$generated_output" > "$generated_summary"
cmp -s "$REFERENCE_CONTENT" "$generated_output" \
    || fail "generated export differs from authoritative fixture bytes"
render_to "$RESEARCH_PROJECT_ID" "$GENERATED_FILE_ID" text \
    "$HARNESS_OUTPUT/generated-file-rendered.bin"
cmp -s "$generated_output" "$HARNESS_OUTPUT/generated-file-rendered.bin" \
    || fail "generated export differs from fresh exact-text renderer stdout"
generated_bytes="$(wc -c < "$generated_output" | tr -d ' ')"
generated_sha="$(sha256sum "$generated_output" | awk '{print $1}')"
assert_file_contains "$generated_summary" "Exported artifact: $GENERATED_FILE_ID"
assert_file_contains "$generated_summary" "Format: text"
assert_file_contains "$generated_summary" "Output: $generated_output"
assert_file_contains "$generated_summary" "Bytes: $generated_bytes"
assert_file_contains "$generated_summary" "SHA-256: $generated_sha"
[[ "$(head -c 3 "$generated_output" | od -An -t x1 | tr -d ' \n')" != "efbbbf" ]] \
    || fail "generated export gained a UTF-8 BOM"
last_byte="$(tail -c 1 "$generated_output" | od -An -t u1 | tr -d ' ')"
[[ "$last_byte" != "10" ]] || fail "generated export gained a trailing newline"
assert_file_contains "$generated_output" "  indented # heading * star | pipe `code`"
assert_file_contains "$generated_output" "한글 UTF-8 line"

developer_before_repeat="$developer_sha"
expect_export_failure \
    repeated-destination "$DEVELOPER_PROJECT_ID" "$DEVELOPER_PLAN_ID" markdown \
    "$developer_output" "Artifact output already exists"
[[ "$(sha256sum "$developer_output" | awk '{print $1}')" == "$developer_before_repeat" ]] \
    || fail "repeated export changed the original destination"

printf '%s' 'DO_NOT_OVERWRITE_4A3_3' > "$EXPORT_ROOT/existing.txt"
existing_before="$(sha256sum "$EXPORT_ROOT/existing.txt" | awk '{print $1}')"
expect_export_failure \
    existing-target "$DEVELOPER_PROJECT_ID" "$DEVELOPER_PLAN_ID" markdown \
    "$EXPORT_ROOT/existing.txt" "Artifact output already exists"
[[ "$(sha256sum "$EXPORT_ROOT/existing.txt" | awk '{print $1}')" == "$existing_before" ]] \
    || fail "existing destination was overwritten"

printf '%s' 'REAL_TARGET_UNCHANGED_4A3_3' > "$EXPORT_ROOT/real-target.txt"
real_target_before="$(sha256sum "$EXPORT_ROOT/real-target.txt" | awk '{print $1}')"
ln -s -- "real-target.txt" "$EXPORT_ROOT/output-link"
final_link_before="$(readlink "$EXPORT_ROOT/output-link")"
expect_export_failure \
    final-symlink "$DEVELOPER_PROJECT_ID" "$DEVELOPER_PLAN_ID" markdown \
    "$EXPORT_ROOT/output-link" "Artifact output must not be a symlink"
[[ "$(sha256sum "$EXPORT_ROOT/real-target.txt" | awk '{print $1}')" == "$real_target_before" ]] \
    || fail "final symlink target changed"
[[ -L "$EXPORT_ROOT/output-link" ]] \
    || fail "final destination symlink was replaced"
[[ "$(readlink "$EXPORT_ROOT/output-link")" == "$final_link_before" ]] \
    || fail "final destination symlink changed"

ln -s -- "missing-target.txt" "$EXPORT_ROOT/dangling-link"
dangling_before="$(readlink "$EXPORT_ROOT/dangling-link")"
expect_export_failure \
    dangling-symlink "$DEVELOPER_PROJECT_ID" "$DEVELOPER_PLAN_ID" markdown \
    "$EXPORT_ROOT/dangling-link" "Artifact output must not be a symlink"
[[ -L "$EXPORT_ROOT/dangling-link" ]] \
    || fail "dangling symlink was replaced"
[[ "$(readlink "$EXPORT_ROOT/dangling-link")" == "$dangling_before" ]] \
    || fail "dangling symlink changed"
assert_absent "$EXPORT_ROOT/missing-target.txt"

mkdir "$EXPORT_ROOT/real-parent"
ln -s -- "real-parent" "$EXPORT_ROOT/linked-parent"
expect_export_failure \
    parent-symlink "$DEVELOPER_PROJECT_ID" "$DEVELOPER_PLAN_ID" markdown \
    "$EXPORT_ROOT/linked-parent/result.md" \
    "Artifact output parent must not be a symlink"
assert_absent "$EXPORT_ROOT/real-parent/result.md"

expect_export_failure \
    missing-parent "$DEVELOPER_PROJECT_ID" "$DEVELOPER_PLAN_ID" markdown \
    "$EXPORT_ROOT/missing-parent/result.md" \
    "Artifact output parent does not exist"
[[ ! -d "$EXPORT_ROOT/missing-parent" ]] \
    || fail "product created the missing parent directory"

structured_text="$EXPORT_ROOT/structured.txt"
expect_export_failure \
    structured-text "$DEVELOPER_PROJECT_ID" "$DEVELOPER_PLAN_ID" text \
    "$structured_text" "does not support format text"
assert_absent "$structured_text"

generated_markdown="$EXPORT_ROOT/generated.md"
expect_export_failure \
    generated-markdown "$RESEARCH_PROJECT_ID" "$GENERATED_FILE_ID" markdown \
    "$generated_markdown" "does not support format markdown"
assert_absent "$generated_markdown"

foreign_output="$EXPORT_ROOT/foreign.md"
expect_export_failure \
    foreign-artifact "$DEVELOPER_PROJECT_ID" "$FOREIGN_ARTIFACT_ID" markdown \
    "$foreign_output" "Project artifact not found: $FOREIGN_ARTIFACT_ID"
assert_absent "$foreign_output"

missing_run_output="$EXPORT_ROOT/missing-run.md"
expect_export_failure \
    missing-linked-run "$MISSING_PROJECT_ID" "$DEVELOPER_PLAN_ID" markdown \
    "$missing_run_output" "Linked Developer run not found: $MISSING_RUN_ID"
assert_absent "$missing_run_output"

extension_output="$EXPORT_ROOT/explicit-format.txt"
extension_summary="$HARNESS_OUTPUT/extension-export.stdout"
project_session export-artifact \
    "$DEVELOPER_PROJECT_ID" "$DEVELOPER_PLAN_ID" \
    --format markdown --output "$extension_output" > "$extension_summary"
cmp -s "$extension_output" "$HARNESS_OUTPUT/developer-plan-rendered.md" \
    || fail "filename extension changed explicit Markdown format"
assert_file_contains "$extension_summary" "Format: markdown"

[[ -z "$(find "$EXPORT_ROOT" -maxdepth 1 -type f -name '.*.tmp' -print -quit)" ]] \
    || fail "a successful export leaked a temporary hard link"

after_projects="$(find "$PROJECT_STORE" -type f -name '*.json' -print0 | sort -z | xargs -0 sha256sum)"
after_developer="$(sha256sum "$DEVELOPER_STORE/$DEVELOPER_RUN_ID.json")"
after_research="$(sha256sum "$RESEARCH_STORE/$RESEARCH_RUN_ID.json")"
after_all="$(snapshot_digest)"
[[ "$before_projects" == "$after_projects" ]] || fail "ProjectSession snapshots changed"
[[ "$before_developer" == "$after_developer" ]] || fail "Developer run changed"
[[ "$before_research" == "$after_research" ]] || fail "Researcher run changed"
[[ "$before_all" == "$after_all" ]] || fail "authoritative store files changed"

after_workspace_hash="$(sha256sum "$WORKSPACE/live-workspace-sentinel.txt")"
after_workspace_count="$(find "$WORKSPACE" -type f | wc -l)"
[[ "$before_workspace_hash" == "$after_workspace_hash" ]] \
    || fail "Developer workspace sentinel changed"
[[ "$before_workspace_count" == "$after_workspace_count" ]] \
    || fail "Developer workspace file count changed"
if grep -Fq -- "$WORKSPACE_SENTINEL" "$developer_output"; then
    fail "Developer export included live workspace sentinel content"
fi

expected_inventory="$HARNESS_OUTPUT/expected-export-inventory.txt"
actual_inventory="$HARNESS_OUTPUT/actual-export-inventory.txt"
cat > "$expected_inventory" <<'EOF'
dangling-link|l|missing-target.txt
developer-plan.md|f|
existing.txt|f|
explicit-format.txt|f|
generated-file.txt|f|
linked-parent|l|real-parent
output-link|l|real-target.txt
real-parent|d|
real-target.txt|f|
EOF
directory_inventory > "$actual_inventory"
cmp -s "$expected_inventory" "$actual_inventory" \
    || fail "export directory contains unexpected product or temporary outputs"

echo "PHASE_4A3_3_CLI_ACCEPTANCE=PASSED"
