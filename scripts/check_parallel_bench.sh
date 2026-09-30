#!/usr/bin/env bash
# Check status of parallel benchmark workers.
#
# Usage:
#   bash scripts/check_parallel_bench.sh [--json]
#
# Shows:
#   - Running workers (PIDs)
#   - Per-scenario progress (from log files)
#   - Estimated completion time
#
# Exit codes:
#   0 - All workers completed
#   1 - Some workers still running
#   2 - No workers found
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND="$REPO_ROOT/backend"
DATA_PAR="$BACKEND/data_par"

OUTPUT_JSON="${1:-}" == "--json"

# Find running workers
WORKERS=$(pgrep -f "run_testbench.py" || true)
NUM_WORKERS=$(echo "$WORKERS" | grep -c . || echo "0")

if [[ "$NUM_WORKERS" -eq 0 ]]; then
    if [[ "$OUTPUT_JSON" == "--json" ]]; then
        echo '{"status": "no_workers", "running": false}'
    else
        echo "No benchmark workers currently running."
    fi
    exit 2
fi

# Check each scenario's log
declare -A STATUS_MAP
COMPLETED=0
TOTAL_PROGRESS=0
TOTAL_DONE=0

for log_file in "$DATA_PAR"/*/bench.log; do
    if [[ ! -f "$log_file" ]]; then
        continue
    fi
    
    scenario=$(basename "$(dirname "$log_file")")
    
    # Check if completed
    if grep -q "status=completed" "$log_file" 2>/dev/null || grep -q "run_id:.*completed" "$log_file" 2>/dev/null; then
        STATUS_MAP[$scenario]="completed"
        ((COMPLETED++)) || true
    elif grep -q "testbench" "$log_file" 2>/dev/null; then
        # Extract progress from log
        progress=$(grep -oP '\[(\d+)/(\d+)\]' "$log_file" | tail -1 || echo "")
        if [[ -n "$progress" ]]; then
            done=$(echo "$progress" | grep -oP '\[\K\d+' || echo "0")
            total=$(echo "$progress" | grep -oP '/\K\d+' || echo "0")
            STATUS_MAP[$scenario]="running ($done/$total)"
            ((TOTAL_DONE += done)) || true
            ((TOTAL_PROGRESS += total)) || true
        else
            STATUS_MAP[$scenario]="starting"
        fi
    else
        STATUS_MAP[$scenario]="unknown"
    fi
done

if [[ "$OUTPUT_JSON" == "--json" ]]; then
    echo "{"
    echo "  \"status\": \"running\","
    echo "  \"num_workers\": $NUM_WORKERS,"
    echo "  \"completed\": $COMPLETED,"
    echo "  \"total_progress\": $TOTAL_PROGRESS,"
    echo "  \"total_done\": $TOTAL_DONE,"
    echo "  \"scenarios\": {"
    first=true
    for scenario in "${!STATUS_MAP[@]}"; do
        if [[ "$first" != "true" ]]; then
            echo ","
        fi
        first=false
        echo -n "    \"$scenario\": \"${STATUS_MAP[$scenario]}\""
    done
    echo ""
    echo "  }"
    echo "}"
else
    echo "========================================"
    echo "Parallel Benchmark Status"
    echo "========================================"
    echo ""
    echo "Running workers: $NUM_WORKERS"
    echo "Completed scenarios: $COMPLETED"
    if [[ "$TOTAL_PROGRESS" -gt 0 ]]; then
        PCT=$((TOTAL_DONE * 100 / TOTAL_PROGRESS))
        echo "Overall progress: $TOTAL_DONE/$TOTAL_PROGRESS ($PCT%)"
    fi
    echo ""
    echo "Per-scenario status:"
    for scenario in "${!STATUS_MAP[@]}"; do
        echo "  $scenario: ${STATUS_MAP[$scenario]}"
    done
    echo ""
    echo "Worker PIDs: $WORKERS"
fi

# Exit 0 if all completed, 1 if still running
if [[ "$COMPLETED" -eq "${#STATUS_MAP[@]}" ]]; then
    exit 0
else
    exit 1
fi