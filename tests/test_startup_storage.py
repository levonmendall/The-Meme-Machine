import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from meme_machine.startup_storage import recover
from meme_machine.solana_evidence_plane import EvidenceWriter,EvidenceReader
from meme_machine.solana_evidence_service import FinalizedFence, ServiceState
from tests.test_solana_evidence_plane import record,proof


class StartupStorage(unittest.IsolatedAsyncioTestCase):
    async def test_cooperative_yields_do_not_restart_the_recovery_window(self):
        from meme_machine.solana_evidence_plane import EvidenceUnavailable
        elapsed=[0]
        async def work(fn,priority,**kwargs):
            elapsed[0]+=1
            raise EvidenceUnavailable('evidence_background_yield')
        with self.assertRaisesRegex(EvidenceUnavailable,'maintenance_startup_recovery_incomplete'):
            await recover(work,None,None,asyncio.Event(),monotonic=lambda:elapsed[0])
        self.assertEqual(elapsed[0],60)

    async def test_dense_released_evidence_recovers_with_bounded_source_queue_waits(self):
        from tests.test_production_maintenance_arbiter import native_runtime,finalized_frontier
        from tests.maintenance_production_harness import rows,ingest,SCOPES
        from meme_machine.solana_maintenance_runtime import ArchiveFlight
        with native_runtime() as (state,runtime,clock):
            runtime.turn(ArchiveFlight(),clock.monotonic())
            values=rows(clock,SCOPES[0],18000,age=1800,same_slot=True)
            ingest(state.writer,values);finalized_frontier(state,clock,SCOPES[0])
            flight=ArchiveFlight()
            self.assertTrue(runtime.turn(flight,clock.monotonic())['cold_recovery_required'])
            started=clock.monotonic()
            async def work(fn,priority,**kwargs):
                # Bounded ordinary source work ahead of every owner admission.
                # The prior separate observe/plan/retention round trips exhaust
                # the same real 60-second recovery window for this finite burst.
                clock.advance(.8)
                return fn(state)
            with ThreadPoolExecutor(max_workers=1) as pool:
                await recover(work,pool,state.writer.path,asyncio.Event(),wall=clock.time,
                    monotonic=clock.monotonic,force=True,flight=flight,clock=runtime.clock,
                    on_complete=lambda s,o:runtime.cold_completed(o,flight))
            self.assertLess(clock.monotonic()-started,60)
            self.assertFalse(state.writer.db.execute('SELECT 1 FROM records').fetchone())
            self.assertEqual(state.writer.db.execute(
                "SELECT value FROM counters WHERE key='archived_records'").fetchone()[0],len(values))
            self.assertEqual(state.writer.db.execute('PRAGMA quick_check').fetchone()[0],'ok')
            self.assertTrue(flight.idle)
            self.assertIsNone(runtime.arbiter.pending)

    async def test_committed_final_slice_yield_keeps_receipt_and_recovery_deadline(self):
        from tests.test_production_maintenance_arbiter import native_runtime,finalized_frontier
        from tests.maintenance_production_harness import rows,ingest,SCOPES
        from meme_machine.solana_evidence_plane import EvidenceUnavailable
        from meme_machine.solana_maintenance_runtime import ArchiveFlight
        with native_runtime() as (state,runtime,clock):
            runtime.turn(ArchiveFlight(),clock.monotonic())
            values=rows(clock,SCOPES[0],700,age=1800)
            ingest(state.writer,values);finalized_frontier(state,clock,SCOPES[0])
            flight=ArchiveFlight()
            self.assertTrue(runtime.turn(flight,clock.monotonic())['cold_recovery_required'])
            original=state.archive_commit_slice;yielded=[False]
            def commit(plan,receipt):
                remaining=original(plan,receipt)
                if not remaining and not yielded[0]:
                    yielded[0]=True
                    raise EvidenceUnavailable('evidence_background_yield')
                return remaining
            state.archive_commit_slice=commit
            async def work(fn,priority,**kwargs):
                clock.advance(.8)
                return fn(state)
            with ThreadPoolExecutor(max_workers=1) as pool:
                await recover(work,pool,state.writer.path,asyncio.Event(),wall=clock.time,
                    monotonic=clock.monotonic,force=True,flight=flight,clock=runtime.clock,
                    on_complete=lambda s,o:runtime.cold_completed(o,flight))
            self.assertTrue(yielded[0])
            self.assertEqual(state.writer.db.execute(
                "SELECT value FROM counters WHERE key='archived_records'").fetchone()[0],len(values))
            self.assertFalse(state.writer.db.execute('SELECT 1 FROM records').fetchone())
            self.assertTrue(flight.idle)
            self.assertIsNone(runtime.arbiter.pending)

    async def test_cold_cleanup_uses_the_same_conservative_clock_margin_as_completion(self):
        from tests.test_production_maintenance_arbiter import native_runtime,finalized_frontier
        from tests.maintenance_production_harness import rows,ingest,SCOPES
        from meme_machine.solana_maintenance_runtime import ArchiveFlight
        with native_runtime() as (state,runtime,clock):
            runtime.turn(ArchiveFlight(),clock.monotonic())
            ingest(state.writer,rows(clock,SCOPES[0],3,age=239))
            finalized_frontier(state,clock,SCOPES[0]);flight=ArchiveFlight()
            self.assertTrue(runtime.turn(flight,clock.monotonic())['cold_recovery_required'])
            original_error=runtime.leases.clock_error
            async def work(fn,priority,**kwargs):return fn(state)
            with ThreadPoolExecutor(max_workers=1) as pool:
                await recover(work,pool,state.writer.path,asyncio.Event(),wall=clock.time,
                    monotonic=clock.monotonic,force=True,flight=flight,clock=runtime.clock,
                    on_complete=lambda s,o:runtime.cold_completed(o,flight))
            self.assertFalse(state.writer.db.execute('SELECT 1 FROM records').fetchone())
            self.assertEqual(state.writer.db.execute("SELECT value FROM counters WHERE key='archived_records'").fetchone()[0],3)
            self.assertEqual(runtime.leases.clock_error,original_error)
            self.assertIsNone(runtime.arbiter.pending)
            self.assertIsNone(runtime.failure)

    async def test_live_young_debt_can_remain_after_real_old_cleanup_without_extending_safety(self):
        from tests.test_production_maintenance_arbiter import native_runtime,finalized_frontier
        from tests.maintenance_production_harness import rows,ingest,SCOPES
        from meme_machine.solana_maintenance_runtime import ArchiveFlight
        with native_runtime() as (state,runtime,clock):
            runtime.turn(ArchiveFlight(),clock.monotonic())
            ingest(state.writer,rows(clock,SCOPES[0],4,age=1800))
            finalized_frontier(state,clock,SCOPES[0]);flight=ArchiveFlight()
            self.assertTrue(runtime.turn(flight,clock.monotonic())['cold_recovery_required'])
            added=[False]
            retention=state.retention
            def ongoing_retention():
                result=retention()
                if not added[0]:
                    ingest(state.writer,rows(clock,SCOPES[0],5,age=185,start=3000,tag='ongoing'))
                    added[0]=True
                return result
            state.retention=ongoing_retention
            async def work(fn,priority,**kwargs):
                return fn(state)
            with ThreadPoolExecutor(max_workers=1) as pool:
                await recover(work,pool,state.writer.path,asyncio.Event(),wall=clock.time,
                    monotonic=clock.monotonic,force=True,flight=flight,
                    on_complete=lambda s,o:runtime.cold_completed(o,flight))
            self.assertEqual(state.writer.db.execute('SELECT COUNT(*) FROM records').fetchone()[0],5)
            self.assertIsNone(runtime.arbiter.pending)
            current=runtime.adapter.observe(runtime.generation)
            self.assertEqual(next(s for s in current.scopes if s.scope==SCOPES[0]).hot_oldest,clock.time()-185)
            self.assertEqual(runtime.turn(flight,clock.monotonic())['side'],'archive')

    async def test_late_cleanup_finishes_existing_archive_carrier_before_new_work(self):
        from tests.test_production_maintenance_arbiter import native_runtime,finalized_frontier
        from tests.maintenance_production_harness import rows,ingest,SCOPES
        from meme_machine.solana_maintenance_runtime import ArchiveFlight
        with native_runtime() as (state,runtime,clock):
            ingest(state.writer,rows(clock,SCOPES[0],15,age=185))
            finalized_frontier(state,clock,SCOPES[0])
            flight=ArchiveFlight()
            runtime.turn(flight,clock.monotonic())
            prepared=flight.prepared
            self.assertIsNotNone(prepared)
            ingest(state.writer,rows(clock,SCOPES[1],3,age=1800))
            finalized_frontier(state,clock,SCOPES[1])
            self.assertTrue(runtime.turn(flight,clock.monotonic())['cold_recovery_required'])
            async def work(fn,priority,**kwargs):return fn(state)
            with ThreadPoolExecutor(max_workers=1) as pool:
                await recover(work,pool,state.writer.path,asyncio.Event(),wall=clock.time,
                    monotonic=clock.monotonic,force=True,flight=flight,
                    on_complete=lambda s,o:runtime.cold_completed(o,flight))
            self.assertTrue(flight.idle)
            self.assertFalse(state.writer.db.execute('SELECT 1 FROM records').fetchone())
            self.assertEqual(state.writer.db.execute("SELECT value FROM counters WHERE key='archived_records'").fetchone()[0],18)
            self.assertIsNone(runtime.arbiter.pending)
            self.assertIsNone(runtime.failure)

    async def test_newly_eligible_old_data_is_actually_cleaned_without_freshening_it(self):
        from tests.test_production_maintenance_arbiter import native_runtime,finalized_frontier
        from tests.maintenance_production_harness import rows,ingest,SCOPES
        from meme_machine.solana_maintenance_runtime import ArchiveFlight
        with native_runtime() as (state,runtime,clock):
            runtime.turn(ArchiveFlight(),clock.monotonic())
            ingest(state.writer,rows(clock,SCOPES[0],119,age=1800,same_slot=True))
            finalized_frontier(state,clock,SCOPES[0])
            original=state.writer.db.execute('SELECT market_time FROM records').fetchall()
            flight=ArchiveFlight()
            result=runtime.turn(flight,clock.monotonic())
            self.assertTrue(result['cold_recovery_required'])
            self.assertIsNone(runtime.failure)
            self.assertEqual(state.writer.db.execute('SELECT market_time FROM records').fetchall(),original)
            async def work(fn,priority,**kwargs):return fn(state)
            with ThreadPoolExecutor(max_workers=1) as pool:
                await recover(work,pool,state.writer.path,asyncio.Event(),wall=clock.time,
                    monotonic=clock.monotonic,force=True,flight=flight,
                    on_complete=lambda s,o:runtime.cold_completed(o))
            self.assertTrue(flight.idle)
            self.assertFalse(state.writer.db.execute('SELECT 1 FROM records').fetchone())
            self.assertFalse(runtime.episodes)
            self.assertFalse(runtime.arbiter.origin)
            self.assertIsNone(runtime.turn(flight,clock.monotonic())['side'])

    async def test_released_candidate_cleans_only_evidence_without_remaining_position_pin(self):
        from tests.test_production_maintenance_arbiter import native_runtime,finalized_frontier
        from tests.maintenance_production_harness import rows,ingest,SCOPES
        from meme_machine.solana_maintenance_runtime import ArchiveFlight
        with native_runtime() as (state,runtime,clock):
            values=rows(clock,SCOPES[0],5,age=1800)
            values=[replace(r,addresses=('protected',) if i==0 else ('unrelated',))
                    for i,r in enumerate(values)]
            ingest(state.writer,values);finalized_frontier(state,clock,SCOPES[0])
            state.writer.interest('candidate',SCOPES[0],lower_slot=0)
            state.writer.interest('position',SCOPES[0],lower_slot=0,priority=0,lifecycle='open')
            with state.writer.transaction():
                state.writer.db.execute('INSERT INTO service_interests VALUES(?,?,?,?)',
                    ('position',SCOPES[0],'protected','transactions'))
            runtime.turn(ArchiveFlight(),clock.monotonic())
            state.writer.release('candidate',SCOPES[0])
            flight=ArchiveFlight()
            self.assertTrue(runtime.turn(flight,clock.monotonic())['cold_recovery_required'])
            async def work(fn,priority,**kwargs):return fn(state)
            with ThreadPoolExecutor(max_workers=1) as pool:
                await recover(work,pool,state.writer.path,asyncio.Event(),wall=clock.time,
                    monotonic=clock.monotonic,force=True,flight=flight,
                    on_complete=lambda s,o:runtime.cold_completed(o))
            remaining=state.writer.db.execute('SELECT identity,market_time FROM records WHERE body IS NOT NULL').fetchall()
            self.assertEqual(remaining,[(values[0].identity,values[0].market_time)])
            self.assertTrue(state.writer.db.execute('SELECT active FROM interests WHERE owner=?',('position',)).fetchone()[0])

    async def test_existing_unserviced_debt_still_expires(self):
        from tests.test_production_maintenance_arbiter import native_runtime,finalized_frontier
        from tests.maintenance_production_harness import rows,ingest,SCOPES
        from meme_machine.solana_maintenance_runtime import ArchiveFlight
        from meme_machine.solana_evidence_plane import EvidenceUnavailable
        with native_runtime() as (state,runtime,clock):
            runtime.turn(ArchiveFlight(),clock.monotonic())
            ingest(state.writer,rows(clock,SCOPES[0],10,age=185))
            finalized_frontier(state,clock,SCOPES[0])
            runtime.turn(ArchiveFlight(),clock.monotonic())
            clock.advance(60)
            with self.assertRaisesRegex(EvidenceUnavailable,'deadline_exhausted'):
                runtime.turn(ArchiveFlight(),clock.monotonic())

    async def test_sparse_address_pin_observation_fits_existing_vm_budget(self):
        from meme_machine.solana_provider_config import AlchemyEndpoint
        from meme_machine.solana_maintenance_state import DebtAgeAdapter, OBSERVATION_VM_STEPS
        with tempfile.TemporaryDirectory() as td:
            state=ServiceState(Path(td)/'evidence.sqlite',AlchemyEndpoint.parse(
                'https://solana-mainnet.g.alchemy.com/v2/offline-test'))
            writer=state.writer;writer.clock=lambda:1000
            self.addCleanup(writer.close)
            rows=[replace(record(),identity='dense'+str(i),signature='s'+str(i),
                scope='program:meteora',slot=1000+i//20,market_time=800,observed_at=1000,
                addresses=('protected-pool',) if i%4000==0 else ('unrelated-pool',))
                for i in range(20000)]
            for start in range(0,len(rows),1000):writer.ingest(rows[start:start+1000])
            writer.interest('position','program:meteora',lower_slot=1000,priority=0,lifecycle='open')
            writer.interest('overlapping-position','program:meteora',lower_slot=1200,priority=0,lifecycle='open')
            with writer.transaction():
                writer.db.execute('INSERT INTO service_interests VALUES(?,?,?,?)',
                    ('position','program:meteora','protected-pool','transactions'))
                writer.db.execute('INSERT INTO service_interests VALUES(?,?,?,?)',
                    ('overlapping-position','program:meteora','protected-pool','transactions'))
            before=writer.db.execute('SELECT COUNT(*) FROM records WHERE body IS NOT NULL').fetchone()[0]
            adapter=DebtAgeAdapter(writer,wall=lambda:1000)
            observation=adapter.observe(state.fence.session)
            scope=next(s for s in observation.scopes if s.scope=='program:meteora')
            self.assertEqual(scope.hot_eligible,19995)
            self.assertEqual(scope.hot_oldest,800)
            self.assertEqual(scope.pins,2)
            self.assertLessEqual(adapter.steps,OBSERVATION_VM_STEPS)
            self.assertEqual(writer.db.execute('SELECT COUNT(*) FROM records WHERE body IS NOT NULL').fetchone()[0],before)
            while writer.archive(820):pass
            remaining=writer.db.execute('SELECT identity FROM records WHERE body IS NOT NULL').fetchall()
            self.assertEqual({r[0] for r in remaining},{'dense'+str(i) for i in range(0,20000,4000)})

    async def test_old_cold_debt_drains_without_resetting_pins_gaps_or_source_time(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'evidence.sqlite';writer=EvidenceWriter(path,clock=lambda:1000)
            FinalizedFence(writer,endpoint_identity='offline')
            rows=[replace(record(),identity='r'+str(i),signature='s'+str(i),slot=i,market_time=i) for i in range(10,41)]
            writer.ingest(rows,proof=proof(10,40))
            writer.interest('position',rows[0].scope,lower_slot=30,priority=0,lifecycle='open')
            writer.gap(rows[0].scope,35,36)
            original_interests=writer.db.execute('SELECT * FROM interests').fetchall()
            original_gaps=writer.db.execute('SELECT * FROM gaps').fetchall()
            class State:
                def __init__(self):self.writer=writer;self.fence=SimpleNamespace(session='cold-generation')
                def archive_plan(self):return writer.archive_snapshot(820,max_records=1000)
                def archive_commit_slice(self,plan,receipt):
                    writer.commit_archive(plan[:512],receipt);return plan[512:]
                def retention(self):return writer.retain(820,archive_first=False,checkpoint=False)
            state=State();calls=[]
            async def work(fn,priority,**kwargs):
                calls.append(kwargs['label']);return fn(state)
            with ThreadPoolExecutor(max_workers=1) as pool:
                await recover(work,pool,path,asyncio.Event(),wall=lambda:1000)
            self.assertIn('archive_commit_plan',calls)
            self.assertEqual(writer.db.execute('SELECT * FROM interests').fetchall(),original_interests)
            self.assertEqual(writer.db.execute('SELECT * FROM gaps').fetchall(),original_gaps)
            self.assertEqual(writer.db.execute('SELECT MIN(market_time) FROM records').fetchone()[0],30)
            self.assertEqual(writer.db.execute('SELECT MIN(observed) FROM lineage').fetchone()[0],100)
            writer.close()

    async def test_fresh_store_skips_cleanup_entirely(self):
        with tempfile.TemporaryDirectory() as td:
            writer=EvidenceWriter(Path(td)/'evidence.sqlite',clock=lambda:100)
            FinalizedFence(writer,endpoint_identity='offline')
            writer.ingest([record()],proof=proof())
            state=SimpleNamespace(writer=writer,fence=SimpleNamespace(session='fresh'))
            calls=[]
            async def work(fn,priority,**kwargs):calls.append(kwargs['label']);return fn(state)
            await recover(work,None,writer.path,asyncio.Event(),wall=lambda:100)
            self.assertEqual(calls,['maintenance_decision']);self.assertEqual(writer.db.execute('SELECT COUNT(*) FROM records').fetchone()[0],1)
            writer.close()
