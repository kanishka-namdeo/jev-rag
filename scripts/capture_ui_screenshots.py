#!/usr/bin/env python3
"""Capture the README / docs UI screenshots from the *live* app with Playwright.

Why this exists: `docs/assets/img/{chat-compare,trace-panel,bench-lab,bench-charts}.png`
are the four live-browser shots the README and `docs/usage.md` embed. They may only be
regenerated from a running stack — the local FastAPI backend plus the Next.js frontend on
:3000 — never from a mock or an image model (see `docs/AGENTS.md`, `assets/img/`).

Prerequisites (nothing is installed by this script):
  1. `bash scripts/dev.sh` from the repo root — backend :8000 + frontend :3000
  2. a Playwright-enabled interpreter with the Chromium build already downloaded, e.g.
     `/root/pwenv-t12/bin/python` on this box. `playwright` is deliberately NOT a
     `backend/.venv` dependency, because it is only needed for docs rendering.

Usage:
  /root/pwenv-t12/bin/python scripts/capture_ui_screenshots.py
  /root/pwenv-t12/bin/python scripts/capture_ui_screenshots.py --only trace-panel
  /root/pwenv-t12/bin/python scripts/capture_ui_screenshots.py --base-url http://localhost:3000

Each shot is a 1512x945 viewport at device_scale_factor=1 (the pixel size the README
already ships, so the README table layout and repo weight do not move) in light theme.
Asking the questions costs real cloud-LLM calls: two per question in Compare mode
(one per pipeline), so the default two questions are four calls.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from playwright.sync_api import expect, sync_playwright
except ModuleNotFoundError:  # pragma: no cover - operator guidance
    sys.exit(
        "playwright is not importable by this interpreter.\n"
        "Use a Playwright-enabled interpreter (e.g. /root/pwenv-t12/bin/python); it is\n"
        "not a backend/.venv dependency on purpose. See this script's docstring."
    )

REPO_ROOT = Path(__file__).resolve().parents[1]

# 1512x945 @1x — the size the four existing shots were captured at.
VIEWPORT = {"width": 1512, "height": 945}

# Two questions over the shipped bench corpora, chosen because they read well and show
# what the product is for: a multi-hop tech-docs lookup, then a finance question whose
# near-identical distractor (Avalanche Robotics) is the whole point of the comparison.
QUESTIONS = [
    "NimbusDB: what are the Pro tier's sustained throughput and concurrent connection "
    "limits, and which replication tier should ledger writes use?",
    "What revenue did Northwind Analytics report for Q3 FY2026, and how did its cloud "
    "analytics segment perform?",
]

SHOTS = ("chat-compare", "trace-panel", "bench-lab", "bench-charts")

ANSWER_TIMEOUT_MS = 300_000  # hybrid answers run the local decision model + a cloud call


def shot(page, out_dir: Path, name: str) -> None:
    path = out_dir / f"{name}.png"
    page.screenshot(path=str(path))
    try:
        shown = path.relative_to(REPO_ROOT)
    except ValueError:  # --out-dir outside the repo
        shown = path
    print(f"saved {shown} ({path.stat().st_size // 1024} KB)")


SCROLL_TO_TOP_JS = """(el, off) => {
  let node = el.parentElement;
  while (node && node !== document.body) {
    const oy = getComputedStyle(node).overflowY;
    if (oy === "auto" || oy === "scroll") {
      node.scrollTop += el.getBoundingClientRect().top
        - node.getBoundingClientRect().top - off;
      return true;
    }
    node = node.parentElement;
  }
  window.scrollBy(0, el.getBoundingClientRect().top - off);
  return false;
}"""


def scroll_to_in_container(page, locator, offset: int = 10, settle_ms: int = 700) -> None:
    """Place `locator` `offset` px below the top of its scroll container.

    Both scrolling views in this app scroll an inner div, not the window, so
    window-level scrolling would land somewhere arbitrary.
    """
    locator.scroll_into_view_if_needed()
    locator.evaluate(SCROLL_TO_TOP_JS, offset)
    page.wait_for_timeout(settle_ms)  # recharts animates in on mount/scroll


def wait_booted(page) -> None:
    page.get_by_text("Jev-RAG").first.wait_for(state="visible", timeout=60_000)
    # The header shows this while app.init() warms the stack and fetches documents.
    booting = page.get_by_text("waking local models")
    try:
        booting.first.wait_for(state="detached", timeout=120_000)
    except Exception:
        print("  ! still showing 'waking local models' — capturing anyway", file=sys.stderr)
    page.wait_for_timeout(1_200)


def ask(page, question: str) -> None:
    box = page.locator("textarea").first
    box.click()
    box.fill(question)
    box.press("Enter")
    # The composer locks while a stream is in flight; the lock is the only reliable
    # "the answer finished" signal the UI exposes.
    try:
        expect(box).to_be_disabled(timeout=25_000)
    except AssertionError:
        pass  # very short answer finished before we polled
    expect(box).to_be_enabled(timeout=ANSWER_TIMEOUT_MS)
    page.wait_for_timeout(1_500)  # let latency/token/cost badges settle


def capture(page, out_dir: Path, want: set[str]) -> None:
    chat_shots = want & {"chat-compare", "trace-panel"}
    if chat_shots:
        print("· chat: new conversation, Compare mode, two questions")
        page.get_by_role("button", name="New chat").click()
        page.get_by_role("tab", name="Compare").click()
        for question in QUESTIONS:
            print(f"  asking: {question[:64]}…")
            ask(page, question)

        # Frame the last exchange from its question bubble down: the answers are long
        # enough that two pairs do not fit, and a mid-sentence clip at the top edge
        # reads as a mistake.
        scroll_to_in_container(page, page.get_by_text(QUESTIONS[-1]).first,
                               offset=110, settle_ms=500)

        if "chat-compare" in want:
            # Compare mode auto-opens the trace panel (store.ts `send`), which would
            # squeeze the two answers into narrow columns — close it for this shot.
            close = page.get_by_role("button", name="Close trace panel")
            if close.count():
                close.click()
                page.wait_for_timeout(600)
            shot(page, out_dir, "chat-compare")

    if "trace-panel" in want:
        print("· trace panel: last hybrid answer")
        page.get_by_role("button", name="View trace").last.click()
        expect(page.get_by_text("Pipeline trace")).to_be_visible(timeout=15_000)
        page.wait_for_timeout(1_200)
        shot(page, out_dir, "trace-panel")
        page.get_by_role("button", name="Close trace panel").click()
        page.wait_for_timeout(400)

    if not want & {"bench-lab", "bench-charts"}:
        return

    print("· benchmark lab")
    page.get_by_role("button", name="Switch to Benchmarks").click()
    expect(page.get_by_text("RAG Benchmark Lab")).to_be_visible(timeout=20_000)
    # BenchView.init() loads the catalog + run list, then auto-selects the newest
    # completed run — that is what puts the metric cards and both panels on screen.
    expect(page.get_by_text("loading runs…")).to_be_hidden(timeout=60_000)
    expect(page.get_by_text("Correctness per scenario")).to_be_visible(timeout=90_000)
    page.wait_for_timeout(1_500)

    if "bench-lab" in want:
        shot(page, out_dir, "bench-lab")

    if "bench-charts" in want:
        scroll_to_in_container(
            page, page.locator('[data-slot="card"]', has_text="Correctness per scenario").first)
        shot(page, out_dir, "bench-charts")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base-url", default="http://localhost:3000",
                    help="running frontend (default: %(default)s)")
    ap.add_argument("--out-dir", default=str(REPO_ROOT / "docs" / "assets" / "img"),
                    help="where the PNGs land (default: docs/assets/img)")
    ap.add_argument("--only", default="",
                    help=f"comma-separated subset of {', '.join(SHOTS)} (default: all)")
    args = ap.parse_args()

    want = {s.strip() for s in args.only.split(",") if s.strip()} or set(SHOTS)
    unknown = want - set(SHOTS)
    if unknown:
        ap.error(f"unknown shot(s): {', '.join(sorted(unknown))}")
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--force-color-profile=srgb"])
        page = browser.new_page(viewport=VIEWPORT, device_scale_factor=1,
                                color_scheme="light", reduced_motion="reduce")
        page.goto(args.base_url, wait_until="domcontentloaded")
        wait_booted(page)
        capture(page, out_dir, want)
        browser.close()


if __name__ == "__main__":
    main()