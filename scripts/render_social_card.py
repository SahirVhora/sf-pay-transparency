#!/usr/bin/env python3
"""Render the social preview SVG to PNG for Open Graph link previews."""

from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
SVG = ROOT / "assets" / "social-card.svg"
PNG = ROOT / "assets" / "social-card.png"


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1200, "height": 630}, device_scale_factor=1)
        page.goto(SVG.resolve().as_uri())
        page.locator("svg").screenshot(path=str(PNG), type="png")
        browser.close()


if __name__ == "__main__":
    main()
