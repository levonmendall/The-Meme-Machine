import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from dashboard.__main__ import FixedWindowRateLimiter, make_server
from dashboard.api import Dashboard
from dashboard.model import Reader


class DashboardServerSecurityTests(unittest.TestCase):
    def test_rate_limiter_is_bounded_and_resets_after_window(self):
        now = [10.0]
        limiter = FixedWindowRateLimiter(2, clock=lambda: now[0])
        self.assertTrue(limiter.allow("client"))
        self.assertTrue(limiter.allow("client"))
        self.assertFalse(limiter.allow("client"))
        now[0] += 60.0
        self.assertTrue(limiter.allow("client"))

    def server(self):
        server = make_server(
            Dashboard(Reader()),
            "127.0.0.1",
            0,
            max_concurrency=4,
            rate_limit_per_minute=30,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.addCleanup(thread.join, 2)
        return server

    def test_dashboard_and_api_are_public_read_only(self):
        server = self.server()
        base = f"http://127.0.0.1:{server.server_port}"

        with urlopen(base + "/healthz", timeout=2) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.read(), b'{"status":"ok"}')

        with urlopen(base + "/dashboard", timeout=2) as response:
            self.assertEqual(response.status, 200)
            self.assertIn(b"THE <strong>MEME MACHINE</strong>", response.read())

        with urlopen(base + "/api/dashboard/portfolio", timeout=2) as response:
            self.assertEqual(response.status, 200)
            self.assertIn(b'"state":"NOT_INITIALIZED"', response.read())

    def test_root_redirects_to_dashboard(self):
        server = self.server()
        request = Request(
            f"http://127.0.0.1:{server.server_port}/",
            method="HEAD",
        )
        opener = __import__("urllib.request", fromlist=["build_opener"]).build_opener(
            __import__("urllib.request", fromlist=["HTTPRedirectHandler"]).HTTPRedirectHandler()
        )
        with opener.open(request, timeout=2) as response:
            self.assertTrue(response.geturl().endswith("/dashboard"))

    def test_unsupported_method_remains_read_only(self):
        server = self.server()
        request = Request(
            f"http://127.0.0.1:{server.server_port}/api/dashboard/portfolio",
            method="POST",
            data=b"ignored",
        )
        with self.assertRaises(HTTPError) as error:
            urlopen(request, timeout=2)
        self.assertEqual(error.exception.code, 405)


if __name__ == "__main__":
    unittest.main()
