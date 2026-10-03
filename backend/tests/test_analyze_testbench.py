"""Tests for ``backend/scripts/analyze_testbench.py`` — hermetic.

Covers the gate-operating-point lookup only: the paired-statistics maths is already
tested in ``test_stats.py`` and the metric formulas in ``test_bench.py``.

Run: cd backend && .venv/bin/python -m pytest tests/test_analyze_testbench.py -v
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="jevrag-analyze-test-")
os.environ.setdefault("JEVRAG_LAZY_MODELS", "1")
os.environ.setdefault("JEVRAG_DATA_DIR", _TMP)
os.environ.setdefault("JEVRAG_DASHSCOPE_API_KEY", "test-key")

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "analyze_testbench.py"
DRIVER = Path(__file__).resolve().parents[1] / "scripts" / "run_testbench.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("analyze_testbench", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_driver():
    spec = importlib.util.spec_from_file_location("run_testbench", DRIVER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


analyze_testbench = _load_module()
run_testbench = _load_driver()


def test_nested_base_config_is_the_testbench_shape():
    """run_testbench.py records the knobs under config["base"] — the regression."""
    cfg = {"testbench": True, "arms": ["base"],
           "base": {"gate_mode": "features", "gate_score_threshold": 0.6}}
    assert analyze_testbench.gate_threshold_from_config(cfg) == 0.6


def test_flat_legacy_config_still_resolves():
    cfg = {"gate_mode": "features", "gate_score_threshold": 0.72}
    assert analyze_testbench.gate_threshold_from_config(cfg) == 0.72


def test_nested_wins_over_flat_when_both_present():
    cfg = {"gate_score_threshold": 0.5, "base": {"gate_score_threshold": 0.6}}
    assert analyze_testbench.gate_threshold_from_config(cfg) == 0.6


def test_jev_gate_mode_reads_the_sufficiency_knob_not_the_score_one():
    cfg = {"base": {"gate_mode": "jev", "gate_score_threshold": 0.6,
                    "jev_sufficiency_threshold": 0.44}}
    assert analyze_testbench.gate_threshold_from_config(cfg) == 0.44


def test_missing_config_falls_back_to_the_documented_default():
    for cfg in (None, {}, {"base": {}}, {"base": {"gate_mode": "jev"}}):
        assert analyze_testbench.gate_threshold_from_config(cfg) == 0.5


def test_zero_threshold_is_not_treated_as_absent():
    """0.0 is a valid operating point; `or`-style defaults would silently replace it."""
    assert analyze_testbench.gate_threshold_from_config(
        {"base": {"gate_mode": "features", "gate_score_threshold": 0.0}}) == 0.0


def test_jev_threshold_nested_and_default():
    assert analyze_testbench.jev_threshold_from_config(
        {"base": {"jev_sufficiency_threshold": 0.4}}) == 0.4
    assert analyze_testbench.jev_threshold_from_config({}) == 0.5


def test_features_gate_escalation_reads_the_string_verdict():
    esc = analyze_testbench.gate_escalated
    assert esc("escalate") is True
    assert esc("easy") is False
    assert esc(None) is False


def test_jev_gate_escalation_reads_the_probability_below_threshold():
    """gate_mode=jev records a float, so a string-only match made gate-jev read 0% always."""
    esc = analyze_testbench.gate_escalated
    assert esc(0.962) is False        # sufficient -> stay on the easy path
    assert esc(0.31) is True          # insufficient -> escalate
    assert esc(0.5, jev_threshold=0.5) is False
    assert esc(0.49, jev_threshold=0.6) is True


def test_bool_gate_answer_is_not_mistaken_for_a_probability():
    assert analyze_testbench.gate_escalated(True) is True
    assert analyze_testbench.gate_escalated(False) is False


def test_driver_records_every_knob_the_analyzer_reads():
    """The phantom-operating-point regression class: run_testbench.py once forgot
    jev_sufficiency_threshold in config["base"], so the analyzer calibrated the
    gate-jev arm at a hardcoded 0.5 the run never used. base_config() is the
    single place knobs are recorded — every analyzer lookup must resolve here."""
    from app.config import Settings

    cfg = run_testbench.base_config(Settings(_env_file=None))
    assert cfg["gate_score_threshold"] == analyze_testbench.gate_threshold_from_config(
        {"base": cfg})
    assert cfg["jev_sufficiency_threshold"] == analyze_testbench.jev_threshold_from_config(
        {"base": cfg})
    # and the values are the live code defaults, not stale literals
    fields = Settings.model_fields
    assert cfg["gate_score_threshold"] == fields["gate_score_threshold"].default
    assert cfg["jev_sufficiency_threshold"] == fields["jev_sufficiency_threshold"].default
