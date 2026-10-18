"""Independent FIFO permit ownership matrix on the actual SQLite owner.

Only virtual elapsed time and explicit barriers are controlled. No substituted
owner, fabricated future, provider, executor or maintenance-progress credit.
"""
import asyncio
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest

from meme_machine.solana_evidence_control import PriorityOwner
from meme_machine.solana_evidence_plane import EvidenceUnavailable, EvidenceWriter
from meme_machine.solana_owner_admission import OwnerAdmission
from tests.maintenance_production_harness import Clock


async def settled(predicate):
    for _ in range(3000):
        if predicate():return
        await asyncio.sleep(.001)
    raise AssertionError('native_owner_barrier_not_reached')


class MaintenancePermitOwnershipTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.clock=Clock()
        self.futures=[];self.releases=[];self.number=0
        def factory():
            writer=EvidenceWriter(Path(self.tmp.name)/'native.sqlite',clock=self.clock.time)
            return SimpleNamespace(writer=writer,events=[],close=writer.close)
        self.owner=PriorityOwner(factory,clock=self.clock.monotonic)
        await asyncio.wait_for(asyncio.wrap_future(self.owner.ready),3)
        await settled(lambda:not self.owner._checkpoint_busy and not self.owner.queue)

    async def asyncTearDown(self):
        for release in self.releases:release.set()
        with self.owner.cv:
            token=self.owner._checkpoint_handoff
        if token is not None:self.owner.release_checkpoint_handoff(token)
        self.owner.close()
        self.assertFalse(self.owner.thread.is_alive())
        self.assertTrue(all(f.done() and not f.cancelled() for f in self.futures))
        self.tmp.cleanup()

    def callback(self,label,*,elapsed=0,entered=None,release=None,wait_closed=False):
        self.number+=1;number=self.number
        def execute(state):
            if entered is not None:entered.set()
            if release is not None and not release.wait(5):
                raise AssertionError('native_source_callback_not_released')
            if wait_closed:
                with self.owner.cv:
                    if not self.owner.cv.wait_for(lambda:self.owner.closed,5):
                        raise AssertionError('native_owner_close_not_observed')
            # Genuine private native mutation; it never acknowledges a gap or
            # grants historical completeness. Event order follows the commit.
            state.writer.gap('program:pump',number,number,'offline_permit_fixture')
            self.clock.advance(elapsed)
            state.events.append((label,self.clock.monotonic()))
            return label
        return execute

    def submit(self,fn,priority=2):
        future=self.owner.submit(fn,priority=priority)
        self.futures.append(future);return future

    def submit_maintenance(self,fn,ticket):
        future=self.owner.submit_maintenance(fn,ticket)
        self.futures.append(future);return future

    async def completed(self,future):
        return await asyncio.wait_for(asyncio.shield(asyncio.wrap_future(future)),3)

    async def opened(self,ticket):
        self.assertIs(await self.completed(ticket.ready),ticket)
        self.assertEqual(ticket.state,'OPEN')
        self.assertIsNone(ticket.command_future)
        return ticket

    async def blocked_source(self,label='current',*,elapsed=0):
        entered=threading.Event();release=threading.Event();self.releases.append(release)
        future=self.submit(self.callback(label,elapsed=elapsed,entered=entered,release=release))
        await settled(entered.is_set)
        return future,release

    async def test_old_work_wait_does_not_backdate_the_actual_new_command(self):
        current,release=await self.blocked_source(elapsed=4)
        older=self.submit(self.callback('older',elapsed=4))
        requested=self.clock.monotonic()
        ticket=self.owner.request_maintenance_boundary(deadline=30)
        younger=self.submit(self.callback('younger',elapsed=.25))
        self.assertEqual(ticket.state,'PENDING')
        self.assertFalse(ticket.ready.done())
        self.assertEqual(ticket.requested_at,requested)
        self.assertLess(older.owner_sequence,ticket.requested_sequence)
        release.set();await self.completed(current);await self.completed(older)
        await self.opened(ticket)
        self.assertEqual(self.clock.monotonic(),8)
        self.assertFalse(younger.done())
        self.assertAlmostEqual(ticket.permit_deadline,8.1)
        submitted=self.clock.monotonic();entry=[]
        native=self.callback('maintenance',elapsed=.5)
        def fresh(state):
            entry.append(self.clock.monotonic())
            if entry[-1]-submitted>3:raise EvidenceUnavailable('evidence_command_expired')
            return native(state)
        command=self.submit_maintenance(fresh,ticket)
        self.assertIs(ticket.command_future,command)
        self.assertEqual(command.owner_accepted_at,submitted)
        self.assertGreater(command.owner_accepted_at-ticket.requested_at,3)
        self.assertGreater(command.owner_sequence,younger.owner_sequence)
        self.assertEqual(await self.completed(command),'maintenance')
        await self.completed(younger)
        await settled(lambda:ticket.state=='RELEASED')
        self.assertEqual(entry,[8])
        self.assertEqual([name for name,_ in self.owner.state.events],
                         ['current','older','maintenance','younger'])
        self.assertEqual(ticket.state,'RELEASED')

    async def test_full_normal_queue_rejects_ticket_then_reserves_one_existing_slot(self):
        current,release=await self.blocked_source(elapsed=4)
        second_entered=threading.Event();second_release=threading.Event()
        self.releases.append(second_release)
        capacity=self.owner.capacity-self.owner.reserved
        queued=[self.submit(self.callback('older0',entered=second_entered,release=second_release))]
        queued.extend(self.submit(self.callback('older'+str(i),elapsed=.01)) for i in range(1,capacity))
        with self.assertRaises(EvidenceUnavailable):
            self.owner.request_maintenance_boundary(deadline=30)
        release.set();await settled(second_entered.is_set)
        self.assertEqual(await self.completed(current),'current')
        ticket=self.owner.request_maintenance_boundary(deadline=30)
        self.assertEqual(ticket.requested_at,4)
        self.assertEqual(ticket.state,'PENDING')
        with self.assertRaises(EvidenceUnavailable):
            self.submit(self.callback('over_capacity'))
        second_release.set()
        for future in queued:await self.completed(future)
        await self.opened(ticket)
        submitted=self.clock.monotonic()
        command=self.submit_maintenance(self.callback('maintenance'),ticket)
        self.assertEqual(command.owner_accepted_at,submitted)
        self.assertGreaterEqual(command.owner_accepted_at,4.5)
        self.assertEqual(await self.completed(command),'maintenance')
        await settled(lambda:ticket.state=='RELEASED')
        self.assertEqual(ticket.state,'RELEASED')

    async def test_second_ticket_cannot_replace_pending_open_or_accepted_owner(self):
        current,release=await self.blocked_source()
        ticket=self.owner.request_maintenance_boundary(deadline=30)
        with self.assertRaises(EvidenceUnavailable):self.owner.request_maintenance_boundary(deadline=30)
        release.set();await self.completed(current);await self.opened(ticket)
        with self.assertRaises(EvidenceUnavailable):self.owner.request_maintenance_boundary(deadline=30)
        entered=threading.Event();done=threading.Event();self.releases.append(done)
        command=self.submit_maintenance(self.callback('maintenance',entered=entered,release=done),ticket)
        await settled(entered.is_set)
        self.assertEqual(ticket.state,'ACCEPTED')
        with self.assertRaises(EvidenceUnavailable):self.owner.request_maintenance_boundary(deadline=30)
        done.set();await self.completed(command)
        await settled(lambda:ticket.state=='RELEASED')
        replacement=self.owner.request_maintenance_boundary(deadline=30)
        await self.opened(replacement)
        self.assertTrue(self.owner.cancel_maintenance_boundary(replacement))

    async def test_urgent_zero_and_one_invalidate_only_unspent_open_permit(self):
        for priority in (0,1):
            with self.subTest(priority=priority):
                ticket=self.owner.request_maintenance_boundary(deadline=30)
                await self.opened(ticket)
                younger=self.submit(self.callback('source'+str(priority)))
                urgent=self.submit(self.callback('urgent'+str(priority)),priority)
                await self.completed(urgent);await self.completed(younger)
                self.assertEqual(ticket.state,'RELEASED')
                self.assertIsNone(ticket.command_future)
                with self.assertRaises(EvidenceUnavailable):
                    self.submit_maintenance(self.callback('stale'),ticket)
                self.assertEqual([name for name,_ in self.owner.state.events][-2:],
                                 ['urgent'+str(priority),'source'+str(priority)])
                await settled(lambda:not self.owner._checkpoint_busy and not self.owner.queue)

    async def test_checkpoint_handoff_and_open_permit_never_overlap(self):
        first=self.submit(lambda state:self.owner.checkpoint_handoff_after_current())
        token=await self.completed(first)
        ticket=self.owner.request_maintenance_boundary(deadline=30)
        await asyncio.sleep(.01)
        self.assertFalse(ticket.ready.done());self.assertEqual(ticket.state,'PENDING')
        self.owner.release_checkpoint_handoff(token)
        await self.opened(ticket)
        second=self.submit(lambda state:self.owner.checkpoint_handoff_after_current())
        await asyncio.sleep(.01)
        self.assertFalse(second.done())
        self.assertTrue(self.owner.cancel_maintenance_boundary(ticket))
        token=await self.completed(second)
        self.assertEqual(ticket.state,'RELEASED')
        self.owner.release_checkpoint_handoff(token)

    async def test_cancel_pending_ticket_restores_exact_normal_queue_capacity(self):
        current,release=await self.blocked_source()
        capacity=self.owner.capacity-self.owner.reserved
        queued=[self.submit(self.callback('older'+str(i))) for i in range(capacity-1)]
        ticket=self.owner.request_maintenance_boundary(deadline=30)
        with self.assertRaises(EvidenceUnavailable):self.submit(self.callback('over_capacity'))
        self.assertTrue(self.owner.cancel_maintenance_boundary(ticket))
        self.assertEqual(ticket.state,'RELEASED');self.assertTrue(ticket.ready.done())
        replacement=self.submit(self.callback('replacement'))
        with self.assertRaises(EvidenceUnavailable):self.submit(self.callback('still_over_capacity'))
        release.set();await self.completed(current)
        for future in queued:await self.completed(future)
        await self.completed(replacement)
        self.assertIsNone(ticket.command_future)

    async def test_cancelling_waiter_never_cancels_an_accepted_native_callback(self):
        ticket=self.owner.request_maintenance_boundary(deadline=30);await self.opened(ticket)
        entered=threading.Event();release=threading.Event();self.releases.append(release)
        command=self.submit_maintenance(self.callback('maintenance',entered=entered,release=release),ticket)
        await settled(entered.is_set)
        self.assertEqual(ticket.state,'ACCEPTED')
        self.assertFalse(self.owner.cancel_maintenance_boundary(ticket))
        waiter=asyncio.shield(asyncio.wrap_future(command));waiter.cancel()
        with self.assertRaises(asyncio.CancelledError):await waiter
        self.assertFalse(command.cancelled());self.assertFalse(command.done())
        self.assertIs(ticket.command_future,command)
        release.set();self.assertEqual(await self.completed(command),'maintenance')
        await settled(lambda:ticket.state=='RELEASED')
        self.assertEqual(ticket.state,'RELEASED')
        self.assertEqual([name for name,_ in self.owner.state.events],['maintenance'])

    async def test_pending_waiter_cancel_releases_slot_without_cancelling_old_work(self):
        current,release=await self.blocked_source()
        ticket=self.owner.request_maintenance_boundary(deadline=30)
        wrapped=asyncio.wrap_future(ticket.ready)
        wrapped.add_done_callback(lambda future:future.exception() if not future.cancelled() else None)
        async def wait_for_boundary():
            try:return await asyncio.shield(wrapped)
            finally:self.owner.cancel_maintenance_boundary(ticket)
        waiter=asyncio.create_task(wait_for_boundary())
        await asyncio.sleep(0);waiter.cancel()
        with self.assertRaises(asyncio.CancelledError):await waiter
        self.assertEqual(ticket.state,'RELEASED')
        self.assertFalse(ticket.ready.cancelled())
        self.assertFalse(current.cancelled());self.assertFalse(current.done())
        replacement=self.submit(self.callback('replacement'))
        release.set();await self.completed(current);await self.completed(replacement)
        self.assertEqual([name for name,_ in self.owner.state.events],['current','replacement'])

    async def test_expired_open_permit_cannot_accept_or_redate_a_command(self):
        ticket=self.owner.request_maintenance_boundary(deadline=30);await self.opened(ticket)
        requested=ticket.requested_at;deadline=ticket.permit_deadline
        self.clock.advance(.101)
        with self.assertRaises(EvidenceUnavailable):
            self.submit_maintenance(self.callback('expired'),ticket)
        self.assertEqual(ticket.state,'RELEASED')
        self.assertIsNone(ticket.command_future)
        self.assertEqual(ticket.requested_at,requested)
        self.assertEqual(ticket.permit_deadline,deadline)
        ordinary=self.submit(self.callback('source'))
        self.assertEqual(await self.completed(ordinary),'source')
        self.assertEqual([name for name,_ in self.owner.state.events],['source'])

    async def test_notification_cancel_is_atomic_with_the_actual_owner_claim(self):
        for cancel_first in (True,False):
            with self.subTest(cancel_before_claim=cancel_first):
                current,release=await self.blocked_source()
                ticket=self.owner.request_maintenance_boundary(deadline=30)
                claimed=threading.Event();finish_claim=threading.Event()
                self.releases.append(finish_claim)
                original=ticket.ready.set_running_or_notify_cancel
                def gated_claim():
                    if not cancel_first:result=original()
                    claimed.set()
                    if not finish_claim.wait(5):raise AssertionError('notification_claim_not_released')
                    return original() if cancel_first else result
                # Gate the real Future's atomic operation, never replace the
                # Future or cancel a native accepted-command future.
                ticket.ready.set_running_or_notify_cancel=gated_claim
                following=self.submit(self.callback('following'))
                release.set();await settled(claimed.is_set)
                self.assertEqual(ticket.ready.cancel(),cancel_first)
                finish_claim.set();await self.completed(current)
                if cancel_first:
                    await settled(lambda:ticket.state=='RELEASED')
                    self.assertTrue(ticket.ready.cancelled())
                    self.assertIsNone(ticket.permit_deadline)
                    self.assertIsNone(ticket.command_future)
                else:
                    await self.opened(ticket)
                    command=self.submit_maintenance(self.callback('maintenance'),ticket)
                    await self.completed(command)
                await self.completed(following)
                self.assertTrue(self.owner.thread.is_alive())
                self.assertEqual(self.owner.state.events[-1][0],'following')
                self.assertEqual(ticket.state,'RELEASED')

    async def test_pending_refusal_notification_cancel_cannot_kill_the_writer(self):
        current,release=await self.blocked_source()
        ticket=self.owner.request_maintenance_boundary(deadline=1)
        publishing=threading.Event();finish_publish=threading.Event()
        self.releases.append(finish_publish)
        original=ticket.ready.set_exception
        def gated_refusal(error):
            publishing.set()
            if not finish_publish.wait(5):raise AssertionError('notification_refusal_not_released')
            return original(error)
        ticket.ready.set_exception=gated_refusal
        following=self.submit(self.callback('following'))
        self.clock.advance(1);release.set()
        await settled(publishing.is_set)
        cancelled=ticket.ready.cancel()
        finish_publish.set();await self.completed(current);await self.completed(following)
        self.assertEqual(ticket.state,'RELEASED')
        self.assertIsNone(ticket.permit_deadline);self.assertIsNone(ticket.command_future)
        if cancelled:self.assertTrue(ticket.ready.cancelled())
        else:self.assertIsInstance(ticket.ready.exception(),EvidenceUnavailable)
        self.assertTrue(self.owner.thread.is_alive())
        self.assertEqual(self.owner.state.events[-1][0],'following')

    async def test_actual_boundary_pending_cancel_and_stop_preserve_old_work(self):
        for outcome in ('cancel','stop'):
            with self.subTest(outcome=outcome):
                current,release=await self.blocked_source()
                admission=OwnerAdmission(self.owner,clock=self.clock.monotonic)
                stop=asyncio.Event();task=asyncio.create_task(admission.boundary(30,stop))
                await settled(lambda:self.owner._maintenance_ticket is not None)
                ticket=self.owner._maintenance_ticket
                self.assertEqual(ticket.state,'PENDING')
                if outcome=='cancel':
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):await task
                else:
                    stop.set();self.assertIsNone(await asyncio.wait_for(task,3))
                self.assertEqual(ticket.state,'RELEASED')
                self.assertFalse(ticket.ready.cancelled())
                self.assertFalse(current.cancelled());self.assertFalse(current.done())
                following=self.submit(self.callback('following'))
                release.set();await self.completed(current);await self.completed(following)
                self.assertEqual(self.owner.state.events[-1][0],'following')

    async def test_stop_or_cancel_during_handoff_cleanup_cannot_lose_the_permit(self):
        class GatedStop:
            def __init__(self):
                self.event=asyncio.Event();self.started=asyncio.Event()
                self.cleaning=asyncio.Event();self.release=asyncio.Event();self.finished=asyncio.Event()
            def is_set(self):return self.event.is_set()
            async def wait(self):
                self.started.set()
                try:return await self.event.wait()
                finally:
                    self.cleaning.set()
                    try:await self.release.wait()
                    finally:self.finished.set()
        for outcome in ('cancel','stop'):
            with self.subTest(outcome=outcome):
                current,release=await self.blocked_source()
                admission=OwnerAdmission(self.owner,clock=self.clock.monotonic)
                stop=GatedStop();task=asyncio.create_task(admission.boundary(30,stop))
                await asyncio.wait_for(stop.started.wait(),3)
                ticket=self.owner._maintenance_ticket
                release.set();await self.completed(current)
                await asyncio.wait_for(stop.cleaning.wait(),3)
                self.assertEqual(ticket.state,'OPEN')
                following=self.submit(self.callback('following'))
                try:
                    if outcome=='cancel':
                        task.cancel()
                        with self.assertRaises(asyncio.CancelledError):await task
                    else:
                        stop.event.set();stop.release.set()
                        self.assertIsNone(await asyncio.wait_for(task,3))
                finally:stop.release.set()
                await settled(stop.finished.is_set)
                self.assertEqual(ticket.state,'RELEASED')
                self.assertIsNone(ticket.command_future)
                await self.completed(following)
                self.assertEqual(self.owner.state.events[-1][0],'following')

    async def test_actual_boundary_full_queue_retries_keep_the_absolute_deadline(self):
        current,release=await self.blocked_source()
        capacity=self.owner.capacity-self.owner.reserved
        queued=[self.submit(self.callback('older'+str(i))) for i in range(capacity)]
        admission=OwnerAdmission(self.owner,clock=self.clock.monotonic)
        original=self.owner.request_maintenance_boundary;attempts=[0];deadlines=set()
        def recorded(*,deadline):
            attempts[0]+=1;deadlines.add(deadline)
            return original(deadline=deadline)
        self.owner.request_maintenance_boundary=recorded
        task=asyncio.create_task(admission.boundary(3,asyncio.Event()))
        try:
            await settled(lambda:attempts[0]>=2)
            self.clock.advance(3)
            with self.assertRaisesRegex(EvidenceUnavailable,'maintenance_boundary_deadline'):
                await asyncio.wait_for(task,3)
        finally:self.owner.request_maintenance_boundary=original
        self.assertEqual(deadlines,{3})
        self.assertEqual(admission.counters['boundary_deadline_exhausted'],1)
        self.assertIsNone(self.owner._maintenance_ticket)
        self.assertFalse(current.cancelled());self.assertFalse(current.done())
        release.set();await self.completed(current)
        for future in queued:await self.completed(future)

    async def test_shutdown_releases_pending_ticket_and_completes_older_callback(self):
        entered=threading.Event()
        current=self.submit(self.callback('current',entered=entered,wait_closed=True))
        await settled(entered.is_set)
        ticket=self.owner.request_maintenance_boundary(deadline=30)
        self.assertEqual(ticket.state,'PENDING')
        self.owner.close()
        self.assertFalse(self.owner.thread.is_alive())
        self.assertEqual(current.result(),'current')
        self.assertTrue(ticket.ready.done());self.assertEqual(ticket.state,'RELEASED')
        self.assertIsNone(ticket.command_future)
        with self.assertRaises(EvidenceUnavailable):self.owner.request_maintenance_boundary(deadline=30)

    async def test_shutdown_preserves_an_accepted_native_future_until_commit(self):
        ticket=self.owner.request_maintenance_boundary(deadline=30);await self.opened(ticket)
        entered=threading.Event()
        command=self.submit_maintenance(self.callback('maintenance',entered=entered,wait_closed=True),ticket)
        await settled(entered.is_set)
        self.assertEqual(ticket.state,'ACCEPTED')
        self.assertFalse(self.owner.cancel_maintenance_boundary(ticket))
        self.owner.close()
        self.assertFalse(self.owner.thread.is_alive())
        self.assertFalse(command.cancelled());self.assertEqual(command.result(),'maintenance')
        self.assertEqual(ticket.state,'RELEASED')
        self.assertEqual([name for name,_ in self.owner.state.events],['maintenance'])
