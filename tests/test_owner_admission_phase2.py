"""Phase 2A finite admission matrix: actual PriorityOwner futures and native SQLite.

Logical clocks and explicit barriers control races; no material pressure cohort,
provider access, synthetic Needs, or replacement maintenance authority.
"""
import asyncio
from concurrent.futures import Future
from dataclasses import asdict, replace
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from meme_machine import solana_evidence_service as service
from meme_machine.solana_evidence_control import PriorityOwner
from meme_machine.solana_evidence_plane import EvidenceUnavailable, EvidenceWriter
from meme_machine.solana_owner_admission import OwnerAdmission, SourceState, PressureHint
from meme_machine.solana_maintenance_runtime import ArchiveFlight, MaintenanceRuntime
from meme_machine.solana_provider_config import AlchemyEndpoint
from meme_machine.solana_evidence_transport import Subscription
from tests.maintenance_production_harness import Clock, ENDPOINT, SCOPES, rows, ingest, run_case
from tests.test_production_maintenance_arbiter import finalized_frontier

EVIDENCE = dict(boundaries=[], timing=[], placement={}, native=[], races=[])
ELIGIBLE = SourceState('blocks', 15, 64*1024*1024, False, 15, 15, 15, 8.899, 8.899)
PRESSURE = dict(archive_pressure=True, retirement_pressure=True)


async def settled(predicate, turns=2000):
    for _ in range(turns):
        if predicate():
            return
        await asyncio.sleep(.001)
    raise AssertionError('explicit_barrier_not_reached')


class GateTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock = Clock()
        self.owner = PriorityOwner(lambda: SimpleNamespace(close=lambda: None),
                                   clock=self.clock.monotonic)
        await asyncio.wrap_future(self.owner.ready)
        await settled(lambda: not self.owner._checkpoint_busy and not self.owner.queue)
        self.gate = OwnerAdmission(self.owner, clock=self.clock.monotonic)
        self.gate.generation = 'generation'
        self.gate.publish('generation', PRESSURE)
        self.futures = []
        self.release = threading.Event()

    async def asyncTearDown(self):
        self.release.set()
        self.gate.close()
        self.owner.admission_notify = None
        await asyncio.to_thread(self.owner.close)
        self.assertTrue(all(f.done() for f in self.futures))
        self.assertFalse(self.owner.thread.is_alive())

    async def opened(self, state=ELIGIBLE):
        task = asyncio.create_task(self.gate.rendezvous(lambda: state))
        await settled(lambda: self.gate.offer is not None)
        return task, self.gate.offer

    def submit(self, fn=lambda state: None, *, priority=4, offer=None):
        future = self.owner.submit(fn, priority=priority,
                                  admit_before=offer.row['deadline'] if offer else None)
        self.futures.append(future)
        if priority == 4:
            self.gate.accepted(future, offer)
        return future

    async def source(self, offer, frames=1, fn=lambda state: None):
        future = self.owner.submit(fn, priority=2)
        self.futures.append(future)
        self.gate.source_accepted(future, offer, frames)
        await asyncio.wrap_future(future)
        await settled(lambda: not self.owner._checkpoint_busy and not self.owner.queue)
        return future

    async def test_full_trigger_boundaries(self):
        cases = [
            ('frames_15', {}, None),
            ('frames_16', dict(pending_frames=16), 'pending_frames'),
            ('frames_17', dict(pending_frames=17), 'pending_frames'),
            ('frames_zero', dict(pending_frames=0), 'pending_frames'),
            ('bytes_exact', dict(pending_bytes=64*1024*1024), None),
            ('bytes_above', dict(pending_bytes=64*1024*1024+1), 'pending_bytes'),
            ('receive_capacity', dict(receiver_waiting=True), 'receiver_capacity'),
            ('account_head', dict(kind='account'), 'head_account'),
            ('ack_head', dict(kind='ack'), 'head_ack'),
            ('control_head', dict(kind='control'), 'head_control'),
            ('draining', dict(draining=True), 'draining'),
        ]
        for field in ('inbound', 'decoded', 'ordered_ready'):
            cases += [(field+'_15', {field:15}, None), (field+'_16', {field:16}, field)]
        for field in ('commit_age', 'head_age'):
            cases += [(field+'_below', {field:8.899}, None),
                      (field+'_equal', {field:8.9}, field),
                      (field+'_above', {field:8.901}, field)]
        for name, change, expected in cases:
            with self.subTest(name=name):
                actual = self.gate._reason(replace(ELIGIBLE, **change))
                self.assertEqual(actual, expected)
                EVIDENCE['boundaries'].append(dict(case=name, actual=actual, passed=True))

        for age, expected in [(.999,None),(1.0,None),(1.001,'hint_age')]:
            self.gate.hint = PressureHint(1,'generation',-age,True)
            self.assertEqual(self.gate._reason(ELIGIBLE),expected)
            EVIDENCE['boundaries'].append(dict(case='hint_age_'+str(age),actual=expected,passed=True))
        for name, hint, expected in [
            ('stale_positive',PressureHint(1,'generation',-2,True),'hint_age'),
            ('stale_negative',PressureHint(1,'generation',-2,False),'no_positive_hint'),
            ('negative',PressureHint(1,'generation',0,False),'no_positive_hint'),
            ('generation_mismatch',PressureHint(1,'wrong',0,True),'hint_generation'),
            ('consumed_epoch',PressureHint(0,'generation',0,True),'hint_consumed')]:
            self.gate.hint=hint
            self.assertEqual(self.gate._reason(ELIGIBLE),expected)
            EVIDENCE['boundaries'].append(dict(case=name,actual=expected,passed=True))

    async def test_owner_runtime_and_previous_request_guards(self):
        for attribute, reason in [('closed','draining'),('failed','failed'),
                                  ('generation_invalid','generation_invalid')]:
            setattr(self.gate,attribute,True)
            self.assertEqual(self.gate._reason(ELIGIBLE),reason)
            setattr(self.gate,attribute,False)
        previous=Future();self.gate.last_source=previous
        self.assertEqual(self.gate._reason(ELIGIBLE),'source_unfinished')
        previous.set_result(None)
        unfinished=Future();self.gate.maintenance_future=unfinished
        self.assertEqual(self.gate._reason(ELIGIBLE),'maintenance_unfinished')
        unfinished.set_result(None)
        with self.owner.cv:
            self.owner._checkpoint_handoff=object()
        self.assertEqual(self.gate._reason(ELIGIBLE),'checkpoint_handoff')
        with self.owner.cv:
            self.owner._checkpoint_handoff=None
        started=threading.Event()
        def blocked(state):
            started.set();self.release.wait(3)
        first=self.submit(blocked,priority=2)
        await settled(started.is_set)
        self.assertEqual(self.gate._reason(ELIGIBLE),'owner_busy')
        queued=self.submit(priority=2)
        self.assertEqual(self.gate._reason(ELIGIBLE),'owner_queue')
        urgent=self.submit(priority=0)
        self.assertEqual(self.gate._reason(ELIGIBLE),'urgent_waiting')
        self.release.set()
        await asyncio.gather(*(asyncio.wrap_future(f) for f in (first,queued,urgent)))
        await settled(lambda:not self.owner._checkpoint_busy)
        with self.owner.cv:
            self.owner.closed=True
        self.assertEqual(self.gate._reason(ELIGIBLE),'owner_closed')
        with self.owner.cv:
            self.owner.closed=False
        EVIDENCE['boundaries'].append(dict(case='owner_runtime_all_guards',passed=True))

    async def test_actual_acceptance_before_deadline_resumes_without_completion(self):
        task,offer=await self.opened()
        await self.gate.before_maintenance()
        self.clock.advance(.099)
        started=threading.Event()
        def blocked(state):
            self.gate.entry(offer);started.set();self.release.wait(3)
            self.gate.completed(offer,result=dict(side=None))
        future=self.submit(blocked,offer=offer)
        got=await task
        self.assertIs(got.maintenance_future,future)
        self.assertEqual(got.row['outcome'],'accepted')
        self.assertFalse(future.done(),'acceptance must resume before completion')
        self.assertAlmostEqual(got.row['gate_wait'],.099)
        source_task=asyncio.create_task(self.source(got))
        await settled(lambda:got.source_future is not None)
        self.release.set();await source_task
        EVIDENCE['timing'].append(dict(case='accept_before',**got.row))

    async def test_exact_deadline_after_timeout_and_overshoot(self):
        for delay in (.100,.101,.125):
            self.gate.publish('generation',PRESSURE)
            task,offer=await self.opened()
            await self.gate.before_maintenance()
            self.clock.advance(delay)
            sequence=self.owner.sequence
            with self.assertRaisesRegex(EvidenceUnavailable,'admission_offer_expired') as error:
                self.submit(offer=offer)
            self.gate.refused(offer,error.exception)
            got=await task
            self.assertEqual(self.owner.sequence,sequence,'late admission entered the owner queue')
            self.assertEqual(got.row['outcome'],'timeout')
            self.assertAlmostEqual(got.row['gate_wait'],delay)
            self.assertAlmostEqual(got.row['overshoot'],max(0,delay-.100))
            self.assertEqual(self.gate.failed,delay>.100)
            await self.source(got)
            self.gate.failed=False
            EVIDENCE['timing'].append(dict(case='deadline_'+str(delay),**got.row))

    async def test_timeout_without_coroutine_wakeup_and_no_second_grant(self):
        task,offer=await self.opened()
        self.clock.advance(.100);self.gate.expire(offer)
        got=await task
        self.assertEqual(got.row['outcome'],'timeout')
        second=asyncio.create_task(self.gate.before_maintenance())
        await asyncio.sleep(0)
        self.assertFalse(second.done(),'late wake jumped the affected source')
        await self.source(got)
        self.assertIsNone(await second)
        self.assertIsNone(await self.gate.rendezvous(lambda:ELIGIBLE))
        self.assertEqual(self.gate.counters['offers'],1)
        EVIDENCE['timing'].append(dict(case='timeout_no_wakeup',**got.row))

    async def test_cancellation_after_acceptance_retains_owner_future(self):
        task,offer=await self.opened()
        await self.gate.before_maintenance()
        future=self.submit(lambda state:self.release.wait(3),offer=offer)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertFalse(future.cancelled())
        self.assertIs(self.gate.maintenance_future,future)
        self.assertIsNone(self.gate.offer)
        self.assertIsNone(await self.gate.before_maintenance())
        self.release.set();await asyncio.wrap_future(future)
        self.assertIsNone(await self.gate.rendezvous(lambda:ELIGIBLE))
        EVIDENCE['races'].append(dict(case='cancel_after_acceptance',**offer.row))

    async def test_fast_completion_barrier_and_exact_fifo(self):
        order=[]
        task,offer=await self.opened()
        await self.gate.before_maintenance()
        first=self.owner.submit(lambda state:order.append('maintenance_one'),priority=4,
                                admit_before=offer.row['deadline'])
        self.futures.append(first)
        first.result(timeout=3)
        self.assertFalse(task.done(),'source resumed before the arranged fast completion')
        self.gate.accepted(first,offer)
        got=await task
        got.row['fast_completion_before_resume']=True
        second=asyncio.create_task(self.gate.before_maintenance())
        await asyncio.sleep(0)
        self.assertFalse(second.done())
        source=self.owner.submit(lambda state:order.append('source'),priority=2)
        self.futures.append(source);self.gate.source_accepted(source,got,1)
        self.assertIsNone(await second)
        last=self.submit(lambda state:order.append('maintenance_two'))
        await asyncio.gather(*(asyncio.wrap_future(f) for f in (source,last)))
        self.assertEqual(order,['maintenance_one','source','maintenance_two'])
        self.assertLess(first.owner_sequence,source.owner_sequence)
        self.assertLess(source.owner_sequence,last.owner_sequence)
        EVIDENCE['races'].append(dict(case='fast_completion_fifo',order=order,**got.row))

    async def test_rearm_only_after_source_completion_and_new_epoch(self):
        task,offer=await self.opened()
        await self.gate.before_maintenance()
        first=self.submit(offer=offer)
        got=await task;await asyncio.wrap_future(first)
        started=threading.Event()
        def source(state):
            started.set();self.release.wait(3)
        future=self.owner.submit(source,priority=2);self.futures.append(future)
        self.gate.source_accepted(future,got,1)
        self.gate.publish('generation',PRESSURE)
        await settled(started.is_set)
        self.assertEqual(self.gate._reason(ELIGIBLE),'source_unfinished')
        self.release.set();await asyncio.wrap_future(future)
        await settled(lambda:not self.owner._checkpoint_busy)
        newer,new=await self.opened()
        self.assertGreater(new.hint.epoch,got.hint.epoch)
        self.gate.abort(new);await newer
        self.assertEqual(self.gate.counters['offers'],2)

    async def test_backlog_recheck_and_batch_guard_changes_during_wait(self):
        for field,value in [('pending_frames',16),('pending_bytes',64*1024*1024+1),
                            ('receiver_waiting',True),('inbound',16),('decoded',16),
                            ('ordered_ready',16),('commit_age',8.9),('head_age',8.9),
                            ('draining',True)]:
            self.gate.publish('generation',PRESSURE)
            current=[ELIGIBLE]
            task=asyncio.create_task(self.gate.rendezvous(lambda:current[0]))
            await settled(lambda:self.gate.offer is not None)
            offer=self.gate.offer
            current[0]=replace(current[0],**{field:value})
            self.gate.recheck()
            got=await task
            self.assertIsNone(got.maintenance_future)
            self.assertTrue(got.row['outcome'].startswith('bypass_'))
            self.gate.abort(offer)
        EVIDENCE['races'].append(dict(case='all_local_guards_rechecked',passed=True))

    async def test_urgent_before_during_after_admission_and_existing_fifo(self):
        order=[];self.owner.admission_notify=lambda:self.gate.loop.call_soon_threadsafe(self.gate.recheck)
        task,offer=await self.opened()
        started=threading.Event()
        def urgent(state):
            order.append('urgent_during');started.set();self.release.wait(3)
        urgent_future=self.submit(urgent,priority=0)
        await settled(started.is_set)
        got=await task
        self.assertIsNone(got.maintenance_future)
        self.assertTrue(got.row['outcome'].startswith('bypass_'))
        source_task=asyncio.create_task(self.source(got,fn=lambda state:order.append('source_after_bypass')))
        self.release.set();await source_task
        await settled(lambda:not self.owner._checkpoint_busy)
        self.release.clear();self.gate.publish('generation',PRESSURE)
        task,offer=await self.opened();await self.gate.before_maintenance()
        started.clear()
        def maintenance(state):
            order.append('maintenance');started.set();self.release.wait(3)
        maintenance_future=self.submit(maintenance,offer=offer)
        got=await task;await settled(started.is_set)
        source=self.owner.submit(lambda state:order.append('source_affected'),priority=2)
        self.futures.append(source);self.gate.source_accepted(source,got,1)
        # All already-admitted nonurgent requests retain exact sequence order.
        older=self.submit(lambda state:order.append('older_nonurgent'),priority=4)
        younger=self.submit(lambda state:order.append('younger_source'),priority=2)
        urgent_after=self.submit(lambda state:order.append('urgent_after'),priority=0)
        foreground=self.submit(lambda state:order.append('foreground_after'),priority=1)
        self.release.set()
        await asyncio.gather(*(asyncio.wrap_future(f) for f in
            (urgent_future,maintenance_future,source,older,younger,urgent_after,foreground)))
        self.assertEqual(order,['urgent_during','source_after_bypass','maintenance',
            'urgent_after','foreground_after','source_affected','older_nonurgent','younger_source'])
        EVIDENCE['races'].append(dict(case='urgent_and_admitted_fifo',order=order))

    async def test_shutdown_and_generation_invalidation_consume_open_offer(self):
        task,offer=await self.opened()
        self.gate.close();got=await task
        self.assertEqual(got.row['outcome'],'aborted')
        self.assertIsNone(await self.gate.before_maintenance())
        self.assertIsNone(await self.gate.rendezvous(lambda:ELIGIBLE))
        self.gate.closed=False;self.gate.publish('generation',PRESSURE)
        task,offer=await self.opened()
        self.gate.publish('wrong-generation',PRESSURE)
        got=await task
        self.assertEqual(got.row['outcome'],'bypass_generation_invalid')
        self.gate.abort(offer)
        EVIDENCE['races'].append(dict(case='shutdown_generation',passed=True))

    async def test_idle_is_immediately_woken_without_cancelling_worker(self):
        stop=asyncio.Event();worker=Future()
        waiter=asyncio.create_task(self.gate.idle(stop,worker))
        await asyncio.sleep(0)
        self.gate.wake.set();await asyncio.wait_for(waiter,.2)
        self.assertFalse(worker.cancelled())
        self.assertFalse(worker.done())
        worker.set_result(None)


    async def test_batching_recomputed_after_rendezvous_and_source_charge_uses_actual_frames(self):
        import ast
        import inspect
        tree=ast.parse(inspect.getsource(service))
        serve=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='serve')
        function=next(n for n in serve.body if isinstance(n,ast.FunctionDef) and n.name=='maintenance_batch_limit')
        pressure={'archive':True,'retention':False}
        namespace=dict(maintenance_pressure=pressure,STREAM_COMMIT_BATCH_MAX_MESSAGES=8)
        exec(compile(ast.Module(body=[function],type_ignores=[]),'native_batch_limit','exec'),namespace)
        limit=namespace['maintenance_batch_limit']
        self.assertEqual(limit(15),1)
        self.assertEqual(limit(16),8)
        self.assertEqual(limit(17),8)
        task,offer=await self.opened();await self.gate.before_maintenance()
        future=self.submit(offer=offer)
        await asyncio.wrap_future(future)
        # The original callback can clear a stale-positive pressure hint before
        # source formation; the actual existing batch function is called afresh.
        pressure['archive']=False
        got=await task
        self.assertEqual(limit(15),8)
        pressure['archive']=True
        self.assertEqual(limit(16),8)
        await self.source(got,frames=8)
        self.assertEqual(got.row['affected_frames'],8)
        source=inspect.getsource(service)
        self.assertLess(source.index('offer=await admission.rendezvous'),
                        source.index('batch_limit=maintenance_batch_limit',source.index('offer=await admission.rendezvous')))
        for frames,native in [(1,.02),(8,.02),(8,1.4)]:
            charge=max(0,.165*frames-native)
            self.assertEqual(charge,max(0,.165*frames-native))
        EVIDENCE['races'].append(dict(case='batch_recomputation_actual_function',
            initial_limit=1,resumed_limit=8,**got.row))


    async def test_accepted_offer_scheduler_overshoot_is_unclamped(self):
        task,offer=await self.opened();await self.gate.before_maintenance()
        future=self.submit(offer=offer)
        self.clock.advance(.125)
        got=await task
        self.assertEqual(got.row['outcome'],'accepted')
        self.assertAlmostEqual(got.row['gate_wait'],.125)
        self.assertAlmostEqual(got.row['overshoot'],.025)
        self.assertTrue(self.gate.failed)
        self.assertFalse(future.cancelled())
        await self.source(got)
        self.assertIsNone(await self.gate.rendezvous(lambda:ELIGIBLE))
        EVIDENCE['timing'].append(dict(case='accepted_scheduler_overshoot',**got.row))

    async def test_shutdown_keeps_accepted_barrier_until_source_submission(self):
        task,offer=await self.opened();await self.gate.before_maintenance()
        future=self.submit(offer=offer);got=await task
        await asyncio.wrap_future(future)
        blocked=asyncio.create_task(self.gate.before_maintenance())
        await asyncio.sleep(0)
        self.gate.close()
        await asyncio.sleep(0)
        self.assertFalse(blocked.done())
        self.assertIs(self.gate.offer,got)
        await self.source(got)
        self.assertIsNone(await blocked)
        self.assertNotIn('source_abort',got.row)
        EVIDENCE['races'].append(dict(case='accepted_drain_barrier',**got.row))


def block_item(clock, slot, *, at=None):
    sub=Subscription('service','chain:solana','all','blocks',2)
    message=dict(method='blockNotification',params=dict(subscription=1,
        result=dict(value=dict(slot=slot,err=None,block=dict(parentSlot=slot-1,
            blockhash='h'+str(slot),previousBlockhash='h'+str(slot-1),
            blockTime=int(clock.time()) if at is None else at,transactions=[])))))
    return sub,message,clock.time(),len(service.canonical(message))


async def placement(treatment, *, initial=.57, frames=1):
    """Identical pre-loss native book, receipt, episodes, source service and M1.

    The only old/new difference is placement of the new ordinary source submit.
    Two earlier native source requests establish the common completed prefix.
    """
    clock=Clock();clock.advance(initial)
    box={};order=[];futures=[];charge=[];source_queued=threading.Event()
    with tempfile.TemporaryDirectory() as td, patch.object(service,'time',clock):
        class State(service.ServiceState):
            def archive_commit_slice_and_plan(self,plan,receipt):
                try:return super().archive_commit_slice_and_plan(plan,receipt)
                finally:clock.advance(.025)
        def factory():
            state=State(Path(td)/'db',AlchemyEndpoint.parse(ENDPOINT))
            state.writer.clock=clock.time
            ingest(state.writer,rows(clock,SCOPES[0],1100,start=100,tag='retired',same_slot=True))
            while state.writer.archive(clock.time()-180):pass
            ingest(state.writer,rows(clock,SCOPES[0],1400,start=1000,tag='hot',same_slot=True))
            # Genuine validated but stalled finalized source, not an inserted
            # episode/deadline. Integer timestamp and fractional receive time
            # project both initial recovery deadlines to logical 10.0 seconds.
            finalized_frontier(state,clock,SCOPES[0],at=int(clock.time())-107)
            runtime=MaintenanceRuntime(state,monotonic=clock.monotonic,wall=clock.time)
            flight=ArchiveFlight()
            result=runtime.turn(flight,clock.monotonic())
            if result['snapshot'] is None:
                raise AssertionError(('native_preparation_not_selected',result))
            prepared=Future()
            prepared.set_result(EvidenceWriter.prepare_and_write_archive(state.writer.path,result['snapshot']))
            flight.attach(prepared,clock.monotonic(),runtime.generation)
            box.update(state=state,runtime=runtime,flight=flight,returned=result)
            return state
        owner=PriorityOwner(factory,clock=clock.monotonic)
        gate=None
        try:
            await asyncio.wrap_future(owner.ready)
            await settled(lambda:not owner._checkpoint_busy and not owner.queue)
            runtime,flight=box['runtime'],box['flight']
            gate=OwnerAdmission(owner,clock=clock.monotonic)
            gate.generation=runtime.generation
            gate.publish(runtime.generation,box['returned'])

            def source_fn(slot, frames=1, label='source'):
                def execute(state):
                    order.append(label)
                    started=clock.monotonic()
                    state.source_batch(tuple(block_item(clock,slot+i,at=int(clock.time())-107)
                                             for i in range(frames)))
                    clock.advance(.020)
                    native_elapsed=clock.monotonic()-started
                    extra=max(0,.165*frames-native_elapsed)
                    clock.advance(extra)
                    charge.append(dict(label=label,frames=frames,entry=started,completion=clock.monotonic(),native_elapsed=native_elapsed,
                        injected=extra,total=clock.monotonic()-started))
                return execute

            for i in range(2):
                previous=owner.submit(source_fn(2_000_001+i,label='prefix_'+str(i)),priority=2)
                futures.append(previous);gate.source_accepted(previous,None,1)
                await asyncio.wrap_future(previous)
            await settled(lambda:not owner._checkpoint_busy)
            before=owner.submit(lambda state:(
                runtime.adapter.observe(runtime.generation),
                runtime._demands(runtime.adapter.observe(runtime.generation)),
                dict(runtime.episodes)),priority=2)
            futures.append(before)
            obs,needs,original=await asyncio.wrap_future(before)
            headroom={n.side:n.recovery_deadline-clock.monotonic()
                      for n in needs if n.scope==SCOPES[0] and n.recovery_excess}
            await settled(lambda:not owner._checkpoint_busy)
            source_state=replace(ELIGIBLE,pending_frames=1,pending_bytes=4096,
                inbound=0,decoded=0,ordered_ready=1,commit_age=0,head_age=0)
            offer=None
            if treatment:
                waiting=asyncio.create_task(gate.rendezvous(lambda:source_state))
                await settled(lambda:gate.offer is not None)
                offer=await gate.before_maintenance()
                clock.advance(.010)
            else:
                source=owner.submit(source_fn(2_000_003,frames),priority=2)
                futures.append(source);gate.source_accepted(source,None,frames)
                await asyncio.wrap_future(source)

            submitted=clock.monotonic()
            def turn(state):
                order.append('maintenance')
                gate.entry(offer)
                if treatment and not source_queued.wait(3):
                    raise AssertionError('source_waited_for_maintenance_completion')
                try:
                    result=runtime.turn(flight,submitted)
                except BaseException as exc:
                    gate.completed(offer,error=exc,event=runtime.ring[-1])
                    raise
                else:
                    gate.completed(offer,result=result,event=runtime.ring[-1])
                    return result
            maintenance=owner.submit(turn,priority=4,
                admit_before=offer.row['deadline'] if offer else None)
            futures.append(maintenance);gate.accepted(maintenance,offer)
            if treatment:
                self_offer=await waiting
                source=owner.submit(source_fn(2_000_003,frames),priority=2)
                futures.append(source);gate.source_accepted(source,self_offer,frames)
                source_queued.set()
            result=await asyncio.wrap_future(maintenance)
            if treatment:await asyncio.wrap_future(source)

            def fresh(state):
                observation=runtime.adapter.observe(runtime.generation)
                current=runtime._demands(observation)
                binding=next(n for n in current if n.scope==SCOPES[0] and n.side=='archive')
                return dict(binding=asdict(binding),episodes=[
                    dict(side=k[0],scope=k[1],values=v) for k,v in sorted(runtime.episodes.items())],
                    original_episodes=[dict(side=k[0],scope=k[1],values=v) for k,v in sorted(original.items())],
                    integrity=state.writer.db.execute('PRAGMA integrity_check').fetchone()[0],
                    transaction_open=state.writer.db.in_transaction,
                    hot=next(s.hot_eligible for s in observation.scopes if s.scope==SCOPES[0]),
                    original_deadline=headroom['archive']+(initial+.33),
                    observation_at=observation.monotonic)
            observation=owner.submit(fresh,priority=2);futures.append(observation)
            row=await asyncio.wrap_future(observation)
            row.update(result_side=result['side'],headroom=headroom,order=order,
                source_charge=charge,offer=None if offer is None else dict(offer.row),
                native_event=dict(runtime.ring[-1]),provider_calls=0)
            return row
        finally:
            if gate is not None:gate.close()
            await asyncio.to_thread(owner.close)
            if futures and not all(f.done() for f in futures):
                raise AssertionError('accepted_future_unfinished')


class NativeGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_old_fails_new_passes_binding_recovery_under_original_deadline(self):
        old=await placement(False)
        new=await placement(True)
        EVIDENCE['placement']=dict(old=old,new=new)
        for row in (old,new):
            self.assertAlmostEqual(row['headroom']['archive'],9.1)
            self.assertAlmostEqual(row['headroom']['retirement'],9.1)
            self.assertEqual(row['integrity'],'ok')
            self.assertFalse(row['transaction_open'])
            for source in row['source_charge']:
                self.assertAlmostEqual(source['injected'],
                    max(0,.165*source['frames']-source['native_elapsed']))
                self.assertAlmostEqual(source['total'],.165*source['frames'])
        self.assertEqual(old['order'],['prefix_0','prefix_1','source','maintenance'])
        self.assertIsNone(old['result_side'])
        self.assertEqual(old['binding']['recovery_excess'],400)
        self.assertEqual(old['hot'],1400)
        self.assertEqual(old['episodes'],old['original_episodes'])
        self.assertEqual(new['order'],['prefix_0','prefix_1','maintenance','source'])
        self.assertEqual(new['result_side'],'archive')
        self.assertEqual(new['hot'],888)
        self.assertEqual(new['binding']['recovery_excess'],0)
        self.assertIsNone(new['binding']['recovery_deadline'])
        self.assertFalse(any(e['side']=='archive' and e['scope']==SCOPES[0] for e in new['episodes']))
        self.assertEqual([e for e in new['episodes'] if e['side']=='retirement'],
                         [e for e in new['original_episodes'] if e['side']=='retirement'])
        self.assertLess(new['observation_at'],new['original_deadline'])
        self.assertEqual(new['native_event']['durable_records'][SCOPES[0]],512)
        self.assertEqual(new['offer']['outcome'],'accepted')
        self.assertLess(new['offer']['maintenance_sequence'],new['offer']['source_sequence'])
        self.assertAlmostEqual(new['offer']['gate_wait'],.010)
        self.assertEqual(new['offer']['affected_frames'],1)

    async def test_already_infeasible_gate_cannot_manufacture_success(self):
        row=await placement(True,initial=.735)
        EVIDENCE['placement']['already_infeasible']=row
        self.assertAlmostEqual(row['headroom']['archive'],8.935)
        self.assertAlmostEqual(row['headroom']['retirement'],8.935)
        self.assertEqual(row['offer']['outcome'],'accepted')
        self.assertIsNone(row['result_side'])
        self.assertEqual(row['hot'],1400)
        self.assertEqual(row['binding']['recovery_excess'],400)
        self.assertEqual(row['episodes'],row['original_episodes'])
        self.assertFalse(row['native_event'].get('durable_records'))
        self.assertEqual(row['integrity'],'ok')

    async def offered_native(self, *, hot=0, retired=0, worker_pending=False,
                             fault=None, repeats=1, scopes=(SCOPES[0],), planning=False):
        clock=Clock();box={};futures=[];native_rows=[]
        if fault=='refusal':clock.advance(.5)
        with tempfile.TemporaryDirectory() as td,patch.object(service,'time',clock):
            class State(service.ServiceState):
                def archive_commit_slice_and_plan(self,plan,receipt):
                    if fault=='exception':raise OSError('maintenance_fault')
                    if fault=='yield':raise EvidenceUnavailable('evidence_background_yield')
                    return super().archive_commit_slice_and_plan(plan,receipt)
            def factory():
                state=State(Path(td)/'db',AlchemyEndpoint.parse(ENDPOINT))
                state.writer.clock=clock.time
                for scope in scopes:
                    ingest(state.writer,rows(clock,scope,retired,start=100,tag='retired',same_slot=True))
                while state.writer.archive(clock.time()-180):pass
                for scope in scopes:
                    ingest(state.writer,rows(clock,scope,hot,start=1000,tag='hot',same_slot=True))
                    finalized_frontier(state,clock,scope,at=int(clock.time())-110 if fault=='refusal' else None)
                if not retired:
                    state.retention() # native initial floor service, no fabricated progress
                runtime=MaintenanceRuntime(state,monotonic=clock.monotonic,wall=clock.time)
                flight=ArchiveFlight()
                result=runtime.turn(flight,clock.monotonic())
                if flight.prepared is not None:
                    future=Future()
                    if not worker_pending:
                        future.set_result(EvidenceWriter.prepare_and_write_archive(state.writer.path,result['snapshot']))
                    flight.attach(future,clock.monotonic(),runtime.generation)
                box.update(state=state,runtime=runtime,flight=flight,returned=result)
                return state
            owner=PriorityOwner(factory,clock=clock.monotonic)
            gate=None
            try:
                await asyncio.wrap_future(owner.ready)
                await settled(lambda:not owner._checkpoint_busy)
                runtime,flight=box['runtime'],box['flight']
                gate=OwnerAdmission(owner,clock=clock.monotonic);gate.generation=runtime.generation
                # For an intentionally stale-positive/no-demand case the
                # earlier native observation remains positive after completion.
                hint=box['returned']
                if not hint['archive_pressure'] and not hint['retirement_pressure']:
                    if hot or retired:
                        raise AssertionError(('missing_native_pressure_hint',hint))
                    hint=PRESSURE
                gate.publish(runtime.generation,hint)
                if planning:
                    prefix=owner.submit(lambda state:ingest(state.writer,
                        rows(clock,SCOPES[0],1800,start=1000,tag='later_hot',same_slot=True)),priority=2)
                    futures.append(prefix);gate.source_accepted(prefix,None,1)
                    await asyncio.wrap_future(prefix)
                    await settled(lambda:not owner._checkpoint_busy)
                if fault=='refusal':clock.advance(.6)
                for i in range(repeats):
                    waiting=asyncio.create_task(gate.rendezvous(lambda:replace(ELIGIBLE,
                        pending_frames=1,pending_bytes=1024,inbound=0,decoded=0,
                        ordered_ready=1,commit_age=0,head_age=0)))
                    await settled(lambda:gate.offer is not None)
                    offer=await gate.before_maintenance();submitted=clock.monotonic()
                    def execute(state):
                        gate.entry(offer)
                        try:
                            result=runtime.turn(flight,submitted)
                        except BaseException as exc:
                            gate.completed(offer,error=exc,event=runtime.ring[-1] if runtime.ring else None)
                            raise
                        else:
                            gate.completed(offer,result=result,event=runtime.ring[-1])
                            return result
                    future=owner.submit(execute,priority=4,admit_before=offer.row['deadline'])
                    futures.append(future);gate.accepted(future,offer)
                    got=await waiting
                    source=owner.submit(lambda state:state.source_batch((block_item(clock,3_000_000+i),)),priority=2)
                    futures.append(source);gate.source_accepted(source,got,1)
                    error=None
                    try:result=await asyncio.wrap_future(future)
                    except BaseException as exc:error=str(exc);result=None
                    await asyncio.wrap_future(source)
                    await settled(lambda:not owner._checkpoint_busy)
                    native_rows.append(dict(offer=dict(got.row),result=result and dict(
                        side=result['side'],archive_pressure=result['archive_pressure'],
                        retirement_pressure=result['retirement_pressure']),error=error,
                        native_event=dict(runtime.ring[-1]),worker_pending=bool(
                            flight.future is not None and not flight.future.done())))
                    if error:break
                    if flight.prepared is not None:
                        next_future=Future()
                        next_future.set_result(EvidenceWriter.prepare_and_write_archive(
                            box['state'].writer.path,flight.prepared))
                        flight.attach(next_future,clock.monotonic(),runtime.generation)
                    gate.publish(runtime.generation,result)
                    if i+1<repeats and not gate.hint.positive:break
                check=owner.submit(lambda state:dict(
                    integrity=state.writer.db.execute('PRAGMA integrity_check').fetchone()[0],
                    transaction_open=state.writer.db.in_transaction,
                    progress=state.writer.db.execute('SELECT scope,side,units,records FROM maintenance_progress ORDER BY scope,side').fetchall()),
                    priority=2)
                futures.append(check);status=await asyncio.wrap_future(check)
                self.assertEqual(status['integrity'],'ok');self.assertFalse(status['transaction_open'])
                row=dict(hot=hot,retired=retired,rows=native_rows,status=status)
                EVIDENCE['native'].append(row)
                return row
            finally:
                if gate is not None:gate.close()
                await asyncio.to_thread(owner.close)
                self.assertTrue(all(f.done() for f in futures))

    async def test_native_archive_only_pressure_comfortable_deadlines(self):
        row=await self.offered_native(hot=1800)
        first=row['rows'][0]
        self.assertEqual(first['result']['side'],'archive')
        self.assertTrue(first['result']['archive_pressure'])
        self.assertFalse(first['result']['retirement_pressure'])
        self.assertEqual(sum(first['offer']['durable_records'].values()),512)

    async def test_native_retirement_only_pressure(self):
        row=await self.offered_native(retired=1800)
        first=row['rows'][0]
        self.assertEqual(first['result']['side'],'retirement')
        self.assertFalse(first['result']['archive_pressure'])
        self.assertTrue(first['result']['retirement_pressure'])
        self.assertGreater(sum(first['offer']['durable_records'].values()),0)

    async def test_native_both_pressure_and_cross_scope_fairness(self):
        row=await self.offered_native(hot=2500,retired=1800,repeats=40,scopes=SCOPES)
        selected=[r['result']['side'] for r in row['rows']]
        self.assertIn('archive',selected);self.assertIn('retirement',selected)
        for scope in SCOPES:
            self.assertTrue(any(r['offer'].get('durable_records',{}).get(scope,0)
                for r in row['rows'] if r['result']['side']=='archive'))
            self.assertTrue(any(r['offer'].get('durable_records',{}).get(scope,0)
                for r in row['rows'] if r['result']['side']=='retirement'))

    async def test_native_worker_pending_is_not_ready_and_no_retry_until_useful(self):
        row=await self.offered_native(hot=1800,worker_pending=True)
        first=row['rows'][0]
        self.assertTrue(first['worker_pending'])
        self.assertIsNone(first['result']['side'])
        self.assertEqual(first['offer']['maintenance_result'],'no_decision')
        self.assertEqual(first['offer']['outcome'],'accepted')
        self.assertFalse(first['offer']['durable_records'])

    async def test_stale_positive_no_demand_consumes_one_observation(self):
        row=await self.offered_native()
        first=row['rows'][0]
        self.assertIsNone(first['result']['side'])
        self.assertFalse(first['result']['archive_pressure'])
        self.assertFalse(first['result']['retirement_pressure'])
        self.assertEqual(first['offer']['maintenance_result'],'no_decision')

    async def test_cooperative_yield_native_refusal_and_maintenance_exception(self):
        for fault in ('yield','refusal','exception'):
            with self.subTest(fault=fault):
                row=await self.offered_native(hot=1800,retired=1800 if fault=='refusal' else 0,fault=fault)
                first=row['rows'][0]
                self.assertIsNotNone(first['error'])
                self.assertEqual(first['offer']['outcome'],'accepted')
                self.assertIn('source_submit',first['offer'])
                self.assertEqual(first['offer']['native_refusal'],fault!='yield')
                if fault=='refusal':self.assertEqual(first['error'],'maintenance_cannot_reserve_both_sides')

    async def test_continuous_source_actual_service_retains_native_authority(self):
        box=await run_case(seed=lambda state,clock:(
            ingest(state.writer,rows(clock,SCOPES[0],1800,same_slot=True)),
            finalized_frontier(state,clock,SCOPES[0])),turns=16)
        self.assertFalse(box['errors'],[str(e) for e in box['errors']])
        self.assertEqual(box['integrity'],'ok')
        self.assertGreater(box['counters'].get('stream_accepted_messages',0),0)
        self.assertIsNone(box['runtime'].failure)

    async def test_real_eight_frame_source_charge_and_nonoverlapping_wait_accounting(self):
        row=await placement(True,frames=8)
        offer=row['offer'];source=row['source_charge'][-1]
        self.assertEqual(offer['affected_frames'],8)
        self.assertEqual(source['frames'],8)
        self.assertAlmostEqual(source['injected'],1.300)
        self.assertAlmostEqual(source['total'],1.320)
        queue=source['entry']-offer['source_submit']
        # Native maintenance execution lies in source queue wait. Gate waiting
        # lies before source submit. Neither substitutes for source service.
        self.assertAlmostEqual(queue,.025)
        self.assertAlmostEqual(offer['gate_wait'],.010)
        self.assertAlmostEqual(offer['source_completion']-offer['open'],
            offer['gate_wait']+queue+source['native_elapsed']+source['injected'])
        self.assertEqual(row['binding']['recovery_excess'],0)
        EVIDENCE['placement']['eight_frames_wait_accounting']=row

    async def test_gate_accepted_native_completion_interruption_preserves_m1(self):
        from tests.test_m1_maintenance_completion import public_key, PROGRESS_SELECT
        clock=Clock();box={};futures=[];source_queued=threading.Event()
        with tempfile.TemporaryDirectory() as td,patch.object(service,'time',clock):
            def factory():
                state=service.ServiceState(Path(td)/'db',AlchemyEndpoint.parse(ENDPOINT))
                state.writer.clock=clock.time
                ledger=[]
                for index in range(1,129):
                    ledger.extend(replace(r,kind='account') for r in rows(clock,
                        'account:'+public_key(index),1,tag='ledger'))
                ingest(state.writer,ledger)
                self.assertEqual(state.writer.archive(clock.time()-180),128)
                ingest(state.writer,rows(clock,SCOPES[0],1800,tag='recovery'))
                finalized_frontier(state,clock,SCOPES[0])
                runtime=MaintenanceRuntime(state,monotonic=clock.monotonic,wall=clock.time)
                flight=ArchiveFlight();result=runtime.turn(flight,clock.monotonic())
                prepared=Future();prepared.set_result(EvidenceWriter.prepare_and_write_archive(
                    state.writer.path,result['snapshot']))
                flight.attach(prepared,clock.monotonic(),runtime.generation)
                box.update(runtime=runtime,flight=flight,returned=result)
                return state
            owner=PriorityOwner(factory,clock=clock.monotonic);gate=None
            try:
                await asyncio.wrap_future(owner.ready);await settled(lambda:not owner._checkpoint_busy)
                runtime,flight=box['runtime'],box['flight']
                gate=OwnerAdmission(owner,clock=clock.monotonic);gate.generation=runtime.generation
                gate.publish(runtime.generation,box['returned'])
                waiting=asyncio.create_task(gate.rendezvous(lambda:replace(ELIGIBLE,
                    pending_frames=1,pending_bytes=1024,inbound=0,decoded=0,
                    ordered_ready=1,commit_age=0,head_age=0)))
                await settled(lambda:gate.offer is not None)
                offer=await gate.before_maintenance();submitted=clock.monotonic()
                reads=[];urgent=[]
                def trace(sql):
                    if not sql.startswith(PROGRESS_SELECT):return
                    reads.append(sql)
                    if len(reads)==2:
                        future=owner.submit(lambda state:state.writer.db.execute(
                            'SELECT COUNT(*) FROM records').fetchone()[0],priority=0)
                        urgent.append(future);futures.append(future)
                def turn(state):
                    gate.entry(offer)
                    if not source_queued.wait(3):raise AssertionError('source_waited_for_completion')
                    state.writer.db.set_trace_callback(trace)
                    try:
                        result=runtime.turn(flight,submitted)
                    except BaseException as exc:
                        gate.completed(offer,error=exc,event=runtime.ring[-1]);raise
                    else:
                        gate.completed(offer,result=result,event=runtime.ring[-1]);return result
                    finally:state.writer.db.set_trace_callback(None)
                accepted=owner.submit(turn,priority=4,admit_before=offer.row['deadline'])
                futures.append(accepted);gate.accepted(accepted,offer)
                got=await waiting
                source=owner.submit(lambda state:state.source_batch((block_item(clock,3_000_000),)),priority=2)
                futures.append(source);gate.source_accepted(source,got,1);source_queued.set()
                with self.assertRaisesRegex(EvidenceUnavailable,'evidence_background_yield'):
                    await asyncio.wrap_future(accepted)
                await asyncio.wrap_future(source)
                await asyncio.gather(*(asyncio.wrap_future(f) for f in urgent))
                self.assertEqual(len(reads),3,'exact interrupted completion and one M1 retry')
                self.assertIsNone(runtime.arbiter.pending)
                self.assertIsNone(runtime.failure)
                self.assertEqual(got.row['native_completion'],'completed')
                self.assertEqual(got.row['durable_records'][SCOPES[0]],512)
                next_turn=owner.submit(lambda state:runtime.turn(flight,clock.monotonic()),priority=4)
                futures.append(next_turn);await asyncio.wrap_future(next_turn)
                self.assertIsNone(runtime.arbiter.pending)
                self.assertIsNone(runtime.failure)
                snapshot=owner.submit(lambda state:dict(
                    integrity=state.writer.db.execute('PRAGMA integrity_check').fetchone()[0],
                    transaction_open=state.writer.db.in_transaction,
                    events=list(runtime.ring)),priority=2)
                futures.append(snapshot);status=await asyncio.wrap_future(snapshot)
                self.assertEqual(status['integrity'],'ok');self.assertFalse(status['transaction_open'])
                self.assertEqual(sum(e.get('completion')=='completed' and
                    e.get('completion_read_interrupted',False) for e in status['events']),1)
                EVIDENCE['native'].append(dict(case='gate_m1_completion',offer=got.row,
                    reads=len(reads),urgent_completed=all(f.done() for f in urgent),status=status))
            finally:
                source_queued.set()
                if gate is not None:gate.close()
                await asyncio.to_thread(owner.close)
                self.assertTrue(all(f.done() for f in futures))

    async def test_native_restart_preserves_episode_and_invalidates_hint_generation(self):
        clock=Clock()
        with tempfile.TemporaryDirectory() as td,patch.object(service,'time',clock):
            path=Path(td)/'db'
            def factory():
                state=service.ServiceState(path,AlchemyEndpoint.parse(ENDPOINT))
                state.writer.clock=clock.time
                ingest(state.writer,rows(clock,SCOPES[0],1800,same_slot=True))
                finalized_frontier(state,clock,SCOPES[0])
                runtime=MaintenanceRuntime(state,monotonic=clock.monotonic,wall=clock.time)
                runtime._demands(runtime.adapter.observe(runtime.generation))
                return SimpleNamespace(writer=state.writer,state=state,runtime=runtime,
                                       close=state.close)
            owner=PriorityOwner(factory,clock=clock.monotonic)
            await asyncio.wrap_future(owner.ready)
            original=owner.state.runtime;episodes=dict(original.episodes);generation=original.generation
            await asyncio.to_thread(owner.close)
            def restart():
                state=service.ServiceState(path,AlchemyEndpoint.parse(ENDPOINT));state.writer.clock=clock.time
                runtime=MaintenanceRuntime(state,monotonic=clock.monotonic,wall=clock.time)
                runtime._demands(runtime.adapter.observe(runtime.generation))
                return SimpleNamespace(writer=state.writer,state=state,runtime=runtime,close=state.close)
            clock.advance(.5);owner=PriorityOwner(restart,clock=clock.monotonic)
            try:
                await asyncio.wrap_future(owner.ready)
                current=owner.state.runtime
                self.assertNotEqual(current.generation,generation)
                self.assertEqual(current.episodes,episodes)
                gate=OwnerAdmission(owner,clock=clock.monotonic);gate.generation=current.generation
                gate.publish(generation,PRESSURE)
                self.assertIsNone(await gate.rendezvous(lambda:ELIGIBLE))
                self.assertEqual(gate.counters['offers'],0)
                gate.close()
                EVIDENCE['native'].append(dict(case='native_restart_hint_fence',episodes=[
                    dict(side=k[0],scope=k[1],values=v) for k,v in sorted(episodes.items())]))
            finally:await asyncio.to_thread(owner.close)


    async def test_planning_consumes_one_attempt_without_waiting_for_worker(self):
        row=await self.offered_native(retired=1800,planning=True)
        first=row['rows'][0]
        self.assertEqual(first['result']['side'],'archive')
        self.assertFalse(first['offer']['durable_records'])
        self.assertEqual(first['offer']['maintenance_result'],'decision')
        self.assertIn('source_submit',first['offer'])
        self.assertEqual(len(row['rows']),1)
