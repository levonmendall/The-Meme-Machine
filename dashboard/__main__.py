"""Read-only dashboard observer with bounded public deployment controls.

This service never starts market execution and never initializes portfolio state.
Loopback development may run without authentication. Any non-loopback bind requires
explicit owner credentials from environment variables.
"""
import argparse
import base64
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
import time
from urllib.parse import urlsplit

from .api import Dashboard
from .model import Reader


AUTH_USER_ENV = "MM_DASHBOARD_USERNAME"
AUTH_PASSWORD_ENV = "MM_DASHBOARD_PASSWORD"
DEFAULT_MAX_CONCURRENCY = 16
DEFAULT_RATE_LIMIT_PER_MINUTE = 120


def _is_loopback(host):
    return str(host).strip().lower() in {"127.0.0.1", "::1", "localhost"}


def _validate_bind(host, username, password):
    if bool(username) != bool(password):
        raise ValueError("dashboard_auth_pair_required")
    if username and ":" in username:
        raise ValueError("dashboard_username_must_not_contain_colon")
    if not _is_loopback(host):
        if not username:
            raise ValueError("public_dashboard_auth_required")
        if len(password) < 20:
            raise ValueError("public_dashboard_password_too_short")


def _authorized(header, username, password):
    if not username and not password:
        return True
    if not isinstance(header, str) or not header.startswith("Basic "):
        return False
    try:
        raw = base64.b64decode(header[6:].strip(), validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return False
    candidate_user, separator, candidate_password = raw.partition(":")
    if not separator:
        return False
    return (
        hmac.compare_digest(candidate_user, username)
        and hmac.compare_digest(candidate_password, password)
    )


class FixedWindowRateLimiter:
    def __init__(self, limit, *, clock=time.monotonic):
        if type(limit) is not int or not 1 <= limit <= 600:
            raise ValueError("dashboard_rate_limit_bounds")
        self.limit = limit
        self.clock = clock
        self.lock = threading.Lock()
        self.state = {}

    def allow(self, key):
        now = self.clock()
        with self.lock:
            started, count = self.state.get(key, (now, 0))
            if now - started >= 60:
                started, count = now, 0
            if count >= self.limit:
                return False
            self.state[key] = (started, count + 1)
            if len(self.state) > 2048:
                self.state = {
                    k: value for k, value in self.state.items()
                    if now - value[0] < 60
                }
                if len(self.state) > 2048:
                    self.state.clear()
                    self.state[key] = (started, count + 1)
            return True


class BoundedThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 32

    def __init__(self, address, handler, *, max_concurrency):
        if type(max_concurrency) is not int or not 1 <= max_concurrency <= 64:
            raise ValueError("dashboard_concurrency_bounds")
        self._slots = threading.BoundedSemaphore(max_concurrency)
        super().__init__(address, handler)

    def process_request(self, request, client_address):
        self._slots.acquire()
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


def make_server(
    app, host, port, *, username=None, password=None,
    max_concurrency=DEFAULT_MAX_CONCURRENCY,
    rate_limit_per_minute=DEFAULT_RATE_LIMIT_PER_MINUTE,
    clock=time.monotonic,
):
    _validate_bind(host, username, password)
    limiter = FixedWindowRateLimiter(rate_limit_per_minute, clock=clock)

    class Handler(BaseHTTPRequestHandler):
        server_version = "MemeMachineDashboard/1"
        sys_version = ""

        def _json(self, status, payload, *, headers=None):
            body = json.dumps(payload, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Type", "application/json")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
            self.close_connection = True

        def _handle(self):
            path = urlsplit(self.path).path
            if path == "/healthz":
                if self.command not in ("GET", "HEAD"):
                    self._json(405, {"error": "read_only"}, headers={"Allow": "GET, HEAD"})
                else:
                    self._json(200, {"status": "ok"})
                return
            if path != "/dashboard" and not path.startswith(("/dashboard/", "/api/dashboard/")):
                self._json(404, {"error": "not_found"})
                return
            client = self.client_address[0] if self.client_address else "unknown"
            if not limiter.allow(client):
                self._json(429, {"error": "rate_limited"}, headers={"Retry-After": "60"})
                return
            if not _authorized(self.headers.get("Authorization"), username, password):
                self._json(
                    401,
                    {"error": "unauthorized"},
                    headers={
                        "WWW-Authenticate":
                            'Basic realm="Meme Machine Dashboard", charset="UTF-8"'
                    },
                )
                return
            if not app.serve(self):
                self._json(404, {"error": "not_found"})

        do_GET = _handle
        do_HEAD = _handle
        do_POST = _handle
        do_PUT = _handle
        do_PATCH = _handle
        do_DELETE = _handle
        do_OPTIONS = _handle

        def log_message(self, *_):
            pass

    return BoundedThreadingHTTPServer(
        (host, port), Handler, max_concurrency=max_concurrency
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("PORT", "8090"))
    )
    parser.add_argument("--inception")
    parser.add_argument("--accounting")
    parser.add_argument("--telemetry")
    parser.add_argument(
        "--fixture-dir", help="Explicit isolated development fixtures only"
    )
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=int(os.environ.get(
            "MM_DASHBOARD_MAX_CONCURRENCY", str(DEFAULT_MAX_CONCURRENCY)
        )),
    )
    parser.add_argument(
        "--rate-limit-per-minute",
        type=int,
        default=int(os.environ.get(
            "MM_DASHBOARD_RATE_LIMIT_PER_MINUTE",
            str(DEFAULT_RATE_LIMIT_PER_MINUTE),
        )),
    )
    args = parser.parse_args()

    if args.fixture_dir and any((args.inception, args.accounting, args.telemetry)):
        parser.error("fixture mode cannot read canonical paths")

    mode = "canonical"
    if args.fixture_dir:
        root = Path(args.fixture_dir)
        args.inception = root / "inception.json"
        args.accounting = root / "accounting.json"
        args.telemetry = root / "telemetry.json"
        mode = "fixture"

    reader = Reader(
        args.inception,
        args.accounting,
        args.telemetry,
        Path(__file__).resolve().parents[1] / "certification/sources.json",
        mode=mode,
    )
    if mode == "fixture":
        from .fixtures import FIXTURE_NOW
        reader.clock = lambda: FIXTURE_NOW

    username = os.environ.get(AUTH_USER_ENV)
    password = os.environ.get(AUTH_PASSWORD_ENV)
    try:
        server = make_server(
            Dashboard(reader),
            args.host,
            args.port,
            username=username,
            password=password,
            max_concurrency=args.max_concurrency,
            rate_limit_per_minute=args.rate_limit_per_minute,
        )
    except ValueError as error:
        parser.error(str(error))

    print(
        f"Read-only {mode} observer bound on {args.host}:{server.server_port}; "
        "portfolio inception is not performed by this service",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
