import base64
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from dashboard.__main__ import (
    FixedWindowRateLimiter,
    _authorized,
    _validate_bind,
    make_server,
)
from dashboard.api import Dashboard
from dashboard.model import Reader


class DashboardServerSecurityTests(unittest.TestCase):
    USER = "owner"
    PASSWORD = "correct-horse-battery-staple-dashboard"

    def auth(self, password=None):
        raw = (self.USER + ":" + (password or self.PASSWORD)).encode()
        return "Basic " + base64.b64encode(raw).decode()

    def test_public_bind_requires_strong_complete_credentials(self):
        _validate_bind("127.0.0.1", None, None)
        with self.assertRaisesRegex(ValueError, "public_dashboard_auth_required"):
            _validate_bind("0.0.0.0", None, None)
        with self.assertRaisesRegex(ValueError, "dashboard_auth_pair_required"):
            _validate_bind("0.0.0.0", self.USER, None)
        with self.assertRaisesRegex(ValueError, "public_dashboard_password_too_short"):
            _validate_bind("0.0.0.0", self.USER, "short")
        _validate_bind("0.0.0.0", self.USER, self.PASSWORD)

    def test_basic_auth_is_constant_contract_and_malformed_input_fails(self):
        self.assertTrue(_authorized(self.auth(), self.USER, self.PASSWORD))
        self.assertFalse(_authorized(self.auth("wrong-password-which-is-long"), self.USER, self.PASSWORD))
        self.assertFalse(_authorized("Bearer token", self.USER, self.PASSWORD))
        self.assertFalse(_authorized("Basic not-base64!", self.USER, self.PASSWORD))
        self.assertFalse(_authorized(None, self.USER, self.PASSWORD))

    def test_rate_limiter_is_bounded_and_resets_after_window(self):
        now = [10.0]
        limiter = FixedWindowRateLimiter(2, clock=lambda: now[0])
        self.assertTrue(limiter.allow("client"))
        self.assertTrue(limiter.allow("client"))
        self.assertFalse(limiter.allow("client"))
        now[0] += 60.0
        self.assertTrue(limiter.allow("client"))

    def test_protected_dashboard_and_api_health_is_non_sensitive(self):
        server = make_server(
            Dashboard(Reader()),
            "127.0.0.1",
            0,
            username=self.USER,
            password=self.PASSWORD,
            max_concurrency=4,
            rate_limit_per_minute=30,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.addCleanup(thread.join, 2)

        base = f"http://127.0.0.1:{server.server_port}"

        with urlopen(base + "/healthz", timeout=2) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.read(), b'{"status":"ok"}')

        for path in ("/dashboard", "/api/dashboard/portfolio"):
            with self.assertRaises(HTTPError) as error:
                urlopen(base + path, timeout=2)
            self.assertEqual(error.exception.code, 401)

        request = Request(
            base + "/api/dashboard/portfolio",
            headers={"Authorization": self.auth()},
        )
        with urlopen(request, timeout=2) as response:
            self.assertEqual(response.status, 200)
            self.assertIn(b'"state":"NOT_INITIALIZED"', response.read())

    def test_unsupported_method_stays_protected_and_read_only(self):
        server = make_server(
            Dashboard(Reader()),
            "127.0.0.1",
            0,
            username=self.USER,
            password=self.PASSWORD,
            max_concurrency=2,
            rate_limit_per_minute=30,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.addCleanup(thread.join, 2)

        request = Request(
            f"http://127.0.0.1:{server.server_port}/api/dashboard/portfolio",
            method="POST",
            data=b"ignored",
            headers={"Authorization": self.auth()},
        )
        with self.assertRaises(HTTPError) as error:
            urlopen(request, timeout=2)
        self.assertEqual(error.exception.code, 405)


if __name__ == "__main__":
    unittest.main()
