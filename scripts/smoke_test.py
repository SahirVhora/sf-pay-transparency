#!/usr/bin/env python3
"""Demo-mode smoke tests for the local backend."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
PORT = 8765
BASE_URL = f"http://127.0.0.1:{PORT}"


def request_json(path: str, method: str = "GET", payload: dict | None = None) -> tuple[int, dict]:
    body = None
    headers = {}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(f"{BASE_URL}{path}", data=body, headers=headers, method=method)
    try:
        with urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def wait_for_server() -> None:
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            status, payload = request_json("/health")
            if status == 200 and payload.get("ok") is True:
                return
        except Exception:
            time.sleep(0.2)
    raise RuntimeError("Backend did not become ready")


def main() -> int:
    env = os.environ.copy()
    env.pop("SFPT_LIVE_MODE", None)
    env["PORT"] = str(PORT)
    proc = subprocess.Popen(
        [sys.executable, "backend_server.py"],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        wait_for_server()

        status, credentials = request_json("/api/credentials")
        assert status == 200, status
        assert credentials["ok"] is True
        assert credentials["liveMode"] is False
        assert credentials["hasPassword"] is False

        status, live_check = request_json("/api/live-checks", method="POST", payload={})
        assert status == 403, status
        assert live_check["liveMode"] is False

        status, clear = request_json("/api/clear-local-data", method="POST", payload={})
        assert status == 200, status
        assert clear["ok"] is True
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    print("Smoke tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
