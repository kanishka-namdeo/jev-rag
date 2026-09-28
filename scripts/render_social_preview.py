#!/usr/bin/env python3
"""Render docs social preview card (1280x640) with Playwright."""
from playwright.sync_api import sync_playwright

HTML = 'file:///home/z/my-project/scripts/social_preview.html'
OUT = '/home/z/my-project/docs/assets/img/social-preview.png'

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={'width': 1280, 'height': 640}, device_scale_factor=2)
    page.goto(HTML)
    page.wait_for_timeout(400)
    page.screenshot(path=OUT, clip={'x': 0, 'y': 0, 'width': 1280, 'height': 640})
    browser.close()
print('saved', OUT)
