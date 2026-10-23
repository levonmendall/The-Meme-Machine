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
        tx=txs[0];batch_sizes=[];repair_calls=[]
        admitted_members=repair_members if repair_admitted_members is None else repair_admitted_members
        assert 1<=admitted_members<=repair_members
        full_cancel=cancel_repair and admitted_members==repair_members and repair_members>7
        addresses={PROGRAMS[f]:program_scope(f) for f in ('pump','pumpswap')}
        statuses_ready=asyncio.Event();native_accepted=asyncio.Event()
        socket_idle=asyncio.Event();repair_entered=asyncio.Event();repair_release=asyncio.Event()
        partial=tx['meta']['logMessages'][:4]+['Log truncated']
        loop=asyncio.get_running_loop();phase_started=loop.time();phases={};phase_trace=[]
        prior_tasks=asyncio.all_tasks() if cancel_repair else set()
        member_numbers={item['transaction']['signatures'][0]:number for number,item in enumerate(txs,1)}
        def phase(name,member=None):
            if not cancel_repair:return
            elapsed=round(loop.time()-phase_started,6)
            # Fixed phase rows are [count, first seconds, last seconds]; retain
            # only the last32 individual events, using fixture member ordinals.
            row=phases.setdefault(name,[0,elapsed,elapsed]);row[0]+=1;row[2]=elapsed
            phase_trace.append((name,elapsed,member))
            del phase_trace[:-32]
        def repair_diagnostic(task):
            children=(asyncio.all_tasks()-prior_tasks)|{task}
            stacks=[]
            for child in sorted(children,key=lambda t:(t.get_coro().__qualname__,t.get_name()))[:12]:
                stacks.append(dict(coro=child.get_coro().__qualname__[:160],done=child.done(),
                    cancelling=child.cancelling(),stack=[f'{Path(frame.f_code.co_filename).name}:{frame.f_lineno}:{frame.f_code.co_name}'
                        for frame in child.get_stack(limit=4)]))
            original='PENDING'
            if task.cancelled():original='CANCELLED'
            elif task.done():
                failure=task.exception()
                original=repr(failure)[:512] if failure is not None else 'RETURNED'
            return 'native_repair_fixture '+json.dumps(dict(elapsed=round(loop.time()-phase_started,6),
                phases=phases,trace_tail=phase_trace,live_outcome=original,
                socket_idle=socket_idle.is_set(),repair_entered=repair_entered.is_set(),
                batch_sizes=batch_sizes[:8],repair_calls=len(repair_calls),
                metrics={key:source.pipeline_metrics.get('log_repair:rolling',{}).get(key)
                    for key in ('repair_logical_calls','supplements_authenticated','supplements_failed')},
                tasks=stacks,omitted_tasks=max(0,len(children)-12)),sort_keys=True)
        async def work(fn,priority=2,**options):
            if options.get('component')=='candidate':
                phase('candidate_owner_entered')
                self.entered.set();await self.release.wait()
                if commit_failure:raise EvidenceUnavailable('original_candidate_commit_failure')
            receipt=cancel_repair and 'native_stream_log_supplement' in fn.__code__.co_consts
            if receipt:phase('receipt_started')
            result=fn(self.state)
            if receipt:phase('receipt_committed')
            if options.get('component')=='candidate':phase('candidate_owner_returned')
            return result
        async def tip(method,*args):
            if method=='getTransaction':
                # WS must keep reading while the selective HTTP repair is in
                # flight, including the same transaction's duplicate packet.
                repair_calls.append(args[0][0])
                phase('scalar_entered',member_numbers[args[0][0]])
                if repair_members==1 or full_cancel:repair_entered.set()
                await socket_idle.wait()
                if cancel_repair and (repair_members==1 or full_cancel):await repair_release.wait()
                fetched=copy.deepcopy(next(item for item in txs if item['transaction']['signatures'][0]==args[0][0]));fetched.pop('transactionIndex',None)
                if repair_failure:fetched['meta']['logMessages']=partial
                phase('scalar_returned',member_numbers[args[0][0]])
                return fetched
            return slot-1
        source.work=work;source.measured_rpc=tip
        real_batch=source.measured_log_batch
        async def batch(signatures,priority=2):
            if len(signatures)==1:return await real_batch(signatures,priority)
            batch_sizes.append(len(signatures));repair_calls.extend(signatures)
            phase('batch_entered',len(signatures))
            if not full_cancel:repair_entered.set()
            await socket_idle.wait()
            if cancel_repair and not full_cancel:await repair_release.wait()
            result=[dict(copy.deepcopy(next(item for item in txs if item['transaction']['signatures'][0]==sig)))
                for sig in signatures]
            phase('batch_returned',len(signatures));return result
        source.measured_log_batch=batch
        class Socket:
            def __init__(socket):socket.acks=asyncio.Queue();socket.sent=0;socket.frontiers=iter((11,12))
            async def send(socket,raw):
                request=json.loads(raw);await socket.acks.put(json.dumps(dict(id=request['id'],result=request['id']+10)))
            async def recv(socket):
                if not socket.acks.empty():
                    phase('ws_ack');return await socket.acks.get()
                subscription=next(socket.frontiers,None)
                if subscription is not None:
                    phase('ws_frontier')
                    return json.dumps(dict(params=dict(subscription=subscription,result=dict(context=dict(slot=slot-1),
                        value=dict(err={'InstructionError':[0,0]},signature='failed',logs=[])))))
                await statuses_ready.wait()
                if socket.sent>=(2 if truncated else 1)*admitted_members:
                    phase('ws_idle')
                    socket_idle.set();await asyncio.Event().wait()
                item=txs[socket.sent//(2 if truncated else 1)];socket.sent+=1
                phase('ws_packet',member_numbers[item['transaction']['signatures'][0]])
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
                phase('native_status',member_numbers[item['transaction']['signatures'][0]])
            u=pb.SubscribeUpdate(filters=['b']);m=u.block_meta;m.slot=slot;m.parent_slot=slot-1
            m.blockhash=str(slot);m.parent_blockhash=str(slot-1);m.block_time.timestamp=tx['blockTime']
            m.executed_transaction_count=index+repair_members;await handler(u,u.ByteSize(),NOW)
            phase('native_meta')
            # Admit the fixture's intended WS population before finality makes
            # any repair witness eligible. Cancellation can then distinguish
            # an accepted complete batch from an explicitly partial slot.
            if repair_members>1:
                statuses_ready.set();await socket_idle.wait()
            u=pb.SubscribeUpdate(filters=['f']);u.slot.slot=slot;u.slot.parent=slot-1;u.slot.status=pb.SLOT_FINALIZED
            await handler(u,u.ByteSize(),NOW);statuses_ready.set()
            phase('native_finality')
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
        from contextlib import ExitStack
        with ExitStack() as patches:
            patches.enter_context(patch('meme_machine.solana_selective_source.connect',lambda *args,**kw:Connection()))
            if cutoff:patches.enter_context(patch('meme_machine.operational.position_continuation.position_only',side_effect=native_accepted.is_set))
            if cancel_repair:
                from meme_machine.solana_candidate_join import CandidateTransactionJoin
                begin=CandidateTransactionJoin.begin_required_log_read
                complete=CandidateTransactionJoin.complete_required_log
                end=CandidateTransactionJoin.end_required_log_read
                def begin_read(join,number,signature):
                    result=begin(join,number,signature)
                    phase('read_acquired',member_numbers.get(signature));return result
                def complete_read(join,number,signature,logs,seen):
                    phase('join_install_started',member_numbers.get(signature))
                    result=complete(join,number,signature,logs,seen)
                    phase('join_install_returned',member_numbers.get(signature));return result
                def end_read(join,number,signature):
                    owned=(number,signature) in join.required_log_reads
                    result=end(join,number,signature)
                    if owned:phase('read_released',member_numbers.get(signature))
                    return result
                patches.enter_context(patch.object(CandidateTransactionJoin,'begin_required_log_read',begin_read))
                patches.enter_context(patch.object(CandidateTransactionJoin,'complete_required_log',complete_read))
                patches.enter_context(patch.object(CandidateTransactionJoin,'end_required_log_read',end_read))
            task=asyncio.create_task(source.rolling_programs(None) if cutoff else source.live(None,desired,local_stop))
            phase('live_created')
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
                entered_waiter=asyncio.create_task(repair_entered.wait())
                try:
                    done,_=await asyncio.wait((entered_waiter,task),timeout=1,return_when=asyncio.FIRST_COMPLETED)
                    if task in done:
                        # Preserve an original source exception and traceback;
                        # an event-only wait previously masked it as a timeout.
                        task.result()
                        self.fail('live source returned before repair cancellation barrier')
                    if entered_waiter not in done:
                        raise TimeoutError('repair cancellation barrier not reached within original 1s')
                except BaseException as error:
                    error.add_note(repair_diagnostic(task))
                    # Release only fixture gates, then finish the original source
                    # while its patches and disposable database still exist.
                    repair_release.set();self.release.set();local_stop.set()
                    if not task.done():task.cancel()
                    settled,_=await asyncio.wait((task,),timeout=2)
                    if task not in settled:error.add_note('native_repair_fixture cleanup still pending after 2s')
                    elif not task.cancelled() and task.exception() is not None and task.exception() is not error:
                        error.add_note('native_repair_fixture cleanup exception: '+repr(task.exception())[:512])
                    raise
                finally:
                    if not entered_waiter.done():entered_waiter.cancel()
                    await asyncio.gather(entered_waiter,return_exceptions=True)
                if repair_members>1:self.assertEqual(batch_sizes,[min(admitted_members,7)])
                if full_cancel:
                    # Seven prepared fields have settled; the last scalar HTTP
                    # read is now independently accepted before cancellation.
                    # Never label seven accepted fields as a completed eight.
                    self.assertEqual(len(repair_calls),repair_members)
                    self.assertEqual(source.pipeline_metrics['log_repair:rolling']['repair_logical_calls'],repair_members)
                task.cancel();await asyncio.sleep(.01)
                self.assertFalse(task.done());repair_release.set()
                if admitted_members==repair_members:
                    await asyncio.wait_for(self.entered.wait(),1);self.release.set()
                else:self.assertFalse(self.entered.is_set())
                with self.assertRaises(asyncio.CancelledError):await asyncio.wait_for(task,2)
                self.last_batch_sizes=batch_sizes;self.last_repair_calls=repair_calls
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
        self.last_batch_sizes=batch_sizes;self.last_repair_calls=repair_calls
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

    async def repair_stage_barrier(self, blocked, *, batch=False):
        """Real live/repair callbacks; gate only offline transport/owner boundaries.

        The WS receiver owns a future packet above its soft waterline. One
        captured head log remains buffered while an absent native-required
        field uses the real measured RPC, accounting and receipt callbacks.
        Virtual wall clocks identify where the existing availability stamp is
        taken; they are not provider latency or market-capacity measurements.
        """
        import based58
        import threading
        from meme_machine import solana_selective_source as module
        from meme_machine.solana_candidate_join import CandidateTransactionJoin
        from meme_machine.solana_selective_history import economic_records
        from meme_machine.solana_source_drain import StopEither
        self.assertIn(blocked,('transport','delivery','receipt','join_install'))
        original=copy.deepcopy(FIXTURE['pump'][0]);slot=original['slot'];index=original['transactionIndex']
        first=original['transaction']['signatures'][0]
        required=[based58.b58encode(bytes([number])*64).decode()
            for number in range(2,4 if batch else 3)]
        future=based58.b58encode(bytes([9])*64).decode()
        transactions={first:original}
        for signature in required+[future]:
            tx=copy.deepcopy(original);tx['transaction']['signatures'][0]=signature
            if signature==future:tx['slot']+=2;tx['blockTime']+=2
            transactions[signature]=tx
        loop=asyncio.get_running_loop();wall=[NOW];physical_return=[];available=[];trace=[]
        transport_release=threading.Event()
        gates={stage:asyncio.Event() for stage in ('delivery','receipt','join_install')}
        entered={stage:asyncio.Event() for stage in ('transport','delivery','receipt','join_install')}
        for stage,gate in gates.items():
            if stage!=blocked:gate.set()
        if blocked!='transport':transport_release.set()
        all_receipts=asyncio.Event();all_receipt_attempts=asyncio.Event()
        receipt_attempts=[];persisted=[];read_contexts={};join_box=[];installed=[];joined=[]
        first_admitted=asyncio.Event();future_waiting=asyncio.Event();future_admitted=asyncio.Event()
        head_installed=asyncio.Event();native_ready=asyncio.Event();packets=asyncio.Queue()
        local_stop=asyncio.Event();physical=[]

        class OfflineRPC:
            def delivered(self,signatures,priority):
                self_case.assertEqual(priority,2);self_case.assertEqual(signatures,required)
                physical.append(tuple(signatures));loop.call_soon_threadsafe(entered['transport'].set)
                if not transport_release.wait(3):raise TimeoutError('offline transport gate')
                wall[0]=NOW+10;physical_return.append(wall[0]);trace.append(('transport_return',wall[0]))
                values=[]
                for signature in signatures:
                    tx=copy.deepcopy(transactions[signature]);tx.pop('transactionIndex',None);values.append(tx)
                receipt=dict(bytes=len(json.dumps(values).encode()),cu=40*len(values),calls=1)
                if len(values)>1:receipt['batch_members']=len(values)
                return values,receipt
            def call_delivered(self,method,params,priority):
                if method=='getSlot':return slot-1,dict(bytes=1,cu=1,calls=1)
                self_case.assertEqual(method,'getTransaction')
                self_case.assertEqual(params[1],dict(commitment='finalized',encoding='json',maxSupportedTransactionVersion=1))
                values,receipt=self.delivered([params[0]],priority);return values[0],receipt
            def log_batch_delivered(self,signatures,priority):return self.delivered(signatures,priority)
        self_case=self
        source=SelectiveSource(SimpleNamespace(credential='offline',identity='a'*64,stream_url='offline'),OfflineRPC())
        source.stop=asyncio.Event();source.batched=True
        def receipts():
            # A separate real reader proves the owner callback's SQL is visible
            # after its commit, not merely present on an uncommitted connection.
            with closing(sqlite3.connect(self.state.writer.path)) as reader:
                return [json.loads(raw) for raw, in reader.execute(
                    "SELECT body FROM acquisition_observations WHERE kind='native_stream_log_supplement'")]
        def accounting():
            return self.history.db.execute("SELECT COALESCE(SUM(calls),0) FROM provider_delivery "
                "WHERE family='rolling_recovery_missing_logs' AND transport='rpc'").fetchone()[0]
        async def work(fn,priority=2,**options):
            closure={name:cell.cell_contents for name,cell in zip(fn.__code__.co_freevars,fn.__closure__ or ())}
            if 'delivery' in fn.__code__.co_names and closure.get('family')=='rolling_recovery_missing_logs':
                entered['delivery'].set();await gates['delivery'].wait()
                result=fn(self.state);trace.append(('delivery_committed',wall[0]));return result
            if 'native_stream_log_supplement' in fn.__code__.co_consts:
                signature=closure['receipt']['native_witness']['signature']
                receipt_attempts.append(signature);available.append(closure['available'])
                if len(receipt_attempts)==len(required):all_receipt_attempts.set()
                entered['receipt'].set();await gates['receipt'].wait()
                result=fn(self.state);self.assertFalse(self.history.db.in_transaction)
                persisted.append(signature);trace.append(('receipt_committed',signature,wall[0]))
                if len(persisted)==len(required):all_receipts.set()
                # complete_required_log is synchronous. Holding the existing
                # awaited owner return is its final asynchronous pre-install
                # boundary; no fake sleep is inserted into join mutation.
                entered['join_install'].set();await gates['join_install'].wait()
                return result
            return fn(self.state)
        source.work=work
        def observe(kind,values):
            if kind=='joined_frame':joined.append(values['slot'])
        source.observer=observe
        begin=CandidateTransactionJoin.begin_required_log_read
        feed=CandidateTransactionJoin.feed_log
        complete=CandidateTransactionJoin.complete_required_log
        wait_space=module.wait_candidate_log_space
        def begin_read(join,number,signature):
            witness=begin(join,number,signature)
            if signature in required:read_contexts[signature]=join.required_log_reads[number,signature]
            return witness
        def feed_log(join,number,signature,logs,error,seen):
            result=feed(join,number,signature,logs,error,seen)
            if signature==first:first_admitted.set()
            if signature==future:future_admitted.set()
            return result
        def install_log(join,number,signature,logs,seen):
            if signature in required:
                self.assertIs(join.required_log_reads[number,signature],read_contexts[signature])
                self.assertTrue(any(row['native_witness']['signature']==signature for row in receipts()))
                self.assertEqual(accounting(),1)
                installed.append(signature);trace.append(('join_install',signature,wall[0]))
            result=complete(join,number,signature,logs,seen)
            if number==slot and join.completed>=slot:head_installed.set()
            return result
        async def pressure(join,progress,stop,session_stop,number,signature,logs):
            if not join_box:join_box.append(join)
            if signature==future:future_waiting.set()
            return await wait_space(join,progress,stop,session_stop,number,signature,logs)
        class Socket:
            def __init__(socket):socket.acks=asyncio.Queue();socket.frontiers=iter((11,12))
            async def send(socket,raw):
                value=json.loads(raw);await socket.acks.put(json.dumps(dict(id=value['id'],result=value['id']+10)))
            async def recv(socket):
                if not socket.acks.empty():return await socket.acks.get()
                frontier=next(socket.frontiers,None)
                if frontier is not None:
                    return json.dumps(dict(params=dict(subscription=frontier,result=dict(context=dict(slot=slot-1),
                        value=dict(err={'InstructionError':[0,0]},signature='failed',logs=[])))))
                return await packets.get()
        class Connection:
            async def __aenter__(self):return Socket()
            async def __aexit__(self,*args):pass
        async def packet(signature):
            tx=transactions[signature]
            await packets.put(json.dumps(dict(params=dict(subscription=11,result=dict(context=dict(slot=tx['slot']),
                value=dict(err=None,signature=signature,logs=tx['meta']['logMessages']))))))
        addresses={PROGRAMS[f]:program_scope(f) for f in ('pump','pumpswap')}
        async def status(handler,number,signature,ordinal):
            u=pb.SubscribeUpdate(filters=[scope_labels(addresses)[program_scope('pump')]])
            u.transaction_status.slot=number;u.transaction_status.index=ordinal
            u.transaction_status.signature=based58.b58decode(signature.encode())
            await handler(u,u.ByteSize(),NOW)
        async def finalized(handler,offset,count):
            number=slot+offset
            u=pb.SubscribeUpdate(filters=['b']);m=u.block_meta;m.slot=number;m.parent_slot=number-1
            m.blockhash=str(number);m.parent_blockhash=str(number-1)
            m.block_time.timestamp=original['blockTime']+offset;m.executed_transaction_count=count
            await handler(u,u.ByteSize(),NOW)
            u=pb.SubscribeUpdate(filters=['f']);u.slot.slot=number;u.slot.parent=number-1;u.slot.status=pb.SLOT_FINALIZED
            await handler(u,u.ByteSize(),NOW)
        async def stream(channel,request,handler,family,session_stop):
            await status(handler,slot,first,index);await packet(first)
            await first_admitted.wait()
            for ordinal,signature in enumerate(required,index+1):await status(handler,slot,signature,ordinal)
            await finalized(handler,0,index+1+len(required))
            await packet(future);await future_waiting.wait()
            # A real finalized linked child makes the absent head eligible.
            await finalized(handler,1,0);native_ready.set()
            await head_installed.wait()
            await status(handler,slot+2,future,index);await finalized(handler,2,index+1)
            await future_admitted.wait()
            await StopEither(source.stop,session_stop).wait()
        source.stream=stream
        desired=[dict(family=f,address=PROGRAMS[f],scope=program_scope(f),priority=6,deadline=NOW+150,
            lower_slot=0,rolling=True) for f in ('pump','pumpswap')]
        size=len(str(original['meta']['logMessages']).encode());bound=size+size//2
        task=None
        with patch('meme_machine.solana_selective_source.connect',lambda *args,**kw:Connection()), \
                patch('meme_machine.solana_selective_source.time.time',side_effect=lambda:wall[0]), \
                patch('meme_machine.solana_selective_source.wait_candidate_log_space',pressure), \
                patch('meme_machine.solana_selective_source.MAX_PENDING_BYTES',bound), \
                patch('meme_machine.solana_candidate_join.MAX_PENDING_BYTES',bound), \
                patch.object(CandidateTransactionJoin,'begin_required_log_read',begin_read), \
                patch.object(CandidateTransactionJoin,'feed_log',feed_log), \
                patch.object(CandidateTransactionJoin,'complete_required_log',install_log):
            task=asyncio.create_task(source.live(None,desired,local_stop))
            try:
                await asyncio.wait_for(entered[blocked].wait(),2)
                await asyncio.wait_for(native_ready.wait(),2)
                if blocked in ('receipt','join_install'):await asyncio.wait_for(all_receipt_attempts.wait(),2)
                if blocked=='join_install':await asyncio.wait_for(all_receipts.wait(),2)
                join=join_box[0]
                self.assertGreater(join.early_log_bytes,bound//2)
                self.assertIn((slot,first),join.early_logs)
                self.assertFalse(future_admitted.is_set());self.assertFalse(head_installed.is_set())
                self.assertEqual(join.pending[slot]['missing_logs'],set(required))
                self.assertEqual(set(join.required_log_reads),{(slot,signature) for signature in required})
                for signature in required:
                    self.assertIs(join.required_log_reads[slot,signature],read_contexts[signature])
                self.assertEqual(installed,[]);self.assertEqual(joined,[])
                self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM rolling_economic_events').fetchone()[0],0)
                self.assertEqual(source.pipeline_metrics['log_repair:rolling']['supplements_authenticated'],0)
                self.assertEqual(accounting(),int(blocked in ('receipt','join_install')))
                self.assertEqual(len(receipts()),len(required) if blocked=='join_install' else 0)
                self.assertEqual(physical_return,[] if blocked=='transport' else [NOW+10])
                self.assertTrue(any(row['phase']=='LOG_BUFFER_WAIT' for row in source.handlers.records.values()))
                wall[0]=NOW+20
                if blocked=='transport':transport_release.set()
                else:gates[blocked].set()
                await asyncio.wait_for(head_installed.wait(),2)
                await asyncio.wait_for(future_admitted.wait(),2)
                local_stop.set();await asyncio.wait_for(task,3)
            finally:
                transport_release.set()
                for gate in gates.values():gate.set()
                local_stop.set()
                if task is not None and not task.done():task.cancel()
                if task is not None:await asyncio.gather(task,return_exceptions=True)
        expected_available=NOW+20 if blocked=='delivery' else NOW+10
        self.assertEqual(available,[expected_available]*len(required))
        self.assertEqual([row['http_result_available_at'] for row in receipts()],available)
        for signature in required:
            self.assertEqual(self.history.db.execute("SELECT min(first_seen) FROM canonical_evidence "
                "WHERE kind='event' AND signature=?",(signature,)).fetchone()[0],expected_available)
        self.assertEqual(physical,[tuple(required)]);self.assertEqual(set(installed),set(required))
        self.assertEqual(joined,[slot,slot+1,slot+2]);self.assertEqual(join_box[0].pending,{})
        self.assertEqual(join_box[0].required_log_reads,{})
        self.assertEqual((join_box[0].pending_bytes,join_box[0].early_log_bytes),(0,0))
        self.assertEqual(source.drain_snapshot()['queues']['rolling'],dict(accepted=3,committed=3,pending=0))
        self.assertEqual(source.drain_snapshot()['pending_handlers'],0)
        self.assertEqual(source.source_drain['unpreserved_sessions'],0)
        expected=set()
        for ordinal,signature in enumerate([first]+required):
            tx=copy.deepcopy(transactions[signature]);tx['transactionIndex']=index+ordinal
            expected.update(row.identity for row in economic_records('pump',PROGRAMS['pump'],tx,
                endpoint_identity='a'*64,seen=NOW,source='alchemy_finalized_stream'))
        expected.update(row.identity for row in economic_records('pump',PROGRAMS['pump'],transactions[future],
            endpoint_identity='a'*64,seen=NOW,source='alchemy_finalized_stream'))
        self.assertEqual({row[0] for row in self.history.db.execute('SELECT identity FROM rolling_economic_events')},expected)
        return SimpleNamespace(trace=trace,physical_return=physical_return,available=available)

    async def test_head_repair_transport_wait_retains_exact_owner_while_ws_is_pressured(self):
        await self.repair_stage_barrier('transport')

    async def test_head_repair_delivery_accounting_wait_precedes_reported_http_availability(self):
        result=await self.repair_stage_barrier('delivery')
        self.assertEqual(result.physical_return,[NOW+10]);self.assertEqual(result.available,[NOW+20])

    async def test_head_repair_receipt_admission_wait_cannot_publish_join_or_economics(self):
        await self.repair_stage_barrier('receipt')

    async def test_head_repair_durable_receipt_return_wait_retains_owner_before_join_install(self):
        await self.repair_stage_barrier('join_install')

    async def test_batched_head_repair_uses_same_delivery_receipt_install_stage_contract(self):
        result=await self.repair_stage_barrier('delivery',batch=True)
        self.assertEqual(result.physical_return,[NOW+10]);self.assertEqual(result.available,[NOW+20,NOW+20])

    async def native_head_live(self, *, truncated=False, later_truncated=0, exhaust=False,
            complete_ws=False, selection_ws=False, cancel=False, invalid_response=None,
            lookahead=None,future_capacity=False,repeated_cancel=False):
        """Actual live native head, with independently controlled accepted HTTP/owner work."""
        import based58
        import time
        from contextlib import nullcontext
        from meme_machine.solana_candidate_join import MAX_PENDING_SLOTS
        source=self.source;source.batched=True
        self.entered.clear();self.release.clear()
        original=copy.deepcopy(FIXTURE['pump'][0]);slot=original['slot'];index=original['transactionIndex']
        signature=original['transaction']['signatures'][0]
        addresses={PROGRAMS[f]:program_scope(f) for f in ('pump','pumpswap')}
        packets=asyncio.Queue();http_entered=asyncio.Event();http_release=asyncio.Event()
        batch_selected=asyncio.Event();batch_release=asyncio.Event();native_create_task=asyncio.create_task
        head_committed=asyncio.Event();published=asyncio.Event();tail_published=asyncio.Event();partial_progress=asyncio.Event()
        later_http=asyncio.Event();receipt_entered=asyncio.Event();receipt_release=asyncio.Event()
        authenticated=asyncio.Event();authenticated_count=[0];first_receipt=[True];joined_slots=[]
        physical=[];responses=[];ws_seen=[];partials=[0];published_slots=[];transactions={signature:original}
        first_owner=[True];failure=None
        partial=original['meta']['logMessages'][:4]+['Log truncated']
        def observe(kind,values):
            if kind=='joined_frame':joined_slots.append(values['slot'])
            if kind=='log_repair' and values.get('stage')=='supplements_authenticated':
                authenticated_count[0]+=1;authenticated.set()
            if kind=='log_repair' and values.get('stage')=='deferred':
                partials[0]+=1;partial_progress.set()
            if kind=='delivery' and values.get('family')=='candidate_logs':
                value=json.loads(values['raw'])
                event=value.get('params',{}).get('result',{}).get('value',{})
                if event.get('signature')==signature and event.get('logs')==original['meta']['logMessages']:
                    ws_seen.append(values['seen'])
        source.observer=observe
        async def work(fn,priority=2,**options):
            if (lookahead=='receipt' or invalid_response=='post_receipt_conflict') and first_receipt[0] and 'native_stream_log_supplement' in fn.__code__.co_consts:
                first_receipt[0]=False;answer=fn(self.state);receipt_entered.set()
                await receipt_release.wait();return answer
            if options.get('component')=='candidate' and first_owner[0]:
                first_owner[0]=False;self.entered.set();await self.release.wait()
                answer=fn(self.state);head_committed.set();return answer
            return fn(self.state)
        async def rpc(method,*args):
            if method!='getTransaction':
                self.assertEqual(method,'getSlot');return slot-1
            self.assertEqual(args[0][1],dict(commitment='finalized',encoding='json',maxSupportedTransactionVersion=1))
            self.assertEqual(args[1:],('rolling_recovery_missing_logs',2))
            requested=args[0][0];physical.append(requested);http_entered.set()
            if requested!=signature:later_http.set()
            await http_release.wait()
            bad=invalid_response if not lookahead or requested==signature else None
            if bad=='null':
                responses.append(time.time());return None
            fetched=copy.deepcopy(transactions[requested]);fetched.pop('transactionIndex',None)
            if bad=='identity':fetched['slot']+=1
            elif bad=='truncated':fetched['meta']['logMessages']=partial
            elif bad=='post_receipt_conflict':fetched['meta']['logMessages'][0]='different provider content'
            responses.append(time.time())
            return fetched
        source.work=work;source.measured_rpc=rpc
        async def log_batch(signatures,priority=2):
            return await asyncio.gather(*(rpc('getTransaction',[number,dict(commitment='finalized',
                encoding='json',maxSupportedTransactionVersion=1)],'rolling_recovery_missing_logs',priority)
                for number in signatures))
        source.measured_log_batch=log_batch
        def create_task(coroutine,*args,**kwargs):
            if getattr(getattr(coroutine,'cr_code',None),'co_name',None)!='log_batch':
                return native_create_task(coroutine,*args,**kwargs)
            started=[False]
            async def held_batch():
                try:
                    batch_selected.set();await batch_release.wait()
                    started[0]=True
                    return await coroutine
                finally:
                    if not started[0]:coroutine.close()
            task=native_create_task(held_batch(),*args,**kwargs)
            # A task canceled before its wrapper first runs cannot execute its
            # finally. Close the still-unstarted original coroutine there too.
            task.add_done_callback(lambda done:coroutine.close() if not started[0] else None)
            return task
        async def packet(number,logs):
            item=transactions[number]
            await packets.put(json.dumps(dict(params=dict(subscription=11,result=dict(context=dict(slot=item['slot']),
                value=dict(err=None,signature=number,logs=logs))))))
        async def partial_packet(number):
            target=partials[0]+1;await packet(number,partial)
            while partials[0]<target:
                partial_progress.clear()
                if partials[0]>=target:break
                await partial_progress.wait()
        class Socket:
            def __init__(socket):socket.acks=asyncio.Queue();socket.frontiers=iter((11,12))
            async def send(socket,raw):
                request=json.loads(raw);await socket.acks.put(json.dumps(dict(id=request['id'],result=request['id']+10)))
            async def recv(socket):
                if not socket.acks.empty():return await socket.acks.get()
                frontier=next(socket.frontiers,None)
                if frontier is not None:
                    return json.dumps(dict(params=dict(subscription=frontier,result=dict(context=dict(slot=slot-1),
                        value=dict(err={'InstructionError':[0,0]},signature='failed',logs=[])))))
                return await packets.get()
        class Connection:
            async def __aenter__(self):return Socket()
            async def __aexit__(self,*args):pass
        async def native_slot(handler,offset,*,economic=False):
            number=slot+offset
            if economic:
                item=copy.deepcopy(original);item['slot']=number;item['blockTime']=original['blockTime']+offset
                if offset:item['transaction']['signatures']=[based58.b58encode(bytes([offset+1])*64).decode()]
                sig=item['transaction']['signatures'][0];transactions[sig]=item
                if offset or truncated:await partial_packet(sig)
                u=pb.SubscribeUpdate(filters=[scope_labels(addresses)[program_scope('pump')]])
                u.transaction_status.slot=number;u.transaction_status.index=index
                u.transaction_status.signature=based58.b58decode(sig.encode())
                await handler(u,u.ByteSize(),NOW)
            u=pb.SubscribeUpdate(filters=['b']);m=u.block_meta;m.slot=number;m.parent_slot=number-1
            m.blockhash=str(number);m.parent_blockhash=str(number-1);m.block_time.timestamp=original['blockTime']+offset
            m.executed_transaction_count=index+1 if economic else 0
            await handler(u,u.ByteSize(),NOW)
            u=pb.SubscribeUpdate(filters=['f']);u.slot.slot=number;u.slot.parent=number-1;u.slot.status=pb.SLOT_FINALIZED
            await handler(u,u.ByteSize(),NOW);published_slots.append(number)
            await asyncio.sleep(0)
        async def stream(channel,request,handler,family,local_stop):
            await native_slot(handler,0,economic=True)
            # An absent live field becomes eligible only with its independently
            # finalized linked successor; the HTTP response grants no finality.
            count=MAX_PENDING_SLOTS-1 if exhaust else max(1,later_truncated)
            for offset in range(1,count+1):
                if lookahead=='receipt' and offset==2:await receipt_entered.wait()
                await native_slot(handler,offset,economic=offset<=later_truncated)
            if lookahead:await native_slot(handler,count+1)
            published.set()
            if exhaust:
                await head_committed.wait()
                for offset in (MAX_PENDING_SLOTS,MAX_PENDING_SLOTS+1):await native_slot(handler,offset)
            tail_published.set()
            await local_stop.wait()
        source.stream=stream
        desired=[dict(family=f,address=PROGRAMS[f],scope=program_scope(f),priority=6,deadline=NOW+150,
            lower_slot=0,rolling=True) for f in ('pump','pumpswap')]
        local_stop=asyncio.Event()
        from meme_machine.solana_candidate_join import CandidateTransactionJoin
        can_fit=CandidateTransactionJoin.required_log_can_fit
        def capacity(join,number,sig,logs):
            return can_fit(join,number,sig,logs) if number==slot else False
        with patch('meme_machine.solana_selective_source.connect',lambda *args,**kw:Connection()), \
                patch.object(CandidateTransactionJoin,'required_log_can_fit',capacity) if future_capacity else nullcontext(), \
                patch('meme_machine.solana_selective_source.asyncio.create_task',create_task) if selection_ws else nullcontext():
            task=asyncio.create_task(source.live(None,desired,local_stop))
            try:
                if selection_ws:
                    await asyncio.wait_for(batch_selected.wait(),2)
                    self.assertEqual(physical,[])
                    await packet(signature,original['meta']['logMessages'])
                    await asyncio.wait_for(self.entered.wait(),2)
                    batch_release.set()
                await asyncio.wait_for(http_entered.wait(),2)
                if lookahead=='receipt':
                    http_release.set();await asyncio.wait_for(receipt_entered.wait(),2)
                if lookahead:await asyncio.wait_for(later_http.wait(),2)
                await asyncio.wait_for(published.wait(),2)
                self.assertEqual(physical[0],signature)
                if later_truncated:
                    self.assertLessEqual(len(physical),7)
                    self.assertEqual(len(physical),len(set(physical)))
                else:self.assertEqual(physical,[signature])
                if complete_ws:
                    await packet(signature,original['meta']['logMessages'])
                    await asyncio.wait_for(self.entered.wait(),2)
                if cancel:
                    task.cancel();await asyncio.sleep(0)
                    self.assertFalse(task.done())
                    if repeated_cancel:
                        original_deadline=source.shutdown_deadline(task)
                        source.session_deadlines[task]=original_deadline
                        task.cancel();await asyncio.sleep(0)
                        self.assertFalse(task.done());self.assertEqual(source.shutdown_deadline(task),original_deadline)
                http_release.set()
                if invalid_response=='post_receipt_conflict':
                    await asyncio.wait_for(receipt_entered.wait(),2)
                    await packet(signature,original['meta']['logMessages'])
                    await asyncio.wait_for(self.entered.wait(),2);self.release.set()
                receipt_release.set()
                if invalid_response is not None:
                    reason={'truncated':'candidate_stream_log_supplement_incomplete',
                        'identity':'candidate_stream_log_supplement_identity_unverified',
                        'post_receipt_conflict':'candidate_stream_log_supplement_identity_unverified',
                        'null':'candidate_required_content_missing'}[invalid_response]
                    with self.assertRaisesRegex(EvidenceUnavailable,reason) as refused:await asyncio.wait_for(task,3)
                    failure=refused.exception
                    if invalid_response!='post_receipt_conflict':self.assertFalse(self.entered.is_set())
                else:
                    await asyncio.wait_for(self.entered.wait(),2)
                    self.assertFalse(task.done());self.release.set()
                    if lookahead:
                        while authenticated_count[0]<later_truncated+1:
                            authenticated.clear()
                            if authenticated_count[0]>=later_truncated+1:break
                            await asyncio.wait_for(authenticated.wait(),2)
                    if exhaust:await asyncio.wait_for(tail_published.wait(),3)
                    if not cancel:local_stop.set()
                    if cancel:
                        with self.assertRaises(asyncio.CancelledError):await asyncio.wait_for(task,3)
                    else:await asyncio.wait_for(task,3)
            finally:
                batch_release.set();http_release.set();receipt_release.set();self.release.set();local_stop.set()
                if not task.done():task.cancel()
                await asyncio.gather(task,return_exceptions=True)
        return SimpleNamespace(slot=slot,signature=signature,physical=physical,responses=responses,ws_seen=ws_seen,
            published_slots=published_slots,head=original,failure=failure,joined_slots=joined_slots)

    async def test_absent_native_head_completes_before_original_pending_slot_bound(self):
        result=await self.native_head_live(exhaust=True)
        self.assertEqual(len(result.physical),1)
        self.assertGreater(len(result.published_slots),256)
        self.assertEqual(self.source.drain_snapshot()['queues']['rolling']['pending'],0)
        available=self.history.db.execute("SELECT min(first_seen) FROM canonical_evidence WHERE signature=? AND kind='event'",(result.signature,)).fetchone()[0]
        self.assertGreaterEqual(available,result.responses[0])
        receipt=json.loads(self.history.db.execute("SELECT body FROM acquisition_observations WHERE kind='native_stream_log_supplement'").fetchone()[0])
        self.assertEqual(receipt['method'],'getTransaction')
        self.assertEqual(receipt['completion_kind'],'native_required_log')
        self.assertEqual(receipt['native_witness']['slot'],result.slot)
        self.assertTrue(receipt['native_order_preserved']);self.assertFalse(receipt['truncated_logs_used_as_complete'])

    async def test_truncated_native_head_precedes_later_truncated_population(self):
        result=await self.native_head_live(truncated=True,later_truncated=12)
        self.assertEqual(result.physical[0],result.signature)
        self.assertEqual(len(result.physical),len(set(result.physical)))
        self.assertLessEqual(len(result.physical),13)
        self.assertEqual(self.source.drain_snapshot()['queues']['rolling']['pending'],0)
        self.assertGreater(self.history.db.execute('SELECT COUNT(*) FROM rolling_economic_events').fetchone()[0],0)
        self.assertEqual(self.source.source_drain['unpreserved_sessions'],0)

    async def test_complete_ws_during_native_head_http_keeps_one_economic_commit_and_original_availability(self):
        from meme_machine.solana_selective_history import economic_records
        result=await self.native_head_live(complete_ws=True)
        self.assertEqual(result.physical,[result.signature])
        self.assertEqual(self.history.db.execute("SELECT COUNT(*) FROM acquisition_observations WHERE kind='native_stream_log_supplement'").fetchone()[0],1)
        expected={row.identity for row in economic_records('pump',PROGRAMS['pump'],result.head,
            endpoint_identity='a'*64,seen=NOW,source='alchemy_finalized_stream')}
        self.assertTrue(expected)
        self.assertEqual({row[0] for row in self.history.db.execute('SELECT identity FROM rolling_economic_events')},expected)
        available=self.history.db.execute("SELECT min(first_seen) FROM canonical_evidence WHERE signature=? AND kind='event'",(result.signature,)).fetchone()[0]
        self.assertEqual(available,result.ws_seen[0]);self.assertLessEqual(available,result.responses[0])

    async def test_cancel_joins_accepted_native_head_http_and_blocked_ordered_owner(self):
        result=await self.native_head_live(cancel=True)
        self.assertEqual(result.physical,[result.signature])
        self.assertEqual(self.source.drain_snapshot()['queues']['rolling']['pending'],0)
        self.assertGreater(self.history.db.execute('SELECT COUNT(*) FROM rolling_economic_events').fetchone()[0],0)
        self.assertEqual(self.source.source_drain['unpreserved_sessions'],0)

    async def test_complete_ws_before_selected_native_head_batch_starts_keeps_accepted_read_idempotent(self):
        from meme_machine.solana_selective_history import economic_records
        result=await self.native_head_live(selection_ws=True)
        self.assertEqual(result.physical,[result.signature])
        self.assertEqual(self.history.db.execute("SELECT COUNT(*) FROM acquisition_observations WHERE kind='native_stream_log_supplement'").fetchone()[0],1)
        self.assertEqual(self.history.db.execute("SELECT COUNT(*) FROM acquisition_observations WHERE kind='native_stream_log_supplement_failed'").fetchone()[0],0)
        expected={row.identity for row in economic_records('pump',PROGRAMS['pump'],result.head,
            endpoint_identity='a'*64,seen=NOW,source='alchemy_finalized_stream')}
        self.assertTrue(expected)
        self.assertEqual({row[0] for row in self.history.db.execute('SELECT identity FROM rolling_economic_events')},expected)
        available=self.history.db.execute("SELECT min(first_seen) FROM canonical_evidence WHERE signature=? AND kind='event'",(result.signature,)).fetchone()[0]
        self.assertEqual(available,result.ws_seen[0])
        self.assertEqual(self.source.drain_snapshot()['queues']['rolling']['pending'],0)

    async def test_invalid_native_head_http_identity_preserves_gap_without_economics_or_ack(self):
        result=await self.native_head_live(invalid_response='identity')
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM rolling_economic_events').fetchone()[0],0)
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM candidate_coverage').fetchone()[0],0)
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM candidate_checkpoints').fetchone()[0],0)
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM candidate_history_outbox').fetchone()[0],0)
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM candidate_gaps WHERE lo=? AND hi IS NULL',(result.slot,)).fetchone()[0],2)

    async def test_repeated_native_head_http_truncation_preserves_gap_without_economics_or_ack(self):
        result=await self.native_head_live(invalid_response='truncated')
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM rolling_economic_events').fetchone()[0],0)
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM candidate_coverage').fetchone()[0],0)
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM candidate_checkpoints').fetchone()[0],0)
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM candidate_history_outbox').fetchone()[0],0)
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM candidate_gaps WHERE lo=? AND hi IS NULL',(result.slot,)).fetchone()[0],2)

    async def test_null_native_head_http_preserves_gap_and_remains_an_ordinary_bounded_retry(self):
        result=await self.native_head_live(invalid_response='null')
        self.assertEqual(result.physical,[result.signature])
        self.assertEqual(result.failure.args,('candidate_required_content_missing',))
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM rolling_economic_events').fetchone()[0],0)
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM candidate_coverage').fetchone()[0],0)
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM candidate_checkpoints').fetchone()[0],0)
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM candidate_history_outbox').fetchone()[0],0)
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM candidate_gaps WHERE lo=? AND hi IS NULL',(result.slot,)).fetchone()[0],2)
        self.assertEqual(self.history.db.execute("SELECT COUNT(*) FROM acquisition_observations WHERE kind IN ('native_stream_log_supplement','native_stream_log_supplement_failed')").fetchone()[0],0)
        attempts=[]
        async def retry(channel,desired,local_stop):
            attempts.append(desired)
            if len(attempts)==1:raise result.failure
            self.source.stop.set()
        with patch.object(self.source,'live',side_effect=retry) as live:
            await asyncio.wait_for(self.source.rolling_programs(None),3)
        self.assertEqual(live.call_count,2)
        self.assertEqual([body['reason'] for kind,body in self.source.pending_diagnostics if kind=='rolling_retry'],
            ['candidate_required_content_missing'])

    async def test_live_lookahead_fetches_linked_future_fields_while_first_http_is_blocked(self):
        result=await self.native_head_live(truncated=True,later_truncated=3,lookahead='http')
        self.assertEqual(len(result.physical),4);self.assertEqual(len(set(result.physical)),4)
        self.assertEqual(result.joined_slots,sorted(set(result.joined_slots)))
        self.assertEqual(result.joined_slots[:4],list(range(result.slot,result.slot+4)))
        self.assertEqual(self.source.pipeline_metrics['log_repair:rolling']['supplements_authenticated'],4)
        self.assertEqual(self.source.pipeline_metrics['log_repair:rolling']['supplements_failed'],0)
        self.assertEqual(self.source.drain_snapshot()['queues']['rolling']['pending'],0)
        from meme_machine.solana_selective_history import economic_records
        expected=set()
        for offset in range(4):
            tx=copy.deepcopy(result.head);tx['slot']+=offset;tx['blockTime']+=offset
            if offset:
                import based58
                tx['transaction']['signatures']=[based58.b58encode(bytes([offset+1])*64).decode()]
            expected.update(row.identity for row in economic_records('pump',PROGRAMS['pump'],tx,
                endpoint_identity='a'*64,seen=NOW,source='alchemy_finalized_stream'))
        self.assertEqual({row[0] for row in self.history.db.execute('SELECT identity FROM rolling_economic_events')},expected)
        self.assertEqual(self.history.db.execute("SELECT COUNT(*) FROM acquisition_observations WHERE kind='native_stream_log_supplement'").fetchone()[0],4)
        path=self.state.writer.path;self.state.writer.close();self.state,self.history=state_at(path)
        self.addCleanup(self.state.writer.close)
        self.assertEqual({row[0] for row in self.history.db.execute('SELECT identity FROM rolling_economic_events')},expected)
        self.assertEqual(self.history.db.execute("SELECT COUNT(*) FROM acquisition_observations WHERE kind='native_stream_log_supplement'").fetchone()[0],4)

    async def test_live_lookahead_fetch_admission_does_not_wait_for_first_owner_receipt_return(self):
        result=await self.native_head_live(truncated=True,later_truncated=3,lookahead='receipt')
        self.assertEqual(len(result.physical),4)
        self.assertEqual(result.joined_slots,sorted(set(result.joined_slots)))
        self.assertEqual(self.source.pipeline_metrics['log_repair:rolling']['supplements_authenticated'],4)
        self.assertEqual(self.source.drain_snapshot()['queues']['rolling']['pending'],0)
        self.assertEqual(self.source.source_drain['unpreserved_sessions'],0)

    async def test_first_null_error_stops_future_capacity_waits_and_keeps_actual_recovery_inputs(self):
        result=await self.native_head_live(truncated=False,later_truncated=3,lookahead='http',
            invalid_response='null',future_capacity=True)
        self.assertEqual(result.failure.args,('candidate_required_content_missing',))
        metric=self.source.pipeline_metrics['log_repair:rolling']
        self.assertEqual(metric['supplements_failed'],1);self.assertEqual(metric['supplements_authenticated'],0)
        receipts=[json.loads(row[0]) for row in self.history.db.execute(
            "SELECT body FROM acquisition_observations WHERE kind='native_stream_log_supplement'")]
        self.assertEqual(len(receipts),3)
        self.assertTrue(all(row['http_result_available_at']>0 for row in receipts))
        retained=[json.loads(row[0]) for row in self.history.db.execute(
            "SELECT body FROM acquisition_observations WHERE kind='selective_missing_field'")]
        self.assertEqual(sum(row.get('authenticated_content_retained') is True for row in retained),3)
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM rolling_economic_events').fetchone()[0],0)
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM candidate_gaps WHERE lo=? AND hi IS NULL',(result.slot,)).fetchone()[0],2)

    async def test_first_authenticated_identity_failure_is_not_replaced_by_callback_name_collision(self):
        result=await self.native_head_live(invalid_response='identity')
        self.assertEqual(result.failure.args,('candidate_stream_log_supplement_identity_unverified',))
        self.assertEqual(self.source.pipeline_metrics['log_repair:rolling']['supplements_failed'],1)
        self.assertEqual(self.history.db.execute("SELECT COUNT(*) FROM acquisition_observations WHERE kind='native_stream_log_supplement_failed'").fetchone()[0],1)
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM rolling_economic_events').fetchone()[0],0)

    async def test_repeated_coordinator_cancel_joins_parallel_accepted_results_on_original_deadline(self):
        result=await self.native_head_live(truncated=True,later_truncated=3,lookahead='http',
            cancel=True,repeated_cancel=True)
        self.assertEqual(len(result.physical),4)
        self.assertEqual(self.source.pipeline_metrics['log_repair:rolling']['supplements_authenticated'],4)
        self.assertEqual(self.source.pipeline_metrics['log_repair:rolling']['supplements_failed'],0)
        self.assertEqual(self.source.drain_snapshot()['queues']['rolling']['pending'],0)
        self.assertEqual(self.source.source_drain['unpreserved_sessions'],0)

    async def test_post_receipt_ws_conflict_counts_failed_and_preserves_durable_original_receipt(self):
        result=await self.native_head_live(invalid_response='post_receipt_conflict')
        self.assertEqual(result.failure.args,('candidate_stream_log_supplement_identity_unverified',))
        metric=self.source.pipeline_metrics['log_repair:rolling']
        self.assertEqual(metric['supplements_failed'],1);self.assertEqual(metric['supplements_authenticated'],0)
        self.assertEqual(self.history.db.execute("SELECT COUNT(*) FROM acquisition_observations WHERE kind='native_stream_log_supplement'").fetchone()[0],1)
        self.assertEqual(self.source.drain_snapshot()['queues']['rolling']['pending'],0)

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
        self.assertEqual(self.last_batch_sizes,[7])
        self.assertEqual(len(self.last_repair_calls),8);self.assertEqual(len(set(self.last_repair_calls)),8)
        metrics=self.source.pipeline_metrics['log_repair:rolling']
        self.assertEqual((metrics['repair_logical_calls'],metrics['supplements_authenticated'],metrics['supplements_failed']),(8,8,0))
        self.assertEqual(self.source.drain_snapshot()['queues']['rolling'],dict(accepted=1,committed=1,pending=0))
        self.assertEqual(self.history.db.execute("SELECT COUNT(*) FROM acquisition_observations WHERE kind='native_stream_log_supplement'").fetchone()[0],8)
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM candidate_coverage').fetchone()[0],0)

    async def test_cancel_during_multi_member_repair_waits_for_original_batch_and_ordered_owner(self):
        await self.actual_live(truncated=True,repair_members=8,cancel_repair=True)
        self.assertEqual(self.last_batch_sizes,[7])
        self.assertEqual(len(self.last_repair_calls),8);self.assertEqual(len(set(self.last_repair_calls)),8)
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


    async def test_completed_repair_payloads_are_released_before_siblings_and_replacement_batches_finish(self):
        import based58
        import gc
        import weakref

        # The whole provider envelope has no join-store authority. Completed
        # responses must disappear even while another member from their batch
        # still awaits its actual durable receipt's owner return.
        class EnvelopeMarker(dict):pass
        source=self.source;source.batched=True
        original=copy.deepcopy(FIXTURE['pump'][0]);slot=original['slot']
        total=28;transactions={}
        for number in range(total):
            item=copy.deepcopy(original)
            item['transaction']['signatures']=[based58.b58encode(bytes([number+1])*64).decode()]
            item.pop('transactionIndex',None)
            transactions[item['transaction']['signatures'][0]]=item
        signatures=list(transactions)
        addresses={PROGRAMS[f]:program_scope(f) for f in ('pump','pumpswap')}
        statuses_ready=asyncio.Event();socket_idle=asyncio.Event()
        owner_release=asyncio.Event();candidate_committed=asyncio.Event()
        local_stop=asyncio.Event();held=set();paused=set();batches=[]
        created=[];references={};live=weakref.WeakValueDictionary();peak_live=[0];completed=[0]

        def observe(kind,values):
            if kind=='log_repair' and values.get('stage')=='supplements_authenticated':
                completed[0]+=1
        source.observer=observe

        async def work(fn,priority=2,**options):
            before=self.history.db.execute('SELECT COALESCE(max(id),0) FROM acquisition_observations').fetchone()[0]
            answer=fn(self.state)
            # Real owner serialization stores bytes in SQLite. Retain only
            # extracted identity strings here, never a mocked observation body
            # or forensic response list that would manufacture this leak.
            rows=self.history.db.execute("SELECT kind,json_extract(body,'$.native_witness.signature') "
                'FROM acquisition_observations WHERE id>? ORDER BY id',(before,)).fetchall()
            for kind,signature in rows:
                if kind=='native_stream_log_supplement' and signature in held:
                    paused.add(signature)
                    await owner_release.wait()
            if options.get('component')=='candidate':candidate_committed.set()
            return answer

        async def rpc(method,*args):
            self.assertEqual(method,'getSlot')
            return slot-1

        async def batch(requested,priority=2):
            self.assertEqual(priority,2)
            self.assertTrue(requested)
            self.assertFalse(set(requested).intersection(created))
            batches.append(tuple(requested));held.add(requested[0])
            values=[]
            for signature in requested:
                value=copy.deepcopy(transactions[signature])
                # Keep the production authenticator's exact dict requirement.
                # This ignored JSON object belongs only to its input envelope;
                # the join retains log arrays, never this lifetime probe.
                marker=EnvelopeMarker();value['_test_envelope_lifetime']=marker
                created.append(signature);references[signature]=weakref.ref(marker);live[signature]=marker
                values.append(value)
                gc.collect();peak_live[0]=max(peak_live[0],len(live))
            return values

        source.work=work;source.measured_rpc=rpc;source.measured_log_batch=batch
        partial=original['meta']['logMessages'][:4]+['Log truncated']
        class Socket:
            def __init__(socket):socket.acks=asyncio.Queue();socket.frontiers=iter((11,12));socket.sent=0
            async def send(socket,raw):
                request=json.loads(raw)
                await socket.acks.put(json.dumps(dict(id=request['id'],result=request['id']+10)))
            async def recv(socket):
                if not socket.acks.empty():return await socket.acks.get()
                frontier=next(socket.frontiers,None)
                if frontier is not None:
                    return json.dumps(dict(params=dict(subscription=frontier,result=dict(context=dict(slot=slot-1),
                        value=dict(err={'InstructionError':[0,0]},signature='failed',logs=[])))))
                await statuses_ready.wait()
                if socket.sent==total:
                    socket_idle.set();await asyncio.Event().wait()
                signature=signatures[socket.sent];socket.sent+=1
                return json.dumps(dict(params=dict(subscription=11,result=dict(context=dict(slot=slot),
                    value=dict(err=None,signature=signature,logs=partial)))))
        class Connection:
            async def __aenter__(self):return Socket()
            async def __aexit__(self,*args):pass
        async def stream(channel,request,handler,family,stop):
            for index,signature in enumerate(signatures):
                u=pb.SubscribeUpdate(filters=[scope_labels(addresses)[program_scope('pump')]])
                u.transaction_status.slot=slot;u.transaction_status.index=index
                u.transaction_status.signature=based58.b58decode(signature.encode())
                await handler(u,u.ByteSize(),NOW)
            u=pb.SubscribeUpdate(filters=['b']);m=u.block_meta;m.slot=slot;m.parent_slot=slot-1
            m.blockhash=str(slot);m.parent_blockhash=str(slot-1);m.block_time.timestamp=original['blockTime']
            m.executed_transaction_count=total
            await handler(u,u.ByteSize(),NOW)
            statuses_ready.set();await socket_idle.wait()
            u=pb.SubscribeUpdate(filters=['f']);u.slot.slot=slot;u.slot.parent=slot-1;u.slot.status=pb.SLOT_FINALIZED
            await handler(u,u.ByteSize(),NOW)
            await stop.wait()
        source.stream=stream
        desired=[dict(family=f,address=PROGRAMS[f],scope=program_scope(f),priority=6,
            deadline=NOW+150,lower_slot=0,rolling=True) for f in ('pump','pumpswap')]

        async def progress(predicate):
            while not predicate():
                if task.done():
                    task.result();self.fail('live repair stopped before payload-lifetime checkpoint')
                await asyncio.sleep(.005)

        with patch('meme_machine.solana_selective_source.connect',lambda *args,**kw:Connection()):
            task=asyncio.create_task(source.live(None,desired,local_stop))
            try:
                await asyncio.wait_for(progress(lambda:len(created)==total and len(paused)==len(batches)
                    and completed[0]==total-len(paused)),3)
                self.assertGreaterEqual(len(batches),3)
                self.assertFalse(owner_release.is_set());self.assertFalse(candidate_committed.is_set())
                self.assertEqual(len(paused),len(batches))
                gc.collect()
                self.assertLessEqual(peak_live[0],8)
                self.assertEqual(set(live),paused)
                self.assertTrue(all(reference() is None for signature,reference in references.items()
                    if signature not in paused))
                receipts=self.history.db.execute("SELECT count(*) FROM acquisition_observations "
                    "WHERE kind='native_stream_log_supplement'").fetchone()[0]
                self.assertEqual(receipts,total)
                owner_release.set()
                await asyncio.wait_for(candidate_committed.wait(),3)
                local_stop.set();await asyncio.wait_for(task,3)
                gc.collect()
                self.assertEqual(len(live),0)
                self.assertTrue(all(reference() is None for reference in references.values()))
                self.assertEqual(source.drain_snapshot()['queues']['rolling'],dict(accepted=1,committed=1,pending=0))
            finally:
                owner_release.set();local_stop.set()
                if not task.done():task.cancel()
                await asyncio.gather(task,return_exceptions=True)


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
