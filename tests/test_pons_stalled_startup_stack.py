"""Bounded startup observations remain independent of signal/query authority."""
from contextlib import ExitStack
from copy import deepcopy
import ast
import json,os,select,signal,sqlite3,subprocess,sys,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
from meme_machine.runtime import status,stop
from meme_machine.operational import lane
from engineering.diagnostics import current_combined_observation_20261014 as diagnostic

ROOT=Path(__file__).resolve().parents[1]
NATIVE_SQL=('WITH RECURSIVE x(n) AS (SELECT id-1 FROM fixture_barrier WHERE id=1 '
            'UNION ALL SELECT n+1 FROM x WHERE n<{limit}) SELECT sum(n) FROM x')
CHILD=r'''
import json,os,signal,sqlite3,sys,threading,time
from pathlib import Path
from unittest.mock import patch
from operational.tests import network_guard
network_guard()
from meme_machine.runtime import status,stop
from meme_machine.operational import lane
from meme_machine.runtime.robinhood.plane import Plane
root=Path(sys.argv[1]);seen=[False];progress=[0];result=[None];query_active=[False];n=60000000
native_sql=__NATIVE_SQL__
os.environ.update(MM_MODE='PAPER',MM_OPERATIONAL_PHASE='OFFLINE_TEST',MM_OPERATION_COST_DIAGNOSTICS='1',MM_LANE_PROCESS_INSTANCE='a'*32)
def shutdown(signum,frame):status.cancellation_signal(signum);stop.requested.set()
signal.signal(signal.SIGTERM,shutdown)
original=sqlite3.connect;original_health=lane.health
class NativeGate(sqlite3.Connection):
    def set_progress_handler(self,*args):progress[0]+=1;return super().set_progress_handler(*args)
    def execute(self,sql,*args):
        if sql=='PRAGMA quick_check' and not seen[0]:
            seen[0]=True;print('SQL_ENTERED',flush=True)
            # The parent holds this disposable DB EXCLUSIVE until two genuine
            # heartbeat publications while TERM is pending. SQLite itself
            # blocks the table-dependent aggregate in this same execute call;
            # no prior query or Python callback/handler defers TERM.
            reader=connect(root/'startup-barrier.sqlite',timeout=20)
            try:
                query_active[0]=True
                result[0]=reader.execute(native_sql.format(limit=n)).fetchone()[0]
            finally:query_active[0]=False;reader.close()
        return super().execute(sql,*args)
def connect(*args,**kwargs):kwargs['factory']=NativeGate;return original(*args,**kwargs)
def health(root,lane_name,phase,**facts):
    original_health(root,lane_name,phase,**facts)
    row=facts.get('stalled_startup_stack')
    if row is not None:print('HEALTH '+json.dumps(dict(stack=row,phase=phase,query_active=query_active[0],signal_seen='cancellation_signal' in facts,event_set=stop.requested.is_set())),flush=True)
publish=lane.NativeHealthPublisher(root,'pons')
with patch.object(sqlite3,'connect',connect),patch.object(lane,'health',health):
    worker=threading.Thread(target=publish.heartbeat,args=(stop.requested,status),name='health');worker.start()
    with status.operation('pons.candidate_restore'):plane=Plane(root/'candidate.sqlite')
    plane.close();facts=status.snapshot();facts.pop('phase',None);publish('STOPPED',**facts);worker.join(3)
print('DONE '+json.dumps(dict(value=result[0],expected=n*(n+1)//2,signal_seen=status.snapshot().get('cancellation_signal',{}).get('signal'),progress_handlers=progress[0],health_joined=not worker.is_alive())),flush=True)
'''.replace('__NATIVE_SQL__',repr(NATIVE_SQL))


class StalledStartupStackTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ,dict(MM_OPERATION_COST_DIAGNOSTICS='1',MM_LANE_PROCESS_INSTANCE='a'*32),clear=True))
        self.stack.enter_context(patch.object(status,'_startup_stages',[]))

    def row(self):
        return dict(version=1,state='CAPTURED',scope=status.STARTUP_STACK_SCOPE,at=1000.,monotonic=106.,pid=11,
            process_start_ticks=10,main_native_thread_id=11,main_thread_start_ticks=10,reporter_native_thread_id=12,
            process_instance='a'*32,trigger_operation='pons.candidate_restore',trigger_native_thread_id=11,
            trigger_started_monotonic=100.,trigger_age_seconds=6.,trigger_active_bracket=True,
            frames=[dict(module='meme_machine.runtime.robinhood.plane',function='__init__',line=71)],
            frames_truncated=False,capture_sequence=1,capture_limit=14)

    def test_optional_capture_never_spends_original_sample_or_terminal_reserve(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);row=dict(native_lifecycle=dict(pons=dict(stalled_startup_stack=self.row())),original='kept')
            without=diagnostic.without_startup_stack(row)
            bound=len(json.dumps(without,sort_keys=True,separators=(',',':')).encode())+1
            with patch.object(diagnostic,'INPUT_BYTES',bound):diagnostic.append_sample(root/'sample',row)
            self.assertEqual(json.loads((root/'sample').read_bytes()),without)
            record=dict(final_native_health=row,original='terminal')
            bound=len(json.dumps(diagnostic.without_startup_stack(record),sort_keys=True).encode())+1
            with patch.object(diagnostic,'TERMINAL_BYTES',bound):diagnostic.write_metadata(root,'result.json',record)
            self.assertEqual(json.loads((root/'result.json').read_bytes()),diagnostic.without_startup_stack(record))
            self.assertIn('stalled_startup_stack',row['native_lifecycle']['pons'])
            with patch.object(diagnostic,'INPUT_BYTES',1),self.assertRaisesRegex(ValueError,'diagnostic_output_limit'):
                diagnostic.append_sample(root/'refused',row)

    def test_descriptive_health_does_not_duplicate_optional_capture(self):
        value=diagnostic.descriptive_lanes(dict(pons=dict(stalled_startup_stack=self.row(),pid=1)))
        self.assertNotIn('stalled_startup_stack',value['pons'])

    def test_capture_requires_actual_stalled_operation_and_preserves_event(self):
        before=stop.requested.is_set()
        self.assertIsNone(status.stalled_startup_stack())
        with status.operation('pons.candidate_restore'):
            self.assertIsNone(status.stalled_startup_stack())
            with patch.object(status,'STARTUP_STACK_MIN_SECONDS',0):
                row=status.stalled_startup_stack()
                self.assertEqual(row['trigger_operation'],'pons.candidate_restore')
                self.assertEqual(row['pid'],os.getpid());self.assertEqual(row['main_native_thread_id'],os.getpid())
                self.assertGreater(row['process_start_ticks'],0);self.assertTrue(row['trigger_active_bracket'])
        self.assertIsNone(status.stalled_startup_stack());self.assertEqual(stop.requested.is_set(),before)

    def test_all_seven_stages_keep_original_native_and_replay_contracts(self):
        from meme_machine.shared_capital import runtime
        public=status.STARTUP_STACK_OPERATIONS-status.STARTUP_DIAGNOSTIC_OPERATIONS
        self.assertEqual(public,{'pons.shared_capital_restore','pons.cohort_recovery','pons.candidate_restore'})
        before=stop.requested.is_set();replay=runtime._STARTUP_REPLAY_CANCEL.get()
        for name in sorted(status.STARTUP_STACK_OPERATIONS):
            with self.subTest(name=name):
                with status.operation(name):
                    self.assertEqual('native_operation' in status.snapshot(),name in public)
                recent=list(status._completed)
                with status.diagnostic_startup(name),patch.object(status,'STARTUP_STACK_MIN_SECONDS',0):
                    self.assertNotIn('native_operation',status.snapshot())
                    self.assertIs(runtime._STARTUP_REPLAY_CANCEL.get(),replay)
                    row=status.stalled_startup_stack()
                    if name in public:self.assertIsNone(row)
                    else:self.assertEqual(row['trigger_operation'],name)
                    self.assertEqual(list(status._completed),recent)
                    observed=diagnostic.native_lifecycle(dict(pons=dict(native_operation=dict(
                        operation=name,state='ACTIVE',pid=os.getpid(),native_thread_id=os.getpid(),
                        at=1.,monotonic=1.))))['pons']['native_operation']
                    self.assertEqual(observed!='UNAVAILABLE',name in public)
                self.assertFalse(status._startup_stages)
                self.assertIsNone(status.stalled_startup_stack())
        self.assertEqual(stop.requested.is_set(),before)

    def test_private_stage_optin_bound_failures_and_cleanup_never_change_native_state(self):
        from meme_machine.shared_capital import runtime
        recent=list(status._completed);replay=runtime._STARTUP_REPLAY_CANCEL.get()
        with patch.dict(os.environ,MM_OPERATION_COST_DIAGNOSTICS='0'),status.diagnostic_startup('pons.observation_start'):
            self.assertFalse(status._startup_stages)
        with status.diagnostic_startup('pons.unreviewed'):self.assertFalse(status._startup_stages)
        self.assertTrue(status.lock.acquire(False))
        try:
            with status.diagnostic_startup('pons.observation_start'):self.assertFalse(status._startup_stages)
        finally:status.lock.release()
        with ExitStack() as nested:
            for _ in range(status.STARTUP_DIAGNOSTIC_LIMIT+3):nested.enter_context(status.diagnostic_startup('pons.observation_start'))
            self.assertEqual(len(status._startup_stages),status.STARTUP_DIAGNOSTIC_LIMIT)
            self.assertNotIn('native_operation',status.snapshot())
        self.assertFalse(status._startup_stages)
        original=RuntimeError('PRIVATE_NOT_PUBLISHED')
        with self.assertRaises(RuntimeError) as caught:
            with status.diagnostic_startup('pons.startup_warmup_checkpoint'):raise original
        self.assertIs(caught.exception,original);self.assertFalse(status._startup_stages)
        with self.assertRaises(stop.Shutdown):
            with status.diagnostic_startup('pons.startup_discovery_checkpoint'):raise stop.Shutdown()
        self.assertFalse(status._startup_stages);self.assertEqual(list(status._completed),recent)
        self.assertIs(runtime._STARTUP_REPLAY_CANCEL.get(),replay)

    def test_actual_new_wrapper_census_uses_only_private_stage_scope(self):
        expected={
            'meme_machine/lanes/pons/pons_selective_cohort.py':{
                'pons.observation_start','pons.startup_warmup_checkpoint','pons.startup_discovery_checkpoint'},
            'meme_machine/runtime/survivor_history.py':{'pons.survivor_restore'}}
        for relative,names in expected.items():
            calls=[node for node in ast.walk(ast.parse((ROOT/relative).read_bytes())) if isinstance(node,ast.Call)
                and isinstance(node.func,ast.Attribute) and isinstance(node.func.value,ast.Name)
                and node.func.value.id=='status' and node.args and isinstance(node.args[0],ast.Constant)
                and node.args[0].value in status.STARTUP_DIAGNOSTIC_OPERATIONS]
            self.assertEqual({node.args[0].value for node in calls},names)
            self.assertTrue(all(node.func.attr=='diagnostic_startup' for node in calls))

    def test_probe_is_diagnostic_pons_only_and_has_fixed_frequency_and_stage_caps(self):
        publish=lane.NativeHealthPublisher('/disposable','pons');row=self.row()
        with patch.object(status,'stalled_startup_stack',return_value=row) as capture,patch.object(lane.time,'monotonic',return_value=100):
            with patch.dict(os.environ,{},clear=True):publish.sample_stalled_startup(status)
            lane.NativeHealthPublisher('/disposable','pump').sample_stalled_startup(status)
            capture.assert_not_called()
            publish.sample_stalled_startup(status);publish.sample_stalled_startup(status)
            self.assertEqual(capture.call_count,1)
        with patch.object(status,'stalled_startup_stack',return_value=row) as capture,patch.object(lane.time,'monotonic',return_value=110):
            publish.sample_stalled_startup(status);self.assertEqual(publish.startup_captures,2)
        with patch.object(status,'stalled_startup_stack',return_value=None) as capture,patch.object(lane.time,'monotonic',return_value=120):
            publish.sample_stalled_startup(status)
            self.assertIn('pons.candidate_restore',capture.call_args.kwargs['excluded'])
        publish.startup_captures=status.STARTUP_STACK_MAX_CAPTURES
        with patch.object(status,'stalled_startup_stack') as capture:publish.sample_stalled_startup(status);capture.assert_not_called()
        self.assertEqual((status.STARTUP_STACK_MIN_SECONDS,status.STARTUP_STACK_INTERVAL_SECONDS,status.STARTUP_STACK_MAX_CAPTURES),(5.,10.,14))

    def test_nonblocking_probe_does_not_wait_for_status_lock_or_publish_finished_stage(self):
        self.assertTrue(status.lock.acquire(False))
        try:self.assertIsNone(status.stalled_startup_stack())
        finally:status.lock.release()
        with status.operation('pons.candidate_restore'),patch.object(status,'STARTUP_STACK_MIN_SECONDS',0):
            original=status.cancellation_stack
            def completed(**kwargs):
                row=original(**kwargs)
                with status.lock:status._operations.clear()
                return row
            with patch.object(status,'cancellation_stack',side_effect=completed):self.assertIsNone(status.stalled_startup_stack())
        with status.diagnostic_startup('pons.observation_start'),patch.object(status,'STARTUP_STACK_MIN_SECONDS',0):
            original=status.cancellation_stack
            def private_completed(**kwargs):
                row=original(**kwargs)
                with status.lock:status._startup_stages.clear()
                return row
            with patch.object(status,'cancellation_stack',side_effect=private_completed):self.assertIsNone(status.stalled_startup_stack())

    def test_public_projection_refuses_bad_identity_stage_clock_frames_and_extra_payload(self):
        row=self.row();lane_row=dict(pid=11,process_instance='a'*32)
        self.assertEqual(diagnostic.stalled_startup_stack(row,lane_row),row)
        cases=[dict(pid=True),dict(main_native_thread_id=12),dict(main_thread_start_ticks=9),dict(trigger_operation='pons.current_hydration'),
            dict(trigger_operation=[]),dict(process_instance='b'*32),dict(trigger_active_bracket=False),dict(trigger_age_seconds=1),
            dict(monotonic=107),dict(capture_sequence=15),dict(version=True),dict(frames=[dict(module=[],function='__init__',line=1)]),
            dict(frames=[dict(module='meme_machine.runtime.robinhood.plane',function='private_canary',line=1)]),dict(frames=row['frames']*9)]
        for values in cases:
            with self.subTest(values=values):self.assertEqual(diagnostic.stalled_startup_stack(dict(row,**values),lane_row),'UNAVAILABLE')
        safe=diagnostic.stalled_startup_stack(dict(row,sql='PRIVATE_SQL',payload='https://private.invalid',locals={'secret':'PRIVATE'}),lane_row)
        self.assertEqual(safe,row);self.assertLess(len(json.dumps(safe).encode()),4096)

    def test_combined_projection_keeps_diagnostic_separate_from_cancellation_and_pump(self):
        row=self.row();lane_row=dict(pid=11,process_instance='a'*32,phase='MANAGING',reconciled=True,stalled_startup_stack=row)
        value=diagnostic.native_lifecycle(dict(pons=lane_row,pump=lane_row))
        self.assertEqual(value['pons']['stalled_startup_stack'],row)
        self.assertEqual(value['pons']['cancellation_signal'],'UNAVAILABLE')
        self.assertEqual(value['pons']['cancellation_stack'],'UNAVAILABLE')
        self.assertEqual(value['pump']['stalled_startup_stack'],'UNAVAILABLE')

    def test_actual_survivor_factory_records_only_its_startup_scope(self):
        from meme_machine.runtime.survivor_history import Worker
        from meme_machine.shared_capital import runtime
        observed=[];steps=[]
        class Service:
            def step(self,*,admit):
                steps.append((list(status._startup_stages),runtime._STARTUP_REPLAY_CANCEL.get(),status.snapshot()))
                return {}
            def close(self):pass
        def factory():
            with status.lock:observed.extend(row['operation'] for row in status._startup_stages)
            self.assertNotIn('native_operation',status.snapshot())
            self.assertTrue(callable(runtime._STARTUP_REPLAY_CANCEL.get()))
            return Service()
        with patch.dict(os.environ,dict(MM_RUNTIME_LANE='pons')):
            worker=Worker(factory,enrichment_enabled=False)
            try:worker.prime();worker.close()
            finally:worker.pool.shutdown(wait=True)
        self.assertIn('pons.survivor_restore',observed)
        self.assertTrue(steps)
        self.assertTrue(all(not rows and replay is None and 'native_operation' not in snapshot for rows,replay,snapshot in steps))
        with status.lock:self.assertFalse(status._startup_stages)

    def test_native_query_barrier_requires_real_database_access_without_recursive_work(self):
        with tempfile.TemporaryDirectory() as directory,ExitStack() as resources:
            path=Path(directory)/'startup-barrier.sqlite'
            barrier=sqlite3.connect(path);resources.callback(barrier.close)
            self.assertEqual(barrier.execute('PRAGMA journal_mode=DELETE').fetchone(),('delete',))
            barrier.execute('CREATE TABLE fixture_barrier(id INTEGER PRIMARY KEY)')
            barrier.execute('INSERT INTO fixture_barrier VALUES(1)');barrier.commit()
            self.assertEqual(barrier.execute('SELECT id FROM fixture_barrier').fetchall(),[(1,)])
            reader=sqlite3.connect(path,timeout=.05);resources.callback(reader.close)
            barrier.execute('BEGIN EXCLUSIVE')
            try:
                # Bound zero completes without recursive CPU work, so SQLITE_BUSY
                # proves a genuine DB dependency rather than an unfinished sum.
                with self.assertRaises(sqlite3.OperationalError) as caught:
                    reader.execute(NATIVE_SQL.format(limit=0)).fetchone()
                self.assertIn(caught.exception.sqlite_errorcode,(sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED))
                print('NATIVE_SQL_LOCK_DISCRIMINATOR '+json.dumps(dict(
                    sqlite_version=sqlite3.sqlite_version,limit=0,
                    sqlite_errorcode=caught.exception.sqlite_errorcode)),flush=True)
            finally:barrier.rollback()
            self.assertEqual(reader.execute(NATIVE_SQL.format(limit=0)).fetchone(),(0,))
            self.assertEqual(reader.execute(NATIVE_SQL.format(limit=1000)).fetchone(),(1000*1001//2,))

    def test_real_child_native_sql_preserves_query_and_publishes_before_deferred_term(self):
        with tempfile.TemporaryDirectory() as directory,ExitStack() as resources:
            barrier=sqlite3.connect(Path(directory)/'startup-barrier.sqlite')
            resources.callback(barrier.close)
            self.assertEqual(barrier.execute('PRAGMA journal_mode=DELETE').fetchone(),('delete',))
            barrier.execute('CREATE TABLE fixture_barrier(id INTEGER PRIMARY KEY)')
            barrier.execute('INSERT INTO fixture_barrier VALUES(1)');barrier.commit()
            barrier.execute('BEGIN EXCLUSIVE')
            child=subprocess.Popen([sys.executable,'-B','-u','-c',CHILD,directory],cwd=ROOT,
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,bufsize=0)
            samples=[];sent=False;released=False;entered=False;deadline=time.monotonic()+25
            try:
                while time.monotonic()<deadline:
                    self.assertTrue(select.select([child.stdout],[],[],max(.01,deadline-time.monotonic()))[0],'child deadline')
                    line=child.stdout.readline().decode()
                    if line.startswith('HEALTH '):
                        row=json.loads(line[7:]);samples.append(row)
                        if not released:
                            self.assertTrue(entered);self.assertTrue(row['query_active'])
                            self.assertNotIn(row['phase'],('STOPPED','FAIL_CLOSED'))
                            self.assertFalse(row['signal_seen']);self.assertFalse(row['event_set'])
                            if not sent:child.send_signal(signal.SIGTERM);sent=True
                            elif len(samples)>=2:
                                barrier.rollback();released=True
                    elif line=='SQL_ENTERED\n':entered=True
                    elif line.startswith('DONE '):done=json.loads(line[5:]);break
                    elif not line:break
                else:self.fail('native child did not finish')
                output,errors=child.communicate(timeout=3)
                self.assertEqual(child.returncode,0,errors)
                if 'done' not in locals():self.fail('missing DONE: '+output.decode()+errors.decode())
                self.assertTrue(sent);self.assertTrue(released);self.assertEqual(done['value'],done['expected'])
                self.assertEqual(done['progress_handlers'],0);self.assertEqual(done['signal_seen'],15);self.assertTrue(done['health_joined'])
                self.assertGreaterEqual(len([row for row in samples if not row['signal_seen']]),2)
                stack=samples[0]['stack'];self.assertGreaterEqual(stack['trigger_age_seconds'],5)
                self.assertIn(dict(module='meme_machine.runtime.robinhood.plane',function='__init__'),
                    [{k:frame[k] for k in ('module','function')} for frame in stack['frames']])
                print('NATIVE_SQL_STALLED_FIXTURE '+json.dumps(dict(
                    recursive_limit=60000000,pre_signal_samples=len([row for row in samples if not row['signal_seen']]),
                    first_capture_age_seconds=stack['trigger_age_seconds'],value=done['value'],
                    progress_handlers=done['progress_handlers'],signal=done['signal_seen'],
                    health_joined=done['health_joined'])),flush=True)
            finally:
                barrier.rollback()
                if child.poll() is None:child.kill();child.communicate(timeout=3)
                child.stdout.close();child.stderr.close()


if __name__=='__main__':unittest.main()
