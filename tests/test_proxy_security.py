import io
import unittest
from email.message import Message
from unittest.mock import Mock, patch

import proxy_server


class _HandlerHarness(proxy_server.ProxyHandler):
    def __init__(self, *, origin=None, authorization=None, path="/"):
        self.headers = Message()
        if origin is not None:
            self.headers["Origin"] = origin
        if authorization is not None:
            self.headers["Authorization"] = authorization
        self.path = path
        self.wfile = io.BytesIO()
        self.client_address = ("127.0.0.1", 12345)
        self.responses = []
        self.sent_headers = []

    def send_response(self, status, message=None):
        self.responses.append(status)

    def send_header(self, name, value):
        self.sent_headers.append((name, value))

    def end_headers(self):
        pass


class ProxySecurityTests(unittest.TestCase):
    def test_host_containment_accepts_sf_subdomains_only(self):
        allowed = [
            "https://api55.sapsf.eu/odata/v2/EmpJob",
            "https://api55.successfactors.com/odata/v2/$metadata",
        ]
        rejected = [
            "http://api55.sapsf.eu/odata/v2/EmpJob",
            "https://sapsf.eu/odata/v2/EmpJob",
            "https://api55.sapsf.eu.evil.example/odata/v2/EmpJob",
            "https://evil.example/?next=api55.sapsf.eu",
            "https://user:pass@api55.sapsf.eu/odata/v2/EmpJob",
        ]
        for url in allowed:
            with self.subTest(url=url):
                self.assertTrue(proxy_server.is_allowed_target(url))
        for url in rejected:
            with self.subTest(url=url):
                self.assertFalse(proxy_server.is_allowed_target(url))

    def test_redirect_handler_does_not_follow(self):
        redirect = proxy_server._NoRedirect()
        self.assertIsNone(
            redirect.redirect_request(
                Mock(), None, 302, "Found", Message(), "https://evil.example/"
            )
        )

    def test_origin_checks_reject_untrusted_browser_and_allow_local_ui(self):
        untrusted = _HandlerHarness(origin="https://evil.example")
        trusted = _HandlerHarness(origin="http://localhost:8080")
        non_browser = _HandlerHarness()
        self.assertFalse(untrusted._origin_allowed())
        self.assertTrue(trusted._origin_allowed())
        self.assertTrue(non_browser._origin_allowed())

        untrusted.do_OPTIONS()
        self.assertEqual(untrusted.responses[-1], 403)

    def test_only_authorization_credential_is_forwarded(self):
        handler = _HandlerHarness(
            origin="http://localhost:8080",
            authorization="Bearer tenant-secret",
            path="/?url=https%3A%2F%2Fapi55.sapsf.eu%2Fodata%2Fv2%2FEmpJob",
        )
        handler.headers["Cookie"] = "session=browser-secret"
        handler.headers["Proxy-Authorization"] = "Basic proxy-secret"

        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b"{}"
        response.status = 200
        response.headers = Message()
        response.headers["Content-Type"] = "application/json"

        with patch.object(proxy_server._OPENER, "open", return_value=response) as opened:
            handler.do_GET()

        request = opened.call_args.args[0]
        forwarded = {name.lower(): value for name, value in request.header_items()}
        self.assertEqual(forwarded["authorization"], "Bearer tenant-secret")
        self.assertEqual(forwarded["accept"], "application/json")
        self.assertNotIn("cookie", forwarded)
        self.assertNotIn("proxy-authorization", forwarded)

    def test_redirect_response_is_blocked(self):
        handler = _HandlerHarness(
            origin="http://localhost:8080",
            authorization="Bearer tenant-secret",
            path="/?url=https%3A%2F%2Fapi55.sapsf.eu%2Fodata%2Fv2%2FEmpJob",
        )
        error = proxy_server.HTTPError(
            "https://api55.sapsf.eu/odata/v2/EmpJob",
            302,
            "Found",
            Message(),
            io.BytesIO(),
        )
        with patch.object(proxy_server._OPENER, "open", side_effect=error):
            handler.do_GET()
        self.assertEqual(handler.responses[-1], 502)
        self.assertIn(b"redirect blocked", handler.wfile.getvalue())


if __name__ == "__main__":
    unittest.main()
