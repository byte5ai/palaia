#!/usr/bin/env bash
# Starts the remote-upstream server and the gateway, runs every scripted
# check for SPEC-002, saves transcripts under transcripts/, then tears both
# servers down. Run from the v3/spikes/gateway/ directory:
#
#   bash scripts/run_all.sh
set -euo pipefail
cd "$(dirname "$0")/.."

mkdir -p transcripts
REMOTE_LOG=transcripts/remote_upstream.log
GATEWAY_LOG=transcripts/gateway.log

echo "== starting remote-upstream on :8811 =="
uv run python servers/remote_upstream.py > "$REMOTE_LOG" 2>&1 &
REMOTE_PID=$!

echo "== starting gateway on :8900 =="
uv run python gateway.py > "$GATEWAY_LOG" 2>&1 &
GATEWAY_PID=$!

cleanup() {
  echo "== stopping gateway (pid $GATEWAY_PID) and remote-upstream (pid $REMOTE_PID) =="
  kill "$GATEWAY_PID" "$REMOTE_PID" 2>/dev/null || true
  wait "$GATEWAY_PID" 2>/dev/null || true
  wait "$REMOTE_PID" 2>/dev/null || true
}
trap cleanup EXIT

# Give uvicorn a moment to bind.
for _ in $(seq 1 20); do
  if curl -s -o /dev/null "http://127.0.0.1:8900/mcp/full/" ; then
    break
  fi
  sleep 0.5
done

FULL_TOKEN="full-profile-secret-token"
MEMORY_TOKEN="memory-only-profile-secret-token"

run() {
  local name="$1"; shift
  echo "===== $name =====" | tee "transcripts/$name.log"
  ("$@") 2>&1 | tee -a "transcripts/$name.log"
}

run "q1_q2_full_tool_list" \
  uv run python scripts/mcp_client.py full "$FULL_TOKEN"

run "q1_q2_memory_only_tool_list" \
  uv run python scripts/mcp_client.py memory-only "$MEMORY_TOKEN"

run "q1_call_local_tool_via_full" \
  uv run python scripts/mcp_client.py full "$FULL_TOKEN" \
  local_memory_search '{"query": "onboarding"}'

run "q1_call_remote_tool_via_full" \
  uv run python scripts/mcp_client.py full "$FULL_TOKEN" \
  remote_say '{"text": "hello from the spike"}'

run "q4_original_remote_name_absent" \
  uv run python scripts/mcp_client.py full "$FULL_TOKEN" \
  remote_echo '{"text": "should not exist"}'

run "q3_wrong_token_rejected" \
  uv run python scripts/mcp_client.py full "wrong-token-entirely"

run "q3_cross_profile_token_rejected" \
  uv run python scripts/mcp_client.py memory-only "$FULL_TOKEN"

echo "== all scripted checks complete, see transcripts/*.log =="
