"""One publication turn preserves accounting, FULL receipts and cancellation.

The canonical writer runs on the real PriorityOwner thread. The small work
adapter retains production admit/accepted/shield behavior; only failure points
and scheduling barriers are injected. All economics and authority are offline
disposable fixtures, never evidence of live readiness or financial activity.
"""
import asyncio
import ast
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from meme_machine.solana_evidence_control import PriorityOwner, admit
from meme_machine import solana_evidence_service as service
from meme_machine.solana_evidence_plane import EvidenceUnavailable, IntervalProof, digest
from meme_machine.solana_history_delivery import capture, deliver, acknowledge
from meme_machine.solana_rolling_history import program_scope
from meme_machine.solana_selective_history import PROGRAMS, economic_records
from meme_machine.solana_selective_source import SelectiveSource, source_work
from tests import test_contained_source_observation as funding_fixture
from tests.test_solana_closure import NOW, state_at
from tests.test_solana_selective_evidence import FIXTURE


class OwnedWork:
    """Actual serve.work, without bootstrapping providers or other service tasks.

    Compile only its unchanged AST and capability assignment against its real
    module globals plus this native owner/counter closure. The hooks observe
    admission/completion; they do not replace scheduling, timers or shielding.
    """
    candidate_delivery_continuation = True
    def __init__(self, owner):
        self.owner = owner
        self.calls = []
        self.futures = []
        self.before = None
        self.returned = None
        self.counts = {}
        tree = ast.parse(Path(service.__file__).read_text())
        serve = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == 'serve')
        work = next(node for node in serve.body if isinstance(node, ast.AsyncFunctionDef) and node.name == 'work')
        capability = next(node for node in serve.body if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)
            and target.value.id == 'work' and target.attr == 'candidate_delivery_continuation'
            for target in node.targets))
        namespace = dict(vars(service), owner=owner, counts=self.counts, asyncio=asyncio, admit=admit)
        exec(compile(ast.Module(body=[work, capability], type_ignores=[]), service.__file__, 'exec'), namespace)
        self.native = namespace['work']

    async def __call__(self, fn, priority=1, *, label=None, component=None,
            accepted=None, admit_before=None, continuation=None):
        self.calls.append((priority, label, component))
        if self.before is not None:
            await self.before(len(self.calls), label, component)
        def observed(future):
            self.futures.append(future)
            if accepted is not None:accepted(future)
        answer = await self.native(fn, priority, label=label, component=component,
            accepted=observed, admit_before=admit_before, continuation=continuation)
        if self.returned is not None:
            self.returned(label, component)
        return answer


class PublicationAccountingTurnTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.funding = funding_fixture.ObservationFundingClosureTests('runTest')
        self.funding.setUp()
        self.addCleanup(self.funding.doCleanups)
        self.financial_before = self.funding.facts()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'canonical.sqlite'
        self.native = {}
        self.releases = []
        self.tasks = []
        self.events = []

        def factory():
            state, history = state_at(self.path)
            history.lifecycle.delivery_separated = True
            rows = [row for tx in FIXTURE['pump'] for row in economic_records(
                'pump', PROGRAMS['pump'], tx, endpoint_identity='a'*64,
                seen=NOW, source='alchemy_finalized_stream')]
            history.ingest(rows)
            self.native.update(state=state, history=history)
            state.close = state.writer.close
            return state

        self.owner = PriorityOwner(factory)
        await asyncio.wrap_future(self.owner.ready)
        # Establish actual consumer ACKs for the retained economics before the
        # operation under test. No outbox receipt or financial result is forged.
        events = await self.query(lambda s: capture(self.native['history'].lifecycle))
        self.assertIsNotNone(events)
        self.assertTrue(events['rows'])
        result = deliver(events)
        self.assertTrue(await self.query(lambda s:
            acknowledge(self.native['history'].lifecycle, events, result)))
        self.canonical_before = await self.canonical_facts()
        self.source = SelectiveSource(SimpleNamespace(credential='offline', identity='a'*64), None)
        self.source.stop = asyncio.Event()
        self.source.batched = True
        self.work = OwnedWork(self.owner)
        self.source.work = source_work(self.work, self.source.stop)
        self.key = (int(NOW)//86400, 'pump', 'yellowstone')

    async def asyncTearDown(self):
        self.source.stop.set()
        for release in self.releases:
            release.set()
        for task in self.tasks:
            if not task.done():
                task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        try:
            self.assertEqual(await self.canonical_facts(), self.canonical_before)
            self.assertEqual(self.funding.facts(), self.financial_before)
        finally:
            await asyncio.to_thread(self.owner.close)

    async def query(self, fn, priority=0):
        return await asyncio.wrap_future(self.owner.submit(fn, priority=priority))

    async def canonical_facts(self):
        names = ('records', 'rolling_economic_events', 'candidate_content_receipts',
            'native_order_attestations', 'candidate_outbox', 'cursors')
        return await self.query(lambda state: {name: state.writer.db.execute(
            'SELECT * FROM '+name+' ORDER BY rowid').fetchall() for name in names})

    async def accounting(self):
        return await self.query(lambda state: state.writer.db.execute(
            'SELECT family,transport,raw_bytes FROM provider_delivery ORDER BY family,transport').fetchall())

    async def proof(self, *, ack=False):
        scope = program_scope('pumpswap')
        def prepare(state):
            life = self.native['history'].lifecycle
            life.defer_proof(IntervalProof(scope, 100, 101, 'alchemy_finalized_stream', 'a'*64,
                dict(finalized=True, complete=True, scope=scope, lower_slot=100,
                    upper_slot=101, lineage_hash=digest([scope, 100, 101])), NOW))
            return capture(life)
        snapshot = await self.query(prepare)
        self.assertEqual(len(snapshot['proofs']), 1)
        result = deliver(snapshot)
        with closing(sqlite3.connect(self.native['history'].lifecycle.path)) as reader:
            self.assertEqual(reader.execute('PRAGMA synchronous').fetchone()[0], 2)
            identity = 'coverage:'+snapshot['proofs'][0]['identity']
            raw, checksum = reader.execute('SELECT body,hash FROM source_receipts WHERE id=?',
                (identity,)).fetchone()
            self.assertEqual(json.loads(raw)['identity'], snapshot['proofs'][0]['identity'])
            self.assertEqual(len(checksum), 64)
        if ack:
            self.assertTrue(await self.query(lambda state:
                acknowledge(self.native['history'].lifecycle, snapshot, result)))
        return snapshot, result

    def publication(self, snapshot, *, expected_bytes=None):
        identities = tuple(snapshot['publication_ids'])
        def after(state):
            self.assertFalse(state.writer.db.in_transaction)
            if expected_bytes is not None:
                self.assertEqual(state.writer.db.execute(
                    'SELECT raw_bytes FROM provider_delivery WHERE family=? AND transport=?',
                    ('pump', 'yellowstone')).fetchone(), (expected_bytes,))
            self.events.append('publication')
            life = self.native['history'].lifecycle
            life.publish(proof_ids=identities)
            return life._published_count
        return after

    async def assert_published(self, snapshot, published=True):
        identity = snapshot['proofs'][0]['identity']
        pending = await self.query(lambda state: state.writer.db.execute(
            'SELECT id FROM candidate_pending_proofs WHERE id=?', (identity,)).fetchone())
        self.assertEqual(pending is None, published)
        missing = await self.query(lambda state: self.native['history'].rolling.missing(
            'pumpswap', program_scope('pumpswap'), 100, 101))
        self.assertEqual(missing, [] if published else [(100, 101)])

    async def wait_entered(self, entered):
        self.assertTrue(await asyncio.to_thread(entered.wait, 2), 'owner callback did not reach its barrier')

    def held(self):
        entered, release = threading.Event(), threading.Event()
        self.releases.append(release)
        return entered, release

    def start(self, awaitable):
        task = asyncio.create_task(awaitable)
        self.tasks.append(task)
        return task

    async def scouts(self, count, *, start=0):
        """Real durable outbox/consumer receipts; not a market-capacity claim."""
        def seed(state):
            life = self.native['history'].lifecycle
            with state.writer.transaction():
                for number in range(start, start+count):
                    life.emit('pump', 'handoff:'+str(number), 'scout',
                        dict(slot=100+number, seen=NOW, fields={}), at=NOW)
            return capture(life, schedule=True)
        return await self.query(seed)

    async def pending_scouts(self):
        return await self.query(lambda state: state.writer.db.execute(
            "SELECT id FROM candidate_history_outbox WHERE address LIKE 'handoff:%' "
            'AND consumed IS NULL ORDER BY priority,created,rowid').fetchall())

    async def enable_capture_actor(self):
        from meme_machine.solana_history_delivery import capture_context
        from meme_machine.solana_history_notifications import delivery_hint,install as notifications
        loop=asyncio.get_running_loop()
        self.work.candidate_delivery_capture_actor=True
        self.source.work=source_work(self.work,self.source.stop)
        def seed(state):
            history=self.native['history']
            notifications(history,loop,self.source.history_changed,capture_hints=True)
            return capture_context(history.lifecycle),delivery_hint(history)
        context,hint=await self.query(seed)
        self.source.delivery_capture_context=context;self.source._history_delivery_hint(hint)

    async def test_capture_actor_uses_consumer_thread_and_only_owner_acks_with_original_cadence(self):
        from meme_machine import solana_history_delivery as delivery
        from meme_machine.solana_history_notifications import WorkPulse
        await self.scouts(129);await self.enable_capture_actor()
        original=delivery.CaptureActor.capture;captures=[];threads=[]
        loop=asyncio.get_running_loop();event_thread=threading.get_ident()
        class ObservedPulse(WorkPulse):
            def __init__(self):super().__init__();self.delays=[]
            async def wait(self,seen,stop,*,delay=None):
                self.delays.append(delay)
                return await super().wait(seen,stop,delay=delay)
        self.source.delivery_urgent=ObservedPulse()
        def observed(actor,*args,**kwargs):
            threads.append(threading.get_ident());snapshot=original(actor,*args,**kwargs)
            captures.append(None if snapshot is None else len(snapshot['rows']))
            if snapshot is None:loop.call_soon_threadsafe(self.source.stop.set)
            return snapshot
        pool=ThreadPoolExecutor(max_workers=1);self.source.delivery_executor=pool
        try:
            with patch.object(delivery.CaptureActor,'capture',observed):
                await asyncio.wait_for(self.source.candidate_history_delivery(),3)
        finally:await asyncio.to_thread(pool.shutdown,wait=True)
        self.assertEqual(captures,[64,64,1,None])
        self.assertEqual(len(set(threads)),1);self.assertNotEqual(threads[0],event_thread)
        self.assertEqual([label for _,label,_ in self.work.calls],['candidate_delivery_ack']*3)
        self.assertEqual(await self.pending_scouts(),[])
        self.assertTrue(any(delay is not None and 0<delay<=.1 for delay in self.source.delivery_urgent.delays))
        self.assertNotIn('owner.stage.candidate_delivery_capture.calls',self.work.counts)

    async def test_capture_actor_canceled_accepted_delivery_full_commits_and_acks_without_proof_publication(self):
        from meme_machine import solana_history_delivery as delivery
        proof,_=await self.proof();await self.scouts(1);await self.enable_capture_actor()
        original=delivery.deliver;original_ack=delivery.acknowledge_actor
        entered,release=self.held();ack_entered,ack_release=self.held();acks=[];physical=[]
        def held(snapshot):
            result=original(snapshot);entered.set()
            if not release.wait(3):raise RuntimeError('offline-actor-delivery-release')
            return result
        def held_ack(*args):
            acks.append(True);ack_entered.set()
            if not ack_release.wait(3):raise RuntimeError('offline-actor-ack-release')
            return original_ack(*args)
        pool=ThreadPoolExecutor(max_workers=1)
        class TrackedExecutor:
            def submit(_self,*args,**kwargs):
                future=pool.submit(*args,**kwargs);physical.append(future);return future
        self.source.delivery_executor=TrackedExecutor()
        try:
            with patch.object(delivery,'deliver',held),patch.object(delivery,'acknowledge_actor',held_ack):
                task=self.start(self.source.candidate_history_delivery())
                await self.wait_entered(entered);task.cancel('original-actor-delivery-cancel');await asyncio.sleep(0)
                task.cancel('second-actor-delivery-cancel');await asyncio.sleep(0)
                self.assertFalse(task.done(),'accepted physical consumer work was abandoned')
                self.assertEqual(len(physical),2);self.assertFalse(physical[1].done())
                self.assertFalse(physical[1].cancelled())
                await self.query(lambda state:state.writer.db.execute(
                    "INSERT INTO service_health VALUES('actor-cancel-progress','1')"))
                release.set();await self.wait_entered(ack_entered)
                self.assertTrue(physical[1].done())
                task.cancel('actor-cancel-during-owner-ack');await asyncio.sleep(0)
                self.assertFalse(task.done(),'repeated cancel cut the owned cleanup before its fresh ACK')
                ack_release.set()
                with self.assertRaises(asyncio.CancelledError) as caught:await task
                self.assertEqual(caught.exception.args,('original-actor-delivery-cancel',))
            self.assertEqual(await self.pending_scouts(),[])
            await self.assert_published(proof,False)
            self.assertEqual(acks,[True])
            self.assertEqual([label for _,label,_ in self.work.calls],['candidate_delivery_ack'])
        finally:
            release.set();ack_release.set();await asyncio.to_thread(pool.shutdown,wait=True)

    async def test_capture_actor_cancellation_joins_physical_read_and_preserves_pending_work(self):
        from meme_machine import solana_history_delivery as delivery
        await self.proof();await self.scouts(1);await self.enable_capture_actor()
        original=delivery._CaptureReader.unconsumed;entered,release=self.held()
        def held(reader,*args,**kwargs):
            entered.set()
            if not release.wait(3):raise RuntimeError('offline-actor-read-release')
            return original(reader,*args,**kwargs)
        pool=ThreadPoolExecutor(max_workers=1);self.source.delivery_executor=pool
        try:
            with patch.object(delivery._CaptureReader,'unconsumed',held):
                task=self.start(self.source.candidate_history_delivery())
                await self.wait_entered(entered);task.cancel('original-actor-read-cancel');await asyncio.sleep(0)
                task.cancel('second-actor-read-cancel');await asyncio.sleep(0)
                self.assertFalse(task.done(),'accepted read outlived its coroutine teardown')
                await self.query(lambda state:state.writer.db.execute(
                    "INSERT INTO service_health VALUES('actor-read-progress','1')"))
                release.set()
                with self.assertRaises(asyncio.CancelledError) as caught:await task
                self.assertEqual(caught.exception.args,('original-actor-read-cancel',))
            self.assertEqual(len(await self.pending_scouts()),1)
            self.assertEqual(self.work.calls,[],'read cancellation admitted an unnecessary owner operation')
            self.assertEqual(await self.query(lambda state:state.writer.db.execute(
                'PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0]),0)
        finally:
            release.set();await asyncio.to_thread(pool.shutdown,wait=True)

    async def test_capture_actor_repeated_cancel_preserves_original_cancel_after_terminal_read_failure(self):
        from meme_machine import solana_history_delivery as delivery
        await self.proof();await self.scouts(1);await self.enable_capture_actor()
        entered,release=self.held();physical=[];failure=RuntimeError('offline-terminal-capture-error')
        def failed_read(reader,*args,**kwargs):
            entered.set()
            if not release.wait(3):raise RuntimeError('offline-failed-read-release')
            raise failure
        pool=ThreadPoolExecutor(max_workers=1)
        class TrackedExecutor:
            def submit(_self,*args,**kwargs):
                future=pool.submit(*args,**kwargs);physical.append(future);return future
        self.source.delivery_executor=TrackedExecutor()
        try:
            with patch.object(delivery._CaptureReader,'unconsumed',failed_read):
                task=self.start(self.source.candidate_history_delivery())
                await self.wait_entered(entered);task.cancel('original-failing-read-cancel');await asyncio.sleep(0)
                task.cancel('second-failing-read-cancel');await asyncio.sleep(0)
                self.assertFalse(task.done());self.assertFalse(physical[0].done())
                release.set()
                with self.assertRaises(asyncio.CancelledError) as caught:await task
                self.assertEqual(caught.exception.args,('original-failing-read-cancel',))
            self.assertTrue(physical[0].done());self.assertIs(physical[0].exception(),failure)
            self.assertEqual(len(await self.pending_scouts()),1)
            self.assertEqual(self.work.calls,[])
            self.assertEqual(await self.query(lambda state:state.writer.db.execute(
                'PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0]),0)
        finally:
            release.set();await asyncio.to_thread(pool.shutdown,wait=True)

    async def test_capture_actor_cancel_cleanup_ack_failure_stops_without_retry_or_publication(self):
        from meme_machine import solana_history_delivery as delivery
        proof,_=await self.proof();await self.scouts(1);await self.enable_capture_actor()
        entered,release=self.held();ack_entered,ack_release=self.held()
        original=delivery.deliver;failure=RuntimeError('offline-terminal-cancel-ack-error');acks=[]
        def held(snapshot):
            result=original(snapshot);entered.set()
            if not release.wait(3):raise RuntimeError('offline-cancel-failed-ack-delivery-release')
            return result
        def failed_ack(*args):
            acks.append(True);ack_entered.set()
            if not ack_release.wait(3):raise RuntimeError('offline-cancel-failed-ack-release')
            raise failure
        pool=ThreadPoolExecutor(max_workers=1);self.source.delivery_executor=pool
        try:
            with patch.object(delivery,'deliver',held),patch.object(delivery,'acknowledge_actor',failed_ack):
                task=self.start(self.source.candidate_history_delivery())
                await self.wait_entered(entered);task.cancel();await asyncio.sleep(0)
                release.set();await self.wait_entered(ack_entered)
                task.cancel();await asyncio.sleep(0);self.assertFalse(task.done())
                ack_release.set()
                with self.assertRaises(RuntimeError) as caught:await task
                self.assertIs(caught.exception,failure)
            self.assertEqual(acks,[True]);self.assertEqual(len(await self.pending_scouts()),1)
            self.assertEqual([label for _,label,_ in self.work.calls],['candidate_delivery_ack'])
            await self.assert_published(proof,False)
        finally:
            release.set();ack_release.set();await asyncio.to_thread(pool.shutdown,wait=True)

    async def test_capture_actor_empty_read_keeps_callback_arriving_before_thread_returns(self):
        from meme_machine import solana_history_delivery as delivery
        await self.enable_capture_actor()
        original=delivery.CaptureActor.capture
        entered,release=self.held();captures=[];loop=asyncio.get_running_loop()
        def observed(actor,*args,**kwargs):
            snapshot=original(actor,*args,**kwargs)
            captures.append(None if snapshot is None else len(snapshot['rows']))
            if snapshot is None and not entered.is_set():
                entered.set()
                if not release.wait(3):raise RuntimeError('offline-empty-actor-release')
            elif snapshot is None:loop.call_soon_threadsafe(self.source.stop.set)
            return snapshot
        pool=ThreadPoolExecutor(max_workers=1);self.source.delivery_executor=pool
        try:
            with patch.object(delivery.CaptureActor,'capture',observed):
                task=self.start(self.source.candidate_history_delivery())
                await self.wait_entered(entered)
                await self.scouts(1)
                release.set();await asyncio.wait_for(task,3)
            self.assertEqual(captures,[None,1,None])
            self.assertEqual(await self.pending_scouts(),[])
            self.assertTrue(all(label=='candidate_delivery_ack' for _,label,_ in self.work.calls))
        finally:
            release.set();self.source.stop.set();await asyncio.to_thread(pool.shutdown,wait=True)

    async def test_capture_actor_read_busy_retains_capture_failure_site(self):
        from meme_machine import solana_history_delivery as delivery
        await self.enable_capture_actor()
        error=sqlite3.OperationalError('offline-read-busy');error.sqlite_errorcode=sqlite3.SQLITE_BUSY
        pool=ThreadPoolExecutor(max_workers=1);self.source.delivery_executor=pool
        try:
            with patch.object(delivery.CaptureActor,'capture',side_effect=error):
                with self.assertRaises(sqlite3.OperationalError) as caught:
                    await self.source.candidate_history_delivery()
            self.assertIs(caught.exception,error)
            self.assertEqual(self.work.calls,[],'capture failure became a consumer-write retry')
        finally:await asyncio.to_thread(pool.shutdown,wait=True)

    async def test_capture_actor_continuous_arrivals_finish_refresh_sweeps_without_starving_outbox(self):
        from meme_machine import solana_history_delivery as delivery
        from meme_machine.solana_history_notifications import WorkPulse
        life=self.native['history'].lifecycle
        def seed(state):
            with state.writer.transaction():
                for index in range(65):
                    state.writer.db.execute('INSERT INTO candidate_lifecycle VALUES(?,?,?,?,?,?,?,?,?,?)',
                        ('pump','actor-refresh:'+str(index),'queued',0,100,100,NOW,NOW,NOW+50,100))
            life.refresh()
        await self.query(seed);await self.enable_capture_actor()
        original=self.source._complete_history_delivery;finished=[];sizes=[];arrivals=[]
        class ObservedPulse(WorkPulse):
            def __init__(self):super().__init__();self.delays=[]
            async def wait(self,seen,stop,*,delay=None):
                self.delays.append(delay)
                return await super().wait(seen,stop,delay=delay)
        self.source.delivery_urgent=ObservedPulse()
        async def complete(snapshot,result,**options):
            sizes.append(len(snapshot['refresh']))
            if len(finished)<3:
                number=len(arrivals)
                identity=await self.query(lambda state:life.emit('pump','refresh-arrival:'+str(number),
                    'scout',dict(fields={})))
                arrivals.append(identity)
            accepted=await original(snapshot,result,**options)
            if snapshot['refresh_scan']['finished']:
                finished.append(snapshot['capture_ack'].refresh_cleared)
                if finished[-1]:self.source.stop.set()
            return accepted
        pool=ThreadPoolExecutor(max_workers=1);self.source.delivery_executor=pool
        try:
            with patch.object(self.source,'_complete_history_delivery',complete):
                await asyncio.wait_for(self.source.candidate_history_delivery(),5)
            # Consuming the last arrival on the next first page changes the
            # conservative all-delivery revision too. One final quiet sweep
            # must then clear; neither cursor reset nor unbounded rescan wins.
            self.assertEqual(finished,[False,False,False,False,True])
            self.assertEqual(sizes,[64,1]*5,'arrivals reset an active refresh cursor or extended its fixed horizon')
            self.assertTrue(arrivals)
            for identity in arrivals:
                self.assertIsNotNone(await self.query(lambda state:state.writer.db.execute(
                    'SELECT consumed FROM candidate_history_outbox WHERE id=?',(identity,)).fetchone()[0]))
            self.assertTrue(any(delay is not None and delay>0 for delay in self.source.delivery_urgent.delays),
                'conservative EOF rejection busy-spun instead of retaining the original cadence')
            self.assertTrue(all(label=='candidate_delivery_ack' for _,label,_ in self.work.calls))
        finally:
            self.source.stop.set();await asyncio.to_thread(pool.shutdown,wait=True)

    async def test_full_batches_carry_one_capture_and_short_batch_keeps_original_coalescing(self):
        await self.scouts(129)
        captures = []
        original = capture
        loop = asyncio.get_running_loop()
        def observed(life, **options):
            snapshot = original(life, **options)
            captures.append(None if snapshot is None else len(snapshot['rows']))
            if snapshot is None:loop.call_soon_threadsafe(self.source.stop.set)
            return snapshot
        from meme_machine.solana_history_notifications import WorkPulse
        class ObservedPulse(WorkPulse):
            def __init__(self):super().__init__();self.delays=[]
            async def wait(self, seen, stop, *, delay=None):
                self.delays.append(delay)
                return await super().wait(seen, stop, delay=delay)
        self.source.delivery_urgent = ObservedPulse()
        pool = ThreadPoolExecutor(max_workers=1)
        self.source.delivery_executor = pool
        try:
            with patch('meme_machine.solana_history_delivery.capture', observed):
                await asyncio.wait_for(self.source.candidate_history_delivery(), 3)
        finally:await asyncio.to_thread(pool.shutdown, wait=True)
        self.assertEqual(captures, [64, 64, 1, None])
        self.assertEqual([label for _, label, _ in self.work.calls],
            ['candidate_delivery_capture', 'candidate_delivery_ack',
             'candidate_delivery_ack', 'candidate_delivery_ack', 'candidate_delivery_capture'])
        self.assertEqual(await self.pending_scouts(), [])
        self.assertEqual(len(self.source.delivery_urgent.delays), 1)
        self.assertGreater(self.source.delivery_urgent.delays[0], 0)
        self.assertLessEqual(self.source.delivery_urgent.delays[0], .1)
        counters = self.work.counts
        self.assertEqual(counters['owner.stage.candidate_delivery_capture.calls'], 4)
        self.assertEqual(counters['owner.stage.candidate_delivery_ack.calls'], 3)
        self.assertGreaterEqual(counters['owner.priority2.execution_total_microseconds'],
            counters['owner.stage.candidate_delivery_ack.execution_total_microseconds']+
            counters['owner.stage.candidate_delivery_capture.execution_total_microseconds'])

    async def test_queued_priority_zero_and_one_win_the_post_ack_claim_boundary(self):
        from meme_machine.solana_history_delivery import acknowledge as original
        for priority in (0, 1):
            with self.subTest(priority=priority):
                snapshot = await self.scouts(64, start=priority*64)
                result = deliver(snapshot)
                entered, release = self.held()
                events = []
                def held_ack(life, snapshot, result):
                    accepted = original(life, snapshot, result)
                    events.append('ack_committed');entered.set()
                    if not release.wait(3):raise RuntimeError('offline-ack-release')
                    return accepted
                def next_capture(state):
                    events.append('continuation')
                    return capture(self.native['history'].lifecycle, schedule=True)
                with patch('meme_machine.solana_history_delivery.acknowledge', held_ack):
                    task = self.start(self.source._complete_history_delivery(
                        snapshot, result, continuation=next_capture))
                    await self.wait_entered(entered)
                    urgent = self.owner.submit(lambda state: events.append('urgent'), priority=priority)
                    release.set();self.assertTrue(await task)
                    await asyncio.wrap_future(urgent)
                self.assertEqual(events, ['ack_committed', 'urgent'])
                await self.source.work(lambda state: events.append('ordinary_capture'), 2,
                    label='candidate_delivery_capture')
                self.assertEqual(events[-2:], ['urgent', 'ordinary_capture'])
                self.assertFalse(self.owner._continuation_claimed)

    async def test_after_claim_urgent_waits_only_one_capture_then_older_source_runs_before_next_ack(self):
        snapshot = await self.scouts(65)
        result = deliver(snapshot)
        entered, release = self.held()
        events = []
        carried = []
        def next_capture(state):
            events.append('capture_started')
            active = self.owner.telemetry()['active_operation']
            self.assertEqual((active['stage'], active['priority']), ('candidate_delivery_ack', 2))
            epoch = self.owner._checkpoint_epoch
            carried.append(capture(self.native['history'].lifecycle, schedule=True))
            self.assertEqual(self.owner._checkpoint_epoch, epoch)
            self.assertFalse(self.owner.try_continuation(lambda state: events.append('second_capture')))
            entered.set()
            if not release.wait(3):raise RuntimeError('offline-capture-release')
            events.append('capture_finished')
        task = self.start(self.source._complete_history_delivery(snapshot, result, continuation=next_capture))
        await self.wait_entered(entered)
        urgent = self.owner.submit(lambda state: events.append('urgent'), priority=0)
        older = self.owner.submit(lambda state: events.append('older_source'), priority=2)
        self.assertFalse(urgent.done());self.assertFalse(older.done())
        release.set();self.assertTrue(await task)
        # A subsequent consumer/ACK is a new ordinary admission, not another
        # owner continuation. Already admitted mandatory work retains service.
        self.assertTrue(await self.source._complete_history_delivery(carried[0], deliver(carried[0])))
        await asyncio.gather(asyncio.wrap_future(urgent), asyncio.wrap_future(older))
        self.assertEqual(events, ['capture_started', 'capture_finished', 'urgent', 'older_source'])
        self.assertEqual(await self.pending_scouts(), [])
        self.assertFalse(self.owner._continuation_claimed)
        self.assertEqual(self.work.counts['owner.stage.candidate_delivery_capture.calls'], 1)
        self.assertEqual(self.work.counts['owner.stage.candidate_delivery_capture.queue_total_microseconds'], 0)
        self.assertGreater(self.work.counts['owner.stage.candidate_delivery_capture.execution_total_microseconds'], 0)

    async def test_pending_maintenance_boundary_declines_continuation_and_retains_fifo_service(self):
        from meme_machine.solana_history_delivery import acknowledge as original
        snapshot = await self.scouts(64)
        result = deliver(snapshot)
        entered, release = self.held()
        events = []
        def held_ack(life, snapshot, result):
            accepted = original(life, snapshot, result);entered.set()
            if not release.wait(3):raise RuntimeError('offline-ack-release')
            return accepted
        with patch('meme_machine.solana_history_delivery.acknowledge', held_ack):
            task = self.start(self.source._complete_history_delivery(snapshot, result,
                continuation=lambda state: events.append('continuation')))
            await self.wait_entered(entered)
            older = self.owner.submit(lambda state: events.append('older_source'), priority=2)
            ticket = self.owner.request_maintenance_boundary(deadline=time.monotonic()+3)
            try:
                release.set();self.assertTrue(await task)
                await asyncio.wrap_future(older)
                await asyncio.wait_for(asyncio.wrap_future(ticket.ready), 2)
                self.assertEqual(events, ['older_source'])
                self.assertEqual(ticket.state, 'OPEN')
            finally:self.owner.cancel_maintenance_boundary(ticket)
        await self.source.work(lambda state: events.append('ordinary_capture'), 2,
            label='candidate_delivery_capture')
        self.assertEqual(events, ['older_source', 'ordinary_capture'])

    async def test_durable_proof_ids_without_consumer_proofs_keep_separate_publication_admission(self):
        await self.proof()
        snapshot = await self.scouts(64)
        self.assertEqual(snapshot['proofs'], [])
        self.assertEqual(len(snapshot['publication_ids']), 1)
        attempted = []
        self.assertTrue(await self.source._complete_history_delivery(snapshot, deliver(snapshot),
            continuation=lambda state: attempted.append(True)))
        self.assertEqual(attempted, [])
        self.assertEqual(self.work.calls, [(2, 'candidate_delivery_ack', None),
            (2, 'source_commit', 'history_publication')])
        self.assertTrue(snapshot['proof_publication_changed'])

    async def test_invalid_or_stale_ack_never_captures_and_legacy_work_keeps_original_path(self):
        snapshot = await self.scouts(64)
        result = deliver(snapshot)
        attempted = []
        continuation = lambda state: attempted.append(True)
        result['acknowledgements'].reverse()
        with self.assertRaisesRegex(EvidenceUnavailable, 'candidate_delivery_ack_order'):
            await self.source._complete_history_delivery(snapshot, result, continuation=continuation)
        self.assertEqual(len(await self.pending_scouts()), 64)
        result['acknowledgements'].reverse()
        native_work = self.source.work
        calls = []
        async def legacy(fn, priority=1, *, label=None):
            calls.append(label)
            return await asyncio.wrap_future(self.owner.submit(fn, priority=priority))
        try:
            self.source.work = source_work(legacy, self.source.stop)
            self.assertFalse(self.source.work.candidate_delivery_continuation)
            self.assertTrue(await self.source._complete_history_delivery(snapshot, result, continuation=continuation))
        finally:self.source.work = native_work
        self.assertEqual(attempted, [])
        self.assertEqual(calls, ['candidate_delivery_ack'])
        snapshot = await self.scouts(64, start=64)
        result = deliver(snapshot)
        await self.query(lambda state: self.native['history'].startup.begin())
        self.assertFalse(await self.source._complete_history_delivery(snapshot, result, continuation=continuation))
        self.assertEqual(attempted, [])
        self.assertEqual(len(await self.pending_scouts()), 64)

    async def test_checkpoint_handoff_and_failed_continuation_leave_no_reusable_claim(self):
        from meme_machine.solana_history_delivery import acknowledge as original
        snapshot = await self.scouts(64)
        result = deliver(snapshot)
        tokens = []
        attempted = []
        def handoff_ack(life, snapshot, result):
            accepted = original(life, snapshot, result)
            tokens.append(self.owner.checkpoint_handoff_after_current())
            return accepted
        try:
            with patch('meme_machine.solana_history_delivery.acknowledge', handoff_ack):
                self.assertTrue(await self.source._complete_history_delivery(snapshot, result,
                    continuation=lambda state: attempted.append(True)))
            self.assertEqual(attempted, [])
        finally:
            if tokens:self.owner.release_checkpoint_handoff(tokens[0])
        snapshot = await self.scouts(64, start=64)
        failure = RuntimeError('offline-continuation-failure')
        def broken(state):raise failure
        with self.assertRaises(RuntimeError) as caught:
            await self.source._complete_history_delivery(snapshot, deliver(snapshot), continuation=broken)
        self.assertIs(caught.exception, failure)
        self.assertEqual(await self.pending_scouts(), [])
        self.assertFalse(self.owner._continuation_claimed)
        self.assertEqual(self.work.counts['owner.stage.candidate_delivery_capture.calls'], 1)
        snapshot = await self.scouts(64, start=128)
        self.assertTrue(await self.source._complete_history_delivery(snapshot, deliver(snapshot),
            continuation=lambda state: attempted.append(True)))
        self.assertEqual(attempted, [True])
        self.assertEqual(self.work.counts['owner.stage.candidate_delivery_capture.calls'], 2)

    async def test_next_capture_error_is_raised_after_successful_ack_without_retry_or_reclassification(self):
        await self.scouts(65)
        original = capture
        failure = RuntimeError('offline-next-capture-failure')
        captures = []
        def fail_second(life, **options):
            captures.append(True)
            if len(captures) == 2:raise failure
            return original(life, **options)
        pool = ThreadPoolExecutor(max_workers=1)
        self.source.delivery_executor = pool
        try:
            with patch('meme_machine.solana_history_delivery.capture', fail_second):
                with self.assertRaises(RuntimeError) as caught:
                    await asyncio.wait_for(self.source.candidate_history_delivery(), 3)
            self.assertIs(caught.exception, failure)
        finally:await asyncio.to_thread(pool.shutdown, wait=True)
        self.assertEqual(len(captures), 2)
        self.assertEqual(self.work.calls, [(2, 'candidate_delivery_capture', None),
            (2, 'candidate_delivery_ack', None)])
        self.assertEqual(len(await self.pending_scouts()), 1)
        self.assertEqual(self.work.counts['owner.stage.candidate_delivery_capture.calls'], 2)
        self.assertEqual(self.work.counts['owner.stage.candidate_delivery_ack.calls'], 1)
        self.assertEqual(self.source.pipeline_metrics['history_delivery_timing:shared']['calls'], 1)
        self.assertFalse(self.owner._continuation_claimed)

    async def test_transient_next_capture_retries_only_capture_with_original_backoff(self):
        original = capture
        original_sleep = asyncio.sleep
        loop = asyncio.get_running_loop()
        for index, reason in enumerate(('evidence_background_yield', 'evidence_control_overloaded')):
            with self.subTest(reason=reason):
                self.source.stop = asyncio.Event()
                self.source.work = source_work(self.work, self.source.stop)
                await self.scouts(65, start=index*65)
                captures = []
                delays = []
                before = len(self.work.calls)
                def transient(life, **options):
                    captures.append(True)
                    if len(captures) == 2:raise EvidenceUnavailable(reason)
                    snapshot = original(life, **options)
                    if snapshot is None:loop.call_soon_threadsafe(self.source.stop.set)
                    return snapshot
                async def observed_sleep(delay):
                    delays.append(delay)
                    await original_sleep(delay)
                pool = ThreadPoolExecutor(max_workers=1)
                self.source.delivery_executor = pool
                try:
                    with patch('meme_machine.solana_history_delivery.capture', transient), patch(
                            'meme_machine.solana_selective_source.asyncio.sleep', observed_sleep):
                        await asyncio.wait_for(self.source.candidate_history_delivery(), 3)
                finally:await asyncio.to_thread(pool.shutdown, wait=True)
                self.assertIn(.01, delays)
                self.assertEqual(len(captures), 4)
                self.assertEqual([label for _, label, _ in self.work.calls[before:]],
                    ['candidate_delivery_capture', 'candidate_delivery_ack',
                     'candidate_delivery_capture', 'candidate_delivery_ack', 'candidate_delivery_capture'])
                self.assertEqual(await self.pending_scouts(), [])

    async def test_revision_inserted_behind_carried_scan_remains_visible_after_retained_tail(self):
        from meme_machine.solana_history_notifications import install as notifications
        from meme_machine import solana_history_delivery as delivery
        loop = asyncio.get_running_loop()
        scope = program_scope('pump')
        def add(life, slot):
            life.defer_proof(IntervalProof(scope, slot, slot, 'alchemy_finalized_stream', 'a'*64,
                dict(finalized=True, complete=True, scope=scope, lower_slot=slot,
                    upper_slot=slot, lineage_hash=digest([scope, slot])), NOW))
        def seed(state):
            history = self.native['history']
            notifications(history, loop, self.source.history_changed)
            with state.writer.transaction():
                for slot in range(100, 230):add(history.lifecycle, slot)
        await self.query(seed)
        await self.scouts(64)
        life = self.native['history'].lifecycle
        entered, release = self.held()
        original = capture
        original_page = delivery._proof_page
        pages = []
        captured = []
        finished = asyncio.Event()
        terminal = []
        original_complete = self.source._complete_history_delivery
        async def completed(snapshot, result, **options):
            accepted = await original_complete(snapshot, result, **options)
            if (accepted and 99 in pages and not snapshot['proof_scan']['more']
                    and not (snapshot['rows'] or snapshot['proofs'] or snapshot['refresh']
                             or snapshot['publication_ids'])):
                terminal.append(snapshot)
                finished.set()
            return accepted
        def page(*args, **kwargs):
            rows = original_page(*args, **kwargs)
            pages.extend(row[3] for row in rows)
            return rows
        def observed(life, **options):
            snapshot = original(life, **options)
            captured.append(snapshot)
            if len(captured) == 2:
                entered.set()
                if not release.wait(3):raise RuntimeError('offline-carried-scan-release')
            return snapshot
        pool = ThreadPoolExecutor(max_workers=1)
        self.source.delivery_executor = pool
        try:
            with patch.object(life, 'unconsumed', return_value=True), patch(
                    'meme_machine.solana_history_delivery.capture', observed), patch(
                    'meme_machine.solana_history_delivery._proof_page', page), patch.object(
                    self.source, '_complete_history_delivery', completed):
                task = self.start(self.source.candidate_history_delivery())
                await self.wait_entered(entered)
                self.assertEqual([label for _, label, _ in self.work.calls],
                    ['candidate_delivery_capture', 'candidate_delivery_ack'])
                def insert(state):
                    with state.writer.transaction():add(life, 99)
                inserted = self.owner.submit(insert, priority=2)
                release.set();await asyncio.wrap_future(inserted)
                await asyncio.wait_for(finished.wait(), 3)
                self.assertEqual(await self.query(lambda state: life._proof_delivery_progress),
                    terminal[-1]['proof_scan']['next'])
                count = len(captured)
                await asyncio.sleep(.03)
                self.assertEqual(len(captured), count, 'finished blocked work must sleep without another capture')
                self.assertFalse(task.done())
                self.source.stop.set()
                await asyncio.wait_for(task, 3)
        finally:
            release.set();self.source.stop.set()
            await asyncio.to_thread(pool.shutdown, wait=True)
        self.assertIn(99, pages)
        self.assertLess(pages.index(228), pages.index(99))
        self.assertLess(len(captured), 12, 'unchanged blocked pages restarted themselves')
        self.assertEqual(await self.pending_scouts(), [])
        self.assertEqual(await self.query(lambda state: state.writer.db.execute(
            'SELECT COUNT(*) FROM candidate_pending_proofs').fetchone()), (131,))
        self.assertFalse(any(snapshot and snapshot['publication_ids'] for snapshot in captured))

    async def test_empty_carried_capture_has_no_idle_poll_and_keeps_later_notification(self):
        await self.scouts(64)
        original = capture
        captures = []
        idle = asyncio.Event()
        loop = asyncio.get_running_loop()
        def observed(life, **options):
            snapshot = original(life, **options)
            captures.append(None if snapshot is None else len(snapshot['rows']))
            if len(captures) == 3:loop.call_soon_threadsafe(idle.set)
            return snapshot
        pool = ThreadPoolExecutor(max_workers=1)
        self.source.delivery_executor = pool
        try:
            with patch('meme_machine.solana_history_delivery.capture', observed):
                task = self.start(self.source.candidate_history_delivery())
                await asyncio.wait_for(idle.wait(), 2)
                await asyncio.sleep(.03)
                self.assertEqual(captures, [64, None, None])
                await self.scouts(1, start=64)
                self.source.history_changed(publication=False)
                for _ in range(100):
                    if not await self.pending_scouts():break
                    await asyncio.sleep(.01)
                self.assertEqual(await self.pending_scouts(), [])
                self.source.stop.set();await asyncio.wait_for(task, 2)
        finally:
            self.source.stop.set()
            await asyncio.to_thread(pool.shutdown, wait=True)

    async def test_canceled_accepted_handoff_preserves_full_ack_and_unconsumed_restart_rows(self):
        snapshot = await self.scouts(65)
        result = deliver(snapshot)
        entered, release = self.held()
        carried = []
        def held_capture(state):
            carried.append(capture(self.native['history'].lifecycle, schedule=True))
            entered.set()
            if not release.wait(3):raise RuntimeError('offline-capture-release')
        task = self.start(self.source._complete_history_delivery(snapshot, result, continuation=held_capture))
        await self.wait_entered(entered)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertFalse(self.work.futures[-1].done())
        release.set();completed = await asyncio.wrap_future(self.work.futures[-1])
        self.assertIs(completed[0], True)
        pending = await self.pending_scouts()
        self.assertEqual(pending, [(row[0],) for row in carried[0]['rows']])
        self.assertEqual(len(pending), 1)
        old = self.owner
        await asyncio.to_thread(old.close)
        def reopen():
            state, history = state_at(self.path)
            history.lifecycle.delivery_separated = True
            self.native.update(state=state, history=history)
            state.close = state.writer.close
            return state
        self.owner = PriorityOwner(reopen)
        await asyncio.wrap_future(self.owner.ready)
        self.work = OwnedWork(self.owner)
        self.source.work = source_work(self.work, self.source.stop)
        replay = await self.query(lambda state: capture(self.native['history'].lifecycle, schedule=True))
        self.assertEqual([row[0] for row in replay['rows']], [row[0] for row in carried[0]['rows']])
        self.assertTrue(await self.source._complete_history_delivery(replay, deliver(replay)))
        self.assertEqual(await self.pending_scouts(), [])
        self.assertFalse(self.owner._continuation_claimed)

    async def test_ack_remains_separate_with_real_priority_zero_before_combined_turn(self):
        snapshot, result = await self.proof()
        self.source.pending_delivery[self.key] = (123, NOW)
        urgent = []
        def returned(label, component):
            if label == 'candidate_delivery_ack':
                def protect(state):
                    self.events.append('priority_zero')
                    self.assertEqual(state.writer.db.execute(
                        'SELECT count(*) FROM provider_delivery').fetchone(), (0,))
                    urgent.append(True)
                self.owner.submit(protect, priority=0)
        self.work.returned = returned
        original = self.native['history'].delivery
        def observed(*args, **kwargs):
            self.events.append('accounting')
            return original(*args, **kwargs)
        with patch.object(self.native['history'], 'delivery', observed):
            self.assertTrue(await self.source._complete_history_delivery(snapshot, result))
        self.assertEqual(urgent, [True])
        self.assertEqual(self.events, ['priority_zero', 'accounting'])
        self.assertEqual(self.work.calls, [(2, 'candidate_delivery_ack', None),
            (2, 'source_commit', 'history_publication')])
        self.assertEqual(await self.accounting(), [('pump', 'yellowstone', 123)])
        self.assertEqual(self.source.pending_delivery, {})
        self.assertTrue(snapshot['proof_publication_changed'])
        await self.assert_published(snapshot)

    async def test_standalone_and_empty_publication_keep_existing_noop_and_return_contracts(self):
        self.assertIsNone(await self.source.flush_delivery())
        self.assertEqual(self.work.calls, [])
        self.source.pending_delivery[self.key] = (123, NOW)
        self.assertIsNone(await self.source.flush_delivery())
        self.assertEqual(self.work.calls, [(2, 'source_commit', 'delivery_accounting')])
        snapshot, _ = await self.proof(ack=True)
        self.assertEqual(await self.source.flush_delivery(self.publication(snapshot, expected_bytes=123)), 1)
        self.assertEqual(self.work.calls[-1], (2, 'source_commit', 'history_publication'))
        self.assertEqual(await self.accounting(), [('pump', 'yellowstone', 123)])
        self.assertEqual(self.source.pending_delivery, {})
        await self.assert_published(snapshot)

    async def test_accounting_rollback_retains_delta_and_never_calls_publication(self):
        snapshot, _ = await self.proof(ack=True)
        self.source.pending_delivery[self.key] = (123, NOW)
        original = self.native['history'].delivery
        def broken(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError('offline-accounting-rollback')
        with patch.object(self.native['history'], 'delivery', broken):
            with self.assertRaisesRegex(RuntimeError, 'offline-accounting-rollback'):
                await self.source.flush_delivery(self.publication(snapshot))
        self.assertEqual(self.events, [])
        self.assertEqual(await self.accounting(), [])
        self.assertEqual(self.source.pending_delivery, {self.key: (123, NOW)})
        await self.assert_published(snapshot, False)
        self.assertEqual(await self.source.flush_delivery(self.publication(snapshot, expected_bytes=123)), 1)
        self.assertEqual(await self.accounting(), [('pump', 'yellowstone', 123)])
        await self.assert_published(snapshot)

    async def test_postcommit_publication_failure_settles_exact_delta_once(self):
        snapshot, _ = await self.proof(ack=True)
        self.source.pending_delivery[self.key] = (123, NOW)
        def broken(state):
            self.assertFalse(state.writer.db.in_transaction)
            self.assertEqual(state.writer.db.execute('SELECT raw_bytes FROM provider_delivery').fetchone(), (123,))
            raise RuntimeError('offline-publication-failure')
        with self.assertRaisesRegex(RuntimeError, 'offline-publication-failure'):
            await self.source.flush_delivery(broken)
        self.assertEqual(self.source.pending_delivery, {})
        self.assertEqual(await self.accounting(), [('pump', 'yellowstone', 123)])
        await self.assert_published(snapshot, False)
        self.assertEqual(await self.source.flush_delivery(self.publication(snapshot, expected_bytes=123)), 1)
        self.assertEqual(await self.accounting(), [('pump', 'yellowstone', 123)])
        await self.assert_published(snapshot)

    async def test_commit_then_retryable_publication_failures_never_repeat_accounting(self):
        snapshot, _ = await self.proof(ack=True)
        publish = self.publication(snapshot, expected_bytes=123)
        self.source.pending_delivery[self.key] = (123, NOW)
        calls = []
        def after(state):
            calls.append(True)
            if len(calls) <= 2:
                raise EvidenceUnavailable(('evidence_background_yield',
                    'evidence_control_overloaded')[len(calls)-1])
            return publish(state)
        self.assertEqual(await self.source.flush_delivery(after), 1)
        self.assertEqual(len(self.work.futures), 3)
        self.assertEqual(len(set(self.work.futures)), 3)
        self.assertEqual(self.source.pending_delivery, {})
        self.assertEqual(await self.accounting(), [('pump', 'yellowstone', 123)])
        await self.assert_published(snapshot)

    async def test_cancellation_before_admission_creates_no_new_work_or_accounting(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def before(number, label, component):
            entered.set()
            await release.wait()
        self.work.before = before
        self.source.pending_delivery[self.key] = (123, NOW)
        task = self.start(self.source.flush_delivery())
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.work.futures, [])
        self.assertEqual(await self.accounting(), [])
        self.assertEqual(self.source.pending_delivery, {self.key: (123, NOW)})
        self.assertFalse(self.source.delivery_lock.locked())

    async def test_commit_yield_then_cancellation_before_retry_admission_settles_committed_delta(self):
        snapshot, _ = await self.proof(ack=True)
        entered, release = asyncio.Event(), asyncio.Event()
        async def before(number, label, component):
            if number == 2:
                entered.set()
                await release.wait()
        self.work.before = before
        def yield_publication(state):
            raise EvidenceUnavailable('evidence_background_yield')
        self.source.pending_delivery[self.key] = (123, NOW)
        task = self.start(self.source.flush_delivery(yield_publication))
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(len(self.work.calls), 2)
        self.assertEqual(len(self.work.futures), 1)
        self.assertTrue(self.work.futures[0].done())
        self.assertFalse(self.work.futures[0].cancelled())
        self.assertEqual(await self.accounting(), [('pump', 'yellowstone', 123)])
        self.assertEqual(self.source.pending_delivery, {})
        await self.assert_published(snapshot, False)

    async def test_latest_accepted_retry_survives_repeated_cancel_and_serializes_new_delta(self):
        snapshot, _ = await self.proof(ack=True)
        entered, release = self.held()
        publish = self.publication(snapshot, expected_bytes=123)
        calls = []
        def after(state):
            calls.append(True)
            if len(calls) == 1:
                raise EvidenceUnavailable('evidence_background_yield')
            entered.set()
            if not release.wait(3):
                raise RuntimeError('offline-publication-barrier-timeout')
            return publish(state)
        self.source.pending_delivery[self.key] = (123, NOW)
        task = self.start(self.source.flush_delivery(after))
        await self.wait_entered(entered)
        self.assertEqual(len(self.work.futures), 2)
        original, latest = self.work.futures
        self.assertTrue(original.done())
        self.assertFalse(latest.done())
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        self.assertFalse(task.done())
        self.assertTrue(self.source.delivery_lock.locked())
        await self.source.delivered('pump', 'yellowstone', 11, NOW)
        next_flush = self.start(self.source.flush_delivery())
        await asyncio.sleep(0)
        self.assertFalse(next_flush.done())
        self.assertEqual(self.source.pending_delivery[self.key][0], 134)
        self.assertEqual(len(self.work.futures), 2)
        release.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(next_flush, 2)
        self.assertTrue(latest.done())
        self.assertFalse(latest.cancelled())
        self.assertEqual(len(self.work.futures), 3)
        self.assertEqual(await self.accounting(), [('pump', 'yellowstone', 134)])
        self.assertEqual(self.source.pending_delivery, {})
        self.assertFalse(self.source.delivery_lock.locked())
        await self.assert_published(snapshot)

    async def test_cancel_after_accepted_accounting_rollback_retains_delta(self):
        entered, release = self.held()
        original = self.native['history'].delivery
        def broken(*args, **kwargs):
            original(*args, **kwargs)
            entered.set()
            if not release.wait(3):
                raise RuntimeError('offline-accounting-barrier-timeout')
            raise RuntimeError('offline-original-accounting-error')
        self.source.pending_delivery[self.key] = (123, NOW)
        with patch.object(self.native['history'], 'delivery', broken):
            task = self.start(self.source.flush_delivery())
            await self.wait_entered(entered)
            task.cancel()
            await asyncio.sleep(0)
            self.assertTrue(self.source.delivery_lock.locked())
            self.assertFalse(task.done())
            release.set()
            with self.assertRaisesRegex(RuntimeError, 'offline-original-accounting-error'):
                await task
        self.assertEqual(await self.accounting(), [])
        self.assertEqual(self.source.pending_delivery, {self.key: (123, NOW)})
        self.assertFalse(self.source.delivery_lock.locked())
        self.assertFalse(self.work.futures[0].cancelled())

    async def test_cancel_after_commit_keeps_original_terminal_publication_error(self):
        snapshot, _ = await self.proof(ack=True)
        entered, release = self.held()
        def broken(state):
            self.assertEqual(state.writer.db.execute('SELECT raw_bytes FROM provider_delivery').fetchone(), (123,))
            entered.set()
            if not release.wait(3):
                raise RuntimeError('offline-publication-barrier-timeout')
            raise RuntimeError('offline-original-publication-error')
        self.source.pending_delivery[self.key] = (123, NOW)
        task = self.start(self.source.flush_delivery(broken))
        await self.wait_entered(entered)
        task.cancel()
        await asyncio.sleep(0)
        self.assertTrue(self.source.delivery_lock.locked())
        self.assertFalse(task.done())
        release.set()
        with self.assertRaisesRegex(RuntimeError, 'offline-original-publication-error'):
            await task
        self.assertEqual(await self.accounting(), [('pump', 'yellowstone', 123)])
        self.assertEqual(self.source.pending_delivery, {})
        self.assertFalse(self.work.futures[0].cancelled())
        await self.assert_published(snapshot, False)


    async def enable_publication_handoff(self):
        self.work.candidate_delivery_publication_handoff = True
        await self.enable_capture_actor()

    async def handoff_capture(self):
        """Actual read actor and physical consumer; no synthesized ACK result."""
        from meme_machine.solana_history_delivery import CaptureActor, capture_context
        from meme_machine.solana_history_notifications import delivery_hint
        context, hint = await self.query(lambda state: (capture_context(self.native['history'].lifecycle),
            delivery_hint(self.native['history'])))
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            snapshot = await asyncio.wrap_future(pool.submit(CaptureActor(context).capture, hint))
            self.assertIsNotNone(snapshot)
            result = await asyncio.wrap_future(pool.submit(deliver, snapshot))
            return snapshot, result
        finally:await asyncio.to_thread(pool.shutdown, wait=True)

    async def wait_handoff(self, predicate):
        async def poll():
            while not await predicate():
                await asyncio.sleep(.005)
        await asyncio.wait_for(poll(), 3)

    async def restart_handoff_owner(self):
        """Reopen durable private stores with no mailbox or scan hints retained."""
        self.source.stop.set()
        await asyncio.to_thread(self.owner.close)
        def factory():
            state, history = state_at(self.path)
            history.lifecycle.delivery_separated = True
            self.native.update(state=state, history=history)
            state.close = state.writer.close
            return state
        self.owner = PriorityOwner(factory)
        await asyncio.shield(asyncio.wrap_future(self.owner.ready))
        self.source = SelectiveSource(SimpleNamespace(credential='offline', identity='a'*64), None)
        self.source.stop = asyncio.Event(); self.source.batched = True
        self.work = OwnedWork(self.owner)
        await self.enable_publication_handoff()

    async def test_publication_handoff_allows_next_physical_full_ack_and_urgent_owner_while_publisher_waits(self):
        from meme_machine import solana_history_delivery as delivery
        proof, _ = await self.proof()
        await self.scouts(128); await self.enable_publication_handoff()
        self.source.pending_delivery[self.key] = (123, NOW)
        capture_entered, capture_release = self.held()
        publication_entered, publication_release = asyncio.Event(), asyncio.Event()
        self.releases.append(publication_release)
        original = delivery.CaptureActor.capture; captures = []
        def observed(actor, *args, **kwargs):
            if len(captures) == 1:
                capture_entered.set()
                if not capture_release.wait(3):raise RuntimeError('handoff_next_capture_release')
            snapshot = original(actor, *args, **kwargs)
            captures.append(None if snapshot is None else len(snapshot['rows']))
            return snapshot
        async def before(index, label, component):
            if label == 'source_commit' and component == 'history_publication':
                publication_entered.set(); await publication_release.wait()
        self.work.before = before
        pool = ThreadPoolExecutor(max_workers=1); self.source.delivery_executor = pool
        try:
            with patch.object(delivery.CaptureActor, 'capture', observed):
                consumer = self.start(self.source.candidate_history_delivery())
                await self.wait_entered(capture_entered)
                self.assertEqual(self.source.proof_publication_handoff.queue.qsize(), 1)
                publisher = self.start(self.source.publish_history())
                await asyncio.wait_for(publication_entered.wait(), 2)
                self.assertEqual(self.source.proof_publication_handoff.active, tuple(proof['publication_ids']))
                capture_release.set()
                async def consumed():return not await self.pending_scouts()
                await self.wait_handoff(consumed)
                self.assertEqual(captures[:2], [64, 64])
                self.assertGreaterEqual(self.work.counts['owner.stage.candidate_delivery_ack.calls'], 2)
                # Publication is still outside owner admission. The next real
                # FULL delivery and fresh ACK have completed, and protection
                # can use the original reserved priority without waiting.
                self.assertEqual(await self.source.work(lambda state: 'urgent_progress', 0), 'urgent_progress')
                self.assertFalse(publication_release.is_set())
                await self.assert_published(proof, False)
                publication_release.set()
                async def published():
                    return await self.query(lambda state: state.writer.db.execute(
                        'SELECT COUNT(*) FROM candidate_pending_proofs').fetchone()[0] == 0)
                await self.wait_handoff(published)
                self.assertEqual(await self.accounting(), [('pump', 'yellowstone', 123)])
                self.assertEqual(self.source.pending_delivery, {})
                await self.assert_published(proof)
                self.source.stop.set()
                await asyncio.wait_for(asyncio.gather(consumer, publisher), 3)
        finally:
            capture_release.set(); publication_release.set(); self.source.stop.set()
            for task in self.tasks:
                if not task.done():task.cancel()
            await asyncio.gather(*self.tasks, return_exceptions=True)
            await asyncio.to_thread(pool.shutdown, wait=True)

    async def test_publication_handoff_bounds_deduplicates_and_stop_or_cancel_releases_full_mailbox_waiter(self):
        from meme_machine.solana_history_notifications import ProofPublicationHandoff
        handoff = ProofPublicationHandoff(); stop = asyncio.Event()
        first = tuple(digest(['first', n]) for n in range(64))
        second = tuple(digest(['second', n]) for n in range(64))
        third = tuple(digest(['third', n]) for n in range(64))
        await handoff.offer(first, stop)
        self.assertEqual(handoff.take(), first)
        await handoff.offer(second, stop)
        self.assertEqual(len(handoff.outstanding), 128)
        await handoff.offer(first, stop); await handoff.offer(second, stop)
        self.assertEqual(handoff.queue.qsize(), 1)
        waiting = self.start(handoff.offer(third, stop))
        await asyncio.sleep(0); self.assertFalse(waiting.done())
        waiting.cancel()
        with self.assertRaises(asyncio.CancelledError):await waiting
        self.assertEqual(handoff.outstanding, set(first+second))
        waiting = self.start(handoff.offer(third, stop))
        await asyncio.sleep(0); stop.set(); await asyncio.wait_for(waiting, 1)
        self.assertEqual(handoff.queue.qsize(), 1)
        self.assertEqual(handoff.outstanding, set(first+second))
        handoff.complete(first)
        self.assertEqual(handoff.take(), second)
        handoff.complete(second)
        self.assertFalse(handoff.ready()); self.assertEqual(handoff.outstanding, set())
        stop.clear()
        with self.assertRaisesRegex(ValueError, 'candidate_publication_handoff_bound'):
            await handoff.offer(tuple(digest(['overflow', n]) for n in range(65)), stop)

    async def test_publication_handoff_busy_exact_keeps_hint_and_runs_fair_scan_before_target_retry(self):
        from meme_machine import solana_history_delivery as delivery
        proof, _ = await self.proof(ack=True); await self.enable_publication_handoff()
        identities = tuple(proof['publication_ids'])
        await self.source.proof_publication_handoff.offer(identities, self.source.stop)
        original_open = delivery.readonly_history
        life = self.native['history'].lifecycle; original_publish = life.publish
        calls = []; busy = []; fair_after_retry = asyncio.Event()
        def publication(*args, **kwargs):
            targeted = kwargs.get('proof_ids')
            calls.append(targeted)
            if len(calls) == 2:self.assertEqual(self.source.proof_publication_handoff.active, identities)
            result = original_publish(*args, **kwargs)
            if targeted is not None and len(calls) == 1:
                self.assertIsNotNone(life._consumer_retry_at)
                busy.append(life._consumer_retry_at)
            if len(calls) >= 4 and targeted is None:
                loop.call_soon_threadsafe(fair_after_retry.set)
            return result
        def opened(path):
            if not calls or len(calls) != 1:return original_open(path)
            error = sqlite3.OperationalError('offline_busy_receipt_read')
            error.sqlite_errorcode = sqlite3.SQLITE_BUSY
            raise error
        loop = asyncio.get_running_loop()
        with patch.object(delivery, 'readonly_history', opened), patch.object(life, 'publish', publication):
            publisher = self.start(self.source.publish_history())
            await asyncio.wait_for(fair_after_retry.wait(), 3)
            self.source.stop.set(); await asyncio.wait_for(publisher, 3)
        self.assertEqual(calls[:4], [identities, None, identities, None])
        self.assertEqual(len(busy), 1)
        self.assertIsNone(self.source.proof_publication_handoff.active)
        self.assertEqual(self.source.proof_publication_handoff.outstanding, set())
        await self.assert_published(proof)

    async def test_publication_handoff_corrupt_receipt_fails_at_fresh_verification_then_durable_restart_replays(self):
        proof, _ = await self.proof(ack=True); await self.enable_publication_handoff()
        identities = tuple(proof['publication_ids']); life = self.native['history'].lifecycle
        with closing(sqlite3.connect(life.path)) as db:
            original = db.execute('SELECT body,hash FROM source_receipts WHERE id=?', ('coverage:'+identities[0],)).fetchone()
            db.execute('UPDATE source_receipts SET hash=? WHERE id=?', ('0'*64, 'coverage:'+identities[0]))
        await self.source.proof_publication_handoff.offer(identities, self.source.stop)
        publisher = self.start(self.source.publish_history())
        with self.assertRaisesRegex(EvidenceUnavailable, 'candidate_delivery_receipt_corrupt'):await publisher
        self.assertEqual(self.source.proof_publication_handoff.active, identities)
        await self.assert_published(proof, False)
        with closing(sqlite3.connect(life.path)) as db:
            db.execute('UPDATE source_receipts SET body=?,hash=? WHERE id=?', (*original, 'coverage:'+identities[0]))
        await self.restart_handoff_owner()
        self.assertFalse(self.source.proof_publication_handoff.ready())
        publisher = self.start(self.source.publish_history())
        async def published():
            return await self.query(lambda state: state.writer.db.execute(
                'SELECT COUNT(*) FROM candidate_pending_proofs').fetchone()[0] == 0)
        await self.wait_handoff(published)
        self.source.stop.set(); await asyncio.wait_for(publisher, 3)
        await self.assert_published(proof)

    async def test_publication_handoff_canceled_after_fresh_ack_keeps_full_receipt_and_pending_proof_for_restart(self):
        proof, _ = await self.proof(); await self.scouts(1); await self.enable_publication_handoff()
        snapshot, result = await self.handoff_capture()
        handoff = self.source.proof_publication_handoff
        # Fill both hint slots with unrelated scheduling-only hashes. No
        # receipt/coverage authority is attached to either mailbox entry.
        await handoff.offer((digest('active_hint'),), self.source.stop); handoff.take()
        await handoff.offer((digest('queued_hint'),), self.source.stop)
        completion = self.start(self.source._complete_history_delivery(snapshot, result))
        async def acked():return not await self.pending_scouts()
        await self.wait_handoff(acked)
        self.assertFalse(completion.done())
        completion.cancel()
        with self.assertRaises(asyncio.CancelledError):await completion
        self.assertEqual(handoff.outstanding, {digest('active_hint'), digest('queued_hint')})
        await self.assert_published(proof, False)
        with closing(sqlite3.connect(self.native['history'].lifecycle.path)) as db:
            self.assertIsNotNone(db.execute('SELECT hash FROM source_receipts WHERE id=?',
                ('coverage:'+proof['publication_ids'][0],)).fetchone())
        await self.restart_handoff_owner()
        publisher = self.start(self.source.publish_history())
        async def published():
            return await self.query(lambda state: state.writer.db.execute(
                'SELECT COUNT(*) FROM candidate_pending_proofs').fetchone()[0] == 0)
        await self.wait_handoff(published)
        self.source.stop.set(); await asyncio.wait_for(publisher, 3)
        await self.assert_published(proof)

    async def test_publication_handoff_rejected_fresh_generation_ack_never_offers_proof_hint(self):
        proof, _ = await self.proof(); await self.enable_publication_handoff()
        snapshot, result = await self.handoff_capture()
        await self.query(lambda state: self.native['history'].startup.begin())
        self.assertFalse(await self.source._complete_history_delivery(snapshot, result))
        self.assertFalse(self.source.proof_publication_handoff.ready())
        self.assertEqual(self.source.proof_publication_handoff.outstanding, set())
        self.assertEqual([label for _, label, _ in self.work.calls], ['candidate_delivery_ack'])
        await self.assert_published(proof, False)


if __name__ == '__main__':
    unittest.main()
