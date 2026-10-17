"""Native scheduling stays immediate without rereading acknowledged bodies."""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from meme_machine.runtime.robinhood.accounting import project
from meme_machine.runtime.robinhood.plane import Plane, canonical
from meme_machine.lanes.pons.pipeline import Pipeline


class PonsSchedulingReadTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ,
            {'MM_OPERATIONAL_PHASE': 'OFFLINE_TEST', 'MM_MODE': 'PAPER'}, clear=True))
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.now = 100.
        self.plane = Plane(self.root / 'plane.sqlite', clock=lambda: self.now)
        self.addCleanup(lambda: self.plane.close())

    def peer(self):
        peer = Plane(self.root / 'plane.sqlite', clock=lambda: self.now)
        self.addCleanup(peer.close)
        return peer

    def observe(self, key, *, owner=None, n=1, priority=4, deadline=105., lane='pons'):
        owner = self.plane if owner is None else owner
        return owner.observe(key, lane, str(n), dict(n=n, synthetic=True),
            ordering=(n,), watermark=dict(block=n), interpretation=dict(policy='offline'),
            observed=self.now, deadline=deadline, priority=priority)

    def finish(self, key, *, owner=None, n=1, priority=4, deadline=105.):
        owner = self.plane if owner is None else owner
        self.observe(key, owner=owner, n=n, priority=priority, deadline=deadline)
        work = owner.claim(lane='pons', key=key)
        self.assertIsNotNone(work)
        self.assertTrue(owner.finish(work, result=dict(synthetic=True, n=n)))
        return work

    def acknowledged_tail(self, count=1169):
        # Synthetic durable fixture only. These are not provider-qualified
        # decisions or financial/historical callbacks. Behavioral tests below
        # use real observe→claim→finish→consume for all new generations.
        body = canonical(dict(synthetic=True, padding='x' * 4096))
        with self.plane.transaction():
            self.plane.db.executemany('''INSERT INTO candidates(
                id,lane,generation,interpretation,latest_id,observed,ordering,
                desired,completed,payload,state,pending,priority,rank,deadline,queued,result)
                VALUES(?,'pons',1,'{}','1',100,'[1]','{}','{}',?,'watching',0,4,0,105,100,?)''',
                ((f'quiet-{n:06d}', body, body) for n in range(count)))
            self.plane.db.execute('INSERT INTO result_consumption SELECT id,generation,100 FROM candidates')

    def test_empty_wide_acknowledged_tail_stays_bounded_under_peer_header_write(self):
        if not Path('/proc/self/io').is_file(): self.skipTest('Linux process I/O counters unavailable')
        self.acknowledged_tail()
        peer = self.peer()
        self.plane.recover(); self.assertEqual(self.plane.unconsumed('pons'), []); self.plane.maintain()
        peer.put('pons:shared:offline:header_number', '1', dict(synthetic=True), dict(authority='offline'))
        def rchar():
            return int(next(row.split(':', 1)[1] for row in Path('/proc/self/io').read_text().splitlines()
                if row.startswith('rchar:')))
        before = rchar()
        self.plane.recover()
        self.assertEqual(self.plane.unconsumed('pons'), [])
        self.plane.maintain()
        # Original native paths exceed 10 MiB here. This generous physical-cost
        # boundary detects body scans without asserting a specific query/index.
        self.assertLess(rchar() - before, 1_500_000)
        self.assertEqual(self.plane.db.execute('SELECT COUNT(*) FROM result_consumption').fetchone()[0], 1169)

    def test_one_pending_candidate_among_acknowledged_tail_is_immediately_claimed(self):
        self.acknowledged_tail(128)
        peer = self.peer()
        self.observe('arriving', owner=peer, priority=1, deadline=103)
        work = self.plane.claim(lane='pons')
        self.assertEqual((work['id'], work['generation'], work['deadline']), ('arriving', 1, 103))
        self.assertTrue(self.plane.current(work))
        self.assertIsNone(peer.claim(lane='pons'))

    def test_live_claim_then_expired_claim_is_not_hidden_by_unchanged_database(self):
        peer = self.peer(); self.observe('pending', owner=peer)
        work = peer.claim(lane='pons')
        self.plane.recover(); self.assertTrue(peer.current(work))
        self.now = 105.
        self.plane.recover()
        self.assertIsNone(self.plane.get('pending')['claim'])
        self.assertFalse(peer.finish(work, result=dict(synthetic=True)))
        self.assertIsNone(self.plane.claim(lane='pons'))
        self.assertEqual(self.plane.get('pending')['reason'], 'original_deadline_expired')

    def test_previous_boot_claim_recovered_on_reopen_but_paused_lane_unchanged(self):
        self.observe('pending'); work = self.plane.claim(lane='pons')
        with self.plane.transaction():
            self.plane.db.execute("UPDATE candidates SET owner='different-boot:1:1' WHERE id='pending'")
            # Retained paused state is historical data, not new producer work.
            self.plane.db.execute('''INSERT INTO candidates SELECT 'paused','ramses',generation,
                interpretation,latest_id,observed,ordering,desired,completed,payload,state,reason,
                pending,priority,rank,deadline,queued,claim,owner,claim_generation,claim_until,result
                FROM candidates WHERE id='pending' ''')
        self.plane.close(); self.plane = Plane(self.root / 'plane.sqlite', clock=lambda: self.now)
        self.assertIsNone(self.plane.get('pending')['claim'])
        self.assertEqual(self.plane.get('paused')['claim'], work['claim'])
        self.assertEqual(self.plane.claim(lane='pons')['id'], 'pending')

    def test_outbox_priority_order_full_result_and_pipeline_projection_are_not_ack(self):
        pipeline = Pipeline(self.root / 'pipeline.sqlite', 'pons', 'offline')
        self.addCleanup(pipeline.close)
        for key, priority, deadline in (('late', 4, 105), ('safety', 1, 104), ('early', 4, 103)):
            self.finish(key, priority=priority, deadline=deadline)
        project(self.plane, pipeline)
        rows = self.plane.unconsumed('pons')
        self.assertEqual([r['id'] for r in rows], ['safety', 'early', 'late'])
        self.assertTrue(all(json.loads(r['result']) == dict(synthetic=True, n=1) for r in rows))
        self.assertTrue(self.plane.consume('early', 1))
        self.assertEqual([r['id'] for r in self.plane.unconsumed('pons')], ['safety', 'late'])

    def test_prior_generation_consumption_never_hides_new_result_or_consumes_out_of_order(self):
        self.finish('candidate'); self.assertTrue(self.plane.consume('candidate', 1))
        self.finish('candidate', n=2)
        self.assertFalse(self.plane.consume('candidate', 1))
        self.plane.maintain()
        rows = self.plane.unconsumed('pons')
        self.assertEqual([(r['id'], r['generation']) for r in rows], [('candidate', 2)])
        self.assertEqual(self.plane.db.execute('SELECT COUNT(*) FROM result_consumption').fetchone()[0], 0)
        self.assertTrue(self.plane.consume('candidate', 2))
        self.assertEqual(self.plane.unconsumed('pons'), [])

    def test_peer_completion_during_outbox_scan_uses_one_snapshot_then_next_turn_sees_it(self):
        self.acknowledged_tail(128); peer = self.peer()
        self.observe('arriving', owner=peer); work = peer.claim(lane='pons', key='arriving')
        committed = []
        def progress():
            if not committed:
                committed.append(peer.finish(work, result=dict(synthetic=True, arriving=True)))
            return 0
        self.plane.db.set_progress_handler(progress, 100)
        try: first = self.plane.unconsumed('pons')
        finally: self.plane.db.set_progress_handler(None, 0)
        self.assertEqual(committed, [True])
        self.assertEqual(first, [])
        second = self.plane.unconsumed('pons')
        self.assertEqual([r['id'] for r in second], ['arriving'])
        self.assertEqual(json.loads(second[0]['result']), dict(synthetic=True, arriving=True))

    def test_cancelled_outbox_read_releases_snapshot_and_next_turn_delivers_original_result(self):
        self.acknowledged_tail(128); self.finish('real-result')
        self.plane.db.set_progress_handler(lambda: 1, 100)
        try:
            import sqlite3
            with self.assertRaises(sqlite3.OperationalError): self.plane.unconsumed('pons')
        finally: self.plane.db.set_progress_handler(None, 0)
        self.assertFalse(self.plane.db.in_transaction)
        self.assertEqual([r['id'] for r in self.plane.unconsumed('pons')], ['real-result'])

