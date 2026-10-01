#!/usr/bin/env python3
"""Render docs social preview card (1280x640 at 1x) with Playwright.

GitHub caps the repo social preview at 1 MB and recommends 1280x640, so the
render stays at device_scale_factor=1 — the old 2x render was 2560x1280 / 1.07 MB.
"""
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[1]
HTML = (REPO_ROOT / "scripts" / "social_preview.html").as_uri()
OUT = str(REPO_ROOT / "docs" / "assets" / "img" / "social-preview.png")

Path(OUT).parent.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={'width': 1280, 'height': 640}, device_scale_factor=1)
    page.goto(HTML)
    page.wait_for_timeout(400)
    page.screenshot(path=OUT, clip={'x': 0, 'y': 0, 'width': 1280, 'height': 640})
    browser.close()
print('saved', OUT)
