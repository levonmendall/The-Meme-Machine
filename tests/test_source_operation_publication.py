"""Independent telemetry from a real blocked owner, with genuine Linux identity."""
import asyncio
from contextlib import closing, contextmanager, nullcontext
from copy import deepcopy
import json
import math
import multiprocessing
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from engineering.diagnostics import current_combined_observation_20261014 as diagnostic
from meme_machine import solana_evidence_service as service


PRIVATE='PRIVATE_SOURCE_OPERATION https://provider.invalid/credential'
FILENAME='solana-evidence-operation-costs.json'


def _database_facts(path):
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        return dict(health=db.execute('SELECT * FROM service_health ORDER BY key').fetchall(),
            cursors=db.execute('SELECT * FROM cursors ORDER BY scope').fetchall())


async def _child_publication(root,channel,mode):
    from meme_machine.runtime import operation_costs as costs
    from meme_machine.solana_evidence_control import PriorityOwner
    from meme_machine.solana_evidence_plane import EvidenceWriter
    from meme_machine.portfolio_accounting import _atomic_json
    from meme_machine.operational.supervisor import Supervisor
    path=Path(root)/'shared/solana-evidence.sqlite';path.parent.mkdir(parents=True)
    entered=threading.Event();release_owner=threading.Event();release_write=threading.Event()
    blocked=asyncio.Event();stop=asyncio.Event();loop=asyncio.get_running_loop()
    completed=[];bodies=[];pending=0;maximum_pending=0
    def factory():
        writer=EvidenceWriter(path)
        fence=service.FinalizedFence(writer,endpoint_identity='a'*64)
        fence.health('pid',os.getpid());fence.health('phase','WARMING')
        fence.health('heartbeat',123.);fence.health('startup_released',False)
        with writer.transaction():
            writer.db.execute('INSERT INTO cursors VALUES(?,?,?)',('control:solana',123,456.))
        return SimpleNamespace(writer=writer,close=writer.close)
    owner=PriorityOwner(factory);await asyncio.wrap_future(owner.ready)
    before=_database_facts(path)
    if mode=='refusals':
        outcomes=[];target=path.parent/FILENAME
        try:
            for case in ('snapshot','target_mode','temporary_mode'):
                existing=target if case=='target_mode' else target.with_name(target.name+'.tmp')
                if case!='snapshot':existing.write_bytes(b'unchanged private fixture');existing.chmod(0o644)
                clock=patch.object(costs,'monotonic',side_effect=RuntimeError(PRIVATE)) if case=='snapshot' else nullcontext()
                with clock, patch('meme_machine.portfolio_accounting._atomic_json',wraps=_atomic_json) as write:
                    failed_snapshot=costs.snapshot() if case=='snapshot' else None
                    try:
                        await asyncio.wait_for(service.publish_operation_costs(path,owner,stop),2)
                    except Exception as error:
                        outcome=dict(case=case,kind=type(error).__name__,message=str(error),
                            atomic_writes=write.call_count,unchanged_database=_database_facts(path)==before)
                    else:raise AssertionError('unsafe publication accepted')
                if case=='snapshot':
                    outcome.update(snapshot_available=failed_snapshot.get('available'),
                        snapshot_has_clock='collected_monotonic' in failed_snapshot,
                        output_exists=target.exists())
                else:
                    outcome.update(retained_bytes=existing.read_bytes().decode(),
                        retained_mode=existing.stat().st_mode&0o777)
                    existing.unlink()
                outcomes.append(outcome)
            channel.send(dict(state='REFUSALS',outcomes=outcomes))
        finally:owner.close()
        return
    def held(state):
        with costs.operation('owner.checkpoint'):
            entered.set()
            if not release_owner.wait(15):raise TimeoutError('disposable owner release')
            return PRIVATE
    held.owner_operation=dict(stage='checkpoint_prepare',component='NONE',
        origin_module='meme_machine.solana_evidence_service',origin_line=1)
    active=owner.submit(held,priority=3)
    if not await asyncio.to_thread(entered.wait,3):raise AssertionError('owner did not enter')
    queued=owner.submit(lambda state:None,priority=3)
    def stored(target,row):
        nonlocal pending,maximum_pending
        pending+=1;maximum_pending=max(maximum_pending,pending)
        try:
            bodies.append(row)
            if row['publication_state']=='ACTIVE' and sum(r['publication_state']=='ACTIVE' for r in bodies)==2:
                loop.call_soon_threadsafe(blocked.set)
                if not release_write.wait(15):raise TimeoutError('disposable publication release')
            _atomic_json(target,row);completed.append(row['publication_state'])
        finally:pending-=1
    if mode=='invalid':costs._recorder_valid=False;costs._recording_lost_calls=1
    task=None
    try:
        with patch('meme_machine.portfolio_accounting._atomic_json',stored):
            task=asyncio.create_task(service.publish_operation_costs(path,owner,stop))
            await asyncio.wait_for(blocked.wait(),4)
            channel.send(dict(state='ACTIVE_BLOCKED',pid=os.getpid(),
                ticks=Supervisor._source_start_ticks(os.getpid()),
                first_clock=bodies[0]['operation_costs']['collected_monotonic'],
                second_clock=bodies[1]['operation_costs']['collected_monotonic'],
                unchanged_while_blocked=_database_facts(path)==before))
            if await asyncio.to_thread(channel.recv)!='CANCEL':raise AssertionError('missing cancellation')
            task.cancel();await asyncio.sleep(0)
            channel.send(dict(state='CANCEL_PENDING',done=task.done(),
                completed=list(completed),maximum_pending=maximum_pending))
            if await asyncio.to_thread(channel.recv)!='RELEASE':raise AssertionError('missing release')
            release_write.set()
            try:await task
            except asyncio.CancelledError:pass
            terminal=json.loads((path.parent/FILENAME).read_text())
            release_owner.set()
            await asyncio.wrap_future(active);await asyncio.wrap_future(queued)
            owner.close()
            channel.send(dict(state='JOINED',publication_state=terminal['publication_state'],
                completed=completed,maximum_pending=maximum_pending,
                unchanged_after_stop=_database_facts(path)==before,
                owner_closed=not owner.thread.is_alive()))
    finally:
        release_write.set();release_owner.set();stop.set()
        if task is not None and not task.done():
            task.cancel();await asyncio.gather(task,return_exceptions=True)
        if owner.thread.is_alive():owner.close()


def _session_child(root,channel,mode):
    try:
        os.setsid()
        from operational.tests import network_guard
        network_guard()
        os.environ['MM_OPERATION_COST_DIAGNOSTICS']='1'
        os.environ['MM_SQLITE_DIAGNOSTIC_REQUIRED']='1'
        if mode.startswith('serve_flags_'):
            os.environ['MM_OPERATION_COST_DIAGNOSTICS']=mode[-2]
            os.environ['MM_SQLITE_DIAGNOSTIC_REQUIRED']=mode[-1]
        asyncio.run(_child_serve(root,channel,mode) if mode.startswith('serve_')
            else _child_publication(root,channel,mode))
    except BaseException as error:
        channel.send(dict(state='ERROR',kind=type(error).__name__,message=str(error)[:256]))
        raise
    finally:channel.close()


async def _child_serve(root,channel,mode):
    from meme_machine.solana_evidence_control import PriorityOwner
    from meme_machine.portfolio_accounting import _atomic_json
    from tests.maintenance_production_harness import NativeCompletionPool
    from tests.evidence_ipc_harness import ipc_transport
    from tests.test_solana_prewarm_startup import quiet_model_b
    path=Path(root)/'shared/solana-evidence.sqlite';path.parent.mkdir(parents=True)
    target=path.parent/FILENAME;stop=asyncio.Event();published=asyncio.Event()
    loop=asyncio.get_running_loop();owners=[];writes=[];original_init=PriorityOwner.__init__
    optional=mode.startswith('serve_flags_');health_published=asyncio.Event();selection={}
    original_health=service.ServiceState.publish_health
    def publish_health(state,*args,**kwargs):
        result=original_health(state,*args,**kwargs)
        loop.call_soon_threadsafe(health_published.set);return result
    def owner_init(owner,*args,**kwargs):
        original_init(owner,*args,**kwargs);owners.append(owner)
    def stored(destination,row):
        _atomic_json(destination,row);writes.append(row['publication_state'])
        if row['publication_state']=='ACTIVE':loop.call_soon_threadsafe(published.set)
    async def driver(work,stop):
        boot=asyncio.Event();boot.set();await quiet_model_b(work,boot)
        if optional:
            await health_published.wait()
            with patch.object(diagnostic,'source_operation_costs',side_effect=AssertionError('optional file read')) as reader:
                sample=diagnostic.pipeline_sample(root,os.getpid())
            with closing(sqlite3.connect(path)) as db:
                ipc=json.loads(db.execute("SELECT value FROM service_health WHERE key='ipc'").fetchone()[0])
            selected=sample['required_counters']['operation_costs']
            selection.update(reader_calls=reader.call_count,sql_metadata_preserved=
                selected==diagnostic.operation_costs(ipc.get('operation_costs'),os.getpid()),
                costs_available=selected['available'],independent_transport='transport' in selected)
        else:await published.wait()
        stop.set()
    if mode=='serve_error':
        temporary=target.with_name(target.name+'.tmp');temporary.write_bytes(b'unchanged');temporary.chmod(0o644)
    error=None
    with ipc_transport(),patch.object(PriorityOwner,'__init__',owner_init), \
            patch('concurrent.futures.ProcessPoolExecutor',NativeCompletionPool), \
            patch('meme_machine.portfolio_accounting._atomic_json',stored), \
            patch.object(service.ServiceState,'publish_health',publish_health), \
            (patch.object(service,'publish_operation_costs',side_effect=AssertionError('optional publisher'))
                if optional else nullcontext()):
        try:
            await asyncio.wait_for(service.serve(path,'https://solana-mainnet.g.alchemy.com/v2/offline-test',
                stop=stop,source_driver=driver),8)
        except Exception as caught:error=dict(kind=type(caught).__name__,message=str(caught))
    with closing(sqlite3.connect(path)) as db:
        phase=json.loads(db.execute("SELECT value FROM service_health WHERE key='phase'").fetchone()[0])
    completed=list(writes);await asyncio.sleep(0)
    channel.send(dict(state='SERVE_RETURN',error=error,phase=phase,
        owners_closed=bool(owners) and all(not owner.thread.is_alive() for owner in owners),
        publisher_pending=any(not task.done() and task.get_coro().__qualname__=='publish_operation_costs'
            for task in asyncio.all_tasks()),
        writes=completed,no_late_writes=writes==completed,
        selection=selection,
        terminal=json.loads(target.read_text())['publication_state'] if target.exists() else None))


class SourceOperationPublicationTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.path=self.root/'shared'/FILENAME

    @contextmanager
    def publisher(self,mode='normal'):
        context=multiprocessing.get_context('spawn');parent,child=context.Pipe()
        process=context.Process(target=_session_child,args=(str(self.root),child,mode))
        process.start();child.close();box=dict(process=process,channel=parent)
        def receive():
            self.assertTrue(parent.poll(7),'publication child response deadline')
            value=parent.recv();self.assertNotEqual(value.get('state'),'ERROR',value);return value
        try:
            box['ready']=receive();self.assertEqual(box['ready']['state'],'ACTIVE_BLOCKED')
            box['raw']=self.path.read_bytes();yield box
        finally:
            if process.is_alive():
                try:
                    parent.send('CANCEL');box['waiting']=receive()
                    parent.send('RELEASE');box['final']=receive()
                finally:
                    process.join(7)
                    if process.is_alive():process.terminate();process.join(3)
            else:process.join(3)
            parent.close()

    def read(self,pid):
        with patch.object(diagnostic.sqlite3,'connect',side_effect=AssertionError('SQL fallback')) as sql:
            value=diagnostic.source_operation_costs(self.root,pid)
        sql.assert_not_called();self.assertNotIn('PRIVATE_',json.dumps(value))
        self.assertNotIn('https://',json.dumps(value));return value

    def replace(self,value):
        self.path.write_text(json.dumps(value,separators=(',',':')))

    def serve_result(self,mode):
        context=multiprocessing.get_context('spawn');parent,child=context.Pipe()
        process=context.Process(target=_session_child,args=(str(self.root),child,mode))
        process.start();child.close()
        try:
            self.assertTrue(parent.poll(10),'serve child response deadline');result=parent.recv()
            self.assertEqual(result['state'],'SERVE_RETURN',result)
            process.join(3);self.assertEqual(process.exitcode,0);return result
        finally:
            if process.is_alive():process.terminate();process.join(3)
            parent.close()

    def test_actual_serve_propagates_initial_publisher_failure_and_closes_owner_as_failed(self):
        result=self.serve_result('serve_error')
        self.assertEqual(result['error'],dict(kind='ValueError',message='operation_cost_publication_path'))
        self.assertEqual(result['phase'],'FAILED');self.assertTrue(result['owners_closed'])
        self.assertFalse(result['publisher_pending'])
        self.assertEqual(result['writes'],[]);self.assertIsNone(result['terminal'])

    def test_actual_serve_normal_stop_joins_publisher_before_off_and_terminal_stopped(self):
        result=self.serve_result('serve_stop')
        self.assertIsNone(result['error']);self.assertEqual(result['phase'],'OFF')
        self.assertTrue(result['owners_closed']);self.assertIn('ACTIVE',result['writes'])
        self.assertFalse(result['publisher_pending'])
        self.assertEqual(result['writes'][-1],'STOPPED');self.assertEqual(result['terminal'],'STOPPED')
        self.assertTrue(result['no_late_writes'])

    def test_optional_flag_matrix_keeps_actual_serve_sql_costs_without_publisher_or_file_reader(self):
        for costs,required in (('0','0'),('1','0'),('0','1')):
            with self.subTest(costs=costs,required=required):
                # Each real service uses its own disposable canonical SQLite store.
                with tempfile.TemporaryDirectory() as temporary:
                    original=self.root;self.root=Path(temporary)
                    try:result=self.serve_result('serve_flags_'+costs+required)
                    finally:self.root=original
                self.assertIsNone(result['error']);self.assertEqual(result['phase'],'OFF')
                self.assertTrue(result['owners_closed']);self.assertFalse(result['publisher_pending'])
                self.assertEqual(result['writes'],[]);self.assertIsNone(result['terminal'])
                self.assertEqual(result['selection'],dict(reader_calls=0,sql_metadata_preserved=True,
                    costs_available=costs=='1',independent_transport=False))

    def test_real_owner_block_does_not_block_fresh_cost_publication_or_change_database(self):
        with self.publisher() as box:
            ready=box['ready'];observed=self.read(ready['pid']);row=observed['operation_costs']
            self.assertEqual(observed['state'],'OBSERVED',observed)
            self.assertTrue(row['available'],row)
            self.assertGreater(ready['second_clock'],ready['first_clock'])
            self.assertTrue(ready['unchanged_while_blocked'])
            self.assertEqual(row['pid'],ready['pid'])
            self.assertEqual(row['collected_monotonic'],ready['first_clock'])
            self.assertTrue(row['recorder_valid'])
            self.assertEqual(diagnostic.OperationCoverage().check('solana',row,time.monotonic()),None)
            owner=observed['owner_observation']['owner_scheduler']
            self.assertEqual(owner['owner_pid'],ready['pid']);self.assertEqual(owner['queued'],1)
            active=observed['owner_observation']['owner_operations']['active']
            self.assertEqual(active['stage'],'checkpoint_prepare')
            self.assertGreaterEqual(active['elapsed_microseconds'],0)
            self.assertTrue(row['active'])
            self.assertEqual(row['transport'],'INDEPENDENT_SOURCE_STATUS_FILE')
            self.assertEqual(observed['owner_observation']['scope'],
                'PROCESS_OWNER_TELEMETRY_NOT_CANONICAL_PROGRESS')
            body=json.loads(box['raw']);body['operation_costs']['private_payload']=PRIVATE
            body['owner_scheduler']['private_payload']=PRIVATE;self.replace(body)
            self.assertEqual(self.read(ready['pid']),observed)
        self.assertTrue(box['final']['unchanged_after_stop'])

    def test_cancelled_accepted_atomic_write_joins_before_terminal_stopped_without_late_active(self):
        with self.publisher() as box:pass
        self.assertEqual(box['waiting']['state'],'CANCEL_PENDING')
        self.assertFalse(box['waiting']['done'])
        self.assertEqual(box['waiting']['completed'],['ACTIVE'])
        self.assertEqual(box['final']['state'],'JOINED')
        self.assertEqual(box['final']['completed'],['ACTIVE','ACTIVE','STOPPED'])
        self.assertEqual(box['final']['maximum_pending'],1)
        self.assertEqual(box['final']['publication_state'],'STOPPED')
        self.assertTrue(box['final']['owner_closed']);self.assertTrue(box['final']['unchanged_after_stop'])
        self.assertEqual(json.loads(self.path.read_text())['publication_state'],'STOPPED')

    def test_existing_guard_preserves_the_original_fifteen_second_freshness_boundary(self):
        with self.publisher() as box:
            pid=box['ready']['pid'];row=self.read(pid)['operation_costs'];clock=row['collected_monotonic']
            guard=diagnostic.OperationCoverage()
            # A real uptime near a binary exponent boundary can make
            # (clock + 15) - clock round above 15. Use exact binary fixture
            # clocks for the predicate boundary; retain the real reader clock.
            boundary_row=dict(row,collected_monotonic=1024.125)
            self.assertIsNone(guard.check('solana',boundary_row,1039.125))
            for observed in (math.nextafter(1039.125,math.inf),math.nextafter(1024.125,-math.inf)):
                self.assertEqual(guard.check('solana',boundary_row,observed),'operation_cost_sample_stale:solana')
            # Reading a retained sample never renews the original producer clock.
            self.assertEqual(self.read(pid)['operation_costs']['collected_monotonic'],clock)

    def test_pid_start_ticks_owner_identity_and_stopped_publication_refuse_without_sql(self):
        with self.publisher() as box:
            pid=box['ready']['pid'];original=json.loads(box['raw'])
            paths=((('pid',),pid+1),(('process_start_ticks',),box['ready']['ticks']+1),
                (('publication_state',),'STOPPED'),(('operation_costs','pid'),pid+1),
                (('owner_scheduler','owner_pid'),pid+1),(('owner_scheduler','native_thread_id'),True))
            for path,value in paths:
                with self.subTest(path=path):
                    body=deepcopy(original);row=body
                    for key in path[:-1]:row=row[key]
                    row[path[-1]]=value;self.replace(body)
                    self.assertEqual(self.read(pid)['state'],diagnostic.UNAVAILABLE)
            self.path.write_bytes(box['raw'])
            self.assertEqual(self.read(True)['state'],diagnostic.UNAVAILABLE)

    def test_missing_corrupt_oversized_symlink_and_dead_source_refuse_without_sql(self):
        with self.publisher() as box:
            pid=box['ready']['pid']
            for raw in (b'{',b'[]',b'x'*(1024*1024+1)):
                with self.subTest(bytes=len(raw)):
                    self.path.write_bytes(raw);self.assertEqual(self.read(pid)['state'],diagnostic.UNAVAILABLE)
            self.path.unlink();self.assertEqual(self.read(pid)['state'],diagnostic.UNAVAILABLE)
            alternate=self.path.with_name('private-retained.json');alternate.write_bytes(box['raw'])
            self.path.symlink_to(alternate)
            self.assertEqual(self.read(pid)['state'],diagnostic.UNAVAILABLE)
            self.path.unlink();self.path.write_bytes(box['raw'])
            box['process'].terminate();box['process'].join(3)
            self.assertFalse(box['process'].is_alive());self.assertEqual(self.read(pid)['state'],diagnostic.UNAVAILABLE)

    def test_failed_actual_recorder_flags_remain_failure_to_the_existing_coverage_guard(self):
        with self.publisher('invalid') as box:
            row=self.read(box['ready']['pid'])['operation_costs']
            self.assertTrue(row['available'],row)
            self.assertIs(row['recorder_valid'],False)
            self.assertEqual(row['recording_lost_calls'],1)
            self.assertEqual(diagnostic.OperationCoverage().check('solana',row,time.monotonic()),
                'operation_cost_recorder_lost:solana')

    def test_opt_out_creates_no_file_or_internal_task(self):
        async def exercise():
            for costs,required in (('0','0'),('1','0'),('0','1')):
                with patch.dict(os.environ,MM_OPERATION_COST_DIAGNOSTICS=costs,MM_SQLITE_DIAGNOSTIC_REQUIRED=required), \
                        patch.object(asyncio,'create_task',side_effect=AssertionError('opt-out task')), \
                        patch('meme_machine.portfolio_accounting._atomic_json',side_effect=AssertionError('opt-out write')):
                    await service.publish_operation_costs(self.root/'shared/solana-evidence.sqlite',None,asyncio.Event())
        asyncio.run(exercise())
        self.assertFalse(self.path.exists());self.assertEqual(list(self.root.iterdir()),[])

    def test_initial_unavailable_snapshot_and_nonprivate_files_fail_before_any_atomic_write(self):
        context=multiprocessing.get_context('spawn');parent,child=context.Pipe()
        process=context.Process(target=_session_child,args=(str(self.root),child,'refusals'))
        process.start();child.close()
        try:
            self.assertTrue(parent.poll(7),'refusal child response deadline');result=parent.recv()
            self.assertEqual(result['state'],'REFUSALS',result)
            self.assertEqual([row['case'] for row in result['outcomes']],
                ['snapshot','target_mode','temporary_mode'])
            for row in result['outcomes']:
                with self.subTest(case=row['case']):
                    self.assertEqual(row['kind'],'ValueError')
                    self.assertEqual(row['message'],'operation_cost_snapshot_identity' if row['case']=='snapshot'
                        else 'operation_cost_publication_path')
                    self.assertEqual(row['atomic_writes'],0);self.assertTrue(row['unchanged_database'])
                    if row['case']=='snapshot':
                        self.assertIs(row['snapshot_available'],False)
                        self.assertFalse(row['snapshot_has_clock']);self.assertFalse(row['output_exists'])
                    else:
                        self.assertEqual(row['retained_bytes'],'unchanged private fixture')
                        self.assertEqual(row['retained_mode'],0o644)
            process.join(3);self.assertEqual(process.exitcode,0)
        finally:
            if process.is_alive():process.terminate();process.join(3)
            parent.close()
