import threading
import unittest
import base64
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import time
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from dashboard.__main__ import FixedWindowRateLimiter, make_server
from dashboard.api import Dashboard
from dashboard.model import Reader
from dashboard.snapshots import PHASES, SCHEMA, SnapshotReader, SnapshotStore, utc
from dashboard.publisher import acceptance, push

OWNER = ('owner', 'synthetic-owner-password-for-tests')
AUTH = 'Basic '+base64.b64encode(':'.join(OWNER).encode()).decode()


def snapshot(now):
    return dict(schema=SCHEMA, captured_at=utc(now),
        source=dict(epoch_id='synthetic-dashboard', candidate_commit='a'*40,
                    deployed_commit='b'*40, publisher_commit='c'*40),
        observer=dict(at=utc(now), epoch_id='synthetic-dashboard', lanes={}),
        monitor=dict(at=utc(now), conditions=[]),
        service=dict(ActiveState='inactive', SubState='dead', MainPID='0'),
        acceptance={p:dict(status='NOT_STARTED', elapsed_seconds=0, verified_result=False) for p in PHASES},
        portfolio=dict(bundle=None, observation=dict(state='UNAVAILABLE')))


class DashboardServerSecurityTests(unittest.TestCase):
    def test_rate_limiter_is_bounded_and_resets_after_window(self):
        now = [10.0]
        limiter = FixedWindowRateLimiter(2, clock=lambda: now[0])
        self.assertTrue(limiter.allow("client"))
        self.assertTrue(limiter.allow("client"))
        self.assertFalse(limiter.allow("client"))
        now[0] += 60.0
        self.assertTrue(limiter.allow("client"))

    def server(self, store=None, public_reads=None):
        server = make_server(
            Dashboard(Reader()),
            "127.0.0.1",
            0,
            max_concurrency=4,
            rate_limit_per_minute=30,
            owner=OWNER, ingest_token='synthetic-ingestion-token', snapshot_store=store,
            public_reads=public_reads,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.addCleanup(thread.join, 2)
        return server

    def test_dashboard_and_api_require_owner_authentication(self):
        server = self.server()
        base = f"http://127.0.0.1:{server.server_port}"

        with urlopen(base + "/healthz", timeout=2) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.read(), b'{"status":"ok"}')

        for path in ('/', '/dashboard', '/dashboard/app.js', '/dashboard/style.css', '/api/dashboard/portfolio'):
            with self.assertRaises(HTTPError) as error:
                urlopen(base+path, timeout=2)
            self.assertEqual(error.exception.code, 401)
        with urlopen(Request(base + "/dashboard", headers={'Authorization': AUTH}), timeout=2) as response:
            self.assertEqual(response.status, 200)
            self.assertIn(b"THE <strong>MEME MACHINE</strong>", response.read())

        with urlopen(Request(base + "/api/dashboard/portfolio", headers={'Authorization': AUTH}), timeout=2) as response:
            self.assertEqual(response.status, 200)
            self.assertIn(b'"state":"NOT_INITIALIZED"', response.read())

    def test_root_redirects_to_dashboard(self):
        server = self.server()
        request = Request(
            f"http://127.0.0.1:{server.server_port}/",
            method="HEAD",
            headers={'Authorization': AUTH},
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
            headers={'Authorization': AUTH},
        )
        with self.assertRaises(HTTPError) as error:
            urlopen(request, timeout=2)
        self.assertEqual(error.exception.code, 405)

    def test_only_separate_ingestion_credential_can_post_snapshots(self):
        with tempfile.TemporaryDirectory() as folder:
            now = time.time()
            store = SnapshotStore(Path(folder)/'latest.json', epoch='synthetic-dashboard', candidate='a'*40)
            server = self.server(store)
            base = f'http://127.0.0.1:{server.server_port}'
            raw = json.dumps(snapshot(now)).encode()
            for auth in ('', AUTH, 'Bearer incorrect'):
                request = Request(base+'/api/dashboard/snapshot', data=raw, headers={
                    'Authorization': auth, 'Content-Type': 'application/json'})
                with self.assertRaises(HTTPError) as error:
                    urlopen(request, timeout=2)
                self.assertEqual(error.exception.code, 401)
            with urlopen(Request(base+'/api/dashboard/snapshot', data=raw, headers={
                    'Authorization': 'Bearer synthetic-ingestion-token', 'Content-Type': 'application/json'}), timeout=2) as response:
                self.assertEqual(response.status, 202)
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(base+'/api/dashboard/system', headers={
                    'Authorization': 'Bearer synthetic-ingestion-token'}), timeout=2)
            self.assertEqual(error.exception.code, 401)
            invalid = snapshot(now); invalid['schema'] = 'wrong'
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(base+'/api/dashboard/snapshot', data=json.dumps(invalid).encode(), headers={
                    'Authorization': 'Bearer synthetic-ingestion-token', 'Content-Type': 'application/json'}), timeout=2)
            self.assertEqual(error.exception.code, 400)
            self.assertEqual(store.get()['schema'], SCHEMA)

    def test_public_read_only_mode_requires_no_visitor_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SnapshotStore(Path(folder)/'latest.json', epoch='synthetic-dashboard', candidate='a'*40)
            server = self.server(store, public_reads=True)
            base = f'http://127.0.0.1:{server.server_port}'
            for path in ('/dashboard', '/dashboard/app.js', '/dashboard/style.css',
                         '/api/dashboard/portfolio', '/api/dashboard/system'):
                with urlopen(base+path, timeout=2) as response:
                    self.assertEqual(response.status, 200)
                    self.assertNotIn('WWW-Authenticate', response.headers)

            with self.assertRaises(HTTPError) as error:
                urlopen(Request(base+'/api/dashboard/portfolio', data=b'{}', method='POST'), timeout=2)
            self.assertEqual(error.exception.code, 405)

            raw = json.dumps(snapshot(time.time())).encode()
            for auth in ('', AUTH, 'Bearer incorrect'):
                with self.assertRaises(HTTPError) as error:
                    urlopen(Request(base+'/api/dashboard/snapshot', data=raw, method='POST',
                        headers={'Authorization': auth, 'Content-Type': 'application/json'}), timeout=2)
                self.assertEqual(error.exception.code, 401)
            with urlopen(Request(base+'/api/dashboard/snapshot', data=raw, method='POST',
                headers={'Authorization': 'Bearer synthetic-ingestion-token',
                         'Content-Type': 'application/json'}), timeout=2) as response:
                self.assertEqual(response.status, 202)

    def test_schema_epoch_candidate_pass_and_time_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            now = 1791490000
            store = SnapshotStore(Path(folder)/'latest.json', epoch='synthetic-dashboard', candidate='a'*40, clock=lambda: now)
            valid = snapshot(now)
            for mutate in (
                lambda s:s['source'].update(epoch_id='other'),
                lambda s:s['source'].update(candidate_commit='d'*40),
                lambda s:s.update(captured_at=utc(now+100)),
                lambda s:s['acceptance']['CAPACITY'].update(status='PASS', verified_result=True),
                lambda s:s['observer'].update(timestamp=float('nan')),
            ):
                bad = deepcopy(valid); mutate(bad)
                with self.assertRaises((ValueError, RuntimeError)):
                    store.accept(bad)
            store.accept(valid)
            old = snapshot(now-1)
            with self.assertRaises(ValueError):store.accept(old)
            restored = SnapshotStore(store.path, epoch='synthetic-dashboard', candidate='a'*40, clock=lambda:now)
            self.assertEqual(restored.get(), valid)

    def test_stopped_unavailable_portfolio_and_stale_snapshot_are_distinct(self):
        with tempfile.TemporaryDirectory() as folder:
            now = [1791490000]
            store = SnapshotStore(Path(folder)/'latest.json', epoch='synthetic-dashboard', candidate='a'*40, clock=lambda:now[0])
            reader = SnapshotReader(store, clock=lambda:now[0])
            self.assertEqual(reader.view()['system']['operations']['snapshot_state'], 'UNAVAILABLE')
            store.accept(snapshot(now[0]))
            view = reader.view()
            self.assertEqual(view['system']['paper_state'], 'STOPPED')
            self.assertEqual(view['system']['operations']['snapshot_state'], 'CURRENT')
            self.assertIsNone(view['portfolio']['metrics']['equity']['value'])
            self.assertEqual(view['system']['lanes']['meteora']['operational']['value'], 'PAUSED')
            now[0] += 61
            self.assertEqual(reader.view()['system']['operations']['snapshot_state'], 'STALE')

    def test_historical_acceptance_is_not_current_candidate_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder,'latest-CAPACITY.json').write_text(json.dumps(dict(
                status='FAIL', identity=dict(commit='b'*40), epoch_id='synthetic-dashboard', elapsed_seconds=335)))
            with patch('dashboard.publisher.service', return_value={'ActiveState': 'inactive'}):
                result = acceptance(folder, 'a'*40, 'synthetic-dashboard', time.time())
            self.assertTrue(all(row['status']=='NOT_STARTED' for row in result.values()))
            self.assertEqual(result['CAPACITY']['previous_attempt']['status'], 'FAIL')

    def test_push_rejects_plain_http_before_network_io(self):
        with patch('dashboard.publisher.build_opener') as network:
            with self.assertRaises(ValueError):push({}, 'http://example.com/api/dashboard/snapshot', 'synthetic-token')
            network.assert_not_called()


if __name__ == "__main__":
    unittest.main()
