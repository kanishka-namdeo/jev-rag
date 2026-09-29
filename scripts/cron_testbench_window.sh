#!/usr/bin/env bash
# cron_testbench_window.sh — run ONE testbench window, cron-safe.
#
# Guards:
#  - flock (10 min non-blocking): if a previous window is still running, exit 0
#    immediately (no overlap, no SQLite contention).
#  - records heartbeat logs so the main agent can verify liveness.
#
# Usage: bash scripts/cron_testbench_window.sh RUN_ID ARMS SCENARIOS [WINDOW_MIN]
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_ID="${1:?run id required}"
ARMS="${2:-base,gate-none,always-hard,oracle-gate}"
SCENARIOS="${3:-squad,hotpotqa,triviaqa,wiki2,musique}"
WINDOW_MIN="${4:-8.8}"

LOCK="/tmp/jevrag_testbench.lock"
LOG="$REPO_ROOT/logs/testbench_cron.log"
STAMP="$(date -u '+%Y-%m-%d %H:%M:%S')"

exec 9>"$LOCK"
if ! flock -n 9; then
  echo "$STAMP [cron-window] another window holds the lock — skipping" >> "$LOG"
  exit 0
fi

echo "$STAMP [cron-window] starting window (run=$RUN_ID arms=$ARMS min=$WINDOW_MIN)" >> "$LOG"
cd "$REPO_ROOT/backend" || exit 1
timeout 585 .venv/bin/python scripts/run_testbench.py \
  --resume "$RUN_ID" --arms "$ARMS" --scenarios "$SCENARIOS" \
  --window-minutes "$WINDOW_MIN" >> "$LOG" 2>&1
rc=$?
echo "$STAMP [cron-window] window exit rc=$rc" >> "$LOG"
exit 0
