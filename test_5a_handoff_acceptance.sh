#!/usr/bin/env bash
set -euo pipefail
ROOT="$(mktemp -d)"
trap 'rm -rf "$ROOT"' EXIT
export HOME="$ROOT/home"
export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/ai-agent-5a-acceptance-cache}"
unset OPENAI_API_KEY
mkdir -p "$HOME" "$ROOT/workspace" "$ROOT/projects" "$HOME/.local/share/ai-agent/research-runs" "$HOME/.local/share/ai-agent/developer-runs"

SEED_JSON="$(ROOT="$ROOT" python - <<'PY'
import json, os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4
from tests.agent.test_research_implementation import _approved_run, _implementation_plan, _package
from ai_agent_project.agent.project_session import ProjectModeProposal, ProjectSession, ProjectStatus
from ai_agent_project.agent.project_session_file_store import FileProjectStore
from ai_agent_project.agent.research import ResearchStatus, WorkMode
from ai_agent_project.agent.research_file_store import FileResearchRunStore
from ai_agent_project.agent.upgrade import ProjectMode
root=Path(os.environ['ROOT']); research_id, project_id = str(uuid4()), str(uuid4())
plan=_implementation_plan(); run=_approved_run().model_copy(update={'implementation_plan': plan, 'implementation_package': _package(plan), 'status': ResearchStatus.IMPLEMENTATION_PACKAGE_READY})
FileResearchRunStore(root/'home/.local/share/ai-agent/research-runs').create(research_id, run)
now=datetime.now(UTC); proposal=ProjectModeProposal(proposed_work_mode=WorkMode.HYBRID, proposed_project_mode=ProjectMode.NEW, rationale='acceptance')
project=ProjectSession(project_id=project_id,title='Acceptance',original_request='handoff',status=ProjectStatus.ACTIVE,mode_proposal=proposal,work_mode=WorkMode.HYBRID,project_mode=ProjectMode.NEW,developer_run_id=None,research_run_id=research_id,created_at=now,updated_at=now)
FileProjectStore(root/'projects').create(project_id, project)
print(json.dumps({'project_id':project_id,'research_id':research_id}))
PY
)"
PROJECT_ID="$(python -c 'import json,sys; print(json.load(sys.stdin)["project_id"])' <<<"$SEED_JSON")"
ARTIFACT_LINE="$(uv run ai-agent project-session --store-root "$ROOT/projects" artifacts "$PROJECT_ID" | grep 'research_implementation_plan')"
ARTIFACT_ID="$(awk -F'|' '{gsub(/^- +| +$/,"",$1); print $1}' <<<"$ARTIFACT_LINE")"
[[ -n "$ARTIFACT_ID" ]]
REGISTERED="$(uv run ai-agent project-session --store-root "$ROOT/projects" handoff-artifact "$PROJECT_ID" "$ARTIFACT_ID" --to developer --purpose developer-bootstrap-context)"
HANDOFF_ID="$(awk -F': ' '/Handoff ID:/{print $2}' <<<"$REGISTERED")"; DIGEST="$(awk -F': ' '/SHA-256:/{print $2}' <<<"$REGISTERED")"
grep -q 'Project ID:' <<<"$REGISTERED"; grep -q 'Artifact ID:' <<<"$REGISTERED"; grep -q 'Source run ID:' <<<"$REGISTERED"; grep -q 'Purpose:' <<<"$REGISTERED"; [[ ${#DIGEST} -eq 64 ]]
LISTED="$(uv run ai-agent project-session --store-root "$ROOT/projects" handoffs "$PROJECT_ID")"; grep -q "$HANDOFF_ID" <<<"$LISTED"; grep -q available <<<"$LISTED"; ! grep -q Content <<<"$LISTED"
REPEAT="$(uv run ai-agent project-session --store-root "$ROOT/projects" handoff-artifact "$PROJECT_ID" "$ARTIFACT_ID" --to developer --purpose developer-bootstrap-context)"; grep -q "$HANDOFF_ID" <<<"$REPEAT"; [[ "$(find "$ROOT/projects/handoffs" -name '*.json' | wc -l)" -eq 1 ]]
HANDOFF_FILE="$ROOT/projects/handoffs/$HANDOFF_ID.json" HANDOFF_ID="$HANDOFF_ID" ARTIFACT_ID="$ARTIFACT_ID" python - <<'PY'
import json, os
d=json.load(open(os.environ['HANDOFF_FILE']))
assert set(d)=={'handoff_id','project_id','source_domain','source_run_id','artifact_id','content_sha256','purpose','created_at'}
assert d['handoff_id']==os.environ['HANDOFF_ID'] and d['artifact_id']==os.environ['ARTIFACT_ID'] and d['source_domain']=='researcher'
PY
GENERATED_ID="$(uv run ai-agent project-session --store-root "$ROOT/projects" artifacts "$PROJECT_ID" | grep 'research_generated_file' | head -1 | awk -F'|' '{gsub(/^- +| +$/,"",$1); print $1}')"
[[ -n "$GENERATED_ID" ]]
GEN="$(uv run ai-agent project-session --store-root "$ROOT/projects" handoff-artifact "$PROJECT_ID" "$GENERATED_ID" --to developer --purpose developer-bootstrap-context)"
grep -q 'Artifact ID:' <<<"$GEN"
ROOT="$ROOT" PROJECT_ID="$PROJECT_ID" HANDOFF_ID="$HANDOFF_ID" ARTIFACT_ID="$ARTIFACT_ID" python - <<'PY'
import json, os, subprocess
from pathlib import Path
from tests.agent.test_research_implementation import _approved_run, _implementation_plan, _package
from ai_agent_project.agent.project_session_file_store import FileProjectStore
from ai_agent_project.agent.research import ResearchStatus
from ai_agent_project.agent.research_file_store import FileResearchRunStore
root=Path(os.environ['ROOT']); project=os.environ['PROJECT_ID']; handoff=os.environ['HANDOFF_ID']; artifact=os.environ['ARTIFACT_ID']; home=root/'home'; ps=FileProjectStore(root/'projects'); rs=FileResearchRunStore(home/'.local/share/ai-agent/research-runs')
def cli(*args, ok=True):
    p=subprocess.run(['uv','run','ai-agent','project-session','--store-root',str(root/'projects'),*args],text=True,capture_output=True)
    assert (p.returncode==0)==ok, p.stderr
    return p.stdout
orig=ps.get(project); run_id=orig.research_run_id; assert run_id
other=str(next(p.stem for p in (home/'.local/share/ai-agent/research-runs').glob('*.json') if p.stem!=run_id)) if len(list((home/'.local/share/ai-agent/research-runs').glob('*.json')))>1 else run_id
if other==run_id:
    from uuid import uuid4
    other=str(uuid4()); rs.create(other, _approved_run().model_copy(update={'implementation_plan':_implementation_plan(),'status':ResearchStatus.IMPLEMENTATION_GENERATION_STARTED}))
ps.replace(project,orig.model_copy(update={'research_run_id':other})); assert 'source_rebound' in cli('handoffs',project)
ps.replace(project,orig); assert 'available' in cli('handoffs',project)
rs.replace(run_id,_approved_run()); assert 'artifact_missing' in cli('handoffs',project)
plan=_implementation_plan().model_copy(update={'package_summary':'changed'}); rs.replace(run_id,_approved_run().model_copy(update={'implementation_plan':plan,'implementation_package':_package(plan),'status':ResearchStatus.IMPLEMENTATION_PACKAGE_READY})); assert 'content_mismatch' in cli('handoffs',project)
(home/'.local/share/ai-agent/research-runs'/f'{run_id}.json').unlink(); assert 'source_missing' in cli('handoffs',project)
d=json.loads((root/'projects/handoffs'/f'{handoff}.json').read_text()); assert d['artifact_id']==artifact and d['content_sha256']
print('matrix-ok')
PY
[[ "$(find "$ROOT/projects/handoffs" -name '*.json' | wc -l)" -eq 2 ]]
[[ "$(find "$ROOT/workspace" -type f | wc -l)" -eq 0 ]]
echo PHASE_5A_CLI_ACCEPTANCE=PASSED
