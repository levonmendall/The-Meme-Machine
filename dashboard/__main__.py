"""Read-only dashboard with optional public viewing and authenticated snapshot receiver.

This service never starts market execution and never initializes portfolio state.
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
from .snapshots import MAX_BYTES, SnapshotReader, SnapshotStore


DEFAULT_MAX_CONCURRENCY = 16
DEFAULT_RATE_LIMIT_PER_MINUTE = 120


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
    app, host, port, *,
    max_concurrency=DEFAULT_MAX_CONCURRENCY,
    rate_limit_per_minute=DEFAULT_RATE_LIMIT_PER_MINUTE,
    clock=time.monotonic,
    owner=None, ingest_token=None, snapshot_store=None, public_reads=None,
):
    limiter = FixedWindowRateLimiter(rate_limit_per_minute, clock=clock)
    # Public viewing must be explicitly enabled; authenticated ingestion never changes.
    public_reads = (os.environ.get('MM_DASHBOARD_PUBLIC_READS') == '1'
                    if public_reads is None else public_reads)
    owner = owner or (os.environ.get('MM_DASHBOARD_OWNER_USER'),
                      os.environ.get('MM_DASHBOARD_OWNER_PASSWORD'))
    ingest_token = ingest_token or os.environ.get('MM_DASHBOARD_INGEST_TOKEN')

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
            self.connection.settimeout(10)
            path = urlsplit(self.path).path
            if path == "/healthz":
                if self.command not in ("GET", "HEAD"):
                    self._json(
                        405, {"error": "read_only"},
                        headers={"Allow": "GET, HEAD"},
                    )
                else:
                    self._json(200, {"status": "ok"})
                return
            client = self.client_address[0] if self.client_address else "unknown"
            if not limiter.allow(client):
                self._json(429, {"error": "rate_limited"}, headers={"Retry-After": "60"})
                return
            if path == '/api/dashboard/snapshot':
                if not ingest_token or snapshot_store is None:
                    self._json(503, {'error': 'ingestion_unavailable'})
                    return
                expected = ('Bearer '+ingest_token).encode()
                if not hmac.compare_digest(self.headers.get('Authorization', '').encode(), expected):
                    self._json(401, {'error': 'unauthorized'})
                    return
                if self.command != 'POST':
                    self._json(405, {'error': 'ingestion_post_only'}, headers={'Allow': 'POST'})
                    return
                try:
                    if (urlsplit(self.path).query or self.headers.get('Transfer-Encoding')
                            or self.headers.get('Content-Encoding', 'identity') != 'identity'
                            or self.headers.get('Content-Type', '').split(';')[0] != 'application/json'):
                        raise ValueError('snapshot_content_type')
                    size = int(self.headers.get('Content-Length', '0'))
                    if not 0 < size <= MAX_BYTES:
                        self._json(413, {'error': 'snapshot_capacity'})
                        return
                    body = self.rfile.read(size)
                    if len(body) != size:
                        raise ValueError('snapshot_incomplete')
                    value = json.loads(body)
                    snapshot_store.accept(value)
                except (ValueError, TypeError, KeyError, RuntimeError, OverflowError, RecursionError):
                    self._json(400, {'error': 'invalid_snapshot'})
                    return
                except OSError:
                    self._json(503, {'error': 'snapshot_unavailable'})
                    return
                self._json(202, {'status': 'accepted', 'captured_at': value['captured_at']})
                return
            if not public_reads:
                if not all(owner):
                    self._json(503, {'error': 'owner_access_not_configured'})
                    return
                try:
                    scheme, encoded = self.headers.get('Authorization', '').split(' ', 1)
                    supplied = base64.b64decode(encoded, validate=True) if scheme == 'Basic' else b''
                    authorized = hmac.compare_digest(supplied, (owner[0]+':'+owner[1]).encode())
                except (ValueError, UnicodeError):
                    authorized = False
                if not authorized:
                    self._json(401, {'error': 'owner_authentication_required'}, headers={
                        'WWW-Authenticate': 'Basic realm="Meme Machine owner", charset="UTF-8"'})
                    return
            if path == '/':
                if self.command not in ('GET', 'HEAD'):
                    self._json(405, {'error': 'read_only'}, headers={'Allow': 'GET, HEAD'})
                    return
                self.send_response(302)
                self.send_header('Location', '/dashboard')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            if path != "/dashboard" and not path.startswith(
                ("/dashboard/", "/api/dashboard/")
            ):
                self._json(404, {"error": "not_found"})
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
        Path(__file__).resolve().parents[1] / "operational/sources.json",
        mode=mode,
    )
    if mode == "fixture":
        from .fixtures import FIXTURE_NOW
        reader.clock = lambda: FIXTURE_NOW
    store = None
    if os.environ.get('MM_DASHBOARD_SNAPSHOT_PATH'):
        if args.fixture_dir or any((args.inception, args.accounting, args.telemetry)):
            parser.error('snapshot mode cannot read fixture or canonical paths')
        store = SnapshotStore(os.environ['MM_DASHBOARD_SNAPSHOT_PATH'],
            epoch=os.environ['MM_DASHBOARD_EPOCH'], candidate=os.environ['MM_DASHBOARD_CANDIDATE'])
        reader = SnapshotReader(store)

    try:
        server = make_server(
            Dashboard(reader),
            args.host,
            args.port,
            max_concurrency=args.max_concurrency,
            rate_limit_per_minute=args.rate_limit_per_minute,
            snapshot_store=store,
        )
    except ValueError as error:
        parser.error(str(error))

    print(
        f"Read-only {mode} dashboard at http://{args.host}:{server.server_port}; "
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
