"""Tests for ``backend/scripts/_merge_par_run.py`` — hermetic.

Only temp SQLite fixtures built from the REAL ``app.db`` SQLAlchemy models: no
local models, no network, no cloud calls, and never the repo's own
``backend/data_par`` / ``backend/data_merged`` directories.

Run: cd backend && .venv/bin/python -m pytest tests/test_merge_par_run.py -v
"""
from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# Make the test hermetic BEFORE importing app code (same pattern as test_bench.py).
_TMP = tempfile.mkdtemp(prefix="jevrag-merge-test-")
os.environ.setdefault("JEVRAG_LAZY_MODELS", "1")
os.environ.setdefault("JEVRAG_DATA_DIR", _TMP)
os.environ.setdefault("JEVRAG_DASHSCOPE_API_KEY", "test-key")

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db import Base, BenchResult, BenchRun  # noqa: E402  (env must be set first)

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "_merge_par_run.py"


def _load_merge_module():
    spec = importlib.util.spec_from_file_location("_merge_par_run", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


merge = _load_merge_module()

T0 = datetime(2026, 9, 30, 12, 0, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------- fixture helpers
def make_db(path: Path) -> Path:
    """Create a DB with the real bench tables and return its path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    Base.metadata.create_all(engine, tables=[BenchRun.__table__, BenchResult.__table__])
    engine.dispose()
    return path


def add_run(db: Path, run_id: str, *, status: str = "completed", label: str = "worker",
            scenarios=("squad",), rows_for_progress: int = 0, config: dict | None = None,
            created: datetime = T0, finished: datetime | None = None) -> str:
    engine = create_engine(f"sqlite:///{db.as_posix()}")
    with Session(engine) as s:
        s.add(BenchRun(
            id=run_id, label=label, status=status, scenario_ids=list(scenarios),
            judge_model="kimi-k2.5",
            config=config or {"gate_mode": "features", "gate_score_threshold": 0.42},
            progress_total=rows_for_progress, progress_done=rows_for_progress,
            progress_stage=status, judge_selftest={"passed": 8},
            summary={"n": rows_for_progress}, error=None,
            created_at=created, started_at=created,
            finished_at=finished or (created if status == "completed" else None)))
        s.commit()
    engine.dispose()
    return run_id


def add_result(db: Path, run_id: str, *, scenario: str, qid: str, mode: str,
               row_id: str | None = None, answer: str = "ans", error: str | None = None,
               created: datetime = T0) -> str:
    engine = create_engine(f"sqlite:///{db.as_posix()}")
    with Session(engine) as s:
        s.add(BenchResult(
            id=row_id, run_id=run_id, scenario_id=scenario, question_id=qid,
            question=f"Q {qid}?", mode=mode, qtype="extractive", answerable=True,
            reference=f"ref {qid}", answer=answer, model="qwen3.7-plus", error=error,
            retrieved_files=[f"{scenario}-01.md"], pre_rerank_files=[f"{scenario}-01.md"],
            retrieval={"hit1": 1, "mrr": 1.0}, naive_retrieval=None,
            generation={"correctness": 1.0, "abstention": "answered"},
            pairwise=None, timings={"latency_ms": 12.5}, tokens_in=10, tokens_out=20,
            cost_usd=0.001, sufficiency_p=0.9, verification_p=0.8,
            routed_model="qwen3.7-plus", jev_decisions=[{"name": "gate", "answer": "easy"}],
            created_at=created))
        s.commit()
    engine.dispose()
    return run_id


def query(db: Path, sql: str, params: tuple = ()):
    conn = sqlite3.connect(str(db))
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def ro_conn(db: Path) -> sqlite3.Connection:
    return merge.read_only(db)


def cli(db_path: Path, data_par: Path, *extra: str) -> list[str]:
    """CLI argv for a meta-less merge over an explicit data_par root."""
    return ["--meta", "", "--data-par", str(data_par), "--out", str(db_path),
            *extra]


# ================================================================== pick_run
def test_pick_run_prefers_completed_run_with_most_rows(tmp_path):
    db = make_db(tmp_path / "app.db")
    add_result(db, add_run(db, "r-small-completed", status="completed"),
               scenario="squad", qid="q1", mode="base")
    big = add_run(db, "r-big-completed", status="completed")
    for i in range(3):
        add_result(db, big, scenario="squad", qid=f"q{i}", mode="base")
    # a NEWER running run with even more rows must not win the tie-break
    running = add_run(db, "r-running", status="running", created=T0.replace(hour=13))
    for i in range(5):
        add_result(db, running, scenario="squad", qid=f"r{i}", mode="base")
    add_result(db, big, scenario="squad", qid="x1", mode="gate-none")

    with ro_conn(db) as conn:
        assert merge.pick_run(conn, "squad") == (big, 4)


def test_pick_run_completed_beats_newest_on_equal_rows(tmp_path):
    db = make_db(tmp_path / "app.db")
    done = add_run(db, "r-done", status="completed")
    add_result(db, done, scenario="squad", qid="q1", mode="base")
    later = add_run(db, "r-later", status="window-budget-reached", created=T0.replace(hour=14))
    add_result(db, later, scenario="squad", qid="q2", mode="base")

    with ro_conn(db) as conn:
        assert merge.pick_run(conn, "squad") == (done, 1)


def test_pick_run_fallback_needs_no_completed_run(tmp_path):
    """Regression: the partial/resume fallback used to raise misuse-of-aggregate."""
    db = make_db(tmp_path / "app.db")
    interrupted = add_run(db, "r-interrupted", status="interrupted")
    oldest = add_run(db, "r-oldest", status="running", created=T0.replace(hour=11))
    for i in range(2):
        add_result(db, oldest, scenario="squad", qid=f"o{i}", mode="base")
    for i in range(4):
        add_result(db, interrupted, scenario="squad", qid=f"i{i}", mode="base")

    with ro_conn(db) as conn:
        run_id, n = merge.pick_run(conn, "squad")   # must not raise sqlite3.OperationalError
    assert (run_id, n) == (interrupted, 4)


def test_pick_run_ignores_other_scenarios_and_filters_arms(tmp_path):
    db = make_db(tmp_path / "app.db")
    run = add_run(db, "r-mixed", status="completed", scenarios=("squad", "hotpotqa"))
    add_result(db, run, scenario="hotpotqa", qid="h1", mode="base")
    add_result(db, run, scenario="squad", qid="s1", mode="base")
    add_result(db, run, scenario="squad", qid="s2", mode="gate-none")

    with ro_conn(db) as conn:
        assert merge.pick_run(conn, "squad") == (run, 2)
        assert merge.pick_run(conn, "squad", arms=["gate-none"]) == (run, 1)
        assert merge.pick_run(conn, "missing-scenario") == (None, 0)


def test_pick_run_on_empty_db_returns_none_zero(tmp_path):
    db = make_db(tmp_path / "app.db")
    with ro_conn(db) as conn:
        assert merge.pick_run(conn, "squad") == (None, 0)
    add_run(db, "r-no-rows", status="completed")     # a run row but no results
    with ro_conn(db) as conn:
        assert merge.pick_run(conn, "squad") == (None, 0)


# ============================================================== end-to-end merge
def _two_scenario_fixture(tmp_path):
    data_par = tmp_path / "data_par"
    squad = make_db(data_par / "squad" / "app.db")
    hotpot = make_db(data_par / "hotpotqa" / "app.db")
    squad_run = add_run(squad, "11111111-1111-1111-1111-111111111111", status="completed",
                        label="par-squad")
    hotpot_run = add_run(hotpot, "22222222-2222-2222-2222-222222222222", status="completed",
                         label="par-hotpotqa")
    for qid in ("sq1", "sq2"):
        add_result(squad, squad_run, scenario="squad", qid=qid, mode="base")
        add_result(squad, squad_run, scenario="squad", qid=qid, mode="gate-none")
    for qid in ("hp1", "hp2"):
        add_result(hotpot, hotpot_run, scenario="hotpotqa", qid=qid, mode="base")
        add_result(hotpot, hotpot_run, scenario="hotpotqa", qid=qid, mode="gate-none",
                   error="APITimeoutError")
    return data_par, squad, hotpot


def test_merge_end_to_end_one_unified_run(tmp_path, capsys):
    data_par, _, _ = _two_scenario_fixture(tmp_path)
    out = tmp_path / "data_merged" / "app.db"

    rc = merge.main(cli(out, data_par, "--scenarios", "squad,hotpotqa", "--label", "merged-x"))

    assert rc == merge.EXIT_OK
    assert out.exists()
    runs = query(out, "select id,status,label,scenario_ids,config,progress_total,"
                      "progress_done,summary from bench_runs")
    assert len(runs) == 1
    run_id, status, label, scenario_ids, config, total, done, summary = runs[0]
    assert (status, label, total, done) == ("completed", "merged-x", 8, 8)
    assert json.loads(scenario_ids) == ["squad", "hotpotqa"]
    cfg = json.loads(config)
    assert cfg["scenarios"] == ["squad", "hotpotqa"]
    assert cfg["gate_score_threshold"] == 0.42          # inherited from the source config
    assert cfg["merged_run_ids"] == {"squad": "11111111-1111-1111-1111-111111111111",
                                     "hotpotqa": "22222222-2222-2222-2222-222222222222"}
    assert summary is None                              # no stale single-scenario summary
    assert query(out, "select count(*) from bench_results where run_id=?", (run_id,))[0][0] == 8
    assert dict(query(out, "select scenario_id, count(*) from bench_results group by 1")) == \
        {"squad": 4, "hotpotqa": 4}
    # every merged row carries the unified run id and a distinct PK
    assert query(out, "select count(distinct id) from bench_results") == [(8,)]
    assert query(out, "select count(*) from bench_results where run_id != ?", (run_id,)) == [(0,)]
    # payload fidelity + the analyzer's last line
    assert query(out, "select answer, retrieval from bench_results limit 1") == \
        [("ans", '{"hit1": 1, "mrr": 1.0}')]
    captured = capsys.readouterr().out
    assert f"unified run id: {run_id}" in captured.splitlines()[-1]


def test_merge_is_idempotent_and_keeps_sources_untouched(tmp_path, capsys):
    data_par, squad, hotpot = _two_scenario_fixture(tmp_path)
    out = tmp_path / "data_merged" / "app.db"
    before = {p: p.read_bytes() for p in (squad, hotpot)}

    for _ in range(2):
        rc = merge.main(cli(out, data_par, "--scenarios", "squad,hotpotqa"))
        capsys.readouterr()
        assert rc == merge.EXIT_OK
        assert query(out, "select count(*) from bench_runs") == [(1,)]
        assert query(out, "select count(*) from bench_results") == [(8,)]

    # strict read-only access: a source byte may not change
    assert {p: p.read_bytes() for p in (squad, hotpot)} == before
    with pytest.raises(sqlite3.OperationalError):
        with ro_conn(squad) as conn:
            conn.execute("delete from bench_results")
            conn.commit()


def test_merge_gives_fresh_pks_when_source_row_ids_collide(tmp_path, capsys):
    data_par = tmp_path / "data_par"
    squad = make_db(data_par / "squad" / "app.db")
    hotpot = make_db(data_par / "hotpotqa" / "app.db")
    shared = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    squad_run = add_run(squad, "r-squad", status="completed")
    hotpot_run = add_run(hotpot, "r-hotpot", status="completed")
    add_result(squad, squad_run, scenario="squad", qid="q1", mode="base", row_id=shared)
    add_result(hotpot, hotpot_run, scenario="hotpotqa", qid="q1", mode="base", row_id=shared)

    out = tmp_path / "data_merged" / "app.db"
    rc = merge.main(cli(out, data_par, "--scenarios", "squad,hotpotqa"))
    capsys.readouterr()

    assert rc == merge.EXIT_OK
    assert query(out, "select count(*) from bench_results") == [(2,)]
    assert query(out, "select count(distinct id) from bench_results") == [(2,)]
    assert query(out, "select count(*) from bench_results where id = ?", (shared,)) == [(0,)]


def test_merge_dedupes_duplicate_triples_in_one_run(tmp_path, capsys):
    data_par = tmp_path / "data_par"
    squad = make_db(data_par / "squad" / "app.db")
    run = add_run(squad, "r-dupe", status="completed")
    add_result(squad, run, scenario="squad", qid="q1", mode="base", answer="first")
    add_result(squad, run, scenario="squad", qid="q1", mode="base", answer="second")
    add_result(squad, run, scenario="squad", qid="q2", mode="base", answer="other")

    out = tmp_path / "data_merged" / "app.db"
    rc = merge.main(cli(out, data_par, "--scenarios", "squad"))
    summary = capsys.readouterr().out

    assert rc == merge.EXIT_OK
    assert query(out, "select count(*) from bench_results") == [(2,)]
    assert dict(query(out, "select question_id, answer from bench_results")) == \
        {"q1": "first", "q2": "other"}
    assert "deduplicated 1" in summary


def test_merge_reports_arms_and_total_in_summary(tmp_path, capsys):
    data_par, _, _ = _two_scenario_fixture(tmp_path)
    out = tmp_path / "data_merged" / "app.db"
    assert merge.main(cli(out, data_par, "--scenarios", "squad,hotpotqa")) == merge.EXIT_OK
    printed = capsys.readouterr().out
    assert "total merged rows: 8" in printed
    assert "deduplicated 0" in printed
    assert "error rows kept visible: 2" in printed
    assert "base,gate-none" in printed          # arms observed from the sources


# ============================================================ meta-file handling
def _meta(path: Path, workers: list[dict], **extra) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "label": "par", **extra, "workers": workers}),
                    encoding="utf-8")
    return path


def test_meta_workers_select_run_ids_and_data_dirs(tmp_path, capsys):
    data_par, squad, hotpot = _two_scenario_fixture(tmp_path)
    # a decoy completed run with MORE rows than the meta-selected one
    decoy = add_run(squad, "r-decoy", status="completed")
    for i in range(5):
        add_result(squad, decoy, scenario="squad", qid=f"d{i}", mode="base")
    custom = tmp_path / "elsewhere" / "hp-custom"
    custom.mkdir(parents=True)
    (custom / "app.db").write_bytes(hotpot.read_bytes())

    meta = _meta(data_par / "parallel_run_meta.json", [
        {"scenario": "squad", "run_id": "11111111-1111-1111-1111-111111111111",
         "data_dir": str(data_par / "squad")},
        {"scenario": "hotpotqa", "run_id": "22222222-2222-2222-2222-222222222222",
         "data_dir": str(custom)},
    ], scenarios="squad,hotpotqa")
    out = tmp_path / "data_merged" / "app.db"

    rc = merge.main(["--meta", str(meta), "--out", str(out)])
    capsys.readouterr()

    assert rc == merge.EXIT_OK
    assert query(out, "select count(*) from bench_results") == [(8,)]
    assert query(out, "select count(*) from bench_results where question_id like 'd%'") == [(0,)]


def test_cli_flags_override_the_meta_file(tmp_path, capsys):
    data_par, squad, _ = _two_scenario_fixture(tmp_path)
    bogus = tmp_path / "does-not-exist"
    meta = _meta(data_par / "parallel_run_meta.json", [
        {"scenario": "squad", "run_id": "deadbeef", "data_dir": str(bogus)},
    ], scenarios="squad")
    out = tmp_path / "data_merged" / "app.db"

    rc = merge.main(["--meta", str(meta), "--out", str(out),
                     "--data-dirs", f"squad:{squad.parent}",
                     "--run-ids", "squad:11111111-1111-1111-1111-111111111111"])
    capsys.readouterr()

    assert rc == merge.EXIT_OK
    assert query(out, "select count(*) from bench_results") == [(4,)]


def test_stale_meta_run_id_falls_back_to_auto_detect(tmp_path, capsys):
    data_par, _, _ = _two_scenario_fixture(tmp_path)
    meta = _meta(data_par / "parallel_run_meta.json", [
        {"scenario": "squad", "run_id": "no-such-run", "data_dir": str(data_par / "squad")},
    ], scenarios="squad")
    out = tmp_path / "data_merged" / "app.db"

    assert merge.main(["--meta", str(meta), "--out", str(out)]) == merge.EXIT_OK
    printed = capsys.readouterr().out
    assert "auto-detected instead" in printed
    assert query(out, "select count(*) from bench_results") == [(4,)]


def test_legacy_run_ids_meta_shape_is_accepted(tmp_path):
    meta = tmp_path / "parallel_run_meta.json"
    meta.write_text(json.dumps({"label": "old", "scenarios": "squad,hotpotqa",
                               "run_ids": {"squad": "abc"}}), encoding="utf-8")
    plan = merge.load_meta(meta)
    assert plan.run_ids == {"squad": "abc"}
    assert plan.data_dirs == {}
    assert plan.scenarios == ["squad", "hotpotqa"]


def test_unparseable_meta_is_not_fatal(tmp_path, capsys):
    meta = tmp_path / "parallel_run_meta.json"
    meta.write_text("{not json", encoding="utf-8")
    data_par, _, _ = _two_scenario_fixture(tmp_path)
    out = tmp_path / "data_merged" / "app.db"

    rc = merge.main(["--meta", str(meta), "--out", str(out), "--scenarios", "squad",
                     "--data-par", str(data_par)])
    printed = capsys.readouterr().out
    assert rc == merge.EXIT_OK
    assert "unreadable" in printed


# ================================================================ loud failures
def test_zero_row_scenario_aborts_loudly_without_writing(tmp_path, capsys):
    data_par, squad, _ = _two_scenario_fixture(tmp_path)
    empty = make_db(data_par / "musique" / "app.db")
    add_run(empty, "r-empty", status="running")
    out = tmp_path / "data_merged" / "app.db"

    rc = merge.main(cli(out, data_par, "--scenarios", "squad,musique"))
    err = capsys.readouterr().err

    assert rc == merge.EXIT_EMPTY_SCENARIO
    assert not out.exists()
    assert "musique" in err and "EMPTY" in err
    assert "ABORTED" in err


def test_scenario_without_a_db_reports_missing(tmp_path, capsys):
    data_par, _, _ = _two_scenario_fixture(tmp_path)
    out = tmp_path / "data_merged" / "app.db"

    rc = merge.main(cli(out, data_par, "--scenarios", "squad,never-ran"))
    err = capsys.readouterr().err

    assert rc == merge.EXIT_MISSING_DB
    assert not out.exists()
    assert "MISSING" in err and "never-ran" in err


def test_explicit_run_id_with_no_rows_is_a_loud_failure(tmp_path, capsys):
    data_par, _, _ = _two_scenario_fixture(tmp_path)
    out = tmp_path / "data_merged" / "app.db"

    rc = merge.main(cli(out, data_par, "--scenarios", "squad",
                        "--run-ids", "squad:11111111-1111-1111-1111-111111111111"))
    capsys.readouterr()
    assert rc == merge.EXIT_OK                      # valid: 4 squad rows in that run

    rc = merge.main(cli(out, data_par, "--scenarios", "squad", "--run-ids", "squad:nope"))
    err = capsys.readouterr().err
    assert rc == merge.EXIT_EMPTY_SCENARIO
    assert "nope" in err and "MISSING" not in err


def test_arms_filter_narrows_rows_and_survives_a_mismatch(tmp_path, capsys):
    data_par, _, _ = _two_scenario_fixture(tmp_path)
    out = tmp_path / "data_merged" / "app.db"

    # arms that exist -> result rows are narrowed to them
    assert merge.main(cli(out, data_par, "--scenarios", "squad,hotpotqa",
                          "--arms", "base")) == merge.EXIT_OK
    printed = capsys.readouterr().out
    assert "total merged rows: 4" in printed
    assert query(out, "select distinct mode from bench_results") == [("base",)]

    # partially matching arms -> merge the matching subset only
    assert merge.main(cli(out, data_par, "--scenarios", "squad,hotpotqa",
                          "--arms", "base,rerank-jev")) == merge.EXIT_OK
    printed = capsys.readouterr().out
    assert "total merged rows: 4" in printed
    assert query(out, "select distinct mode from bench_results") == [("base",)]

    # arms that match NOTHING anywhere (e.g. a bench_resume run whose modes are
    # traditional|hybrid) -> loud warning, every arm merged instead of refusing
    assert merge.main(cli(out, data_par, "--scenarios", "squad",
                          "--arms", "rerank-jev")) == merge.EXIT_OK
    captured = capsys.readouterr()
    assert "ARM MISMATCH" in captured.err or "matches no mode" in captured.err
    assert "total merged rows: 4" in captured.out
    assert query(out, "select distinct mode from bench_results order by 1") == \
        [("base",), ("gate-none",)]


def test_partial_source_is_flagged_not_silently_ok(tmp_path, capsys):
    data_par = tmp_path / "data_par"
    squad = make_db(data_par / "squad" / "app.db")
    run = add_run(squad, "r-window", status="window-budget-reached")
    add_result(squad, run, scenario="squad", qid="q1", mode="base")
    out = tmp_path / "data_merged" / "app.db"

    assert merge.main(cli(out, data_par, "--scenarios", "squad")) == merge.EXIT_OK
    printed = capsys.readouterr().out
    assert "PARTIAL" in printed
    assert query(out, "select status, error from bench_runs")[0][0] == "completed"
    assert "PARTIAL MERGE" in query(out, "select error from bench_runs")[0][0]


# ============================================================== merge_runs unit
def test_merge_runs_prefers_row_from_completed_run(tmp_path):
    data_par, _, _ = _two_scenario_fixture(tmp_path)
    partial_db = make_db(tmp_path / "other" / "squad2" / "app.db")
    partial_run = add_run(partial_db, "r-partial", status="interrupted")
    for qid in ("sq1", "sq2"):
        add_result(partial_db, partial_run, scenario="squad", qid=qid, mode="base",
                   answer="from-partial")
    add_result(partial_db, partial_run, scenario="squad", qid="sq3", mode="base",
               answer="only-partial")

    completed_sel = merge.Selection(
        merge.Source("squad", data_par / "squad" / "app.db", run_origin="auto",
                     path_origin="convention"),
        "11111111-1111-1111-1111-111111111111", "completed", 4)
    partial_sel = merge.Selection(
        merge.Source("squad", partial_db, run_origin="auto", path_origin="convention"),
        partial_run, "interrupted", 3)
    out = tmp_path / "merged" / "app.db"

    for order in ([completed_sel, partial_sel], [partial_sel, completed_sel]):
        if out.exists():
            out.unlink()
        stats = merge.merge_runs(order, out, label="x", arms=[], scenarios=["squad"])
        assert stats.read_rows == 7
        assert stats.copied_rows == 5          # sq1/sq2 base collapse onto the completed row
        assert stats.deduped_rows == 2
        answers = dict(query(out, "select question_id, answer from bench_results"))
        assert answers["sq1"] == "ans" and answers["sq3"] == "only-partial"
        assert query(out, "select count(*) from bench_runs") == [(1,)]


def test_merge_runs_refuses_to_overwrite_a_source(tmp_path):
    data_par, squad, _ = _two_scenario_fixture(tmp_path)
    sel = merge.Selection(merge.Source("squad", squad), "11111111-1111-1111-1111-111111111111",
                          "completed", 4)
    with pytest.raises(merge.MergeError):
        merge.merge_runs([sel], squad, label="x", arms=[], scenarios=["squad"])


def test_cli_defaults_are_repo_anchored(tmp_path):
    """No absolute paths baked in: defaults derive from this script's own location."""
    parser = merge.build_parser()
    defaults = {a.dest: a.default for a in parser._actions}
    assert Path(defaults["out"]).is_absolute()
    assert str(merge.BACKEND) in defaults["out"]
    assert Path(defaults["out"]).parent == merge.BACKEND / "data_merged"
    assert Path(defaults["meta"]) == merge.META_DEFAULT
    assert merge.ROOT == Path(__file__).resolve().parents[2]
