#!/usr/bin/env python3
"""One-shot refactor splice for bench/runner.py (M5 shared-orchestrator).

Replaces the hand-mirrored arm implementations (_retrieve_sync, _complete_sync,
_label, _arm_traditional, _arm_hybrid, _retrieve_multi_sync) with a single
_run_arm() that drives the production ChatService and consumes its events.
Idempotent: skips if the marker is already present.
"""
import re
import sys

PATH = "/home/z/my-project/backend/app/bench/runner.py"

NEW_ARMS = '''    # ================================================================ pipeline arms
    async def _run_arm(self, mode: str, q: BenchQuestion, doc_ids: list[str]) -> dict:
        """Drive ONE arm through the production ChatService orchestrator.

        Bench mode (ChatRequest.bench=True): no conversation rows, no persistence,
        real exceptions propagate (the JevEngineUnavailable retry logic in
        _run_question depends on it), and the done event carries the exact
        context block used for generation.

        Captured per arm (same fields the pre-v3 hand-mirrored arms produced):
        - answer / model / usage / timings / decisions / sufficiency_p /
          verification_p  <- from the `done` event
        - files       <- last `sources` event (post-screening kept passages:
                         exactly what the generator was shown as context)
        - pre_files   <- last `retrieval` event (pre-rerank candidate pool;
                         the corrective retry re-emits it, last wins, matching
                         the old mirror's behaviour)
        - context     <- done event context_used (what the judge sees)
        """
        req = ChatRequest(message=q.question, mode=mode, doc_ids=doc_ids, bench=True)
        pre_files: list[str] = []
        files: list[str] = []
        final: dict = {}
        async for evt in self.chat.run(req):
            evt_type = evt.get("type")
            if evt_type == "retrieval":
                pre_files = [c["filename"] for c in evt.get("retrieved", [])]
            elif evt_type == "sources":
                files = [c["filename"] for c in evt.get("citations", [])]
            elif evt_type == "done":
                final = evt
        timings = dict(final.get("timings") or {})
        timings["latency_ms"] = final.get("latency_ms", 0.0)
        return {
            "answer": final.get("content", ""),
            "model": final.get("model", ""),
            "usage": final.get("usage") or {},
            "context": final.get("context_used", ""),
            "files": files,
            "pre_files": pre_files,
            "timings": timings,
            "decisions": final.get("decisions") or [],
            "sufficiency_p": final.get("context_sufficiency"),
            "verification_p": final.get("verification"),
        }

'''

CALL_SITE_OLD = '''        trad = await self._arm_traditional(q, doc_ids)
'''
CALL_SITE_NEW = '''        trad = await self._run_arm("traditional", q, doc_ids)
'''

CALL_SITE_OLD2 = '''                hyb = await self._arm_hybrid(q, doc_ids)
'''
CALL_SITE_NEW2 = '''                hyb = await self._run_arm("hybrid", q, doc_ids)
'''

CONFIG_OLD = '''                "pipeline": "hybrid-v2",
'''
CONFIG_NEW = '''                "pipeline": "hybrid-v2",
                "orchestrator": "chat-service-shared",
'''


def main() -> int:
    with open(PATH) as f:
        src = f.read()
    if "_run_arm" in src:
        print("already spliced — nothing to do")
        return 0

    start = src.index("    # ================================================================ pipeline arms")
    end = src.index("    # ================================================================ aggregation")
    src = src[:start] + NEW_ARMS + src[end:]

    for old, new in ((CALL_SITE_OLD, CALL_SITE_NEW), (CALL_SITE_OLD2, CALL_SITE_NEW2),
                     (CONFIG_OLD, CONFIG_NEW)):
        if old not in src:
            print(f"MARKER MISSING: {old!r}", file=sys.stderr)
            return 1
        src = src.replace(old, new, 1)

    with open(PATH, "w") as f:
        f.write(src)
    print("spliced OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
