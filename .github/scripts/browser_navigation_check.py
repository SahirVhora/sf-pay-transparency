"""Check local demo navigation in Chromium without tenant credentials."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
from collections import deque
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urldefrag, urlsplit
from urllib.request import urlopen

from playwright.sync_api import sync_playwright


def main() -> None:
    base = os.environ.get("BROWSER_BASE_URL", "http://127.0.0.1:8765/")
    command = os.environ.get(
        "BROWSER_START_COMMAND", "python -m http.server 8765 --bind 127.0.0.1"
    )
    server = subprocess.Popen(shlex.split(command))
    try:
        for _ in range(120):
            if server.poll() is not None:
                raise RuntimeError("The demo server exited before it became ready")
            try:
                with urlopen(base, timeout=2):
                    break
            except (URLError, TimeoutError):
                time.sleep(0.5)
        else:
            raise RuntimeError("The demo server did not become ready")

        errors: list[str] = []
        seen: set[str] = set()
        pending = deque([base])
        origin = urlsplit(base).netloc
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: errors.append(message.text) if message.type == "error" else None,
            )
            page.on(
                "response",
                lambda response: errors.append(f"HTTP {response.status}: {response.url}")
                if response.status >= 400 and urlsplit(response.url).netloc == origin
                else None,
            )
            while pending:
                target = pending.popleft()
                if target in seen:
                    continue
                if len(seen) >= 100:
                    raise AssertionError("Navigation exceeded 100 pages; coverage is incomplete")
                seen.add(target)
                response = page.goto(target, wait_until="networkidle")
                assert response is not None and response.ok, f"Failed navigation: {target}"
                assert page.locator("body").inner_text().strip(), f"Empty page: {target}"
                broken = page.locator("img").evaluate_all(
                    "images => images.filter(i => i.complete && !i.naturalWidth).map(i => i.src)"
                )
                assert not broken, f"Broken images: {broken}"
                links = page.locator("a[href]").evaluate_all(
                    "links => links.map(link => link.href)"
                )
                for raw in links:
                    link = urldefrag(raw)[0]
                    parsed = urlsplit(link)
                    if parsed.scheme not in {"http", "https"} or parsed.netloc != origin:
                        continue
                    if any(word in parsed.path.lower() for word in ("logout", "delete", "clear")):
                        continue
                    if link in seen:
                        continue
                    result = page.request.get(link)
                    assert result.ok, f"Broken link: {target} -> {link} ({result.status})"
                    if "text/html" in result.headers.get("content-type", ""):
                        pending.append(link)
            # File/static deployments must stay in demo mode without calling /api.
            static_page = browser.new_page()
            static_requests = []
            static_page.on("request", lambda request: static_requests.append(request.url)
                           if "/api/" in request.url else None)
            static_page.on("pageerror", lambda error: errors.append(str(error)))
            static_page.on("console", lambda message: errors.append(message.text)
                           if message.type in {"error", "warning"} else None)
            static_page.goto(Path("index.html").resolve().as_uri(), wait_until="networkidle")
            assert "Demo Mode" in static_page.locator("body").inner_text()
            assert not static_requests, f"Static demo called a backend: {static_requests}"
            browser.close()
        assert not errors, "\n".join(errors)
        print(json.dumps({"pages_checked": len(seen), "routes": sorted(seen), "errors": errors}))
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=10)


if __name__ == "__main__":
    main()
