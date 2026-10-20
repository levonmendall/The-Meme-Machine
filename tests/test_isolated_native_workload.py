"""Disposable native corpus and public transport boundaries; never real RPC."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from meme_machine.operational import isolated_native_workload as workload


class Scratch(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'native'
        self.root.mkdir(mode=0o700)

    def corpus(self):
        value = workload.Corpus(self.root)
        self.addCleanup(value.close)
        return value


class CorpusIsolation(Scratch):
    def test_durable_rpc_and_events_survive_close_without_financial_tables(self):
        corpus = self.corpus()
        corpus.request(workload.SOLANA, 'getSlot', [{'commitment': 'finalized'}], 123, .25)
        corpus.event('pump', dict(slot=123, block=dict(transactions=[])), 1000)
        corpus.event('pons', dict(first=23, last=24, acquired_head=24), 1001)
        self.assertEqual(corpus.db.execute('PRAGMA synchronous').fetchone(), (2,))
        self.assertEqual(corpus.path.stat().st_mode & 0o777, 0o600)
        corpus.close()
        with sqlite3.connect('file:' + str(corpus.path) + '?mode=ro', uri=True) as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone(), ('ok',))
            self.assertEqual(db.execute('SELECT count(*) FROM rpc').fetchone(), (1,))
            events = db.execute('SELECT lane,body,sha256 FROM events ORDER BY id').fetchall()
            self.assertEqual([row[0] for row in events], ['pump', 'pons'])
            for lane, body, checksum in events:
                self.assertEqual(hashlib.sha256(body.encode()).hexdigest(), checksum)
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertEqual(tables, {'rpc', 'events', 'rpc_events', 'completions'})
        replay = workload.ReplayRPC(corpus.path)
        self.assertEqual(replay.call(workload.SOLANA, 'getSlot', [{'commitment': 'finalized'}]), 123)

    def test_private_real_directory_and_exclusive_file_are_required(self):
        self.corpus()
        with self.assertRaises(FileExistsError):
            workload.Corpus(self.root)
        alias = self.root.parent / 'alias'
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(workload.ObservationUnavailable, 'native_scratch_path'):
            workload.Corpus(alias)
        public = self.root.parent / 'public'
        public.mkdir(mode=0o700); public.chmod(0o755)
        with self.assertRaisesRegex(workload.ObservationUnavailable, 'native_scratch_permissions'):
            workload.Corpus(public)
        self.assertFalse((public / 'corpus.sqlite3').exists())

    def test_concurrent_lanes_commit_without_cross_thread_connection_loss(self):
        corpus = self.corpus()
        def publish(index):
            lane = 'pump' if index % 2 == 0 else 'pons'
            corpus.event(lane, dict(index=index), index + .5)
        with ThreadPoolExecutor(max_workers=4) as workers:
            list(workers.map(publish, range(40)))
        rows = corpus.db.execute('SELECT lane,count(*) FROM events GROUP BY lane ORDER BY lane').fetchall()
        self.assertEqual(rows, [('pons', 20), ('pump', 20)])
        self.assertEqual(corpus.db.execute('PRAGMA integrity_check').fetchone(), ('ok',))

    def test_byte_limit_and_table_injection_do_not_partially_append(self):
        corpus = self.corpus()
        corpus.event('pump', dict(slot=1), 1)
        before = corpus.bytes
        with patch.object(workload, 'MAX_CORPUS', before):
            with self.assertRaisesRegex(workload.ObservationUnavailable, 'native_corpus_byte_limit'):
                corpus.event('pons', dict(block=2), 2)
        self.assertEqual(corpus.bytes, before)
        self.assertEqual(corpus.db.execute('SELECT count(*) FROM events').fetchone(), (1,))
        with self.assertRaisesRegex(workload.ObservationUnavailable, 'native_corpus_table'):
            corpus.append('events); DROP TABLE rpc;--', 'x')
        self.assertEqual(corpus.db.execute('SELECT count(*) FROM rpc').fetchone(), (0,))

    def test_attempt_and_completion_are_distinct_and_repeated_completion_is_refused(self):
        corpus = self.corpus()
        identity = corpus.event('pons', dict(first=3, last=3, acquired_head=3), 1)
        self.assertEqual(corpus.counts()['pons'], dict(attempted_events=1, completed_events=0))
        with corpus.recording(identity):
            corpus.request(workload.ROBINHOOD, 'eth_getLogs', [dict(fromBlock='0x3')], [], .1)
        corpus.complete(identity)
        self.assertEqual(corpus.counts()['pons'], dict(attempted_events=1, completed_events=1))
        self.assertEqual(corpus.db.execute('SELECT event_id,rpc_count FROM completions').fetchone(),
                         (identity, 1))
        with self.assertRaises(sqlite3.IntegrityError):
            corpus.complete(identity)
        with self.assertRaisesRegex(workload.ObservationUnavailable, 'native_corpus_event_missing'):
            corpus.complete(999)


class Clock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, delay):
        self.sleeps.append(delay)
        self.now += delay


class PublicTransport(Scratch):
    def setUp(self):
        super().setUp()
        self.store = self.corpus()
        self.clock = Clock()
        self.stop = threading.Event()
        self.calls = []

    def transport(self, endpoint, payload, timeout):
        packet = json.loads(payload)
        self.calls.append((self.clock(), endpoint, packet, timeout))
        self.clock.now += .25
        return workload.canonical(dict(jsonrpc='2.0', id=packet['id'], result=123)).encode()

    def client(self, **kwargs):
        options = dict(transport=self.transport, clock=self.clock, sleeper=self.clock.sleep)
        options.update(kwargs)
        return workload.PublicRPC(self.store, self.stop, 20, **options)

    def test_lanes_share_one_pacing_budget_and_every_result_is_durable(self):
        rpc = self.client()
        self.assertEqual(rpc.call(workload.SOLANA, 'getSlot', []), 123)
        self.assertEqual(rpc.call(workload.ROBINHOOD, 'eth_blockNumber', []), 123)
        self.assertEqual([row[0] for row in self.calls], [0.0, 1.0])
        self.assertEqual(self.clock.sleeps, [.75])
        self.assertEqual([row[3] for row in self.calls], [6, 6])
        self.assertEqual(rpc.requests, 2)
        self.assertEqual(self.store.db.execute('SELECT endpoint,method FROM rpc ORDER BY id').fetchall(),
            [(workload.SOLANA, 'getSlot'), (workload.ROBINHOOD, 'eth_blockNumber')])

    def test_unknown_endpoint_mutating_methods_and_params_reject_before_transport(self):
        rpc = self.client()
        for endpoint, method, params in (
                ('http://127.0.0.1:8545', 'eth_blockNumber', []),
                (workload.SOLANA, 'sendTransaction', []),
                (workload.ROBINHOOD, 'eth_sendRawTransaction', []),
                (workload.SOLANA, 'getSlot', {}),
                (workload.SOLANA, 'getBlocks', [100,140,{'commitment':'finalized'}]),
                (workload.SOLANA, 'getBlocks', [100,101,{'commitment':'confirmed'}])):
            with self.subTest(endpoint=endpoint, method=method, params=params):
                with self.assertRaises(workload.ObservationUnavailable):
                    rpc.call(endpoint, method, params)
        self.assertEqual(self.calls, [])
        self.assertEqual(rpc.requests, 0)

    def test_jsonrpc_rejection_retains_only_fixed_method_and_int32_code(self):
        canary = 'PRIVATE_PROVIDER_BODY https://private.invalid/API_KEY'
        for code in (-32005, True, '-32005', 2**31, -(2**31)-1):
            with self.subTest(code=code):
                def reject(endpoint, payload, timeout):
                    packet = json.loads(payload)
                    return workload.canonical(dict(jsonrpc='2.0', id=packet['id'],
                        error=dict(code=code, message=canary, data=dict(secret=canary)))).encode()
                rpc = self.client(transport=reject)
                with self.assertRaisesRegex(workload.ObservationUnavailable, 'native_rpc_rejected') as caught:
                    rpc.call(workload.SOLANA, 'getBlocks', [100, 101, {'commitment':'finalized'}])
                self.assertEqual(rpc.rejection, dict(method='getBlocks',
                    code=code if type(code) is int and -(2**31) <= code < 2**31 else None))
                self.assertNotIn(canary, workload.canonical(rpc.rejection))
                self.assertNotIn(canary, str(caught.exception))
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM rpc').fetchone()[0], 0)

    def test_concurrent_lane_transports_never_overlap(self):
        entered = threading.Event()
        release = threading.Event()
        second_entered = threading.Event()
        calls = []
        def held(endpoint, payload, timeout):
            packet = json.loads(payload)
            calls.append(endpoint)
            if len(calls) == 1:
                entered.set()
                if not release.wait(2):
                    raise AssertionError('test transport was not released')
            else:
                second_entered.set()
            return workload.canonical(dict(jsonrpc='2.0', id=packet['id'], result=1)).encode()
        rpc = self.client(transport=held)
        with ThreadPoolExecutor(max_workers=2) as workers:
            first = workers.submit(rpc.call, workload.SOLANA, 'getSlot', [])
            self.assertTrue(entered.wait(2))
            second = workers.submit(rpc.call, workload.ROBINHOOD, 'eth_blockNumber', [])
            try:
                self.assertFalse(second_entered.wait(.05))
            finally:
                release.set()
            self.assertEqual((first.result(timeout=2), second.result(timeout=2)), (1, 1))
        self.assertEqual(calls, [workload.SOLANA, workload.ROBINHOOD])

    def test_request_ceiling_and_stop_reject_without_extra_dispatch(self):
        rpc = self.client()
        with patch.object(workload, 'MAX_REQUESTS', 1):
            rpc.call(workload.SOLANA, 'getSlot', [])
            with self.assertRaisesRegex(workload.ObservationUnavailable, 'native_rpc_request_limit'):
                rpc.call(workload.ROBINHOOD, 'eth_blockNumber', [])
        self.stop.set()
        with self.assertRaisesRegex(workload.ObservationUnavailable, 'native_work_window_closed'):
            rpc.call(workload.SOLANA, 'getSlot', [])
        self.assertEqual(len(self.calls), 1)

    def test_cancel_during_pacing_never_dispatches_waiting_request(self):
        def cancel(delay):
            self.clock.sleep(delay)
            self.stop.set()
        rpc = self.client(sleeper=cancel)
        rpc.call(workload.SOLANA, 'getSlot', [])
        with self.assertRaisesRegex(workload.ObservationUnavailable, 'native_work_window_closed'):
            rpc.call(workload.ROBINHOOD, 'eth_blockNumber', [])
        self.assertEqual(rpc.requests, 1)
        self.assertEqual(len(self.calls), 1)

    def test_deadline_expiring_during_pacing_does_not_send_nonpositive_timeout(self):
        def oversleep(delay):
            self.clock.now = 21
        rpc = self.client(sleeper=oversleep)
        rpc.call(workload.SOLANA, 'getSlot', [])
        with self.assertRaisesRegex(workload.ObservationUnavailable, 'native_work_window_closed'):
            rpc.call(workload.ROBINHOOD, 'eth_blockNumber', [])
        self.assertEqual(rpc.requests, 1)
        self.assertEqual(len(self.calls), 1)

    def test_429_closes_global_acquisition_before_sibling_or_retry(self):
        attempts = []
        def rejected(endpoint, payload, timeout):
            attempts.append(endpoint)
            raise HTTPError(endpoint, 429, 'PRIVATE_PROVIDER_BODY', {}, None)
        rpc = self.client(transport=rejected)
        with self.assertRaisesRegex(workload.ObservationUnavailable, '^native_provider_429$'):
            rpc.call(workload.SOLANA, 'getSlot', [])
        self.assertTrue(self.stop.is_set())
        with self.assertRaises(workload.ObservationUnavailable):
            rpc.call(workload.ROBINHOOD, 'eth_blockNumber', [])
        self.assertEqual(attempts, [workload.SOLANA])
        self.assertEqual((rpc.requests, rpc.http_429), (1, 1))
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM rpc').fetchone(), (0,))

    def test_malformed_identity_nonfinite_error_and_oversized_responses_do_not_record(self):
        responses = (b'{', b'[]', b'{"jsonrpc":"2.0","id":true,"result":12}',
            b'{"jsonrpc":"2.0","id":1,"error":{"message":"PRIVATE_PROVIDER_BODY"}}',
            b'{"jsonrpc":"2.0","id":1,"result":NaN}',
            b'x' * 129, b'{"jsonrpc":"1.0","id":1,"result":12}',
            b'{"jsonrpc":"2.0","id":2,"result":12}')
        for raw in responses:
            with self.subTest(raw=raw[:64]), patch.object(workload, 'MAX_BODY', 128):
                rpc = self.client(transport=lambda *_: raw)
                with self.assertRaises(workload.ObservationUnavailable) as caught:
                    rpc.call(workload.SOLANA, 'getSlot', [])
                self.assertNotIn('PRIVATE_PROVIDER_BODY', str(caught.exception))
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM rpc').fetchone(), (0,))


class ReplayIntegrity(Scratch):
    def setUp(self):
        super().setUp()
        self.store = self.corpus()

    def test_repeated_identical_queries_consume_recorded_sequence_once_without_network(self):
        self.store.request(workload.SOLANA, 'getSlot', [], 10, .1)
        self.store.request(workload.SOLANA, 'getSlot', [], 11, .2)
        self.store.request(workload.ROBINHOOD, 'eth_blockNumber', [], '0x11', .3)
        with patch.object(workload.PublicRPC, '_transport', side_effect=AssertionError('network forbidden')):
            rpc = workload.ReplayRPC(self.store.path)
            self.assertEqual(rpc.call(workload.SOLANA, 'getSlot', []), 10)
            self.assertEqual(rpc.call(workload.ROBINHOOD, 'eth_blockNumber', []), '0x11')
            self.assertEqual(rpc.call(workload.SOLANA, 'getSlot', []), 11)
            with self.assertRaisesRegex(workload.ObservationUnavailable, 'native_replay_input_missing'):
                rpc.call(workload.SOLANA, 'getSlot', [])
            with self.assertRaises(workload.ObservationUnavailable):
                rpc.call(workload.SOLANA, 'getBlock', [10])
            with self.assertRaises(workload.ObservationUnavailable):
                rpc.call(workload.SOLANA, 'sendTransaction', [])

    def test_response_or_request_relabeling_cannot_reuse_original_checksum(self):
        self.store.request(workload.SOLANA, 'getBlock', [10], dict(blockhash='original'), .1)
        original = self.store.db.execute('SELECT * FROM rpc').fetchone()
        for column, value in (('response', workload.canonical(dict(blockhash='forged'))),
                ('params', '[11]'), ('method', 'getSlot'), ('endpoint', workload.ROBINHOOD)):
            with self.subTest(column=column):
                self.store.db.execute('UPDATE rpc SET ' + column + '=? WHERE id=1', (value,))
                with self.assertRaises(workload.ObservationUnavailable):
                    workload.ReplayRPC(self.store.path)
                self.store.db.execute('DELETE FROM rpc')
                self.store.db.execute('INSERT INTO rpc VALUES(?,?,?,?,?,?,?)', original)

    def test_self_consistent_hash_cannot_admit_unknown_method_endpoint_or_params_shape(self):
        for endpoint, method, params in (('https://private.invalid', 'getSlot', []),
                (workload.SOLANA, 'sendTransaction', []),
                (workload.ROBINHOOD, 'eth_sendRawTransaction', []),
                (workload.SOLANA, 'getSlot', {})):
            self.store.db.execute('DELETE FROM rpc')
            body = workload.canonical(123)
            checksum = hashlib.sha256(workload.canonical([endpoint, method, params, 123]).encode()).hexdigest()
            self.store.db.execute('INSERT INTO rpc VALUES(1,?,?,?,?,?,?)',
                (endpoint, method, workload.canonical(params), body, checksum, .1))
            with self.subTest(endpoint=endpoint, method=method, params=params):
                with self.assertRaises(workload.ObservationUnavailable):
                    workload.ReplayRPC(self.store.path)

    def test_replay_checks_request_body_and_total_corpus_bounds(self):
        self.store.request(workload.SOLANA, 'getSlot', [], 'x' * 100, .1)
        with patch.object(workload, 'MAX_BODY', 64):
            with self.assertRaises(workload.ObservationUnavailable):
                workload.ReplayRPC(self.store.path)
        with patch.object(workload, 'MAX_CORPUS', 64):
            with self.assertRaises(workload.ObservationUnavailable):
                workload.ReplayRPC(self.store.path)
        self.store.request(workload.SOLANA, 'getSlot', [], 20, .2)
        with patch.object(workload, 'MAX_REQUESTS', 1):
            with self.assertRaises(workload.ObservationUnavailable):
                workload.ReplayRPC(self.store.path)


class CaptureLifecycle(Scratch):
    def test_storage_rejection_precedes_any_corpus_or_provider(self):
        usage = SimpleNamespace(f_bavail=1, f_bfree=1, f_blocks=100, f_frsize=4096)
        with patch.object(workload.os, 'statvfs', return_value=usage), \
                patch.object(workload, 'Corpus') as corpus, \
                patch.object(workload, 'PublicRPC') as rpc:
            with self.assertRaisesRegex(workload.ObservationUnavailable, 'native_scratch_storage_admission'):
                workload.capture(self.root, duration=12)
            corpus.assert_not_called(); rpc.assert_not_called()

    def test_root_usage_threshold_is_independent_of_free_byte_reserve(self):
        usage = SimpleNamespace(f_bavail=10 * 1024**3, f_bfree=10 * 1024**3,
                                f_blocks=100 * 1024**3, f_frsize=1)
        with patch.object(workload.os, 'statvfs', return_value=usage):
            with self.assertRaisesRegex(workload.ObservationUnavailable, 'native_scratch_storage_admission'):
                workload._storage_admission(self.root)

    def test_failed_consume_preserves_attempt_without_completion_and_keeps_partial_flags(self):
        closed = []
        pump_attempted = threading.Event()
        class Projection:
            def __init__(self, lane): self.lane = lane
            def consume(self, *args, **kwargs):
                if self.lane == 'pump': pump_attempted.set()
                raise ValueError('PRIVATE_NATIVE_FAILURE')
            def snapshot(self): return dict(retained=True)
            def reopen(self): return dict(restored=True)
            def close(self): closed.append(self.lane)
        class RPC:
            requests = 0
            http_429 = 0
            def __init__(self, corpus, stop, deadline): self.deadline = deadline
            def call(self, endpoint, method, params):
                if method == 'eth_chainId' and not pump_attempted.wait(2):
                    raise AssertionError('Pump test worker did not run')
                return {'getSlot': 81, 'getBlocks':[81], 'getBlock': {}, 'eth_chainId': '0x1237',
                        'eth_blockNumber': '0x2a'}[method]
        with patch.object(workload, '_storage_admission', return_value={}), \
                patch.object(workload, 'PublicRPC', RPC), \
                patch.object(workload, '_projection', side_effect=lambda lane, root: Projection(lane)):
            result = workload.capture(self.root, duration=12)
        self.assertEqual(result['result'], 'PARTIAL_NATIVE_ALTERNATIVE')
        self.assertEqual(result['lanes']['pump']['attempted_events'], 1)
        self.assertEqual(result['lanes']['pump']['completed_events'], 0)
        self.assertEqual(result['lanes']['pump']['error_type'], 'ValueError')
        self.assertIsNone(result['lanes']['pump']['code'])
        self.assertNotIn('PRIVATE_NATIVE_FAILURE', workload.canonical(result))
        self.assertEqual(set(closed), {'pump', 'pons'})
        self.assertTrue(result['cleanup_completed'])
        for key in ('production_equivalent', 'full_market_speed_proven',
                    'financial_authority', 'acceptance_passed', 'native_cancellation_bounded'):
            self.assertFalse(result[key])
        with sqlite3.connect(self.root / 'corpus.sqlite3') as db:
            self.assertEqual(db.execute('SELECT count(*) FROM completions').fetchone(), (0,))

    def test_thread_start_failure_joins_started_worker_before_closing_corpus(self):
        state = dict(closed=False, finalizations=0)
        class Projection:
            def snapshot(self): return {}
            def reopen(self): return {}
            def close(self): state['finalizations'] += 1
        class RPC:
            def __init__(self, corpus, stop, deadline): self.deadline = deadline
            def call(self, *args): raise workload.ObservationUnavailable('native_work_window_closed')
        original_start = threading.Thread.start
        original_close = workload.Corpus.close
        def start(thread):
            if thread.name == 'isolated-pons':
                raise RuntimeError('second worker failed to start')
            return original_start(thread)
        def close(corpus):
            self.assertEqual(state['finalizations'], 1)
            state['closed'] = True
            original_close(corpus)
        with patch.object(workload, '_storage_admission', return_value={}), \
                patch.object(workload, 'PublicRPC', RPC), \
                patch.object(workload, '_projection', return_value=Projection()), \
                patch.object(threading.Thread, 'start', start), \
                patch.object(workload.Corpus, 'close', close):
            with self.assertRaisesRegex(RuntimeError, 'second worker failed to start'):
                workload.capture(self.root, duration=12)
        self.assertTrue(state['closed'])

    def test_backlog_counts_same_chain_population_and_regression_never_becomes_progress(self):
        progress = workload.Progress('pump')
        progress.sample(100)
        progress.enumerate_slots(100, 100, [100])
        progress.sample(first=100, last=100)
        progress.sample(105)
        progress.enumerate_slots(101, 105, [101, 102, 103, 104, 105])
        progress.sample(first=101, last=101)
        progress.sample(first=102, last=102)
        last = progress.summary()['samples'][-1]
        self.assertEqual(last['offered_chain_units'], 6)
        self.assertEqual(last['completed_chain_units'], 3)
        self.assertEqual(last['sampled_backlog_chain_units'], 3)
        self.assertIsInstance(last['wall_epoch_seconds'], float)
        with self.assertRaisesRegex(workload.ObservationUnavailable, 'native_chain_head_regressed'):
            progress.sample(104)
        with self.assertRaisesRegex(workload.ObservationUnavailable, 'native_processing_population_changed'):
            progress.sample(first=104, last=105)
        self.assertEqual(progress.summary()['samples'][-1], last)

    def test_capture_decodes_only_returned_blocks_and_retains_public_absence_separately(self):
        consumed = []
        pump_done = threading.Event()
        class Projection:
            def __init__(self, lane): self.lane = lane
            def consume(self, slot, *args, **kwargs):
                if self.lane != 'pump':
                    raise AssertionError('unexpected offline Pons consumption')
                consumed.append(slot)
                if slot == 84:
                    rpc_stop[0].set()
                    pump_done.set()
            def snapshot(self): return dict(partial=True)
            def reopen(self): return dict(restored=True)
            def close(self): pass
        rpc_stop = []
        class RPC:
            requests = 0
            http_429 = 0
            def __init__(self, corpus, stop, deadline):
                self.corpus, self.deadline = corpus, deadline
                self.head_reads = 0
                rpc_stop.append(stop)
            def call(self, endpoint, method, params):
                self.requests += 1
                if method == 'getSlot':
                    self.head_reads += 1
                    value = 81 if self.head_reads == 1 else 84
                elif method == 'getBlocks':
                    value = [81] if params[0] == 81 else [83, 84]
                elif method == 'getBlock':
                    value = {}
                elif method == 'eth_chainId':
                    if not pump_done.wait(2):
                        raise AssertionError('offline Pump capture did not finish')
                    value = '0x1237'
                else:
                    raise AssertionError('unexpected offline method')
                self.corpus.request(endpoint, method, params, value, 0.)
                return value
        with patch.object(workload, '_storage_admission', return_value={}), \
                patch.object(workload, 'PublicRPC', RPC), \
                patch.object(workload, '_projection', side_effect=lambda lane, root:Projection(lane)):
            result = workload.capture(self.root, duration=12)
        self.assertEqual(consumed, [81, 83, 84])
        pump = result['lanes']['pump']
        self.assertEqual((pump['attempted_events'], pump['completed_events']), (3, 3))
        sample = pump['processing']['samples'][-1]
        self.assertEqual(sample['offered_chain_units'], 4)
        self.assertEqual(sample['completed_chain_units'], 3)
        self.assertEqual(sample['provider_enumerated_absent_chain_units'], 1)
        self.assertEqual(sample['sampled_backlog_chain_units'], 0)
        self.assertEqual(sample['sampled_backlog_population'],
                         'provider_enumerated_available_block_slots')
        self.assertFalse(pump['processing']['public_absences_are_chain_proof'])
        with sqlite3.connect(self.root/'corpus.sqlite3') as db:
            self.assertEqual([json.loads(row[0])['slot'] for row in db.execute(
                "SELECT body FROM events WHERE lane='pump' ORDER BY id")], [81, 83, 84])
            self.assertEqual([json.loads(row[0]) for row in db.execute(
                "SELECT response FROM rpc WHERE method='getBlocks' ORDER BY id")], [[81], [83, 84]])


class PublicSolanaEnumeration(unittest.TestCase):
    def test_absent_slots_are_acquisition_facts_and_never_completed_economics(self):
        calls = []
        class RPC:
            def call(self, endpoint, method, params):
                calls.append((endpoint, method, params))
                return [100, 102, 104]
        progress = workload.Progress('pump')
        progress.sample(100)
        progress.sample(104)
        last, blocks = workload.solana_block_slots(RPC(), 100, 104)
        self.assertEqual(calls, [(workload.SOLANA, 'getBlocks',
                                 [100, 104, {'commitment':'finalized'}])])
        progress.enumerate_slots(100, last, blocks)
        sample = progress.summary()['samples'][-1]
        self.assertEqual(sample['completed_chain_units'], 0)
        self.assertEqual(sample['enumerated_block_chain_units'], 3)
        self.assertEqual(sample['provider_enumerated_absent_chain_units'], 2)
        self.assertEqual(sample['sampled_backlog_chain_units'], 3)
        for slot in range(100, 105):
            if slot in blocks:
                progress.sample(first=slot, last=slot)
            else:
                progress.reported_absent(slot, slot)
        sample = progress.summary()['samples'][-1]
        self.assertEqual(sample['completed_chain_units'], 3)
        self.assertEqual(sample['offered_chain_units'], 5)
        self.assertEqual(sample['sampled_backlog_chain_units'], 0)
        self.assertFalse(progress.summary()['public_absences_are_chain_proof'])
        self.assertEqual(progress.summary()['public_slot_enumerations'][0]['enumerated_absent_slots'],
                         [101, 103])
        self.assertFalse(progress.summary()['public_slot_enumerations'][0]['canonical_completeness'])

    def test_range_is_capped_at_forty_and_malformed_responses_never_change_progress(self):
        responses = [[100, 139]]
        calls = []
        class RPC:
            def call(self, endpoint, method, params):
                calls.append(params)
                return responses[-1]
        self.assertEqual(workload.solana_block_slots(RPC(), 100, 200), (139, [100, 139]))
        self.assertEqual(calls[-1], [100, 139, {'commitment':'finalized'}])
        progress = workload.Progress('pump')
        progress.sample(100)
        progress.sample(139)
        before = json.loads(workload.canonical(progress.summary()))
        for malformed in (None, '100', [True], [100, '101'], [99], [140], [101, 100], [100, 100]):
            with self.subTest(malformed=malformed):
                responses.append(malformed)
                with self.assertRaises(workload.ObservationUnavailable):
                    workload.solana_block_slots(RPC(), 100, 200)
                with self.assertRaises(workload.ObservationUnavailable):
                    progress.enumerate_slots(100, 139, malformed)
                self.assertEqual(progress.summary(), before)
        with self.assertRaisesRegex(workload.ObservationUnavailable, 'native_solana_enumeration_range'):
            progress.enumerate_slots(100, 140, [])
        before_calls = len(calls)
        with self.assertRaisesRegex(workload.ObservationUnavailable, 'native_solana_enumeration_range'):
            workload.solana_block_slots(RPC(), 100, 99)
        self.assertEqual(len(calls), before_calls)
        self.assertEqual(progress.summary(), before)

    def test_regressed_head_and_unenumerated_absence_preserve_original_population(self):
        progress = workload.Progress('pump')
        progress.sample(100)
        progress.sample(104)
        progress.enumerate_slots(100, 104, [100, 102, 104])
        progress.sample(first=100, last=100)
        before = json.loads(workload.canonical(progress.summary()))
        for operation in (lambda:progress.sample(103),
                          lambda:progress.reported_absent(101, 102),
                          lambda:progress.enumerate_slots(100, 104, []),
                          lambda:progress.sample(first=101, last=101)):
            with self.assertRaises(workload.ObservationUnavailable):
                operation()
            self.assertEqual(progress.summary(), before)


class NativeFailureReceipts(unittest.TestCase):
    def test_only_exact_literal_component_codes_are_admitted(self):
        from meme_machine.operational.isolated_native_pons import PonsProjectionUnavailable
        for error, expected in (
            (ValueError('isolated_pump_complete_logs_required'), 'isolated_pump_complete_logs_required'),
            (PonsProjectionUnavailable('pons_projection_history_mismatch'), 'pons_projection_history_mismatch'),
            (workload.ObservationUnavailable('native_solana_enumeration_shape'), 'native_solana_enumeration_shape')):
            self.assertEqual(workload._failure(error)['code'], expected)
        canaries = ('PRIVATE_API_KEY https://private.invalid/private_body',
                    'isolated_pump_private_canary', 'pons_projection_private_canary',
                    'native_private_canary')
        for canary in canaries:
            for constructor in (ValueError, PonsProjectionUnavailable, workload.ObservationUnavailable):
                with self.subTest(constructor=constructor.__name__, canary=canary):
                    receipt = workload._failure(constructor(canary))
                    self.assertIsNone(receipt['code'])
                    self.assertNotIn(canary, workload.canonical(receipt))

    def test_attribute_error_in_pump_startup_reports_only_pinned_module_function_line(self):
        # A real on-host Pump AttributeError had been swallowed as type-only,
        # stopping Pons before either worker could make a public RPC request.
        # No exception text or arbitrary path can enter the published receipt.
        from meme_machine.operational import isolated_native_pump
        canary = 'PRIVATE_ATTRIBUTE_AND_RPC_BODY https://private.invalid/token'
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(isolated_native_pump, 'PumpNativeProjection',
                              side_effect=AttributeError(canary)):
                try:
                    workload._projection('pump', Path(directory))
                except AttributeError as error:
                    receipt = workload._failure(error)
                else:
                    self.fail('expected attributed Pump startup failure')
        self.assertEqual(receipt['error_type'], 'AttributeError')
        self.assertIsNone(receipt['code'])
        self.assertEqual(receipt['failure_site']['module'],
                         'meme_machine.operational.isolated_native_workload')
        self.assertEqual(receipt['failure_site']['function'], '_projection')
        self.assertTrue(0 < receipt['failure_site']['line'] < 100000)
        self.assertEqual(set(receipt['failure_site']), {'module', 'function', 'line'})
        self.assertNotIn(canary, workload.canonical(receipt))
        self.assertNotIn('/private/', workload.canonical(receipt))

    def test_foreign_attribute_error_never_exposes_external_traceback(self):
        try:
            raise AttributeError('PRIVATE_REMOTE_PROVIDER_KEY')
        except AttributeError as error:
            receipt = workload._failure(error)
        self.assertEqual(receipt['error_type'], 'AttributeError')
        self.assertIsNone(receipt['failure_site'])
        self.assertNotIn('PRIVATE_REMOTE_PROVIDER_KEY', workload.canonical(receipt))

    def test_native_boundary_retains_only_application_failure_site_without_message_or_path(self):
        from meme_machine.lanes.pons import BoundaryError
        from meme_machine.lanes.pons.abi import calldata
        canary = 'PRIVATE_SQL_AND_PROVIDER_BODY https://private.invalid/API_KEY'
        try:
            calldata('f(uint256)', -1)
        except BoundaryError as error:
            error.args = (canary,)
            receipt = workload._failure(error)
        else:
            self.fail('native ABI boundary did not reject negative uint')
        self.assertIsNone(receipt['code'])
        site = receipt['failure_site']
        self.assertEqual(site['module'], 'meme_machine.lanes.pons.abi')
        self.assertEqual(site['function'], 'calldata')
        self.assertIs(type(site['line']), int)
        self.assertEqual(set(site), {'module', 'function', 'line'})
        self.assertNotIn(canary, workload.canonical(receipt))
        self.assertNotIn(str(Path(__file__).resolve().parents[1]), workload.canonical(receipt))


if __name__ == '__main__':
    unittest.main()
