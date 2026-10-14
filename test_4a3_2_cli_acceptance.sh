#!/usr/bin/env bash
set -euo pipefail

ORIGINAL_HOME="$HOME"
ACCEPTANCE_ROOT="$ORIGINAL_HOME/.local/share/ai-agent/4a3-2-cli-acceptance"
export HOME="$ACCEPTANCE_ROOT/home"
PROJECT_STORE="$ACCEPTANCE_ROOT/project-sessions"
DEVELOPER_STORE="$HOME/.local/share/ai-agent/project-runs"
RESEARCH_STORE="$HOME/.local/share/ai-agent/research-runs"
WORKSPACE="$ACCEPTANCE_ROOT/developer-workspace"
HARNESS_OUTPUT="$ACCEPTANCE_ROOT/harness-output"
PRODUCT_EXPORT_OUTPUT="$ACCEPTANCE_ROOT/product-export-output"
IDS_FILE="$ACCEPTANCE_ROOT/ids.env"
WORKSPACE_SENTINEL="DEVELOPER_WORKSPACE_MUST_REMAIN_UNREAD_4A3_2"

rm -rf -- "$ACCEPTANCE_ROOT"
mkdir -p -- \
    "$PROJECT_STORE" "$DEVELOPER_STORE" "$RESEARCH_STORE" "$WORKSPACE" \
    "$HARNESS_OUTPUT" "$PRODUCT_EXPORT_OUTPUT"
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

assert_file_excludes() {
    local path="$1"
    local prohibited="$2"
    if grep -Fq -- "$prohibited" "$path"; then
        fail "$path unexpectedly contains: $prohibited"
    fi
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

snapshot_digest() {
    find "$PROJECT_STORE" "$DEVELOPER_STORE" "$RESEARCH_STORE" \
        -type f -name '*.json' -print0 \
        | sort -z \
        | xargs -0 sha256sum \
        | sha256sum \
        | awk '{print $1}'
}

export PROJECT_STORE DEVELOPER_STORE RESEARCH_STORE WORKSPACE IDS_FILE

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
from ai_agent_project.agent.research import ResearchRun, WorkMode
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
developer_specification = developer.specification.model_copy(
    update={
        "summary": "# heading\n* star\n| pipe\n`code`\n<angle>\n[brackets]"
    }
)
developer = ProjectRun.model_validate(
    developer.model_copy(update={"specification": developer_specification}).model_dump()
)

research = _terminal_research_run()
assert research.implementation_package is not None
assert research.implementation_package.artifacts
exact_content = (
    "line one\n"
    "  indented line with # heading * star | pipe `code` <angle> [brackets]\n"
    "\n"
    "line four"
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
selected = next(
    item for item in research.report.directions if item.id == research.selected_direction_id
)
escaped_selected = selected.model_copy(
    update={"title": "# heading * star | pipe `code` <angle> [brackets]"}
)
report = research.report.model_copy(
    update={
        "directions": tuple(
            escaped_selected if item.id == selected.id else item
            for item in research.report.directions
        )
    }
)
research = ResearchRun.model_validate(
    research.model_copy(
        update={"implementation_package": package, "report": report}
    ).model_dump()
)

developer_run_id = identifier()
research_run_id = identifier()
developer_store.create(developer_run_id, developer)
research_store.create(research_run_id, research)


def project(name: str, mode: WorkMode) -> str:
    project_id = identifier()
    project_store.create(
        project_id,
        ProjectSession.awaiting_confirmation(
            project_id=project_id,
            title=name,
            original_request=f"Phase 4A-3.2 acceptance: {name}",
            mode_proposal=ProjectModeProposal(
                proposed_work_mode=mode,
                proposed_project_mode=ProjectMode.NEW,
                rationale="Trusted offline fixture",
            ),
        ),
    )
    session_service.confirm_project_mode(project_id, mode, ProjectMode.NEW)
    return project_id


developer_project_id = project("Developer rendering", WorkMode.DEVELOPER)
session_service.bind_developer_run(developer_project_id, developer_run_id)
research_project_id = project("Researcher rendering", WorkMode.RESEARCHER)
session_service.bind_research_run(research_project_id, research_run_id)

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
    "DEV_SPEC_ID": one(developer_project_id, ProjectArtifactType.SPECIFICATION),
    "DEV_PLAN_ID": one(developer_project_id, ProjectArtifactType.PROJECT_PLAN),
    "DEV_EXECUTION_ID": one(
        developer_project_id, ProjectArtifactType.EXECUTION_STATE
    ),
    "RESEARCH_REQUEST_ID": one(
        research_project_id, ProjectArtifactType.RESEARCH_REQUEST
    ),
    "DISCOVERY_ID": one(research_project_id, ProjectArtifactType.DISCOVERY_REPORT),
    "DIRECTION_ID": one(research_project_id, ProjectArtifactType.SELECTED_DIRECTION),
    "RESEARCH_PLAN_ID": one(research_project_id, ProjectArtifactType.RESEARCH_PLAN),
    "PACKAGE_ID": one(
        research_project_id, ProjectArtifactType.RESEARCH_IMPLEMENTATION_PACKAGE
    ),
    "GENERATED_FILE_ID": one(
        research_project_id, ProjectArtifactType.RESEARCH_GENERATED_FILE
    ),
    "RESULTS_ID": one(research_project_id, ProjectArtifactType.RESEARCH_RESULTS),
    "ANALYSIS_ID": one(
        research_project_id, ProjectArtifactType.RESEARCH_RESULT_ANALYSIS
    ),
    "SYNTHESIS_ID": one(research_project_id, ProjectArtifactType.RESEARCH_SYNTHESIS),
    "PAPER_ID": one(research_project_id, ProjectArtifactType.PAPER_MATERIALS),
    "GENERATED_ARTIFACT_ID": generated.artifact_id,
    "GENERATED_RELATIVE_PATH": generated.relative_path,
}
Path(os.environ["IDS_FILE"]).write_text(
    "".join(
        f"{key}={shlex.quote(value)}\n" for key, value in sorted(values.items())
    ),
    encoding="utf-8",
)
(Path(os.environ["IDS_FILE"]).parent / "authoritative-generated-content.bin").write_bytes(
    exact_content.encode("utf-8")
)
PY

# Fixture metadata is generated and shell-quoted by trusted Python setup.
# shellcheck disable=SC1090
set -a
source "$IDS_FILE"
set +a
ESCAPED_DEV_SPEC_ID="${DEV_SPEC_ID//-/\\-}"
ESCAPED_DEVELOPER_RUN_ID="${DEVELOPER_RUN_ID//-/\\-}"

before_digest="$(snapshot_digest)"
before_project="$(sha256sum "$PROJECT_STORE/$DEVELOPER_PROJECT_ID.json")"
before_developer="$(sha256sum "$DEVELOPER_STORE/$DEVELOPER_RUN_ID.json")"
before_research="$(sha256sum "$RESEARCH_STORE/$RESEARCH_RUN_ID.json")"

render_to "$DEVELOPER_PROJECT_ID" "$DEV_SPEC_ID" markdown "$HARNESS_OUTPUT/dev-spec.md"
for expected in \
    "# Developer specification" \
    "**Artifact ID:**" \
    "$ESCAPED_DEV_SPEC_ID" \
    "**Artifact type:** specification" \
    "**Source domain:** developer" \
    "**Source run ID:** $ESCAPED_DEVELOPER_RUN_ID" \
    "**Source version:** v1" \
    "Build it"; do
    assert_file_contains "$HARNESS_OUTPUT/dev-spec.md" "$expected"
done
for escaped in \
    '\# heading' '\* star' '\| pipe' '\`code\`' '&lt;angle&gt;' '\[brackets\]'; do
    assert_file_contains "$HARNESS_OUTPUT/dev-spec.md" "$escaped"
done

render_to "$DEVELOPER_PROJECT_ID" "$DEV_PLAN_ID" markdown "$HARNESS_OUTPUT/dev-plan-1.md"
render_to "$DEVELOPER_PROJECT_ID" "$DEV_PLAN_ID" markdown "$HARNESS_OUTPUT/dev-plan-2.md"
cmp -s "$HARNESS_OUTPUT/dev-plan-1.md" "$HARNESS_OUTPUT/dev-plan-2.md" \
    || fail "Developer project_plan Markdown is not byte-stable"
assert_file_contains "$HARNESS_OUTPUT/dev-plan-1.md" "Developer project plan v2"
assert_file_contains "$HARNESS_OUTPUT/dev-plan-1.md" "Revised"

render_to "$DEVELOPER_PROJECT_ID" "$DEV_EXECUTION_ID" markdown \
    "$HARNESS_OUTPUT/dev-execution.md"
assert_file_contains "$HARNESS_OUTPUT/dev-execution.md" "Developer execution state"
assert_file_contains "$HARNESS_OUTPUT/dev-execution.md" "awaiting\\_plan\\_approval"
assert_file_contains "$HARNESS_OUTPUT/dev-execution.md" "**attempt\\_count:** 0"
assert_file_contains "$HARNESS_OUTPUT/dev-execution.md" "**checkpoint:** null"

render_to "$RESEARCH_PROJECT_ID" "$RESEARCH_REQUEST_ID" markdown \
    "$HARNESS_OUTPUT/research-request.md"
render_to "$RESEARCH_PROJECT_ID" "$DISCOVERY_ID" markdown \
    "$HARNESS_OUTPUT/discovery.md"
render_to "$RESEARCH_PROJECT_ID" "$DIRECTION_ID" markdown \
    "$HARNESS_OUTPUT/direction-1.md"
render_to "$RESEARCH_PROJECT_ID" "$DIRECTION_ID" markdown \
    "$HARNESS_OUTPUT/direction-2.md"
cmp -s "$HARNESS_OUTPUT/direction-1.md" "$HARNESS_OUTPUT/direction-2.md" \
    || fail "selected_direction Markdown is not byte-stable"
for escaped in \
    '\# heading' '\* star' '\| pipe' '\`code\`' '&lt;angle&gt;' '\[brackets\]'; do
    assert_file_contains "$HARNESS_OUTPUT/direction-1.md" "$escaped"
done

render_to "$RESEARCH_PROJECT_ID" "$RESEARCH_PLAN_ID" markdown \
    "$HARNESS_OUTPUT/research-plan.md"
render_to "$RESEARCH_PROJECT_ID" "$PACKAGE_ID" markdown \
    "$HARNESS_OUTPUT/package.md"
assert_file_contains "$HARNESS_OUTPUT/package.md" "$GENERATED_ARTIFACT_ID"
assert_file_contains "$HARNESS_OUTPUT/package.md" "${GENERATED_RELATIVE_PATH//./\\.}"
assert_file_contains "$HARNESS_OUTPUT/package.md" "**generated\\_not\\_executed:** true"
assert_file_excludes "$HARNESS_OUTPUT/package.md" "line one"
assert_file_excludes "$HARNESS_OUTPUT/package.md" "indented line"

render_to "$RESEARCH_PROJECT_ID" "$RESULTS_ID" markdown \
    "$HARNESS_OUTPUT/results.md"
render_to "$RESEARCH_PROJECT_ID" "$ANALYSIS_ID" markdown \
    "$HARNESS_OUTPUT/analysis.md"
render_to "$RESEARCH_PROJECT_ID" "$SYNTHESIS_ID" markdown \
    "$HARNESS_OUTPUT/synthesis.md"
render_to "$RESEARCH_PROJECT_ID" "$PAPER_ID" markdown \
    "$HARNESS_OUTPUT/paper-1.md"
render_to "$RESEARCH_PROJECT_ID" "$PAPER_ID" markdown \
    "$HARNESS_OUTPUT/paper-2.md"
cmp -s "$HARNESS_OUTPUT/paper-1.md" "$HARNESS_OUTPUT/paper-2.md" \
    || fail "paper_materials Markdown is not byte-stable"

assert_file_contains "$HARNESS_OUTPUT/results.md" "not\\_executed"
assert_file_contains "$HARNESS_OUTPUT/analysis.md" "inconclusive"
assert_file_contains "$HARNESS_OUTPUT/synthesis.md" "inconclusive"
assert_file_contains "$HARNESS_OUTPUT/paper-1.md" "not\\_measured"
assert_file_contains "$HARNESS_OUTPUT/paper-1.md" "null"
assert_file_contains "$HARNESS_OUTPUT/results.md" "{}"
assert_file_contains "$HARNESS_OUTPUT/research-request.md" "null"
assert_file_contains "$HARNESS_OUTPUT/discovery.md" "[]"

render_to "$RESEARCH_PROJECT_ID" "$GENERATED_FILE_ID" text \
    "$HARNESS_OUTPUT/generated-1.bin"
render_to "$RESEARCH_PROJECT_ID" "$GENERATED_FILE_ID" text \
    "$HARNESS_OUTPUT/generated-2.bin"
cmp -s "$ACCEPTANCE_ROOT/authoritative-generated-content.bin" \
    "$HARNESS_OUTPUT/generated-1.bin" \
    || fail "generated-file text differs from authoritative bytes"
cmp -s "$HARNESS_OUTPUT/generated-1.bin" "$HARNESS_OUTPUT/generated-2.bin" \
    || fail "generated-file text is not byte-stable"
assert_file_contains "$HARNESS_OUTPUT/generated-1.bin" "# heading * star | pipe"
assert_file_excludes "$HARNESS_OUTPUT/generated-1.bin" '```'
assert_file_excludes "$HARNESS_OUTPUT/generated-1.bin" "Artifact ID"
last_byte="$(tail -c 1 "$HARNESS_OUTPUT/generated-1.bin" | od -An -t u1 | tr -d ' ')"
[[ "$last_byte" != "10" ]] || fail "generated text gained a trailing newline"

set +e
structured_error="$(project_session artifact \
    "$DEVELOPER_PROJECT_ID" "$DEV_SPEC_ID" --format text 2>&1)"
structured_status=$?
generated_error="$(project_session artifact \
    "$RESEARCH_PROJECT_ID" "$GENERATED_FILE_ID" --format markdown 2>&1)"
generated_status=$?
set -e
(( structured_status != 0 )) || fail "structured text rendering unexpectedly succeeded"
(( generated_status != 0 )) || fail "generated-file Markdown unexpectedly succeeded"
[[ "$structured_error" == *"does not support format text"* ]] \
    || fail "structured unsupported-format error was unclear"
[[ "$generated_error" == *"does not support format markdown"* ]] \
    || fail "generated-file unsupported-format error was unclear"

after_project="$(sha256sum "$PROJECT_STORE/$DEVELOPER_PROJECT_ID.json")"
after_developer="$(sha256sum "$DEVELOPER_STORE/$DEVELOPER_RUN_ID.json")"
after_research="$(sha256sum "$RESEARCH_STORE/$RESEARCH_RUN_ID.json")"
after_digest="$(snapshot_digest)"
[[ "$before_project" == "$after_project" ]] || fail "ProjectSession changed"
[[ "$before_developer" == "$after_developer" ]] || fail "Developer run changed"
[[ "$before_research" == "$after_research" ]] || fail "Researcher run changed"
[[ "$before_digest" == "$after_digest" ]] || fail "authoritative stores changed"

[[ "$(<"$WORKSPACE/live-workspace-sentinel.txt")" == "$WORKSPACE_SENTINEL" ]] \
    || fail "Developer workspace sentinel changed"
[[ "$(find "$WORKSPACE" -type f | wc -l)" -eq 1 ]] \
    || fail "Developer workspace was read into or modified by product output"
[[ -z "$(find "$PRODUCT_EXPORT_OUTPUT" -mindepth 1 -print -quit)" ]] \
    || fail "product artifact export output was created"

echo "PHASE_4A3_2_CLI_ACCEPTANCE=PASSED"
