"""Real private owner/support and original canonical/FULL input replay.

Unavailable root/unit/source-install acquisition is the existing fixture's
explicit premise. Anonymous kernel peer issuance, original all-four financial
replay, canonical storage, release proofs and native FULL history commits run.
The synthetic storage rows do not claim mainnet acquisition or full-market work.
"""
from contextlib import closing
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from meme_machine.operational import normal_boot as boot
from meme_machine.operational import normal_boot_record as wire
from meme_machine.operational import normal_pump_boot as pump
from meme_machine.operational import normal_source_boot as source
from tests import test_normal_boot_context as fixtures
from tests.test_solana_closure import NOW


def native_rows(first, count, *, available=NOW):
    from meme_machine.solana_evidence_plane import FinalizedRecord
    from meme_machine.solana_selective_history import PROGRAMS
    return [FinalizedRecord('storage-native:'+str(i),'program:pump',200+i,
        'storage-signature:'+str(i),PROGRAMS['pump'],('storage-mint',),int(NOW),
        dict(event=dict(mint='storage-mint',event_type='trade',market_time=int(NOW),
            native_buy=i,index=0),raw_lineage=dict(logs=['synthetic native storage fixture'],err=None)),
        'alchemy_finalized_stream','a'*64,float(available),transaction_index=0,event_index=0)
        for i in range(first,first+count)]


def initial_generation(cap, *, fresh=0):
    """Actual atomic registry/outbox producer, no source acquisition claim."""
    from meme_machine.operational.normal_source_registry import NativeSourceRegistry
    from meme_machine.solana_evidence_service import ServiceState
    from meme_machine.solana_provider_config import AlchemyEndpoint
    from meme_machine.solana_selective_source import install
    from meme_machine.solana_source_drain import HandlerLedger
    state=ServiceState(Path(cap.identity()['root'])/'shared/solana-evidence.sqlite',
        AlchemyEndpoint.parse('https://solana-mainnet.g.alchemy.com/v2/offline_fixture_only'))
    try:
        history=install(state);history.clock=lambda:NOW
        ledger=HandlerLedger(cap.generation);snapshot=ledger.snapshot()
        cap.begin(state,dict(state='RUNNING',terminal=False,source_pid=os.getpid(),run_identity=cap.generation,
            accepted_handlers=0,settled_handlers=0,pending_handlers=0,handler_accounting=snapshot,
            closed_sessions=0,pending_history=0,pending_proofs=0,unpreserved_sessions=0,
            all_accepted_committed=True,queues={name:dict(accepted=0,committed=0,pending=0)
                for name in ('control','scout','rolling','candidate')}))
        registry=NativeSourceRegistry(state,cap);history._normal_source_registry=registry
        if fresh:history.ingest(native_rows(100000,fresh))
    finally:state.close()


CHILD=r'''
import json,os,sys,time
from contextlib import closing
from types import SimpleNamespace
from unittest.mock import patch
from operational.tests import network_guard
network_guard()
from meme_machine.operational import normal_boot as boot,normal_pump_boot as pump,normal_source_boot as source
from tests.test_pump_current_input_native import initial_generation
fixture=json.loads(sys.stdin.readline());locator,record=fixture['locator'],fixture['record'];role=fixture['role']
module=source if role=='source' else pump
fields='MainPID='+str(record['supervisor']['pid'])+'\nInvocationID='+record['supervisor']['invocation_id']+'\nActiveState=active\n'
try:
    with patch.object(module,'_read_record',return_value=(locator,record)), \
         patch.object(module,'_clock_sha256',return_value='e'*64), \
         patch.object(boot,'_source_identity',return_value=(record['application_commit'],record['application_tree'])), \
         patch.object(module.subprocess,'run',return_value=SimpleNamespace(stdout=fields)):
        cap=(source.accept_source_launch if role=='source' else pump.accept_pump_owner_launch)(int(sys.argv[1]))
        if role=='source':
            initial_generation(cap,fresh=fixture.get('fresh',0))
            print(json.dumps({'generation':cap.generation,'identity_sha256':cap.identity_sha256}),flush=True)
            sys.stdin.readline()
        else:
            from meme_machine.runtime.candidate_history import CandidateHistory
            from meme_machine.runtime.pump_current_work import PumpCurrentWork,source_generation_projection
            from meme_machine.solana_evidence_plane import EvidenceReader
            from meme_machine.solana_selective_history import ConsumerReader
            from meme_machine.solana_selective_runtime import consume_pump_discovery
            from meme_machine.lanes.pump.runner import policy_hash
            from meme_machine.runtime.stop import Shutdown,requested
            from meme_machine.lanes.pump.solana_evidence_runtime import LocalPumpTape
            from meme_machine.lanes.pump.runner import _observed_creation
            from tests.test_solana_closure import NOW
            path=os.environ['MM_SOLANA_CANDIDATE_HISTORY_DB']
            with closing(CandidateHistory(path)) as history,closing(EvidenceReader(os.environ['MM_SOLANA_EVIDENCE_PLANE_DB'])) as original:
                reader=ConsumerReader(original)
                work=PumpCurrentWork(path,record['boot_eligibility']['epoch_id'],policy_hash())
                raw=original.db.execute("SELECT value FROM service_health WHERE key='source_drain_current_generation'").fetchone()[0]
                work.source_observation(source_generation_projection(json.loads(raw)))
                assert work.input_context is not None and not work.input_context_unavailable
                # A controlled virtual lease tests page/EOF correlation rather
                # than Cloud scheduling speed. Production keeps its25ms clock.
                if fixture.get('fixed_lease'):work.input_context.census.clock=lambda:0.
                plane=SimpleNamespace(reader=reader,_selective_reader=lambda:reader,clock=lambda:NOW)
                tape=LocalPumpTape(plane,native_work=work)
                def original_creation_branch(target,events):
                    missing=0
                    for event in events:
                        if _observed_creation(target,{},event['mint']) is None:
                            missing+=1
                            if target.native_work is not None:target.native_work.disposition(event,'MISSING_CREATION')
                        else:raise AssertionError('unexpected fixture creation')
                    if target.native_work is not None:target.native_work.finish()
                    return missing
                matched=None
                if fixture.get('matched'):
                    # Warm the original native history once, then compare the
                    # SAME idempotent canonical/history work on both sides.
                    # Both execute the actual LocalPumpTape creation attention
                    # and original missing-creation branch. This is not a full
                    # runner/Survivor/protection or provider-capacity benchmark.
                    plain=LocalPumpTape(plane);cursor=0
                    for _ in range(3):events,cursor=plain.events_since(cursor);original_creation_branch(plain,events)
                    cursor=0;turns=[];missing=0
                    for _ in range(3):
                        counts=dict(queries=0,frontier_queries=0,key_queries=0)
                        def query(sql):
                            counts['queries']+=1
                            counts['frontier_queries']+=int('source_generation_frontier' in sql)
                            counts['key_queries']+=int('INDEXED BY candidate_outbox_scope' in sql)
                        original.db.set_trace_callback(query)
                        start=time.perf_counter();cpu=time.thread_time()
                        events,cursor=plain.events_since(cursor)
                        original.db.set_trace_callback(None)
                        missing+=original_creation_branch(plain,events)
                        turns.append(dict(wall=time.perf_counter()-start,cpu=time.thread_time()-cpu,rows=len(events),**counts))
                    matched=dict(contract='WARM_NATIVE_DISCOVERY_FULL_AND_REAL_MISSING_CREATION_BRANCH_NOT_ALL_RUNNER',
                        plain=turns,plain_missing=missing,plain_cursor=cursor)
                views=[];sequence=0;physical=[];capture_cost=[]
                actual_capture=work.input_context.capture
                def measured_capture(*args,**kwargs):
                    started=time.perf_counter();cpu=time.thread_time()
                    try:return actual_capture(*args,**kwargs)
                    finally:capture_cost.append(dict(wall=time.perf_counter()-started,cpu=time.thread_time()-cpu))
                work.input_context.capture=measured_capture
                for command in fixture.get('commands',['consume','consume','consume']):
                    if command=='cancel':
                        requested.set()
                        try:tape.events_since(sequence)
                        except Shutdown:pass
                        else:raise AssertionError('native cancellation missing')
                        finally:requested.clear()
                        assert not original.db.in_transaction
                        views.append({'cancelled':True});continue
                    if command=='future':tape.plane.clock=lambda:NOW+100
                    if command=='missing_frontier':
                        import sqlite3
                        with closing(sqlite3.connect(original.path)) as db:
                            db.execute("DELETE FROM service_health WHERE key='source_generation_frontier'");db.commit()
                    if command=='foreign_frontier':
                        import sqlite3
                        with closing(sqlite3.connect(original.path)) as db:
                            raw=db.execute("SELECT value FROM service_health WHERE key='source_generation_frontier'").fetchone()[0]
                            changed=json.loads(raw);changed['generation']='f'*32
                            db.execute("UPDATE service_health SET value=? WHERE key='source_generation_frontier'",(json.dumps(changed),));db.commit()
                    if command=='failed_full':
                        import sqlite3
                        from meme_machine.runtime import candidate_history as module
                        opened=module.open_candidate_history
                        class FailedCommit:
                            def __init__(self,db):self.original=db
                            def __getattr__(self,name):return getattr(self.original,name)
                            def execute(self,sql,*args):
                                if sql=='COMMIT':raise sqlite3.OperationalError('private-native-full-commit-failed')
                                return self.original.execute(sql,*args)
                        def failed_open():
                            value=opened();value._history().db=FailedCommit(value.db);return value
                        with patch.object(module,'open_candidate_history',side_effect=failed_open):
                            try:tape.events_since(sequence)
                            except sqlite3.OperationalError as error:
                                assert str(error)=='private-native-full-commit-failed'
                            else:raise AssertionError('FULL commit did not fail')
                        assert not original.db.in_transaction
                        views.append(work.snapshot()['native_input_prefix']);continue
                    trace=[];original.db.set_trace_callback(trace.append)
                    started=time.perf_counter();cpu=time.thread_time()
                    events,sequence=tape.events_since(sequence)
                    physical.append(dict(wall=time.perf_counter()-started,cpu=time.thread_time()-cpu,
                        queries=len(trace),frontier_queries=sum('source_generation_frontier' in sql for sql in trace),
                        key_queries=sum('INDEXED BY candidate_outbox_scope' in sql for sql in trace),
                        retained=len(tape.candidate_history_rows)))
                    original.db.set_trace_callback(None)
                    original_creation_branch(tape,events)
                    views.append(work.snapshot()['native_input_prefix'])
                    physical[-1]['with_outcome_observation_wall']=time.perf_counter()-started
                    physical[-1]['with_outcome_observation_cpu']=time.thread_time()-cpu
                queued=history.db.execute("SELECT candidate,id,status FROM work WHERE candidate='old-queued' ORDER BY rowid").fetchall()
                print(json.dumps(dict(views=views,physical=physical,matched=matched,capture_cost=capture_cost,queued=queued,sequence=sequence,
                    internal_retained=work.input_context.prefixes.inherited['records'],
                    input_context_private=type(work.input_context.owner) is pump.NativePumpOwnerContext,
                    source_transaction=original.db.in_transaction,
                    retained=history.db.execute('SELECT count(*) FROM events WHERE identity LIKE \'pump-source:storage-native:%\'').fetchone()[0])),flush=True)
            sys.stdin.readline();cap.close()
except BaseException as error:
    import traceback;traceback.print_exc(file=sys.stderr)
    raise SystemExit(2)
'''


class CurrentPrivateInputTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.NativePrewriteReplayTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root=self.fixture.root;self.record=self.fixture.record;self.locator=self.fixture.locator
        self.enterContext(patch.object(source,'_ISSUED_CONTEXT',None))
        self.enterContext(patch.object(pump,'_ISSUED_CONTEXT',None))
        self.enterContext(patch.object(source,'_clock_sha256',return_value='e'*64))
        self.enterContext(patch.object(pump,'_clock_sha256',return_value='e'*64))

    def prepare(self,count,*,future=False,dangling=False,queued=False):
        from meme_machine.solana_selective_source import commit_control
        from meme_machine.solana_selective_history import PROGRAMS
        from meme_machine.solana_history_delivery import capture,deliver,acknowledge
        from meme_machine.runtime.candidate_history import CandidateHistory
        from tests.test_solana_closure import state_at
        from tests.test_candidate_commit_batches import frame
        # Quiet genuine source publication releases the unchanged gate. Large
        # storage rows below are not used to fabricate coverage or FULL ACKs.
        state,history=state_at(self.root/'shared/solana-evidence.sqlite')
        with patch.dict(os.environ,MM_SOLANA_CANDIDATE_HISTORY_DB=str(self.root/'shared/solana-candidate-history.sqlite')):
            try:
                for slot in (100,101):commit_control(state,frame(slot,logs=False))
                history.startup.begin()
                for family in ('pump','pumpswap'):
                    history.startup.feed_ack(family,100,100)
                history.startup.native(('pump','pumpswap'))
                for family in ('pump','pumpswap'):
                    history.request(family,PROGRAMS[family],100,100,priority=0,deadline=NOW+120)
                    job,_=history.plan();history.commit_page(job,dict(data=[]),finalized_through=100,seen=NOW)
                    while batch:=capture(history.lifecycle):
                        self.assertTrue(acknowledge(history.lifecycle,batch,deliver(batch)))
                        history.lifecycle.publish()
                    history.lifecycle.publish()
                self.assertTrue(history.startup.advance()['released'])
                for first in range(0,count,1024):history.ingest(native_rows(first,min(1024,count-first)))
                if future:history.ingest(native_rows(90000,1,available=NOW+50))
                if dangling:
                    top=history.db.execute('SELECT max(sequence) FROM candidate_outbox').fetchone()[0]
                    history.db.execute('INSERT INTO candidate_outbox VALUES(?,?,?,?,?)',
                        (top+1,'deliberately-dangling','program:pump',999999,float(NOW)))
                    history.db.commit()
            finally:state.writer.close()
        if queued:
            with closing(CandidateHistory(self.root/'shared/solana-candidate-history.sqlite')) as history:
                history.observe('pump','old-queued',surface='pump.fun',observed_at=int(NOW))
                history.enqueue('pump','old-queued',kind='history',ready_at=NOW,deadline=NOW+100,
                    estimate_seconds=1,priority=1)
        # Reseal via the original full native/financial replay, not a digest-only
        # substitute, after all fixture writers close and before new issuance.
        paths=[path for path in self.root.rglob('*') if path.suffix in ('.sqlite','.sqlite3')
            and path not in (self.root/'portfolio.sqlite',self.root/'shared-capital.sqlite')]
        context,snapshots=self.fixture.case.context(extra=paths)
        context._validate_owner=boot._owner_dead
        from meme_machine.runtime.native_flat_boot import validate_stopped_flat_boot_inputs
        try:value=validate_stopped_flat_boot_inputs(context).value()
        finally:
            context.close()
            for db in snapshots.values():db.close()
        certificate=self.record['boot_eligibility']
        for key in ('epoch_id','inception_sha256','journal_hash','projection_hash','combined_sequence',
                'native_input_sha256','policy_sha256'):certificate[key]=value[key]
        self.record['boot_id']=certificate['boot_id']=self.locator['boot_id']=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        self.record['supervisor']['start_ticks']=pump._process_start(os.getpid())
        certificate['physical_generation_sha256']=fixtures.physical_hash(self.root)
        fixtures.rehash(certificate);self.locator['record_sha256']=hashlib.sha256(wire.canonical(self.record)).hexdigest()
        self.fixture.launch._locator=deepcopy(self.locator);self.fixture.launch._record=deepcopy(self.record)
        self.context=boot.consume_normal_boot(self.fixture.supervisor,cancelled=lambda:False)

    def child(self,role,**options):
        channel=source.SourceLaunch(self.context) if role=='source' else pump.PumpOwnerLaunch(self.context)
        env=dict(os.environ,MM_STATE_ROOT=str(self.root),MM_RUNTIME_LANE='pump',
            MM_PAPER_EPOCH=self.record['boot_eligibility']['epoch_id'],MM_LANE_PROCESS_INSTANCE='d'*32,
            MM_SOLANA_EVIDENCE_PLANE_DB=str(self.root/'shared/solana-evidence.sqlite'),
            MM_SOLANA_CANDIDATE_HISTORY_DB=str(self.root/'shared/solana-candidate-history.sqlite'),
            MM_SOLANA_EVIDENCE_BROKER_DB=str(self.root/'pump/solana-evidence-broker.sqlite3'))
        process=subprocess.Popen([sys.executable,'-c',CHILD,str(channel.child_fd)],stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,pass_fds=(channel.child_fd,),
            start_new_session=True,env=env)
        def cleanup():
            if process.poll() is None:process.kill()
            process.wait(timeout=5)
            for stream in (process.stdin,process.stdout,process.stderr):stream.close()
        self.addCleanup(cleanup)
        process.stdin.write(json.dumps(dict(locator=self.locator,record=self.record,role=role,**options))+'\n');process.stdin.flush()
        kwargs=dict(deadline=time.monotonic()+5)
        if role=='pump':kwargs['process_instance']='d'*32
        channel.bind(process,**kwargs)
        raw=process.stdout.readline()
        if not raw:
            self.fail('child failed: '+process.stderr.read())
        return process,json.loads(raw)

    def test_private_native_5001_inherited_full_commits_and_new_source_union(self):
        self.prepare(5001,queued=True)
        _,source_value=self.child('source',fresh=3)
        _,value=self.child('pump',fixed_lease=True,matched=True)
        self.assertTrue(value['input_context_private']);self.assertFalse(value['source_transaction'])
        first,last=value['views'][0],value['views'][-1]
        self.assertNotEqual(first['key_census']['state'],'EOF')
        self.assertEqual(first['retained_prefix']['inherited_retained']['records'],5000)
        self.assertEqual(last['state'],'OBSERVED')
        self.assertEqual(last['retained_prefix']['inherited_expected']['records'],5001)
        self.assertEqual(last['retained_prefix']['inherited_retained']['records'],5001)
        self.assertEqual(last['retained_prefix']['source_retained']['records'],3)
        self.assertEqual(last['retained_prefix']['source_identity_sha256'],source_value['identity_sha256'])
        self.assertEqual(value['retained'],5004)
        self.assertEqual(len(value['queued']),1)
        self.assertNotEqual(value['queued'][0][-1],'complete')
        self.assertTrue(all(row['frontier_queries']==1 for row in value['physical']))
        self.assertEqual(value['matched']['plain_cursor'],value['sequence'])
        self.assertEqual(value['matched']['plain_missing'],5004)
        self.assertEqual([row['rows'] for row in value['matched']['plain']],
            [row['retained'] for row in value['physical']])
        self.assertTrue(all(row['frontier_queries']==row['key_queries']==0 for row in value['matched']['plain']))
        self.assertEqual([observed['queries']-plain['queries']
            for observed,plain in zip(value['physical'],value['matched']['plain'],strict=True)],[3,3,2])
        self.assertFalse(last['readiness_authority']);self.assertFalse(last['funding_authority'])
        print('private-native-5001-observation-cost '+json.dumps(dict(
            native_turns=value['physical'],opt_in_capture=value['capture_cost'],
            key_leases=last['key_census']['leases'],matched=value['matched']),sort_keys=True))

    def test_future_and_dangling_inherited_members_cannot_disappear_at_payload_eof(self):
        self.prepare(2,future=True,dangling=True)
        self.child('source')
        _,value=self.child('pump',fixed_lease=True)
        view=value['views'][-1]
        self.assertEqual(view['key_census']['state'],'EOF')
        self.assertEqual(view['key_census']['population']['records'],4)
        self.assertEqual(view['retained_prefix']['inherited_retained']['records'],2)
        self.assertEqual(view['state'],'INCOMPLETE')

    def test_actual_future_visibility_can_close_without_moving_boot_cut(self):
        self.prepare(2,future=True)
        self.child('source')
        _,value=self.child('pump',fixed_lease=True,commands=['consume','future','consume'])
        self.assertEqual(value['views'][0]['state'],'INCOMPLETE')
        self.assertEqual(value['views'][-1]['state'],'OBSERVED')
        self.assertEqual(value['views'][-1]['retained_prefix']['inherited_retained']['records'],3)

    def test_cancelled_key_snapshot_rolls_back_and_missing_frontier_stays_incomplete(self):
        self.prepare(2)
        self.child('source')
        _,value=self.child('pump',fixed_lease=True,commands=['cancel','consume','missing_frontier'])
        self.assertTrue(value['views'][0]['cancelled'])
        self.assertEqual(value['views'][1]['state'],'OBSERVED')
        self.assertEqual(value['views'][2]['state'],'INCOMPLETE')
        self.assertEqual(value['views'][2]['retained_prefix']['inherited_retained']['records'],2)

    def test_original_full_commit_failure_cannot_earn_retention(self):
        self.prepare(2)
        self.child('source')
        _,value=self.child('pump',commands=['failed_full'])
        view=value['views'][0]
        self.assertEqual(value['retained'],0)
        self.assertEqual(view['state'],'INCOMPLETE')
        self.assertTrue(view['retained_prefix']['capture_pending'])
        self.assertEqual(view['retained_prefix']['inherited_retained']['records'],0)

    def test_same_snapshot_foreign_generation_refuses_without_resetting_prior_retention(self):
        self.prepare(2);self.child('source')
        _,value=self.child('pump',commands=['consume','foreign_frontier'])
        self.assertEqual(value['views'][0]['state'],'OBSERVED')
        self.assertEqual(value['views'][1]['state'],'UNKNOWN')
        self.assertEqual(value['internal_retained'],2)


if __name__=='__main__':unittest.main()
