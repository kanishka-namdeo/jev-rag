"""Hermetic tests for the hybrid v2 pipeline logic (no models, no network).

Covers the shared policy functions (used by BOTH the SSE pipeline and the bench
runner — keeping them identical is a bench contract) and the new JevEngine
decision methods with a mocked decide() backend.
"""
from __future__ import annotations

import os
import tempfile

# Make tests hermetic BEFORE importing app code: lazy models, temp data dir.
_TMP = tempfile.mkdtemp(prefix="jevrag-test-")
os.environ.setdefault("JEVRAG_LAZY_MODELS", "1")
os.environ.setdefault("JEVRAG_DATA_DIR", _TMP)
os.environ.setdefault("JEVRAG_DASHSCOPE_API_KEY", "test-key")


# ------------------------------------------------------------------ policy fns

def test_parse_citations():
    from app.rag.pipelines import parse_citations

    assert parse_citations("Plain answer with no markers.") == []
    assert parse_citations("It is 42 [1].") == [1]
    assert parse_citations("A [2] then B [1].") == [2, 1]          # first-use order
    assert parse_citations("A [2] and again [2].") == [2]          # dedupe
    assert parse_citations("Cited twice [1][3].") == [1, 3]
    assert parse_citations("Comma form [1, 3] too.") == [1, 3]
    assert parse_citations("Nested junk [n] [12a] ok.") == []


def test_apply_battery_policy():
    from app.config import Settings
    from app.rag.pipelines import apply_battery_policy

    s = Settings(_env_file=None)
    chunks = [{"index": 1, "jev_score": 0.9}, {"index": 2, "jev_score": 0.9},
              {"index": 3, "jev_score": 0.8}, {"index": 4, "jev_score": 0.05}]
    verdicts = {
        1: {"evidence": 0.9, "contradiction": 0.02, "injection": 0.01},  # clean include
        2: {"evidence": 0.8, "contradiction": 0.70, "injection": 0.01},  # conflict-block
        3: {"evidence": 0.9, "contradiction": 0.02, "injection": 0.95},  # injection drop
        4: {"evidence": 0.02, "contradiction": 0.01, "injection": 0.01}, # no evidence, weak rel
    }
    actions, reasons = apply_battery_policy(chunks, verdicts, s)
    assert actions[1] == "include"
    assert actions[2] == "conflict"
    assert actions[3] == "drop" and "injection" in reasons[3]
    assert actions[4] == "drop" and "no evidence" in reasons[4]

    # relevance rescue: weak evidence but strong rerank relevance -> keep
    rescue = [{"index": 5, "jev_score": 0.93}]
    actions2, _ = apply_battery_policy(
        rescue, {5: {"evidence": 0.02, "contradiction": 0.1, "injection": 0.0}}, s)
    assert actions2[5] == "include"

    # ordered policy: injection outranks contradiction (security first)
    both = [{"index": 6, "jev_score": 0.9}]
    actions3, _ = apply_battery_policy(
        both, {6: {"evidence": 0.9, "contradiction": 0.9, "injection": 0.95}}, s)
    assert actions3[6] == "drop"


def test_citation_summary():
    from app.config import Settings
    from app.rag.pipelines import citation_summary

    s = Settings(_env_file=None)  # jev_citation_confidence = 0.8
    verdicts = {
        1: {"verdict": "supports", "confidence": 0.94},
        2: {"verdict": "supports", "confidence": 0.64},   # below auto-accept
        3: {"verdict": "contradicts", "confidence": 0.85},
    }
    frac, contradicts, flags = citation_summary(verdicts, s)
    assert abs(frac - 1 / 3) < 1e-9
    assert contradicts is True
    assert flags[1]["verified"] is True and flags[2]["verified"] is False
    assert flags[3]["verdict"] == "contradicts"

    frac0, contradicts0, flags0 = citation_summary({}, s)
    assert frac0 is None and contradicts0 is False and flags0 == {}

    _, contradicts_only, _ = citation_summary(
        {4: {"verdict": "says_nothing", "confidence": 0.9}}, s)
    assert contradicts_only is False


def test_composite_quality():
    from app.rag.pipelines import composite_quality

    # TypeSafe's own example weights: 0.4 answers + 0.4 cites + 0.2 no-conflict
    assert composite_quality(1.0, 1.0, False) == 1.0
    assert composite_quality(0.0, 0.0, True) == 0.0
    assert composite_quality(0.5, 1.0, False) == round(0.4 * 0.5 + 0.4 * 1.0 + 0.2, 3)
    assert composite_quality(1.0, 0.5, True) == round(0.4 + 0.2 + 0.0, 3)


# ------------------------------------------------------------------ prompts

def test_format_conflict_block():
    from app.rag.prompts import format_conflict_block

    out = format_conflict_block([{"chunk_index_label": 3, "filename": "a.md", "text": "T"}])
    assert "Conflicting evidence" in out
    assert "Passage [3] (source: a.md)" in out


# ------------------------------------------------------------------ engine (mocked)

def _engine():
    from app.config import Settings
    from app.llm.jev_engine import JevEngine

    return JevEngine(Settings(_env_file=None))


def test_effort_routing_parses_choice():
    eng = _engine()
    eng._decide = lambda state, questions: {  # type: ignore[method-assign]
        "model": "mock",
        "answers": {
            "effort": {"choice": "multi_step",
                       "probabilities": {"single_pass": 0.1, "multi_step": 0.8,
                                         "no_retrieval": 0.1},
                       "confidence": 0.62},
        },
        "usage": {"input_tokens": 10},
    }
    chosen, probs, conf, rec = eng.effort_routing("Compare A and B")
    assert chosen == "multi_step"
    assert abs(probs["multi_step"] - 0.8) < 1e-9
    assert abs(conf - 0.62) < 1e-9
    assert rec["name"] == "effort" and rec["kind"] == "choice" and rec["answer"] == "multi_step"
    assert rec["probabilities"]["multi_step"] == 0.8


def test_screen_passages_extracts_verdicts():
    eng = _engine()

    def fake_decide(state, questions):
        assert state.startswith("Question:")
        assert set(questions) == {"e1", "x1", "i1", "e2", "x2", "i2"}
        return {"answers": {
            "e1": {"noul": 0.91}, "x1": {"noul": 0.03}, "i1": {"noul": 0.01},
            "e2": {"noul": 0.05}, "x2": {"noul": 0.66}, "i2": {"noul": 0.02},
        }, "usage": None}

    eng._decide = fake_decide  # type: ignore[method-assign]
    chunks = [{"index": 1, "text": "gold"}, {"index": 2, "text": "conflicting"}]
    verdicts, rec = eng.screen_passages("q", chunks, char_limit=100)
    assert verdicts[1]["evidence"] == 0.91 and verdicts[1]["contradiction"] == 0.03
    assert verdicts[2]["contradiction"] == 0.66
    assert rec["name"] == "battery" and rec["kind"] == "noul"
    assert rec["probabilities"]["[2] conflict"] == 0.66
    assert "passage 1" in rec["answer"]


def test_sufficiency_standalone():
    eng = _engine()
    eng._decide = lambda state, questions: {  # type: ignore[method-assign]
        "answers": {"sufficiency": {"noul": 0.83}}, "usage": None}
    p, rec = eng.sufficiency("q", "ctx")
    assert abs(p - 0.83) < 1e-9
    assert rec["name"] == "sufficiency"
    assert rec["probabilities"] == {"false": 0.17, "true": 0.83}


def test_select_best_candidate_ranks():
    eng = _engine()
    eng._decide = lambda state, questions: {  # type: ignore[method-assign]
        "answers": {"cand_direct": {"noul": 0.97}, "cand_reasoned": {"noul": 0.81}},
        "usage": None}
    winner, scores, rec = eng.select_best_candidate(
        "q", "ctx", {"direct": "answer a", "reasoned": "answer b"})
    assert winner == "direct"
    assert scores["direct"] > scores["reasoned"]
    assert rec["name"] == "best_of_2" and rec["answer"] == "direct"


def test_verify_citations_and_quality_batch():
    eng = _engine()
    calls: list[set] = []

    def fake_decide(state, questions):
        # citations + groundedness + addresses share ONE call (fan-out batching)
        calls.append(set(questions))
        assert "grounded" in questions and "addresses" in questions
        assert "Proposed answer" in state
        return {"answers": {
            "cite_1": {"choice": "supports", "confidence": 0.94,
                       "probabilities": {"supports": 0.94, "contradicts": 0.02,
                                         "says_nothing": 0.04}},
            "cite_2": {"choice": "says_nothing", "confidence": 0.64,
                       "probabilities": {"supports": 0.2, "contradicts": 0.1,
                                         "says_nothing": 0.7}},
            "grounded": {"noul": 0.95},
            "addresses": {"noul": 0.88},
        }, "usage": {"input_tokens": 42}}

    eng._decide = fake_decide  # type: ignore[method-assign]
    passages = [
        {"chunk_index_label": 1, "text": "p1"},
        {"chunk_index_label": 2, "text": "p2"},
    ]
    verdicts, grounded, addresses, recs = eng.verify_citations_and_quality(
        "q", "answer [1] and [2]", "ctx", passages, [1, 2], 1600)
    assert calls == [{"cite_1", "cite_2", "grounded", "addresses"}]
    assert verdicts[1]["verdict"] == "supports" and verdicts[1]["confidence"] == 0.94
    assert verdicts[2]["verdict"] == "says_nothing"
    assert grounded == 0.95 and addresses == 0.88
    names = [r["name"] for r in recs]
    assert names == ["citations", "verification", "addresses"]
    assert recs[0]["probabilities"]["[1] supports"] == 0.94
    assert recs[1]["answer"] == 0.95

    # no citations -> only the two quality nouls, no citations record
    v2, g2, a2, recs2 = eng.verify_citations_and_quality(
        "q", "no citations here", "ctx", passages, [], 1600)
    assert calls[-1] == {"grounded", "addresses"}
    assert v2 == {} and [r["name"] for r in recs2] == ["verification", "addresses"]


def test_engine_effort_options_match_experiment():
    """The shipped option set must stay identical to the validated experiment A1."""
    from app.llm.jev_engine import EFFORT_OPTIONS

    assert set(EFFORT_OPTIONS) == {"no_retrieval", "single_pass", "multi_step"}
    for v in EFFORT_OPTIONS.values():
        assert isinstance(v, str) and len(v) > 20
