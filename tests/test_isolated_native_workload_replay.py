"""Replay disposable completed native inputs; never acquire real market data."""
from contextlib import contextmanager
import copy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

from meme_machine.operational import isolated_native_workload as workload


def file_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def copied(value):
    return json.loads(workload.canonical(value))


class CompletedNativeReplay(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.capture_root = self.base / 'capture'
        self.capture_root.mkdir(mode=0o700)
        self.replay_root = self.base / 'replay'
        self.replay_root.mkdir(mode=0o700)
        self.corpus = workload.Corpus(self.capture_root)
        self.addCleanup(self.corpus.close)
        self.instances = {'pump': [], 'pons': []}
        self.logs = [dict(blockNumber='0x2a', transactionHash='0xabc', logIndex='0x0')]

    @staticmethod
    def log_query(first, last):
        return [dict(fromBlock=hex(first), toBlock=hex(last))]

    @contextmanager
    def fake_native(self):
        """Keep replay orchestration real while replacing economic projections."""
        case = self

        class Projection:
            lane = None

            def __init__(self, root):
                self.root = Path(root)
                case.assertEqual(self.root.parent, case.replay_root)
                case.assertEqual(self.root.name, self.lane)
                self.inputs = []
                self.snapshot_calls = 0
                self.reopen_calls = 0
                self.closed = False
                case.instances[self.lane].append(self)

            def snapshot(self):
                self.snapshot_calls += 1
                return dict(lane=self.lane, inputs=copied(self.inputs))

            def reopen(self):
                self.reopen_calls += 1
                return dict(lane=self.lane, inputs=copied(self.inputs))

            def close(self):
                self.closed = True

        class Pump(Projection):
            lane = 'pump'

            def consume(self, slot, block, *, observed_at):
                self.inputs.append(dict(slot=slot, block=copied(block), observed_at=observed_at))

        class Pons(Projection):
            lane = 'pons'

            def consume(self, first, last, rpc, *, observed_at):
                logs = rpc.call(workload.ROBINHOOD, 'eth_getLogs', case.log_query(first, last))
                self.inputs.append(dict(first=first, last=last, logs=copied(logs),
                                        observed_at=observed_at))

        pump = types.ModuleType('meme_machine.operational.isolated_native_pump')
        pump.PumpNativeProjection = Pump
        pons = types.ModuleType('meme_machine.operational.isolated_native_pons')
        pons.PonsNativeProjection = Pons
        with patch.dict(sys.modules, {pump.__name__: pump, pons.__name__: pons}), \
                patch.object(workload, '_storage_admission'), \
                patch.object(workload.PublicRPC, '_transport',
                             side_effect=AssertionError('network forbidden')) as network, \
                patch.object(workload, 'build_opener',
                             side_effect=AssertionError('network forbidden')):
            yield network
            network.assert_not_called()

    def pump_event(self, slot, observed, *, complete=True):
        block = dict(blockhash='block-' + str(slot), transactions=[])
        event_id = self.corpus.event('pump',
            dict(slot=slot, block=block, acquired_head=slot + 1), observed)
        self.assertIs(type(event_id), int)
        if complete:
            self.corpus.complete(event_id)
        return event_id, dict(slot=slot, block=block, observed_at=observed)

    def pons_event(self, first, last, observed, *, complete=True):
        event_id = self.corpus.event('pons',
            dict(first=first, last=last, acquired_head=last), observed)
        self.assertIs(type(event_id), int)
        if complete:
            with self.corpus.recording(event_id):
                self.corpus.request(workload.ROBINHOOD, 'eth_getLogs',
                                    self.log_query(first, last), self.logs, .25)
            self.corpus.complete(event_id)
        return event_id, dict(first=first, last=last, logs=copied(self.logs), observed_at=observed)

    def seal(self):
        self.corpus.close()
        return file_digest(self.corpus.path)

    def test_only_completed_events_are_consumed_and_original_times_are_retained(self):
        _, pump_first = self.pump_event(81, 1000.125)
        self.pump_event(82, 1001.5, complete=False)
        _, pons_first = self.pons_event(42, 43, 1002.75)
        self.pons_event(44, 45, 1003.875, complete=False)
        _, pump_second = self.pump_event(83, 1004.25)
        expected_sha256 = self.seal()
        original_bytes = self.corpus.path.read_bytes()

        with self.fake_native():
            result = workload.replay(self.corpus.path, self.replay_root, expected_sha256)

        self.assertEqual(len(self.instances['pump']), 1)
        self.assertEqual(len(self.instances['pons']), 1)
        self.assertEqual(self.instances['pump'][0].inputs, [pump_first, pump_second])
        self.assertEqual(self.instances['pons'][0].inputs, [pons_first])
        for lane in ('pump', 'pons'):
            projection = self.instances[lane][0]
            expected_state = dict(lane=lane, inputs=projection.inputs)
            self.assertGreaterEqual(projection.snapshot_calls, 1)
            self.assertEqual(projection.reopen_calls, 1)
            self.assertTrue(projection.closed)
            self.assertEqual(result['lanes'][lane]['projection'], expected_state)
            self.assertEqual(result['lanes'][lane]['restoration'], expected_state)
        self.assertEqual(self.corpus.path.read_bytes(), original_bytes)

    def test_wrong_external_digest_rejects_before_constructing_any_projection(self):
        self.pump_event(81, 1000.125)
        self.pons_event(42, 43, 1001.5)
        self.seal()

        with self.fake_native(), self.assertRaises(workload.ObservationUnavailable):
            workload.replay(self.corpus.path, self.replay_root, '0' * 64)

        self.assertEqual(self.instances, {'pump': [], 'pons': []})
        self.assertEqual(list(self.replay_root.iterdir()), [])

    def test_event_body_tamper_rejects_even_with_recomputed_external_digest(self):
        event_id, _ = self.pump_event(81, 1000.125)
        self.pons_event(42, 43, 1001.5)
        self.seal()
        with sqlite3.connect(self.corpus.path) as db:
            forged = workload.canonical(dict(slot=999, block=dict(transactions=[]), acquired_head=999))
            db.execute('UPDATE events SET body=? WHERE id=?', (forged, event_id))
        forged_sha256 = file_digest(self.corpus.path)

        with self.fake_native(), self.assertRaisesRegex(
                workload.ObservationUnavailable, 'native_corpus_event_hash'):
            workload.replay(self.corpus.path, self.replay_root, forged_sha256)

        self.assertEqual(self.instances, {'pump': [], 'pons': []})

    def test_missing_event_rpc_cannot_use_another_attempt_or_network_fallback(self):
        incomplete, _ = self.pons_event(42, 43, 1000.125, complete=False)
        with self.corpus.recording(incomplete):
            self.corpus.request(workload.ROBINHOOD, 'eth_getLogs',
                                self.log_query(42, 43), self.logs, .25)
        completed, _ = self.pons_event(42, 43, 1001.5, complete=False)
        self.corpus.complete(completed)
        expected_sha256 = self.seal()

        with self.fake_native():
            result = workload.replay(self.corpus.path, self.replay_root, expected_sha256)

        self.assertEqual(len(self.instances['pons']), 1)
        self.assertEqual(self.instances['pons'][0].inputs, [])
        self.assertTrue(self.instances['pons'][0].closed)
        self.assertEqual(result['lanes']['pons']['state'], 'PARTIAL_OR_BLOCKED')
        self.assertEqual(result['lanes']['pons']['code'], 'native_replay_input_missing')

    def test_replay_refuses_nonprivate_corpus_file_before_constructing_projection(self):
        self.pump_event(81, 1000.125)
        expected_sha256 = self.seal()
        self.corpus.path.chmod(0o644)

        with self.fake_native(), self.assertRaises(workload.ObservationUnavailable):
            workload.replay(self.corpus.path, self.replay_root, expected_sha256)

        self.assertEqual(self.instances, {'pump': [], 'pons': []})

    def test_replay_refuses_symlinked_corpus_before_constructing_any_projection(self):
        self.pump_event(81, 1000.125)
        expected_sha256 = self.seal()
        alias = self.capture_root / 'alias.sqlite3'
        alias.symlink_to(self.corpus.path)

        with self.fake_native(), self.assertRaises(workload.ObservationUnavailable):
            workload.replay(alias, self.replay_root, expected_sha256)

        self.assertEqual(self.instances, {'pump': [], 'pons': []})


class CombinedRealNativeReplay(unittest.TestCase):
    def test_version_one_public_blocks_capture_and_replay_both_actual_native_projections(self):
        """Regression for public getBlock -32015 at the obsolete version-zero cap."""
        fixture_root = Path(__file__).parent
        pump = json.loads((fixture_root/'fixtures/solana_selective_cohort.json').read_text())
        pons = json.loads((fixture_root/'lanes/pons/fixtures/'
            'public_log_timestamp_35915320840.json').read_text())
        tx = copy.deepcopy(pump['pump'][0])
        tx.pop('transactionIndex', None)
        # Synthetic provider capability metadata; original protocol event bytes
        # remain the retained fixture. This is not authentic v1 market evidence.
        tx['version'] = 1
        slot, pons_block = tx['slot'], int(pons['header']['number'],16)
        observed_now = max(tx['blockTime'],int(pons['header']['timestamp'],16))+3.125
        block = dict(blockTime=tx['blockTime'], blockhash='offline-version-one-'+str(slot),
                     parentSlot=slot-1, previousBlockhash='offline-parent', transactions=[tx])
        requests = []
        canary = 'PRIVATE_PROVIDER_MESSAGE https://private.invalid/API_KEY'

        def transport(endpoint, payload, timeout):
            packet = json.loads(payload)
            method, params = packet['method'], packet['params']
            requests.append((endpoint, method, copied(params)))
            if endpoint == workload.SOLANA:
                if method == 'getSlot':
                    response = slot
                elif method == 'getBlocks':
                    self.assertEqual(params, [slot, slot, {'commitment':'finalized'}])
                    response = [slot]
                elif method == 'getBlock':
                    self.assertEqual(params[0], slot)
                    if params[1]['maxSupportedTransactionVersion'] == 0:
                        return workload.canonical(dict(jsonrpc='2.0', id=packet['id'],
                            error=dict(code=-32015,message=canary))).encode()
                    self.assertEqual(params[1]['maxSupportedTransactionVersion'], 1)
                    response = copied(block)
                else:
                    self.fail('unexpected offline Solana method')
            else:
                self.assertEqual(endpoint, workload.ROBINHOOD)
                if method == 'eth_chainId':
                    response = '0x1237'
                elif method == 'eth_blockNumber':
                    response = hex(pons_block)
                elif method == 'eth_getBlockByNumber':
                    self.assertEqual(params, [hex(pons_block),False])
                    response = copied(pons['header'])
                elif method == 'eth_getLogs':
                    self.assertEqual((int(params[0]['fromBlock'],16),int(params[0]['toBlock'],16)),
                                     (pons_block,pons_block))
                    response = [copied(pons['event'])]
                elif method == 'eth_getTransactionReceipt':
                    self.assertEqual(params, [pons['event']['transactionHash']])
                    response = copied(pons['receipt'])
                else:
                    self.fail('unexpected offline Robinhood method')
            return workload.canonical(dict(jsonrpc='2.0',id=packet['id'],result=response)).encode()

        original_rpc = workload.PublicRPC
        original_complete = workload.Corpus.complete
        clients = []

        def client(corpus, stop, deadline):
            # Exercise the actual PublicRPC recorder and shared transport lock;
            # only its injected sleeper bypasses real pacing in this offline test.
            rpc = original_rpc(corpus,stop,deadline,transport=transport,sleeper=lambda _:None)
            clients.append(rpc)
            return rpc

        def complete(corpus, event_id):
            original_complete(corpus,event_id)
            counts = corpus.counts()
            if all(counts.get(lane,{}).get('completed_events',0) >= 1 for lane in ('pump','pons')):
                clients[0].stop.set()

        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(os.environ,{},clear=True), \
                patch.object(workload.time,'time',return_value=observed_now), \
                patch.object(workload,'_storage_admission',return_value=dict(offline_fixture=True)), \
                patch.object(original_rpc,'_transport',side_effect=AssertionError('network forbidden')) as network, \
                patch.object(workload,'build_opener',side_effect=AssertionError('network forbidden')):
            base = Path(directory)
            rejected_root, capture_root, replay_root = (base/name for name in ('rejected','capture','replay'))
            for root in (rejected_root,capture_root,replay_root):
                root.mkdir(mode=0o700)
            rejected = workload.Corpus(rejected_root)
            self.addCleanup(rejected.close)
            rejecting_rpc = original_rpc(rejected,threading.Event(),workload.time.monotonic()+12,
                                         transport=transport,sleeper=lambda _:None)
            with self.assertRaisesRegex(workload.ObservationUnavailable,'native_rpc_rejected'):
                rejecting_rpc.call(workload.SOLANA,'getBlock',[slot,dict(
                    commitment='finalized',encoding='json',transactionDetails='full',
                    rewards=False,maxSupportedTransactionVersion=0)])
            self.assertEqual(rejecting_rpc.rejection,dict(method='getBlock',code=-32015))
            self.assertEqual(rejected.counts(),{})
            rejected.close()

            with patch.object(workload,'PublicRPC',side_effect=client), \
                    patch.object(workload.Corpus,'complete',complete):
                captured = workload.capture(capture_root,duration=12)
            self.assertEqual(len(clients),1)
            self.assertIsNone(captured['provider_rpc_rejection'])
            self.assertTrue(captured['all_started_workers_joined'])
            self.assertTrue(captured['cleanup_completed'])
            for lane in ('pump','pons'):
                self.assertEqual(captured['lanes'][lane]['completed_events'],1,captured['lanes'][lane])
                self.assertTrue(captured['lanes'][lane]['projection_closed'])
            self.assertGreater(captured['lanes']['pump']['projection']['counts']['events'],0)
            self.assertEqual(captured['lanes']['pons']['projection']['durable_economic_events'],1)
            corpus_path = capture_root/'corpus.sqlite3'
            before = corpus_path.read_bytes()
            replayed = workload.replay(corpus_path,replay_root,file_digest(corpus_path))
            self.assertEqual(replayed['provider_requests'],0)
            self.assertTrue(replayed['all_started_workers_joined'])
            self.assertTrue(replayed['cleanup_completed'])
            self.assertEqual(corpus_path.read_bytes(),before)
            for lane, key in (('pump','logical_sha256'),('pons','economic_corpus_sha256')):
                self.assertEqual(replayed['lanes'][lane]['state'],'REPLAY_COMPLETED_INPUTS')
                self.assertEqual(replayed['lanes'][lane]['replayed_events'],1)
                self.assertEqual(replayed['lanes'][lane]['projection'][key],
                                 captured['lanes'][lane]['projection'][key])
                self.assertEqual(replayed['lanes'][lane]['restoration'][key],
                                 captured['lanes'][lane]['projection'][key])
            for result in (captured,replayed):
                self.assertFalse(result['production_equivalent'])
                self.assertFalse(result['financial_authority'])
                self.assertFalse(result['acceptance_passed'])
                self.assertNotIn(canary,workload.canonical(result))
            # Both the failing public request and corrected real capture passed
            # the capability-sensitive provider boundary; neither reached HTTP.
            versions = [params[1]['maxSupportedTransactionVersion']
                        for endpoint,method,params in requests if method == 'getBlock']
            self.assertEqual(versions,[0,1])
            network.assert_not_called()

    def test_completed_corpus_replays_both_real_native_projections_and_preserves_economics(self):
        """One offline end-to-end contract; both projections retain partial parity."""
        from meme_machine.operational.isolated_native_pump import PumpNativeProjection
        from meme_machine.operational.isolated_native_pons import PonsNativeProjection, NAMESPACE
        from meme_machine.solana_program_decoders import pump_events

        fixture_root = Path(__file__).parent
        pump_fixture = json.loads((fixture_root/'fixtures/solana_selective_cohort.json').read_text())
        pons_fixture = json.loads((fixture_root/'lanes/pons/fixtures/'
            'public_log_timestamp_35915320840.json').read_text())
        transaction = copy.deepcopy(pump_fixture['pump'][0])
        # This fixture is one offered full-block transaction array, not a
        # claim that the retained selective transaction is a complete mainnet block.
        transaction.pop('transactionIndex', None)
        slot = transaction['slot']
        block = dict(blockTime=transaction['blockTime'], blockhash='offline-block-'+str(slot),
                     parentSlot=slot-1, previousBlockhash='offline-parent',
                     transactions=[transaction])
        pump_seen = 1792000000.125
        pons_block = int(pons_fixture['header']['number'], 16)
        pons_seen = int(pons_fixture['header']['timestamp'], 16)+3.75
        expected_pump_events = len(pump_events(transaction))
        self.assertGreater(expected_pump_events, 0)
        calls = []

        def transport(endpoint, payload, timeout):
            self.assertEqual(endpoint, workload.ROBINHOOD)
            packet = json.loads(payload)
            method, params = packet['method'], packet['params']
            calls.append((method, copied(params)))
            if method == 'eth_getBlockByNumber':
                self.assertEqual(params, [hex(pons_block), False])
                response = copy.deepcopy(pons_fixture['header'])
            elif method == 'eth_getLogs':
                query = params[0]
                self.assertEqual((int(query['fromBlock'],16), int(query['toBlock'],16)),
                                 (pons_block, pons_block))
                response = [copy.deepcopy(pons_fixture['event'])]
            elif method == 'eth_getTransactionReceipt':
                self.assertEqual(params, [pons_fixture['event']['transactionHash']])
                response = copy.deepcopy(pons_fixture['receipt'])
            else:
                self.fail('unexpected offline method: '+method)
            return workload.canonical(dict(jsonrpc='2.0', id=packet['id'], result=response)).encode()

        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(os.environ, {}, clear=True), \
                patch.object(workload, '_storage_admission', return_value=dict(offline_fixture=True)), \
                patch.object(workload.PublicRPC, '_transport',
                             side_effect=AssertionError('network forbidden')) as network, \
                patch.object(workload, 'build_opener',
                             side_effect=AssertionError('network forbidden')):
            base = Path(directory)
            capture_root, replay_root = base/'capture', base/'replay'
            capture_root.mkdir(mode=0o700)
            replay_root.mkdir(mode=0o700)
            corpus = workload.Corpus(capture_root)
            self.addCleanup(corpus.close)
            original_pump_root, original_pons_root = base/'original-pump', base/'original-pons'
            original_pump_root.mkdir(mode=0o700)
            original_pons_root.mkdir(mode=0o700)
            original_pump = PumpNativeProjection(original_pump_root)
            self.addCleanup(original_pump.close)
            original_pons = PonsNativeProjection(original_pons_root)
            self.addCleanup(original_pons.close)
            # All transport responses pass the real PublicRPC receipt recorder.
            # Its injected clock/sleeper avoid real provider pacing in offline CI.
            rpc = workload.PublicRPC(corpus, threading.Event(), 100,
                transport=transport, clock=lambda:0., sleeper=lambda _:None)
            pump_event = corpus.event('pump',
                dict(slot=slot, block=block, acquired_head=slot), pump_seen)
            original_pump.consume(slot, block, observed_at=pump_seen)
            with patch.object(workload.time, 'time', return_value=pump_seen+1):
                corpus.complete(pump_event)
            pons_event = corpus.event('pons',
                dict(first=pons_block, last=pons_block, acquired_head=pons_block), pons_seen)
            with corpus.recording(pons_event):
                original_pons.consume(pons_block, pons_block, rpc, observed_at=pons_seen)
            with patch.object(workload.time, 'time', return_value=pons_seen+1):
                corpus.complete(pons_event)
            baseline_pump = original_pump.snapshot()
            baseline_pons = original_pons.snapshot()
            baseline_pump_restore = original_pump.reopen(now=pump_seen)
            baseline_pons_restore = original_pons.reopen()
            original_pump.close()
            original_pons.close()
            self.assertEqual(corpus.counts(), dict(
                pump=dict(attempted_events=1, completed_events=1),
                pons=dict(attempted_events=1, completed_events=1)))
            self.assertGreaterEqual(len(calls), 4)
            corpus.close()
            original_corpus_bytes = corpus.path.read_bytes()
            external_sha256 = file_digest(corpus.path)

            # No fake projection/module injection: replay constructs the actual
            # Pump and Pons components on their two independently owned threads.
            result = workload.replay(corpus.path, replay_root, external_sha256)
            network.assert_not_called()
            self.assertEqual(result['provider_requests'], 0)
            self.assertEqual(result['corpus_sha256'], external_sha256)
            self.assertTrue(result['all_started_workers_joined'])
            self.assertTrue(result['cleanup_completed'])
            self.assertFalse(result['production_equivalent'])
            self.assertFalse(result['full_market_speed_proven'])
            self.assertFalse(result['acceptance_passed'])
            self.assertEqual(corpus.path.read_bytes(), original_corpus_bytes)
            for lane in ('pump', 'pons'):
                outcome = result['lanes'][lane]
                self.assertEqual(outcome['state'], 'REPLAY_COMPLETED_INPUTS', outcome)
                self.assertEqual(outcome['replayed_events'], 1)
                self.assertTrue(outcome['projection_closed'])

            pump = result['lanes']['pump']
            self.assertEqual(pump['projection']['logical_sha256'], baseline_pump['logical_sha256'])
            self.assertEqual(pump['projection']['captured_block_digest'],
                             baseline_pump['captured_block_digest'])
            self.assertEqual(pump['projection']['counts'], baseline_pump['counts'])
            self.assertEqual(pump['projection']['counts']['events'], expected_pump_events)
            self.assertEqual(pump['restoration']['logical_sha256'], baseline_pump['logical_sha256'])
            self.assertTrue(pump['restoration']['economic_history_unchanged'])
            self.assertEqual(pump['restoration']['authenticated_history_events'], expected_pump_events)
            self.assertEqual(pump['restoration']['restored_created_candidates'],
                             baseline_pump_restore['restored_created_candidates'])
            self.assertFalse(pump['projection']['funding_authority'])

            pons = result['lanes']['pons']
            for snapshot in (pons['projection'], pons['restoration']):
                self.assertEqual(snapshot['economic_corpus_sha256'],
                                 baseline_pons['economic_corpus_sha256'])
                self.assertEqual(snapshot['durable_economic_events'], 1)
                self.assertEqual(snapshot['native_candidates']['unique_candidates'], 1)
                self.assertEqual(snapshot['pending_native_candidates'],
                                 baseline_pons['pending_native_candidates'])
                self.assertFalse(snapshot['allocation_authority'])
                self.assertFalse(snapshot['canonical_completeness'])
            self.assertEqual(pons['restoration']['history_reads_this_process'],
                             baseline_pons_restore['history_reads_this_process'])
            self.assertEqual(pons['restoration']['decoded_cursor'], pons_block)
            with sqlite3.connect('file:'+str(replay_root/'pons/candidates.sqlite')+'?mode=ro',
                                 uri=True) as db:
                replayed = json.loads(db.execute('SELECT body FROM evidence WHERE namespace=?',
                                                (NAMESPACE,)).fetchone()[0])
                self.assertEqual(replayed['raw_event']['observed_at'], int(pons_seen))
                self.assertEqual(replayed['raw_event']['event_at'],
                                 int(pons_fixture['header']['timestamp'],16))


if __name__ == '__main__':
    unittest.main()
