#!/usr/bin/env bash
set -euo pipefail

ROOT="$(mktemp -d /tmp/ai-agent-5b2-acceptance-XXXXXX)"
trap 'rm -rf "$ROOT"' EXIT
export HOME="$ROOT/home"
export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/ai-agent-5b2-acceptance-cache}"
unset OPENAI_API_KEY
mkdir -p "$HOME"

IDS="$(uv run python test_5b2_developer_bootstrap_acceptance.py --mode setup --root "$ROOT")"
export PHASE_5B2_IDS="$IDS"
mkdir -p "$HOME/.local/share/ai-agent"
ln -s "$ROOT/research" "$HOME/.local/share/ai-agent/research-runs"
ln -s "$ROOT/developer" "$HOME/.local/share/ai-agent/project-runs"
ln -s "$ROOT/handoffs" "$ROOT/projects/handoffs"
uv run python test_5b2_developer_bootstrap_acceptance.py --mode cli --root "$ROOT"
uv run python test_5b2_developer_bootstrap_acceptance.py --mode verify --root "$ROOT"
uv run python test_5b2_developer_bootstrap_acceptance.py --mode api --root "$ROOT"
uv run python test_5b2_developer_bootstrap_acceptance.py --mode failures --root "$ROOT"

echo PHASE_5B2_PERSISTENCE_ACCEPTANCE=PASSED
echo PHASE_5B2_PROVENANCE_ACCEPTANCE=PASSED
echo PHASE_5B2_PENDING_ACTION_ACCEPTANCE=PASSED
echo PHASE_5B2_NO_EXECUTION=PASSED
echo PHASE_5B2_MUTATION_ISOLATION=PASSED
echo PHASE_5B2_DUPLICATE_SAFETY=PASSED
echo PHASE_5B2_FAILURE_ATOMICITY=PASSED
echo PHASE_5B2_CLI_ACCEPTANCE=PASSED
echo PHASE_5B2_API_ACCEPTANCE=PASSED
echo PHASE_5B2_OFFLINE_ACCEPTANCE=PASSED
