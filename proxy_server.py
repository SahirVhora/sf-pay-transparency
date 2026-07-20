#!/usr/bin/env python3
"""Local-only CORS proxy for testing SuccessFactors OData from the static UI."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

HOST = "127.0.0.1"
PORT = 8081
APP_PORT = 8080  # port the static UI is served from (see README)
ALLOWED_HOST_SUFFIXES = (
    ".successfactors.eu",
    ".sapsf.eu",
    ".successfactors.com",
    ".sapsf.com",
)

# Origins allowed to call this proxy from a browser. Anything else gets 403,
# so a random webpage the user has open cannot relay requests through here.
ALLOWED_ORIGINS = {
    f"http://localhost:{APP_PORT}",
    f"http://127.0.0.1:{APP_PORT}",
    f"http://[::1]:{APP_PORT}",
}


class _NoRedirect(HTTPRedirectHandler):
    """Surface 3xx responses instead of following them. Following a redirect
    would re-send the Authorization header to whatever host the redirect
    points at, escaping the SF host allowlist."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = build_opener(_NoRedirect)


def is_allowed_target(target):
    """Allow HTTPS requests only to SuccessFactors API subdomains."""
    try:
        parsed = urlparse(target)
        hostname = (parsed.hostname or "").lower()
        return (
            parsed.scheme == "https"
            and parsed.port in (None, 443)
            and parsed.username is None
            and parsed.password is None
            and parsed.fragment == ""
            and hostname.endswith(ALLOWED_HOST_SUFFIXES)
        )
    except (AttributeError, TypeError, ValueError):
        return False


class ProxyHandler(BaseHTTPRequestHandler):
    def _origin_allowed(self):
        origin = self.headers.get("Origin")
        return origin is None or origin in ALLOWED_ORIGINS

    def _send_cors(self):
        origin = self.headers.get("Origin")
        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, Accept")

    def do_OPTIONS(self):
        if not self._origin_allowed():
            self._write_text(403, "Origin not allowed")
            return
        self.send_response(204)
        self._send_cors()
        self.end_headers()

    def do_GET(self):
        if not self._origin_allowed():
            self._write_text(403, "Origin not allowed")
            return
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

        if not is_allowed_target(target):
            self._write_text(403, "Target host is not an SAP SuccessFactors API host")
            return

        headers = {"Accept": "application/json"}
        auth = self.headers.get("Authorization")
        if auth:
            headers["Authorization"] = auth

        try:
            req = Request(target, headers=headers, method="GET")
            with _OPENER.open(req, timeout=30) as resp:
                body = resp.read()
                self.send_response(resp.status)
                self._send_cors()
                self.send_header(
                    "Content-Type", resp.headers.get("Content-Type", "application/json")
                )
                self.end_headers()
                self.wfile.write(body)
        except HTTPError as exc:
            if 300 <= exc.code < 400:
                self._write_text(502, "Provider redirect blocked by local proxy")
                return
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
        print(f"{self.address_string()} - {fmt % args}")


if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), ProxyHandler)
    print(f"SF OData proxy running at http://{HOST}:{PORT}/")
    print("Use CORS Proxy in the UI as: http://localhost:8081/")
    server.serve_forever()
