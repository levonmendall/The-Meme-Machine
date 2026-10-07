"""Active Model B startup proofs; no legacy producer or market I/O."""
import asyncio
from contextlib import closing
import os,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tests.test_solana_closure import state_at,NOW
from meme_machine.solana_evidence_plane import EvidenceUnavailable,IntervalProof,digest
from meme_machine.solana_rolling_history import program_scope
from meme_machine.solana_selective_runtime import CONTROL
from meme_machine.solana_prewarm_startup import PHASES,candidate_release
from meme_machine.runtime.candidate_history import CandidateHistory,CandidateDeadlineMissed


def proof(scope,lo,hi,at=NOW):
    return IntervalProof(scope,lo,hi,'alchemy_finalized_stream','a'*64,
        dict(finalized=True,complete=True,scope=scope,lower_slot=lo,upper_slot=hi,
             lineage_hash=digest([scope,lo,hi])),at)


def seal(history,lo,hi):
    history.writer.ingest([],proof=proof(CONTROL,lo,hi,history.clock()))
    for family in ('pump','pumpswap'):
        history.lifecycle.defer_proof(proof(program_scope(family),lo,hi,history.clock()))
    history.lifecycle.publish()


async def quiet_model_b(work,stop):
    """Offline Model B fixture for shared maintenance, never old block intake."""
    from meme_machine.solana_selective_source import install
    def boot(state):
        h=install(state);h.startup.begin()
        for family in ('pump','pumpswap'):h.startup.feed_ack(family,100,100)
        h.startup.native(('pump','pumpswap'));seal(h,100,100);h.startup.advance()
    await work(boot,0)
    await stop.wait()


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'canonical.sqlite'
        self.now=[NOW];self.state,self.h=state_at(self.path,lambda:self.now[0])
    def tearDown(self):self.state.writer.close();self.tmp.cleanup()
    def begin(self):
        self.h.startup.begin()
        for family in ('pump','pumpswap'):self.h.startup.feed_ack(family,100,101)
        self.h.startup.native(('pump','pumpswap'))
    def test_missing_startup_state_does_not_authorize_consumer_release(self):
        self.assertFalse(candidate_release(self.path))
        self.assertFalse(candidate_release(Path(self.tmp.name)/'unavailable.sqlite'))
    def test_skipped_initial_slot_requires_an_actual_finalized_parent_boundary(self):
        from meme_machine.solana_selective_source import commit_candidates
        from meme_machine.solana_candidate_join import YellowstoneTransactionFrame
        from meme_machine.solana_selective_history import PROGRAMS
        from meme_machine.yellowstone import geyser_pb2 as pb
        addresses={PROGRAMS[f]:program_scope(f) for f in ('pump','pumpswap')}
        for parent in (100,99):
            u=pb.SubscribeUpdate();b=u.block;b.slot=102;b.parent_slot=parent;b.blockhash='102';b.parent_blockhash=str(parent);b.block_time.timestamp=int(NOW)
            frame=YellowstoneTransactionFrame(u,10,NOW,replay_from_slot=100)
            if parent==99:self.h.db.execute('DELETE FROM candidate_blocks')
            commit_candidates(self.state,frame,addresses,str(parent))
            self.assertEqual(self.h.lifecycle.missing(program_scope('pump'),100,101),[] if parent==99 else [(100,101)])
    def test_exact_replayed_last_receipt_joins_new_session_child_without_a_gap(self):
        from meme_machine.solana_selective_source import commit_candidates
        from meme_machine.solana_candidate_join import YellowstoneTransactionFrame
        from meme_machine.solana_selective_history import PROGRAMS
        from meme_machine.yellowstone import geyser_pb2 as pb
        addresses={PROGRAMS[f]:program_scope(f) for f in ('pump','pumpswap')}
        def frame(slot):
            u=pb.SubscribeUpdate();b=u.block;b.slot=slot;b.parent_slot=slot-1;b.blockhash=str(slot);b.parent_blockhash=str(slot-1);b.block_time.timestamp=int(NOW)
            return YellowstoneTransactionFrame(u,10,NOW,replay_from_slot=100)
        commit_candidates(self.state,frame(100),addresses,'old')
        self.assertEqual(self.h.lifecycle.missing(program_scope('pump'),100,100),[(100,100)])
        self.state.writer.close();self.state,self.h=state_at(self.path,lambda:self.now[0])
        commit_candidates(self.state,frame(100),addresses,'new');commit_candidates(self.state,frame(101),addresses,'new')
        self.assertEqual(self.h.lifecycle.missing(program_scope('pump'),100,100),[])
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM acquisition_jobs').fetchone()[0],0)
    def test_clean_boot_releases_only_after_durable_contiguous_publication(self):
        self.begin();self.assertFalse(candidate_release(self.path))
        self.assertEqual(self.h.startup.advance()['phase'],'WAIT_FOR_DURABLE_PUBLICATION')
        self.h.writer.ingest([],proof=proof(CONTROL,100,101))
        self.h.lifecycle.defer_proof(proof(program_scope('pump'),100,101));self.h.lifecycle.publish()
        self.assertFalse(self.h.startup.advance()['released'])
        self.h.lifecycle.defer_proof(proof(program_scope('pumpswap'),100,101));self.h.lifecycle.publish()
        self.assertEqual(self.h.startup.advance()['phase'],'STEADY_STATE')
        self.assertTrue(candidate_release(self.path))
        self.assertEqual([r[0] for r in self.h.db.execute('SELECT phase FROM prewarm_startup_transitions ORDER BY sequence')],list(PHASES))
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM acquisition_jobs').fetchone()[0],0)
        self.assertFalse(self.h.startup.snapshot()['legacy_startup_active'])
    def test_ack_or_timeout_cannot_seal_an_open_upper_boundary(self):
        self.begin();seal(self.h,100,100);self.now[0]+=200
        self.assertFalse(self.h.startup.advance()['released'])
        self.assertEqual(self.h.lifecycle.missing(program_scope('pump'),100,101),[(101,101)])
    def test_unresolved_gap_prevents_release_until_real_overlap_proof(self):
        self.begin();seal(self.h,100,101);self.h.gap(program_scope('pump'),101,101,'disconnect')
        self.assertFalse(self.h.startup.advance()['released'])
        self.h.lifecycle.defer_proof(proof(program_scope('pump'),101,101));self.h.lifecycle.publish()
        self.assertTrue(self.h.startup.advance()['released'])
    def test_candidate_workers_wait_but_original_deadline_can_expire(self):
        self.begin()
        with patch.dict(os.environ,MM_SOLANA_EVIDENCE_PLANE_DB=str(self.path)),closing(CandidateHistory(self.h.lifecycle.path,clock=lambda:self.now[0])) as c:
            c.enqueue('meteora','pool',kind='warmup',ready_at=NOW,deadline=NOW+30,
                estimate_seconds=12,priority=30,identity='work',payload={})
            self.assertIsNone(c.claim('one'));self.now[0]+=31
            with self.assertRaises(CandidateDeadlineMissed):c.claim('two')
            self.assertEqual(c.db.execute('SELECT status,deadline FROM work').fetchone(),('deadline_missed',NOW+30))
    def test_fail_closed_never_releases_or_selects_legacy_startup(self):
        self.begin();self.h.startup.fail('unresolved_gap');seal(self.h,100,101)
        snap=self.h.startup.advance();self.assertEqual(snap['phase'],'FAIL_CLOSED')
        self.assertFalse(snap['released']);self.assertFalse(snap['legacy_fallback'])
    def test_restart_at_each_boundary_restores_frontier_without_deadline_reset(self):
        for phase in ('RESTORE_DURABLE_FRONTIER','START_ROLLING_FEEDS','RECOVERY_OVERLAP',
                'WAIT_FOR_DURABLE_PUBLICATION','RELEASE_CANDIDATE_CONSUMERS','STEADY_STATE'):
            with self.subTest(phase=phase):
                self.state.writer.close();self.path=Path(self.tmp.name)/(phase+'.sqlite')
                self.state,self.h=state_at(self.path,lambda:self.now[0])
                self.h.startup.begin()
                # Interruption after a committed transition, not a fabricated
                # complete interval. The previous frontier is already durable.
                self.h.lifecycle.checkpoint(program_scope('pump'),99,digest([99]))
                self.h.lifecycle.checkpoint(program_scope('pumpswap'),99,digest([99]))
                with closing(CandidateHistory(self.h.lifecycle.path,clock=lambda:self.now[0])) as c:
                    c.enqueue('meteora','pool',kind='warmup',ready_at=NOW,deadline=NOW+150,
                        estimate_seconds=12,priority=30,identity=phase,payload={})
                # Test the durable phase commit independently of sockets.
                with self.h.writer.transaction():
                    self.h.db.execute('UPDATE prewarm_startup SET phase=?,released=?',(phase,int(phase in ('RELEASE_CANDIDATE_CONSUMERS','STEADY_STATE'))))
                self.state.writer.close();self.state,self.h=state_at(self.path,lambda:self.now[0])
                restored=self.h.startup.begin();self.assertEqual(restored['restored_frontiers'],dict(pump=99,pumpswap=99))
                self.assertFalse(restored['released'])
                for f in ('pump','pumpswap'):self.h.startup.feed_ack(f,98,101)
                self.h.startup.native(('pump','pumpswap'));seal(self.h,98,101)
                self.assertTrue(self.h.startup.advance()['released'])
                self.h.lifecycle.repair([dict(family='pump',address='late',scope='candidate:pump:late',
                    lower_slot=98,priority=4,deadline=NOW+150)],101)
                with closing(CandidateHistory(self.h.lifecycle.path)) as c:
                    self.assertEqual(c.db.execute('SELECT deadline FROM work WHERE id=?',(phase,)).fetchone()[0],NOW+150)
                self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM rolling_economic_events').fetchone()[0],0)
    def test_true_late_discovery_fetches_only_missing_prefix(self):
        self.h.bind('pumpswap','pool');seal(self.h,105,110)
        m=self.h.rolling.prepare('pumpswap','pool',100,110,deadline=NOW+150,reason='LATE_DISCOVERY')
        self.assertEqual(m['missing_intervals'],[(100,104)])
        self.assertEqual(self.h.db.execute('SELECT lo,hi,deadline FROM acquisition_jobs').fetchall(),[(100,104,NOW+150)])
        self.assertEqual(self.h.db.execute('SELECT reason FROM backfill_reasons').fetchone()[0],'LATE_DISCOVERY')
    def test_unchanged_meteora_membership_has_stable_revision(self):
        self.h.observe('meteora','pool',slot=100,signature='',seen=NOW,fields=dict(wsol_pair_locator=True,activity=False))
        self.h.bind('meteora','pool')
        revision=self.h.db.execute('SELECT revision FROM prewarm_membership_revision').fetchone()[0]
        for i in range(100):
            self.h.observe('meteora','pool',slot=100+i,signature='',seen=NOW+i,fields=dict(wsol_pair_locator=True,activity=False))
            self.h.bind('meteora','pool')
        self.assertEqual(self.h.db.execute('SELECT revision FROM prewarm_membership_revision').fetchone()[0],revision)

    def test_checkpoint_prefix_repairs_only_proven_missing_slots_not_publication_tail(self):
        scope=self.h.bind('meteora','pool')
        with closing(CandidateHistory(self.h.lifecycle.path,clock=lambda:NOW)) as c:
            c.enqueue('meteora','pool',kind='warmup',ready_at=NOW,deadline=NOW+150,
                estimate_seconds=12,priority=30,identity='prefix',payload={})
            c.wait_for_history('prefix',scope,99,102,retry_at=NOW+120)
        self.assertEqual(self.h.rolling.repair_required_checkpoint_prefixes(),[])
        self.h.lifecycle.defer_proof(proof(scope,100,101));self.h.lifecycle.publish()
        self.h.rolling.repair_required_checkpoint_prefixes();self.h.rolling.repair_required_checkpoint_prefixes()
        self.assertEqual(self.h.db.execute('SELECT lo,hi,deadline FROM acquisition_jobs').fetchall(),[(99,99,NOW+150)])
        self.assertEqual(self.h.db.execute('SELECT reason FROM backfill_reasons').fetchone()[0],'CHECKPOINT_GAP')
        self.h.lifecycle.defer_proof(proof(scope,99,99));self.h.lifecycle.publish()
        self.assertEqual(self.h.rolling.repair_required_checkpoint_prefixes(),[])
        with closing(CandidateHistory(self.h.lifecycle.path,clock=lambda:NOW)) as c:self.assertIsNone(c.claim('one'))
        self.h.lifecycle.defer_proof(proof(scope,102,102));self.h.lifecycle.publish()
        with closing(CandidateHistory(self.h.lifecycle.path,clock=lambda:NOW)) as c:self.assertEqual(c.claim('one')['deadline'],NOW+150)


class StartupAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_last_websocket_log_can_complete_native_join_and_release_startup(self):
        import copy,json,based58
        from meme_machine.solana_selective_source import SelectiveSource
        from meme_machine.solana_selective_history import PROGRAMS
        from meme_machine.solana_candidate_join import scope_labels
        from meme_machine.yellowstone import geyser_pb2 as pb
        from tests.test_solana_selective_evidence import FIXTURE
        tx=copy.deepcopy(FIXTURE['pump'][0]);slot=tx['slot'];index=tx['transactionIndex']
        addresses={PROGRAMS[f]:program_scope(f) for f in ('pump','pumpswap')}
        with tempfile.TemporaryDirectory() as t:
            state,h=state_at(Path(t)/'canonical.sqlite');h.startup.begin()
            source=SelectiveSource(SimpleNamespace(credential='offline',stream_url='offline'),None)
            source.stop=asyncio.Event();statuses_ready=asyncio.Event();log_committed=asyncio.Event()
            async def work(fn,*a,**kw):
                result=fn(state)
                row=h.db.execute('SELECT COUNT(*) FROM rolling_economic_events').fetchone()[0]
                if row:log_committed.set()
                return result
            async def rpc(method,*args):self.assertEqual(method,'getSlot');return slot-1
            source.work=work;source.measured_rpc=rpc
            class Socket:
                def __init__(self):self.acks=asyncio.Queue();self.sent=False;self.frontiers=iter((11,12))
                async def send(self,raw):
                    r=json.loads(raw);await self.acks.put(json.dumps(dict(id=r['id'],result=r['id']+10)))
                async def recv(self):
                    if not self.acks.empty():return await self.acks.get()
                    subscription=next(self.frontiers,None)
                    if subscription is not None:
                        return json.dumps(dict(method='logsNotification',params=dict(subscription=subscription,result=dict(
                            context=dict(slot=slot-1),value=dict(err={'InstructionError':[0,0]},signature='failed',logs=[])))))
                    await statuses_ready.wait()
                    if self.sent:await asyncio.Event().wait()
                    self.sent=True
                    return json.dumps(dict(method='logsNotification',params=dict(subscription=11,result=dict(
                        context=dict(slot=slot),value=dict(err=None,signature=tx['transaction']['signatures'][0],logs=tx['meta']['logMessages'])))))
            class Connection:
                async def __aenter__(self):return Socket()
                async def __aexit__(self,*a):pass
            async def stream(channel,request,handler,*args):
                u=pb.SubscribeUpdate(filters=[scope_labels(addresses)[program_scope('pump')]])
                s=u.transaction_status;s.slot=slot;s.index=index;s.signature=based58.b58decode(tx['transaction']['signatures'][0].encode())
                await handler(u,u.ByteSize(),NOW)
                for at in (slot,slot+1):
                    u=pb.SubscribeUpdate(filters=['b']);m=u.block_meta;m.slot=at;m.parent_slot=at-1
                    m.blockhash=str(at);m.parent_blockhash=str(at-1);m.block_time.timestamp=tx['blockTime']
                    m.executed_transaction_count=index+1 if at==slot else 0
                    await handler(u,u.ByteSize(),NOW)
                    u=pb.SubscribeUpdate(filters=['f']);u.slot.slot=at;u.slot.parent=at-1;u.slot.status=pb.SLOT_FINALIZED
                    await handler(u,u.ByteSize(),NOW)
                    if at==slot:
                        statuses_ready.set();await log_committed.wait()
                        # This frame became ready on the log callback, not on
                        # the native callback above. Readiness must be durable.
                        self.assertTrue(all(r[0] is not None for r in h.db.execute('SELECT native_at FROM prewarm_startup_feeds')))
                source.stop.set()
            source.stream=stream
            desired=[dict(family=f,address=PROGRAMS[f],scope=program_scope(f),priority=6,deadline=NOW+150,lower_slot=0,rolling=True) for f in ('pump','pumpswap')]
            try:
                with patch('meme_machine.solana_selective_source.connect',lambda *a,**kw:Connection()):
                    await asyncio.wait_for(source.live(None,desired,asyncio.Event()),3)
                h.writer.ingest([],proof=proof(CONTROL,slot,slot+1));h.lifecycle.publish()
                self.assertTrue(h.startup.advance()['released'])
                self.assertEqual(h.db.execute('SELECT COUNT(*) FROM acquisition_jobs').fetchone()[0],0)
            finally:state.writer.close()
    async def test_shared_entrypoint_backpressure_includes_checkpoint_and_health(self):
        from meme_machine import solana_evidence_service as service
        from meme_machine.solana_evidence_control import PriorityOwner
        from tests.maintenance_production_harness import NativeCompletionPool
        from tests.evidence_ipc_harness import ipc_transport
        original_init=PriorityOwner.__init__;executed=[];stop=asyncio.Event()
        def bounded(owner,factory,**kw):return original_init(owner,factory,capacity=4,reserved=1)
        async def driver(work,stop):
            boot_done=asyncio.Event();boot_done.set();await quiet_model_b(work,boot_done)
            def command(n):
                def apply(state):time.sleep(.002);executed.append(n);return n
                return apply
            result=await asyncio.gather(*(work(command(n),2,label='source_commit') for n in range(32)))
            self.assertEqual(result,list(range(32)));stop.set()
        with tempfile.TemporaryDirectory() as t,ipc_transport(),patch.object(PriorityOwner,'__init__',bounded),patch('concurrent.futures.ProcessPoolExecutor',NativeCompletionPool):
            path=Path(t)/'canonical.sqlite'
            await asyncio.wait_for(service.serve(path,'https://solana-mainnet.g.alchemy.com/v2/offline-test',stop=stop,source_driver=driver),10)
            import sqlite3,json
            with closing(sqlite3.connect(path)) as db:
                ipc=json.loads(db.execute("SELECT value FROM service_health WHERE key='ipc'").fetchone()[0])
                metrics=json.loads(db.execute("SELECT value FROM service_health WHERE key='owner_scheduler'").fetchone()[0])
            self.assertGreater(metrics['admission_waited'],0)
            self.assertLessEqual(metrics['queue_peak'],3);self.assertEqual(metrics['queued'],0)
            self.assertEqual(sorted(executed),list(range(32)))
    async def test_archived_default_startup_is_not_available(self):
        from meme_machine.solana_evidence_service import serve
        with self.assertRaisesRegex(EvidenceUnavailable,'legacy_startup_archived_model_b_driver_required'):
            await serve('/unused','https://solana-mainnet.g.alchemy.com/v2/offline-test')
    async def test_actual_owner_backpressure_drains_every_unadmitted_command(self):
        from meme_machine.solana_evidence_control import PriorityOwner
        from meme_machine.solana_selective_source import source_work
        executed=[];observed=[];stop=asyncio.Event()
        owner=PriorityOwner(lambda:SimpleNamespace(close=lambda:None),capacity=4,reserved=1)
        await asyncio.wrap_future(owner.ready)
        async def work(fn,priority=2,**kw):return await asyncio.shield(asyncio.wrap_future(owner.submit(fn,priority=priority)))
        work=source_work(work,stop,lambda kind,**values:observed.append(values))
        def command(n):
            def apply(s):time.sleep(.005);executed.append(n);return n
            return apply
        try:
            results=await asyncio.gather(*(work(command(n),2) for n in range(24)))
            self.assertEqual(results,list(range(24)));self.assertEqual(sorted(executed),list(range(24)))
            self.assertEqual(owner.telemetry()['queued'],0);self.assertLessEqual(owner.telemetry()['queue_peak'],3)
            self.assertGreater(sum(r['retries'] for r in observed),0)
        finally:owner.close()
    async def test_membership_plan_coalesces_unchanged_state_before_owner_admission(self):
        from meme_machine.solana_selective_source import SelectiveSource
        with tempfile.TemporaryDirectory() as t:
            state,h=state_at(Path(t)/'canonical.sqlite');h.startup.begin()
            for f in ('pump','pumpswap'):h.startup.feed_ack(f,100,100)
            h.startup.native(('pump','pumpswap'));seal(h,100,100);h.startup.advance()
            h.observe('meteora','pool',slot=100,signature='',seen=NOW,fields=dict(wsol_pair_locator=True))
            source=SelectiveSource(SimpleNamespace(credential='offline'),None);source.stop=asyncio.Event()
            source.canonical_path=str(h.writer.path);plans=[];installs=[];events=[]
            async def work(fn,*a,**kw):plans.append(1);return fn(state)
            async def live(channel,desired,local_stop):installs.append(desired);await local_stop.wait()
            source.work=work;source.live=live;source.observer=lambda kind,values:events.append(kind)
            try:
                task=asyncio.create_task(source.live_manager(None));await asyncio.sleep(.82)
                source.stop.set();await task
                self.assertEqual(len(plans),1);self.assertEqual(len(installs),1)
                self.assertGreaterEqual(events.count('membership_suppressed'),2)
            finally:state.writer.close()

    async def test_provider_subscription_pressure_retries_same_durable_interest(self):
        from meme_machine.solana_selective_source import SelectiveSource
        with tempfile.TemporaryDirectory() as t:
            state,h=state_at(Path(t)/'canonical.sqlite');h.startup.begin()
            for f in ('pump','pumpswap'):h.startup.feed_ack(f,100,100)
            h.startup.native(('pump','pumpswap'));seal(h,100,100);h.startup.advance()
            h.observe('meteora','pool',slot=100,signature='',seen=NOW,fields=dict(wsol_pair_locator=True))
            h.lifecycle.promote('meteora','pool',deadline=NOW+150)
            source=SelectiveSource(SimpleNamespace(credential='offline'),None);source.stop=asyncio.Event()
            source.canonical_path=str(h.writer.path);attempts=[];resumed=asyncio.Event()
            async def work(fn,*a,**kw):return fn(state)
            async def live(channel,desired,local_stop):
                attempts.append(desired)
                if len(attempts)==1:raise EvidenceUnavailable('candidate_native_resource_exhausted')
                resumed.set();await local_stop.wait()
            source.work=work;source.live=live
            try:
                task=asyncio.create_task(source.live_manager(None))
                await asyncio.wait_for(resumed.wait(),3)
                source.stop.set();await task
                self.assertEqual(attempts[0],attempts[1])
                self.assertEqual(h.db.execute('SELECT deadline FROM candidate_lifecycle').fetchone()[0],NOW+150)
                self.assertIn('candidate_native_resource_exhausted',h.db.execute(
                    "SELECT body FROM acquisition_observations WHERE kind='subscription_retry'").fetchone()[0])
            finally:state.writer.close()

    async def test_native_subscription_write_error_uses_scoped_retry_status(self):
        import grpc
        from meme_machine.solana_selective_source import SelectiveSource
        from meme_machine.yellowstone import geyser_pb2 as pb
        class Call:
            cancelled=False
            async def write(self,request):
                raise grpc.aio.AioRpcError(grpc.StatusCode.RESOURCE_EXHAUSTED,(),(),details='offline pressure')
            def cancel(self):self.cancelled=True
        call=Call()
        channel=SimpleNamespace(stream_stream=lambda *a,**kw:lambda **options:call)
        source=SelectiveSource(SimpleNamespace(credential='offline'),None);source.stop=asyncio.Event()
        with self.assertRaisesRegex(EvidenceUnavailable,'^candidate_native_resource_exhausted$'):
            await source.stream(channel,pb.SubscribeRequest(),None,'candidate_live')
        self.assertTrue(call.cancelled)


if __name__=='__main__':unittest.main()
