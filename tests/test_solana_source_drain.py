"""Actual source queue/session lifecycle with disposable evidence and no network."""
import asyncio
from contextlib import closing
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from meme_machine.solana_candidate_join import scope_labels
from meme_machine.solana_evidence_plane import EvidenceUnavailable
from meme_machine.solana_rolling_history import program_scope
from meme_machine.solana_selective_history import PROGRAMS
from meme_machine.solana_selective_source import SelectiveSource,CandidateCommitQueue
from meme_machine.solana_source_drain import AcceptedQueue,next_owned,join_owned,settle_owned,receive_until_closed,INTAKE_CLOSED
from meme_machine.solana_source_drain import CONTROL_RECOVERY_KEY,control_recovery,preserve_control_recovery,complete_control_recovery
from meme_machine.yellowstone import geyser_pb2 as pb
from tests.test_scout_commit_batches import update
from tests.test_solana_closure import state_at,NOW
from tests.test_solana_selective_evidence import FIXTURE


class SourceDrainTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.state,self.history=state_at(Path(self.tmp.name)/'canonical.sqlite')
        self.addCleanup(self.state.writer.close)
        self.source=SelectiveSource(SimpleNamespace(credential='offline',identity='a'*64,stream_url='offline'),None)
        self.source.stop=asyncio.Event();self.entered=asyncio.Event();self.release=asyncio.Event()

    async def work(self,fn,priority=2,**options):return fn(self.state)

    async def quiet(self,*args):await self.source.stop.wait()

    async def test_idle_socket_close_and_simultaneous_delivery_do_not_cancel_owned_handler(self):
        stop=asyncio.Event();stop.set()
        async def ready():return b'accepted-before-close'
        self.assertEqual(await receive_until_closed(ready,stop),b'accepted-before-close')
        canceled=[]
        async def idle():
            try:await asyncio.Event().wait()
            finally:canceled.append(True)
        self.assertIs(await receive_until_closed(idle,stop),INTAKE_CLOSED)
        self.assertEqual(canceled,[True])

    async def test_simultaneous_queue_close_keeps_the_last_item(self):
        counts=[];queue=AcceptedQueue(1,lambda a,c:counts.append((a,c)));done=asyncio.Event()
        await queue.put('last');done.set()
        self.assertEqual(await next_owned(queue,done),'last');queue.committed(['last'])
        self.assertIsNone(await next_owned(queue,done));await queue.join()
        self.assertEqual(counts,[(1,0),(0,1)])

    async def test_failed_consumer_does_not_wait_forever_or_ack(self):
        queue=CandidateCommitQueue()
        queue.queue.put_nowait('still-pending')
        async def failed():raise EvidenceUnavailable('original_commit_failure')
        task=asyncio.create_task(failed())
        with self.assertRaisesRegex(EvidenceUnavailable,'original_commit_failure'):
            await asyncio.wait_for(join_owned(queue,task),.5)
        self.assertEqual(queue.queue.qsize(),1)

    async def test_late_commit_failure_cancels_capacity_blocked_producer_with_exact_pending_count(self):
        queue=AcceptedQueue(1,lambda a,c:self.source.frame_census('scout',a,c))
        entered=asyncio.Event();full=asyncio.Event()
        async def produce():
            await queue.put('first');await queue.put('second');full.set();await queue.put('third')
        async def consume():
            await queue.get();entered.set();await self.release.wait()
            raise EvidenceUnavailable('late_commit_failure')
        producer=asyncio.create_task(produce());consumer=asyncio.create_task(consume())
        await entered.wait();await full.wait()
        settle=asyncio.create_task(settle_owned([producer],[consumer]))
        await asyncio.sleep(0);self.assertFalse(settle.done());self.release.set()
        results=await asyncio.wait_for(settle,.5)
        self.assertIsInstance(results[0],asyncio.CancelledError)
        with self.assertRaisesRegex(EvidenceUnavailable,'late_commit_failure'):consumer.result()
        self.assertEqual(self.source.drain_snapshot()['queues']['scout'],dict(accepted=2,committed=0,pending=2))

    async def actual_run(self,*,fail=False,startup='quiet'):
        source=self.source
        capacity_blocked=asyncio.Event()
        class Channel:
            async def __aenter__(self):return None
            async def __aexit__(self,*args):pass
        async def scouts(channel,tip,handler):
            # The last put initially waits behind the bounded 64-item queue.
            for number in range(1,131 if fail else 66):
                if number==129:capacity_blocked.set()
                await handler(update(1+(number-1)%65),1,NOW)
            source.stop.set()
        async def work(fn,priority=2,**options):
            if options.get('component')=='scout':
                self.entered.set();await self.release.wait()
                if fail:raise EvidenceUnavailable('original_scout_commit_failure')
            return fn(self.state)
        async def tip(*args):return 100
        source.measured_rpc=tip
        source.control_stream=self.quiet;source.scout_stream=scouts
        for name in ('acquire_pool','live_manager','rolling_programs','cold_maintenance','publish_history','source_reporting'):
            setattr(source,name,self.quiet)
        if startup!='quiet':
            async def interrupted_startup(*args):
                await source.stop.wait()
                if startup=='cancel':raise asyncio.CancelledError()
                raise EvidenceUnavailable('original_startup_dependency_failure')
            source.live_manager=interrupted_startup
        with patch('meme_machine.solana_selective_source.grpc.aio.secure_channel',return_value=Channel()), \
                patch('meme_machine.solana_selective_source.enabled',return_value=False), \
                patch('meme_machine.solana_selective_source.operational',return_value=True), \
                patch('meme_machine.solana_history_work.enabled',return_value=False):
            task=asyncio.create_task(source.run(work,source.stop))
            await asyncio.wait_for(self.entered.wait(),1)
            if fail:
                await asyncio.wait_for(capacity_blocked.wait(),1);source.stop.set()
            # This is a real stop with a writer-held batch and one more queued
            # frame; financial flatness is irrelevant to this ownership proof.
            await asyncio.wait_for(source.stop.wait(),1)
            await asyncio.sleep(0);self.assertFalse(task.done());self.release.set()
            if fail:
                with self.assertRaisesRegex(EvidenceUnavailable,'original_scout_commit_failure'):await asyncio.wait_for(task,2)
            elif startup=='fatal':
                with self.assertRaisesRegex(EvidenceUnavailable,'original_startup_dependency_failure'):await asyncio.wait_for(task,2)
            else:await asyncio.wait_for(task,2)

    async def test_actual_driver_drains_capacity_blocked_scout_producer_after_stop(self):
        await self.actual_run()
        body=self.source.drain_snapshot()
        self.assertEqual(body['state'],'DRAINED');self.assertTrue(body['terminal'])
        self.assertEqual(body['queues']['scout'],dict(accepted=65,committed=65,pending=0))
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM market_observations').fetchone()[0],65)
        terminal=json.loads(self.history.db.execute("SELECT value FROM service_health WHERE key='source_drain'").fetchone()[0])
        self.assertEqual((terminal['source_pid'],terminal['run_identity']),(body['source_pid'],body['run_identity']))
        self.assertGreaterEqual(terminal['terminal_at_monotonic'],terminal['started_at_monotonic'])
        self.assertNotEqual(terminal['run_identity'],SelectiveSource(SimpleNamespace(credential='offline'),None).drain_snapshot()['run_identity'])
        self.assertGreater(terminal['pending_history'],0)
        self.assertEqual(terminal['pending_history'],self.history.db.execute(
            'SELECT COUNT(*) FROM candidate_history_outbox WHERE consumed IS NULL').fetchone()[0])
        self.assertEqual(terminal['pending_proofs'],0)

    async def test_actual_driver_preserves_original_commit_failure_and_unfinished_census(self):
        await self.actual_run(fail=True)
        body=self.source.drain_snapshot()
        self.assertEqual(body['state'],'RECOVERY_REQUIRED')
        self.assertEqual(body['queues']['scout'],dict(accepted=128,committed=0,pending=128))
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM market_observations').fetchone()[0],0)

    async def test_intentional_stop_canceling_startup_wait_does_not_falsely_fail_source_drain(self):
        await self.actual_run(startup='cancel')
        self.assertEqual(self.source.drain_snapshot()['state'],'DRAINED')
        self.assertEqual(self.source.drain_snapshot()['queues']['scout'],dict(accepted=65,committed=65,pending=0))

    async def test_real_startup_error_racing_intentional_stop_is_not_suppressed(self):
        await self.actual_run(startup='fatal')
        self.assertEqual(self.source.drain_snapshot()['queues']['scout']['pending'],0)

    async def actual_live(self,*,transport_failure=False,cancel=False,commit_failure=False):
        import based58
        source=self.source;tx=copy.deepcopy(FIXTURE['pump'][0]);slot=tx['slot'];index=tx['transactionIndex']
        addresses={PROGRAMS[f]:program_scope(f) for f in ('pump','pumpswap')}
        statuses_ready=asyncio.Event();native_accepted=asyncio.Event()
        async def work(fn,priority=2,**options):
            if options.get('component')=='candidate':
                self.entered.set();await self.release.wait()
                if commit_failure:raise EvidenceUnavailable('original_candidate_commit_failure')
            return fn(self.state)
        async def tip(*args):return slot-1
        source.work=work;source.measured_rpc=tip
        class Socket:
            def __init__(socket):socket.acks=asyncio.Queue();socket.sent=False;socket.frontiers=iter((11,12))
            async def send(socket,raw):
                request=json.loads(raw);await socket.acks.put(json.dumps(dict(id=request['id'],result=request['id']+10)))
            async def recv(socket):
                if not socket.acks.empty():return await socket.acks.get()
                subscription=next(socket.frontiers,None)
                if subscription is not None:
                    return json.dumps(dict(params=dict(subscription=subscription,result=dict(context=dict(slot=slot-1),
                        value=dict(err={'InstructionError':[0,0]},signature='failed',logs=[])))))
                await statuses_ready.wait()
                if socket.sent:await asyncio.Event().wait()
                socket.sent=True
                return json.dumps(dict(params=dict(subscription=11,result=dict(context=dict(slot=slot),
                    value=dict(err=None,signature=tx['transaction']['signatures'][0],logs=tx['meta']['logMessages'])))))
        class Connection:
            async def __aenter__(self):return Socket()
            async def __aexit__(self,*args):pass
        async def stream(channel,request,handler,family,local_stop):
            u=pb.SubscribeUpdate(filters=[scope_labels(addresses)[program_scope('pump')]])
            s=u.transaction_status;s.slot=slot;s.index=index;s.signature=based58.b58decode(tx['transaction']['signatures'][0].encode())
            await handler(u,u.ByteSize(),NOW)
            u=pb.SubscribeUpdate(filters=['b']);m=u.block_meta;m.slot=slot;m.parent_slot=slot-1
            m.blockhash=str(slot);m.parent_blockhash=str(slot-1);m.block_time.timestamp=tx['blockTime']
            m.executed_transaction_count=index+1;await handler(u,u.ByteSize(),NOW)
            u=pb.SubscribeUpdate(filters=['f']);u.slot.slot=slot;u.slot.parent=slot-1;u.slot.status=pb.SLOT_FINALIZED
            await handler(u,u.ByteSize(),NOW);statuses_ready.set()
            await self.entered.wait();native_accepted.set()
            if transport_failure:raise EvidenceUnavailable('candidate_native_internal')
            await local_stop.wait()
        source.stream=stream
        desired=[dict(family=f,address=PROGRAMS[f],scope=program_scope(f),priority=6,deadline=NOW+150,
            lower_slot=0,rolling=True) for f in ('pump','pumpswap')]
        local_stop=asyncio.Event()
        with patch('meme_machine.solana_selective_source.connect',lambda *args,**kw:Connection()):
            task=asyncio.create_task(source.live(None,desired,local_stop))
            await asyncio.wait_for(native_accepted.wait(),1)
            if cancel:task.cancel()
            else:local_stop.set()
            await asyncio.sleep(0);self.assertFalse(task.done());self.release.set()
            if transport_failure:
                with self.assertRaisesRegex(EvidenceUnavailable,'candidate_native_internal'):await asyncio.wait_for(task,2)
            elif commit_failure:
                with self.assertRaisesRegex(EvidenceUnavailable,'original_candidate_commit_failure'):await asyncio.wait_for(task,2)
            elif cancel:
                with self.assertRaises(asyncio.CancelledError):await asyncio.wait_for(task,2)
            else:await asyncio.wait_for(task,2)
        return slot

    async def test_actual_live_filter_replacement_finishes_accepted_commit_and_preserves_gap(self):
        slot=await self.actual_live()
        self.assertGreater(self.history.db.execute('SELECT COUNT(*) FROM rolling_economic_events').fetchone()[0],0)
        self.assertEqual(self.source.drain_snapshot()['queues']['rolling'],dict(accepted=1,committed=1,pending=0))
        # One retained block still lacks its linked child proof: its economic
        # commit is real, but no candidate checkpoint/coverage was fabricated.
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM candidate_checkpoints').fetchone()[0],0)
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM candidate_gaps WHERE lo=? AND hi IS NULL',(slot,)).fetchone()[0],2)

    async def test_actual_live_transport_failure_drains_before_reconnect_and_preserves_original(self):
        await self.actual_live(transport_failure=True)
        self.assertEqual(self.source.drain_snapshot()['queues']['rolling']['pending'],0)
        self.assertEqual(self.source.source_drain['closed_sessions'],1)
        self.assertEqual(self.source.source_drain['unpreserved_sessions'],0)

    async def test_actual_live_cancellation_finishes_owner_before_returning_canceled(self):
        await self.actual_live(cancel=True)
        self.assertEqual(self.source.drain_snapshot()['queues']['rolling']['pending'],0)
        self.assertGreater(self.history.db.execute('SELECT COUNT(*) FROM candidate_history_outbox').fetchone()[0],0)

    async def test_actual_live_commit_failure_does_not_ack_or_clear_accepted_count(self):
        await self.actual_live(commit_failure=True)
        self.assertEqual(self.source.drain_snapshot()['queues']['rolling'],dict(accepted=1,committed=0,pending=1))
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM rolling_economic_events').fetchone()[0],0)
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM candidate_gaps WHERE hi IS NULL').fetchone()[0],2)

    async def test_startup_abort_preserves_accepted_early_log_below_scheduling_placeholder(self):
        source=self.source;source.work=self.work;source.batched=True
        tx=FIXTURE['pump'][0];slot=tx['slot'];log_settled=asyncio.Event()
        async def tip(*args):return slot+10
        async def forbidden(*args):self.fail('no native stream before both actual log frontiers')
        source.measured_rpc=tip;source.stream=forbidden
        class Socket:
            def __init__(self):self.acks=asyncio.Queue();self.sent=False
            async def send(self,raw):
                request=json.loads(raw);await self.acks.put(json.dumps(dict(id=request['id'],result=request['id']+10)))
            async def recv(self):
                if not self.acks.empty():return await self.acks.get()
                if self.sent:
                    # Another read proves the preceding handler finished.
                    log_settled.set();await asyncio.Event().wait()
                self.sent=True
                return json.dumps(dict(params=dict(subscription=11,result=dict(context=dict(slot=slot),
                    value=dict(err=None,signature=tx['transaction']['signatures'][0],logs=tx['meta']['logMessages'])))))
        class Connection:
            async def __aenter__(self):return Socket()
            async def __aexit__(self,*args):pass
        desired=[dict(family=f,address=PROGRAMS[f],scope=program_scope(f),priority=6,deadline=NOW+150,
            lower_slot=0,rolling=True) for f in ('pump','pumpswap')]
        with patch('meme_machine.solana_selective_source.connect',lambda *args,**kw:Connection()):
            task=asyncio.create_task(source.live(None,desired,asyncio.Event()))
            await asyncio.wait_for(log_settled.wait(),1);task.cancel()
            with self.assertRaises(asyncio.CancelledError):await asyncio.wait_for(task,2)
        self.assertEqual(self.history.db.execute('SELECT scope,lo,hi FROM candidate_gaps ORDER BY scope').fetchall(),
            [(program_scope(f),slot,None) for f in ('pump','pumpswap')])
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM candidate_coverage').fetchone()[0],0)
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM candidate_checkpoints').fetchone()[0],0)
        self.assertEqual(self.source.source_drain['preserved_partial_sessions'],1)

    async def test_restart_uses_earliest_partial_control_obligation_even_below_newest_coverage(self):
        from meme_machine.solana_selective_runtime import CONTROL
        from tests.test_solana_prewarm_startup import proof
        source=self.source;source.work=self.work
        async def partial(channel,request,handler,*args):
            u=pb.SubscribeUpdate(filters=['b']);m=u.block_meta;m.slot=2000;m.parent_slot=1999
            m.blockhash='h2000';m.parent_blockhash='h1999';m.block_time.timestamp=int(NOW)
            await handler(u,u.ByteSize(),NOW);source.stop.set()
        source.stream=partial
        await source.control_stream(None,2001,AcceptedQueue(64,lambda *args:None))
        raw=self.history.db.execute('SELECT value FROM service_health WHERE key=?',(CONTROL_RECOVERY_KEY,)).fetchone()[0]
        self.assertEqual((control_recovery(raw)['lower_slot'],control_recovery(raw)['upper_slot']),(2000,2000))
        # An independently complete later interval cannot erase the old hole.
        self.state.writer.ingest([],proof=proof(CONTROL,2500,2501))
        self.state.writer.close();self.state,self.history=state_at(self.state.writer.path)
        self.addCleanup(self.state.writer.close)
        recovered=SelectiveSource(SimpleNamespace(credential='offline'),None);recovered.stop=asyncio.Event();recovered.work=self.work
        floors=[]
        async def resumed(channel,request,*args):floors.append(request.from_slot);recovered.stop.set()
        recovered.stream=resumed
        await recovered.control_stream(None,3000,AcceptedQueue(64,lambda *args:None))
        self.assertEqual(floors,[2000-256])
        self.assertEqual(self.history.db.execute('SELECT lo,hi FROM coverage WHERE scope=? ORDER BY id',(CONTROL,)).fetchall(),[(2500,2501)])
        self.assertEqual(recovered.source_drain['control_pending_replay']['lower_slot'],2000)

    async def test_control_obligation_requires_new_complete_coverage_not_newest_head_or_old_proof(self):
        from meme_machine.solana_selective_runtime import CONTROL
        from tests.test_solana_prewarm_startup import proof
        self.state.writer.ingest([],proof=proof(CONTROL,100,101))
        expected=preserve_control_recovery(self.state,100,101)
        self.assertEqual(complete_control_recovery(self.state,CONTROL),expected)
        self.state.writer.ingest([],proof=proof(CONTROL,500,600))
        self.assertEqual(complete_control_recovery(self.state,CONTROL),expected)
        self.state.writer.ingest([],proof=proof(CONTROL,100,100))
        self.assertEqual(complete_control_recovery(self.state,CONTROL),dict(expected,lower_slot=101))
        self.state.writer.ingest([],proof=proof(CONTROL,101,101))
        before=self.history.db.execute('SELECT * FROM cursors').fetchall()
        self.assertIsNone(complete_control_recovery(self.state,CONTROL))
        self.assertEqual(self.history.db.execute('SELECT * FROM cursors').fetchall(),before)

    async def test_required_control_replay_outside_configured_window_fails_closed_before_dispatch(self):
        expected=preserve_control_recovery(self.state,100,102)
        self.source.work=self.work
        async def forbidden(*args):self.fail('unavailable required cursor must not become a prospective tail')
        self.source.stream=forbidden
        with self.assertRaisesRegex(EvidenceUnavailable,'control_required_replay_outside_configured_window'):
            await self.source.control_stream(None,10000,AcceptedQueue(64,lambda *args:None))
        raw=self.history.db.execute('SELECT value FROM service_health WHERE key=?',(CONTROL_RECOVERY_KEY,)).fetchone()[0]
        self.assertEqual(control_recovery(raw),expected)

    async def test_control_coverage_pages_preserve_prefix_rollback_and_do_not_skip_missing_middle(self):
        from meme_machine.solana_selective_runtime import CONTROL
        from tests.test_solana_prewarm_startup import proof
        expected=preserve_control_recovery(self.state,100,612)
        with self.state.writer.transaction():
            for slot in range(100,613):self.state.writer._coverage(proof(CONTROL,slot,slot))
        class Rollback(Exception):pass
        with self.assertRaises(Rollback),self.state.writer.transaction():
            partial=complete_control_recovery(self.state,CONTROL)
            self.assertEqual(partial['lower_slot'],612)
            raise Rollback()
        raw=self.history.db.execute('SELECT value FROM service_health WHERE key=?',(CONTROL_RECOVERY_KEY,)).fetchone()[0]
        self.assertEqual(control_recovery(raw),expected)
        self.assertEqual(complete_control_recovery(self.state,CONTROL)['lower_slot'],612)
        self.assertIsNone(complete_control_recovery(self.state,CONTROL))
        # A separately fenced obligation cannot reuse those old proof rows.
        expected=preserve_control_recovery(self.state,100,612)
        with self.state.writer.transaction():
            for slot in range(100,613):
                if slot!=350:
                    p=proof(CONTROL,slot,slot)
                    from dataclasses import replace
                    p=replace(p,witness=dict(p.witness,lineage_hash='second-'+str(slot)))
                    self.state.writer._coverage(p)
        self.assertEqual(complete_control_recovery(self.state,CONTROL)['lower_slot'],350)
        self.assertEqual(complete_control_recovery(self.state,CONTROL)['lower_slot'],350)
        p=proof(CONTROL,350,350)
        from dataclasses import replace
        self.state.writer._coverage(replace(p,witness=dict(p.witness,lineage_hash='second-350')))
        self.assertIsNone(complete_control_recovery(self.state,CONTROL))
