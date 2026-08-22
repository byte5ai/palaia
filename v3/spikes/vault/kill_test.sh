#!/usr/bin/env bash
# SPEC-003 Q5 — atomicity under kill -9.
#
# Repeatedly: launch writer.py (atomic-write-then-git-commit loop), let it
# run for a short RANDOM delay so different trials interrupt it at
# different points (mid content write, mid rename, mid git add, mid git
# commit/index-write), SIGKILL it, then run checker.py against the vault
# it left behind.
#
# Usage: ./kill_test.sh [trials] [results_file]
set -euo pipefail

TRIALS="${1:-20}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESULTS_FILE="${2:-/tmp/kill_test_results.jsonl}"
: > "$RESULTS_FILE"

for i in $(seq 1 "$TRIALS"); do
  VAULT_DIR="$(mktemp -d /tmp/kill-vault.XXXXXX)"
  # `uv run` execs a *child* python process rather than replacing itself on
  # this platform (verified: `uv run writer.py` PID stays a separate uv
  # process, with the real interpreter as its child) — so we must kill by
  # matching the unique --vault-dir argument, not by the wrapper's PID,
  # or the actual writer keeps running (and racing the checker) after
  # `kill -9 $PID` returns.
  MATCH="writer.py --vault-dir $VAULT_DIR "
  uv run "$SCRIPT_DIR/writer.py" --vault-dir "$VAULT_DIR" --n 200000 >"$VAULT_DIR/.writer.stdout" 2>"$VAULT_DIR/.writer.stderr" &

  DELAY="$(python3 -c "import random; random.seed(${i}); print(round(random.uniform(0.05, 1.2), 3))")"
  sleep "$DELAY"

  # SIGKILL every process (uv wrapper + real interpreter) matching this
  # trial's unique vault path: uncatchable, no cleanup handler runs.
  pkill -9 -f "$MATCH" 2>/dev/null || true
  # Confirm nothing matching this trial is still alive before inspecting.
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    pgrep -f "$MATCH" >/dev/null 2>&1 || break
    sleep 0.1
    pkill -9 -f "$MATCH" 2>/dev/null || true
  done
  wait 2>/dev/null || true

  uv run "$SCRIPT_DIR/checker.py" --vault-dir "$VAULT_DIR" --trial "$i" --delay "$DELAY" >> "$RESULTS_FILE"
  echo "trial $i (delay=${DELAY}s) -> $(tail -n1 "$RESULTS_FILE")" 1>&2

  rm -rf "$VAULT_DIR"
done

echo "---"
echo "raw per-trial results: $RESULTS_FILE"
python3 - "$RESULTS_FILE" <<'PYEOF'
import json
import sys

path = sys.argv[1]
rows = [json.loads(l) for l in open(path) if l.strip()]
n = len(rows)
corrupt = sum(1 for r in rows if r["vault_corrupt"])
lock_present = sum(1 for r in rows if r["git_index_lock_present"])
recovered = sum(1 for r in rows if r["recovery_needed"] and r["recovery_sufficient_lock_removal_only"])
recovery_failed = sum(1 for r in rows if r["recovery_needed"] and not r["recovery_sufficient_lock_removal_only"])
rebuild_ok = sum(1 for r in rows if r["rebuild_error"] is None)

print(f"trials: {n}")
print(f"vault_corrupt (truncated/unparseable note, or rebuild crashed): {corrupt}/{n}")
print(f"git index.lock left behind: {lock_present}/{n}")
print(f"  of those, lock removal alone was sufficient recovery: {recovered}/{lock_present if lock_present else 0}")
print(f"  of those, lock removal was NOT sufficient: {recovery_failed}/{lock_present if lock_present else 0}")
print(f"index rebuildable from files afterwards: {rebuild_ok}/{n}")
PYEOF
