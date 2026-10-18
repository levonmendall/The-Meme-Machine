"""Actual parent transports/accounting with explicit offline source/image fixtures."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from meme_machine.operational import isolated_native_image as image
from meme_machine.operational import parent_head_lifecycle as heads
from meme_machine.operational.bounded_provider import Budget, MAX_FRAME
from meme_machine.operational.parent_channel import ParentChannel
from meme_machine.operational.parent_transport import ParentHTTP, SourceBinding
from meme_machine.operational.transport_bridge import EndpointAlias, ParentAttempt, ReadCall
from meme_machine.runtime.governor import Governor
from meme_machine.lanes.pons.provider_admission import Admission
from meme_machine.solana_provider_config import GENESIS
from tests.test_isolated_native_launcher import receipt as approval_fixture
from tests.test_parent_native_transport import _Raw, SOL, PONS
from tests.test_provider_clock_domain import identity


class Physical:
    def __init__(self, budget):
        self.budget = budget; self.calls = []; self.raw = []
        self.gate = threading.Event(); self.gate.set(); self.entered = threading.Event()
        self.status = 200; self.fail_after = None; self.slot = 100; self.chain = '0x1237'
        self.genesis = GENESIS; self.reverse = False; self.error_method = None
        self.header = dict(number='0x64', timestamp='0x3e8', hash='0x' + 'd' * 64)

    def __call__(self, request, timeout):
        assert int(self.budget.snapshot()['http_reserved']) >= MAX_FRAME
        calls = json.loads(request.data); self.calls.append(calls)
        rows = calls if isinstance(calls, list) else [calls]
        replies = []
        for row in rows:
            method = row['method']
            if method == self.error_method:
                reply = dict(id=row['id'], error=dict(code=-32005, message='PRIVATE_PROVIDER_MESSAGE'))
            else:
                result = (self.genesis if method == 'getGenesisHash' else self.slot if method == 'getSlot'
                    else self.chain if method == 'eth_chainId' else dict(self.header))
                reply = dict(jsonrpc='2.0', id=row['id'], result=result)
            replies.append(reply)
        if self.reverse: replies.reverse()
        body = json.dumps(replies if isinstance(calls, list) else replies[0]).encode()
        self.entered.set()
        if not self.gate.wait(timeout): raise TimeoutError('offline physical bound')
        raw = _Raw(body, fail_after=self.fail_after, status=self.status); self.raw.append(raw)
        return raw


class ParentHeadLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        context = patch('meme_machine.runtime.provider_clock.current_identity', return_value=identity())
        context.start(); self.addCleanup(context.stop)
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.budget = Budget.create(self.root / 'usage.sqlite')
        self.governor = Governor(self.root / 'governor.sqlite')
        self.admission = Admission(self.root / 'pons.sqlite', PONS, lane='pons')
        self.sol = SourceBinding.configured(EndpointAlias('history2', 'solana',
            frozenset(('getGenesisHash', 'getSlot'))), 'pump_history_receipt',
            environ={'MM_SOLANA_READ_RPC_URL': SOL}, governor=self.governor, read_class='solana_evidence_2')
        self.pons = SourceBinding.configured(EndpointAlias('discovery', 'robinhood',
            frozenset(('eth_chainId', 'eth_getBlockByNumber', 'eth_blockNumber'))), 'pons_discovery',
            environ={'MM_ROBINHOOD_READ_RPC_URL': PONS}, admission=self.admission)
        self.physical = Physical(self.budget)
        self.http = ParentHTTP(self.budget, [self.sol, self.pons], opener=self.physical)
        self.channel = ParentChannel(self.http, seconds=60)
        self.addAsyncCleanup(self.channel.aclose)
        # Synthetic copied-image fixture; only the current-checkout guard is
        # replaced in positive unit tests. Real manifest/file verification runs.
        writer = image._ImageWriter(self.root / 'native-image')
        entry = b'# synthetic fixed entry\n'; requirements = b'fixed requirements\n'
        writer.copy(entry, 'app/' + image.ENTRY)
        writer.copy(requirements, 'app/requirements.txt')
        row = approval_fixture(); row['source_files'] = {image.ENTRY: hashlib.sha256(entry).hexdigest()}
        exact = deepcopy(row)
        self.approval = image.NativeImageApproval(row, authenticate=lambda value: value == exact)
        manifest = dict(schema='isolated-native-copied-image-v1', source_commit=row['source_commit'],
            source_tree=row['source_tree'], requirements_sha256=row['requirements_sha256'],
            files=list(writer.files), bytes=writer.bytes, financial_authority=False, provider_calls=0,
            actual_service_restrictions_verified=False)
        raw = image.encoded(manifest); writer.copy(raw, 'manifest.json')
        self.image = dict(root=writer.root, manifest=manifest, manifest_sha256=hashlib.sha256(raw).hexdigest())

    def start(self, *, refresh=False, channel=None):
        with patch.object(image, 'source_objects', return_value=(self.root, b'', [])) as verified:
            result = (channel or self.channel).start_head_measurement(self.approval, self.image, refresh=refresh)
        verified.assert_called_once_with(self.approval)
        return result

    async def perform(self, binding, calls, *, http=None, channel=None):
        http = http or self.http; channel = channel or self.channel
        attempt = ParentAttempt(channel.session, secrets.token_urlsafe(32), binding.alias,
            tuple(ReadCall(method, json.dumps(params).encode()) for method, params in calls), len(calls) > 1,
            asyncio.get_running_loop().time() + 3)
        delivered = None
        try:
            delivered = await http.execute(attempt)
            return delivered
        finally:
            await http.release(attempt, uncertain=delivered is None)

    async def solana(self):
        return await self.perform(self.sol, [('getGenesisHash', []), ('getSlot', [dict(commitment='finalized')])])

    async def pons_heads(self):
        return await self.perform(self.pons, [('eth_chainId', []), ('eth_getBlockByNumber', ['latest', False])])

    def stale(self, owner, kind):
        # Explicit offline old-publication fixture; preserve the real purchase
        # and exercise the actual refresh path without a five-second sleep.
        retained = dict(owner.points[kind])
        for field in ('request_started_monotonic', 'physical_completed_monotonic', 'physical_completed_wall'):
            retained[field] -= 6
        owner.points[kind] = retained

    async def test_default_parent_has_no_sampler_or_added_purchase(self):
        self.assertIsNone(self.channel.head_measurement())
        await self.solana()
        self.assertEqual(self.budget.snapshot()['http_attempts'], '1')
        self.assertIsNone(self.channel.head_measurement())

    async def test_exact_approval_current_checkout_and_real_image_bytes_are_required(self):
        with self.assertRaises(image.Refused):
            self.channel.start_head_measurement(self.approval, self.image, refresh=False)
        self.assertIsNone(self.channel._head_lifecycle)
        broken = dict(self.image, manifest_sha256='f' * 64)
        with patch.object(image, 'source_objects', return_value=(self.root, b'', [])), self.assertRaises(image.Refused):
            self.channel.start_head_measurement(self.approval, broken, refresh=False)
        self.assertIsNone(self.channel._head_lifecycle)
        row = self.approval.value(); row['source_tree'] = 'f' * 40
        other = image.NativeImageApproval(row, authenticate=lambda value: value == row)
        with patch.object(image, 'source_objects', return_value=(self.root, b'', [])), self.assertRaises(ValueError):
            self.channel.start_head_measurement(other, self.image, refresh=False)
        self.assertEqual(self.budget.snapshot()['http_attempts'], '0')

    async def test_actual_reverse_batch_identity_and_heads_keep_transport_session_type(self):
        owner = self.start(); self.physical.reverse = True
        await self.solana(); await self.pons_heads()
        before = self.budget.snapshot()
        result = owner.snapshot()
        self.assertEqual(result['generation'], dict(kind='PARENT_TRANSPORT_SESSION', value=self.channel.session))
        self.assertEqual(len(result['generation']['value']), 43)
        self.assertEqual(result['source_pid'], os.getpid())
        self.assertEqual(result['source_process_start_ticks'], heads._process()[1])
        self.assertEqual(result['image_manifest_sha256'], self.image['manifest_sha256'])
        for kind in ('solana_finalized', 'pons_latest'):
            self.assertEqual(result['heads'][kind]['state'], 'OBSERVED')
            self.assertEqual(result['heads'][kind]['last']['height'], 100)
        self.assertEqual(result['bindings']['discovery']['pons_admission_session'], self.admission.session)
        self.assertIsNone(result['canonical_source_generation']); self.assertIsNone(result['economic_arrival_count'])
        self.assertFalse(result['canonical_coverage']); self.assertFalse(result['normal_readiness'])
        self.assertEqual(self.budget.snapshot(), before)
        self.assertNotIn('offline-parent-secret', json.dumps(result))
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.assertLessEqual(len(json.dumps(result, separators=(',', ':')).encode()), 4096)
        result['heads']['solana_finalized']['last']['height'] = 9999
        self.assertEqual(owner.snapshot()['heads']['solana_finalized']['last']['height'], 100)

    async def test_network_proof_missing_or_wrong_is_not_assumed_and_wrong_proof_stays_latched(self):
        owner = self.start()
        await self.perform(self.sol, [('getSlot', [dict(commitment='finalized')])])
        self.assertIsNone(owner.snapshot()['heads']['solana_finalized']['last'])
        self.physical.genesis = 'wrong-network'
        await self.solana()
        self.physical.genesis = GENESIS
        await self.solana()
        result = owner.snapshot()
        self.assertFalse(result['providers']['solana']['verified'])
        self.assertEqual(result['heads']['solana_finalized']['state'], 'UNAVAILABLE')
        count = len(self.physical.calls)
        self.assertFalse(await owner.refresh_once('solana'))
        self.assertEqual(len(self.physical.calls), count)

    async def test_latest_finalized_and_historical_or_unfinalized_heads_stay_distinct(self):
        owner = self.start(); await self.solana(); await self.pons_heads()
        await self.perform(self.sol, [('getSlot', [dict(commitment='confirmed')])])
        await self.perform(self.pons, [('eth_getBlockByNumber', ['0x1', False])])
        self.assertIsNone(owner.snapshot()['heads']['pons_finalized']['last'])
        self.physical.header['number'] = '0x60'
        await self.perform(self.pons, [('eth_getBlockByNumber', ['finalized', False])])
        result = owner.snapshot()
        self.assertEqual(result['heads']['pons_latest']['last']['height'], 100)
        self.assertEqual(result['heads']['pons_finalized']['last']['height'], 96)

    async def test_stale_only_refresh_uses_original_purchase_work_priority_and_completion_pacing(self):
        owner = self.start(); await self.solana()
        self.assertFalse(await owner.refresh_once('solana'))
        count = len(self.physical.calls)
        self.stale(owner, 'solana_finalized')
        self.assertTrue(await owner.refresh_once('solana'))
        self.assertFalse(await owner.refresh_once('solana'))
        self.assertEqual(len(self.physical.calls), count + 1)
        self.assertEqual(self.budget.snapshot()['http_attempts'], str(count + 1))
        self.assertEqual(self.budget.snapshot()['http_reserved'], '0')
        labels = self.http.purchases.snapshot()['operations']
        self.assertTrue(any(row['operation'] == 'history_receipt' and row['consumer'] == 'history'
                            and row['purpose'] == 'history_receipt' for row in labels))
        self.assertEqual(owner.snapshot()['bindings']['history2']['read_class'], 'solana_evidence_2')

    async def test_429_and_partial_response_keep_original_debt_without_retry_or_new_authority(self):
        owner = self.start(); await self.pons_heads()
        self.physical.status = 429; self.physical.fail_after = 0
        self.stale(owner, 'pons_latest')
        self.assertFalse(await owner.refresh_once('pons'))
        self.assertFalse(await owner.refresh_once('pons'))
        state = self.budget.snapshot()
        self.assertEqual(state['http_attempts'], '2')
        self.assertEqual(state['http_uncertain_bytes'], str(MAX_FRAME))
        self.assertEqual(state['http_reserved'], '0')
        with sqlite3.connect(self.admission.path) as db:
            self.assertGreater(db.execute('SELECT cooldown FROM limits').fetchone()[0], time.monotonic())
        self.assertEqual(owner.snapshot()['heads']['pons_latest']['state'], 'UNAVAILABLE')
        self.assertEqual(owner.refresh_failures['pons_latest'], 1)

    async def test_generation_process_admission_or_clock_change_invalidates_retained_head(self):
        owner = self.start(); await self.solana(); await self.pons_heads()
        original = self.channel.session
        self.channel.session = secrets.token_urlsafe(32)
        self.assertEqual(owner.snapshot()['heads']['solana_finalized']['state'], 'UNAVAILABLE')
        self.channel.session = original
        self.assertFalse(owner.snapshot()['owner_current'])
        with patch.object(heads, '_process', return_value=(os.getpid(), owner.ticks + 1)):
            self.assertFalse(owner.snapshot()['owner_current'])
        with patch('meme_machine.runtime.provider_clock.current_identity', return_value=identity(namespace=43)):
            self.assertFalse(owner.snapshot()['owner_current'])
        session = self.admission.session; self.admission.session = 'f' * 32
        self.assertFalse(owner.snapshot()['owner_current']); self.admission.session = session

    async def test_duplicate_owner_and_cross_channel_start_refused_before_provider(self):
        self.start()
        with self.assertRaises(ValueError): self.start()
        other = ParentChannel(self.http, seconds=30)
        with self.assertRaises(ValueError): self.start(channel=other)
        self.assertEqual(self.budget.snapshot()['http_attempts'], '0')

    async def test_second_worker_start_failure_retains_and_joins_first_worker(self):
        loop = asyncio.get_running_loop(); original = loop.create_task; retained = []
        def create(coroutine, **kwargs):
            if coroutine.cr_code.co_name == '_run':
                if retained: raise RuntimeError('offline second worker startup failure')
                task = original(coroutine, **kwargs); retained.append(task); return task
            return original(coroutine, **kwargs)
        with patch.object(loop, 'create_task', side_effect=create), self.assertRaises(RuntimeError):
            self.start(refresh=True)
        owner = self.channel._head_lifecycle
        self.assertIsNotNone(owner); self.assertEqual(owner.tasks, retained)
        self.assertTrue(owner.stop_requested.is_set()); self.assertFalse(owner.stopped)
        self.assertFalse(owner.snapshot()['startup_complete'])
        with self.assertRaises(ValueError): self.start()
        await self.channel.aclose()
        self.assertTrue(owner.stopped); self.assertTrue(all(task.done() for task in retained))
        self.assertEqual(self.budget.snapshot()['http_attempts'], '0')

    async def test_one_inflight_refresh_and_stop_join_preserve_original_uncertainty(self):
        owner = self.start(); await self.solana()
        self.physical.entered.clear(); self.physical.gate.clear()
        self.stale(owner, 'solana_finalized')
        request = asyncio.create_task(owner.refresh_once('solana'))
        await asyncio.to_thread(self.physical.entered.wait, 2)
        self.assertTrue(self.physical.entered.is_set())
        self.assertFalse(await owner.refresh_once('solana'))
        closing = asyncio.create_task(self.channel.aclose())
        await asyncio.sleep(.02)
        self.assertFalse(closing.done()); self.assertFalse(owner.stopped)
        self.physical.gate.set()
        await asyncio.wait_for(closing, 2)
        self.assertFalse(await request); self.assertFalse(request.cancelled())
        self.assertTrue(owner.stopped); self.assertFalse(owner.inflight)
        self.assertEqual(self.budget.snapshot()['http_reserved'], '0')
        self.assertEqual(self.budget.snapshot()['http_uncertain_bytes'], str(MAX_FRAME))
        self.assertFalse(self.http._states)

    async def test_actual_owned_refresh_tasks_wait_for_paid_identity_and_join_on_close(self):
        owner = self.start(refresh=True)
        await asyncio.sleep(.02)
        self.assertEqual(self.budget.snapshot()['http_attempts'], '0')
        await self.perform(self.sol, [('getGenesisHash', [])])
        until = asyncio.get_running_loop().time() + 2
        while owner.snapshot()['heads']['solana_finalized']['last'] is None and asyncio.get_running_loop().time() < until:
            await asyncio.sleep(.01)
        self.assertIsNotNone(owner.snapshot()['heads']['solana_finalized']['last'])
        self.assertEqual(self.budget.snapshot()['http_attempts'], '2')
        await self.channel.aclose()
        self.assertTrue(all(task.done() for task in owner.tasks))
        self.assertTrue(owner.snapshot()['collection_stopped'])
        self.assertEqual(owner.snapshot()['heads']['solana_finalized']['state'], 'UNAVAILABLE')

    async def test_missing_exact_refresh_capability_never_infers_another_priority_or_alias(self):
        source = replace(self.sol, read_class='solana_evidence_1')
        http = ParentHTTP(self.budget, [source], opener=self.physical)
        channel = ParentChannel(http, seconds=30); self.addAsyncCleanup(channel.aclose)
        owner = self.start(channel=channel)
        self.assertIsNone(owner.refresh_sources['solana'])
        self.assertFalse(await owner.refresh_once('solana'))
        self.assertEqual(owner.snapshot()['providers']['solana']['refresh_capability'], 'UNAVAILABLE_CAPABILITY')
        self.assertEqual(self.budget.snapshot()['http_attempts'], '0')

    async def test_shared_worker_capacity_refuses_refresh_without_cancelling_native_leader(self):
        http = ParentHTTP(self.budget, [self.sol], opener=self.physical, workers=1)
        channel = ParentChannel(http, seconds=30, workers=1); self.addAsyncCleanup(channel.aclose)
        owner = self.start(channel=channel)
        await self.perform(self.sol, [('getGenesisHash', []), ('getSlot', [dict(commitment='finalized')])],
            http=http, channel=channel)
        self.stale(owner, 'solana_finalized')
        self.physical.gate.clear(); self.physical.entered.clear()
        leader = asyncio.create_task(self.perform(self.sol, [('getSlot', [dict(commitment='confirmed')])],
            http=http, channel=channel))
        try:
            await asyncio.to_thread(self.physical.entered.wait, 2)
            self.assertTrue(self.physical.entered.is_set())
            self.assertFalse(await owner.refresh_once('solana'))
            self.assertFalse(leader.done()); self.assertFalse(leader.cancelled())
            self.assertEqual(self.budget.snapshot()['http_attempts'], '2')
        finally: self.physical.gate.set()
        delivered = await leader
        self.assertTrue(delivered.eof)
        self.assertEqual(self.budget.snapshot()['http_reserved'], '0')

    async def test_incomplete_head_join_retains_owners_and_cannot_claim_stopped(self):
        from meme_machine.operational.isolated_native_lifetime import NativeOwnerDrainFailure
        owner = self.start(); await self.solana(); self.stale(owner, 'solana_finalized')
        self.physical.gate.clear(); self.physical.entered.clear()
        request = asyncio.create_task(owner.refresh_once('solana'))
        await asyncio.to_thread(self.physical.entered.wait, 2)
        self.assertTrue(self.physical.entered.is_set())
        owner.stop()
        try:
            with self.assertRaises(NativeOwnerDrainFailure) as caught:
                await owner.join(deadline=asyncio.get_running_loop().time())
            self.assertIn(self.http, caught.exception._retained)
            self.assertFalse(caught.exception.receipt['all_workers_joined'])
            self.assertFalse(owner.stopped)
        finally:
            self.physical.gate.set()
            self.assertFalse(await request); self.assertFalse(request.cancelled())
        await owner.join(deadline=asyncio.get_running_loop().time() + 1)

    async def test_http_body_failure_does_not_create_head_and_keeps_physical_debt(self):
        owner = self.start()
        await self.perform(self.sol, [('getGenesisHash', [])])
        self.physical.fail_after = 1
        self.assertFalse(await owner.refresh_once('solana'))
        result = owner.snapshot()
        self.assertIsNone(result['heads']['solana_finalized']['last'])
        state = self.budget.snapshot()
        self.assertEqual(state['http_attempts'], '2')
        self.assertGreater(int(state['http_bytes']), 7)
        self.assertGreater(int(state['http_uncertain_bytes']), 0)
        self.assertEqual(state['http_reserved'], '0')

    async def test_sampler_stop_never_cancels_inline_caller_or_unrelated_native_leader(self):
        owner = self.start(); await self.solana(); self.stale(owner, 'solana_finalized')
        self.physical.gate.clear(); self.physical.entered.clear()
        leader = asyncio.create_task(self.perform(self.sol, [('getSlot', [dict(commitment='confirmed')])]))
        request = None
        try:
            await asyncio.to_thread(self.physical.entered.wait, 2)
            self.assertTrue(self.physical.entered.is_set()); self.physical.entered.clear()
            request = asyncio.create_task(owner.refresh_once('solana'))
            await asyncio.to_thread(self.physical.entered.wait, 2)
            self.assertTrue(self.physical.entered.is_set())
            owner.stop(); await asyncio.sleep(.02)
            self.assertFalse(leader.done()); self.assertFalse(leader.cancelled())
            self.assertFalse(request.cancelled())
        finally: self.physical.gate.set()
        await owner.join(deadline=asyncio.get_running_loop().time() + 2)
        self.assertFalse(await request); self.assertFalse(request.cancelled())
        self.assertTrue((await leader).eof)
        self.assertEqual(self.budget.snapshot()['http_reserved'], '0')
        self.assertFalse(self.http._states)

    async def test_callers_own_cancellation_joins_its_admitted_attempt_before_propagating(self):
        owner = self.start(); await self.solana(); self.stale(owner, 'solana_finalized')
        self.physical.gate.clear(); self.physical.entered.clear()
        request = asyncio.create_task(owner.refresh_once('solana'))
        try:
            await asyncio.to_thread(self.physical.entered.wait, 2)
            self.assertTrue(self.physical.entered.is_set())
            request.cancel(); await asyncio.sleep(.02)
            self.assertFalse(request.done())
        finally: self.physical.gate.set()
        with self.assertRaises(asyncio.CancelledError): await request
        self.assertFalse(owner.pending_chains); self.assertFalse(owner.owned_attempts)
        self.assertFalse(owner.stopped)
        self.assertEqual(self.budget.snapshot()['http_reserved'], '0')


if __name__ == '__main__': unittest.main()
