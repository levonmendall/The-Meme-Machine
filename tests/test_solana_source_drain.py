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
from meme_machine.solana_source_drain import finish_owned
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

    async def actual_run(self,*,fail=False,startup='quiet',repeated_cancel=False):
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
            if startup=='unexpected_cancel':
                # Keep this producer alive so its ordinary return cannot race
                # the deliberately interrupted startup child under test.
                await source.stop.wait()
            else:source.stop.set()
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
                if startup=='unexpected_cancel':
                    await self.entered.wait();raise asyncio.CancelledError()
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
            if repeated_cancel:
                for _ in range(100):
                    if getattr(source,'global_teardown',None) is not None:break
                    await asyncio.sleep(.005)
                self.assertIsNotNone(source.global_teardown)
                task.cancel();await asyncio.sleep(0);task.cancel()
            await asyncio.sleep(0);self.assertFalse(task.done());self.release.set()
            if fail:
                with self.assertRaisesRegex(EvidenceUnavailable,'original_scout_commit_failure'):await asyncio.wait_for(task,2)
            elif startup=='fatal':
                with self.assertRaisesRegex(EvidenceUnavailable,'original_startup_dependency_failure'):await asyncio.wait_for(task,2)
            elif startup=='unexpected_cancel':
                with self.assertRaises(asyncio.CancelledError):await asyncio.wait_for(task,2)
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

    async def test_repeated_source_cancel_joins_single_global_teardown_and_commits_accepted_frames(self):
        await self.actual_run(repeated_cancel=True)
        self.assertEqual(self.source.drain_snapshot()['state'],'DRAINED')
        self.assertEqual(self.source.drain_snapshot()['queues']['scout'],dict(accepted=65,committed=65,pending=0))

    async def test_first_startup_error_survives_repeated_source_cancellation_during_drain(self):
        await self.actual_run(startup='fatal',repeated_cancel=True)
        self.assertEqual(self.source.drain_snapshot()['queues']['scout']['pending'],0)

    async def test_unexpected_child_cancellation_is_not_successful_global_drain(self):
        await self.actual_run(startup='unexpected_cancel')
        body=self.source.drain_snapshot()
        self.assertTrue(body['unexpected_cancellation'])
        self.assertEqual(body['state'],'RECOVERY_REQUIRED')
        self.assertEqual(body['queues']['scout'],dict(accepted=65,committed=65,pending=0))

    async def actual_live(self,*,transport_failure=False,cancel=False,commit_failure=False,repeated_cancel=False,cutoff=False,
            truncated=False,repair_failure=False,cancel_repair=False,unsupported=False,complete_duplicate=False,repair_members=1,repair_admitted_members=None,census_bound=False):
        import based58
        source=self.source;tx=copy.deepcopy(FIXTURE['pump'][0]);slot=tx['slot'];index=tx['transactionIndex']
        txs=[]
        for number in range(repair_members):
            item=copy.deepcopy(tx);item['transactionIndex']=index+number
            if repair_members>1:item['transaction']['signatures']=[based58.b58encode(bytes([number+1])*64).decode()]
            txs.append(item)
        tx=txs[0];batch_sizes=[]
        admitted_members=repair_members if repair_admitted_members is None else repair_admitted_members
        assert 1<=admitted_members<=repair_members
        addresses={PROGRAMS[f]:program_scope(f) for f in ('pump','pumpswap')}
        statuses_ready=asyncio.Event();native_accepted=asyncio.Event()
        socket_idle=asyncio.Event();repair_entered=asyncio.Event();repair_release=asyncio.Event()
        partial=tx['meta']['logMessages'][:4]+['Log truncated']
        async def work(fn,priority=2,**options):
            if options.get('component')=='candidate':
                self.entered.set();await self.release.wait()
                if commit_failure:raise EvidenceUnavailable('original_candidate_commit_failure')
            return fn(self.state)
        async def tip(method,*args):
            if method=='getTransaction':
                # WS must keep reading while the selective HTTP repair is in
                # flight, including the same transaction's duplicate packet.
                if repair_members==1:repair_entered.set()
                await socket_idle.wait()
                if cancel_repair and repair_members==1:await repair_release.wait()
                fetched=copy.deepcopy(next(item for item in txs if item['transaction']['signatures'][0]==args[0][0]));fetched.pop('transactionIndex',None)
                if repair_failure:fetched['meta']['logMessages']=partial
                return fetched
            return slot-1
        source.work=work;source.measured_rpc=tip
        real_batch=source.measured_log_batch
        async def batch(signatures,priority=2):
            if len(signatures)==1:return await real_batch(signatures,priority)
            batch_sizes.append(len(signatures));repair_entered.set();await socket_idle.wait()
            if cancel_repair:await repair_release.wait()
            return [dict(copy.deepcopy(next(item for item in txs if item['transaction']['signatures'][0]==sig)))
                for sig in signatures]
        source.measured_log_batch=batch
        class Socket:
            def __init__(socket):socket.acks=asyncio.Queue();socket.sent=0;socket.frontiers=iter((11,12))
            async def send(socket,raw):
                request=json.loads(raw);await socket.acks.put(json.dumps(dict(id=request['id'],result=request['id']+10)))
            async def recv(socket):
                if not socket.acks.empty():return await socket.acks.get()
                subscription=next(socket.frontiers,None)
                if subscription is not None:
                    return json.dumps(dict(params=dict(subscription=subscription,result=dict(context=dict(slot=slot-1),
                        value=dict(err={'InstructionError':[0,0]},signature='failed',logs=[])))))
                await statuses_ready.wait()
                if socket.sent>=(2 if truncated else 1)*admitted_members:
                    socket_idle.set();await asyncio.Event().wait()
                item=txs[socket.sent//(2 if truncated else 1)];socket.sent+=1
                return json.dumps(dict(params=dict(subscription=11,result=dict(context=dict(slot=slot),
                    value=dict(err=None,signature=item['transaction']['signatures'][0],
                        logs=None if unsupported else partial if truncated and not (complete_duplicate and socket.sent==2)
                            else tx['meta']['logMessages'])))))
        class Connection:
            async def __aenter__(self):return Socket()
            async def __aexit__(self,*args):pass
        async def stream(channel,request,handler,family,local_stop):
            for item in txs:
                u=pb.SubscribeUpdate(filters=[scope_labels(addresses)[program_scope('pump')]])
                s=u.transaction_status;s.slot=slot;s.index=item['transactionIndex'];s.signature=based58.b58decode(item['transaction']['signatures'][0].encode())
                if census_bound:
                    await source.handle_native(handler,u,u.ByteSize(),NOW,'census-bound-fixture','pump')
                else:await handler(u,u.ByteSize(),NOW)
            u=pb.SubscribeUpdate(filters=['b']);m=u.block_meta;m.slot=slot;m.parent_slot=slot-1
            m.blockhash=str(slot);m.parent_blockhash=str(slot-1);m.block_time.timestamp=tx['blockTime']
            m.executed_transaction_count=index+repair_members;await handler(u,u.ByteSize(),NOW)
            # Admit the fixture's intended WS population before finality makes
            # any repair witness eligible. Cancellation can then distinguish
            # an accepted complete batch from an explicitly partial slot.
            if repair_members>1:
                statuses_ready.set();await socket_idle.wait()
            u=pb.SubscribeUpdate(filters=['f']);u.slot.slot=slot;u.slot.parent=slot-1;u.slot.status=pb.SLOT_FINALIZED
            await handler(u,u.ByteSize(),NOW);statuses_ready.set()
            admitted=asyncio.create_task(self.entered.wait());closing=asyncio.create_task(local_stop.wait())
            try:
                done,_=await asyncio.wait((admitted,closing),return_when=asyncio.FIRST_COMPLETED)
                if admitted not in done:return
            finally:
                for task in (admitted,closing):
                    if not task.done():task.cancel()
                await asyncio.gather(admitted,closing,return_exceptions=True)
            native_accepted.set()
            if transport_failure:raise EvidenceUnavailable('candidate_native_internal')
            await local_stop.wait()
        source.stream=stream
        desired=[dict(family=f,address=PROGRAMS[f],scope=program_scope(f),priority=6,deadline=NOW+150,
            lower_slot=0,rolling=True) for f in ('pump','pumpswap')]
        local_stop=asyncio.Event()
        from contextlib import nullcontext
        with patch('meme_machine.solana_selective_source.connect',lambda *args,**kw:Connection()), \
                patch('meme_machine.operational.position_continuation.position_only',side_effect=native_accepted.is_set) if cutoff else nullcontext():
            task=asyncio.create_task(source.rolling_programs(None) if cutoff else source.live(None,desired,local_stop))
            if census_bound:
                with self.assertRaisesRegex(EvidenceUnavailable,'^yellowstone_census_buffer_bound$') as refused:
                    await asyncio.wait_for(task,2)
                self.last_native_failure=refused.exception
                return slot
            if unsupported:
                with self.assertRaisesRegex(EvidenceUnavailable,'incomplete_finalized_logs'):
                    await asyncio.wait_for(task,2)
                return slot
            if repair_failure:
                with self.assertRaisesRegex(EvidenceUnavailable,'candidate_stream_log_supplement_incomplete'):
                    await asyncio.wait_for(task,2)
                return slot
            if cancel_repair:
                await asyncio.wait_for(repair_entered.wait(),1)
                if repair_members>1:self.assertEqual(batch_sizes,[admitted_members])
                task.cancel();await asyncio.sleep(.01)
                self.assertFalse(task.done());repair_release.set()
                if admitted_members==repair_members:
                    await asyncio.wait_for(self.entered.wait(),1);self.release.set()
                else:self.assertFalse(self.entered.is_set())
                with self.assertRaises(asyncio.CancelledError):await asyncio.wait_for(task,2)
                self.last_batch_sizes=batch_sizes
                return slot
            await asyncio.wait_for(native_accepted.wait(),1)
            if cancel:task.cancel()
            else:local_stop.set()
            if repeated_cancel or cutoff:
                for _ in range(100):
                    if source.session_teardowns:break
                    await asyncio.sleep(.005)
                self.assertTrue(source.session_teardowns)
                if repeated_cancel:task.cancel()
                if cutoff:source.stop.set()
            await asyncio.sleep(0);self.assertFalse(task.done());self.release.set()
            if transport_failure:
                with self.assertRaisesRegex(EvidenceUnavailable,'candidate_native_internal'):await asyncio.wait_for(task,2)
            elif commit_failure:
                with self.assertRaisesRegex(EvidenceUnavailable,'original_candidate_commit_failure'):await asyncio.wait_for(task,2)
            elif cancel:
                with self.assertRaises(asyncio.CancelledError):await asyncio.wait_for(task,2)
            else:await asyncio.wait_for(task,2)
        self.last_batch_sizes=batch_sizes
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

    async def test_repeated_coordinator_cancellation_does_not_cancel_accepted_owner_commit(self):
        await self.actual_live(cancel=True,repeated_cancel=True)
        self.assertEqual(self.source.drain_snapshot()['queues']['rolling']['pending'],0)
        self.assertGreater(self.history.db.execute('SELECT COUNT(*) FROM candidate_history_outbox').fetchone()[0],0)
        self.assertFalse(self.source.session_teardowns)

    async def test_actual_optional_cutoff_cancels_coordinator_but_drains_owned_evidence(self):
        await self.actual_live(cutoff=True)
        self.assertEqual(self.source.drain_snapshot()['queues']['rolling'],dict(accepted=1,committed=1,pending=0))
        self.assertGreater(self.history.db.execute('SELECT COUNT(*) FROM candidate_history_outbox').fetchone()[0],0)

    async def test_actual_live_commit_failure_does_not_ack_or_clear_accepted_count(self):
        await self.actual_live(commit_failure=True)
        self.assertEqual(self.source.drain_snapshot()['queues']['rolling'],dict(accepted=1,committed=0,pending=1))
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM rolling_economic_events').fetchone()[0],0)
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM candidate_gaps WHERE hi IS NULL').fetchone()[0],2)

    async def close_accepted_soft_wait(self, *, retry=False, hard_full=False, expired=False):
        """Real WS callback/session teardown; only transports and byte scale differ."""
        import based58
        from meme_machine import solana_selective_source as source_module
        source=self.source;source.work=self.work;source.batched=True
        tx=FIXTURE['pump'][0];slot=tx['slot'];waiting=asyncio.Event();close=asyncio.Event();native_ready=asyncio.Event()
        first=['first accepted log'];size=len(str(first).encode());bound=size*3
        second=['x'*(size*2)] if hard_full else list(first)
        signatures=[tx['transaction']['signatures'][0],
            based58.b58encode(b'2'*64).decode()]
        lease=[0.]
        original_wait=source_module.wait_candidate_log_space
        async def space(join,progress,stop,local_stop,number,identity,logs):
            if identity==signatures[1]:
                if expired:join.clock=lambda:lease[0]
                waiting.set()
            return await original_wait(join,progress,stop,local_stop,number,identity,logs)
        async def tip(*args):return slot-1
        source.measured_rpc=tip
        async def stream(channel,request,handler,family,local_stop):
            native_ready.set()
            await close.wait()
            if retry:raise EvidenceUnavailable('candidate_log_buffer_pressure')
            await local_stop.wait()
        source.stream=stream
        class Socket:
            def __init__(socket):socket.acks=asyncio.Queue();socket.number=0
            async def send(socket,raw):
                request=json.loads(raw);await socket.acks.put(json.dumps(dict(id=request['id'],result=request['id']+10)))
            async def recv(socket):
                if not socket.acks.empty():return await socket.acks.get()
                number=socket.number;socket.number+=1
                if number<2:
                    return json.dumps(dict(params=dict(subscription=11+number,result=dict(context=dict(slot=slot-1),
                        value=dict(err={'InstructionError':[0,0]},signature='failed',logs=[])))))
                await native_ready.wait()
                if number<4:
                    return json.dumps(dict(params=dict(subscription=11,result=dict(context=dict(slot=slot),
                        value=dict(err=None,signature=signatures[number-2],logs=(first,second)[number-2])))))
                await asyncio.Event().wait()
        class Connection:
            async def __aenter__(self):return Socket()
            async def __aexit__(self,*args):pass
        desired=[dict(family=f,address=PROGRAMS[f],scope=program_scope(f),priority=6,deadline=NOW+150,
            lower_slot=0,rolling=True) for f in ('pump','pumpswap')]
        local_stop=asyncio.Event()
        with patch('meme_machine.solana_selective_source.connect',lambda *args,**kw:Connection()), \
                patch('meme_machine.solana_selective_source.wait_candidate_log_space',space), \
                patch('meme_machine.solana_selective_source.MAX_PENDING_BYTES',bound), \
                patch('meme_machine.solana_candidate_join.MAX_PENDING_BYTES',bound):
            task=asyncio.create_task(source.live(None,desired,local_stop))
            try:
                await asyncio.wait_for(waiting.wait(),1)
                self.assertFalse(task.done())
                snapshot=source.drain_snapshot()
                self.assertEqual(snapshot['pending_handlers'],1)
                self.assertEqual(next(iter(source.handlers.records.values()))['phase'],'LOG_BUFFER_WAIT')
                if expired:lease[0]=120.
                close.set()
                if not retry:local_stop.set()
                if hard_full or expired:
                    with self.assertRaises(asyncio.CancelledError):await asyncio.wait_for(task,2)
                elif retry:
                    with self.assertRaisesRegex(EvidenceUnavailable,'^candidate_log_buffer_pressure$'):
                        await asyncio.wait_for(task,2)
                else:await asyncio.wait_for(task,2)
            finally:
                if not task.done():task.cancel()
                await asyncio.gather(task,return_exceptions=True)
        body=json.loads(self.history.db.execute("SELECT body FROM acquisition_observations WHERE kind='source_session_drain'").fetchone()[0])
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM candidate_coverage').fetchone()[0],0)
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM candidate_checkpoints').fetchone()[0],0)
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM rolling_economic_events').fetchone()[0],0)
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM candidate_gaps WHERE lo=? AND hi IS NULL',(slot,)).fetchone()[0],2)
        self.assertFalse(body['complete_history_claim'])
        self.assertEqual(source.source_drain['preserved_partial_sessions'],1)
        self.assertEqual(source.source_drain['unpreserved_sessions'],0)
        self.assertLessEqual(body['early_log_bytes'],bound)
        return body

    async def test_normal_session_close_admits_owned_soft_wait_within_original_hard_bound(self):
        body=await self.close_accepted_soft_wait()
        self.assertEqual(body['early_log_count'],2)
        self.assertTrue(body['drained'])
        self.assertEqual(self.source.drain_snapshot()['pending_handlers'],0)
        self.assertEqual(body['handler_dispositions'],[])

    async def test_pressure_retry_preserves_original_error_but_finishes_owned_soft_wait(self):
        body=await self.close_accepted_soft_wait(retry=True)
        self.assertEqual(body['early_log_count'],2)
        self.assertTrue(body['drained'])
        self.assertEqual(self.source.drain_snapshot()['pending_handlers'],0)

    async def test_close_without_hard_headroom_preserves_interrupted_handler_and_gap(self):
        body=await self.close_accepted_soft_wait(hard_full=True)
        self.assertEqual(body['early_log_count'],1)
        self.assertFalse(body['drained'])
        snapshot=self.source.drain_snapshot()
        self.assertEqual(snapshot['pending_handlers'],1)
        self.assertEqual(snapshot['handler_accounting']['recoverable'],1)
        self.assertEqual(snapshot['handler_accounting']['returned'],snapshot['accepted_handlers']-1)

    async def test_close_does_not_extend_original_wait_lease_to_use_hard_headroom(self):
        body=await self.close_accepted_soft_wait(expired=True)
        self.assertEqual(body['early_log_count'],1)
        self.assertFalse(body['drained'])
        self.assertEqual(self.source.drain_snapshot()['pending_handlers'],1)
        self.assertEqual(self.source.drain_snapshot()['handler_accounting']['recoverable'],1)

    async def test_actual_truncated_ws_packets_repair_once_without_program_restart_or_partial_decode(self):
        await self.actual_live(truncated=True)
        self.assertEqual(self.source.source_drain['closed_sessions'],1)
        self.assertEqual(self.source.drain_snapshot()['pending_handlers'],0)
        self.assertEqual(self.source.drain_snapshot()['queues']['rolling'],dict(accepted=1,committed=1,pending=0))
        self.assertGreater(self.history.db.execute('SELECT COUNT(*) FROM rolling_economic_events').fetchone()[0],0)
        receipt=json.loads(self.history.db.execute("SELECT body FROM acquisition_observations WHERE kind='native_stream_log_supplement'").fetchone()[0])
        self.assertEqual(receipt['method'],'getTransaction');self.assertFalse(receipt['truncated_logs_used_as_complete'])
        metrics=self.source.pipeline_metrics['log_repair:rolling']
        self.assertEqual((metrics['deferred'],metrics['duplicate_deliveries'],metrics['repair_logical_calls'],
            metrics['supplements_authenticated'],metrics['supplements_failed']),(1,1,1,1,0))

    async def test_actual_eight_truncated_packets_coalesce_and_authenticate_before_one_ordered_commit(self):
        await self.actual_live(truncated=True,repair_members=8)
        self.assertEqual(self.last_batch_sizes,[8])
        metrics=self.source.pipeline_metrics['log_repair:rolling']
        self.assertEqual((metrics['repair_logical_calls'],metrics['supplements_authenticated'],metrics['supplements_failed']),(8,8,0))
        self.assertEqual(self.source.drain_snapshot()['queues']['rolling'],dict(accepted=1,committed=1,pending=0))
        self.assertEqual(self.history.db.execute("SELECT COUNT(*) FROM acquisition_observations WHERE kind='native_stream_log_supplement'").fetchone()[0],8)
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM candidate_coverage').fetchone()[0],0)

    async def test_cancel_during_multi_member_repair_waits_for_original_batch_and_ordered_owner(self):
        await self.actual_live(truncated=True,repair_members=8,cancel_repair=True)
        self.assertEqual(self.last_batch_sizes,[8])
        self.assertEqual(self.source.drain_snapshot()['pending_handlers'],0)
        self.assertEqual(self.source.drain_snapshot()['queues']['rolling'],dict(accepted=1,committed=1,pending=0))
        self.assertEqual(self.source.pipeline_metrics['log_repair:rolling']['supplements_authenticated'],8)

    async def test_cancel_during_partial_batch_preserves_missing_native_logs_without_economic_commit(self):
        slot=await self.actual_live(truncated=True,repair_members=8,repair_admitted_members=2,cancel_repair=True)
        self.assertEqual(self.last_batch_sizes,[2])
        self.assertEqual(self.source.drain_snapshot()['queues']['rolling'],dict(accepted=0,committed=0,pending=0))
        self.assertEqual(self.source.pipeline_metrics['log_repair:rolling']['supplements_authenticated'],2)
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM rolling_economic_events').fetchone()[0],0)
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM candidate_coverage').fetchone()[0],0)
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM candidate_checkpoints').fetchone()[0],0)
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM candidate_gaps WHERE lo=? AND hi IS NULL',(slot,)).fetchone()[0],2)
        body=json.loads(self.history.db.execute("SELECT body FROM acquisition_observations WHERE kind='source_session_drain'").fetchone()[0])
        self.assertEqual((body['pending_slots'],body['oldest_statuses'],body['oldest_missing_logs']),(1,8,6))
        self.assertEqual(self.source.source_drain['preserved_partial_sessions'],1)

    async def test_actual_repeated_http_truncation_preserves_gap_and_no_economic_or_coverage_claim(self):
        slot=await self.actual_live(truncated=True,repair_failure=True)
        self.assertEqual(self.source.drain_snapshot()['pending_handlers'],0)
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM rolling_economic_events').fetchone()[0],0)
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM candidate_coverage').fetchone()[0],0)
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM candidate_checkpoints').fetchone()[0],0)
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM candidate_gaps WHERE lo=? AND hi IS NULL',(slot,)).fetchone()[0],2)
        self.assertEqual(self.history.db.execute("SELECT COUNT(*) FROM acquisition_observations WHERE kind='native_stream_log_supplement_failed'").fetchone()[0],1)
        self.assertEqual(self.source.pipeline_metrics['log_repair:rolling']['supplements_failed'],1)

    async def test_actual_full_ws_duplicate_coalesces_with_pending_authenticated_repair(self):
        await self.actual_live(truncated=True,complete_duplicate=True)
        metrics=self.source.pipeline_metrics['log_repair:rolling']
        self.assertEqual((metrics['deferred'],metrics['duplicate_deliveries'],metrics['repair_logical_calls'],
            metrics['supplements_authenticated']),(1,1,1,1))
        self.assertEqual(self.source.drain_snapshot()['pending_handlers'],0)
        self.assertEqual(self.source.drain_snapshot()['queues']['rolling'],dict(accepted=1,committed=1,pending=0))

    async def test_cancel_during_actual_truncation_repair_waits_for_original_result_and_owner(self):
        await self.actual_live(truncated=True,cancel_repair=True)
        self.assertEqual(self.source.drain_snapshot()['pending_handlers'],0)
        self.assertEqual(self.source.drain_snapshot()['queues']['rolling'],dict(accepted=1,committed=1,pending=0))
        self.assertEqual(self.source.pipeline_metrics['log_repair:rolling']['supplements_authenticated'],1)
        self.assertGreater(self.history.db.execute('SELECT COUNT(*) FROM rolling_economic_events').fetchone()[0],0)

    async def test_permanent_stream_supplement_failure_is_not_an_unchanged_reconnect_loop(self):
        from unittest.mock import AsyncMock
        source=self.source;source.work=self.work
        async def startup():return None
        source.wait_current_control=startup
        for reason in ('candidate_stream_log_supplement_incomplete','incomplete_finalized_logs'):
            with self.subTest(reason=reason):
                async def live(*args):raise EvidenceUnavailable(reason)
                source.live=AsyncMock(side_effect=live)
                with self.assertRaisesRegex(EvidenceUnavailable,reason):
                    await asyncio.wait_for(source.rolling_programs(None),1)
                self.assertEqual(source.live.call_count,1)

    async def test_actual_unsupported_log_shape_preserves_failed_callback_and_exact_unavailable_gap(self):
        slot=await self.actual_live(unsupported=True)
        self.assertEqual(self.source.source_drain['closed_sessions'],1)
        snapshot=self.source.drain_snapshot()
        self.assertEqual(snapshot['pending_handlers'],1)
        self.assertEqual(snapshot['handler_accounting']['recoverable'],1)
        self.assertEqual(snapshot['handler_accounting']['returned'],snapshot['handler_accounting']['accepted']-1)
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM rolling_economic_events').fetchone()[0],0)
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM candidate_coverage').fetchone()[0],0)
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM candidate_gaps WHERE lo=? AND hi IS NULL',(slot,)).fetchone()[0],2)
        reason_rows=[body for kind,body in self.source.pending_diagnostics if kind=='log_join_failure']
        self.assertEqual([body['reason'] for body in reason_rows],
            ['incomplete_finalized_logs','candidate_stream_logs_null_or_missing'])

    async def test_actual_census_bound_attributes_guard_without_settling_failed_native_handler(self):
        with patch('meme_machine.solana_candidate_join.MAX_PENDING_SLOTS',0):
            slot=await self.actual_live(census_bound=True)
        error=self.last_native_failure
        self.assertIs(type(error),EvidenceUnavailable)
        self.assertEqual(error.args,('yellowstone_census_buffer_bound',))
        self.assertEqual(error.join_capacity_reason,'yellowstone_census_pending_slots_bound')
        rows=self.history.db.execute("SELECT body FROM acquisition_observations WHERE kind='join_failure'").fetchall()
        self.assertEqual(len(rows),1)
        self.assertEqual(json.loads(rows[0][0])['reason'],'yellowstone_census_pending_slots_bound')
        snapshot=self.source.drain_snapshot()
        self.assertEqual(snapshot['pending_handlers'],1)
        self.assertEqual(snapshot['handler_accounting']['recoverable'],1)
        self.assertEqual(snapshot['handler_accounting']['returned'],snapshot['handler_accounting']['accepted']-1)
        self.assertEqual(self.source.source_drain['closed_sessions'],1)
        self.assertEqual(self.source.source_drain['preserved_partial_sessions'],1)
        self.assertEqual(self.source.source_drain['unpreserved_sessions'],0)
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM rolling_economic_events').fetchone()[0],0)
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM candidate_coverage').fetchone()[0],0)
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM candidate_checkpoints').fetchone()[0],0)
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM candidate_gaps WHERE lo=? AND hi IS NULL',(slot,)).fetchone()[0],2)

    async def test_untagged_census_failure_preserves_generic_reason_and_exception_identity(self):
        from meme_machine.solana_candidate_join import CandidateTransactionJoin
        original=CandidateTransactionJoin.feed;failures=[]
        def untagged(join,*args):
            try:return original(join,*args)
            except EvidenceUnavailable as error:
                del error.join_capacity_reason;failures.append(error);raise
        with patch('meme_machine.solana_candidate_join.MAX_PENDING_SLOTS',0), \
                patch.object(CandidateTransactionJoin,'feed',untagged):
            await self.actual_live(census_bound=True)
        self.assertEqual(len(failures),1)
        self.assertIs(self.last_native_failure,failures[0])
        self.assertEqual(self.last_native_failure.args,('yellowstone_census_buffer_bound',))
        row=self.history.db.execute("SELECT body FROM acquisition_observations WHERE kind='join_failure'").fetchone()
        self.assertEqual(json.loads(row[0])['reason'],'yellowstone_census_buffer_bound')
        self.assertEqual(self.source.drain_snapshot()['handler_accounting']['recoverable'],1)

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


class NativeIntakeCancellationTests(unittest.IsolatedAsyncioTestCase):
    async def stream(self,*,write_idle=False,accepted=False):
        source=SelectiveSource(SimpleNamespace(credential='offline'),None)
        source.stop=asyncio.Event();local=asyncio.Event();entered=asyncio.Event();release=asyncio.Event()
        async def delivered(*args):pass
        source.delivered=delivered
        closed=[];read_cancelled=[];write_cancelled=[]
        u=pb.SubscribeUpdate();u.block_meta.slot=123
        class Call:
            def __init__(self):self.reads=0
            async def write(self,request):
                if write_idle:
                    entered.set()
                    try:await asyncio.Event().wait()
                    finally:write_cancelled.append(True)
            async def read(self):
                self.reads+=1
                if accepted and self.reads==1:return u.SerializeToString()
                entered.set()
                try:await asyncio.Event().wait()
                finally:read_cancelled.append(True)
            def cancel(self):closed.append(True)
        call=Call()
        class Channel:
            def stream_stream(self,*args,**kwargs):return lambda **kw:call
        async def handler(update,size,seen):
            entered.set();await release.wait()
        task=asyncio.create_task(source.stream(Channel(),pb.SubscribeRequest(),handler,'shared',local))
        try:
            await asyncio.wait_for(entered.wait(),.5);local.set()
            if accepted:
                await asyncio.sleep(0);self.assertFalse(task.done());release.set()
            await asyncio.wait_for(task,.5)
            self.assertEqual(closed,[True])
            body=source.drain_snapshot()
            self.assertEqual((body['accepted_handlers'],body['settled_handlers']),(int(accepted),int(accepted)))
            if write_idle:self.assertEqual(write_cancelled,[True])
            elif not accepted:self.assertEqual(read_cancelled,[True])
        finally:
            if not task.done():task.cancel()
            await asyncio.gather(task,return_exceptions=True)

    async def test_idle_provider_read_is_cancelled_without_an_accepted_handler(self):
        await self.stream()

    async def test_idle_subscription_write_is_cancelled_without_fabricating_received_work(self):
        await self.stream(write_idle=True)

    async def test_closing_transport_waits_for_already_accepted_handler(self):
        await self.stream(accepted=True)

    async def test_owned_teardown_deadline_fails_instead_of_waiting_forever(self):
        cancelled=[]
        async def blocked():
            try:await asyncio.Event().wait()
            finally:cancelled.append(True)
        task=asyncio.create_task(blocked());await asyncio.sleep(0)
        with self.assertRaises(TimeoutError):
            await finish_owned(task,asyncio.get_running_loop().time()+.02)
        await asyncio.gather(task,return_exceptions=True)
        self.assertEqual(cancelled,[True]);self.assertTrue(task.cancelled())

    async def test_optional_child_ignoring_first_cancellation_remains_bounded_and_failed(self):
        source=SelectiveSource(SimpleNamespace(credential='offline'),None)
        source.stop=asyncio.Event();local=asyncio.Event();entered=asyncio.Event();release=asyncio.Event()
        async def unresponsive():
            entered.set()
            try:await asyncio.Event().wait()
            except asyncio.CancelledError:await release.wait()
        task=asyncio.create_task(unresponsive());await entered.wait()
        source.drain_deadline=asyncio.get_running_loop().time()+.02
        try:
            with self.assertRaises(TimeoutError):await asyncio.wait_for(source.close_optional_session(task,local),.5)
            self.assertEqual(source.drain_snapshot()['state'],'RECOVERY_REQUIRED')
            self.assertTrue(source.drain_snapshot()['terminal_record_unavailable'])
            self.assertTrue(local.is_set())
        finally:
            release.set();task.cancel();await asyncio.gather(task,return_exceptions=True)
