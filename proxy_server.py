#!/usr/bin/env python3
"""Local-only CORS proxy for testing SuccessFactors OData from the static UI."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


HOST = "127.0.0.1"
PORT = 8081
ALLOWED_HOST_SUFFIXES = (".successfactors.eu", ".sapsf.eu", ".successfactors.com", ".sapsf.com")


class ProxyHandler(BaseHTTPRequestHandler):
    def _send_cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, Accept")

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/" and not parsed.query:
            self._write_text(
                200,
                "SF OData proxy is running.\n\n"
                "Open the app at: http://localhost:8080\n"
                "In the app settings, set CORS Proxy to: http://localhost:8081/\n\n"
                "This proxy endpoint is called by the app as:\n"
                "http://localhost:8081/?url=https://api55.sapsf.eu/odata/v2/...\n",
            )
            return

        target = parse_qs(parsed.query).get("url", [""])[0]
        if not target:
            self._write_text(400, "Missing ?url=https://... target")
            return

        target_url = urlparse(target)
        if target_url.scheme != "https" or not target_url.hostname:
            self._write_text(400, "Only HTTPS target URLs are allowed")
            return

        hostname = target_url.hostname.lower()
        if not hostname.endswith(ALLOWED_HOST_SUFFIXES):
            self._write_text(403, "Target host is not an SAP SuccessFactors API host")
            return

        headers = {"Accept": "application/json"}
        auth = self.headers.get("Authorization")
        if auth:
            headers["Authorization"] = auth

        try:
            req = Request(target, headers=headers, method="GET")
            with urlopen(req, timeout=30) as resp:
                body = resp.read()
                self.send_response(resp.status)
                self._send_cors()
                self.send_header("Content-Type", resp.headers.get("Content-Type", "application/json"))
                self.end_headers()
                self.wfile.write(body)
        except HTTPError as exc:
            body = exc.read()
            self.send_response(exc.code)
            self._send_cors()
            self.send_header("Content-Type", exc.headers.get("Content-Type", "text/plain"))
            self.end_headers()
            self.wfile.write(body)
        except URLError as exc:
            self._write_text(502, f"Proxy request failed: {exc.reason}")
        except Exception as exc:
            self._write_text(500, f"Proxy error: {exc}")

    def _write_text(self, status, text):
        self.send_response(status)
        self._send_cors()
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(text.encode("utf-8"))

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args))


if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), ProxyHandler)
    print(f"SF OData proxy running at http://{HOST}:{PORT}/")
    print("Use CORS Proxy in the UI as: http://localhost:8081/")
    server.serve_forever()
