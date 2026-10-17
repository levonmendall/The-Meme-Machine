"""One publication turn preserves accounting, FULL receipts and cancellation.

The canonical writer runs on the real PriorityOwner thread. The small work
adapter retains production admit/accepted/shield behavior; only failure points
and scheduling barriers are injected. All economics and authority are offline
disposable fixtures, never evidence of live readiness or financial activity.
"""
import asyncio
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from meme_machine.solana_evidence_control import PriorityOwner, admit
from meme_machine.solana_evidence_plane import EvidenceUnavailable, IntervalProof, digest
from meme_machine.solana_history_delivery import capture, deliver, acknowledge
from meme_machine.solana_rolling_history import program_scope
from meme_machine.solana_selective_history import PROGRAMS, economic_records
from meme_machine.solana_selective_source import SelectiveSource, source_work
from tests import test_contained_source_observation as funding_fixture
from tests.test_solana_closure import NOW, state_at
from tests.test_solana_selective_evidence import FIXTURE


class OwnedWork:
    """Production admission semantics with observable offline scheduling hooks."""
    def __init__(self, owner):
        self.owner = owner
        self.calls = []
        self.futures = []
        self.before = None
        self.returned = None

    async def __call__(self, fn, priority=1, *, label=None, component=None,
            accepted=None, admit_before=None):
        self.calls.append((priority, label, component))
        if self.before is not None:
            await self.before(len(self.calls), label, component)
        options = dict(priority=priority)
        if admit_before is not None:
            options['admit_before'] = admit_before
        future = await admit(self.owner, fn, **options)
        self.futures.append(future)
        if accepted is not None:
            accepted(future)
        wrapped = asyncio.wrap_future(future)
        try:
            answer = await asyncio.shield(wrapped)
        except asyncio.CancelledError:
            wrapped.add_done_callback(lambda f: f.exception() if not f.cancelled() else None)
            raise
        if self.returned is not None:
            self.returned(label, component)
        return answer


class PublicationAccountingTurnTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.funding = funding_fixture.ObservationFundingClosureTests('runTest')
        self.funding.setUp()
        self.addCleanup(self.funding.doCleanups)
        self.financial_before = self.funding.facts()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'canonical.sqlite'
        self.native = {}
        self.releases = []
        self.tasks = []
        self.events = []

        def factory():
            state, history = state_at(self.path)
            history.lifecycle.delivery_separated = True
            rows = [row for tx in FIXTURE['pump'] for row in economic_records(
                'pump', PROGRAMS['pump'], tx, endpoint_identity='a'*64,
                seen=NOW, source='alchemy_finalized_stream')]
            history.ingest(rows)
            self.native.update(state=state, history=history)
            state.close = state.writer.close
            return state

        self.owner = PriorityOwner(factory)
        await asyncio.wrap_future(self.owner.ready)
        # Establish actual consumer ACKs for the retained economics before the
        # operation under test. No outbox receipt or financial result is forged.
        events = await self.query(lambda s: capture(self.native['history'].lifecycle))
        self.assertIsNotNone(events)
        self.assertTrue(events['rows'])
        result = deliver(events)
        self.assertTrue(await self.query(lambda s:
            acknowledge(self.native['history'].lifecycle, events, result)))
        self.canonical_before = await self.canonical_facts()
        self.source = SelectiveSource(SimpleNamespace(credential='offline', identity='a'*64), None)
        self.source.stop = asyncio.Event()
        self.source.batched = True
        self.work = OwnedWork(self.owner)
        self.source.work = source_work(self.work, self.source.stop)
        self.key = (int(NOW)//86400, 'pump', 'yellowstone')

    async def asyncTearDown(self):
        self.source.stop.set()
        for release in self.releases:
            release.set()
        for task in self.tasks:
            if not task.done():
                task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        try:
            self.assertEqual(await self.canonical_facts(), self.canonical_before)
            self.assertEqual(self.funding.facts(), self.financial_before)
        finally:
            await asyncio.to_thread(self.owner.close)

    async def query(self, fn, priority=0):
        return await asyncio.wrap_future(self.owner.submit(fn, priority=priority))

    async def canonical_facts(self):
        names = ('records', 'rolling_economic_events', 'candidate_content_receipts',
            'native_order_attestations', 'candidate_outbox', 'cursors')
        return await self.query(lambda state: {name: state.writer.db.execute(
            'SELECT * FROM '+name+' ORDER BY rowid').fetchall() for name in names})

    async def accounting(self):
        return await self.query(lambda state: state.writer.db.execute(
            'SELECT family,transport,raw_bytes FROM provider_delivery ORDER BY family,transport').fetchall())

    async def proof(self, *, ack=False):
        scope = program_scope('pumpswap')
        def prepare(state):
            life = self.native['history'].lifecycle
            life.defer_proof(IntervalProof(scope, 100, 101, 'alchemy_finalized_stream', 'a'*64,
                dict(finalized=True, complete=True, scope=scope, lower_slot=100,
                    upper_slot=101, lineage_hash=digest([scope, 100, 101])), NOW))
            return capture(life)
        snapshot = await self.query(prepare)
        self.assertEqual(len(snapshot['proofs']), 1)
        result = deliver(snapshot)
        with closing(sqlite3.connect(self.native['history'].lifecycle.path)) as reader:
            self.assertEqual(reader.execute('PRAGMA synchronous').fetchone()[0], 2)
            identity = 'coverage:'+snapshot['proofs'][0]['identity']
            raw, checksum = reader.execute('SELECT body,hash FROM source_receipts WHERE id=?',
                (identity,)).fetchone()
            self.assertEqual(json.loads(raw)['identity'], snapshot['proofs'][0]['identity'])
            self.assertEqual(len(checksum), 64)
        if ack:
            self.assertTrue(await self.query(lambda state:
                acknowledge(self.native['history'].lifecycle, snapshot, result)))
        return snapshot, result

    def publication(self, snapshot, *, expected_bytes=None):
        identities = tuple(snapshot['publication_ids'])
        def after(state):
            self.assertFalse(state.writer.db.in_transaction)
            if expected_bytes is not None:
                self.assertEqual(state.writer.db.execute(
                    'SELECT raw_bytes FROM provider_delivery WHERE family=? AND transport=?',
                    ('pump', 'yellowstone')).fetchone(), (expected_bytes,))
            self.events.append('publication')
            life = self.native['history'].lifecycle
            life.publish(proof_ids=identities)
            return life._published_count
        return after

    async def assert_published(self, snapshot, published=True):
        identity = snapshot['proofs'][0]['identity']
        pending = await self.query(lambda state: state.writer.db.execute(
            'SELECT id FROM candidate_pending_proofs WHERE id=?', (identity,)).fetchone())
        self.assertEqual(pending is None, published)
        missing = await self.query(lambda state: self.native['history'].rolling.missing(
            'pumpswap', program_scope('pumpswap'), 100, 101))
        self.assertEqual(missing, [] if published else [(100, 101)])

    async def wait_entered(self, entered):
        self.assertTrue(await asyncio.to_thread(entered.wait, 2), 'owner callback did not reach its barrier')

    def held(self):
        entered, release = threading.Event(), threading.Event()
        self.releases.append(release)
        return entered, release

    def start(self, awaitable):
        task = asyncio.create_task(awaitable)
        self.tasks.append(task)
        return task

    async def test_ack_remains_separate_with_real_priority_zero_before_combined_turn(self):
        snapshot, result = await self.proof()
        self.source.pending_delivery[self.key] = (123, NOW)
        urgent = []
        def returned(label, component):
            if label == 'candidate_delivery_ack':
                def protect(state):
                    self.events.append('priority_zero')
                    self.assertEqual(state.writer.db.execute(
                        'SELECT count(*) FROM provider_delivery').fetchone(), (0,))
                    urgent.append(True)
                self.owner.submit(protect, priority=0)
        self.work.returned = returned
        original = self.native['history'].delivery
        def observed(*args, **kwargs):
            self.events.append('accounting')
            return original(*args, **kwargs)
        with patch.object(self.native['history'], 'delivery', observed):
            self.assertTrue(await self.source._complete_history_delivery(snapshot, result))
        self.assertEqual(urgent, [True])
        self.assertEqual(self.events, ['priority_zero', 'accounting'])
        self.assertEqual(self.work.calls, [(2, 'candidate_delivery_ack', None),
            (2, 'source_commit', 'history_publication')])
        self.assertEqual(await self.accounting(), [('pump', 'yellowstone', 123)])
        self.assertEqual(self.source.pending_delivery, {})
        self.assertTrue(snapshot['proof_publication_changed'])
        await self.assert_published(snapshot)

    async def test_standalone_and_empty_publication_keep_existing_noop_and_return_contracts(self):
        self.assertIsNone(await self.source.flush_delivery())
        self.assertEqual(self.work.calls, [])
        self.source.pending_delivery[self.key] = (123, NOW)
        self.assertIsNone(await self.source.flush_delivery())
        self.assertEqual(self.work.calls, [(2, 'source_commit', 'delivery_accounting')])
        snapshot, _ = await self.proof(ack=True)
        self.assertEqual(await self.source.flush_delivery(self.publication(snapshot, expected_bytes=123)), 1)
        self.assertEqual(self.work.calls[-1], (2, 'source_commit', 'history_publication'))
        self.assertEqual(await self.accounting(), [('pump', 'yellowstone', 123)])
        self.assertEqual(self.source.pending_delivery, {})
        await self.assert_published(snapshot)

    async def test_accounting_rollback_retains_delta_and_never_calls_publication(self):
        snapshot, _ = await self.proof(ack=True)
        self.source.pending_delivery[self.key] = (123, NOW)
        original = self.native['history'].delivery
        def broken(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError('offline-accounting-rollback')
        with patch.object(self.native['history'], 'delivery', broken):
            with self.assertRaisesRegex(RuntimeError, 'offline-accounting-rollback'):
                await self.source.flush_delivery(self.publication(snapshot))
        self.assertEqual(self.events, [])
        self.assertEqual(await self.accounting(), [])
        self.assertEqual(self.source.pending_delivery, {self.key: (123, NOW)})
        await self.assert_published(snapshot, False)
        self.assertEqual(await self.source.flush_delivery(self.publication(snapshot, expected_bytes=123)), 1)
        self.assertEqual(await self.accounting(), [('pump', 'yellowstone', 123)])
        await self.assert_published(snapshot)

    async def test_postcommit_publication_failure_settles_exact_delta_once(self):
        snapshot, _ = await self.proof(ack=True)
        self.source.pending_delivery[self.key] = (123, NOW)
        def broken(state):
            self.assertFalse(state.writer.db.in_transaction)
            self.assertEqual(state.writer.db.execute('SELECT raw_bytes FROM provider_delivery').fetchone(), (123,))
            raise RuntimeError('offline-publication-failure')
        with self.assertRaisesRegex(RuntimeError, 'offline-publication-failure'):
            await self.source.flush_delivery(broken)
        self.assertEqual(self.source.pending_delivery, {})
        self.assertEqual(await self.accounting(), [('pump', 'yellowstone', 123)])
        await self.assert_published(snapshot, False)
        self.assertEqual(await self.source.flush_delivery(self.publication(snapshot, expected_bytes=123)), 1)
        self.assertEqual(await self.accounting(), [('pump', 'yellowstone', 123)])
        await self.assert_published(snapshot)

    async def test_commit_then_retryable_publication_failures_never_repeat_accounting(self):
        snapshot, _ = await self.proof(ack=True)
        publish = self.publication(snapshot, expected_bytes=123)
        self.source.pending_delivery[self.key] = (123, NOW)
        calls = []
        def after(state):
            calls.append(True)
            if len(calls) <= 2:
                raise EvidenceUnavailable(('evidence_background_yield',
                    'evidence_control_overloaded')[len(calls)-1])
            return publish(state)
        self.assertEqual(await self.source.flush_delivery(after), 1)
        self.assertEqual(len(self.work.futures), 3)
        self.assertEqual(len(set(self.work.futures)), 3)
        self.assertEqual(self.source.pending_delivery, {})
        self.assertEqual(await self.accounting(), [('pump', 'yellowstone', 123)])
        await self.assert_published(snapshot)

    async def test_cancellation_before_admission_creates_no_new_work_or_accounting(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def before(number, label, component):
            entered.set()
            await release.wait()
        self.work.before = before
        self.source.pending_delivery[self.key] = (123, NOW)
        task = self.start(self.source.flush_delivery())
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.work.futures, [])
        self.assertEqual(await self.accounting(), [])
        self.assertEqual(self.source.pending_delivery, {self.key: (123, NOW)})
        self.assertFalse(self.source.delivery_lock.locked())

    async def test_commit_yield_then_cancellation_before_retry_admission_settles_committed_delta(self):
        snapshot, _ = await self.proof(ack=True)
        entered, release = asyncio.Event(), asyncio.Event()
        async def before(number, label, component):
            if number == 2:
                entered.set()
                await release.wait()
        self.work.before = before
        def yield_publication(state):
            raise EvidenceUnavailable('evidence_background_yield')
        self.source.pending_delivery[self.key] = (123, NOW)
        task = self.start(self.source.flush_delivery(yield_publication))
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(len(self.work.calls), 2)
        self.assertEqual(len(self.work.futures), 1)
        self.assertTrue(self.work.futures[0].done())
        self.assertFalse(self.work.futures[0].cancelled())
        self.assertEqual(await self.accounting(), [('pump', 'yellowstone', 123)])
        self.assertEqual(self.source.pending_delivery, {})
        await self.assert_published(snapshot, False)

    async def test_latest_accepted_retry_survives_repeated_cancel_and_serializes_new_delta(self):
        snapshot, _ = await self.proof(ack=True)
        entered, release = self.held()
        publish = self.publication(snapshot, expected_bytes=123)
        calls = []
        def after(state):
            calls.append(True)
            if len(calls) == 1:
                raise EvidenceUnavailable('evidence_background_yield')
            entered.set()
            if not release.wait(3):
                raise RuntimeError('offline-publication-barrier-timeout')
            return publish(state)
        self.source.pending_delivery[self.key] = (123, NOW)
        task = self.start(self.source.flush_delivery(after))
        await self.wait_entered(entered)
        self.assertEqual(len(self.work.futures), 2)
        original, latest = self.work.futures
        self.assertTrue(original.done())
        self.assertFalse(latest.done())
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        self.assertFalse(task.done())
        self.assertTrue(self.source.delivery_lock.locked())
        await self.source.delivered('pump', 'yellowstone', 11, NOW)
        next_flush = self.start(self.source.flush_delivery())
        await asyncio.sleep(0)
        self.assertFalse(next_flush.done())
        self.assertEqual(self.source.pending_delivery[self.key][0], 134)
        self.assertEqual(len(self.work.futures), 2)
        release.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(next_flush, 2)
        self.assertTrue(latest.done())
        self.assertFalse(latest.cancelled())
        self.assertEqual(len(self.work.futures), 3)
        self.assertEqual(await self.accounting(), [('pump', 'yellowstone', 134)])
        self.assertEqual(self.source.pending_delivery, {})
        self.assertFalse(self.source.delivery_lock.locked())
        await self.assert_published(snapshot)

    async def test_cancel_after_accepted_accounting_rollback_retains_delta(self):
        entered, release = self.held()
        original = self.native['history'].delivery
        def broken(*args, **kwargs):
            original(*args, **kwargs)
            entered.set()
            if not release.wait(3):
                raise RuntimeError('offline-accounting-barrier-timeout')
            raise RuntimeError('offline-original-accounting-error')
        self.source.pending_delivery[self.key] = (123, NOW)
        with patch.object(self.native['history'], 'delivery', broken):
            task = self.start(self.source.flush_delivery())
            await self.wait_entered(entered)
            task.cancel()
            await asyncio.sleep(0)
            self.assertTrue(self.source.delivery_lock.locked())
            self.assertFalse(task.done())
            release.set()
            with self.assertRaisesRegex(RuntimeError, 'offline-original-accounting-error'):
                await task
        self.assertEqual(await self.accounting(), [])
        self.assertEqual(self.source.pending_delivery, {self.key: (123, NOW)})
        self.assertFalse(self.source.delivery_lock.locked())
        self.assertFalse(self.work.futures[0].cancelled())

    async def test_cancel_after_commit_keeps_original_terminal_publication_error(self):
        snapshot, _ = await self.proof(ack=True)
        entered, release = self.held()
        def broken(state):
            self.assertEqual(state.writer.db.execute('SELECT raw_bytes FROM provider_delivery').fetchone(), (123,))
            entered.set()
            if not release.wait(3):
                raise RuntimeError('offline-publication-barrier-timeout')
            raise RuntimeError('offline-original-publication-error')
        self.source.pending_delivery[self.key] = (123, NOW)
        task = self.start(self.source.flush_delivery(broken))
        await self.wait_entered(entered)
        task.cancel()
        await asyncio.sleep(0)
        self.assertTrue(self.source.delivery_lock.locked())
        self.assertFalse(task.done())
        release.set()
        with self.assertRaisesRegex(RuntimeError, 'offline-original-publication-error'):
            await task
        self.assertEqual(await self.accounting(), [('pump', 'yellowstone', 123)])
        self.assertEqual(self.source.pending_delivery, {})
        self.assertFalse(self.work.futures[0].cancelled())
        await self.assert_published(snapshot, False)


if __name__ == '__main__':
    unittest.main()
