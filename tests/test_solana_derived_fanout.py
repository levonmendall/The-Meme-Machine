"""Disposable durable fanout fences; no providers or financial authority."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from meme_machine import solana_derived_fanout as fanout
from meme_machine.solana_evidence_control import PriorityOwner
from meme_machine.solana_evidence_plane import EvidenceUnavailable
from meme_machine.solana_history_delivery import capture, capture_context, deliver, acknowledge
from meme_machine.solana_rolling_history import program_scope
from meme_machine.solana_scoped_retirement import ScopedRetirement
from meme_machine.solana_selective_history import PROGRAMS, economic_records
from meme_machine.solana_selective_source import SelectiveSource
from tests.test_publication_accounting_turn import OwnedWork
from tests.test_solana_closure import NOW, state_at
from tests.test_solana_selective_evidence import FIXTURE


def fixture_row():
    return next(row for tx in FIXTURE['pump'] for row in economic_records(
        'pump', PROGRAMS['pump'], tx, endpoint_identity='a'*64,
        seen=NOW, source='alchemy_finalized_stream') if row.kind=='event')


class DerivedFanoutTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'canonical.sqlite'
        self.state,self.h=state_at(self.path);self.addCleanup(self.state.writer.close)
        self.life=self.h.lifecycle;self.life.delivery_separated=True;self.row=fixture_row()
        self.mint=self.row.payload['event']['mint']
    def freeze(self,aliases=()):
        self.h.bind('pump',self.mint)
        for alias in aliases:self.h.bind('pump',alias,market_address=self.mint)
        with self.state.writer.transaction():self.h.ingest((self.row,),defer_fanout=True)
        return capture_context(self.life)
    def prepare(self,context):
        return fanout.prepare(context.canonical_path,context.endpoint_identity,context.source_identity)

    def test_pending_recipient_fences_proof_and_retirement_until_actual_full_ack(self):
        context=self.freeze();scope=program_scope('pump');slot=self.row.slot
        self.assertTrue(fanout.pending(self.life,scope,slot))
        self.assertFalse(fanout.pending(self.life,scope,slot-1))
        self.assertFalse(fanout.pending(self.life,'candidate:pump:unrelated',slot))
        self.assertTrue(fanout.record_pending(self.h.db,self.row.identity))
        retirement=ScopedRetirement(self.h)
        self.assertEqual(retirement.pinned('pump',self.mint,slot,slot,None),'pending_consumer')
        with self.assertRaisesRegex(EvidenceUnavailable,'checkpoint_ahead_of_history'):
            self.life.checkpoint(scope,slot,'no-consumer-receipt')
        self.assertTrue(fanout.apply(self.life,self.prepare(context)))
        self.assertEqual(fanout.pending_counts(self.life),(0,0,0))
        self.assertFalse(fanout.record_pending(self.h.db,self.row.identity))
        self.assertTrue(self.life.unconsumed(scope,through=slot),'materialization is not a consumer receipt')
        snapshot=capture(self.life);self.assertTrue(snapshot['rows'])
        self.assertTrue(acknowledge(self.life,snapshot,deliver(snapshot)))
        self.assertFalse(self.life.unconsumed(scope,through=slot))
        self.life.checkpoint(scope,slot,'actual-full-and-fresh-ack')

    def test_large_recipient_population_is_paged_without_reselecting_later_aliases(self):
        aliases=tuple('alias-'+str(i) for i in range(90));context=self.freeze(aliases)
        intent_count,retained,remaining=fanout.pending_counts(self.life)
        self.assertEqual(intent_count,1);self.assertEqual(remaining,91)
        self.h.bind('pump','later-alias',market_address=self.mint)
        original=self.h.db.execute('SELECT outbox_rowid,created FROM candidate_fanout_targets ORDER BY position').fetchall()
        # Scale the existing byte bound to exercise an admitted intent whose
        # complete recipient population exceeds a page. Only indexed target
        # slices, rather than that complete population, enter the RO capture.
        raw_bytes=len(self.h.db.execute('SELECT record_raw FROM candidate_derived_fanout').fetchone()[0].encode())
        page=max(raw_bytes+2048,(retained//2))
        self.assertLess(page,retained)
        pages=0;outputs=[]
        with patch.object(fanout,'PAGE_BYTES',page):
            while (prepared:=self.prepare(context)) is not None:
                pages+=1;batch=[output for _,_,rows in prepared.records for output in rows]
                self.assertLessEqual(len(batch),64)
                self.assertLessEqual(sum(len(r[5].encode())+256 for r in batch),page)
                outputs.extend((r[0],r[7]) for r in batch)
                self.assertTrue(fanout.apply(self.life,prepared))
        self.assertGreater(pages,1);self.assertEqual(outputs,original)
        addresses={r[0] for r in self.h.db.execute('SELECT address FROM candidate_history_outbox')}
        self.assertNotIn('later-alias',addresses);self.assertEqual(addresses,{self.mint,*aliases})
        self.assertEqual(fanout.pending_counts(self.life),(0,0,0))

    def test_read_transaction_closes_before_hashing_and_replaced_source_is_refused(self):
        context=self.freeze();original=fanout.hashlib.sha256;checked=[]
        def hashing(*args,**kwargs):
            with closing(sqlite3.connect(self.path,timeout=0)) as db:
                self.assertEqual(db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0],0)
            checked.append(True);return original(*args,**kwargs)
        with patch.object(fanout.hashlib,'sha256',hashing):prepared=self.prepare(context)
        self.assertTrue(checked);self.assertTrue(fanout.apply(self.life,prepared))
        with self.assertRaisesRegex(EvidenceUnavailable,'source_replaced'):
            fanout.prepare(context.canonical_path,context.endpoint_identity,(-1,-1))

    def test_corrupt_marker_and_altered_prepared_body_leave_durable_obligation(self):
        context=self.freeze();prepared=self.prepare(context);before=fanout.pending_counts(self.life)
        row,targets,outputs=prepared.records[0];bad=replace(prepared,records=((row,targets,
            (tuple((*outputs[0][:5],outputs[0][5]+' ',*outputs[0][6:])),*outputs[1:])),))
        with self.assertRaisesRegex(EvidenceUnavailable,'preparation_changed'):fanout.apply(self.life,bad)
        self.assertEqual(fanout.pending_counts(self.life),before)
        self.h.db.execute("UPDATE candidate_history_outbox SET body='{}' WHERE rowid=?",(outputs[0][0],))
        with self.assertRaisesRegex(EvidenceUnavailable,'source_corrupt'):fanout.apply(self.life,prepared)
        self.assertEqual(fanout.pending_counts(self.life),before)
        self.assertIsNone(capture(self.life),'a reservation can never become a delivery snapshot')

    def test_orphan_reserved_row_cannot_disappear_into_empty_preparation_or_drain(self):
        context=self.freeze()
        self.h.db.execute('DELETE FROM candidate_fanout_targets')
        self.h.db.execute('DELETE FROM candidate_derived_fanout')
        with self.assertRaisesRegex(EvidenceUnavailable,'reservation_orphan'):self.prepare(context)
        with self.assertRaisesRegex(EvidenceUnavailable,'reservation_orphan'):fanout.pending_counts(self.life)
        plan=self.h.db.execute("EXPLAIN QUERY PLAN SELECT 1 FROM candidate_history_outbox WHERE id>='fanout:' AND id<'fanout;' LIMIT 1").fetchall()
        self.assertTrue(any('INDEX' in row[3] and 'id>' in row[3] for row in plan),plan)
        # The namespace is case sensitive everywhere. A different ordinary ID
        # must remain visible to capture and pending-history accounting.
        self.h.db.execute('UPDATE candidate_history_outbox SET id=upper(id)')
        self.assertIsNone(self.prepare(context))
        self.assertEqual(self.h.db.execute("SELECT count(*) FROM candidate_history_outbox WHERE consumed IS NULL AND id NOT GLOB 'fanout:*'").fetchone()[0],1)
        self.assertTrue(capture(self.life)['rows'][0][0].startswith('FANOUT:'))

    def test_rehashed_target_cannot_replace_the_frozen_population_chain(self):
        context=self.freeze();target=self.h.db.execute('SELECT '+fanout.TARGET_COLUMNS+' FROM candidate_fanout_targets').fetchone()
        changed=(*target[:-2],target[-2]+1)
        # Even a changed target with an internally consistent row hash must
        # authenticate to the intake-frozen population head, not merely itself.
        self.h.db.execute('UPDATE candidate_fanout_targets SET created=?,hash=? WHERE outbox_rowid=?',
            (changed[-1],fanout.digest([changed,'']),target[0]))
        with self.assertRaisesRegex(EvidenceUnavailable,'source_corrupt'):self.prepare(context)
        self.assertGreater(fanout.pending_counts(self.life)[2],0)

    def test_changed_next_page_boundary_rejects_apply_before_any_materialization(self):
        context=self.freeze(tuple('alias-'+str(i) for i in range(90)))
        prepared=self.prepare(context);self.assertEqual(len(prepared.records[0][1]),64)
        identity,end,checksum=prepared.tails[0];self.assertEqual(end,64)
        before=fanout.pending_counts(self.life)
        self.h.db.execute('UPDATE candidate_fanout_targets SET hash=? WHERE intent=? AND position=?',
            ('0'*64,identity,end))
        self.assertFalse(fanout.apply(self.life,prepared))
        self.assertEqual(fanout.pending_counts(self.life),before)
        self.assertEqual(self.h.db.execute('SELECT position FROM candidate_derived_fanout').fetchone()[0],0)
        self.assertEqual(self.h.db.execute("SELECT count(*) FROM candidate_history_outbox WHERE id NOT GLOB 'fanout:*'").fetchone()[0],0)
        with self.assertRaisesRegex(EvidenceUnavailable,'source_corrupt'):self.prepare(context)


class DerivedFanoutWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'canonical.sqlite';self.native={}
        def factory():
            state,h=state_at(self.path);h.lifecycle.delivery_separated=True
            with state.writer.transaction():h.ingest((fixture_row(),),defer_fanout=True)
            self.native.update(history=h);state.close=state.writer.close;return state
        self.owner=PriorityOwner(factory);await asyncio.shield(asyncio.wrap_future(self.owner.ready))
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='fanout-test')
        self.source=SelectiveSource(SimpleNamespace(credential='offline',identity='a'*64),None)
        self.source.work=OwnedWork(self.owner);self.source.preparation_executor=self.pool
        self.source.delivery_capture_context=await self.query(lambda s:capture_context(self.native['history'].lifecycle))
        self.tasks=[];self.releases=[]
    async def asyncTearDown(self):
        for event in self.releases:event.set()
        for task in self.tasks:
            if not task.done():task.cancel()
        if self.tasks:await asyncio.gather(*self.tasks,return_exceptions=True)
        self.pool.shutdown(wait=True);await asyncio.to_thread(self.owner.close);self.tmp.cleanup()
    async def query(self,fn):return await asyncio.wrap_future(self.owner.submit(fn,priority=0))
    def start(self):
        task=asyncio.create_task(self.source.derived_fanout());self.tasks.append(task);return task

    async def test_producers_closed_drains_real_intent_and_releases_preparation_before_owner_wait(self):
        entered=asyncio.Event();release=asyncio.Event();self.releases.append(release)
        async def before(number,label,component):
            self.assertFalse(self.source.preparation_lock.locked())
            entered.set();await release.wait()
        self.source.work.before=before;self.source.fanout_done.set();task=self.start()
        await asyncio.wait_for(entered.wait(),3)
        pending=await self.query(lambda s:fanout.pending_counts(self.native['history'].lifecycle))
        self.assertGreater(pending[2],0);self.assertFalse(task.done())
        # Another native preparation can use the original shared slot while
        # this derived result waits for owner admission.
        async with self.source.preparation_lock:
            self.assertEqual(await asyncio.wrap_future(self.pool.submit(int,'7')),7)
        release.set();await asyncio.wait_for(task,3)
        self.assertEqual(await self.query(lambda s:fanout.pending_counts(self.native['history'].lifecycle)),(0,0,0))

    async def test_read_busy_retries_after_original_backoff_and_keeps_obligation(self):
        original=fanout.prepare;calls=[]
        def prepare(*args):
            calls.append(time.monotonic())
            if len(calls)==1:
                error=sqlite3.OperationalError('offline busy');error.sqlite_errorcode=sqlite3.SQLITE_BUSY;raise error
            return original(*args)
        self.source.fanout_done.set()
        with patch.object(fanout,'prepare',prepare):await asyncio.wait_for(self.start(),3)
        self.assertGreaterEqual(calls[1]-calls[0],.09)
        self.assertEqual(await self.query(lambda s:fanout.pending_counts(self.native['history'].lifecycle)),(0,0,0))

    async def test_repeated_cancellation_joins_physical_preparation_even_after_terminal_error(self):
        entered=threading.Event();release=threading.Event();self.releases.append(release)
        def prepare(*args):entered.set();release.wait(3);raise RuntimeError('terminal physical read')
        with patch.object(fanout,'prepare',prepare):
            task=self.start();self.assertTrue(await asyncio.to_thread(entered.wait,2))
            task.cancel();await asyncio.sleep(0);task.cancel();await asyncio.sleep(0)
            self.assertFalse(task.done());self.assertTrue(self.source.preparation_lock.locked())
            release.set()
            with self.assertRaises(asyncio.CancelledError):await asyncio.wait_for(task,3)
        self.assertFalse(self.source.preparation_lock.locked())
        self.assertGreater((await self.query(lambda s:fanout.pending_counts(self.native['history'].lifecycle)))[2],0)
        self.source.fanout_done.set();await asyncio.wait_for(self.start(),3)
        self.assertEqual(await self.query(lambda s:fanout.pending_counts(self.native['history'].lifecycle)),(0,0,0))
