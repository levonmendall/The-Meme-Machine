"""Real SQLite checkpoint progress after stale generations, with safe handoff."""
import asyncio
from contextlib import closing
from dataclasses import replace
from pathlib import Path
import random
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from meme_machine.lanes.meteora.solana_evidence_control import PriorityOwner
from meme_machine.lanes.meteora.solana_evidence_plane import EvidenceUnavailable, EvidenceWriter
from meme_machine.lanes.meteora.solana_evidence_service import ServiceState
from meme_machine.lanes.meteora.solana_provider_config import AlchemyEndpoint
from meme_machine.lanes.meteora.solana_checkpoint import reclaim_at_boundary, checkpoint_and_reclaim
from tests.lanes.meteora.test_run381_retention_progress import record


class CheckpointHandoffTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'db'
        config=AlchemyEndpoint.parse('https://solana-mainnet.g.alchemy.com/v2/offline-test')
        self.owner=PriorityOwner(lambda:ServiceState(self.path,config))
        await asyncio.wrap_future(self.owner.ready)

    async def asyncTearDown(self):
        await asyncio.to_thread(self.owner.close)
        self.temp.cleanup()

    async def work(self,operation,priority=2):
        return await asyncio.wrap_future(self.owner.submit(operation,priority=priority))

    async def wait_event(self,event):
        self.assertTrue(await asyncio.to_thread(event.wait,5),'test coordination deadline')

    def rows(self,cycle,count=16):
        return [replace(record(),identity=f'handoff:{cycle}:{i}',signature=f's:{cycle}:{i}',
                payload={'body':random.Random(cycle*100+i).randbytes(8192).hex()})
                for i in range(count)]

    async def test_stale_generation_reproduces_growth_then_boundary_reclaims_without_loss(self):
        expected=set();baseline_sizes=[];repaired_sizes=[]
        await self.work(lambda state:state.writer.finish_checkpoint())
        for repaired,sizes in ((False,baseline_sizes),(True,repaired_sizes)):
            for index in range(8):
                cycle=index+100*repaired;rows=self.rows(cycle)
                await self.work(lambda s,rows=rows:s.writer.ingest(rows));expected.update(r.identity for r in rows)
                # A current reader allows PASSIVE copying but prevents WAL reset.
                with closing(sqlite3.connect(self.path,isolation_level=None)) as reader:
                    reader.execute('BEGIN');snapshot=reader.execute('SELECT COUNT(*) FROM records').fetchone()
                    ticket=await self.work(lambda s:self.owner.checkpoint_ticket_after_current())
                    complete=await asyncio.to_thread(EvidenceWriter.checkpoint,self.path)
                    self.assertEqual(complete[0],0);self.assertEqual(complete[1],complete[2])
                    tail=self.rows(cycle+1000,1);expected.add(tail[0].identity)
                    await self.work(lambda s,tail=tail:s.writer.ingest(tail))
                    current=await self.work(lambda s,t=ticket:self.owner.checkpoint_current(t))
                    self.assertFalse(current,'stale PASSIVE receipt unexpectedly became current')
                    self.assertEqual(reader.execute('SELECT COUNT(*) FROM records').fetchone(),snapshot)
                    reader.execute('ROLLBACK')
                if repaired:self.assertEqual(await reclaim_at_boundary(self.owner,self.path),(0,0,0))
                sizes.append(Path(str(self.path)+'-wal').stat().st_size)
        self.assertGreater(baseline_sizes[-1],baseline_sizes[0]*4,baseline_sizes)
        self.assertEqual(repaired_sizes,[0]*8)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual({r[0] for r in db.execute('SELECT identity FROM records')},expected)
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone(),('ok',))
        self.assertEqual(await self.work(lambda s:s.writer.db.execute('PRAGMA synchronous').fetchone()[0]),2)
        print('checkpoint-handoff-growth-proof',{'baseline_wal_bytes':baseline_sizes,'repaired_wal_bytes':repaired_sizes,'records':len(expected)})

    async def test_handoff_keeps_io_off_owner_and_serializes_queued_mutations(self):
        await self.work(lambda s:s.writer.ingest(self.rows(1)))
        entered=threading.Event();release=threading.Event();threads=[]
        def delayed(path):
            threads.append(threading.get_ident());entered.set()
            if not release.wait(5):raise TimeoutError('test release')
            return checkpoint_and_reclaim(path)
        with patch('meme_machine.lanes.meteora.solana_checkpoint.checkpoint_and_reclaim',side_effect=delayed):
            task=asyncio.create_task(reclaim_at_boundary(self.owner,self.path))
            await self.wait_event(entered)
            later=self.owner.submit(lambda s:s.writer.ingest(self.rows(2)),priority=0)
            try:
                await asyncio.sleep(.03);self.assertFalse(later.done())
                with closing(sqlite3.connect(self.path)) as db:
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM records').fetchone()[0],16)
            finally:release.set()
            self.assertEqual(await task,(0,0,0));await asyncio.wrap_future(later)
        self.assertNotIn(self.owner.thread.ident,threads)
        self.assertEqual(await self.work(lambda s:s.writer.db.execute('SELECT COUNT(*) FROM records').fetchone()[0]),32)

    async def test_pinned_reader_returns_without_waiting_and_lease_is_released(self):
        await self.work(lambda s:s.writer.ingest(self.rows(1)))
        with closing(sqlite3.connect(self.path,isolation_level=None)) as reader:
            reader.execute('BEGIN');before=reader.execute('SELECT COUNT(*) FROM records').fetchone()
            await self.work(lambda s:s.writer.ingest(self.rows(2)))
            start=time.monotonic();result=await reclaim_at_boundary(self.owner,self.path)
            self.assertLess(time.monotonic()-start,1)
            self.assertNotEqual(result[1],result[2])
            await self.work(lambda s:s.writer.ingest(self.rows(3)),priority=0)
            self.assertEqual(reader.execute('SELECT COUNT(*) FROM records').fetchone(),before)
            reader.execute('ROLLBACK')
        self.assertEqual(await reclaim_at_boundary(self.owner,self.path),(0,0,0))

    async def test_io_error_releases_lease_and_preserves_original_exception(self):
        with patch('meme_machine.lanes.meteora.solana_checkpoint.checkpoint_and_reclaim',side_effect=OSError('injected disk')):
            with self.assertRaisesRegex(OSError,'injected disk'):
                await reclaim_at_boundary(self.owner,self.path)
        await self.work(lambda s:s.writer.ingest(self.rows(1)),priority=0)
        self.assertEqual(await reclaim_at_boundary(self.owner,self.path),(0,0,0))

    async def test_cancelled_queued_handoff_is_consumed_and_released(self):
        entered=threading.Event();release=threading.Event()
        def older(s):
            entered.set()
            if not release.wait(5):raise TimeoutError('test release')
        preceding=self.owner.submit(older,priority=2);await self.wait_event(entered)
        with patch('meme_machine.lanes.meteora.solana_checkpoint.checkpoint_and_reclaim') as io:
            task=asyncio.create_task(reclaim_at_boundary(self.owner,self.path))
            await asyncio.sleep(.02);task.cancel();task.cancel();release.set()
            with self.assertRaises(asyncio.CancelledError):await task
            await asyncio.wrap_future(preceding);io.assert_not_called()
        await self.work(lambda s:s.writer.ingest(self.rows(1)),priority=0)

    async def test_cancellation_joins_inflight_io_before_resuming_mutation(self):
        entered=threading.Event();release=threading.Event()
        def delayed(path):
            entered.set()
            if not release.wait(5):raise TimeoutError('test release')
            return checkpoint_and_reclaim(path)
        with patch('meme_machine.lanes.meteora.solana_checkpoint.checkpoint_and_reclaim',side_effect=delayed):
            task=asyncio.create_task(reclaim_at_boundary(self.owner,self.path));await self.wait_event(entered)
            task.cancel();await asyncio.sleep(.01);task.cancel()
            later=self.owner.submit(lambda s:s.writer.ingest(self.rows(1)),priority=0)
            try:
                await asyncio.sleep(.02);self.assertFalse(task.done());self.assertFalse(later.done())
            finally:release.set()
            with self.assertRaises(asyncio.CancelledError):await task
            await asyncio.wrap_future(later)

    async def test_wrong_release_token_does_not_unlock_the_boundary(self):
        with self.assertRaisesRegex(EvidenceUnavailable,'checkpoint_handoff_owner_thread'):
            self.owner.checkpoint_handoff_after_current()
        token=await self.work(lambda s:self.owner.checkpoint_handoff_after_current())
        try:
            with self.assertRaisesRegex(EvidenceUnavailable,'checkpoint_handoff_token'):
                self.owner.release_checkpoint_handoff(object())
            later=self.owner.submit(lambda s:True,priority=0)
            await asyncio.sleep(.02);self.assertFalse(later.done())
        finally:self.owner.release_checkpoint_handoff(token)
        self.assertTrue(await asyncio.wrap_future(later))


if __name__=='__main__':unittest.main()
