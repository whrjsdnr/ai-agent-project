#!/usr/bin/env bash
set -euo pipefail

RUN_ID=c6307b84-72b3-48ba-baf9-cce2e5dc1b0f
STORE_ROOT=/home/geonug/.local/share/ai-agent/3b2-cli-acceptance
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

step "1. Status after direction selection"
run_research status "$RUN_ID"

step "2. Generate research plan"
run_research plan "$RUN_ID"

step "3. Show research plan"
run_research show-plan "$RUN_ID"

step "4. Approve research plan"
run_research approve-plan "$RUN_ID"

step "5. Verify approved plan status"
run_research status "$RUN_ID"

step "6. Generate implementation plan"
run_research implementation-plan "$RUN_ID"

step "7. Show implementation plan"
run_research show-implementation-plan "$RUN_ID"

step "8. Verify implementation generation status"
run_research status "$RUN_ID"

step "9. Generate implementation package"
run_research generate-package "$RUN_ID"

step "10. Show implementation package"
run_research show-package "$RUN_ID"

step "11. Final persisted status"
run_research status "$RUN_ID"

step "3B-2 CLI ACCEPTANCE COMPLETED"
echo "RUN_ID=$RUN_ID"
echo "STORE_ROOT=$STORE_ROOT"
echo
echo "Expected final status: implementation_package_ready"
echo "Verify:"
echo "  - selected direction unchanged"
echo "  - approved plan version unchanged"
echo "  - generated_not_executed=true"
echo "  - artifact paths are relative"
