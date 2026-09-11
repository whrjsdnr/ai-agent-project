#!/usr/bin/env bash
set -euo pipefail

RUN_ID="${RUN_ID:-ee8bf950-9288-4c0f-9490-3f6914741564}"
STORE_ROOT="${STORE_ROOT:-/tmp/ai-agent-research-3b1-cli-acceptance}"

run_research() {
    uv run ai-agent research \
        --store-root "$STORE_ROOT" \
        "$@"
}

step() {
    echo
    echo "============================================================"
    echo "$1"
    echo "============================================================"
}

step "0. Acceptance configuration"
echo "RUN_ID=$RUN_ID"
echo "STORE_ROOT=$STORE_ROOT"

step "1. Initial status — expected: research_plan_approved"
run_research status "$RUN_ID"

step "2. Generate implementation plan"
run_research implementation-plan "$RUN_ID"

step "3. Show persisted implementation plan"
run_research show-implementation-plan "$RUN_ID"

step "4. Status — expected: implementation_generation_started"
run_research status "$RUN_ID"

step "5. Generate implementation package"
run_research generate-package "$RUN_ID"

step "6. Show persisted implementation package"
run_research show-package "$RUN_ID"

step "7. Final status — expected: implementation_package_ready"
run_research status "$RUN_ID"

step "3B-2 CLI ACCEPTANCE COMMANDS COMPLETED"
echo "All commands exited successfully."
echo
echo "Manual verification:"
echo "  [ ] selected direction is still D1"
echo "  [ ] approved plan version is still v2"
echo "  [ ] final status is implementation_package_ready"
echo "  [ ] generated_not_executed is true"
echo "  [ ] all artifact paths are relative"
echo "  [ ] no /home/..., /tmp/..., C:\\..., or ../ artifact paths"
