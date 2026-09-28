"""Measure jev-score RSS under different llama.cpp flags to find the memory hog."""
import json
import subprocess
import sys
import time

BINARY = "/home/z/my-project/models/jev-style/build/jev-score"
MODEL = "/home/z/my-project/models/jev-style/Jev-Style-0.8B-Decision-v3-Q4_K_M.gguf"


def measure(extra_args, label):
    cmd = [BINARY, "--model", MODEL] + extra_args
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True, bufsize=1)
    try:
        line = proc.stdout.readline()
        ready = json.loads(line) if line else {"ready": False}
        if not ready.get("ready"):
            print(f"{label}: FAILED to start: {ready}")
            return
        time.sleep(1.5)  # let it settle
        rss_kb = int(open(f"/proc/{proc.pid}/status").read().split("VmRSS:")[1].split("kB")[0])
        print(f"{label}: RSS = {rss_kb / 1024:.0f} MB  (args: {' '.join(extra_args)})")
    finally:
        try:
            proc.stdin.write('{"cmd":"quit"}\n')
            proc.stdin.flush()
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


measure(["--n-ctx", "8192", "--n-ubatch", "1024", "--ngl", "999", "--flash-attn", "auto",
         "--n-seq-max", "17", "--n-outputs-max", "256"], "A: ctx8192 ubatch1024 (current)")
measure(["--n-ctx", "8192", "--n-ubatch", "256", "--ngl", "999", "--flash-attn", "auto",
         "--n-seq-max", "17", "--n-outputs-max", "64"], "B: ctx8192 ubatch256 out64")
measure(["--n-ctx", "4096", "--n-ubatch", "256", "--ngl", "999", "--flash-attn", "auto",
         "--n-seq-max", "17", "--n-outputs-max", "64"], "C: ctx4096 ubatch256 out64")
measure(["--n-ctx", "8192", "--n-ubatch", "128", "--ngl", "999", "--flash-attn", "on",
         "--n-seq-max", "4", "--n-outputs-max", "32"], "D: ctx8192 ubatch128 fa-on seq4 out32")
