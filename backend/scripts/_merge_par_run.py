#!/usr/bin/env python3
"""Merge per-scenario parallel-run DBs into one canonical merged DB.

One parallel worker = one scenario = one data directory
(``backend/data_par/<scenario>/app.db``, docs/parallel-bench-runbook.md
§"Worker contracts"). This script turns those scattered result sets back into a
single analysable run in ``backend/data_merged/app.db`` containing exactly ONE
``bench_runs`` row plus deduplicated ``bench_results`` rows, so
``backend/scripts/analyze_testbench.py`` works against it unchanged.

Source selection (per scenario; higher entries win):
  1. ``--run-ids scenario:uuid,...`` / ``--data-dirs scenario:path,...`` —
     explicit operator intent always beats the meta file
  2. ``--meta`` file (default ``backend/data_par/parallel_run_meta.json``):
     ``workers[]`` gives each scenario's ``run_id`` + ``data_dir``; the legacy
     ``{"run_ids": {...}}`` shape written by the current launcher is accepted too
  3. otherwise auto-detect inside the scenario DB: prefer the ``completed`` run
     with the most rows for that scenario (so a later in-flight retry cannot win
     the tie-break); when no completed run has rows (partial / resumed /
     window-budget case) fall back to the run with the most rows and say so

Row merging:
  * source DBs are opened strictly READ-ONLY (``file:...?mode=ro``); only
    ``--out`` (default ``backend/data_merged/app.db``) is written, and it is
    rebuilt from scratch every run (idempotent)
  * result rows are deduplicated on the (``scenario_id``, ``question_id``,
    ``mode``) triple — ``mode`` carries the arm name for testbench-driven runs —
    tie-break: a row from a ``completed`` run beats one from a non-completed run,
    otherwise the first row in plan order (then lowest source rowid) wins
  * every copied row gets a FRESH uuid primary key, so equal source row ids from
    different worker DBs can never collide in the merged DB
  * a scenario that resolves to zero rows is a loud, actionable error (non-zero
    exit, scenario named) and the merged DB is left untouched — silently
    producing a short run is worse than refusing

Usage:
  # everything comes from the meta file written by run_parallel_bench.sh
  .venv/bin/python scripts/_merge_par_run.py --label "hgate-par (merged)"

  # no meta file: name the scenarios (and optionally the arms)
  .venv/bin/python scripts/_merge_par_run.py --arms base,gate-none --scenarios squad,hotpotqa

  # explicit overrides
  .venv/bin/python scripts/_merge_par_run.py --run-ids squad:abc123,hotpotqa:def456
  .venv/bin/python scripts/_merge_par_run.py --data-dirs squad:./data_par/squad

Exit codes: 0 merged · 2 a source DB file is missing / nothing selected ·
3 a source is unreadable or the merged row cannot be written ·
4 a scenario resolved to zero rows.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# Repo root anchored from this file's own location — never a hardcoded path.
ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
# The launcher and the monitor honour JEVRAG_DATA_PAR_ROOT, so the merge must too —
# otherwise a scratch-root run launches, monitors, and then cannot be merged with the
# same root argument set (docs/parallel-bench-runbook.md §"Worker contracts" item 1).
DATA_PAR_DEFAULT = Path(os.environ.get("JEVRAG_DATA_PAR_ROOT") or BACKEND / "data_par")
META_DEFAULT = DATA_PAR_DEFAULT / "parallel_run_meta.json"
MERGED_DB_DEFAULT = BACKEND / "data_merged" / "app.db"
MAIN_DB = BACKEND / "data" / "app.db"

RUN_TABLE = "bench_runs"
RESULT_TABLE = "bench_results"
# Fallback scenario list for meta-less invocations (legacy behaviour).
DEFAULT_SCENARIOS = "squad,hotpotqa,triviaqa,wiki2,musique"

EXIT_OK = 0
EXIT_MISSING_DB = 2
EXIT_BAD_SOURCE = 3
EXIT_EMPTY_SCENARIO = 4


class MergeError(Exception):
    """A fatal, operator-actionable problem with the merge."""


# -------------------------------------------------------------- small helpers
def split_list(spec: str) -> list[str]:
    """Comma-separated CLI value -> list of non-empty tokens."""
    return [s.strip() for s in (spec or "").split(",") if s.strip()]


def parse_pairs(spec: str) -> dict[str, str]:
    """Parse ``a:1,b:2`` into ``{"a": "1", "b": "2"}`` (last wins on repeats)."""
    out: dict[str, str] = {}
    for pair in (spec or "").split(","):
        if ":" not in pair:
            continue
        key, value = pair.split(":", 1)
        key, value = key.strip(), value.strip()
        if key and value:
            out[key] = value
    return out


def resolve_path(raw: str, base: Path = ROOT) -> Path:
    """Resolve a CLI/meta path value.

    Absolute paths are used as-is (that is what the launcher writes). Relative
    ones are tried against the repo root first, then ``backend/`` so the
    historic ``--data-dirs squad:./data_par/squad`` form keeps working.
    """
    p = Path(str(raw)).expanduser()
    if p.is_absolute():
        return p
    at_root = (base / p).resolve()
    if at_root.exists():
        return at_root
    at_backend = (BACKEND / p).resolve()
    return at_backend if at_backend.exists() else at_root


def _loads(value):
    if value is None or isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return {}


# ------------------------------------------------------------- sqlite plumbing
def read_only(db_path: Path) -> sqlite3.Connection:
    """Open a source DB strictly read-only (URI ``mode=ro``)."""
    posix = Path(str(db_path)).as_posix()
    escaped = posix.replace("%", "%25").replace("?", "%3F").replace("#", "%23")
    conn = sqlite3.connect(f"file:{escaped}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    """Column names of ``table`` — empty list when the table is absent."""
    return [r["name"] for r in conn.execute(f"pragma table_info({table})")]


def _mode_filter(arms: list[str] | None, column: str = "mode") -> tuple[str, list[str]]:
    """``(' and mode in (?,?)', ['base', ...])`` — empty when no arm filter."""
    if not arms:
        return "", []
    return f" and {column} in ({','.join('?' * len(arms))})", list(arms)


def count_rows(conn: sqlite3.Connection, run_id: str, scenario: str,
               arms: list[str] | None = None) -> int:
    clause, params = _mode_filter(arms)
    row = conn.execute(
        f"select count(*) from {RESULT_TABLE} where run_id=? and scenario_id=?{clause}",
        [run_id, scenario, *params]).fetchone()
    return int(row[0]) if row else 0


def run_status(conn: sqlite3.Connection, run_id: str) -> str | None:
    row = conn.execute(f"select status from {RUN_TABLE} where id=?", (run_id,)).fetchone()
    return row[0] if row else None


def distinct_modes(conn: sqlite3.Connection, run_id: str, scenario: str) -> list[str]:
    """The ``mode`` values present for one scenario inside one run."""
    return [str(r[0]) for r in conn.execute(
        f"select distinct mode from {RESULT_TABLE} where run_id=? and scenario_id=? order by mode",
        (run_id, scenario)).fetchall()]


def pick_run(conn: sqlite3.Connection, scenario: str,
             arms: list[str] | None = None) -> tuple[str | None, int]:
    """Return ``(run_id, n_rows)`` for ``scenario`` inside one worker DB.

    1. Prefer a ``completed`` run that has rows for this scenario: most rows
       wins, the newest run breaks ties.
    2. Otherwise (interrupted worker, window budget reached, resumed retry)
       fall back to the run with the most rows for this scenario — again newest
       on ties. This is the partial/resume case, where an aggregate may not sit
       in WHERE (``misuse of aggregate``), hence GROUP BY ... HAVING.
    3. ``(None, 0)`` when no run in this DB has a matching row.
    """
    clause, params = _mode_filter(arms, column="b.mode")
    join = (f"left join {RESULT_TABLE} b on b.run_id = r.id "
            f"and b.scenario_id = ?{clause}")
    args = [scenario, *params]

    completed = conn.execute(
        f"select r.id, count(b.id) from {RUN_TABLE} r {join} "
        "where r.status = 'completed' group by r.id having count(b.id) > 0 "
        "order by count(b.id) desc, r.rowid desc", args).fetchall()
    if completed:
        return completed[0][0], int(completed[0][1])

    partial = conn.execute(
        f"select r.id, count(b.id) from {RUN_TABLE} r {join} "
        "group by r.id having count(b.id) > 0 "
        "order by count(b.id) desc, r.rowid desc", args).fetchall()
    if partial:
        return partial[0][0], int(partial[0][1])
    return None, 0


# ------------------------------------------------------------------ meta file
@dataclass
class MetaPlan:
    run_ids: dict[str, str] = field(default_factory=dict)
    data_dirs: dict[str, str] = field(default_factory=dict)
    scenarios: list[str] = field(default_factory=list)
    note: str = ""


def load_meta(meta_path: Path) -> MetaPlan:
    """Read a parallel-run meta file; never fatal (callers fall back).

    Handles the runbook shape ``{"workers": [{"scenario","run_id","data_dir",...}]}``
    and the legacy launcher shape ``{"run_ids": {"squad": "<uuid>"}}``.
    """
    if not meta_path.exists():
        return MetaPlan(note=f"no meta file at {meta_path} — using the data_par convention")
    try:
        raw = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return MetaPlan(note=f"meta file {meta_path} unreadable ({exc}) — ignoring it")
    if not isinstance(raw, dict):
        return MetaPlan(note=f"meta file {meta_path} is not a JSON object — ignoring it")

    plan = MetaPlan()
    workers = raw.get("workers")
    if isinstance(workers, list):
        for w in workers:
            if not isinstance(w, dict):
                continue
            sid = str(w.get("scenario") or "").strip()
            if not sid:
                continue
            rid = str(w.get("run_id") or "").strip()
            if rid:
                plan.run_ids[sid] = rid
            dd = str(w.get("data_dir") or "").strip()
            if dd:
                plan.data_dirs[sid] = dd
    legacy = raw.get("run_ids")
    if not plan.run_ids and isinstance(legacy, dict):
        plan.run_ids = {str(k).strip(): str(v).strip()
                        for k, v in legacy.items() if str(v or "").strip()}
    plan.scenarios = split_list(str(raw.get("scenarios") or ""))
    if not plan.scenarios:
        plan.scenarios = sorted(set(plan.run_ids) | set(plan.data_dirs))
    shape = "workers[]" if isinstance(workers, list) else "run_ids{}"
    plan.note = (f"meta {meta_path.name} ({shape}): {len(plan.run_ids)} run_id(s), "
                 f"{len(plan.data_dirs)} data_dir(s)")
    return plan


# -------------------------------------------------------------- plan building
def db_file(path: Path) -> Path:
    """Interpret a data-dir-or-DB-file value: ``<dir>`` -> ``<dir>/app.db``.

    ``--data-dirs`` and the meta file's ``data_dir`` name the worker's DATA
    DIRECTORY (runbook §Worker contracts 1); an explicit ``*.db`` file is also
    accepted for convenience.
    """
    return path if path.suffix.lower() == ".db" else path / "app.db"


@dataclass
class Source:
    scenario: str
    db_path: Path
    run_id: str | None = None
    run_origin: str = "auto"           # cli | meta | auto
    path_origin: str = "convention"    # cli | meta | convention


@dataclass
class Selection:
    source: Source
    run_id: str
    status: str
    n_rows: int
    notes: list[str] = field(default_factory=list)


def build_plan(scenarios: list[str], cli_run_ids: dict[str, str],
               cli_data_dirs: dict[str, str], meta: MetaPlan,
               data_par: Path) -> list[Source]:
    """Map each scenario to a source DB path and an optional forced run id."""
    plan: list[Source] = []
    for sid in scenarios:
        if sid in cli_data_dirs:
            db_path, path_origin = db_file(resolve_path(cli_data_dirs[sid])), "cli"
        elif sid in meta.data_dirs:
            db_path, path_origin = db_file(resolve_path(meta.data_dirs[sid])), "meta"
        else:
            db_path, path_origin = data_par / sid / "app.db", "convention"
        if sid in cli_run_ids:
            run_id, run_origin = cli_run_ids[sid], "cli"
        elif sid in meta.run_ids:
            run_id, run_origin = meta.run_ids[sid], "meta"
        else:
            run_id, run_origin = None, "auto"
        plan.append(Source(sid, db_path, run_id, run_origin, path_origin))
    return plan


def resolve_selections(plan: list[Source],
                       arms: list[str] | None) -> tuple[list[Selection], list[str]]:
    """Validate every source read-only.

    Returns ``(usable selections, problems)``. Problems are fatal for the whole
    merge (missing DB file, missing bench tables, unknown forced run id, zero
    rows) — refusing beats writing a silently short merged run.
    """
    selections: list[Selection] = []
    problems: list[str] = []
    for src in plan:
        if not src.db_path.exists():
            problems.append(f"MISSING: scenario '{src.scenario}' has no DB at {src.db_path}")
            continue
        try:
            conn = read_only(src.db_path)
        except sqlite3.Error as exc:
            problems.append(f"UNREADABLE: {src.db_path} ('{src.scenario}'): {exc}")
            continue
        try:
            if not table_columns(conn, RESULT_TABLE) or not table_columns(conn, RUN_TABLE):
                problems.append(f"NO BENCH TABLES: {src.db_path} ('{src.scenario}') — "
                                "this worker never wrote results here")
                continue
            notes: list[str] = []
            run_id, status, n_rows = src.run_id, None, 0
            if run_id:
                status = run_status(conn, run_id)
                n_rows = count_rows(conn, run_id, src.scenario, arms)
                if status is None or n_rows == 0:
                    reason = ("is not in this DB" if status is None
                              else "has 0 matching result rows")
                    if src.run_origin == "cli":
                        # An explicit --run-ids is operator intent: never quietly
                        # swap in a different run, fail loudly instead.
                        problems.append(
                            f"UNKNOWN RUN: --run-ids {src.scenario}:{run_id} {reason} "
                            f"({src.db_path}). Fix the id or drop --run-ids to auto-detect.")
                        continue
                    notes.append(f"{src.run_origin} run_id {run_id[:8]} {reason} — "
                                 "auto-detected instead")
                    run_id, n_rows = pick_run(conn, src.scenario, arms)
                    status = run_status(conn, run_id) if run_id else None
            else:
                run_id, n_rows = pick_run(conn, src.scenario, arms)
                status = run_status(conn, run_id) if run_id else None

            if run_id is None or n_rows == 0:
                if arms:
                    # Distinguish "the worker produced nothing" from "you asked for
                    # arms this driver never writes" (bench_resume stores modes
                    # traditional|hybrid, not arm names).
                    alt_id = run_id or pick_run(conn, src.scenario)[0]
                    alt_n = count_rows(conn, alt_id, src.scenario) if alt_id else 0
                    if alt_id and alt_n:
                        modes = ",".join(distinct_modes(conn, alt_id, src.scenario))
                        problems.append(
                            f"ARM MISMATCH: scenario '{src.scenario}' has {alt_n} rows in run "
                            f"{alt_id[:8]} but none with --arms {','.join(arms)} — the modes "
                            f"there are {modes}. Drop --arms or name those instead.")
                        continue
                filter_note = f" with arms={','.join(arms)}" if arms else ""
                problems.append(
                    f"EMPTY: scenario '{src.scenario}' has 0 result rows in "
                    f"{src.db_path}{filter_note}. The worker never ran, died before "
                    "committing, or the arms do not match its modes — resume it with "
                    f"run_parallel_bench.sh --scenarios {src.scenario}, or drop it "
                    "from --scenarios.")
                continue
            if status != "completed":
                notes.append(f"run {run_id[:8]} is status='{status}', not 'completed' — "
                             "the merged run is PARTIAL (runbook §4: resume first)")
            selections.append(Selection(src, run_id, status or "", n_rows, notes))
        finally:
            conn.close()
    return selections, problems


# --------------------------------------------------------------------- merging
def _copy_schema(target: sqlite3.Connection, source_db: Path) -> None:
    """Recreate the first source DB's tables/indexes/views in the merged DB."""
    conn = read_only(source_db)
    try:
        rows = conn.execute("select name, sql from sqlite_master "
                            "where type in ('table','index','view') order by rowid").fetchall()
    finally:
        conn.close()
    for name, sql in rows:
        if not sql or str(name).startswith("sqlite_"):
            continue
        if sql.strip().upper().startswith(("CREATE TABLE", "CREATE INDEX",
                                          "CREATE UNIQUE INDEX", "CREATE VIEW")):
            target.execute(sql)


def _timestamp_bounds(selections: list[Selection]) -> dict[str, str | None]:
    """created_at/started_at = earliest over sources, finished_at = latest."""
    out: dict[str, str | None] = {"created_at": None, "started_at": None, "finished_at": None}
    for sel in selections:
        conn = read_only(sel.source.db_path)
        try:
            row = conn.execute(
                f"select created_at, started_at, finished_at from {RUN_TABLE} where id=?",
                (sel.run_id,)).fetchone()
        finally:
            conn.close()
        if not row:
            continue
        for value, key in ((row["created_at"], "created_at"),
                           (row["started_at"], "started_at"),
                           (row["finished_at"], "finished_at")):
            if value is None:
                continue
            current = out[key]
            if current is None:
                out[key] = str(value)
            elif key == "finished_at":
                out[key] = max(str(current), str(value))
            else:
                out[key] = min(str(current), str(value))
    return out


def _partial_note(selections: list[Selection]) -> str | None:
    notes = [f"{s.source.scenario}: run {s.run_id[:8]} status={s.status or '?'}"
             for s in selections if s.status != "completed"]
    if not notes:
        return None
    return "PARTIAL MERGE — non-completed source runs: " + "; ".join(notes)


@dataclass
class MergeStats:
    run_id: str
    per_scenario: dict[str, int]
    read_rows: int
    copied_rows: int
    deduped_rows: int
    error_rows: int


def merge_runs(selections: list[Selection], merged_db: Path, *, label: str,
               arms: list[str], scenarios: list[str]) -> MergeStats:
    """Rebuild ``merged_db``: one unified run row + deduplicated result rows."""
    if not selections:
        raise MergeError("nothing to merge (no usable source selection)")
    for sel in selections:
        if Path(sel.source.db_path).resolve() == Path(merged_db).resolve():
            raise MergeError(f"refusing to overwrite a source DB: {merged_db}")
    if merged_db.exists() and merged_db.parent == MAIN_DB.parent:
        raise MergeError(f"refusing to write into the live data dir: {merged_db}")

    # Completed sources first: they supply the run-row template and win the dedupe
    # tie-break; plan order is preserved inside each priority class.
    ranked = sorted(enumerate(selections),
                    key=lambda p: (0 if p[1].status == "completed" else 1, p[0]))
    ordered = [sel for _, sel in ranked]
    priority = {id(sel): 1 if sel.status == "completed" else 0 for sel in selections}

    merged_db.parent.mkdir(parents=True, exist_ok=True)
    if merged_db.exists():
        merged_db.unlink()

    template_conn = read_only(ordered[0].source.db_path)
    target = sqlite3.connect(str(merged_db))
    target.row_factory = sqlite3.Row
    try:
        template = dict(template_conn.execute(
            f"select * from {RUN_TABLE} where id=?", (ordered[0].run_id,)).fetchone() or {})
        if not template:
            raise MergeError(f"run {ordered[0].run_id} not found in "
                             f"{ordered[0].source.db_path}")
        _copy_schema(target, ordered[0].source.db_path)
        result_cols = [c for c in table_columns(target, RESULT_TABLE) if c != "id"]
        if "run_id" not in result_cols:
            raise MergeError(f"{merged_db}: merged bench_results has no run_id column")

        # ---- collect rows, deduping on (scenario_id, question_id, mode)
        kept: dict[tuple[str, str, str], tuple[tuple[int, int], sqlite3.Row]] = {}
        read_rows = 0
        seq = 0
        for sel in ordered:
            conn = read_only(sel.source.db_path)
            try:
                clause, params = _mode_filter(arms)
                rows = conn.execute(
                    f"select * from {RESULT_TABLE} where run_id=? and scenario_id=?{clause} "
                    "order by rowid",
                    [sel.run_id, sel.source.scenario, *params]).fetchall()
                for row in rows:
                    read_rows += 1
                    key = (str(row["scenario_id"]), str(row["question_id"]), str(row["mode"]))
                    rank = (priority[id(sel)], -seq)
                    seq += 1
                    prev = kept.get(key)
                    if prev is None or rank > prev[0]:
                        kept[key] = (rank, row)
            finally:
                conn.close()

        # ---- one unified bench_runs row (analyzer contract)
        unified_id = str(uuid.uuid4())
        n_merged = len(kept)
        config = _loads(template.get("config")) or {}
        config["arms"] = arms
        config["scenarios"] = scenarios
        config["merged_from"] = [str(s.source.db_path) for s in ordered]
        config["merged_run_ids"] = {s.source.scenario: s.run_id for s in ordered}
        config["merged_run_status"] = {s.source.scenario: s.status for s in ordered}
        stamps = _timestamp_bounds(ordered)
        values = {
            **template,
            "id": unified_id,
            "label": label,
            "status": "completed",
            "scenario_ids": json.dumps(scenarios),
            "config": json.dumps(config),
            "progress_total": n_merged,
            "progress_done": n_merged,
            "progress_stage": "completed",
            "summary": None,
            "error": _partial_note(ordered),
            **stamps,
        }
        run_cols = [c for c in table_columns(target, RUN_TABLE) if c in values]
        target.execute(
            f"insert into {RUN_TABLE} ({','.join(run_cols)}) "
            f"values ({','.join('?' * len(run_cols))})",
            [values[c] for c in run_cols])

        # ---- fresh PK per copied row so source ids cannot collide
        per_scenario: dict[str, int] = {}
        error_rows = 0
        insert_sql = (f"insert into {RESULT_TABLE} (id,{','.join(result_cols)}) "
                      f"values ({','.join('?' * (len(result_cols) + 1))})")
        for row in (r for _, r in sorted(kept.values(), key=lambda item: -item[0][1])):
            available = set(row.keys())
            params: list = [str(uuid.uuid4())]          # fresh PK — never collides
            for col in result_cols:
                if col == "run_id":
                    params.append(unified_id)
                else:
                    params.append(row[col] if col in available else None)
            if "error" in available and str(row["error"] or "").strip():
                error_rows += 1
            sid = str(row["scenario_id"])
            per_scenario[sid] = per_scenario.get(sid, 0) + 1
            target.execute(insert_sql, params)
        target.commit()
    finally:
        target.close()
        template_conn.close()

    return MergeStats(unified_id, per_scenario, read_rows, n_merged,
                      read_rows - n_merged, error_rows)


def observed_arms(selections: list[Selection]) -> list[str]:
    """Distinct ``mode`` values in the selected runs (used when --arms is empty)."""
    arms: list[str] = []
    for sel in selections:
        conn = read_only(sel.source.db_path)
        try:
            for row in conn.execute(
                    f"select distinct mode from {RESULT_TABLE} where run_id=? order by mode",
                    (sel.run_id,)).fetchall():
                if row[0] not in arms:
                    arms.append(str(row[0]))
        finally:
            conn.close()
    return arms


# -------------------------------------------------------------------------- CLI
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Merge per-scenario parallel benchmark DBs into one merged run",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--run-ids", default="",
                        help="Comma-separated scenario:run_id pairs (e.g. squad:abc123,hotpotqa:def456); "
                             "overrides the meta file")
    parser.add_argument("--data-dirs", default="",
                        help="Comma-separated scenario:path pairs for source data directories; "
                             "overrides the meta file")
    parser.add_argument("--arms", default="",
                        help="Comma-separated arm names (bench_results.mode) narrowing the merge; "
                             "empty = every arm present in the selected runs. Arms that match no "
                             "mode anywhere warn and are ignored (bench_resume runs are keyed by "
                             "pipeline mode, not arm name)")
    parser.add_argument("--scenarios", default="",
                        help="Comma-separated scenario IDs narrowing the merge; "
                             "empty = the meta file list, else the built-in default")
    parser.add_argument("--label", default="", help="Label for the merged run")
    parser.add_argument("--meta", default=None,
                        help="parallel_run_meta.json to build the plan from "
                             "(default: <data-par>/parallel_run_meta.json; empty string disables it)")
    parser.add_argument("--data-par", default=str(DATA_PAR_DEFAULT),
                        help="Per-scenario data dir root used when neither --data-dirs "
                             "nor the meta file names a path")
    parser.add_argument("--out", default=str(MERGED_DB_DEFAULT),
                        help="Merged DB to (re)create")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    arms = split_list(args.arms)
    cli_run_ids = parse_pairs(args.run_ids)
    cli_data_dirs = parse_pairs(args.data_dirs)
    data_par = resolve_path(args.data_par)
    merged_db = Path(str(args.out)).expanduser()
    merged_db = merged_db if merged_db.is_absolute() else (ROOT / merged_db).resolve()

    meta = MetaPlan(note="meta file disabled (--meta '')")
    # Unset --meta follows --data-par / JEVRAG_DATA_PAR_ROOT, so one scratch root drives
    # the whole chain; an explicit empty --meta still disables the meta file entirely.
    meta_arg = str(data_par / "parallel_run_meta.json") if args.meta is None else args.meta
    if meta_arg:
        meta = load_meta(resolve_path(meta_arg))
    scenarios = split_list(args.scenarios) or meta.scenarios or split_list(DEFAULT_SCENARIOS)
    if not scenarios:
        print("ERROR: no scenarios selected (empty meta file and no --scenarios)", file=sys.stderr)
        return EXIT_MISSING_DB

    print(f"plan: {meta.note}")
    print(f"      data_par={data_par}")
    print(f"      merged db={merged_db}")
    if arms:
        print(f"      arms filter: {','.join(arms)}")
    plan = build_plan(scenarios, cli_run_ids, cli_data_dirs, meta, data_par)
    for src in plan:
        tag = "" if src.db_path.exists() else "  <- MISSING"
        run = f" run_id={src.run_id} [{src.run_origin}]" if src.run_id else " [auto-detect]"
        print(f"      {src.scenario:<12} db={src.db_path} [{src.path_origin}]{run}{tag}")

    selections, problems = resolve_selections(plan, arms or None)
    if problems and not selections and all(p.startswith("ARM MISMATCH") for p in problems):
        # Every source is healthy but none of them uses the requested arm names —
        # almost always a bench_resume (internal suite) run whose modes are
        # traditional|hybrid. Merge every arm rather than refusing.
        print(f"WARNING: --arms {','.join(arms)} matches no mode in any selected run — "
              "merging every arm present in the sources", file=sys.stderr)
        arms = []
        selections, problems = resolve_selections(plan, None)
    for problem in problems:
        print(f"ERROR: {problem}", file=sys.stderr)
    if problems:
        print(f"\nABORTED: {len(problems)} scenario(s) unusable — the merged DB was not written.",
              file=sys.stderr)
        if any(p.startswith("MISSING") or p.startswith("UNREADABLE") for p in problems):
            return EXIT_MISSING_DB
        return EXIT_EMPTY_SCENARIO

    print("\nselected (per scenario):")
    for sel in selections:
        print(f"  {sel.source.scenario:<12} run={sel.run_id} rows={sel.n_rows} "
              f"status={sel.status or '?'} origin={sel.source.run_origin}")
        for note in sel.notes:
            print(f"    note: {note}")

    merged_arms = arms or observed_arms(selections)
    label = args.label or f"merged {len(selections)} scenarios ({datetime.now():%Y-%m-%d})"
    try:
        stats = merge_runs(selections, merged_db, label=label, arms=merged_arms,
                           scenarios=[s.source.scenario for s in selections])
    except MergeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_BAD_SOURCE
    except sqlite3.Error as exc:
        print(f"ERROR: sqlite failure while writing {merged_db}: {exc}", file=sys.stderr)
        return EXIT_BAD_SOURCE

    print("\nmerged (deduplicated rows per scenario):")
    for scenario in [s.source.scenario for s in selections]:
        print(f"  {scenario:<12} {stats.per_scenario.get(scenario, 0)}")
    print(f"  arms: {','.join(merged_arms) or '(none)'}")
    print(f"\ntotal merged rows: {stats.copied_rows} — read {stats.read_rows}, "
          f"deduplicated {stats.deduped_rows}, error rows kept visible: {stats.error_rows}")
    print(f"merged db: {merged_db}")
    print("analyze it (from backend/):")
    print(f"  JEVRAG_DATA_DIR={merged_db.parent} .venv/bin/python scripts/analyze_testbench.py "
          f"{stats.run_id} --out ../docs/testbench-results.md")
    print(f"unified run id: {stats.run_id}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
