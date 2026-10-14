"""Actual Pons HTTP dispatch boundaries; synthetic replies and disposable ledgers."""
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from urllib.error import HTTPError

from meme_machine.lanes.pons import BoundaryError
from meme_machine.lanes.pons.provider_admission import Admission
from meme_machine.lanes.pons.provider_topology import PacedRpc, ProviderPacer


PUBLIC = 'https://rpc.mainnet.chain.robinhood.com'
CANONICAL = 'https://robinhood-mainnet.g.alchemy.com/v2/OFFLINE_ONLY'
CALLS = [('eth_getLogs', [dict(fromBlock='0x1', toBlock='0xa')])] * 4


class PublicDispatchSpacingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        self.now = 100.0
        self.lock = threading.Lock()
        self.starts = []
        self.sleep_hook = None
        self.reject = False

    def clock(self):
        with self.lock:
            return self.now

    def sleep(self, seconds):
        with self.lock:
            self.now += seconds
        if self.sleep_hook is not None:
            self.sleep_hook()

    def gate(self, endpoint=PUBLIC):
        with patch('meme_machine.operational.position_continuation.provider_interval', return_value=.1):
            return Admission(Path(self.tmp.name) / 'provider.sqlite', endpoint,
                             lane='pons', clock=self.clock, sleeper=self.sleep)

    def client(self, gate=None):
        gate = gate or self.gate()
        with patch('meme_machine.lanes.pons.provider_admission.configured', return_value=gate):
            rpc = PacedRpc(PUBLIC, role='pons_discovery_public_observation',
                           requests_per_second=2, retries=2, limit=80, per_scope=80,
                           pacer=ProviderPacer(2, clock=self.clock, sleeper=self.sleep))
        return rpc

    def http(self, request, **kwargs):
        self.starts.append(self.clock())
        self.sleep(.125)
        if self.reject:
            self.reject = False
            raise HTTPError(PUBLIC, 429, 'synthetic_fixture', {}, io.BytesIO(b'{}'))
        payload = json.loads(request.data)
        def reply(item):
            return dict(jsonrpc='2.0', id=item['id'], result=[])
        value = [reply(item) for item in payload] if isinstance(payload, list) else reply(payload)
        return io.BytesIO(json.dumps(value).encode())

    def transport_rows(self, gate):
        with sqlite3.connect(gate.path) as connection:
            return [json.loads(row[0]) for row in connection.execute('SELECT body FROM transports ORDER BY seq')]

    def assert_spacing(self, seconds=.5):
        self.assertTrue(all(b - a >= seconds - 1e-9 for a, b in zip(self.starts, self.starts[1:])), self.starts)

    def test_original_actual_path_cooldown_reproduction_is_corrected(self):
        # Preserve the original reproduction's synthetic latency, gate, public
        # interval, five physical attempts and terminal first 429.
        from engineering.diagnostics.public_dispatch_cooldown_20261014 import scenario
        with patch.dict(os.environ, {}, clear=True):
            control = scenario(Path(self.tmp.name), rejection=False)
            cooldown = scenario(Path(self.tmp.name), rejection=True)
        self.assertEqual(cooldown['statuses'], [429, 200, 200, 200, 200])
        self.assertEqual(control['synthetic_physical_attempts'], 5)
        self.assertEqual(cooldown['synthetic_physical_attempts'], 5)
        self.assertGreaterEqual(control['minimum_gap_seconds'], .5 - 1e-9)
        self.assertGreaterEqual(cooldown['minimum_gap_seconds'], .5 - 1e-9)
        self.assertEqual(cooldown['retries'], 0)

    def test_single_and_batch_share_actual_dispatch_clock_and_terminal_429(self):
        rpc = self.client()
        with patch('meme_machine.lanes.pons.provider.urlopen', side_effect=self.http):
            rpc._http('eth_getLogs', [{}])
            self.reject = True
            with self.assertRaisesRegex(BoundaryError, 'provider_http_429'):
                rpc.batch(CALLS, scope='scout')
            rpc._http('eth_getLogs', [{}])
            rpc._http_batch(CALLS)
        self.assertEqual(len(self.starts), 4)
        self.assert_spacing()
        rows = self.transport_rows(rpc.shared_admission)
        self.assertEqual([row['physical_requests'] for row in rows], [1] * 4)
        self.assertEqual([row['http_status'] for row in rows], [200, 429, 200, 200])
        self.assertEqual(rows[1]['retry_attempt'], 0)
        self.assertGreaterEqual(self.starts[2] - self.starts[1], 8)

    def test_new_client_cannot_reset_shared_adaptive_slowdown(self):
        first = self.client()
        self.assertTrue(first.pacer.slow_to(1))
        second = self.client(self.gate())
        self.assertEqual(second.pacer.requests_per_second, 1)
        with patch('meme_machine.lanes.pons.provider.urlopen', side_effect=self.http):
            first._http('eth_getLogs', [{}])
            second._http_batch(CALLS)
        self.assert_spacing(1)
        self.assertTrue(second.pacer.recover_to(1.1))
        self.assertAlmostEqual(first.shared_admission.public_interval(.5), 1 / 1.1)

    def test_adaptive_change_while_queued_rechecks_existing_deadline(self):
        first = self.client()
        queued = self.client(self.gate())
        with patch('meme_machine.lanes.pons.provider.urlopen', side_effect=self.http):
            first._http('eth_getLogs', [{}])
            def slower():
                self.sleep_hook = None
                first.pacer.slow_to(1)
            self.sleep_hook = slower
            queued._http('eth_getLogs', [{}])
        self.assert_spacing(1)

    def test_local_serialization_delay_revalidates_through_same_gate(self):
        rpc = self.client()
        peer = self.client(self.gate())
        from meme_machine.lanes.pons import provider
        request_constructor = provider.Request
        delay = [True]
        def delayed(*args, **kwargs):
            if delay[0]:
                delay[0] = False
                self.sleep(1)
                peer._http('eth_getLogs', [{}])
            return request_constructor(*args, **kwargs)
        with patch('meme_machine.lanes.pons.provider.urlopen', side_effect=self.http):
            rpc._http('eth_getLogs', [{}])
            with patch('meme_machine.lanes.pons.provider.Request', side_effect=delayed):
                rpc._http_batch(CALLS)
        self.assertEqual(len(self.starts), 3)
        self.assert_spacing()
        self.assertGreaterEqual(self.transport_rows(rpc.shared_admission)[-1]['dispatch_revalidations'], 1)

    def test_start_accounting_delay_revalidates_without_an_extra_attempt(self):
        rpc = self.client()
        peer = self.client(self.gate())
        from meme_machine.lanes.pons import provider
        started = provider.http_started
        delay = [True]
        def delayed(size):
            started(size)
            if delay[0]:
                delay[0] = False
                self.sleep(1)
                peer._http('eth_getLogs', [{}])
        with patch('meme_machine.lanes.pons.provider.urlopen', side_effect=self.http):
            rpc._http('eth_getLogs', [{}])
            with patch('meme_machine.lanes.pons.provider.http_started', side_effect=delayed):
                rpc._http_batch(CALLS)
        self.assertEqual(len(self.starts), 3)
        self.assert_spacing()
        rows = self.transport_rows(rpc.shared_admission)
        self.assertEqual(sum(row['physical_requests'] for row in rows), 3)
        self.assertGreaterEqual(rows[-1]['dispatch_revalidations'], 1)
        self.assertEqual(rows[-1]['transport_dispatch_monotonic'], self.starts[-1])

    def test_expired_local_grant_requeues_without_renewing_its_deadline(self):
        rpc = self.client()
        from meme_machine.lanes.pons import provider
        request_constructor = provider.Request
        def delayed(*args, **kwargs):
            self.sleep(.75)
            return request_constructor(*args, **kwargs)
        with patch('meme_machine.lanes.pons.provider.urlopen', side_effect=self.http), \
                patch('meme_machine.lanes.pons.provider.Request', side_effect=delayed):
            rpc._http_batch(CALLS)
        self.assertEqual(self.starts, [100.75])
        rows = self.transport_rows(rpc.shared_admission)
        self.assertEqual(rows[0]['dispatch_revalidations'], 1)
        self.assertEqual(rows[0]['physical_requests'], 1)
        with sqlite3.connect(rpc.shared_admission.path) as connection:
            grants = [json.loads(row[0]) for row in connection.execute('SELECT body FROM admissions ORDER BY seq')]
        self.assertEqual([row['created'] for row in grants], [100, 100.75])
        self.assertEqual([row['deadline'] for row in grants], [130, 130])

    def test_cancelled_wait_cleans_queue_without_starting_transport(self):
        rpc = self.client()
        with sqlite3.connect(rpc.shared_admission.path) as connection:
            connection.execute('UPDATE limits SET next_at=110')
        self.sleep_hook = lambda: (_ for _ in ()).throw(KeyboardInterrupt())
        with patch('meme_machine.lanes.pons.provider.urlopen', side_effect=self.http):
            with self.assertRaises(KeyboardInterrupt):
                rpc._http_batch(CALLS)
        self.assertEqual(self.starts, [])
        with sqlite3.connect(rpc.shared_admission.path) as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM queue').fetchone()[0], 0)
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM queue_meta').fetchone()[0], 0)
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM transport_starts').fetchone()[0], 0)

    def test_absolute_deadline_not_renewed_after_adaptive_change(self):
        rpc = self.client()
        with patch('meme_machine.lanes.pons.provider.urlopen', side_effect=self.http):
            rpc._http('eth_getLogs', [{}])
            rpc.evidence_deadline = 100.3
            with patch('meme_machine.lanes.pons.provider.time.monotonic', side_effect=self.clock):
                with self.assertRaisesRegex(BoundaryError, 'provider_shared_admission_deadline'):
                    rpc._http_batch(CALLS)
        self.assertEqual(len(self.starts), 1)
        with sqlite3.connect(rpc.shared_admission.path) as connection:
            row = json.loads(connection.execute('SELECT body FROM admissions ORDER BY seq DESC LIMIT 1').fetchone()[0])
        self.assertEqual(row['deadline'], 100.3)
        self.assertFalse(row['granted'])

    def test_public_cooldown_does_not_delay_canonical_protection(self):
        public = self.client()
        canonical = self.gate(CANONICAL)
        with sqlite3.connect(public.shared_admission.path) as connection:
            connection.execute('UPDATE limits SET cooldown=200 WHERE endpoint=?', (public.shared_admission.endpoint,))
        starts = []
        canonical.invoke(lambda: starts.append(self.clock()), ['eth_call'], 'paper_exit', deadline=103)
        self.assertEqual(starts, [100])
        with sqlite3.connect(canonical.path) as connection:
            row = json.loads(connection.execute('SELECT body FROM admissions ORDER BY seq DESC LIMIT 1').fetchone()[0])
        self.assertEqual(row['priority'], 0)

    def test_concurrent_consumers_share_endpoint_dispatch_spacing(self):
        first = self.client()
        second = self.client(self.gate())
        barrier = threading.Barrier(2)
        # Yield the host while the synthetic clock advances, so SQLite peers
        # can obtain their existing grants without an artificial busy spin.
        self.sleep_hook = lambda: threading.Event().wait(.001)
        def run(rpc, batch):
            barrier.wait()
            return rpc._http_batch(CALLS) if batch else rpc._http('eth_getLogs', [{}])
        with patch('meme_machine.lanes.pons.provider.urlopen', side_effect=self.http), ThreadPoolExecutor(2) as pool:
            calls = [pool.submit(run, first, False), pool.submit(run, second, True)]
            for call in calls:
                call.result(timeout=5)
        self.assertEqual(len(self.starts), 2)
        self.assert_spacing()

    def test_post_transport_ledger_failure_retains_original_http_evidence(self):
        for failure in ('connect', 'write_then_close', 'close'):
            with self.subTest(failure=failure):
                rpc = self.client()
                gate = rpc.shared_admission
                connect = gate.connect
                accounting_error = sqlite3.OperationalError('offline_accounting_failure')
                close_error = RuntimeError('offline_secondary_close_failure')
                rejected = [False]
                class Connection:
                    def __init__(self, db):self.db = db
                    def __getattr__(self, name):return getattr(self.db, name)
                    def execute(self, sql, *args):
                        if failure == 'write_then_close' and sql.startswith('INSERT INTO transports'):
                            raise accounting_error
                        return self.db.execute(sql, *args)
                    def close(self):
                        self.db.close()
                        raise close_error if failure == 'write_then_close' else accounting_error
                def connection():
                    if rejected[0]:
                        if failure == 'connect':raise accounting_error
                        return Connection(connect())
                    return connect()
                def rejected_http(request, **kwargs):
                    self.starts.append(self.clock())
                    rejected[0] = True
                    body = b'{"error":{"code":429,"message":"rate limit exceeded"}}'
                    raise HTTPError(PUBLIC, 429, 'unrecorded_provider_text',
                                    {'X-Request-ID':'fixture-429'}, io.BytesIO(body))
                before = len(self.starts)
                with patch.object(gate, 'connect', side_effect=connection), \
                        patch('meme_machine.lanes.pons.provider.urlopen', side_effect=rejected_http):
                    with self.assertRaises(sqlite3.OperationalError) as caught:
                        rpc._http_batch(CALLS)
                self.assertIs(caught.exception, accounting_error)
                self.assertEqual(len(self.starts), before + 1)
                self.assertEqual(accounting_error.provider_original_boundary, 'provider_http_429')
                self.assertEqual(accounting_error.provider_http_context['http_status'], 429)
                self.assertEqual(accounting_error.provider_http_context['response_headers']['x-request-id'], 'fixture-429')
                notes = '\n'.join(accounting_error.__notes__)
                self.assertIn('original_transport_boundary=provider_http_429', notes)
                self.assertNotIn('unrecorded_provider_text', notes)
                if failure == 'write_then_close':
                    self.assertIn('provider_transport_ledger_close_failed:RuntimeError', notes)
