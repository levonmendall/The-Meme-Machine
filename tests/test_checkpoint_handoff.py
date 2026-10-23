"""Real SQLite checkpoint progress after stale generations, with safe handoff."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import random
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from meme_machine.solana_evidence_control import PriorityOwner
from meme_machine.solana_evidence_plane import EvidenceUnavailable, EvidenceWriter
from meme_machine.solana_evidence_service import ServiceState
from meme_machine.solana_provider_config import AlchemyEndpoint
from meme_machine.solana_checkpoint import CheckpointWorker, reclaim_at_boundary, checkpoint_and_reclaim
from tests.test_retention_progress import record


class CheckpointHandoffTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'db'
        config=AlchemyEndpoint.parse('https://solana-mainnet.g.alchemy.com/v2/offline-test')
        self.owner=PriorityOwner(lambda:ServiceState(self.path,config))
        await asyncio.wrap_future(self.owner.ready)
        self.workers=[]

    async def asyncTearDown(self):
        for worker in self.workers:worker.close()
        await asyncio.to_thread(self.owner.close)
        self.temp.cleanup()

    async def checkpoint_worker(self):
        worker=CheckpointWorker(self.owner,self.path);self.workers.append(worker)
        await asyncio.shield(asyncio.wrap_future(worker.ready))
        return worker

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
        with patch('meme_machine.solana_checkpoint.checkpoint_and_reclaim',side_effect=delayed):
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

    async def test_completed_io_releases_owner_while_asyncio_coordinator_is_occupied(self):
        await self.work(lambda s:s.writer.ingest(self.rows(1)))
        worker=await self.checkpoint_worker()
        entered=threading.Event();release=threading.Event();io_completed=threading.Event()
        committed=threading.Event()
        def delayed(path):
            entered.set()
            if not release.wait(5):raise TimeoutError('test release')
            result=checkpoint_and_reclaim(path)
            io_completed.set()
            return result
        def mutation(state):
            result=state.writer.ingest(self.rows(2));committed.set()
            return result
        with patch('meme_machine.solana_checkpoint.checkpoint_and_reclaim',side_effect=delayed):
            task=asyncio.create_task(reclaim_at_boundary(self.owner,self.path,worker=worker))
            await self.wait_event(entered)
            later=self.owner.submit(mutation,priority=0)
            try:
                # Real unfinished I/O must retain the exact mutation boundary.
                await asyncio.sleep(.02)
                self.assertFalse(later.done());self.assertFalse(committed.is_set())
                release.set()
                # Deliberately occupy this loop: no coordinator continuation or
                # asyncio Future callback can release the boundary during wait.
                completed_without_loop=committed.wait(1)
                self.assertTrue(io_completed.is_set(),'physical checkpoint did not complete')
                self.assertTrue(completed_without_loop,
                    'finished checkpoint retained owner until asyncio resumed')
                self.assertFalse(task.done(),'fixture did not occupy the result coordinator')
                later.result(timeout=1)
            finally:
                release.set()
                await task
                await asyncio.wrap_future(later)
        self.assertEqual(await self.work(lambda s:s.writer.db.execute('SELECT COUNT(*) FROM records').fetchone()[0]),32)

    async def test_ready_checkpoint_worker_does_not_borrow_saturated_default_executor(self):
        await self.work(lambda s:s.writer.ingest(self.rows(1)))
        worker=await self.checkpoint_worker()
        entered=threading.Event();release=threading.Event();threads=[]
        executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='blocked-checkpoint-test')
        asyncio.get_running_loop().set_default_executor(executor)
        def occupy():
            threads.append(threading.get_ident());entered.set()
            if not release.wait(5):raise TimeoutError('test release')
        blocker=asyncio.get_running_loop().run_in_executor(None,occupy)
        self.assertTrue(entered.wait(1),'default executor was not occupied')
        task=asyncio.create_task(reclaim_at_boundary(self.owner,self.path,worker=worker))
        try:
            done,_=await asyncio.wait({task},timeout=1)
            self.assertIn(task,done,'checkpoint queued behind unrelated default-executor work')
            self.assertEqual(await task,(0,0,0))
            self.assertFalse(blocker.done(),'default executor was released before discriminator')
            self.assertNotIn(worker.thread.ident,threads)
            await self.work(lambda s:s.writer.ingest(self.rows(2)),priority=0)
        finally:
            release.set()
            await blocker
            await task
        self.assertEqual(await self.work(lambda s:s.writer.db.execute('SELECT COUNT(*) FROM records').fetchone()[0]),32)

    async def test_closed_ready_worker_consumes_queued_grant_without_io(self):
        worker=await self.checkpoint_worker()
        entered=threading.Event();release=threading.Event()
        def older(state):
            entered.set()
            if not release.wait(5):raise TimeoutError('test release')
        preceding=self.owner.submit(older,priority=2);await self.wait_event(entered)
        job=worker.prepare()
        accepted=self.owner.submit(lambda state:worker.grant(job),priority=2)
        with patch('meme_machine.solana_checkpoint.checkpoint_and_reclaim') as io:
            try:
                worker.close()
                self.assertFalse(worker.thread.is_alive())
                with self.assertRaisesRegex(EvidenceUnavailable,'checkpoint_worker_unavailable'):
                    worker.prepare()
            finally:release.set()
            await asyncio.wrap_future(preceding)
            self.assertFalse(await asyncio.wrap_future(accepted))
            self.assertIsNone(await asyncio.wrap_future(job.result))
            io.assert_not_called()
        self.assertEqual(self.owner.telemetry().get('checkpoint_handoffs',0),0)
        await self.work(lambda s:s.writer.ingest(self.rows(1)),priority=0)

    async def test_queued_cancellation_precedes_grant_without_coordinator_resumption(self):
        worker=await self.checkpoint_worker()
        entered=threading.Event();release=threading.Event();consumed=threading.Event()
        def older(state):
            entered.set()
            if not release.wait(5):raise TimeoutError('test release')
        preceding=self.owner.submit(older,priority=2);await self.wait_event(entered)
        with patch('meme_machine.solana_checkpoint.checkpoint_and_reclaim',return_value=(0,0,0)) as io:
            task=asyncio.create_task(reclaim_at_boundary(self.owner,self.path,worker=worker))
            later=None
            try:
                deadline=time.monotonic()+1
                while not self.owner.telemetry()['queued'] and time.monotonic()<deadline:
                    if task.done():await task
                    await asyncio.sleep(.001)
                self.assertEqual(self.owner.telemetry()['queued'],1,'handoff was not admitted behind older work')
                later=self.owner.submit(lambda state:consumed.set(),priority=2)
                task.cancel();release.set()
                # Owner must consume the canceled grant while this coroutine is
                # still occupied, before it can catch CancelledError itself.
                self.assertTrue(consumed.wait(1),'owner did not consume the admitted handoff')
                io.assert_not_called()
            finally:
                release.set()
                with self.assertRaises(asyncio.CancelledError):await task
                await asyncio.wrap_future(preceding)
                if later is not None:await asyncio.wrap_future(later)
        self.assertEqual(self.owner.telemetry().get('checkpoint_handoffs',0),0)

    async def test_service_retains_late_passive_io_error_and_joins_before_writer_close(self):
        await self.late_passive_service_error()

    async def test_service_repeated_cancellation_still_joins_late_passive_io_error(self):
        await self.late_passive_service_error(repeat_cancel=True)

    async def late_passive_service_error(self,*,repeat_cancel=False):
        from meme_machine import solana_evidence_service as service
        from tests.evidence_ipc_harness import ipc_transport
        from tests.maintenance_production_harness import NativeCompletionPool
        from tests.test_solana_prewarm_startup import quiet_model_b
        loop=asyncio.get_running_loop();stop=asyncio.Event();entered=asyncio.Event()
        release=threading.Event();io_completed=threading.Event();owners=[];workers=[]
        failure=OSError('late checkpoint I/O fixture')
        owner_init=PriorityOwner.__init__;owner_close=PriorityOwner.close
        worker_init=CheckpointWorker.__init__
        def tracked_owner(owner,*args,**kwargs):
            owner_init(owner,*args,**kwargs);owners.append(owner)
        def tracked_worker(worker,*args,**kwargs):
            worker_init(worker,*args,**kwargs);workers.append(worker)
        def close_owner(owner):
            self.assertTrue(io_completed.is_set(),'writer closed before accepted PASSIVE completed')
            self.assertTrue(workers and all(not worker.thread.is_alive() for worker in workers),
                'writer closed before dedicated checkpoint worker joined')
            return owner_close(owner)
        def passive(path):
            loop.call_soon_threadsafe(entered.set)
            if not release.wait(5):raise TimeoutError('test release')
            io_completed.set();raise failure
        async def driver(work,stop):
            boot=asyncio.Event();boot.set();await quiet_model_b(work,boot)
            await stop.wait()
        path=Path(self.temp.name)/'service-db'
        with ipc_transport(),patch('concurrent.futures.ProcessPoolExecutor',NativeCompletionPool), \
                patch.object(PriorityOwner,'__init__',tracked_owner), \
                patch.object(PriorityOwner,'close',close_owner), \
                patch.object(CheckpointWorker,'__init__',tracked_worker), \
                patch.object(EvidenceWriter,'checkpoint',side_effect=passive):
            runner=asyncio.create_task(service.serve(path,
                'https://solana-mainnet.g.alchemy.com/v2/offline-test',stop=stop,source_driver=driver))
            try:
                await asyncio.wait_for(entered.wait(),3)
                stop.set();checkpoint_tasks=[];deadline=time.monotonic()+3
                while time.monotonic()<deadline:
                    checkpoint_tasks=[task for task in asyncio.all_tasks()
                        if task.get_coro().__qualname__=='serve.<locals>.checkpoint']
                    if checkpoint_tasks and checkpoint_tasks[0].cancelling():break
                    if runner.done():await runner
                    await asyncio.sleep(.001)
                self.assertEqual(len(checkpoint_tasks),1,'service checkpoint task was not retained')
                self.assertTrue(checkpoint_tasks[0].cancelling(),'shutdown did not cancel accepted PASSIVE waiter')
                if repeat_cancel:
                    checkpoint_tasks[0].cancel()
                    runner.cancel()
                    await asyncio.sleep(0)
                self.assertFalse(runner.done());self.assertFalse(io_completed.is_set())
                release.set()
                with self.assertRaises(OSError) as caught:
                    await asyncio.wait_for(asyncio.shield(runner),3)
                self.assertIs(caught.exception,failure,'original physical I/O exception was replaced')
            finally:
                stop.set();release.set()
                if not runner.done():runner.cancel()
                await asyncio.gather(runner,return_exceptions=True)
        self.assertTrue(owners and all(not owner.thread.is_alive() for owner in owners))
        self.assertTrue(workers and all(not worker.thread.is_alive() for worker in workers))
        self.assertFalse(Path(str(path)+'.sock').exists())
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(json.loads(db.execute("SELECT value FROM service_health WHERE key='phase'").fetchone()[0]),'FAILED')
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone(),('ok',))

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
        with patch('meme_machine.solana_checkpoint.checkpoint_and_reclaim',side_effect=OSError('injected disk')):
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
        with patch('meme_machine.solana_checkpoint.checkpoint_and_reclaim') as io:
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
        with patch('meme_machine.solana_checkpoint.checkpoint_and_reclaim',side_effect=delayed):
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
