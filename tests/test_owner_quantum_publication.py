"""Real nonbatched publication fences on disposable quiet Model B state.

Existing synthetic quiet-interval proofs exercise ordering/recovery contracts;
they are never authenticated market evidence or economic opportunity claims.
No provider, financial ledger, installed database or runtime is accessed.
"""
import asyncio
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from meme_machine.solana_candidate_development import DISPATCH, IDLE
from meme_machine.solana_history_work import HistoricalTasks
from meme_machine.solana_selective_source import SelectiveSource
from tests.test_solana_closure import NOW, state_at
from tests.test_solana_prewarm_startup import proof, quiet_model_b


class OwnerQuantumPublicationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name)/'canonical.sqlite'
        self.environment = patch.dict('os.environ',
            MM_SOLANA_HISTORY_SEPARATED='0',
            MM_SOLANA_CANDIDATE_HISTORY_DB=str(Path(temporary.name)/'history.sqlite'))
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.state, self.history = state_at(self.path)
        self.addCleanup(self.state.writer.close)

        async def direct(fn, *args, **options):
            return fn(self.state)

        stopped = asyncio.Event()
        stopped.set()
        await quiet_model_b(direct, stopped)
        self.assertTrue(self.history.startup.snapshot()['released'])
        self.source = SelectiveSource(SimpleNamespace(
            credential='offline', identity='a'*64), None)
        self.source.batched = False
        self.source.stop = asyncio.Event()
        self.source.measured_rpc = AsyncMock(side_effect=AssertionError(
            'publication fixture must not request provider data'))
        self.turns = []
        self.events = []

    def committed(self, sql, parameters=()):
        # A different connection cannot see the actor's uncommitted writes.
        with closing(sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro',
                uri=True)) as reader:
            return reader.execute(sql, parameters).fetchall()

    async def acquire_until_idle(self):
        async def work(fn, *args, **options):
            if options.get('label') != 'candidate_development':
                return fn(self.state)
            self.assertLess(len(self.turns), 64, 'publication never reached bounded honest IDLE')
            result = fn(self.state)  # Actual Source request/plan/claim callback.
            self.assertFalse(self.history.db.in_transaction)
            self.turns.append(result.state)
            self.events.append(('owner_return', result.state))
            if result.state == IDLE:
                self.assertTrue(any(event[0] == 'publish_done' for event in self.events),
                    'IDLE was returned before the real publisher completed')
                self.source.stop.set()
            return result

        self.source.work = work
        await self.source.acquire()
        self.source.measured_rpc.assert_not_awaited()
        self.assertFalse(self.history.db.in_transaction)
        self.assertEqual(getattr(self.state, 'acquisition_inflight', set()), set())
        self.assertEqual(getattr(self.state, 'acquisition_claim_tokens', {}), {})
        self.assertEqual(getattr(self.history, '_archive_preparation_tickets', {}), {})

    async def test_real_nonbatched_publisher_observes_prior_committed_binding_and_preparation(self):
        history = self.history
        history.historical_tasks = HistoricalTasks(history)
        history.install_planner()
        address = 'committed-before-nonbatched-publication'
        with self.state.writer.transaction():
            history.observe('pump', address, slot=100, signature='', seen=NOW, fields={})
            history.bind('pump', address)
            preparation = history.rolling.prepare('pump', address, 0, 100,
                priority=3, deadline=NOW+150)['historical_job']
        before = self.committed('SELECT body,priority,deadline,status FROM rolling_preparation_jobs WHERE id=?',
            (preparation,))
        self.assertEqual(len(before), 1)
        self.assertEqual(before[0][1:], (3, NOW+150, 'pending'))
        original_publish = history.lifecycle.publish

        def publish(*args, **options):
            entered_in_transaction = history.db.in_transaction
            binding = self.committed('SELECT address FROM evidence_bindings WHERE family=? AND address=?',
                ('pump', address))
            prepared = self.committed('SELECT body,priority,deadline,status FROM rolling_preparation_jobs WHERE id=?',
                (preparation,))
            self.events.append(('publish_enter', entered_in_transaction))
            # Call the real publisher first: the unfixed runtime must fail its
            # own canonical-before-consumer guard, not a mocked replacement.
            result = original_publish(*args, **options)
            self.assertFalse(entered_in_transaction)
            self.assertFalse(history.db.in_transaction)
            self.assertEqual(binding, [(address,)])
            self.assertEqual(prepared, before)
            self.events.append(('publish_done', preparation))
            return result

        with patch.object(history.lifecycle, 'publish', side_effect=publish):
            await self.acquire_until_idle()
        self.assertTrue(any(event[0] == 'publish_done' for event in self.events))
        self.assertNotIn(DISPATCH, self.turns)
        self.assertEqual(self.committed('SELECT body,priority,deadline,status FROM rolling_preparation_jobs WHERE id=?',
            (preparation,)), before)
        delivered = self.committed("SELECT consumed FROM candidate_history_outbox WHERE address=? AND kind='scout'",
            (address,))
        self.assertTrue(delivered)
        self.assertTrue(all(consumed is not None for consumed, in delivered))

    async def test_real_publication_changes_coverage_before_fresh_selection_and_never_claims_stale_plan(self):
        history = self.history
        address = 'publication-before-fresh-archive-selection'
        with self.state.writer.transaction():
            history.observe('pump', address, slot=100, signature='', seen=NOW, fields={})
            scope = history.bind('pump', address)
            identity = history.request('pump', address, 101, 101,
                priority=3, deadline=NOW+150)
        self.assertEqual(history.rolling.missing('pump', scope, 101, 101), [(101, 101)])
        self.assertEqual(self.committed('SELECT lo,hi,priority,deadline,status FROM acquisition_jobs WHERE id=?',
            (identity,)), [(101, 101, 3, NOW+150, 'pending')])
        original_publish = history.lifecycle.publish
        published = []

        def publish(*args, **options):
            entered_in_transaction = history.db.in_transaction
            # Deliver the existing test suite's synthetic quiet proof at this
            # boundary. A plan computed before publication would request this
            # genuinely missing interval; the real publisher now satisfies it.
            if not published:
                with self.state.writer.transaction():
                    history.lifecycle.defer_proof(proof(scope, 101, 101))
            self.events.append(('publish_enter', entered_in_transaction))
            result = original_publish(*args, **options)
            self.assertFalse(entered_in_transaction)
            self.assertFalse(history.db.in_transaction)
            self.assertEqual(history.rolling.missing('pump', scope, 101, 101), [])
            self.assertEqual(self.committed('SELECT COUNT(*) FROM candidate_pending_proofs WHERE scope=?',
                (scope,)), [(0,)])
            published.append(True)
            self.events.append(('publish_done', identity))
            return result

        with patch.object(history.lifecycle, 'publish', side_effect=publish):
            await self.acquire_until_idle()
        self.assertTrue(published)
        self.assertNotIn(DISPATCH, self.turns,
            'coverage publication must precede a fresh decision, never a stale claimed DISPATCH')
        self.assertEqual(self.committed('SELECT lo,hi,priority,deadline,status,token,pages FROM acquisition_jobs WHERE id=?',
            (identity,)), [(101, 101, 3, NOW+150, 'complete', None, 0)])
        self.assertEqual(history.rolling.missing('pump', scope, 101, 101), [])
        self.assertEqual(self.committed('SELECT COUNT(*) FROM acquisition_page_receipts WHERE job=?',
            (identity,)), [(0,)])


if __name__ == '__main__':
    unittest.main()
