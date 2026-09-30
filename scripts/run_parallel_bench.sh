#!/usr/bin/env bash
# Launch parallel benchmark workers: one per scenario on separate JEVRAG_DATA_DIRs.
#
# Usage:
#   bash scripts/run_parallel_bench.sh --arms "base,gate-none" --scenarios "squad,hotpotqa" [--label "my-run"]
#
# This creates backend/data_par/<scenario>/ for each scenario, launches detached
# workers via setsid nohup, and prints merge instructions when done.
#
# Prerequisites:
#   - Backend venv set up (scripts/setup_backend.sh)
#   - Local models built (scripts/setup_local_models.sh)
#   - backend/.env configured with API keys
#
# After workers complete, merge results with:
#   cd backend && .venv/bin/python scripts/_merge_par_run.py --run-ids <run_id_per_scenario>
#
# See: AGENTS.md § "Benchmarks may run with parallel workers"
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND="$REPO_ROOT/backend"

# Default values
ARMS="${ARMS:-base,gate-none,always-hard,oracle-gate}"
SCENARIOS="${SCENARIOS:-squad,hotpotqa,triviaqa,wiki2,musique}"
LABEL="${LABEL:-parallel-bench}"
MAX_PER_SCENARIO="${MAX_PER_SCENARIO:-0}"  # 0 = all questions
WINDOW_MINUTES="${WINDOW_MINUTES:-100000}"  # effectively unlimited

# Parse args
while [[ $# -gt 0 ]]; do
    case "$1" in
        --arms) ARMS="$2"; shift 2 ;;
        --scenarios) SCENARIOS="$2"; shift 2 ;;
        --label) LABEL="$2"; shift 2 ;;
        --max-per-scenario) MAX_PER_SCENARIO="$2"; shift 2 ;;
        --window-minutes) WINDOW_MINUTES="$2"; shift 2 ;;
        *) echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
done

# Convert comma-separated to arrays
IFS=',' read -ra SCENARIO_ARR <<< "$SCENARIOS"
IFS=',' read -ra ARM_ARR <<< "$ARMS"

NUM_SCENARIOS="${#SCENARIO_ARR[@]}"
NUM_ARMS="${#ARM_ARR[@]}"

echo "========================================"
echo "Parallel Benchmark Launch"
echo "========================================"
echo "Arms: $ARMS"
echo "Scenarios: $SCENARIOS"
echo "Label: $LABEL"
echo "Max per scenario: $MAX_PER_SCENARIO"
echo "Window minutes: $WINDOW_MINUTES"
echo "Workers: $NUM_SCENARIOS"
echo ""

# Check prerequisites
if [[ ! -d "$BACKEND/.venv" ]]; then
    echo "ERROR: Backend venv not found. Run: bash scripts/setup_backend.sh" >&2
    exit 1
fi

if [[ ! -f "$BACKEND/.env" ]]; then
    echo "ERROR: backend/.env not found. Copy from backend/.env.example and configure." >&2
    exit 1
fi

# Create data directories and launch workers
declare -a RUN_IDS
declare -a LOG_FILES

for scenario in "${SCENARIO_ARR[@]}"; do
    # Trim whitespace
    scenario=$(echo "$scenario" | xargs)
    
    # Create data directory for this scenario
    DATA_DIR="$BACKEND/data_par/$scenario"
    mkdir -p "$DATA_DIR"
    
    LOG_FILE="$DATA_DIR/bench.log"
    LOG_FILES+=("$LOG_FILE")
    
    echo "Launching worker for scenario: $scenario"
    echo "  Data dir: $DATA_DIR"
    echo "  Log file: $LOG_FILE"
    
    # Launch worker in background with separate JEVRAG_DATA_DIR
    # Use setsid to create new session, nohup to detach, redirect output to log
    JEVRAG_DATA_DIR="$DATA_DIR" \
    nohup setsid "$BACKEND/.venv/bin/python" "$BACKEND/scripts/run_testbench.py" \
        --arms "$ARMS" \
        --scenarios "$scenario" \
        --label "$LABEL-$scenario" \
        --max-per-scenario "$MAX_PER_SCENARIO" \
        --window-minutes "$WINDOW_MINUTES" \
        > "$LOG_FILE" 2>&1 &
    
    PID=$!
    echo "  PID: $PID"
    
    # Give each worker a moment to start and capture run_id from first log line
    sleep 2
    
    # Extract run_id from log (first line contains it after "testbench <run_id>")
    if [[ -f "$LOG_FILE" ]]; then
        RUN_ID=$(grep -oP 'testbench \K[a-f0-9-]{36}' "$LOG_FILE" | head -1 || true)
        if [[ -n "$RUN_ID" ]]; then
            RUN_IDS+=("$scenario:$RUN_ID")
            echo "  Run ID: $RUN_ID"
        fi
    fi
    
    echo ""
done

echo "========================================"
echo "All workers launched!"
echo "========================================"
echo ""
echo "Monitor progress:"
for scenario in "${SCENARIO_ARR[@]}"; do
    scenario=$(echo "$scenario" | xargs)
    echo "  tail -f $BACKEND/data_par/$scenario/bench.log"
done
echo ""
echo "Check worker status:"
echo "  ps aux | grep run_testbench.py"
echo ""
echo "Kill all workers (if needed):"
echo "  pkill -f run_testbench.py"
echo ""

# Print merge instructions
echo "========================================"
echo "After completion, merge results:"
echo "========================================"
echo ""
echo "1. Wait for all workers to complete (check logs for 'completed' status)"
echo ""
echo "2. Run the merge script:"
echo "   cd $BACKEND"
echo "   .venv/bin/python scripts/_merge_par_run.py \\"

# Build the --run-ids argument
RUN_IDS_ARG=""
for entry in "${RUN_IDS[@]}"; do
    if [[ -n "$RUN_IDS_ARG" ]]; then
        RUN_IDS_ARG="$RUN_IDS_ARG,"
    fi
    RUN_IDS_ARG="$RUN_IDS_ARG$entry"
done

if [[ -n "$RUN_IDS_ARG" ]]; then
    echo "     --run-ids $RUN_IDS_ARG \\"
fi
echo "     --arms $ARMS \\"
echo "     --scenarios $SCENARIOS \\"
echo "     --label \"$LABEL (merged)\""
echo ""
echo "3. Analyze merged results:"
echo "   JEVRAG_DATA_DIR=$BACKEND/data_merged .venv/bin/python scripts/analyze_testbench.py <merged-run-id> --out ../docs/benchmark-results.md"
echo ""

# Save run info to a metadata file
META_FILE="$BACKEND/data_par/parallel_run_meta.json"
cat > "$META_FILE" << EOF
{
    "label": "$LABEL",
    "arms": "$ARMS",
    "scenarios": "$SCENARIOS",
    "max_per_scenario": $MAX_PER_SCENARIO,
    "window_minutes": $WINDOW_MINUTES,
    "num_workers": $NUM_SCENARIOS,
    "launched_at": "$(date -Iseconds)",
    "run_ids": {
$(for i in "${!RUN_IDS[@]}"; do
    entry="${RUN_IDS[$i]}"
    scenario="${entry%%:*}"
    run_id="${entry#*:}"
    comma=","
    if [[ $i -eq $((${#RUN_IDS[@]} - 1)) ]]; then comma=""; fi
    echo "        \"$scenario\": \"$run_id\"$comma"
done)
    }
}
EOF
echo "Metadata saved to: $META_FILE"