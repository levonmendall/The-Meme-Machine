"""Actual native service under bounded FIFO contention and truthful admission.

The synthetic source callbacks update only a native cursor on disposable state.
No provider, financial work, fabricated Need, callback ACK or market-speed claim.
"""
import asyncio
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from meme_machine.solana_evidence_control import PriorityOwner
from meme_machine.solana_evidence_plane import EvidenceUnavailable
from meme_machine.solana_evidence_service import ServiceState
from meme_machine.solana_maintenance_runtime import ArchiveFlight,MaintenanceRuntime
from meme_machine.solana_provider_config import AlchemyEndpoint
from tests.maintenance_production_harness import Clock
from tests import test_production_maintenance_arbiter as native_fixture
from tests.maintenance_production_harness import rows,ingest,SCOPES


class NativeObservationWindowTests(unittest.TestCase):
    def test_fixed_appointment_failures_survive_original_privacy_redaction(self):
        from meme_machine.runtime.evidence_worker import failure_diagnostic
        reasons=('maintenance_admission_bound_unavailable','maintenance_boundary_deadline',
            'maintenance_boundary_outstanding','maintenance_boundary_unavailable',
            'maintenance_boundary_expired','maintenance_boundary_cancelled',
            'maintenance_boundary_closed','maintenance_boundary_urgent_invalidated',
            'maintenance_boundary_command_missing')
        for reason in reasons:
            with self.subTest(reason=reason):
                self.assertEqual(failure_diagnostic(EvidenceUnavailable(reason)),
                    'evidence_worker_failed:EvidenceUnavailable:'+reason)
        private='https://private-canary.invalid/key?credential=do-not-publish'
        for reason in ('maintenance_boundary_'+private,'maintenance_boundary_deadline '+private,
                'maintenance_boundary_new_unknown'):
            self.assertEqual(failure_diagnostic(EvidenceUnavailable(reason)),
                'evidence_worker_failed:EvidenceUnavailable')
        self.assertEqual(failure_diagnostic(ValueError(private)),
            'evidence_worker_failed:ValueError')

    def test_transport_bound_is_absolute_sql_free_and_real_observations_refresh_it(self):
        with native_fixture.native_runtime() as (state,runtime,clock):
            flight=ArchiveFlight();runtime.turn(flight,0)
            original=runtime.admission_deadline();origins=dict(runtime.arbiter.origin)
            self.assertEqual(original,30)
            clock.advance(5)
            with patch.object(runtime.adapter,'observe',side_effect=AssertionError('unexpected_rescan')):
                statements=[];state.writer.db.set_trace_callback(statements.append)
                try:
                    self.assertEqual(runtime.admission_deadline(),original)
                    self.assertEqual(runtime.admission_deadline(),original)
                finally:state.writer.db.set_trace_callback(None)
            self.assertFalse(statements);self.assertEqual(runtime.arbiter.origin,origins)
            runtime.turn(flight,clock.monotonic())
            self.assertEqual(runtime.admission_deadline(),35)

    def test_cleared_then_new_actual_duties_remain_serviceable_across_many_droughts(self):
        with native_fixture.native_runtime() as (state,runtime,clock):
            flight=ArchiveFlight()
            for index in range(8):
                native_fixture.orphan_chunk(state.writer,f'cohort-{index}')
                runtime.turn(flight,clock.monotonic())
                self.assertEqual(runtime.ring[-1]['durable_progress']['__housekeeping__'],1)
                self.assertGreater(runtime.admission_deadline(),clock.monotonic())
                clock.advance(10)
                runtime.turn(flight,clock.monotonic())
                self.assertIsNone(runtime.ring[-1]['selected'])
                clock.advance(10)
            self.assertGreater(clock.monotonic(),3*runtime.leases.drought)
            self.assertIsNone(runtime.failure)
            self.assertEqual(state.writer.db.execute("SELECT units,records FROM maintenance_progress "
                "WHERE scope='__housekeeping__' AND side='retirement'").fetchone(),(8,0))

    def test_open_observation_window_never_extends_original_record_service_deadline(self):
        with native_fixture.native_runtime() as (state,runtime,clock):
            ingest(state.writer,rows(clock,SCOPES[1],5,age=210))
            flight=ArchiveFlight();runtime.turn(flight,0)
            self.assertIsNotNone(flight.prepared)
            bound=runtime.admission_deadline()
            clock.advance(13)
            self.assertLess(clock.monotonic(),bound)
            before=state.writer.db.execute('SELECT COUNT(*) FROM records WHERE body IS NOT NULL').fetchone()
            with self.assertRaisesRegex(EvidenceUnavailable,'^maintenance_service_deadline_exhausted$'):
                runtime.turn(flight,clock.monotonic())
            self.assertEqual(state.writer.db.execute('SELECT COUNT(*) FROM records WHERE body IS NOT NULL').fetchone(),before)
            self.assertTrue(runtime.arbiter.failed)
            with self.assertRaisesRegex(EvidenceUnavailable,'^maintenance_admission_bound_unavailable$'):
                runtime.admission_deadline()


async def settled(predicate):
    for _ in range(3000):
        if predicate():return
        await asyncio.sleep(.001)
    raise AssertionError('native_fifo_fixture_not_reached')


class MaintenanceAdmissionServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_serve_waits_behind_old_native_work_before_constructing_turn(self):
        from tests.maintenance_production_harness import run_case,seed_book
        from tests.test_maintenance_owner_entry_clock import OwnerTurnProbe
        clock=Clock();accepted=[];requested=[];release=threading.Event()
        original=PriorityOwner.request_maintenance_boundary
        def request(owner,*,deadline):
            if requested:return original(owner,deadline=deadline)
            requested.append(clock.monotonic())
            for index in range(5):
                def old_source(state,index=index):
                    if index==0 and not release.wait(5):
                        raise AssertionError('offline_boundary_older_work_not_released')
                    # Real existing native counter transaction, not an invented
                    # market event, maintenance result or progress acknowledgement.
                    with state.writer.transaction():state.fence.count('offline_older_owner_work')
                    clock.advance(.8)
                accepted.append(owner.submit(old_source,priority=2))
            try:return original(owner,deadline=deadline)
            finally:release.set()
        try:
            with patch.object(PriorityOwner,'request_maintenance_boundary',request),OwnerTurnProbe(clock) as probe:
                box=await run_case(clock=clock,seed=lambda state,at:seed_book(state,at,hot=(100,0,0)),turns=6)
            self.assertFalse(box['errors'],[str(error) for error in box['errors']])
            self.assertIsNone(box['runtime'].failure)
            self.assertEqual(box['integrity'],'ok')
            self.assertEqual(box['counters']['offline_older_owner_work'],5)
            event,=probe.events
            self.assertGreater(event['submitted']-requested[0],3)
            self.assertLessEqual(event['callback_entry']-event['submitted'],3)
            self.assertTrue(all(f.done() and not f.cancelled() and f.exception() is None for f in accepted))
            self.assertGreater(box['counters'].get('archived_records',0),0)
            self.assertGreater(box['owner'].telemetry()['maintenance_boundary.accepted'],0)
        finally:release.set()

    async def exercise(self,*,reserved):
        clock=Clock();temporary=tempfile.TemporaryDirectory();all_futures=[];gates=[];box={}
        path=Path(temporary.name)/'native.sqlite'
        def factory():
            state=ServiceState(path,AlchemyEndpoint.parse('https://solana-mainnet.g.alchemy.com/v2/offline-test'))
            state.writer.clock=clock.time
            with state.writer.transaction():
                state.writer.db.execute('INSERT INTO cursors VALUES(?,?,?)',('control:solana',1,clock.time()))
            runtime=MaintenanceRuntime(state,monotonic=clock.monotonic,wall=clock.time)
            flight=ArchiveFlight();result=runtime.turn(flight,clock.monotonic())
            self.assertEqual(result['side'],'retirement')
            self.assertEqual(state.writer.db.execute('SELECT units,records FROM maintenance_progress '
                'WHERE scope=? AND side=?',('control:solana','retirement')).fetchone(),(1,0))
            box.update(state=state,runtime=runtime,flight=flight,result=result)
            return state
        owner=PriorityOwner(factory,clock=clock.monotonic)
        expired=[];entries=[];commands=[];native_success=[]
        try:
            await asyncio.wait_for(asyncio.wrap_future(owner.ready),3)
            def submit(fn,priority=2):
                future=owner.submit(fn,priority=priority);all_futures.append(future);return future
            async def complete(future):
                return await asyncio.wait_for(asyncio.shield(asyncio.wrap_future(future)),3)
            def wave():
                entered=threading.Event();release=threading.Event();gates.append(release);rows=[]
                for index in range(5):
                    def source(state,index=index):
                        if index==0:
                            entered.set()
                            if not release.wait(5):raise AssertionError('native_fifo_source_not_released')
                        with state.writer.transaction():
                            state.writer.db.execute('UPDATE cursors SET slot=slot+1,updated=? WHERE scope=?',
                                (clock.time(),'control:solana'))
                        clock.advance(1.2)
                    rows.append(submit(source))
                return rows,entered,release
            def native_command(submitted):
                def turn(state):
                    entered=clock.monotonic();entries.append((submitted,entered))
                    # The original service callback guard runs BEFORE native
                    # arbitration and does not give expired commands a new clock.
                    if entered-submitted>box['runtime'].leases.owner:
                        expired.append((submitted,entered))
                        raise EvidenceUnavailable('evidence_command_expired')
                    result=box['runtime'].turn(box['flight'],submitted,owner_entered=entered)
                    box['result']=result;native_success.append(entered);return result
                return turn
            current,entered,release=wave();await settled(entered.is_set)
            for _ in range(7):
                requested=clock.monotonic()
                if reserved:
                    ticket=owner.request_maintenance_boundary(deadline=box['runtime'].admission_deadline())
                    commands.append(ticket)
                else:
                    command=submit(native_command(requested),4)
                younger,next_entered,next_release=wave()
                release.set()
                for future in current:await complete(future)
                if reserved:
                    self.assertIs(await complete(ticket.ready),ticket)
                    submitted=clock.monotonic()
                    self.assertGreater(submitted-ticket.requested_at,3)
                    command=owner.submit_maintenance(native_command(submitted),ticket)
                    all_futures.append(command)
                    await complete(command)
                    self.assertEqual(command.owner_accepted_at,submitted)
                    self.assertGreater(command.owner_sequence,younger[-1].owner_sequence)
                    self.assertIsNone(box['runtime'].failure)
                else:
                    with self.assertRaisesRegex(EvidenceUnavailable,'^evidence_command_expired$'):
                        await complete(command)
                await settled(next_entered.is_set)
                current,entered,release=younger,next_entered,next_release
            release.set()
            for future in current:await complete(future)
            # Identical40 genuine native cursor commits,48 virtual seconds.
            self.assertAlmostEqual(clock.monotonic(),48)
            final=submit(native_command(clock.monotonic()),4)
            if reserved:
                await complete(final)
                self.assertFalse(expired);self.assertEqual(len(native_success),8)
                self.assertIsNone(box['runtime'].failure)
            else:
                with self.assertRaisesRegex(EvidenceUnavailable,'^maintenance_service_deadline_exhausted$'):
                    await complete(final)
                self.assertEqual(len(expired),7);self.assertFalse(native_success)
                self.assertEqual(box['runtime'].failure,'EvidenceUnavailable:maintenance_service_deadline_exhausted')
            inspect=submit(lambda state:(
                state.writer.db.execute('SELECT units,records FROM maintenance_progress '
                    'WHERE scope=? AND side=?',('control:solana','retirement')).fetchone(),
                state.writer.db.execute('SELECT slot FROM cursors WHERE scope=?',('control:solana',)).fetchone(),
                state.writer.db.execute('PRAGMA integrity_check').fetchone()[0]),0)
            progress,cursor,integrity=await complete(inspect)
            self.assertEqual(cursor,(41,));self.assertEqual(integrity,'ok')
            self.assertEqual(progress,(9 if reserved else 1,0))
            self.assertLessEqual(owner.telemetry()['queue_peak'],11)
            return dict(reserved=reserved,expired=len(expired),service_entries=entries,
                actual_progress=progress,native_success=native_success,virtual_seconds=clock.monotonic())
        finally:
            for release in gates:release.set()
            owner.close();temporary.cleanup()
            self.assertFalse(owner.thread.is_alive())
            self.assertTrue(all(f.done() and not f.cancelled() for f in all_futures))

    async def test_fifo_expiry_requeue_hides_native_turns_and_exhausts_real_drought(self):
        result=await self.exercise(reserved=False)
        self.assertEqual(result['expired'],7)

    async def test_actual_reserved_turns_renew_real_progress_across_original_drought_window(self):
        result=await self.exercise(reserved=True)
        self.assertGreater(result['virtual_seconds'],45)
        self.assertEqual(result['expired'],0)
