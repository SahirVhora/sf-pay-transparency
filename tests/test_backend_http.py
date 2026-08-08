import unittest
from unittest.mock import Mock, patch

import backend_server
import requests


class BackendHttpTests(unittest.TestCase):
    @patch("backend_server.requests.get")
    def test_sf_get_uses_basic_auth_and_never_follows_redirects(self, get):
        response = Mock(
            status_code=200,
            content=b"{}",
            headers={"Content-Type": "application/json"},
        )
        get.return_value = response

        result = backend_server._sf_get(
            "https://api55.sapsf.eu/odata/v2/$metadata",
            "api-user",
            "secret",
        )

        self.assertEqual(result, (200, b"{}", "application/json"))
        get.assert_called_once_with(
            "https://api55.sapsf.eu/odata/v2/$metadata",
            headers={"Accept": "application/json"},
            auth=("api-user", "secret"),
            timeout=60,
            allow_redirects=False,
        )

    @patch("backend_server.time.sleep")
    @patch("backend_server.requests.get")
    def test_sf_get_retries_transient_responses(self, get, sleep):
        get.side_effect = [
            Mock(status_code=503, content=b"busy", headers={}),
            Mock(status_code=200, content=b"ok", headers={}),
        ]

        result = backend_server._sf_get(
            "https://api55.sapsf.eu/odata/v2/EmpJob",
            "api-user",
            "secret",
        )

        self.assertEqual(result, (200, b"ok", ""))
        self.assertEqual(get.call_count, 2)
        sleep.assert_called_once_with(1)

    @patch("backend_server.time.sleep")
    @patch("backend_server.requests.get")
    def test_sf_get_surfaces_network_failure_after_three_attempts(self, get, sleep):
        get.side_effect = requests.exceptions.ConnectionError("offline")

        with self.assertRaisesRegex(RuntimeError, "Could not reach SuccessFactors"):
            backend_server._sf_get(
                "https://api55.sapsf.eu/odata/v2/EmpJob",
                "api-user",
                "secret",
            )

        self.assertEqual(get.call_count, 3)
        self.assertEqual(sleep.call_count, 2)


if __name__ == "__main__":
    unittest.main()
