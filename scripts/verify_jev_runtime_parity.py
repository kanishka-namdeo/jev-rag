"""Parity + memory test: JevStyleDecisionGGUF stock flags vs Jev-RAG trimmed flags.

Runs the same decision battery (noul, 3-option choice, multi-question fan-out —
the exact shapes the pipeline uses) through two runtimes in one process (sequentially,
one at a time) and compares answers bit-for-bit, then reports each child's RSS.

Exit 0 = identical answers; exit 1 = mismatch/ failure.
"""
import json
import os
import subprocess
import sys

os.environ["JEV_SCORE_N_CTX"] = "8192"
sys.path.insert(0, "/home/z/my-project/models/jev-style")

STATE = ("Customer question: What is the maximum message size for the NimbusDB Pro tier "
         "and how does it compare across tiers?\n\n"
         "Passage [1] (source: bench-techdocs-02-limits.md):\n"
         "NimbusDB tiers: Starter caps messages at 16 MB, Pro at 256 MB, and Enterprise at 1 GB. "
         "Quotas refresh monthly.\n\n"
         "Passage [2] (source: bench-techdocs-01-overview.md):\n"
         "NimbusDB is a streaming platform with three tiers.\n\n"
         "Passage [3] (source: bench-techdocs-03-api.md):\n"
         "The REST API accepts payloads up to the tier message limit.\n\n"
         "Passage [4] (source: bench-techdocs-04-architecture.md):\n"
         "Brokers persist messages to tier-specific storage volumes with tier-scoped replication.")

QUESTIONS = [
    # noul (single) — sufficiency shape
    {"t": "noul", "ins": "The passages above are sufficient to answer the customer question."},
    # choice — effort routing shape
    {"t": "choice", "ins": "Classify the customer question.",
     "crit": {"no_retrieval": "a conversational request not needing documents",
              "single_pass": "one document passage answers it",
              "multi_step": "it requires combining multiple documents"}},
    # multi-question fan-out — rerank shape (4 nouls, one per passage)
    {"t": "noul", "ins": "Passage [1] helps answer the question."},
    {"t": "noul", "ins": "Passage [2] helps answer the question."},
    {"t": "noul", "ins": "Passage [3] helps answer the question."},
    {"t": "noul", "ins": "Passage [4] helps answer the question."},
]


def child_rss_mb(proc: subprocess.Popen) -> float:
    for _ in range(20):
        try:
            status = open(f"/proc/{proc.pid}/status").read()
            return int(status.split("VmRSS:")[1].split("kB")[0]) / 1024
        except Exception:
            pass
    return -1.0


def run_variant(label: str, env_extra: dict) -> tuple[dict, float]:
    for k in ("JEV_SCORE_N_SEQ_MAX", "JEV_SCORE_N_OUTPUTS_MAX", "JEV_SCORE_RLIMIT_DATA_MB"):
        os.environ.pop(k, None)
    os.environ.update(env_extra)
    import importlib
    import jev_style_decision_gguf as rt
    importlib.reload(rt)  # re-read spawn-time env defaults
    runtime = rt.JevStyleDecisionGGUF(
        model_dir="/home/z/my-project/models/jev-style", quant="Q4_K_M")
    try:
        out = runtime.decide_many(STATE, QUESTIONS)
        rss = child_rss_mb(runtime.proc)
        print(f"{label}: RSS = {rss:.0f} MB   (n_seq_max={runtime.info.get('n_seq_max')}, "
              f"n_outputs_max={runtime.info.get('n_outputs_max')})")
        return out, rss
    finally:
        runtime.close()


stock, stock_rss = run_variant("stock (seq17/out256)", {})
trim, trim_rss = run_variant("trim  (seq2/out32)",
                             {"JEV_SCORE_N_SEQ_MAX": "2", "JEV_SCORE_N_OUTPUTS_MAX": "32"})

# The runtime returns per-question result dicts; compare full JSON for bit-parity.
stock_json = json.dumps(stock, sort_keys=True)
trim_json = json.dumps(trim, sort_keys=True)
print("\nanswers identical:", stock_json == trim_json)
if stock_json != trim_json:
    for i, (a, b) in enumerate(zip(stock, trim)):
        if json.dumps(a, sort_keys=True) != json.dumps(b, sort_keys=True):
            print(f"  Q{i}: stock={a}\n       trim ={b}")
print(f"RSS: stock {stock_rss:.0f} MB -> trim {trim_rss:.0f} MB (saves {stock_rss - trim_rss:.0f} MB)")
sys.exit(0 if stock_json == trim_json else 1)
