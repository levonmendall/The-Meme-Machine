"""Production serve()/native SQLite integration and conditional liveness tests."""
import asyncio
from concurrent.futures import Future
from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

from meme_machine import solana_maintenance_runtime as production
from meme_machine.solana_maintenance_arbiter import ClockModel,MaintenanceArbiter,Need,ServiceLeases
from meme_machine.solana_evidence_plane import EvidenceUnavailable,EvidenceWriter
from meme_machine.solana_retention_outcome import RetentionOutcome
from tests.maintenance_production_harness import (SCOPES,Clock,rows,ingest,seed_book,run_case,NativeCompletionPool)


class ProductionServeTests(unittest.IsolatedAsyncioTestCase):
    def healthy(self,box):
        self.assertFalse(box['errors'],[str(x) for x in box['errors']])
        self.assertEqual(box['integrity'],'ok')
        self.assertIsNone(box['runtime'].failure)
        self.assertLessEqual(box['pool'].max_inflight,1)
        self.assertTrue(all(n<=512 for side,_,n in box['operations'] if side=='archive'))
        self.assertLessEqual(len(box['runtime'].ring),64)
        for v in box['runtime'].arbiter.max_gap.values():
            self.assertLess(v,box['runtime'].leases.drought)
        for v in box['runtime'].arbiter.max_scope_gap.values():
            self.assertLess(v,box['runtime'].leases.drought)

    async def test_continuous_archive_pressure_low_retirement_debt(self):
        def seed(s,c):seed_book(s,c,hot=(15000,0,0),retired=(1,0,0),same_slot=True)
        box=await run_case(seed=seed,turns=26)
        self.healthy(box)
        sides=[s for s,_,_ in box['operations']]
        self.assertIn('retirement',sides)
        self.assertGreater(sides.count('archive'),sides.count('retirement'))
        self.assertTrue(any(a==b=='archive' for a,b in zip(sides,sides[1:])),sides)

    async def test_continuous_retirement_debt_with_ready_archive(self):
        def seed(s,c):seed_book(s,c,hot=(100,100,100),retired=(6000,6000,6000))
        box=await run_case(seed=seed,turns=18)
        self.healthy(box)
        self.assertGreater(box['counters'].get('compacted_records',0),0)
        self.assertGreater(box['counters'].get('archived_records',0),18000)
        sides=[s for s,_,_ in box['operations']]
        self.assertTrue(any(a==b=='retirement' for a,b in zip(sides,sides[1:])),sides)

    async def test_simultaneous_high_debt_and_three_scopes(self):
        box=await run_case(seed=lambda s,c:seed_book(s,c,hot=(3500,3500,3500),retired=(2500,2500,2500)),turns=36)
        self.healthy(box)
        for scope in SCOPES:
            self.assertGreater(box['counters'].get('lifecycle.archived.'+scope,0),2500)
            self.assertGreater(box['counters'].get('lifecycle.retired.'+scope,0),0)
            self.assertIn(('archive',scope),box['runtime'].arbiter.max_scope_gap)
            self.assertIn(('retirement',scope),box['runtime'].arbiter.max_scope_gap)

    async def test_changing_debt_dominance(self):
        def after(r,f,result,b):
            if b['turns']==8:
                ingest(r.writer,rows(b['clock'],SCOPES[1],4000,start=3_000_000,tag='second',same_slot=True))
                ingest(r.writer,rows(b['clock'],SCOPES[1],1,start=4_000_000,tag='fresh',age=0))
        box=await run_case(seed=lambda s,c:seed_book(s,c,hot=(1200,0,0),retired=(4000,0,0)),after=after,turns=28)
        self.healthy(box)
        self.assertGreater(box['counters'].get('lifecycle.archived.'+SCOPES[1],0),1000)
        self.assertGreater(box['counters'].get('lifecycle.retired.'+SCOPES[0],0),0)

    async def test_source_urgent_foreground_arrivals_preserve_priority(self):
        queued=[];order=[]
        def before(r,f,b):
            if not queued and f.pending:
                def run(name):
                    def callback(state):
                        order.append(name)
                        if name=='source':
                            with state.writer.transaction():state.writer._count('test_source_durable')
                    return callback
                queued.extend(b['owner'].submit(run(name),priority=p)
                    for name,p in [('source',2),('foreground',1),('urgent',0)])
        box=await run_case(seed=lambda s,c:seed_book(s,c,hot=(1700,0,0)),before=before,turns=15)
        self.healthy(box)
        self.assertEqual(order[:3],['urgent','foreground','source'])
        self.assertEqual(box['counters'].get('test_source_durable'),1)
        self.assertTrue(all(f.done() and f.exception() is None for f in queued))

    async def test_held_reader_source_and_retirement_interaction(self):
        reader=[None];baseline=[None];seen=[]
        def before(r,f,b):
            if reader[0] is None:
                reader[0]=sqlite3.connect(b['path'],isolation_level=None,check_same_thread=False)
                reader[0].execute('BEGIN')
                baseline[0]=dict(reader[0].execute('SELECT key,value FROM counters'))
        def after(r,f,result,b):
            if result.get('side')=='retirement':
                self.assertEqual(dict(reader[0].execute('SELECT key,value FROM counters')),baseline[0])
                now=dict(r.writer.db.execute('SELECT key,value FROM counters'))
                if now.get('compacted_records',0)>baseline[0].get('compacted_records',0):seen.append(now)
        try:
            box=await run_case(seed=lambda s,c:seed_book(s,c,hot=(2000,2000,2000),retired=(800,800,800)),before=before,after=after,turns=24)
            self.healthy(box)
            self.assertTrue(seen)
            self.assertGreater(box['counters'].get('stream_accepted_messages',0),0)
        finally:
            if reader[0]:reader[0].execute('ROLLBACK');reader[0].close()

    async def test_scope_fairness_under_new_dense_meteora_arrivals(self):
        def after(r,f,result,b):
            if b['turns']<18:
                ingest(r.writer,rows(b['clock'],SCOPES[0],128,start=3_000_000+b['turns']*128,tag='continuous'))
        box=await run_case(seed=lambda s,c:seed_book(s,c,hot=(1000,1000,1000),retired=(1000,1000,1000)),after=after,turns=30)
        self.healthy(box)
        for scope in SCOPES:
            self.assertGreater(box['counters'].get('lifecycle.archived.'+scope,0),1000)
            self.assertGreater(box['counters'].get('lifecycle.retired.'+scope,0),0)

    async def test_pins_floors_and_continuity_are_not_zero_debt(self):
        from meme_machine.solana_evidence_plane import IntervalProof,digest
        def seed(s,c):
            seed_book(s,c,hot=(400,0,0),retired=(200,0,0))
            s.writer.interest('pinned',SCOPES[0],lower_slot=1000,priority=0,lifecycle='open')
            proof=IntervalProof(SCOPES[0],10,99,'alchemy_finalized_stream','a'*64,
                dict(finalized=True,complete=True,scope=SCOPES[0],lower_slot=10,upper_slot=99,lineage_hash=digest(['old'])),c.time()-200)
            s.writer.ingest([],proof=proof)
        box=await run_case(seed=seed,turns=4)
        self.healthy(box)
        m=next(s for s in box['runtime'].last_observation.scopes if s.scope==SCOPES[0])
        self.assertEqual(m.pins,1)
        self.assertEqual(m.hot_eligible,0)
        self.assertEqual(m.retirement_eligible,0)
        self.assertLessEqual(m.floor,1000)
        self.assertEqual(box['counters'].get('archived_records',0),200)
        self.assertEqual(box['counters'].get('compacted_records',0),200)
        self.assertGreater(box['counters'].get('lifecycle.continuity.'+SCOPES[0],0),0)

    async def test_stale_observation_fails_before_mutation(self):
        def before(r,f,b):
            native=r.adapter.observe
            r.adapter.observe=lambda g:replace(native(g),monotonic=b['clock'].monotonic()-10)
        # Cold-start observation can yield the owner to source/control work
        # before this injected observation is read. Permit that bounded retry;
        # the stale observation must still fail before any archive mutation.
        box=await run_case(seed=lambda s,c:seed_book(s,c,hot=(100,0,0)),before=before,turns=3)
        self.assertTrue(box['errors'])
        self.assertEqual(box['counters'].get('archived_records',0),0)
        self.assertTrue(box['runtime'].failure)

    async def test_generation_change_revokes_old_runtime(self):
        def before(r,f,b):r.state.fence.session='superseding-generation'
        box=await run_case(seed=lambda s,c:seed_book(s,c,hot=(100,0,0)),before=before,turns=1)
        self.assertTrue(any('generation_changed' in str(e) for e in box['errors']))
        self.assertEqual(box['counters'].get('archived_records',0),0)

    async def test_zero_durable_progress_never_renews_success(self):
        def zero(s,plan,receipt,native,b):
            b['clock'].advance(1)
            return plan,None
        box=await run_case(seed=lambda s,c:seed_book(s,c,hot=(100,0,0)),archive_hook=zero,turns=60)
        self.assertTrue(box['errors'])
        self.assertEqual(box['counters'].get('archived_records',0),0)
        self.assertEqual(box['runtime'].arbiter.max_gap['archive'],0)
        self.assertLess(box['turns'],60)

    async def test_archive_worker_failure_is_terminal_not_a_second_publication(self):
        class Broken(NativeCompletionPool):
            def submit(self,fn,*args,**kwargs):
                if fn is EvidenceWriter.prepare_and_write_archive:
                    self.submissions.append(args[1]);f=Future();f.set_exception(OSError('worker unavailable'));return f
                return super().submit(fn,*args,**kwargs)
        box=await run_case(seed=lambda s,c:seed_book(s,c,hot=(100,0,0)),pool_class=Broken,turns=10)
        self.assertTrue(any('worker unavailable' in str(e) for e in box['errors']))
        self.assertEqual(len(box['pool'].submissions),1)

    async def test_near_safety_deadline_has_no_fabricated_reservation(self):
        def seed(s,c):
            s.writer.clock=c.time
            ingest(s.writer,rows(c,SCOPES[0],10,age=236))
        box=await run_case(seed=seed,turns=1)
        self.assertTrue(box['errors'])
        self.assertEqual(box['counters'].get('archived_records',0),0)
        self.assertFalse(box['operations'])

    async def test_queue_expiry_does_not_change_native_records(self):
        def before(r,f,b):b['clock'].advance(4)
        box=await run_case(seed=lambda s,c:seed_book(s,c,hot=(100,0,0)),before=before,turns=1)
        self.assertTrue(any('owner_lease_exceeded' in str(e) for e in box['errors']))
        self.assertEqual(box['counters'].get('archived_records',0),0)

    async def test_restart_preserves_active_recovery_deadline(self):
        clock=Clock()
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'db'
            first=await run_case(seed=lambda s,c:seed_book(s,c,hot=(5000,0,0),same_slot=True),clock=clock,path=path,turns=2)
            self.healthy(first)
            self.assertTrue(first['episodes'])
            second=await run_case(clock=clock,path=path,turns=2)
            self.healthy(second)
            self.assertEqual(first['episodes'],second['episodes'])
            self.assertNotEqual(first['runtime'].generation,second['runtime'].generation)





from contextlib import contextmanager
from meme_machine import solana_evidence_service as service
from meme_machine.solana_provider_config import AlchemyEndpoint
from meme_machine.solana_maintenance_state import DebtAgeAdapter, progress as durable_progress
from tests.maintenance_production_harness import ENDPOINT


def finalized_frontier(state, clock, scope, *, slot=2_000_000, at=None):
    """Use the native finalized-block validator, not a synthetic demand value."""
    sub = next(s for s in service.program_subscriptions()
               if s.scope == scope and s.evidence_class in ('census','transactions'))
    timestamp = int(clock.time()) if at is None else at
    state.fence.block(sub, dict(params=dict(result=dict(value=dict(
        slot=slot, err=None, block=dict(parentSlot=slot-1, blockhash=f'h{slot}',
        previousBlockhash=f'h{slot-1}', blockTime=timestamp, transactions=[]))))), clock.time())


@contextmanager
def native_runtime(clock=None, path=None):
    clock = clock or Clock()
    with tempfile.TemporaryDirectory() as td, patch.object(service, 'time', clock):
        state = service.ServiceState(path or Path(td)/'db', AlchemyEndpoint.parse(ENDPOINT))
        state.writer.clock = clock.time
        try:
            yield state, production.MaintenanceRuntime(state, monotonic=clock.monotonic,
                                                        wall=clock.time), clock
        finally:
            state.close()


def orphan_chunk(writer, key):
    with writer.transaction():
        writer.db.execute('INSERT INTO hot_chunks VALUES(?,?)', (key,b'orphan-test'))


class AdapterCorrectionsTests(unittest.TestCase):
    def test_repeated_native_housekeeping_renews_its_own_service_not_first_sighting(self):
        with native_runtime() as (state,r,clock):
            flight = production.ArchiveFlight()
            for i in range(40):
                orphan_chunk(state.writer, str(i))
                result = r.turn(flight,clock.monotonic())
                self.assertEqual(result['side'],'retirement')
                self.assertEqual(r.ring[-1]['durable_progress'].get('__housekeeping__'),1)
                self.assertFalse(r.ring[-1]['durable_records'])
                clock.advance(2)
            ledger = state.writer.db.execute("SELECT units,records FROM maintenance_progress WHERE scope='__housekeeping__' AND side='retirement'").fetchone()
            self.assertEqual(ledger,(40,0))
            self.assertLess(r.arbiter.max_scope_gap['retirement','__housekeeping__'],r.leases.drought)

    def test_scoped_progress_cannot_renew_housekeeping_obligation(self):
        with native_runtime() as (state,r,clock):
            orphan_chunk(state.writer,'never-serviced')
            def demand():
                return next(n for n in r._demands(r.adapter.observe(r.generation))
                            if n.scope=='__housekeeping__')
            before=demand().safety_deadline
            clock.advance(4)
            with state.writer.transaction():
                durable_progress(state.writer,SCOPES[0],'retirement',3,2)
            self.assertEqual(demand().safety_deadline,before)
            self.assertIsNone(state.writer.db.execute("SELECT 1 FROM maintenance_progress WHERE scope='__housekeeping__'").fetchone())

    def test_housekeeping_rollback_cannot_report_durable_service(self):
        with native_runtime() as (state,r,clock):
            orphan_chunk(state.writer,'rollback')
            with self.assertRaisesRegex(RuntimeError,'rollback'):
                with state.writer.transaction():
                    state.writer.db.execute('DELETE FROM hot_chunks')
                    durable_progress(state.writer,'__housekeeping__','retirement',1)
                    raise RuntimeError('rollback')
            self.assertEqual(state.writer.db.execute('SELECT COUNT(*) FROM hot_chunks').fetchone()[0],1)
            self.assertEqual(state.writer.db.execute('SELECT COUNT(*) FROM maintenance_progress').fetchone()[0],0)

    def test_gc_does_not_renew_unserviced_record_retirement(self):
        with native_runtime() as (state,r,clock):
            needs=[Need(SCOPES[0],'retirement',11,10,100,None,0)]
            before={}
            with state.writer.transaction():
                durable_progress(state.writer,SCOPES[0],'retirement',1,0)
                durable_progress(state.writer,'__housekeeping__','retirement',2,0)
            progress,records=r._native_progress(before,needs,'retirement')
            self.assertEqual(progress[SCOPES[0]],0)
            self.assertEqual(progress['__housekeeping__'],2)
            self.assertEqual(records,{})

    def test_durable_frontier_survives_all_receipt_and_hot_record_removal(self):
        with native_runtime() as (state,r,clock):
            ingest(state.writer,rows(clock,SCOPES[0],1500,same_slot=True))
            while state.writer.archive(clock.time()-180):pass
            finalized_frontier(state,clock,SCOPES[0])
            with state.writer.transaction():state.writer.db.execute('DELETE FROM stream_receipts')
            observation=r.adapter.observe(r.generation)
            scope=next(s for s in observation.scopes if s.scope==SCOPES[0])
            self.assertEqual(scope.source_time,clock.time())
            self.assertEqual(scope.retirement_eligible,1500)
            need=next(n for n in r._demands(observation) if n.side=='retirement' and n.scope==SCOPES[0])
            self.assertEqual(need.recovery_deadline,r.clock.project(clock.time()+120))

    def test_receipts_alone_are_not_the_recovery_clock_authority(self):
        with native_runtime() as (state,r,clock):
            ingest(state.writer,rows(clock,SCOPES[0],1200,same_slot=True))
            finalized_frontier(state,clock,SCOPES[0])
            with state.writer.transaction():
                state.writer.db.execute('DELETE FROM service_health WHERE key=?',('finalized_frontier:'+SCOPES[0],))
            scope=next(s for s in r.adapter.observe(r.generation).scopes if s.scope==SCOPES[0])
            self.assertIsNone(scope.source_time)
            with self.assertRaisesRegex(EvidenceUnavailable,'recovery_source_unavailable'):
                r._demands(r.adapter.observe(r.generation))

    def test_malformed_or_future_frontier_is_not_replaced_by_receipts(self):
        for invalid in ('{', '{}', 'null', '{"slot":1,"time":true,"seen":1800000000}',
                        '{"slot":1,"time":1800000001,"seen":1800000000}',
                        '{"slot":1,"time":1800000000,"seen":1800000001}'):
            with self.subTest(invalid=invalid),native_runtime() as (state,r,clock):
                finalized_frontier(state,clock,SCOPES[0])
                with state.writer.transaction():
                    state.writer.db.execute('UPDATE service_health SET value=? WHERE key=?',
                                           (invalid,'finalized_frontier:'+SCOPES[0]))
                with self.assertRaisesRegex(EvidenceUnavailable,'frontier'):
                    r.adapter.observe(r.generation)

    def test_restart_receipt_removal_preserves_latched_deadline(self):
        clock=Clock()
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'db'
            with native_runtime(clock,path) as (state,r,clock):
                ingest(state.writer,rows(clock,SCOPES[0],1500,same_slot=True))
                while state.writer.archive(clock.time()-180):pass
                finalized_frontier(state,clock,SCOPES[0])
                r._demands(r.adapter.observe(r.generation))
                original=dict(r.episodes)
                with state.writer.transaction():state.writer.db.execute('DELETE FROM stream_receipts')
                generation=r.generation
            clock.advance(2)
            with native_runtime(clock,path) as (state,r,clock):
                self.assertNotEqual(r.generation,generation)
                r._demands(r.adapter.observe(r.generation))
                self.assertEqual(r.episodes,original)
                self.assertEqual(r.clock.source[SCOPES[0]],clock.time()-2)
                clock.advance(121)
                with self.assertRaises(EvidenceUnavailable):r.turn(production.ArchiveFlight(),clock.monotonic())


class HousekeepingRestartTests(unittest.TestCase):
    def test_restart_does_not_gift_unserviced_housekeeping_a_new_deadline(self):
        clock=Clock()
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'db'
            with native_runtime(clock,path) as (state,r,clock):
                orphan_chunk(state.writer,'still-unserviced')
                first=next(n.safety_deadline for n in r._demands(r.adapter.observe(r.generation)) if n.scope=='__housekeeping__')
            clock.advance(30)
            with native_runtime(clock,path) as (state,r,clock):
                after=next(n.safety_deadline for n in r._demands(r.adapter.observe(r.generation)) if n.scope=='__housekeeping__')
                self.assertLessEqual(after,first,'restart extended an outstanding housekeeping obligation')
                clock.advance(20)
                with self.assertRaises(EvidenceUnavailable):r.turn(production.ArchiveFlight(),clock.monotonic())

    def test_observed_empty_ends_old_housekeeping_obligation(self):
        with native_runtime() as (state,r,clock):
            flight=production.ArchiveFlight()
            orphan_chunk(state.writer,'first')
            self.assertEqual(r.turn(flight,clock.monotonic())['side'],'retirement')
            self.assertIsNone(r.turn(flight,clock.monotonic())['side'])
            clock.advance(60)
            orphan_chunk(state.writer,'new-later-work')
            result=r.turn(flight,clock.monotonic())
            self.assertEqual(result['side'],'retirement')
            self.assertEqual(r.ring[-1]['durable_progress'].get('__housekeeping__'),1)
            self.assertIsNone(r.failure)


class FrontierCurrentnessTests(unittest.TestCase):
    def test_missing_current_frontier_cannot_borrow_prior_observation(self):
        with native_runtime() as (state,r,clock):
            ingest(state.writer,rows(clock,SCOPES[0],1500,same_slot=True))
            finalized_frontier(state,clock,SCOPES[0])
            r._demands(r.adapter.observe(r.generation))
            original=dict(r.episodes)
            with state.writer.transaction():
                state.writer.db.execute('DELETE FROM service_health WHERE key=?',
                                        ('finalized_frontier:'+SCOPES[0],))
                state.writer.db.execute('DELETE FROM stream_receipts')
            with self.assertRaisesRegex(EvidenceUnavailable,'recovery_source_unavailable'):
                r._demands(r.adapter.observe(r.generation))
            self.assertEqual(r.episodes,original,'missing state must not erase or restart an episode')

    def test_stalled_then_catching_up_frontier_does_not_extend_recovery_deadline(self):
        with native_runtime() as (state,r,clock):
            ingest(state.writer,rows(clock,SCOPES[0],1500,same_slot=True))
            finalized_frontier(state,clock,SCOPES[0],at=int(clock.time()-20))
            first=r._demands(r.adapter.observe(r.generation))
            deadline=next(n.recovery_deadline for n in first if n.scope==SCOPES[0] and n.side=='archive')
            # The 20-second-late frontier leaves <120 wall-seconds, even when
            # source delivery subsequently stalls or catches up in one block.
            self.assertEqual(deadline,100-r.leases.clock_error)
            clock.advance(10)
            second=r._demands(r.adapter.observe(r.generation))
            self.assertEqual(next(n.recovery_deadline for n in second if n.scope==SCOPES[0] and n.side=='archive'),deadline)
            finalized_frontier(state,clock,SCOPES[0],slot=2_000_001)
            third=r._demands(r.adapter.observe(r.generation))
            self.assertEqual(next(n.recovery_deadline for n in third if n.scope==SCOPES[0] and n.side=='archive'),deadline)


class AdapterServeCorrectionsTests(unittest.IsolatedAsyncioTestCase):
    async def test_continuous_housekeeping_in_actual_serve_uses_own_progress(self):
        def seed(state,clock):
            state.writer.clock=clock.time
            orphan_chunk(state.writer,'initial')
        def after(runtime,flight,result,box):
            orphan_chunk(runtime.writer,'turn-'+str(box['turns']))
            box['clock'].advance(2)
        box=await run_case(seed=seed,after=after,turns=30)
        self.assertFalse(box['errors'],[str(e) for e in box['errors']])
        self.assertGreater(box['clock'].monotonic(),box['runtime'].leases.drought)
        progress=[row for row in box['native_progress'] if row[:2]==('__housekeeping__','retirement')]
        self.assertEqual(len(progress),1)
        self.assertGreaterEqual(progress[0][3],30)
        self.assertEqual(progress[0][5],0,'housekeeping must not become record progress')
        self.assertLess(box['runtime'].arbiter.max_scope_gap['retirement','__housekeeping__'],box['runtime'].leases.drought)
        self.assertFalse(any(side=='archive' for side,_,_ in box['operations']))

    async def test_receipt_removal_during_native_serve_keeps_durable_clock(self):
        seen=[]
        def seed(state,clock):seed_book(state,clock,hot=(2000,2000,2000),retired=(1500,1500,1500))
        def before(runtime,flight,box):
            with runtime.writer.transaction():runtime.writer.db.execute('DELETE FROM stream_receipts')
        def after(runtime,flight,result,box):
            seen.extend(s.source_time for s in runtime.last_observation.scopes if s.scope in SCOPES)
        box=await run_case(seed=seed,before=before,after=after,turns=28)
        self.assertFalse(box['errors'],[str(e) for e in box['errors']])
        self.assertTrue(seen)
        self.assertTrue(all(t is not None for t in seen))
        for scope in SCOPES:
            self.assertGreater(box['counters'].get('lifecycle.archived.'+scope,0),1500)
            self.assertGreater(box['counters'].get('lifecycle.retired.'+scope,0),0)
        self.assertEqual(box['integrity'],'ok')

    async def test_actual_serve_restart_without_receipts_keeps_episode_identity(self):
        clock=Clock()
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'db'
            first=await run_case(seed=lambda s,c:seed_book(s,c,hot=(6000,0,0),same_slot=True),turns=4,clock=clock,path=path)
            self.assertFalse(first['errors'],[str(e) for e in first['errors']])
            episodes=dict(first['runtime'].episodes)
            self.assertIn(('archive',SCOPES[0]),episodes)
            with closing(sqlite3.connect(path)) as db:
                db.execute('DELETE FROM stream_receipts');db.commit()
            clock.advance(2)
            second=await run_case(turns=2,clock=clock,path=path)
            self.assertFalse(second['errors'],[str(e) for e in second['errors']])
            self.assertNotEqual(first['runtime'].generation,second['runtime'].generation)
            self.assertEqual(second['runtime'].episodes[('archive',SCOPES[0])],episodes[('archive',SCOPES[0])])
            self.assertEqual(second['integrity'],'ok')


class ReceiptFinalizationServeTests(unittest.IsolatedAsyncioTestCase):
    async def test_final_durable_slice_yield_keeps_one_receipt_until_acknowledged(self):
        attempts=[]
        def archive(state,plan,receipt,native,box):
            attempts.append(receipt)
            if len(attempts)==1:
                state.archive_commit(plan[:512],receipt,retain=False)
                raise EvidenceUnavailable('evidence_background_yield')
            return native()
        box=await run_case(seed=lambda s,c:seed_book(s,c,hot=(40,0,0)),
                           archive_hook=archive,turns=6)
        self.assertFalse(box['errors'],[str(e) for e in box['errors']])
        self.assertGreaterEqual(len(attempts),2,'committed receipt lost its completion admission')
        self.assertIs(attempts[0],attempts[1])
        self.assertEqual(len(box['pool'].submissions),1)
        self.assertEqual(box['counters'].get('archived_records'),40)
        events=[e for e in box['runtime'].ring if e['selected']=='archive']
        self.assertEqual(sum(sum(e.get('durable_records',{}).values()) for e in events),40,
                         'idempotent finalization fabricated archive progress')
        self.assertFalse(box['runtime'].failure)


if __name__=='__main__':unittest.main()
