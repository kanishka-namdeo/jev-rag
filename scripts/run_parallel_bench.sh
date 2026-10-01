#!/usr/bin/env bash
# Launch parallel benchmark workers: one per scenario on separate JEVRAG_DATA_DIRs.
#
# Binding spec: docs/parallel-bench-runbook.md (§"Worker contracts", §"Procedure").
# If you change a flag, the meta schema or the data-dir convention here, change the
# runbook + check_parallel_bench.sh + backend/scripts/_merge_par_run.py in the same commit.
#
# Usage:
#   bash scripts/run_parallel_bench.sh [options]
#
#   --driver testbench|resume   which worker runs each scenario (default: testbench)
#   --arms LIST                 comma-separated arms      (testbench driver only)
#   --scenarios LIST            comma-separated scenario ids, one worker each
#   --label NAME                run label; each worker gets "<label>-<scenario>"
#   --max-per-scenario N        questions per scenario, 0 = all (testbench driver only)
#   --window-minutes N          soft per-worker wall-clock deadline
#   --max-parallel N            concurrent workers; the rest queue (default: 5)
#   --resume s:run_id,...       resume existing per-scenario runs
#   --data-par PATH          scratch data_par root (default: backend/data_par)
#   --smoke                     resume-driver only: stop after 2 questions
#   --dry-run                   print the exact worker command lines, touch nothing
#
# Env defaults (FLAGS OVERRIDE THESE): DRIVER ARMS SCENARIOS LABEL MAX_PER_SCENARIO
#   WINDOW_MINUTES MAX_PARALLEL RESUME_SPEC RUN_ID_TIMEOUT JEVRAG_DATA_PAR_ROOT
#
# ARMS defaults to the 4-arm H-GATE family (base,gate-none,always-hard,oracle-gate),
# NOT the full 9-arm Layer-2 suite — always pass --arms explicitly for a full run.
#
# Contracts implemented (runbook §"Worker contracts"):
#   1. one worker = one scenario = one data dir: backend/data_par/<scenario>/ for
#      EVERY scenario, squad included — no exceptions
#   2. "RUN_ID=<uuid>" is the worker's first machine-readable stdout line; we poll
#      for it (warm-up is ~17 s, so a fixed sleep never sees it) and fail loudly if
#      it never arrives
#   3. the per-worker DB, not the log, is the progress source of truth
#   4. backend/data_par/parallel_run_meta.json describes THIS launch and is the only
#      machine-readable handoff to the monitor and the merge script
#
# Prerequisites: scripts/setup_backend.sh, scripts/setup_local_models.sh, backend/.env.
# Workers are detached with `setsid nohup`, so they survive this terminal.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND="$REPO_ROOT/backend"
# Same override the monitor and merge accept, so a smoke run can be pointed at a
# scratch root instead of writing into the real backend/data_par/ history.
DATA_PAR="${JEVRAG_DATA_PAR_ROOT:-$BACKEND/data_par}"
META_FILE="$DATA_PAR/parallel_run_meta.json"   # recomputed if --data-par is given
PY="$BACKEND/.venv/bin/python"

# How we recognise a live worker process in /proc (POSIX ERE, no grep -oP).
WORKER_RE='scripts/(run_testbench|bench_resume)[.][py]'
ID_RE='^[A-Za-z0-9._-]+$'
# Launcher contract: poll this long for the worker's RUN_ID= line (seconds).
RUN_ID_TIMEOUT="${RUN_ID_TIMEOUT:-90}"

# --- env defaults, overridden by flags below ---
DRIVER="${DRIVER:-testbench}"
ARMS="${ARMS:-base,gate-none,always-hard,oracle-gate}"
SCENARIOS="${SCENARIOS:-squad,hotpotqa,triviaqa,wiki2,musique}"
LABEL="${LABEL:-parallel-bench}"
MAX_PER_SCENARIO="${MAX_PER_SCENARIO:-0}"
WINDOW_MINUTES="${WINDOW_MINUTES:-100000}"
MAX_PARALLEL="${MAX_PARALLEL:-5}"
RESUME_SPEC="${RESUME_SPEC:-}"
SMOKE=0
DRY_RUN=0

usage() {
    sed -n -E 's/^# ?//p' "$0" | sed -n '/^Usage:/,/^Prerequisites:/p' || true
}

die() {
    printf 'ERROR: %s\n' "$1" >&2
    exit "${2:-2}"
}

need_value() {  # need_value "$@"
    if [[ $# -lt 2 || -z "${2:-}" ]]; then
        die "${1} requires a value"
    fi
}

is_uint() {
    case "$1" in
        ''|*[!0-9]*) return 1 ;;
        *) return 0 ;;
    esac
}

is_num() {
    [[ "$1" =~ ^[0-9]+([.][0-9]+)?$ ]]
}

# The worker's RUN_ID= line, or nothing. awk stops at the first hit on purpose:
# a `sed | head -1` pipeline would SIGPIPE the writer and `set -o pipefail` would
# turn a successful capture into a non-zero assignment.
log_run_id() {
    local log="$1" rid=""
    if [[ ! -f "$log" ]]; then
        return 0
    fi
    rid="$(awk 'index($0, "RUN_ID=") == 1 { sub(/^RUN_ID=/, ""); gsub(/[[:space:]]/, ""); print; exit }' \
              "$log" 2>/dev/null || true)"
    if [[ "$rid" =~ $ID_RE ]]; then
        printf '%s' "$rid"
    fi
}

# trim leading/trailing whitespace without external tools
trim() {
    local s="$1"
    s="${s#"${s%%[![:space:]]*}"}"
    s="${s%"${s##*[![:space:]]}"}"
    printf '%s' "$s"
}

# ---------------------------------------------------------------- arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --driver)            need_value "$@"; DRIVER="$(trim "$2")"; shift 2 ;;
        --arms)              need_value "$@"; ARMS="$2"; shift 2 ;;
        --scenarios)         need_value "$@"; SCENARIOS="$2"; shift 2 ;;
        --label)             need_value "$@"; LABEL="$(trim "$2")"; shift 2 ;;
        --max-per-scenario)  need_value "$@"; MAX_PER_SCENARIO="$(trim "$2")"; shift 2 ;;
        --window-minutes)    need_value "$@"; WINDOW_MINUTES="$(trim "$2")"; shift 2 ;;
        --max-parallel)      need_value "$@"; MAX_PARALLEL="$(trim "$2")"; shift 2 ;;
        --resume)            need_value "$@"; RESUME_SPEC="$2"; shift 2 ;;
        --data-par)          need_value "$@"; DATA_PAR="$(trim "$2")"
                             META_FILE="$DATA_PAR/parallel_run_meta.json"; shift 2 ;;
        --smoke)             SMOKE=1; shift ;;
        --dry-run)           DRY_RUN=1; shift ;;
        -h|--help)           usage; exit 0 ;;
        *)                   printf 'Unknown argument: %s\n\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
done

case "$DRIVER" in
    testbench) DRIVER_SCRIPT="$BACKEND/scripts/run_testbench.py" ;;
    resume)    DRIVER_SCRIPT="$BACKEND/scripts/bench_resume.py" ;;
    *)         die "--driver must be 'testbench' or 'resume' (got '$DRIVER')" ;;
esac

is_uint "$MAX_PER_SCENARIO" || die "--max-per-scenario must be an integer (got '$MAX_PER_SCENARIO')"
is_num  "$WINDOW_MINUTES"   || die "--window-minutes must be a number (got '$WINDOW_MINUTES')"
is_uint "$MAX_PARALLEL"     || die "--max-parallel must be a positive integer (got '$MAX_PARALLEL')"
if (( MAX_PARALLEL < 1 )); then
    die "--max-parallel must be >= 1 (got '$MAX_PARALLEL')"
fi
is_uint "$RUN_ID_TIMEOUT"   || die "RUN_ID_TIMEOUT must be an integer number of seconds (got '$RUN_ID_TIMEOUT')"
[[ -n "$(trim "$LABEL")" ]] || die "--label must not be empty"

# --smoke belongs to the resume driver; the testbench driver has no such flag.
if (( SMOKE )) && [[ "$DRIVER" != "resume" ]]; then
    die "--smoke is supported by --driver resume only (run_testbench.py has no --smoke)"
fi

# ------------------------------------------------- normalise scenario/arm lists
IFS=',' read -ra RAW_SCENARIOS <<< "$SCENARIOS"
IFS=',' read -ra RAW_ARMS <<< "$ARMS"

declare -a SCENARIO_ARR=()
declare -A SEEN_SCENARIO=()
for raw in ${RAW_SCENARIOS[@]+"${RAW_SCENARIOS[@]}"}; do
    sid="$(trim "$raw")"
    if [[ -z "$sid" ]]; then
        continue
    fi
    if [[ ! "$sid" =~ $ID_RE ]]; then
        die "invalid scenario id '$sid' (allowed: [A-Za-z0-9._-]; it also becomes a directory name)"
    fi
    if [[ -n "${SEEN_SCENARIO[$sid]+x}" ]]; then
        die "scenario '$sid' listed twice — two workers would share one data dir and double-write it"
    fi
    SEEN_SCENARIO["$sid"]=1
    SCENARIO_ARR+=("$sid")
done
(( ${#SCENARIO_ARR[@]} > 0 )) || die "--scenarios resolved to an empty list"

declare -a ARM_ARR=()
for raw in ${RAW_ARMS[@]+"${RAW_ARMS[@]}"}; do
    arm="$(trim "$raw")"
    if [[ -z "$arm" ]]; then
        continue
    fi
    if [[ ! "$arm" =~ $ID_RE ]]; then
        die "invalid arm name '$arm' (allowed: [A-Za-z0-9._-])"
    fi
    ARM_ARR+=("$arm")
done
if [[ "$DRIVER" == "testbench" ]]; then
    (( ${#ARM_ARR[@]} > 0 )) || die "--arms resolved to an empty list for the testbench driver"
fi
# Normalise once so the banner, the worker argv and the meta file all agree.
if (( ${#ARM_ARR[@]} > 0 )); then
    ARMS="$(IFS=,; printf '%s' "${ARM_ARR[*]}")"
fi

# ------------------------------------------------------- resume spec (per-scenario)
declare -A RESUME_MAP=()
if [[ -n "$RESUME_SPEC" ]]; then
    IFS=',' read -ra RAW_RESUME <<< "$RESUME_SPEC"
    for pair in ${RAW_RESUME[@]+"${RAW_RESUME[@]}"}; do
        pair="$(trim "$pair")"
        if [[ -z "$pair" ]]; then
            continue
        fi
        if [[ "$pair" != *:* ]]; then
            die "--resume expects scenario:run_id pairs (got '$pair'), e.g. musique:67a1dc06-..."
        fi
        rsid="$(trim "${pair%%:*}")"
        grid="$(trim "${pair#*:}")"
        if [[ ! "$rsid" =~ $ID_RE || ! "$grid" =~ $ID_RE ]]; then
            die "malformed --resume pair '$pair' (expected scenario:run_id)"
        fi
        if [[ -z "${SEEN_SCENARIO[$rsid]+x}" ]]; then
            die "--resume names scenario '$rsid' which is not in --scenarios (${SCENARIOS})"
        fi
        RESUME_MAP["$rsid"]="$grid"
    done
fi

# ------------------------------------------------------------- worker command
# build_worker_cmd <scenario> sets WORKER_CMD to the exact argv (after the
# JEVRAG_DATA_DIR assignment). Dry-run and the real launch share this function,
# so the printed lines can never drift from what actually runs.
# Driver mapping (runbook §"Procedure / 2. Launch"):
#   testbench -> run_testbench.py --arms --scenarios <sid> --max-per-scenario --window-minutes --label
#               (+ --resume <run_id>)
#   resume    -> bench_resume.py  --scenarios <sid> --max-minutes --label
#               (+ --run-id <run_id>, + --smoke)
declare -a WORKER_CMD=()
WORKER_DATA_DIR=""
WORKER_LOG=""
build_worker_cmd() {
    local sid="$1"
    WORKER_DATA_DIR="$DATA_PAR/$sid"
    WORKER_LOG="$WORKER_DATA_DIR/bench.log"
    WORKER_CMD=("nohup" "setsid" "$PY" "$DRIVER_SCRIPT")
    local rid=""
    if [[ -n "${RESUME_MAP[$sid]+x}" ]]; then
        rid="${RESUME_MAP[$sid]}"
    fi
    if [[ "$DRIVER" == "testbench" ]]; then
        WORKER_CMD+=(
            "--arms" "$ARMS"
            "--scenarios" "$sid"
            "--max-per-scenario" "$MAX_PER_SCENARIO"
            "--window-minutes" "$WINDOW_MINUTES"
            "--label" "$LABEL-$sid"
        )
        if [[ -n "$rid" ]]; then
            WORKER_CMD+=("--resume" "$rid")
        fi
    else
        WORKER_CMD+=(
            "--scenarios" "$sid"
            "--max-minutes" "$WINDOW_MINUTES"
            "--label" "$LABEL-$sid"
        )
        if [[ -n "$rid" ]]; then
            WORKER_CMD+=("--run-id" "$rid")
        fi
        if (( SMOKE )); then
            WORKER_CMD+=("--smoke")
        fi
    fi
}

quote_one() {  # shell-quote one word, but leave safe words readable
    local w="$1"
    if [[ -n "$w" && "$w" =~ ^[A-Za-z0-9_@%+=:,./-]+$ ]]; then
        printf '%s' "$w"
    else
        printf '%q' "$w"
    fi
    return 0
}

quote_cmd() {  # prints the args as one shell-quoted, copy-pasteable command line
    local out="" a
    for a in "$@"; do
        if [[ -n "$out" ]]; then
            out+=" "
        fi
        out+="$(quote_one "$a")"
    done
    printf '%s' "$out"
    return 0
}

# ------------------------------------------------------------------- banner
echo "========================================"
echo "Parallel Benchmark Launch"
echo "========================================"
echo "Driver: $DRIVER  ($DRIVER_SCRIPT)"
echo "Arms: $ARMS"
echo "Scenarios: ${SCENARIO_ARR[*]}"
echo "Label: $LABEL"
echo "Max per scenario: $MAX_PER_SCENARIO"
echo "Window minutes: $WINDOW_MINUTES"
echo "Workers: ${#SCENARIO_ARR[@]} (max parallel: $MAX_PARALLEL)"
if [[ ${#RESUME_MAP[@]} -gt 0 ]]; then
    echo "Resuming: $RESUME_SPEC"
fi
if [[ "$DRIVER" == "resume" ]]; then
    if [[ "$MAX_PER_SCENARIO" != "0" || ${#ARM_ARR[@]} -gt 0 ]]; then
        echo "NOTE: bench_resume.py takes no --arms/--max-per-scenario; they are not passed."
    fi
fi
echo ""

# ------------------------------------------------------- dry-run (touch nothing)
if (( DRY_RUN )); then
    echo "Dry run — worker command lines that WOULD have launched:"
    echo ""
    for sid in "${SCENARIO_ARR[@]}"; do
        build_worker_cmd "$sid"
        line="JEVRAG_DATA_DIR=$(quote_one "$WORKER_DATA_DIR") $(quote_cmd "${WORKER_CMD[@]}") > $(quote_one "$WORKER_LOG") 2>&1 &"
        echo "# scenario $sid"
        echo "$line"
        echo ""
    done
    echo "No directory was created and no file was written."
    exit 0
fi

# ----------------------------------------------------------------- prereqs
if [[ ! -d "$BACKEND/.venv" ]]; then
    die "backend venv not found at $BACKEND/.venv. Run: bash scripts/setup_backend.sh" 1
fi
if [[ ! -x "$PY" ]]; then
    die "backend interpreter not executable at $PY. Run: bash scripts/setup_backend.sh" 1
fi
if [[ ! -f "$BACKEND/.env" ]]; then
    die "backend/.env not found. Copy from backend/.env.example and configure it." 1
fi
if [[ ! -f "$DRIVER_SCRIPT" ]]; then
    die "driver script missing: $DRIVER_SCRIPT" 1
fi
# JSON generation + meta parsing use python3 stdlib only.
META_PY="$PY"
if [[ ! -x "$META_PY" ]]; then
    META_PY="$(command -v python3 || true)"
fi
if [[ -z "$META_PY" ]]; then
    die "need python3 (stdlib json) to write the meta file" 1
fi

# --------------------------------------------------------------- liveness
# pid_alive <pid>: true while the worker process is still running.
# Transient /proc read failures count as ALIVE, not dead: during an execve chain
# (nohup -> setsid -> python) /proc/<pid>/cmdline is briefly empty, and treating
# that as death once silently failed a worker that had already printed its RUN_ID.
# Death needs hard evidence: the pid is gone, it is a reaped-but-unwaited zombie,
# or the pid now belongs to a different program.
pid_alive() {
    local p="$1" state cmd
    if [[ ! -d /proc ]]; then
        kill -0 "$p" 2>/dev/null
        return $?
    fi
    if [[ ! -e "/proc/$p" ]]; then
        return 1
    fi
    if [[ -r "/proc/$p/status" ]]; then
        state="$(awk '/^State:/{ print $2; exit }' "/proc/$p/status" 2>/dev/null || true)"
        if [[ "$state" == "Z" ]]; then
            return 1
        fi
    fi
    if [[ -r "/proc/$p/cmdline" ]]; then
        # Pure-bash match (no grep pipeline): a recycled pid now belonging to an
        # unrelated program must not look alive. An empty cmdline means the pid is
        # mid-execve, so it stays alive.
        cmd="$(tr '\0' ' ' < "/proc/$p/cmdline" 2>/dev/null || true)"
        if [[ -n "$cmd" && "$cmd" != *"scripts/run_testbench.py"* \
              && "$cmd" != *"scripts/bench_resume.py"* ]]; then
            return 1
        fi
    fi
    return 0
}

# Live workers and the data dirs they own: JEVRAG_DATA_DIR in /proc/<pid>/environ
# is the authoritative ownership claim, so an untracked worker is still caught.
live_owned_dirs() {  # prints "<data_dir>\t<scenario>\t<pid>" per live worker
    local p dd sid
    for p in $(pgrep -f "$WORKER_RE" 2>/dev/null || true); do
        if [[ "$p" == "$$" || "$p" == "$PPID" ]]; then
            continue
        fi
        if [[ ! -r "/proc/$p/environ" ]]; then
            continue
        fi
        dd="$(tr '\0' '\n' < "/proc/$p/environ" 2>/dev/null \
              | awk '/^JEVRAG_DATA_DIR=/{ sub(/^JEVRAG_DATA_DIR=/, ""); print; exit }' || true)"
        if [[ -z "$dd" ]]; then
            continue
        fi
        sid="$(basename "$dd")"
        printf '%s\t%s\t%s\n' "$dd" "$sid" "$p"
    done
}

meta_owned_dirs() {  # defense in depth: pids recorded by the previous launch
    if [[ ! -f "$META_FILE" ]]; then
        return 0
    fi
    META_FILE="$META_FILE" "$META_PY" - <<'PY'
import json, os, sys
path = os.environ["META_FILE"]
try:
    with open(path, encoding="utf-8") as fh:
        meta = json.load(fh)
except Exception:
    sys.exit(0)
for w in meta.get("workers") or []:
    try:
        pid = int(w.get("pid"))
    except (TypeError, ValueError):
        continue
    dd = str(w.get("data_dir") or "")
    # run_id may be null (capture failed) while the worker is still warming up:
    # it still owns that data dir, so report it and let the pid_alive check decide.
    if pid > 0 and dd and os.path.isdir(f"/proc/{pid}"):
        print(f"{dd}\t{os.path.basename(dd)}\t{pid}")
PY
}

# -------------------------------------------------- already-running guard
# Refuse BEFORE touching anything: two workers on one data dir double-write the
# same SQLite/Chroma store and the merge tie-break can no longer be trusted.
declare -a GUARD_CLAIMS=()
while IFS= read -r line; do
    if [[ -n "$line" ]]; then
        GUARD_CLAIMS+=("$line")
    fi
done < <(live_owned_dirs; meta_owned_dirs)

declare -a OFFENDERS=()
for sid in "${SCENARIO_ARR[@]}"; do
    target="$DATA_PAR/$sid"
    for claim in ${GUARD_CLAIMS[@]+"${GUARD_CLAIMS[@]}"}; do
        cdir="${claim%%$'\t'*}"
        cpid="${claim##*$'\t'}"
        if [[ "$cdir" == "$target" ]]; then
            if pid_alive "$cpid"; then
                OFFENDERS+=("$sid -> $target (live pid $cpid)")
                break
            fi
        fi
    done
done
if (( ${#OFFENDERS[@]} > 0 )); then
    echo "ERROR: refusing to launch — a live worker already owns a target data dir:" >&2
    for o in "${OFFENDERS[@]}"; do
        echo "  $o" >&2
    done
    echo "Wait for it (bash scripts/check_parallel_bench.sh) or kill it first;" >&2
    echo "double-writing one JEVRAG_DATA_DIR corrupts the run." >&2
    exit 1
fi

# ----------------------------------------------------------- launch + capture
declare -a WORKER_PIDS=()
declare -a W_SCENARIO=()
declare -a W_RUN_ID=()
declare -a W_PID=()
declare -a W_DIR=()
declare -a W_LOG=()
CAP_RUN_ID=""
CAP_STATUS=0
FAILED_SCENARIOS=()
LAUNCHED=0

live_worker_count() {  # sets LIVE_COUNT from the pids this launcher started
    local n=0 i
    for i in ${WORKER_PIDS[@]+"${WORKER_PIDS[@]}"}; do
        if pid_alive "$i"; then
            n=$(( n + 1 ))
        fi
    done
    LIVE_COUNT=$n
}

# Block until a parallel slot is free. `wait -n` parks the shell on child death
# (no polling while a worker is still running); the sleep only covers the case
# where nothing was left to reap.
await_slot() {
    local before after
    while :; do
        live_worker_count
        if (( LIVE_COUNT < MAX_PARALLEL )); then
            return 0
        fi
        echo "  [$MAX_PARALLEL workers already running] queueing '$QUEUE_SCENARIO', waiting for a slot..."
        before="$LIVE_COUNT"
        if (( ${#WORKER_PIDS[@]} > 0 )); then
            wait -n >/dev/null 2>&1 || true
        fi
        live_worker_count
        after="$LIVE_COUNT"
        if [[ "$before" == "$after" ]]; then
            sleep 3
        fi
    done
}

# Poll the log for the worker's RUN_ID= line (contract 2). Sets CAP_RUN_ID and
# CAP_STATUS (0 ok / 1 timeout / 2 worker died before printing it).
# Capturing is deliberately SEQUENTIAL: worker n+1 starts only after worker n
# announced itself (~17 s of model warm-up each). That staggers the model
# load-ups, which is kinder to RAM than firing every worker at once, and it is
# what makes the run ids reliable. Do not "optimise" it into a fire-and-forget loop.
capture_run_id() {
    local log="$1" pid="$2"
    local polls=$(( RUN_ID_TIMEOUT * 2 )) i rid="" strikes=0
    CAP_RUN_ID=""
    CAP_STATUS=1
    for (( i = 0; i < polls; i++ )); do
        rid="$(log_run_id "$log")"
        if [[ -n "$rid" ]]; then
            CAP_RUN_ID="$rid"
            CAP_STATUS=0
            return 0
        fi
        if pid_alive "$pid"; then
            strikes=0
        else
            # two consecutive dead verdicts (1s apart) before declaring death
            strikes=$(( strikes + 1 ))
            if (( strikes >= 2 )); then
                rid="$(log_run_id "$log")"
                if [[ -n "$rid" ]]; then
                    CAP_RUN_ID="$rid"
                    CAP_STATUS=0
                    return 0
                fi
                CAP_STATUS=2
                return 1
            fi
        fi
        sleep 0.5
    done
    # timed out: one last look in case the line landed on the final tick
    rid="$(log_run_id "$log")"
    if [[ -n "$rid" ]]; then
        CAP_RUN_ID="$rid"
        CAP_STATUS=0
        return 0
    fi
    return 1
}

for sid in "${SCENARIO_ARR[@]}"; do
    QUEUE_SCENARIO="$sid"
    await_slot
    build_worker_cmd "$sid"
    mkdir -p "$WORKER_DATA_DIR"

    echo "Launching worker for scenario: $sid"
    echo "  Data dir: $WORKER_DATA_DIR"
    echo "  Log file: $WORKER_LOG"
    JEVRAG_DATA_DIR="$WORKER_DATA_DIR" "${WORKER_CMD[@]}" > "$WORKER_LOG" 2>&1 &
    wpid=$!
    WORKER_PIDS+=("$wpid")
    LAUNCHED=$(( LAUNCHED + 1 ))
    echo "  PID: $wpid"

    if capture_run_id "$WORKER_LOG" "$wpid"; then
        echo "  Run ID: $CAP_RUN_ID"
    else
        case "$CAP_STATUS" in
            2) echo "  RESULT: worker DIED before printing RUN_ID= (see $WORKER_LOG)" >&2 ;;
            *) echo "  RESULT: no RUN_ID= line within ${RUN_ID_TIMEOUT}s (see $WORKER_LOG)" >&2 ;;
        esac
        echo "  FAILED: $sid — its run id is unknown, so it cannot be merged automatically." >&2
        FAILED_SCENARIOS+=("$sid")
        CAP_RUN_ID=""
    fi

    W_SCENARIO+=("$sid")
    W_RUN_ID+=("$CAP_RUN_ID")
    W_PID+=("$wpid")
    W_DIR+=("$WORKER_DATA_DIR")
    W_LOG+=("$WORKER_LOG")
    echo ""
done

# -------------------------------------------------------------- meta file (4)
# Contract 4 says the meta file describes THIS launch — so a resume launch replaces a
# previous full-suite meta with one that names only the resumed scenarios. The merge
# reads workers[], and would then silently produce a short run that still exits 0.
# Capture the outgoing set first so we can warn about exactly that.
PREV_WORKERS=""
if [[ -f "$META_FILE" ]]; then
    PREV_WORKERS="$(META_FILE="$META_FILE" "$META_PY" - <<'PY' 2>/dev/null || true
import json
import os
try:
    with open(os.environ["META_FILE"], encoding="utf-8") as fh:
        meta = json.load(fh)
except Exception:
    raise SystemExit(0)
out = []
for w in meta.get("workers") or []:
    sid = str(w.get("scenario") or "").strip()
    rid = str(w.get("run_id") or "").strip()
    if sid:
        out.append(f"{sid}:{rid}")
if not out:
    # legacy meta files carry only the scenarios list, no per-worker ids
    out = [s.strip() + ":" for s in str(meta.get("scenarios") or "").split(",") if s.strip()]
print(",".join(out))
PY
)"
fi

WORKERS_TSV=""
for i in "${!W_SCENARIO[@]}"; do
    if [[ -n "$WORKERS_TSV" ]]; then
        WORKERS_TSV+=$'\n'
    fi
    WORKERS_TSV+="$(printf '%s\t%s\t%s\t%s\t%s' \
        "${W_SCENARIO[$i]}" "${W_RUN_ID[$i]}" "${W_PID[$i]}" "${W_DIR[$i]}" "${W_LOG[$i]}")"
done

META_OK=1
if ! LAUNCH_LABEL="$LABEL" LAUNCH_DRIVER="$DRIVER" LAUNCH_ARMS="$ARMS" \
     LAUNCH_SCENARIOS="${SCENARIO_ARR[*]}" LAUNCH_MAX="$MAX_PER_SCENARIO" \
     LAUNCH_WINDOW="$WINDOW_MINUTES" WORKERS_TSV="$WORKERS_TSV" META_FILE="$META_FILE" \
     "$META_PY" - <<'PY'
import json
import os
import sys
from datetime import datetime


def as_number(text):
    text = (text or "").strip()
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


workers = []
raw = os.environ.get("WORKERS_TSV", "")
for line in raw.splitlines():
    if not line.strip():
        continue
    parts = line.split("\t")
    if len(parts) != 5:
        print("skipping malformed worker line: %r" % (line,), file=sys.stderr)
        continue
    scenario, run_id, pid, data_dir, log_file = parts
    workers.append({
        "scenario": scenario,
        # null => the worker never printed RUN_ID=; read its log and relaunch it
        "run_id": run_id or None,
        "pid": int(pid) if pid.isdigit() else None,
        "data_dir": data_dir,
        "log_file": log_file,
    })

meta = {
    "version": 1,
    "label": os.environ.get("LAUNCH_LABEL", ""),
    "driver": os.environ.get("LAUNCH_DRIVER", ""),
    "arms": os.environ.get("LAUNCH_ARMS", ""),
    "scenarios": ",".join(os.environ.get("LAUNCH_SCENARIOS", "").split()),
    "max_per_scenario": as_number(os.environ.get("LAUNCH_MAX", "0")),
    "window_minutes": as_number(os.environ.get("LAUNCH_WINDOW", "")),
    "num_workers": len(workers),
    "launched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    "workers": workers,
}

target = os.environ["META_FILE"]
tmp = target + ".tmp"
os.makedirs(os.path.dirname(target), exist_ok=True)
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(meta, fh, indent=2)
    fh.write("\n")
os.replace(tmp, target)
print("meta: %d worker(s), %d with a run id -> %s"
      % (len(workers), sum(1 for w in workers if w["run_id"]), target))
PY
then
    META_OK=0
    echo "ERROR: failed to write $META_FILE — the monitor and merge steps cannot resolve run ids." >&2
fi

# ------------------------------------------------------------------ report
echo "========================================"
echo "$LAUNCHED worker(s) launched (${#SCENARIO_ARR[@]} scenarios, max parallel $MAX_PARALLEL)"
echo "========================================"

# Warn about scenarios the outgoing meta knew about but this launch does not.
if [[ -n "$PREV_WORKERS" ]]; then
    DROPPED=""
    IFS=',' read -ra PREV_PAIRS <<< "$PREV_WORKERS"
    for pair in ${PREV_PAIRS[@]+"${PREV_PAIRS[@]}"}; do
        psid="${pair%%:*}"
        [[ -z "$psid" ]] && continue
        keep=0
        for sid in "${SCENARIO_ARR[@]}"; do
            [[ "$sid" == "$psid" ]] && keep=1 && break
        done
        (( keep )) || DROPPED+="${DROPPED:+ }$pair"
    done
    if [[ -n "$DROPPED" ]]; then
        echo "" >&2
        echo "WARNING: $META_FILE now describes ONLY this launch." >&2
        echo "  Scenarios from the previous launch are no longer in it: $DROPPED" >&2
        echo "  Merging from the meta file alone would silently produce a SHORT run that" >&2
        echo "  still exits 0. Pass every scenario explicitly, e.g.:" >&2
        ALL_IDS=""
        for pair in ${PREV_PAIRS[@]+"${PREV_PAIRS[@]}"}; do
            psid="${pair%%:*}"
            prid="${pair#*:}"
            [[ -z "$psid" || -z "$prid" ]] && continue
            keep=0
            for sid in "${SCENARIO_ARR[@]}"; do
                [[ "$sid" == "$psid" ]] && keep=1 && break
            done
            (( keep )) && continue
            ALL_IDS+="${ALL_IDS:+,}$psid:$prid"
        done
        for i in "${!W_SCENARIO[@]}"; do
            [[ -z "${W_RUN_ID[$i]}" ]] && continue
            ALL_IDS+="${ALL_IDS:+,}${W_SCENARIO[$i]}:${W_RUN_ID[$i]}"
        done
        if [[ -n "$ALL_IDS" ]]; then
            echo "    .venv/bin/python scripts/_merge_par_run.py --run-ids $ALL_IDS" >&2
        else
            echo "    (no run ids were recoverable — merge with --data-dirs instead)" >&2
        fi
    fi
fi

if (( ${#FAILED_SCENARIOS[@]} > 0 )); then
    echo ""
    echo "FAILED scenarios (no RUN_ID= captured — the meta file records them with run_id null):" >&2
    for f in "${FAILED_SCENARIOS[@]}"; do
        echo "  $f" >&2
    done
    echo "  Inspect: tail -n 50 $DATA_PAR/<scenario>/bench.log" >&2
    echo "  Relaunch that scenario alone, e.g." >&2
    echo "    bash scripts/run_parallel_bench.sh --scenarios <scenario> --label $LABEL" >&2
fi
echo ""
echo "Monitor progress (runbook §3):"
echo "  bash scripts/check_parallel_bench.sh            # human-readable"
echo "  bash scripts/check_parallel_bench.sh --json      # machine-readable"
for sid in "${SCENARIO_ARR[@]}"; do
    echo "  tail -f $DATA_PAR/$sid/bench.log          # error text for one worker"
done
echo ""
echo "Liveness / kill:"
echo "  ps aux | grep -E '$WORKER_RE'"
echo "  pkill -f '$DRIVER_SCRIPT'"
echo ""
echo "Merge results (runbook §5, from backend/):"
echo "  cd backend"
echo "  .venv/bin/python scripts/_merge_par_run.py --meta \"$META_FILE\" --label \"$LABEL (merged)\""
echo ""
RUN_IDS_ARG=""
DATA_DIRS_ARG=""
for i in "${!W_SCENARIO[@]}"; do
    if [[ -z "${W_RUN_ID[$i]}" ]]; then
        continue
    fi
    if [[ -n "$RUN_IDS_ARG" ]]; then
        RUN_IDS_ARG+=","
        DATA_DIRS_ARG+=","
    fi
    RUN_IDS_ARG+="${W_SCENARIO[$i]}:${W_RUN_ID[$i]}"
    DATA_DIRS_ARG+="${W_SCENARIO[$i]}:${W_DIR[$i]}"
done
if [[ -n "$RUN_IDS_ARG" ]]; then
    echo "Explicit override (use this if the merge script cannot read the meta file):"
    echo "  cd backend"
    echo "  .venv/bin/python scripts/_merge_par_run.py \\"
    echo "      --run-ids $RUN_IDS_ARG \\"
    echo "      --data-dirs $DATA_DIRS_ARG \\"
    echo "      --arms $ARMS \\"
    echo "      --scenarios $(IFS=,; echo "${SCENARIO_ARR[*]}") \\"
    echo "      --label \"$LABEL (merged)\""
    echo ""
fi
echo "Analyze + export (runbook §6, record the merged run id printed by the merge):"
echo "  cd backend"
echo "  JEVRAG_DATA_DIR=backend/data_merged \\"
echo "    .venv/bin/python scripts/analyze_testbench.py <merged-run-id> \\"
echo "    --out ../docs/testbench-results-$LABEL.md"
echo ""
if (( META_OK )); then
    echo "Metadata: $META_FILE"
fi

if (( ${#FAILED_SCENARIOS[@]} > 0 )); then
    exit 1
fi
if (( ! META_OK )); then
    exit 1
fi
exit 0
