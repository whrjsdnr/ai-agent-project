RUN_ID=c6307b84-72b3-48ba-baf9-cce2e5dc1b0f
STORE_ROOT=/home/geonug/.local/share/ai-agent/3b2-cli-acceptance

uv run ai-agent research \
  --store-root "$STORE_ROOT" \
  directions "$RUN_ID"
uv run ai-agent research \
  --store-root "$STORE_ROOT" \
  select-direction "$RUN_ID" D1
uv run ai-agent research \
  --store-root "$STORE_ROOT" \
  status "$RUN_ID"
