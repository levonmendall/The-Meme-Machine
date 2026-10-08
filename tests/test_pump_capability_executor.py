"""Offline only: authentic logs/indices, explicitly SYNTHETIC native envelopes.

Constructed metadata and wire bodies exercise mechanics, never provider payload
size or admission. No economic fixture or production expectation is rewritten.
"""
import asyncio
from dataclasses import replace
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

import based58
import grpc

from engineering.solana_capacity.capability_limits import Budget, CapabilityStop, Limits, MIB
from engineering.solana_capacity.capability_limits import tree_bytes, MAX_STORAGE_ENTRIES
from engineering.solana_capacity.credential_reconciliation import APP_IDS, reconcile
from engineering.solana_capacity.capability_evidence import ADDRESSES, LABELS, PairedEvidence
from engineering.solana_capacity.capability_executor import (CaptureMeter, Executor, HTTPBoundary,
    NativeCall, NativeChannel, NoRedirect, offline_plan, supervise, supervisor_reason,
    validate_headroom, validate_requests, write_receipt)
from engineering.solana_capacity.offline_replay import frames
from meme_machine.solana_candidate_join import CandidateTransactionJoin
from meme_machine.solana_evidence_plane import EvidenceUnavailable
from meme_machine.solana_provider_config import AlchemyEndpoint, GENESIS
from meme_machine.solana_selective_history import PROGRAMS
from meme_machine.yellowstone import geyser_pb2 as pb

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT/'tests/fixtures/solana_selective_cohort.json').read_text())
NOW = 1791400000.0
CONFIG = AlchemyEndpoint.parse('https://solana-mainnet.g.alchemy.com/v2/offline-fixture-key')


def status(tx, family, *, failed=False):
    label = next(k for k, f in LABELS.items() if f == family)
    u = pb.SubscribeUpdate(filters=[label])
    s = u.transaction_status
    s.slot, s.index = tx['slot'], tx['transactionIndex']
    s.signature = based58.b58decode(tx['transaction']['signatures'][0].encode())
    s.bank_id = 123
    if failed:
        s.err.err = struct.pack('<I', 7)
    return u


def full_body(tx, *, alt=False):
    """Synthetic envelope around unchanged authentic logs/signature/index."""
    u = pb.SubscribeUpdate(filters=['t'])
    u.transaction.slot = tx['slot']
    s = u.transaction.transaction
    s.index = tx['transactionIndex']
    s.signature = based58.b58decode(tx['transaction']['signatures'][0].encode())
    s.transaction.signatures.append(s.signature)
    s.transaction.message.account_keys.extend(based58.b58decode(k.encode()) for k in tx['transaction']['message']['accountKeys'])
    for field, source in (('loaded_writable_addresses', 'writable'), ('loaded_readonly_addresses', 'readonly')):
        getattr(s.meta, field).extend(based58.b58decode(k.encode()) for k in tx['meta'].get('loadedAddresses', {}).get(source, []))
    if alt:
        key = based58.b58decode(PROGRAMS['pumpswap'].encode())
        keys = s.transaction.message.account_keys
        keys[:] = [k for k in keys if k != key]
        s.meta.loaded_readonly_addresses.append(key)
    s.meta.log_messages.extend(tx['meta']['logMessages'])
    u.created_at.seconds = int(NOW)
    return u


def headers(slot, parent, count=2000):
    meta = pb.SubscribeUpdate(filters=['b'])
    meta.block_meta.slot, meta.block_meta.parent_slot = slot, parent
    meta.block_meta.blockhash, meta.block_meta.parent_blockhash = 'hash-'+str(slot), 'hash-'+str(parent)
    meta.block_meta.block_time.timestamp = int(NOW)
    meta.block_meta.executed_transaction_count = count
    final = pb.SubscribeUpdate(filters=['f'])
    final.slot.slot, final.slot.parent, final.slot.status = slot, parent, pb.SLOT_FINALIZED
    return meta, final


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        self.now = [0.0]
    def tearDown(self):
        self.tmp.cleanup()
    def budget(self, **changes):
        return Budget(self.out, limits=replace(Limits(), **changes), clock=lambda: self.now[0])

    def test_each_initiation_and_write_limit_stops_before_an_extra_attempt(self):
        for name in ('channels', 'native_rpcs', 'ws_connections', 'native_writes',
                     'ping_writes', 'ws_subscribes', 'ws_unsubscribes'):
            with self.subTest(resource=name):
                b = self.budget()
                for _ in range(getattr(b.limits, name)):
                    b.claim(name)
                with self.assertRaisesRegex(CapabilityStop, name+'_bound'):
                    b.claim(name)
                self.assertEqual(b.counts[name], getattr(b.limits, name))
                self.assertTrue(b.stop.is_set())

    def test_physical_method_budget_independent_of_stream_message_counts(self):
        b = self.budget(physical_methods=1)
        b.claim('native_rpcs', physical=True)
        with self.assertRaisesRegex(CapabilityStop, 'physical_methods_bound'):
            b.claim('ws_subscribes', physical=True)
        self.assertEqual(b.counts['ws_subscribes'], 0)

    def test_http_methods_counts_and_cu_are_independently_bounded(self):
        b = self.budget()
        b.http('getGenesisHash', [])
        for _ in range(4):
            b.http('getSlot', [{'commitment': 'finalized'}])
        self.assertEqual((b.counts['http_requests'], b.counts['http_cu']), (5, 90))
        with self.assertRaisesRegex(CapabilityStop, 'http_requests_bound'):
            b.http('getSlot', [{'commitment': 'finalized'}])
        with self.assertRaisesRegex(CapabilityStop, 'http_cu_bound'):
            self.budget(http_cu=19).http('getSlot', [{'commitment': 'finalized'}])
        b = self.budget()
        b.http('getGenesisHash', [])
        with self.assertRaisesRegex(CapabilityStop, 'http_method_count_bound'):
            b.http('getGenesisHash', [])
        for method, params in (('getTransaction', ['x']), ('getSlot', []), ('getBlock', [])):
            with self.assertRaisesRegex(CapabilityStop, 'http_method_or_params_forbidden'):
                self.budget().http(method, params)

    def test_stopping_frame_and_trailing_frames_are_charged_and_preserved(self):
        b = self.budget(receive_stop=8, stopping_ceiling=12, frame_bytes=8, cancellation_reserve=8)
        captured = []
        capture = lambda raw, size, trailing: captured.append((raw, size, trailing))
        b.receive('websocket', b'1234567', capture)
        with self.assertRaisesRegex(CapabilityStop, 'received_byte_stop_threshold'):
            b.receive('yellowstone', b'12345', capture)
        b.receive('websocket', b'12345678', capture)
        with self.assertRaisesRegex(CapabilityStop, 'cancellation_reserve_bound'):
            b.receive('yellowstone', b'X', capture)
        self.assertEqual(b.bytes['total_application'], 21)
        self.assertEqual(captured[-1], (b'X', 1, True))
        self.assertEqual(b.stopping_bytes, 12)

    def test_stopping_ceiling_oversize_record_count_and_ws_cu(self):
        b = self.budget(receive_stop=8, stopping_ceiling=9, frame_bytes=8)
        b.receive('websocket', b'1234567', lambda *a: None)
        with self.assertRaisesRegex(CapabilityStop, 'stopping_frame_ceiling'):
            b.receive('websocket', b'1234567', lambda *a: None)
        captured = []
        b = self.budget(frame_bytes=8)
        with self.assertRaisesRegex(CapabilityStop, 'frame_bytes_bound'):
            b.receive('yellowstone', b'x'*9, lambda *a: captured.append(a))
        self.assertEqual(captured, [(None, 9, False)])
        self.assertEqual(b.bytes['yellowstone'], 9)
        b = self.budget(records=1)
        b.receive('http', b'1', lambda *a: None)
        with self.assertRaisesRegex(CapabilityStop, 'record_count_bound'):
            b.receive('http', b'2', lambda *a: None)
        b = self.budget()
        b.bytes['websocket'] = 26844*5000
        b.stop.set()
        with self.assertRaisesRegex(CapabilityStop, 'ws_cu_reserve_bound'):
            b.receive('websocket', b'1', lambda *a: None)

    def test_memory_storage_wall_and_shutdown_are_independent(self):
        for kwargs, expected in ((dict(rss=513*MIB, storage=0), 'rss_budget'),
                                 (dict(rss=0, storage=257*MIB), 'storage_hard_budget'),
                                 (dict(rss=0, storage=224*MIB), 'storage_stop_threshold')):
            with self.assertRaisesRegex(CapabilityStop, expected):
                self.budget().resources(**kwargs)
        b = self.budget()
        self.now[0] = 60
        with self.assertRaisesRegex(CapabilityStop, 'wall_deadline'):
            b.resources(rss=0, storage=0)
        self.now[0] = 62.01
        with self.assertRaisesRegex(CapabilityStop, 'shutdown_deadline'):
            b.resources(rss=0, storage=0, shutdown=True)

    def test_limit_increases_and_post_stop_requests_are_rejected(self):
        for change in (dict(wall_seconds=61), dict(native_rpcs=4), dict(receive_stop=49*MIB), dict(rss_bytes=513*MIB),
                       dict(channels=0.5), dict(frame_bytes=True), dict(wall_seconds=float('nan'))):
            with self.assertRaisesRegex(ValueError, 'capability_limit_enlargement'):
                replace(Limits(), **change)
        b = self.budget()
        b.shutdown()
        with self.assertRaisesRegex(CapabilityStop, 'request_after_stop'):
            b.claim('native_rpcs')

    def test_supervisor_independent_limits_and_actual_stuck_process_shutdown(self):
        self.assertEqual(supervisor_reason(60, 0, 0), 'supervisor_wall_deadline')
        self.assertEqual(supervisor_reason(0, 513*MIB, 0), 'supervisor_rss_budget')
        self.assertEqual(supervisor_reason(0, 0, 224*MIB), 'supervisor_storage_stop_threshold')
        command = [sys.executable, '-c', 'import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(30)']
        receipt = supervise(command, self.out, limits=replace(Limits(), wall_seconds=0.3, paired_seconds=0.2, shutdown_seconds=0.1))
        self.assertTrue(receipt['hard_kill'])
        self.assertLess(receipt['wall_seconds'], 1)
        self.assertFalse(receipt['shutdown_deadline_exceeded'])
        self.assertEqual(receipt['application_bytes_not_observable_after_forced_kill'], 'UNKNOWN')

    def test_supervisor_detects_actual_memory_and_disk_pressure(self):
        for label, code, changes, expected in (
            ('memory', 'import time; x=bytearray(48*1024*1024); time.sleep(30)',
             dict(rss_bytes=32*MIB), 'supervisor_rss_budget'),
            ('disk', 'from pathlib import Path; import time; Path("payload").write_bytes(b"x"*131072); time.sleep(30)',
             dict(storage_stop=65536, storage_bytes=524288), 'supervisor_storage_stop_threshold')):
            with self.subTest(case=label):
                out = self.out/label
                out.mkdir()
                if label == 'disk':
                    code = 'import os; os.chdir('+repr(str(out))+'); '+code
                r = supervise([sys.executable, '-c', code], out,
                    limits=replace(Limits(), wall_seconds=2, paired_seconds=1, shutdown_seconds=0.2, **changes))
                self.assertEqual(r['reason'], expected)
                self.assertLess(r['wall_seconds'], 1)

    def test_total_observed_ceiling_is_independent_and_new_requests_cannot_follow_deadline(self):
        b = self.budget()
        b.stop.set()
        b.bytes['streaming'] = 128*MIB
        with self.assertRaisesRegex(CapabilityStop, 'observed_payload_ceiling'):
            b.receive('yellowstone', b'1', lambda *a: None)
        for claim in (lambda b: b.claim('channels'), lambda b: b.http('getGenesisHash', [])):
            self.now[0] = 0
            b = self.budget()
            self.now[0] = 60
            with self.assertRaisesRegex(CapabilityStop, 'wall_deadline'):
                claim(b)

    def test_storage_inventory_and_symlinks_fail_explicitly_and_supervisor_stops_child(self):
        for n in range(MAX_STORAGE_ENTRIES+1):
            (self.out/str(n)).touch()
        with self.assertRaisesRegex(CapabilityStop, 'storage_inventory_bound'):
            tree_bytes(self.out)
        for path in self.out.iterdir():
            path.unlink()
        (self.out/'link').symlink_to(self.out/'missing')
        with self.assertRaisesRegex(CapabilityStop, 'disposable_storage_symlink'):
            tree_bytes(self.out)
        receipt = supervise([sys.executable, '-c', 'import time; time.sleep(30)'], self.out,
                            limits=replace(Limits(), wall_seconds=2, paired_seconds=1, shutdown_seconds=0.2))
        self.assertEqual(receipt['reason'], 'disposable_storage_symlink')
        self.assertIsNotNone(receipt['exit_code'])
        self.assertLess(receipt['wall_seconds'], 1)

    def test_report_size_limit_rejects_before_creating_an_oversized_receipt(self):
        target = self.out/'result.json'
        with self.assertRaisesRegex(CapabilityStop, 'receipt_size_bound'):
            write_receipt(target, {'oversized': 'x'*MIB})
        self.assertFalse(target.exists())

    def test_paired_measurement_cutoff_charges_transition_and_shutdown_overlap(self):
        b = self.budget()
        meter = CaptureMeter(self.out/'raw.zlib', b)
        for phase, at, trailing in (('paired',44.99,False), ('transition',45,False), ('shutdown',45,True)):
            self.now[0] = at
            meter.capture('one','pumpswap','yellowstone',b'X',1,trailing,NOW,at)
            self.assertEqual(meter.phase_bytes[phase,'yellowstone','pumpswap'],1)
        meter.close()


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {'MM_OPERATIONAL_PHASE': 'BOUNDED_PUMP_CAPABILITY'})
        self.env.start()
        self.budget = Budget(self.out)
        self.pair = PairedEvidence(self.out, CONFIG.identity, self.budget, mono=lambda: 0.0)
        self.lo = FIXTURE['pumpswap'][0]['slot']
        self.pair.start(self.lo, self.lo, self.lo)
    def tearDown(self):
        self.pair.close()
        self.env.stop()
        self.tmp.cleanup()
    def native(self, u, family='pumpswap', seen=NOW):
        self.pair.native(family, u, u.ByteSize(), seen)
    def logs(self, tx, family, seen=NOW, error=None):
        self.pair.ws(family, tx['slot'], tx['transaction']['signatures'][0], tx['meta']['logMessages'], error, 100, seen)

    def corpus(self):
        selected = [('pumpswap', tx) for tx in FIXTURE['pumpswap']] + [('pump', FIXTURE['pump'][0])]
        by_slot = {}
        for family, tx in selected:
            by_slot.setdefault(tx['slot'], []).append((family, tx))
        slots = [self.lo, self.lo+1, self.lo+2, FIXTURE['pump'][0]['slot'], FIXTURE['pump'][0]['slot']+1]
        parent = self.lo-1
        for slot in slots:
            for family, tx in by_slot.get(slot, []):
                self.logs(tx, family)
                self.native(status(tx, family))
                if family == 'pumpswap':
                    self.native(full_body(tx))
            for u in headers(slot, parent):
                self.native(u, 'shared')
                self.native(u)
            parent = slot

    def test_authentic_logs_and_true_indices_match_in_both_durable_owners(self):
        self.corpus()
        result = self.pair.compare()
        self.assertTrue(result['complete'], result['reasons'])
        self.assertGreaterEqual(len(result['common_intervals']), 3)
        self.assertEqual(result['reference'], result['alternative'])
        rows = list(self.pair.reference.writer.db.execute('SELECT signature,transaction_index,event_index FROM canonical_evidence ORDER BY 1,2,3'))
        # Independent decoder-derived oracle, not a copy of executor output.
        from meme_machine.solana_program_decoders import pump_events, pumpswap_trade_events
        expected = []
        for family, decoder, txs in (('pump', pump_events, FIXTURE['pump'][:1]), ('pumpswap', pumpswap_trade_events, FIXTURE['pumpswap'])):
            for tx in txs:
                expected.extend((tx['transaction']['signatures'][0], tx['transactionIndex'], e['index']) for e in decoder(tx))
        self.assertEqual(rows, sorted(expected))
        report = self.pair.traffic_report(result)
        self.assertEqual(report['verified_provider_savings_bytes'], 0)
        self.assertGreater(report['mean_full_native_success_bytes'], 0)

    def test_native_body_cannot_replace_status_and_missing_body_cannot_close(self):
        tx = FIXTURE['pumpswap'][0]
        self.logs(tx, 'pumpswap')
        self.native(full_body(tx))
        with self.assertRaisesRegex(EvidenceUnavailable, 'yellowstone_unfiltered_transaction'):
            for u in headers(tx['slot'], tx['slot']-1):
                self.native(u)

    def test_missing_body_and_late_status_remain_incomplete_until_original_fact_arrives(self):
        tx = FIXTURE['pumpswap'][0]
        self.logs(tx, 'pumpswap')
        self.native(status(tx, 'pumpswap'))
        for u in headers(tx['slot'], tx['slot']-1):
            self.native(u)
        self.assertEqual(self.pair.alternative.join.completed, -1)
        self.assertFalse(self.pair.compare()['complete'])
        self.native(full_body(tx))
        self.assertEqual(self.pair.alternative.join.completed, tx['slot'])

    def test_failed_identity_is_retained_but_no_failed_economics_are_committed(self):
        tx = FIXTURE['pumpswap'][0]
        self.logs(tx, 'pumpswap', error='BlockhashNotFound')
        self.native(status(tx, 'pumpswap', failed=True))
        for u in headers(tx['slot'], tx['slot']-1):
            self.native(u)
        for side in (self.pair.reference, self.pair.alternative):
            self.assertEqual(side.writer.db.execute('SELECT COUNT(*) FROM canonical_evidence').fetchone()[0], 0)
            self.assertEqual(json.loads(side.writer.db.execute('SELECT error FROM capability_witnesses').fetchone()[0]), 'BlockhashNotFound')

    def test_contradictory_error_index_logs_and_late_negative_witness_stop(self):
        tx = FIXTURE['pumpswap'][0]
        self.logs(tx, 'pumpswap')
        with self.assertRaisesRegex(CapabilityStop, 'ws_status_contradiction'):
            self.native(status(tx, 'pumpswap', failed=True))

    def test_alt_membership_is_checked_and_full_body_index_conflict_stops(self):
        tx = FIXTURE['pumpswap'][0]
        self.logs(tx, 'pumpswap')
        self.native(status(tx, 'pumpswap'))
        body = full_body(tx, alt=True)
        self.native(body)
        body.transaction.transaction.index += 1
        with self.assertRaisesRegex(CapabilityStop, 'bodies_identity_contradiction'):
            self.native(body)

    def test_original_receipt_clocks_are_not_retimed_for_parity(self):
        self.corpus()
        # A durable timestamp change must break the exact frozen comparison.
        self.pair.alternative.writer.db.execute('UPDATE candidate_lifecycle SET first_seen=first_seen+1')
        result = self.pair.compare()
        self.assertFalse(result['complete'])
        self.assertIn('candidate_lifecycle', result['differing_projections'])

    def test_independent_late_failure_and_body_log_contradictions_are_not_discarded(self):
        tx = FIXTURE['pumpswap'][0]
        self.logs(tx, 'pumpswap')
        self.native(status(tx, 'pumpswap'))
        u = full_body(tx)
        u.transaction.transaction.meta.log_messages.append('unexpected native economic log')
        with self.assertRaisesRegex(CapabilityStop, 'ws_body_contradiction'):
            self.native(u)

    def test_join_actual_32_mib_and_256_slot_limits_are_preserved(self):
        from meme_machine.solana_candidate_join import MAX_PENDING_BYTES, MAX_PENDING_SLOTS
        self.assertEqual((MAX_PENDING_BYTES, MAX_PENDING_SLOTS), (32*MIB, 256))
        j = CandidateTransactionJoin(ADDRESSES, set(), filtered_from_slot=1, clock=lambda: 0)
        u = headers(2, 1)[0]
        j.feed(u, 16*MIB, NOW)
        u = headers(3, 2)[0]
        j.feed(u, 16*MIB, NOW)
        with self.assertRaisesRegex(EvidenceUnavailable, 'yellowstone_census_buffer_bound'):
            j.feed(u, 1, NOW)
        j = CandidateTransactionJoin(ADDRESSES, set(), filtered_from_slot=1, clock=lambda: 0)
        with self.assertRaisesRegex(EvidenceUnavailable, 'yellowstone_census_buffer_bound'):
            for slot in range(1, 258):
                u = headers(slot, max(1, slot-1))[0]
                j.feed(u, u.ByteSize(), NOW)


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_read_is_metered_before_malformed_decode_and_cancels(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            meter, budget = CaptureMeter(out/'raw.zlib'), Budget(out)
            class Call:
                async def read(self): return b'malformed-provider-protobuf'
                def cancel(self): self.cancelled = True
            raw_call = Call()
            call = NativeCall(raw_call, budget, meter, 'one', 'pumpswap', pb.SubscribeRequest())
            raw = await call.read()
            with self.assertRaises(Exception): pb.SubscribeUpdate.FromString(raw)
            call.cancel()
            meter.close()
            self.assertEqual(list(frames(out/'raw.zlib'))[0][1], raw)
            self.assertEqual(budget.bytes['yellowstone'], len(raw))
            self.assertTrue(raw_call.cancelled)

    async def test_native_one_read_and_ping_and_rebuild_are_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            meter, budget = CaptureMeter(out/'raw.zlib'), Budget(out, limits=replace(Limits(), ping_writes=1))
            event = asyncio.Event()
            class Call:
                async def read(self): await event.wait(); return grpc.aio.EOF
                async def write(self, request): pass
                def cancel(self): pass
            expected = pb.SubscribeRequest(commitment=pb.FINALIZED)
            call = NativeCall(Call(), budget, meter, 'one', 'pump', expected)
            await call.write(expected)
            pending = asyncio.create_task(call.read())
            await asyncio.sleep(0)
            with self.assertRaisesRegex(CapabilityStop, 'native_outstanding_read_bound'):
                await call.read()
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
            meter.close()
            budget = Budget(out, limits=replace(Limits(), ping_writes=1))
            call = NativeCall(Call(), budget, None, 'one', 'pump', expected)
            await call.write(expected)
            await call.write(pb.SubscribeRequest(ping=pb.SubscribeRequestPing(id=1)))
            with self.assertRaisesRegex(CapabilityStop, 'ping_writes_bound'):
                await call.write(pb.SubscribeRequest(ping=pb.SubscribeRequestPing(id=1)))
            budget = Budget(out)
            call = NativeCall(Call(), budget, None, 'one', 'pump', expected)
            await call.write(expected)
            with self.assertRaisesRegex(CapabilityStop, 'filter_rebuild_forbidden'):
                await call.write(expected)


class BoundaryTests(unittest.TestCase):
    def test_default_cli_and_request_validation_open_no_network(self):
        with patch('grpc.aio.secure_channel', side_effect=AssertionError('network')), patch('urllib.request.urlopen', side_effect=AssertionError('network')):
            self.assertEqual(offline_plan()['provider_calls'], 0)
            with patch.dict(os.environ, {'MM_OPERATIONAL_PHASE': 'BOUNDED_PUMP_CAPABILITY'}):
                req = validate_requests(123, 150)
            self.assertEqual(set(req['pump'].accounts), {'p'})
            tx = req['pumpswap'].transactions['t']
            self.assertTrue(tx.HasField('failed'))
            self.assertFalse(tx.failed)
            self.assertTrue(all(not s.HasField('failed') for s in req['pumpswap'].transactions_status.values()))
            encoded = req['pumpswap'].SerializeToString()
            self.assertEqual(pb.SubscribeRequest.FromString(encoded), req['pumpswap'])
        from engineering.solana_capacity.capability_executor import main
        with patch('pathlib.Path.read_text', side_effect=AssertionError('credential read')), \
                patch('pathlib.Path.read_bytes', side_effect=AssertionError('file read')), \
                patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(main(['--env-file', '/nonexistent/credentials']), 0)
            self.assertEqual(json.loads(output.getvalue())['provider_calls'], 0)
        with patch('grpc.aio.secure_channel', side_effect=AssertionError('network')):
            with self.assertRaises(SystemExit): main(['--execute-provider-experiment'])

    def test_headroom_is_identity_topology_time_and_authorization_specific(self):
        receipt = dict(endpoint_identity=CONFIG.identity, authorization_reference='explicit-next-turn',
                       app_id=APP_IDS['pump'], credential_app_binding_verified=True,
                       additional_experiment_topology=dict(native_channels=1,native_subscribe_rpcs=3,websocket_connections=1,websocket_subscriptions=2,candidate_filters=5),
                       headroom_verified=True, production_changes_required=False, checked_at=NOW, expires_at=NOW+60)
        validate_headroom(receipt, CONFIG.identity, 'explicit-next-turn', now=lambda: NOW)
        for changed in ({'headroom_verified':False}, {'expires_at':NOW}, {'endpoint_identity':'wrong'}, {'production_changes_required':True},
                        {'app_id':APP_IDS['pons']}, {'credential_app_binding_verified':False}):
            with self.assertRaisesRegex(CapabilityStop, 'current_account_headroom_required'):
                validate_headroom(dict(receipt, **changed), CONFIG.identity, 'explicit-next-turn', now=lambda: NOW)

    def test_http_byte_meter_rejects_redirects_batches_and_unplanned_endpoints(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            meter, budget = CaptureMeter(out/'raw.zlib'), Budget(out)
            class Opener:
                calls = 0
                def open(self, request, **options):
                    self.calls += 1
                    return io.BytesIO(b'{"jsonrpc":"2.0","id":1,"result":123}')
            opener = Opener()
            boundary = HTTPBoundary(CONFIG, budget, meter, opener)
            body = dict(jsonrpc='2.0', id=1, method='getSlot', params=[dict(commitment='finalized')])
            with boundary.open(urllib.request.Request(CONFIG.http_url, json.dumps(body).encode())) as response:
                raw = response.read(16*MIB+1)
            self.assertEqual(budget.bytes['http'], len(raw))
            self.assertEqual(opener.calls, 1)
            with self.assertRaisesRegex(CapabilityStop, 'http_batch_or_envelope_forbidden'):
                boundary.open(urllib.request.Request(CONFIG.http_url, json.dumps([body]).encode()))
            with self.assertRaisesRegex(CapabilityStop, 'http_redirect_forbidden'):
                NoRedirect().redirect_request(None,None,302,None,None,'https://example.invalid')
            meter.close()

    def test_http_errors_and_response_overruns_are_metered_without_retries(self):
        for case in ('oversize_chunk', 'oversize_response', 'admission_error'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp)
                budget = Budget(out, limits=replace(Limits(), frame_bytes=8))
                meter = CaptureMeter(out/'raw.zlib')
                class Opener:
                    calls = 0
                    def open(self, request, **options):
                        self.calls += 1
                        if case == 'admission_error':
                            raise urllib.error.HTTPError(request.full_url, 429, 'admission', {}, io.BytesIO(b'error'))
                        class Chunks(io.BytesIO):
                            def read(self, n):
                                return super().read(min(n, 2))
                        return (Chunks if case == 'oversize_response' else io.BytesIO)(b'123456789')
                opener = Opener()
                boundary = HTTPBoundary(CONFIG, budget, meter, opener)
                body = dict(jsonrpc='2.0', id=1, method='getGenesisHash', params=[])
                expected = {'admission_error':'http_admission_or_transport_error',
                            'oversize_response':'http_response_frame_bound', 'oversize_chunk':'frame_bytes_bound'}[case]
                with self.assertRaisesRegex(CapabilityStop, expected):
                    with boundary.open(urllib.request.Request(CONFIG.http_url, json.dumps(body).encode())) as response:
                        response.read(9)
                self.assertEqual(opener.calls, 1)
                self.assertEqual(budget.bytes['http'], 5 if case == 'admission_error' else 9)
                meter.close()

    def test_credentials_are_compared_without_emitting_keys_paths_or_suffixes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'credentials.env'
            pump_key, pons_key = 'secret-pump-ZYX1', 'secret-pons-WVU2'
            path.write_text('MM_SOLANA_READ_RPC_URL="https://solana-mainnet.g.alchemy.com/v2/'+pump_key+'"\n'
                            'MM_ROBINHOOD_READ_RPC_URL="https://robinhood-mainnet.g.alchemy.com/v2/'+pons_key+'"\n'
                            'MM_SOLANA_YELLOWSTONE_TOKEN='+pump_key+'\n')
            result = reconcile(path, {APP_IDS['pump']:pump_key[-4:], APP_IDS['pons']:pons_key[-4:]})
            self.assertTrue(result['native_pump_token_matches_configured_pump_key'])
            self.assertTrue(result['pump_and_pons_keys_distinct'])
            self.assertTrue(all(r['admin_suffix_match'] for r in result['roles'].values()))
            self.assertTrue(all(r['endpoint_role_matches'] for r in result['roles'].values()))
            public = json.dumps(result)
            for secret in (pump_key, pons_key, pump_key[-4:], pons_key[-4:], '/v2/'):
                self.assertNotIn(secret, public)
            wrong = reconcile(path, {APP_IDS['pump']:'XXXX'})
            self.assertEqual(wrong['roles']['pump']['app_binding'], 'MASKED_SUFFIX_MISMATCH')
            self.assertIsNone(wrong['roles']['pons']['admin_suffix_match'])
            with self.assertRaisesRegex(ValueError, 'four_character_admin_suffix_required'):
                reconcile(path, {APP_IDS['pump']:pump_key})

    def test_live_clock_cannot_be_replaced_with_a_synthetic_phase_clock(self):
        with self.assertRaisesRegex(CapabilityStop, 'live_clock_override_forbidden'):
            Executor(Path('unopened'), CONFIG, None, None, live=True, clock=lambda: 0.0)

    def test_invalid_or_foreign_endpoints_cannot_pass_credential_role_reconciliation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'credentials.env'
            for url in ('https://solana-mainnet.g.alchemy.com:1234/v2/secretXYZ1',
                        'https://robinhood-mainnet.g.alchemy.com/v2/secretXYZ1',
                        'https://solana-mainnet.g.alchemy.com/v2/secretXYZ1/extra'):
                path.write_text('MM_SOLANA_READ_RPC_URL='+url+'\n')
                r = reconcile(path, {APP_IDS['pump']:'XYZ1'})['roles']['pump']
                self.assertFalse(r['endpoint_role_matches'])
                self.assertFalse(r['admin_suffix_match'])
                self.assertIsNone(r['endpoint_identity_sha256'])


class FiniteHarness:
    """One fake WS and one fake channel, using the actual finite orchestration."""
    def __init__(self, *, admitted=True, native_rejected=False, close_stalls=False):
        self.admitted = admitted
        self.native_rejected = native_rejected
        self.close_stalls = close_stalls
        self.calls = {}
        self.ws_messages = asyncio.Queue(maxsize=64)
        self.ws_writes = []
        self.connect_options = None
        self.channel_closed = False
        self.acquire_count = 0
        self.http_count = 0
        self.unsubscribed = False
        self.ack_received = False
        self.tail_received = False
        self.tip = FIXTURE['pumpswap'][0]['slot']
        self.last = FIXTURE['pump'][0]['slot']+1

    def acquire(self, *args, **kwargs): self.acquire_count += 1
    def succeeded(self, *args): pass
    def rate_limited(self, *args): pass

    def open(self, request, **options):
        self.http_count += 1
        method = json.loads(request.data)['method']
        return io.BytesIO(json.dumps(dict(jsonrpc='2.0', id=1, result=GENESIS if method=='getGenesisHash' else self.tip)).encode())

    def queue(self, value): self.ws_messages.put_nowait(json.dumps(value))

    def clock(self):
        # Deterministic phase clock for synthetic transports. The live executor
        # rejects clock injection and keeps the independent real-time supervisor.
        drained = all(f in self.calls and self.calls[f].drained for f in ('shared','pumpswap'))
        if self.unsubscribed:
            return 3.0 if drained and self.ack_received and self.tail_received and self.http_count==5 else 2.0
        return 2.0 if drained else 0.0

    def log(self, tx, family):
        return dict(jsonrpc='2.0', method='logsNotification', params=dict(subscription=10 if family=='pump' else 20,
            result=dict(context=dict(slot=tx['slot']), value=dict(signature=tx['transaction']['signatures'][0],err=None,logs=tx['meta']['logMessages']))))

    def ws_connect(self, url, **options):
        self.connect_options = options
        harness = self
        class WS:
            async def __aenter__(self): return self
            async def __aexit__(self, *exc): pass
            async def send(self, raw):
                request = json.loads(raw)
                harness.ws_writes.append(request)
                number = request['id']
                if number in (1,2):
                    if harness.admitted:
                        harness.queue(dict(jsonrpc='2.0', id=number, result=number*10))
                        # Partial startup slots cannot establish coverage.
                        prefix = dict(slot=harness.tip-1, transaction=dict(signatures=['1'*64]), meta=dict(logMessages=[]))
                        harness.queue(harness.log(prefix, 'pump' if number==1 else 'pumpswap'))
                    else:
                        harness.queue(dict(jsonrpc='2.0', id=number, error=dict(code=429)))
                    if number == 2 and harness.admitted:
                        for tx in FIXTURE['pumpswap']:
                            harness.queue(harness.log(tx, 'pumpswap'))
                        harness.queue(harness.log(FIXTURE['pump'][0], 'pump'))
                else:
                    harness.unsubscribed = True
                    harness.queue(dict(jsonrpc='2.0', id=3, result=True))
                    # Meter the genuine trailing original notification after ACK.
                    harness.queue(harness.log(FIXTURE['pumpswap'][0], 'pumpswap'))
                    harness.continuation()
            async def recv(self):
                raw = await harness.ws_messages.get()
                value = json.loads(raw)
                if value.get('id') == 3:
                    harness.ack_received = True
                elif harness.unsubscribed and 'params' in value:
                    harness.tail_received = True
                return raw
            async def close(self):
                if harness.close_stalls:
                    await asyncio.Event().wait()
        return WS()

    def initial(self, family):
        out = []
        if family == 'pump':
            ping = pb.SubscribeUpdate()
            ping.ping.SetInParent()
            return [ping]
        by_slot = {self.tip:[('pumpswap',tx) for tx in FIXTURE['pumpswap']],
                   FIXTURE['pump'][0]['slot']:[('pump',FIXTURE['pump'][0])]}
        parent = self.tip-1
        for slot in (self.tip, self.tip+1, self.tip+2, FIXTURE['pump'][0]['slot'], self.last):
            if family == 'pumpswap':
                for f, tx in by_slot.get(slot, []):
                    out.append(status(tx, f))
                    if f == 'pumpswap': out.append(full_body(tx))
            out.extend(headers(slot, parent))
            parent = slot
        return out

    def continuation(self):
        # Explicitly synthetic identities/envelopes after suppression, keeping
        # the authentic economic log bytes unchanged. These are never samples
        # of provider size, admission or market activity.
        tx = dict(slot=self.last+1, transactionIndex=0, transaction=dict(signatures=['1'*64]))
        trade = json.loads(json.dumps(FIXTURE['pumpswap'][0]))
        trade['slot'], trade['transactionIndex'] = self.last+1, 1
        trade['transaction']['signatures'] = [based58.b58encode(b'\x01'*64).decode()]
        for family, call in self.calls.items():
            if family == 'pump': continue
            call.drained = False
            if family == 'pumpswap':
                for u in (status(tx, 'pumpswap', failed=True), status(trade, 'pumpswap'), full_body(trade)):
                    call.queue.put_nowait(u.SerializeToString())
            for u in (*headers(self.last+1, self.last), *headers(self.last+2, self.last+1)):
                call.queue.put_nowait(u.SerializeToString())

    def channel_factory(self):
        harness = self
        class Channel:
            def stream_stream(self, method, **options):
                def open_call(**kwargs):
                    class Call:
                        def __init__(self): self.queue=asyncio.Queue(maxsize=64);self.writes=[];self.cancelled=False;self.drained=False
                        async def write(self, request):
                            self.writes.append(request)
                            if request.HasField('ping'): return
                            if harness.native_rejected:
                                raise grpc.aio.AioRpcError(grpc.StatusCode.RESOURCE_EXHAUSTED,
                                    grpc.aio.Metadata(), grpc.aio.Metadata(), 'synthetic provider admission failure')
                            family = 'pump' if request.accounts else 'pumpswap' if request.transactions_status else 'shared'
                            harness.calls[family] = self
                            for u in harness.initial(family): self.queue.put_nowait(u.SerializeToString())
                        async def read(self):
                            if self.queue.empty(): self.drained=True
                            return await self.queue.get()
                        def cancel(self): self.cancelled=True
                    return Call()
                return open_call
            async def close(self, grace=0): harness.channel_closed=True
        return Channel()


class OrchestrationTests(unittest.IsolatedAsyncioTestCase):
    async def run_harness(self, out, harness):
        from meme_machine.runtime.evidence_worker import RepairRPC
        rpc = RepairRPC(CONFIG.http_url, harness)
        executor = Executor(out, CONFIG, harness, rpc, limits=replace(Limits(),wall_seconds=3,paired_seconds=2),
            ws_connect=harness.ws_connect, channel_factory=harness.channel_factory, clock=harness.clock)
        with HTTPBoundary(CONFIG, executor.budget, executor.meter, harness), patch('time.time', return_value=NOW), \
                patch('grpc.aio.secure_channel', side_effect=AssertionError('unexpected provider call')):
            return await executor.execute()

    async def test_full_finite_path_suppresses_only_after_strict_parity_and_closes(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'MM_OPERATIONAL_PHASE':'BOUNDED_PUMP_CAPABILITY'}):
            harness = FiniteHarness()
            report = await self.run_harness(Path(tmp), harness)
            self.assertTrue(report['paired']['complete'], report['budget']['failures'])
            self.assertTrue(report['suppression_acknowledged'])
            self.assertTrue(report['suppression_evidence']['complete'])
            self.assertEqual(report['suppression_evidence']['pumpswap_successes'], 1)
            self.assertEqual(report['suppression_evidence']['pumpswap_failures'], 1)
            self.assertEqual(report['budget']['initiations']['http_requests'], 5)
            self.assertEqual(report['budget']['initiations']['http_cu'], 90)
            self.assertEqual(report['budget']['initiations']['physical_methods'], 11)
            self.assertEqual(report['budget']['initiations']['native_rpcs'], 3)
            self.assertEqual(report['budget']['initiations']['native_cancellations'], 3)
            self.assertEqual(harness.connect_options['max_queue'], 1)
            self.assertEqual(len(harness.ws_writes), 3)
            self.assertEqual(harness.ws_writes[-1]['params'], [20])
            self.assertTrue(harness.channel_closed)
            self.assertTrue(all(call.cancelled for call in harness.calls.values()))
            self.assertEqual(report['verified_provider_savings_bytes'], 0)
            self.assertEqual(report['classification'], 'OFFLINE_SYNTHETIC_TRANSPORT')
            self.assertLess(report['shutdown']['seconds'], 2)
            self.assertEqual(sum(r['bytes'] for r in report['all_received_components']), report['budget']['received_application_bytes']['total_application'])
            self.assertEqual(sum(r['messages'] for r in report['all_received_components']), report['budget']['initiations']['records'])
            self.assertGreater(report['traffic']['paired_streaming_bytes_not_routed_to_evidence'], 0)  # Native heartbeat included.
            self.assertTrue(report['local_decode']['yellowstone.messages'])
            self.assertTrue(report['local_decode']['websocket.messages'])
            clocks = [m for m, _ in frames(Path(tmp)/'provider.frames.zlib') if m['kind']=='collector_delivery_clock']
            self.assertTrue(clocks)
            self.assertTrue(all(m['seen']==NOW for m in clocks))

    async def test_first_admission_error_stops_without_retry_or_second_phase(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'MM_OPERATIONAL_PHASE':'BOUNDED_PUMP_CAPABILITY'}):
            harness = FiniteHarness(admitted=False)
            report = await self.run_harness(Path(tmp), harness)
            self.assertIn('websocket_admission_error', report['budget']['failures'])
            self.assertFalse(report['suppression_attempted'])
            self.assertLessEqual(report['budget']['initiations']['http_requests'], 2)
            self.assertLessEqual(report['budget']['initiations'].get('native_rpcs',0), 2)
            self.assertEqual(report['verified_provider_savings_bytes'], 0)
            self.assertTrue(report['shutdown']['completed'])

    async def test_native_resource_exhaustion_stops_first_attempt_without_reconnect(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'MM_OPERATIONAL_PHASE':'BOUNDED_PUMP_CAPABILITY'}):
            harness = FiniteHarness(native_rejected=True)
            report = await self.run_harness(Path(tmp), harness)
            self.assertIn('native_admission_or_transport_error', report['budget']['failures'])
            self.assertFalse(report['suppression_attempted'])
            self.assertLessEqual(report['budget']['initiations']['native_rpcs'], 2)
            self.assertEqual(report['budget']['initiations']['channels'], 1)
            self.assertTrue(harness.channel_closed)
            self.assertTrue(all(call.cancelled for call in harness.calls.values()))

    async def test_stalled_ws_close_still_cancels_tasks_and_closes_native_channel(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'MM_OPERATIONAL_PHASE':'BOUNDED_PUMP_CAPABILITY'}):
            harness = FiniteHarness(close_stalls=True)
            report = await self.run_harness(Path(tmp), harness)
            self.assertIn('bounded_shutdown_failure', report['budget']['failures'])
            self.assertEqual(report['shutdown']['failed_steps'], ['websocket_close'])
            self.assertLess(report['shutdown']['seconds'], 2)
            self.assertTrue(harness.channel_closed)
            self.assertTrue(all(call.cancelled for call in harness.calls.values()))


if __name__ == '__main__':
    from operational.tests import network_guard
    network_guard()
    unittest.main()
