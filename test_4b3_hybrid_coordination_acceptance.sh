#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ACCEPTANCE_ROOT="$(mktemp -d /tmp/ai-agent-4b3-cli.XXXXXX)"
UV_CACHE_DIR="$(mktemp -d /tmp/ai-agent-4b3-uv-cache.XXXXXX)"
export UV_CACHE_DIR
export PYTHONDONTWRITEBYTECODE=1
cleanup() {
  rm -rf -- "$UV_CACHE_DIR" "$ACCEPTANCE_ROOT"
}
trap cleanup EXIT
cd "$REPO_ROOT"
env -u OPENAI_API_KEY uv run python ./test_4b3_api_acceptance.py \
  --cli --root "$ACCEPTANCE_ROOT"
