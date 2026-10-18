"""Real accounting/admission, offline physical I/O, disposable connected IPC."""
import asyncio
import base64
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import socket
import sqlite3
import struct
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import grpc

from meme_machine.operational.bounded_provider import Budget, MAX_FRAME
from meme_machine.operational.transport_bridge import (
    BridgeRejected, EndpointAlias, ParentAttempt, ReadCall, encode_frame,
)
from meme_machine.operational.parent_transport import (
    SourceBinding, SourceReference, NativeSourceBinding, ParentHTTP, ParentNativeStream, ParentTransportFailure,
    authenticated_native_factory, validate_subscription,
)
from meme_machine.operational.parent_channel import ParentChannel, serve_connected
from meme_machine.runtime.governor import Governor
from meme_machine.lanes.pons.provider_admission import Admission

SOL = 'https://solana-mainnet.g.alchemy.com/v2/offline-parent-secret'
PONS = 'https://robinhood-mainnet.g.alchemy.com/v2/offline-parent-secret'


def decoded(frame):
    return json.loads(frame[4:])


class _Raw:
    status = 200

    def __init__(self, body, *, fail_after=None, status=200):
        self.body = io.BytesIO(body)
        self.reads = 0
        self.fail_after = fail_after
        self.closed = False
        self.status = status

    def set_read_deadline(self, deadline):
        self.deadline = deadline

    def read1(self, size):
        self.reads += 1
        if self.fail_after is not None and self.reads > self.fail_after:
            raise OSError('https://offline.invalid/secret-must-not-cross-wire')
        return self.body.read(min(size, 7 if self.fail_after is not None else size))

    def close(self):
        self.closed = True
        self.body.close()


class _Physical:
    def __init__(self, budget):
        self.budget = budget
        self.calls = []
        self.body = None
        self.fail_after = None
        self.status = 200
        self.entered = threading.Event()
        self.gate = threading.Event()
        self.gate.set()
        self.raw = []

    def __call__(self, request, timeout):
        # Real durable quota reservation precedes every fake physical dispatch.
        state = self.budget.snapshot()
        assert int(state['http_reserved']) >= MAX_FRAME
        assert int(state['http_attempts']) >= 1
        calls = json.loads(request.data)
        self.calls.append(calls)
        self.entered.set()
        if not self.gate.wait(timeout):
            raise TimeoutError('offline physical deadline')
        if self.body is None:
            rows = calls if isinstance(calls, list) else [calls]
            reply = [dict(jsonrpc='2.0', id=r['id'], result='0x123') for r in rows]
            body = json.dumps(reply if isinstance(calls, list) else reply[0]).encode()
        else:
            body = self.body
        raw = _Raw(body, fail_after=self.fail_after, status=self.status)
        self.raw.append(raw)
        return raw


class _Native:
    def __init__(self, values=()):
        self.values = asyncio.Queue()
        for value in values:
            self.values.put_nowait(value)
        self.closed = False
        self.writes = []

    async def read(self):
        value = await self.values.get()
        return value if value is grpc.aio.EOF else (len(value), value)

    async def write(self, body):
        self.writes.append(body)

    async def aclose(self):
        self.closed = True


class ParentNativeTransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # This managed worker denies stat(/proc/self/ns/time). Use the existing
        # explicit offline domain fixture, never relax the real clock guard.
        from tests.test_provider_clock_domain import identity
        clock = patch('meme_machine.runtime.provider_clock.current_identity', return_value=identity())
        clock.start()
        self.addCleanup(clock.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.budget = Budget.create(self.root/'usage.sqlite', modeled_spend_limit='3')
        self.governor = Governor(self.root/'governor.sqlite')
        self.admission = Admission(self.root/'pons.sqlite', PONS, lane='pons')
        self.sol = SourceBinding.configured(EndpointAlias('pump', 'solana',
            frozenset(('getSlot', 'getBlock', 'getSignaturesForAddress'))), 'pump_discovery',
            environ={'MM_SOLANA_READ_RPC_URL': SOL}, governor=self.governor)
        self.pons = SourceBinding.configured(EndpointAlias('pons', 'robinhood',
            frozenset(('eth_chainId', 'eth_blockNumber', 'eth_getBlockByHash'))), 'pons_current_qualification',
            environ={'MM_ROBINHOOD_READ_RPC_URL': PONS}, admission=self.admission)
        self.physical = _Physical(self.budget)
        self.http = ParentHTTP(self.budget, [self.sol, self.pons], opener=self.physical)
        self.addAsyncCleanup(self.http.aclose)
        self.counter = 0

    def attempt(self, source=None, calls=None, batch=False):
        source = source or self.sol
        self.counter += 1
        methods = calls or [('getSlot', [])]
        return ParentAttempt('session', str(self.counter), source.alias,
            tuple(ReadCall(m, json.dumps(p).encode()) for m, p in methods), batch,
            time.monotonic()+3)

    async def perform(self, attempt):
        try:
            return await self.http.execute(attempt)
        finally:
            await self.http.release(attempt, uncertain=True)

    async def test_actual_authenticated_identity_no_placeholder_or_secret_wire(self):
        self.assertEqual(self.sol.identity, hashlib.sha256(SOL.encode()).hexdigest())
        self.assertNotIn('offline-parent-secret', repr(self.sol))
        receipt = self.sol.receipt()
        self.assertTrue(receipt['authenticated'])
        self.assertNotIn('offline-parent-secret', json.dumps(receipt))
        reference = SourceReference.from_receipt(receipt)
        self.assertEqual(reference.endpoint_identity, self.sol.identity)
        self.assertFalse(hasattr(reference, '_url'))
        with self.assertRaises(BridgeRejected):
            SourceReference.from_receipt(dict(receipt, credentials='not-allowed'))
        for environ in ({}, {'MM_SOLANA_READ_RPC_URL': 'https://offline.invalid/fake'}):
            with self.assertRaises(ValueError):
                SourceBinding.configured(self.sol.alias, 'pump_discovery', environ=environ,
                                         governor=self.governor)
        with self.assertRaises(BridgeRejected):
            SourceBinding.configured(self.sol.alias, 'pump_held_protection',
                environ={'MM_SOLANA_READ_RPC_URL': SOL}, governor=self.governor)
        with self.assertRaises(BridgeRejected):
            SourceBinding.configured(self.pons.alias, 'pons_discovery',
                environ={'MM_ROBINHOOD_READ_RPC_URL': PONS+'different'}, admission=self.admission)

    async def test_one_real_pons_batch_preserves_control_usage_and_fences(self):
        attempt = self.attempt(self.pons, [('eth_chainId', []), ('eth_blockNumber', [])], True)
        value = await self.perform(attempt)
        self.assertTrue(value.eof)
        self.assertIsInstance(self.physical.calls[0], list)
        self.assertEqual(len(self.physical.calls), 1)
        state = self.budget.snapshot()
        self.assertEqual(state['http_attempts'], '1')
        self.assertEqual(state['rpc_elements'], '2')
        self.assertEqual(state['http_reserved'], '0')
        self.assertEqual(state['http_uncertain_bytes'], '0')
        self.assertEqual(await self.http.activity_marker('pons'), (1, 1))
        with sqlite3.connect(self.admission.path) as db:
            row = json.loads(db.execute('SELECT body FROM transports').fetchone()[0])
            self.assertTrue(row['batch'])
            self.assertEqual(row['category'], 'final_qualification')
            self.assertEqual(row['purchase_work']['operation'], 'pons_current_qualification')
            self.assertEqual(row['physical_requests'], 1)
            grant = json.loads(db.execute('SELECT body FROM admissions').fetchone()[0])
            self.assertEqual(grant['priority'], 10)
        self.assertEqual(self.http.purchases.snapshot()['totals']['physical_requests'], 1)

    async def test_sol_governor_real_method_throttle_before_unread_error_body(self):
        self.physical.status = 429
        self.physical.fail_after = 0
        with self.assertRaises(Exception):
            await self.perform(self.attempt(calls=[('getSignaturesForAddress', ['address'])]))
        status = self.governor.status()
        self.assertEqual(status['providers'][0]['rate_errors'], 1)
        self.assertEqual(status['method_pressure'][0]['rate_streak'], 1)
        self.assertGreater(status['method_pressure'][0]['cooldown_remaining_seconds'], 0)
        state = self.budget.snapshot()
        self.assertEqual(state['http_uncertain_bytes'], str(MAX_FRAME))
        self.assertEqual(state['http_reserved'], '0')

    async def test_pons_429_retains_real_debt_if_body_capture_fails(self):
        self.physical.status = 429
        self.physical.fail_after = 0
        with self.assertRaises(Exception):
            await self.perform(self.attempt(self.pons, [('eth_chainId', [])]))
        with sqlite3.connect(self.admission.path) as db:
            self.assertGreater(db.execute('SELECT cooldown FROM limits').fetchone()[0], time.monotonic())
            row = json.loads(db.execute('SELECT body FROM transports').fetchone()[0])
            self.assertEqual(row['http_status'], 429)
            self.assertEqual(row['boundary'], 'provider_http_429')

    async def test_rpc_error_is_charged_and_only_genuine_code_crosses_wire(self):
        self.physical.body = b'{"id":1,"error":{"code":-32005,"message":"offline-parent-secret"}}'
        delivered = await self.perform(self.attempt())
        self.assertNotIn(b'offline-parent-secret', delivered.body)
        self.assertEqual(json.loads(delivered.body)['error']['code'], -32005)
        self.assertEqual(self.governor.status()['providers'][0]['rate_errors'], 1)
        state = self.budget.snapshot()
        self.assertEqual(state['http_bytes'], str(len(self.physical.body)))
        self.assertEqual(state['http_uncertain_bytes'], '0')
        self.assertEqual(self.http.purchases.snapshot()['totals']['failed_requests'], 1)

    async def test_mixed_solana_batch_preserves_successful_members_and_error_ids(self):
        self.physical.body = json.dumps([
            dict(id=2, result='retained-complete-economic-result'),
            dict(id=1, error=dict(code=-32005, message='offline-parent-secret'))]).encode()
        delivered = await self.perform(self.attempt(calls=[('getSlot', []), ('getSlot', [])], batch=True))
        rows = {r['id']: r for r in json.loads(delivered.body)}
        self.assertEqual(rows[2]['result'], 'retained-complete-economic-result')
        self.assertEqual(rows[1]['error']['code'], -32005)
        self.assertNotIn(b'offline-parent-secret', delivered.body)
        self.assertEqual(self.budget.snapshot()['rpc_elements'], '2')
        self.assertEqual(self.budget.snapshot()['http_attempts'], '1')

    async def test_partial_read_is_charged_uncertain_and_physical_eof_required(self):
        self.physical.fail_after = 1
        with self.assertRaises(OSError):
            await self.perform(self.attempt())
        state = self.budget.snapshot()
        self.assertEqual(state['http_bytes'], '7')
        self.assertEqual(state['http_uncertain_bytes'], str(MAX_FRAME-7))
        self.assertEqual(state['http_reserved'], '0')
        self.assertTrue(self.physical.raw[0].closed)

    async def test_parent_owned_receipt_retries_only_idempotent_failed_cleanup(self):
        original=self.budget.http_event
        closes=[]
        def failed_once(token,**kwargs):
            if kwargs.get('close'):
                closes.append(token)
                if len(closes)==1:raise sqlite3.OperationalError('offline close fault')
            return original(token,**kwargs)
        attempt=self.attempt()
        with patch.object(self.budget,'http_event',failed_once):
            with self.assertRaises(sqlite3.OperationalError):await self.http.execute(attempt)
            await self.http.release(attempt,uncertain=True)
        self.assertEqual(len(closes),2);self.assertEqual(len(set(closes)),1)
        self.assertEqual(self.budget.snapshot()['http_attempts'],'1')
        self.assertEqual(self.budget.snapshot()['http_reserved'],'0')
        self.assertFalse(self.http._states)

    async def test_permanent_receipt_cleanup_failure_stops_without_false_closed_claim(self):
        http=ParentHTTP(self.budget,[self.sol],opener=self.physical)
        channel=ParentChannel(http);channel.test_seq=0
        original=self.budget.http_event
        def failed_close(token,**kwargs):
            if kwargs.get('close'):raise sqlite3.OperationalError('offline permanent close fault')
            return original(token,**kwargs)
        try:
            with patch.object(self.budget,'http_event',failed_close):
                await self.dispatch(channel,'http_begin',alias='pump',batch=False,
                    calls=[dict(method='getSlot',params=[])])
                await asyncio.wait_for(channel.stopped.wait(),1)
                self.assertTrue(channel.closed)
                self.assertEqual(next(iter(channel.contents.values())).status,'accounting_failed')
                self.assertTrue(http._states)
                with sqlite3.connect(self.budget.path) as db:
                    self.assertEqual(db.execute('SELECT closed FROM http_receipts').fetchone()[0],0)
                with self.assertRaises(ParentTransportFailure):await channel.aclose()
        finally:
            # This intentionally unresolved receipt is synthetic disposable
            # failure evidence, never authoritative state or a false runtime ACK.
            http._executor.shutdown(wait=True)

    async def test_cancellation_joins_delivered_accounting_and_closes_once(self):
        self.physical.gate.clear()
        attempt = self.attempt()
        task = asyncio.create_task(self.http.execute(attempt))
        await asyncio.to_thread(self.physical.entered.wait, 2)
        self.assertTrue(self.physical.entered.is_set())
        task.cancel()
        await asyncio.sleep(.01)
        self.assertFalse(task.done())
        self.physical.gate.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        await self.http.release(attempt, uncertain=True)
        before = self.budget.snapshot()
        await self.http.release(attempt, uncertain=True)
        self.assertEqual(self.budget.snapshot(), before)
        self.assertEqual(before['http_attempts'], '1')
        self.assertEqual(before['http_uncertain_bytes'], str(MAX_FRAME))
        self.assertEqual(before['http_reserved'], '0')

    async def test_separate_pump_and_pons_workers_not_serialized_by_io(self):
        self.physical.gate.clear()
        pump = asyncio.create_task(self.perform(self.attempt()))
        await asyncio.to_thread(self.physical.entered.wait, 2)
        pons = asyncio.create_task(self.perform(self.attempt(self.pons, [('eth_chainId', [])])))
        for _ in range(100):
            if len(self.physical.calls) == 2:
                break
            await asyncio.sleep(.005)
        self.assertEqual(len(self.physical.calls), 2)
        self.physical.gate.set()
        await asyncio.gather(pump, pons)
        self.assertEqual(self.budget.snapshot()['http_attempts'], '2')

    async def test_cancel_queued_pons_grant_leaves_no_budget_purchase(self):
        with sqlite3.connect(self.admission.path) as db:
            db.execute('UPDATE limits SET next_at=?', (time.monotonic()+10,))
        attempt = self.attempt(self.pons, [('eth_chainId', [])])
        task = asyncio.create_task(self.http.execute(attempt))
        await asyncio.sleep(.05)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        await self.http.release(attempt, uncertain=True)
        self.assertEqual(self.budget.snapshot()['http_attempts'], '0')
        with sqlite3.connect(self.admission.path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM queue').fetchone()[0], 0)

    async def test_cancel_queued_sol_grant_preserves_clock_without_purchase(self):
        with sqlite3.connect(self.governor.path) as db:
            db.execute('INSERT INTO pressure VALUES(?,?,0,0,0)', ('solana', time.monotonic()+10))
        attempt = self.attempt()
        task = asyncio.create_task(self.http.execute(attempt))
        await asyncio.sleep(.05)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        await self.http.release(attempt, uncertain=True)
        self.assertEqual(self.budget.snapshot()['http_attempts'], '0')
        with sqlite3.connect(self.governor.path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM queue').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT reason FROM grants').fetchone()[0], 'attempt_canceled')

    async def test_parent_reconstructs_work_without_inherited_held_priority(self):
        from meme_machine.lanes.pons import provider_admission as pa
        token = pa._position_work.set(True)
        try:
            await self.perform(self.attempt(self.pons, [('eth_chainId', [])]))
            self.assertTrue(pa._position_work.get())
        finally:
            pa._position_work.reset(token)
        with sqlite3.connect(self.admission.path) as db:
            grant = json.loads(db.execute('SELECT body FROM admissions').fetchone()[0])
            self.assertEqual(grant['priority'], 10)

    async def test_original_repair_priorities_are_parent_issued_fixed_aliases(self):
        for priority in range(1,7):
            governor=Governor(self.root/('priority-'+str(priority)+'.sqlite'))
            binding=SourceBinding.configured(EndpointAlias('repair-'+str(priority),'solana',
                frozenset(('getSlot',))),'pump_history_receipt',
                environ={'MM_SOLANA_READ_RPC_URL':SOL},governor=governor,
                read_class='solana_evidence_'+str(priority))
            http=ParentHTTP(self.budget,[binding],opener=self.physical)
            attempt=self.attempt(binding)
            try:
                await http.execute(attempt);await http.release(attempt,uncertain=False)
                self.assertEqual(SourceReference.from_receipt(binding.receipt()).read_class,
                    'solana_evidence_'+str(priority))
                with sqlite3.connect(governor.path) as db:
                    self.assertEqual(db.execute('SELECT priority FROM grants').fetchone()[0],priority)
                purchase=http.purchases.snapshot()['operations'][0]
                self.assertEqual(purchase['operation'],'history_receipt')
            finally:await http.aclose()
        self.assertEqual(self.budget.snapshot()['http_attempts'],'6')
        with self.assertRaises(BridgeRejected):
            SourceBinding.configured(self.sol.alias,'pump_discovery',environ={'MM_SOLANA_READ_RPC_URL':SOL},
                governor=self.governor,read_class='solana_evidence_0')

    async def test_publication_refuses_reflected_credential_after_charging(self):
        self.physical.body = json.dumps(dict(id=1, result='offline-parent-secret')).encode()
        with self.assertRaises(ParentTransportFailure):
            await self.perform(self.attempt())
        self.assertEqual(self.budget.snapshot()['http_bytes'], str(len(self.physical.body)))
        self.assertEqual(self.budget.snapshot()['http_reserved'], '0')

    async def test_repair_request_deadline_is_fixed_in_parent_not_wire(self):
        source=replace(self.sol,read_class='solana_evidence_2')
        http=ParentHTTP(self.budget,[source],opener=self.physical)
        channel=ParentChannel(http,seconds=60,attempt_seconds=30)
        self.addAsyncCleanup(channel.aclose)
        channel.test_seq=0
        before=asyncio.get_running_loop().time()
        opened=await self.dispatch(channel,'http_begin',alias=source.alias.name,
            calls=[dict(method='getSlot',params=[])],batch=False)
        attempt=channel.contents[opened['token']].attempt
        self.assertGreater(attempt.deadline,before+7.9)
        self.assertLessEqual(attempt.deadline,asyncio.get_running_loop().time()+8)
        self.assertEqual((await self.terminal(channel,opened['token']))['status'],'delivered')

    async def test_logical_demand_cancellation_joins_accepted_commit(self):
        from meme_machine.runtime.robinhood import provider_usage
        original = provider_usage.demand
        entered, gate = threading.Event(), threading.Event()
        def committing(*args):
            entered.set()
            if not gate.wait(2): raise TimeoutError('offline demand gate')
            return original(*args)
        with patch.object(provider_usage, 'demand', committing):
            task = asyncio.create_task(self.http.demand('pons', ['eth_chainId']))
            await asyncio.to_thread(entered.wait, 1)
            task.cancel()
            await asyncio.sleep(.01)
            self.assertFalse(task.done())
            gate.set()
            with self.assertRaises(asyncio.CancelledError): await task
        with sqlite3.connect(self.admission.path) as db:
            self.assertEqual(db.execute('SELECT n FROM logical_demand').fetchone()[0], 1)

    async def test_native_full_commit_handoff_backpressure_and_uncertain_close(self):
        raw = _Native([b'first', b'second'])
        async def factory():
            self.assertGreater(int(self.budget.snapshot()['native_reserved']), 0)
            return raw
        stream = await ParentNativeStream.open(self.budget, 'yellowstone', factory, lambda body: None)
        self.addAsyncCleanup(stream.aclose)
        seq, body = await stream.read()
        self.assertEqual(body, b'first')
        self.assertGreaterEqual(int(self.budget.snapshot()['native_bytes']), 5)
        with self.assertRaises(BridgeRejected):
            await stream.read()
        with self.assertRaises(BridgeRejected):
            stream.acknowledge_handoff(seq+1)
        stream.acknowledge_handoff(seq)
        self.assertEqual((await stream.read())[1], b'second')
        await stream.aclose()
        state = self.budget.snapshot()
        self.assertEqual(state['native_bytes'], '11')
        self.assertEqual(state['native_reserved'], '0')
        self.assertEqual(state['native_uncertain_bytes'], str(4*MAX_FRAME))
        self.assertTrue(raw.closed)

    async def test_native_cancel_during_full_commit_waits_for_commit(self):
        raw = _Native([b'durable'])
        async def factory(): return raw
        stream = await ParentNativeStream.open(self.budget, 'yellowstone', factory, lambda body: None)
        self.addAsyncCleanup(stream.aclose)
        original = self.budget.native
        entered, gate = threading.Event(), threading.Event()
        def committing(*args, **kwargs):
            entered.set()
            if not gate.wait(2): raise TimeoutError('offline commit gate')
            return original(*args, **kwargs)
        with patch.object(self.budget, 'native', committing):
            reading = asyncio.create_task(stream.read())
            await asyncio.to_thread(entered.wait, 1)
            closing = asyncio.create_task(stream.aclose())
            await asyncio.sleep(.01)
            self.assertFalse(closing.done())
            gate.set()
            await closing
            await asyncio.gather(reading, return_exceptions=True)
        self.assertEqual(self.budget.snapshot()['native_bytes'], '7')
        self.assertEqual(self.budget.snapshot()['native_reserved'], '0')

    async def test_stream_open_failure_preserves_reserved_uncertain_usage(self):
        async def refused(): raise OSError('private transport error')
        with self.assertRaises(OSError):
            await ParentNativeStream.open(self.budget, 'yellowstone', refused, lambda body: None)
        state = self.budget.snapshot()
        self.assertEqual(state['native_opens'], '1')
        self.assertEqual(state['native_reserved'], '0')
        self.assertEqual(state['native_uncertain_bytes'], str(4*MAX_FRAME))

    async def test_native_abort_fault_still_closes_transport_and_original_reservation(self):
        class FaultyAbort(_Native):
            def cancel(self):raise OSError('private abort detail')
        raw=FaultyAbort()
        async def factory():return raw
        stream=await ParentNativeStream.open(self.budget,'yellowstone',factory,lambda body:None)
        with self.assertRaisesRegex(ParentTransportFailure,'^parent_stream_cleanup_failed$'):
            await stream.aclose()
        self.assertTrue(raw.closed)
        self.assertFalse(stream.cleanup_verified)
        self.assertEqual(self.budget.snapshot()['native_reserved'],'0')
        self.assertEqual(self.budget.snapshot()['native_uncertain_bytes'],str(4*MAX_FRAME))
        # A second close joins the same failed cleanup; it cannot reacquire.
        with self.assertRaises(ParentTransportFailure):await stream.aclose()
        self.assertEqual(self.budget.snapshot()['native_opens'],'1')

    async def test_fixed_native_subscriptions_reject_broad_or_paused_family(self):
        from meme_machine.yellowstone import geyser_pb2 as pb
        from meme_machine.solana_selective_history import PROGRAMS
        request = pb.SubscribeRequest(commitment=pb.FINALIZED)
        request.blocks_meta['b'].SetInParent()
        request.slots['f'].filter_by_commitment = True
        validate_subscription('yellowstone', request.SerializeToString())
        request.transactions['all'].vote = False
        with self.assertRaises(BridgeRejected):
            validate_subscription('yellowstone', request.SerializeToString())
        request.transactions['all'].account_include.append(PROGRAMS['meteora'])
        with self.assertRaises(BridgeRejected):
            validate_subscription('yellowstone', request.SerializeToString())
        value = dict(jsonrpc='2.0', id=1, method='logsSubscribe', params=[
            dict(mentions=[PROGRAMS['pump']]), dict(commitment='finalized')])
        validate_subscription('solana_websocket', json.dumps(value).encode())
        value['method'] = 'sendTransaction'
        with self.assertRaises(BridgeRejected):
            validate_subscription('solana_websocket', json.dumps(value).encode())

    async def test_actual_grpc_factory_keeps_source_token_in_parent(self):
        class Call:
            async def read(self): return grpc.aio.EOF
            async def write(self, value): pass
            def cancel(self): self.canceled = True
        call = Call()
        observed = {}
        class Channel:
            def stream_stream(self, path, **kwargs):
                observed['path'] = path
                def create(**kwargs):
                    observed.update(kwargs)
                    return call
                return create
            async def close(self, grace): observed['closed'] = True
        def open_channel(target, credentials, **kwargs):
            observed['target'] = target
            observed.update(kwargs)
            return Channel()
        with patch('grpc.aio.secure_channel', open_channel):
            raw = await authenticated_native_factory(self.sol, 'yellowstone')()
            self.assertIs(await raw.read(), grpc.aio.EOF)
            await raw.aclose()
        self.assertEqual(observed['target'], 'solana-mainnet.streaming.alchemy.com:443')
        self.assertEqual(observed['path'], '/geyser.Geyser/Subscribe')
        self.assertEqual(observed['metadata'], (('x-token', 'offline-parent-secret'),))
        self.assertTrue(observed['closed'])
        self.assertEqual(dict(observed['options'])['grpc.enable_retries'], 0)

    async def channel(self, **kwargs):
        channel = ParentChannel(self.http, **kwargs)
        self.addAsyncCleanup(channel.aclose)
        channel.test_seq = 0
        return channel

    def native_handle(self,channel):
        return next(handle for handle,stream in reversed(list(channel.streams.items())) if not stream.closed)

    async def dispatch(self, channel, verb, **kwargs):
        if verb=='http_begin' and 'provider_deadline_us' not in kwargs:
            kwargs['provider_deadline_us']=int((time.monotonic()+30)*1_000_000)
        channel.test_seq += 1
        return decoded(await channel.dispatch(encode_frame(dict(
            session=channel.session, seq=channel.test_seq, verb=verb, **kwargs))))

    async def terminal(self, channel, token):
        for _ in range(200):
            value = await self.dispatch(channel, 'poll', token=token)
            if value['status'] != 'running': return value
            await asyncio.sleep(.001)
        self.fail('offline parent did not complete')

    async def test_channel_complete_large_economic_body_chunks_exact_replay(self):
        self.physical.body = json.dumps(dict(id=1, result='x'*600000)).encode()
        channel = await self.channel()
        value = await self.dispatch(channel, 'http_begin', alias='pump', batch=False,
            calls=[dict(method='getBlock', params=[10, dict(maxSupportedTransactionVersion=1)])])
        token = value['token']
        self.assertEqual((await self.terminal(channel, token))['status'], 'delivered')
        result, offset = bytearray(), 0
        while True:
            value = await self.dispatch(channel, 'read', token=token, offset=offset)
            chunk = base64.b64decode(value['body_b64'])
            self.assertLessEqual(len(chunk), 65536)
            result.extend(chunk)
            # Immediate sequence replay returns the same chunk, no second read.
            frame = encode_frame(dict(session=channel.session, seq=channel.test_seq,
                verb='read', token=token, offset=offset))
            self.assertEqual(decoded(await channel.dispatch(frame)), value)
            ack = await self.dispatch(channel, 'ack', token=token, offset=offset, sha256=value['sha256'])
            offset += len(chunk)
            if value['final']:
                self.assertEqual(ack['status'], 'consumed')
                break
        self.assertEqual(json.loads(result), json.loads(self.physical.body))
        self.assertEqual(len(self.physical.calls), 1)
        self.assertNotIn(token, channel.contents)
        self.assertEqual(self.budget.snapshot()['http_reserved'], '0')

    async def test_cache_hit_demand_exact_replay_preserves_real_shared_ledger(self):
        channel = await self.channel()
        frame = encode_frame(dict(session=channel.session, seq=1, verb='demand', alias='pons',
            methods=['eth_getBlockByHash', 'eth_getBlockByHash']))
        first = await channel.dispatch(frame)
        self.assertEqual(await channel.dispatch(frame), first)
        with sqlite3.connect(self.admission.path) as db:
            self.assertEqual(db.execute('SELECT method,n FROM logical_demand').fetchall(),
                [('eth_getBlockByHash', 2)])
        self.assertEqual(self.budget.snapshot()['http_attempts'], '0')
        self.assertEqual(len(self.physical.calls), 0)

    async def test_channel_native_chunk_ack_is_not_canonical_ack(self):
        raw = _Native([b'native-payload', b'next'])
        async def factory(): return raw
        stream = await ParentNativeStream.open(self.budget, 'yellowstone', factory, lambda body: None)
        channel = await self.channel(streams={'pump': stream})
        accepted = await self.dispatch(channel, 'native_read', stream=self.native_handle(channel))
        token = accepted['token']
        self.assertEqual((await self.terminal(channel, token))['status'], 'delivered')
        value = await self.dispatch(channel, 'read', token=token, offset=0)
        self.assertEqual(base64.b64decode(value['body_b64']), b'native-payload')
        self.assertIsNotNone(stream.pending)
        await self.dispatch(channel, 'ack', token=token, offset=0, sha256=value['sha256'])
        self.assertIsNone(stream.pending)
        self.assertIn('transport_memory_only', channel.hello()['acknowledgements'])
        self.assertEqual(sorted(p.name for p in self.root.iterdir()),
                         ['governor.sqlite', 'pons.sqlite', 'usage.sqlite', 'usage.sqlite-shm', 'usage.sqlite-wal'])

    async def test_native_reopen_earns_new_reservation_and_stale_token_cannot_close_it(self):
        raws = []
        async def factory():
            raw = _Native([grpc.aio.EOF])
            raws.append(raw)
            return raw
        channel = await self.channel(native_sources=[NativeSourceBinding(self.sol, 'yellowstone')])
        with patch('meme_machine.operational.parent_transport.authenticated_native_factory',
                   return_value=factory):
            token = (await self.dispatch(channel, 'native_open', alias='pump'))['token']
            self.assertEqual((await self.terminal(channel, token))['status'], 'opened')
            old_read = (await self.dispatch(channel, 'native_read', stream=self.native_handle(channel)))['token']
            self.assertEqual((await self.terminal(channel, old_read))['status'], 'eof')
            closing = (await self.dispatch(channel, 'native_close', stream=self.native_handle(channel)))['token']
            self.assertEqual((await self.terminal(channel, closing))['status'], 'closed')
            token = (await self.dispatch(channel, 'native_open', alias='pump'))['token']
            self.assertEqual((await self.terminal(channel, token))['status'], 'opened')
            self.assertFalse(raws[1].closed)
            # A retained old read handle references exactly the original stream.
            await self.dispatch(channel, 'cancel', token=old_read)
            self.assertFalse(raws[1].closed)
        state = self.budget.snapshot()
        self.assertEqual(state['native_opens'], '2')
        self.assertEqual(state['native_reserved'], str(4*MAX_FRAME))
        self.assertEqual(state['native_uncertain_bytes'], str(4*MAX_FRAME))

    async def test_concurrent_native_instances_under_one_source_have_independent_reservations(self):
        raws=[]
        async def factory():
            raw=_Native([('instance-'+str(len(raws))).encode()]);raws.append(raw);return raw
        channel=await self.channel(native_sources=[NativeSourceBinding(self.sol,'yellowstone')])
        handles=[]
        with patch('meme_machine.operational.parent_transport.authenticated_native_factory',return_value=factory):
            for _ in range(3):
                token=(await self.dispatch(channel,'native_open',alias='pump'))['token']
                result=await self.terminal(channel,token)
                self.assertEqual(result['status'],'opened');handles.append(result['stream'])
            self.assertEqual(len(set(handles)),3)
            self.assertEqual(self.budget.snapshot()['native_reserved'],str(12*MAX_FRAME))
            for index,handle in enumerate(handles):
                token=(await self.dispatch(channel,'native_read',stream=handle))['token']
                self.assertEqual((await self.terminal(channel,token))['status'],'delivered')
                body=await self.dispatch(channel,'read',token=token,offset=0)
                self.assertEqual(base64.b64decode(body['body_b64']),('instance-'+str(index)).encode())
                await self.dispatch(channel,'ack',token=token,offset=0,sha256=body['sha256'])
            token=(await self.dispatch(channel,'native_close',stream=handles[0]))['token']
            await self.terminal(channel,token)
            self.assertTrue(raws[0].closed);self.assertFalse(raws[1].closed)
        self.assertEqual(self.budget.snapshot()['native_opens'],'3')
        self.assertEqual(self.budget.snapshot()['native_reserved'],str(8*MAX_FRAME))

    async def test_native_capacity_comes_from_original_budget_profile(self):
        budget=Budget.create(self.root/'small.sqlite',limits=dict(self.budget.limits,
            native_inflight_bytes=4*MAX_FRAME),modeled_spend_limit='3')
        http=ParentHTTP(budget,[self.sol],opener=_Physical(budget))
        channel=ParentChannel(http,native_sources=[NativeSourceBinding(self.sol,'yellowstone')])
        channel.test_seq=0
        self.addAsyncCleanup(channel.aclose)
        self.assertEqual(channel.hello()['maximum_streams'],1)
        async def factory():return _Native()
        with patch('meme_machine.operational.parent_transport.authenticated_native_factory',return_value=factory):
            token=(await self.dispatch(channel,'native_open',alias='pump'))['token']
            await self.terminal(channel,token)
            with self.assertRaises(BridgeRejected):
                await self.dispatch(channel,'native_open',alias='pump')
        self.assertEqual(budget.snapshot()['native_opens'],'1')

    async def test_actual_nitro_framing_inflation_and_full_commit_use_same_budget(self):
        import zlib
        from meme_machine.lanes.pons.sequencer_feed import _WebSocket
        from meme_machine.operational.parent_transport import sequencer_native_factory
        from tests.lanes.pons.test_sequencer_feed import row
        payload=json.dumps(dict(version=1,messages=[row(10)])).encode()
        compressor=zlib.compressobj(wbits=-15)
        compressed=(compressor.compress(payload)+compressor.flush(zlib.Z_SYNC_FLUSH))[:-4]
        header=bytes([0xc1,126])+struct.pack('!H',len(compressed)) if len(compressed)>=126 else bytes([0xc1,len(compressed)])
        class Socket:
            def __init__(self):self.data=bytearray(header+compressed);self.stop=threading.Event()
            def recv(self,size):
                if self.data:
                    out=bytes(self.data[:size]);del self.data[:size];return out
                self.stop.wait(2)
                raise OSError('offline socket stopped')
            def shutdown(self,_):self.stop.set()
            def close(self):self.stop.set()
        sock=Socket()
        def connect(client):
            self.assertEqual(client.url,'wss://feed.mainnet.chain.robinhood.com')
            client.sock=sock;client.permessage_deflate=True
            client.socket_observer(sock)
            return client
        binding=NativeSourceBinding(self.pons,'robinhood_sequencer')
        self.assertTrue(binding.receipt()['observation_only'])
        with patch.object(_WebSocket,'connect',connect):
            stream=await binding.open(self.budget)
            self.addAsyncCleanup(stream.aclose)
            seq,body=await stream.read()
            self.assertEqual(body,payload)
            self.assertEqual(self.budget.snapshot()['native_bytes'],str(len(payload)))
            self.assertEqual(self.budget.snapshot()['native_reserved'],str(5*MAX_FRAME))
            with self.assertRaises(BridgeRejected):await stream.write(b'anything')
            stream.acknowledge_handoff(seq)
            await asyncio.wait_for(stream.aclose(),2)
        self.assertEqual(self.budget.snapshot()['native_reserved'],'0')
        self.assertEqual(self.budget.snapshot()['native_uncertain_bytes'],str(5*MAX_FRAME))

    async def test_nitro_decompression_stops_at_original_output_limit(self):
        import zlib
        from meme_machine.lanes.pons.sequencer_feed import _WebSocket
        from meme_machine.lanes.pons import BoundaryError
        compressor=zlib.compressobj(wbits=-15)
        wire=(compressor.compress(b'x'*100000)+compressor.flush(zlib.Z_SYNC_FLUSH))[:-4]
        client=_WebSocket('wss://feed.mainnet.chain.robinhood.com',max_frame_bytes=1024)
        client.permessage_deflate=True
        with self.assertRaisesRegex(BoundaryError,'message_capacity'):
            client._inflate_message(wire)

    async def test_unknown_stream_accounting_failure_stops_connected_channel(self):
        class BadRaw(_Native):
            async def read(self): return (0, b'wrong-size')
        async def factory(): return BadRaw()
        stream = await ParentNativeStream.open(self.budget, 'yellowstone', factory, lambda body: None)
        channel = await self.channel(streams={'pump': stream})
        await self.dispatch(channel, 'native_read', stream=self.native_handle(channel))
        await asyncio.wait_for(channel.stopped.wait(), 1)
        self.assertTrue(channel.closed)
        await channel.aclose()
        self.assertEqual(self.budget.snapshot()['native_reserved'], '0')

    async def test_native_failure_is_published_only_after_original_cleanup_finishes(self):
        entered,gate=asyncio.Event(),asyncio.Event()
        class LostRaw(_Native):
            async def read(self):raise OSError('offline transport loss')
            async def aclose(self):
                entered.set();await gate.wait();await super().aclose()
        raw=LostRaw()
        async def factory():return raw
        stream=await ParentNativeStream.open(self.budget,'yellowstone',factory,lambda body:None)
        channel=await self.channel(streams={'pump':stream})
        token=(await self.dispatch(channel,'native_read',stream=self.native_handle(channel)))['token']
        await asyncio.wait_for(entered.wait(),1)
        self.assertEqual((await self.dispatch(channel,'poll',token=token))['status'],'running')
        gate.set()
        self.assertEqual((await self.terminal(channel,token))['status'],'failed')
        await self.dispatch(channel,'cancel',token=token)
        self.assertFalse(channel.closed)
        self.assertTrue(stream.cleanup_verified)
        self.assertEqual(self.budget.snapshot()['native_reserved'],'0')

    async def test_foreign_token_and_altered_replay_fail_without_extra_purchase(self):
        channel = await self.channel()
        frame = encode_frame(dict(session=channel.session, seq=1, verb='activity', alias='pons'))
        await channel.dispatch(frame)
        with self.assertRaises(BridgeRejected):
            await channel.dispatch(encode_frame(dict(session=channel.session, seq=1,
                verb='demand', alias='pons', methods=['eth_chainId'])))
        self.assertTrue(channel.closed)
        self.assertEqual(self.budget.snapshot()['http_attempts'], '0')

    async def test_connected_private_server_child_death_joins_native_cleanup(self):
        raw = _Native()
        async def factory(): return raw
        stream = await ParentNativeStream.open(self.budget, 'yellowstone', factory, lambda body: None)
        channel = await self.channel(streams={'pump': stream})
        parent, child = socket.socketpair()
        reader, writer = await asyncio.open_connection(sock=parent)
        cr, cw = await asyncio.open_connection(sock=child)
        exited = asyncio.Event()
        task = asyncio.create_task(serve_connected(reader, writer, channel, child_exited=exited))
        size = int.from_bytes(await cr.readexactly(4), 'big')
        hello = json.loads(await cr.readexactly(size))
        self.assertEqual(hello['session'], channel.session)
        cw.write(encode_frame(dict(session=channel.session, seq=1, verb='native_read', stream=self.native_handle(channel))))
        await cw.drain()
        size = int.from_bytes(await cr.readexactly(4), 'big')
        self.assertEqual(json.loads(await cr.readexactly(size))['status'], 'accepted')
        exited.set()
        await asyncio.wait_for(task, 2)
        cw.close()
        await cw.wait_closed()
        self.assertTrue(channel.closed)
        self.assertTrue(raw.closed)
        self.assertEqual(self.budget.snapshot()['native_reserved'], '0')
        self.assertEqual(self.budget.snapshot()['native_uncertain_bytes'], str(4*MAX_FRAME))
