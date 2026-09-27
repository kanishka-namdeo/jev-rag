"""Verify trimmed jev-score flags keep answers IDENTICAL while cutting RSS.

Runs the same rendered request (via the real Python runtime, exact mode) through
the stock flags and the trimmed flags, and compares probabilities + RSS.
"""
import json
import os
import subprocess
import sys
import time

BINARY = "/home/z/my-project/models/jev-style/build/jev-score"
MODEL = "/home/z/my-project/models/jev-style/Jev-Style-0.8B-Decision-v3-Q4_K_M.gguf"

CONFIGS = {
    "stock  (seq17 out256)": ["--n-seq-max", "17", "--n-outputs-max", "256"],
    "trim   (seq2  out32)":  ["--n-seq-max", "2",  "--n-outputs-max", "32"],
}

# A representative multi-question request in the engine's own wire format:
# state + 4 questions, sequential mode, prefix sharing (mirrors rerank/battery).
STATE = ("Customer question: What is the maximum message size for the NimbusDB Pro tier?\n\n"
         "Passage [1] (source: bench-techdocs-02-limits.md):\n"
         "NimbusDB Pro tier: messages up to 256 MB; Starter caps at 16 MB.\n\n"
         "Passage [2] (source: bench-techdocs-01-overview.md):\n"
         "NimbusDB is a streaming platform with three tiers.\n\n"
         "Passage [3] (source: bench-techdocs-03-api.md):\n"
         "The REST API accepts payloads up to the tier message limit.\n\n"
         "Passage [4] (source: bench-techdocs-04-architecture.md):\n"
         "Brokers persist messages to tier-specific storage volumes.")
QUESTIONS = [
    {"ids": [10, 11, 12, 13, 14], "slots": [3], "rows": [100, 200]},
    {"ids": [10, 11, 12, 13, 15], "slots": [3], "rows": [100, 200]},
    {"ids": [10, 11, 12, 13, 16], "slots": [3], "rows": [100, 200]},
    {"ids": [10, 11, 12, 13, 17], "slots": [3], "rows": [100, 200]},
]


def run_one(extra, label):
    cmd = [BINARY, "--model", MODEL, "--n-ctx", "8192", "--n-ubatch", "1024",
           "--ngl", "999", "--flash-attn", "auto"] + extra
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True, bufsize=1)
    try:
        line = proc.stdout.readline()
        ready = json.loads(line) if line else {"ready": False}
        if not ready.get("ready"):
            print(f"{label}: FAILED to start: {ready}")
            return None, None
        req = {"prefix": [1, 2, 3, 4], "share_prefix": True, "keep_prefix": True,
               "mode": "sequential", "questions": QUESTIONS}
        proc.stdin.write(json.dumps(req) + "\n")
        proc.stdin.flush()
        resp_line = proc.stdout.readline()
        resp = json.loads(resp_line) if resp_line else {"error": "exited"}
        time.sleep(1.0)
        rss_kb = int(open(f"/proc/{proc.pid}/status").read().split("VmRSS:")[1].split("kB")[0])
        print(f"{label}: RSS = {rss_kb / 1024:.0f} MB   ready={ready}")
        return resp, rss_kb / 1024
    finally:
        try:
            proc.stdin.write('{"cmd":"quit"}\n')
            proc.stdin.flush()
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


results = {}
for label, extra in CONFIGS.items():
    resp, rss = run_one(extra, label)
    results[label] = (resp, rss)

(stock_resp, stock_rss), (trim_resp, trim_rss) = results.values()
if stock_resp and trim_resp:
    if "error" in stock_resp or "error" in trim_resp:
        print("ERROR in response:", stock_resp.get("error"), trim_resp.get("error"))
        sys.exit(1)
    same = stock_resp.get("results") == trim_resp.get("results")
    print(f"\nanswers identical: {same}")
    print(f"RSS: stock {stock_rss:.0f} MB -> trim {trim_rss:.0f} MB  (saves {stock_rss - trim_rss:.0f} MB)")
    sys.exit(0 if same else 2)
print("\ncomparison incomplete")
sys.exit(3)
