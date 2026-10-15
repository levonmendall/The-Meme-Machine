"""Actual native startup ownership with disposable SQLite and controlled I/O.

These are failure/cancellation mechanics, not market replay or capacity proof.
"""
from collections import deque
from contextlib import ExitStack,closing
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from meme_machine.runtime import status,stop


class NativeStartupLifecycle(unittest.TestCase):
    def setUp(self):
        self.prior=(status.state,status._operations,status._completed,status._signal,
                    stop.requested.is_set())
        status.state=dict(phase='RECONCILING',reconciled=False)
        status._operations=[];status._completed=deque(maxlen=8);status._signal=None
        stop.requested.clear()

    def tearDown(self):
        status.state,status._operations,status._completed,status._signal,requested=self.prior
        if requested:stop.requested.set()
        else:stop.requested.clear()

    @staticmethod
    def finish_worker(worker):
        try:worker.close(timeout=1)
        except BaseException:pass  # Preserve the test's original failure.
        for thread in worker.pool._threads:thread.join(1)

    def pump_fixture(self,stack,root,*,cleanup_error=False):
        from meme_machine.lanes.pump import runner,paper_accounting
        from meme_machine.runtime.candidate_history import CandidateHistory
        from meme_machine.lanes.pump.pipeline import Pipeline
        from meme_machine.lanes.pump.solana_evidence_broker import EvidenceBroker
        from meme_machine.lanes.pump.pump_acceleration_confirmations import ConfirmationBook
        epoch='offline-native-startup-lifecycle'
        stack.enter_context(patch.dict(os.environ,dict(PATH=os.environ.get('PATH',''),
            MM_PAPER_EPOCH=epoch,MM_PAPER_POLICY_REVISION='paper-opportunity-access-v1',
            MM_DIRECTIONAL_COMPOSITE_REQUIRED='1',
            MM_DIRECTIONAL_SLEEVE_DB=str(root/'sleeve.sqlite'),
            MM_DIRECTIONAL_COHORT_ID=epoch,
            MM_SOLANA_EVIDENCE_BROKER_DB=str(root/'broker.sqlite')),clear=True))
        for name in ('ACCOUNTING','CANDIDATE_HISTORY','PIPELINE','FILL_PERSISTENCE_CONTEXT'):
            stack.enter_context(patch.object(runner,name,None))
        stack.enter_context(patch.object(runner,'REPORT',root/'report.json'))
        stack.enter_context(patch.object(runner,'INITIAL_LAMPORTS',1000))
        stack.enter_context(patch.object(runner,'_save',return_value=None))
        stack.enter_context(patch.object(runner,'_restore_observed_pump_candidates',return_value=0))
        stack.enter_context(patch.object(ConfirmationBook,'from_files',
            return_value=ConfirmationBook({'cohort':[]},1)))
        opened={};closed=[]
        def own(name,value,method='close'):
            original=getattr(value,method)
            def close():
                closed.append((name,threading.get_native_id()))
                original()
                if cleanup_error and name=='candidate_history':
                    raise OSError('fixture_cleanup_failure')
            setattr(value,method,close);opened[name]=value
            # Test-owned fallback only; assertions precede fixture cleanup.
            def fallback():
                try:original()
                except BaseException:pass
            stack.callback(fallback)
            return value
        history=own('candidate_history',CandidateHistory(root/'candidates.sqlite',clock=lambda:1000))
        history.observe('pump','retained',surface='pump',observed_at=1000)
        history.append_event('pump','retained',identity='retained:create',slot=10,
            transaction_index=0,event_index=0,market_time=1000,kind='pump_create',
            payload=dict(event_type='create',mint='retained',creator='creator',market_time=1000))
        history.enqueue('pump','retained',kind='warmup',ready_at=1000,deadline=1100,
            estimate_seconds=1,identity='required-retained-history')
        expected={table:history.db.execute('SELECT * FROM '+table).fetchall()
            for table in ('candidates','events','work')}
        stack.enter_context(patch('meme_machine.runtime.candidate_history.open_candidate_history',
            return_value=history))
        book=paper_accounting.PaperBook
        stack.enter_context(patch.object(paper_accounting,'PaperBook',
            side_effect=lambda *args,**kwargs:own('accounting',book(*args,**kwargs))))
        stack.enter_context(patch.object(runner,'Pipeline',
            side_effect=lambda *args,**kwargs:own('pipeline',Pipeline(*args,**kwargs))))
        plane=own('plane',SimpleNamespace(close=lambda:None,telemetry=lambda:{}))
        stack.enter_context(patch.object(runner,'RuntimeEvidence',return_value=plane))
        stack.enter_context(patch.object(runner,'EvidenceBroker',
            side_effect=lambda *args,**kwargs:own('broker',EvidenceBroker(*args,**kwargs))))
        sessions=own('sessions',SimpleNamespace(finish=lambda:None,history=[],
            postgrad=SimpleNamespace(held_pumpswap_probe_reuses=0,held_finalized_time_reuses=0),
            pump=SimpleNamespace(local_finalized_time_reuses=0),rpc=SimpleNamespace(http_requests=0),
            holder_probe_status=lambda:{}),'finish')
        stack.enter_context(patch.object(runner,'Sessions',return_value=sessions))
        return runner,opened,closed,expected

    def assert_pending_preserved(self,root,expected):
        with closing(sqlite3.connect((root/'candidates.sqlite').resolve().as_uri()+'?mode=ro',uri=True)) as db:
            self.assertEqual({table:db.execute('SELECT * FROM '+table).fetchall()
                for table in expected},expected)

    def test_actual_pump_startup_failure_closes_resources_and_preserves_first_error(self):
        with tempfile.TemporaryDirectory() as directory,ExitStack() as stack:
            root=Path(directory)
            runner,opened,closed,expected=self.pump_fixture(stack,root,cleanup_error=True)
            original=RuntimeError('fixture_runtime_evidence_open_failure')
            stack.enter_context(patch.object(runner,'RuntimeEvidence',side_effect=original))
            with self.assertRaises(RuntimeError) as caught:
                runner.main(campaign=True,discovery_seconds=600)
            self.assertIs(caught.exception,original)
            self.assertIsNone(runner.ACCOUNTING);self.assertIsNone(runner.CANDIDATE_HISTORY)
            self.assertIsNone(runner.PIPELINE);self.assertIsNone(runner.FILL_PERSISTENCE_CONTEXT)
            for name in ('candidate_history','accounting','pipeline'):
                self.assertEqual([thread for key,thread in closed if key==name],
                    [threading.get_native_id()])
                with self.assertRaises(sqlite3.ProgrammingError):opened[name].db.execute('SELECT 1')
            self.assertIs(status.snapshot()['reconciled'],False)
            cleanup=[row for row in status.snapshot()['native_recent_operations']
                if row['operation']=='pump.startup_cleanup.candidate_history_open']
            self.assertEqual(len(cleanup),1)
            self.assertEqual(cleanup[0]['state'],'ERROR')
            self.assertEqual(cleanup[0]['error_type'],'OSError')
            self.assertEqual(cleanup[0]['native_thread_id'],threading.get_native_id())
            self.assertNotIn('fixture_cleanup_failure',json.dumps(status.snapshot()))
            self.assert_pending_preserved(root,expected)

    def test_actual_pump_survivor_prime_failure_closes_owned_service_on_its_executor(self):
        from meme_machine.runtime.survivor_history import Worker
        from meme_machine.lanes.pump import pumpswap_survivor_runtime
        with tempfile.TemporaryDirectory() as directory,ExitStack() as stack:
            root=Path(directory);runner,opened,closed,expected=self.pump_fixture(stack,root)
            original=RuntimeError('fixture_survivor_initial_step_failure');owner_threads=[];workers=[]
            class OwnedService:
                def __init__(self,*args):
                    owner_threads.append(threading.get_native_id())
                    self.db=sqlite3.connect(root/'survivor-owned.sqlite')
                    self.db.execute('CREATE TABLE pending(identity PRIMARY KEY)')
                    self.db.execute("INSERT INTO pending VALUES('accepted-native-recovery')");self.db.commit()
                def step(self,*,admit):raise original
                def close(self):
                    closed.append(('survivor_service',threading.get_native_id()));self.db.close()
            stack.enter_context(patch.object(pumpswap_survivor_runtime,'Runtime',OwnedService))
            start=runner._startup_work
            def started(identity,call,*args,**kwargs):
                value=start(identity,call,*args,**kwargs)
                if isinstance(value,Worker):
                    workers.append(value);stack.callback(self.finish_worker,value)
                return value
            stack.enter_context(patch.object(runner,'_startup_work',side_effect=started))
            with self.assertRaises(RuntimeError) as caught:
                runner.main(campaign=True,discovery_seconds=600)
            self.assertIs(caught.exception,original)
            self.assertEqual(len(owner_threads),1);self.assertNotEqual(owner_threads[0],threading.get_native_id())
            self.assertEqual([thread for key,thread in closed if key=='survivor_service'],owner_threads)
            self.assertEqual(len(workers),1);self.assertTrue(workers[0].closed)
            for name in ('candidate_history','accounting','pipeline','plane','broker','sessions'):
                self.assertEqual([thread for key,thread in closed if key==name],
                    [threading.get_native_id()])
            self.assertIsNone(runner.ACCOUNTING);self.assertIsNone(runner.CANDIDATE_HISTORY)
            self.assertIsNone(runner.PIPELINE);self.assertIsNone(runner.FILL_PERSISTENCE_CONTEXT)
            with closing(sqlite3.connect((root/'survivor-owned.sqlite').as_uri()+'?mode=ro',uri=True)) as db:
                self.assertEqual(db.execute('SELECT * FROM pending').fetchall(),[('accepted-native-recovery',)])
            self.assert_pending_preserved(root,expected)

    def test_survivor_factory_cancellation_reaches_owned_initial_capital_replay(self):
        from meme_machine.runtime.survivor_history import Worker
        from meme_machine.shared_capital import runtime
        from tests.shared_capital_support import Harness
        with tempfile.TemporaryDirectory() as directory,ExitStack() as stack:
            h=Harness(directory);stack.callback(h.close);constructed=[];observed=[];steps=[]
            before=h.authority.db.execute('SELECT * FROM shared_capital_events ORDER BY sequence').fetchall()
            def factory():
                observed.append(runtime._STARTUP_REPLAY_CANCEL.get())
                stop.requested.set()
                owner=runtime.connection(h.path);constructed.append(owner)
                return SimpleNamespace(step=lambda **kwargs:steps.append(kwargs) or {},close=owner.close)
            worker=Worker(factory,enrichment_enabled=False);stack.callback(self.finish_worker,worker)
            with self.assertRaises(stop.Shutdown):worker.prime(timeout=1)
            self.assertEqual(len(observed),1);self.assertTrue(callable(observed[0]))
            self.assertEqual(constructed,[]);self.assertEqual(steps,[])
            self.assertEqual(h.authority.db.execute('SELECT * FROM shared_capital_events ORDER BY sequence').fetchall(),before)
            self.assertIs(status.snapshot()['reconciled'],False)

    def test_survivor_constructor_scope_does_not_leak_into_initial_or_later_steps(self):
        from meme_machine.runtime.survivor_history import Worker
        from meme_machine.shared_capital import runtime
        scopes=[];factories=[]
        def factory():
            factories.append(runtime._STARTUP_REPLAY_CANCEL.get())
            return SimpleNamespace(step=lambda **kwargs:scopes.append(runtime._STARTUP_REPLAY_CANCEL.get()) or {},
                close=lambda:None)
        worker=Worker(factory,enrichment_enabled=False)
        try:
            worker.prime(timeout=1);stop.requested.set();worker.prime(timeout=1)
            self.assertEqual(len(factories),1);self.assertTrue(callable(factories[0]))
            self.assertEqual(scopes,[None,None])
        finally:self.finish_worker(worker)

    def test_startup_cleanup_without_primary_error_attempts_all_and_remains_failed(self):
        from meme_machine.lanes.pump import runner
        closed=[];original=OSError('fixture_close_failure')
        def failed_close():closed.append('first');raise original
        first=SimpleNamespace(close=failed_close)
        second=SimpleNamespace(close=lambda:closed.append('second'))
        @runner._startup_lifecycle
        def completed():
            runner.ACCOUNTING=runner._startup_work('pump.accounting_restore',lambda:first)
            runner.PIPELINE=runner._startup_work('pump.pipeline_open',lambda:second)
            return 'startup-returned'
        with patch.object(runner,'ACCOUNTING',None),patch.object(runner,'PIPELINE',None):
            with self.assertRaises(OSError) as caught:completed()
            self.assertIs(caught.exception,original)
            self.assertEqual(closed,['first','second'])
            self.assertIsNone(runner.ACCOUNTING);self.assertIsNone(runner.PIPELINE)
        self.assertIsNone(runner._STARTUP_RESOURCES.get())

    def test_actual_continuous_pump_future_shutdown_after_handoff_closes_every_owner(self):
        """An accepted constructor can fail after Current enters its loop."""
        from meme_machine.runtime.survivor_history import Worker
        from meme_machine.lanes.pump import pumpswap_survivor_runtime
        with tempfile.TemporaryDirectory() as directory,ExitStack() as stack:
            root=Path(directory);runner,opened,closed,expected=self.pump_fixture(stack,root)
            original=stop.Shutdown();entered=threading.Event();workers=[];factory_facts=[]
            def interrupted_factory(*args):
                factory_facts.append(status.snapshot()['native_operation'])
                entered.set();stop.requested.set();raise original
            stack.enter_context(patch.object(pumpswap_survivor_runtime,'Runtime',
                side_effect=interrupted_factory))
            stack.enter_context(patch('meme_machine.operational.position_continuation.continuous_operation',
                return_value=True))
            start=runner._startup_work
            def started(identity,call,*args,**kwargs):
                value=start(identity,call,*args,**kwargs)
                if isinstance(value,Worker):
                    workers.append(value);stack.callback(self.finish_worker,value)
                return value
            stack.enter_context(patch.object(runner,'_startup_work',side_effect=started))
            def reached_loop(*args):
                self.assertTrue(entered.wait(1));self.assertEqual(len(workers),1)
                # The real future carries the constructor's first exception.
                try:workers[0].future.result(timeout=1)
                finally:
                    factory_facts.extend(row for row in status.snapshot()['native_recent_operations']
                        if row['operation']=='pump.survivor_runtime_restore')
            stack.enter_context(patch.object(runner,'_monitor_positions',side_effect=reached_loop))
            with self.assertRaises(stop.Shutdown) as caught:
                runner.main(campaign=True,discovery_seconds=600)
            self.assertIs(caught.exception,original)
            self.assertEqual([row['state'] for row in factory_facts],['ACTIVE','CANCELLED'])
            self.assertTrue(all(row['operation']=='pump.survivor_runtime_restore' for row in factory_facts))
            self.assertTrue(all(row['native_thread_id']!=threading.get_native_id() for row in factory_facts))
            self.assertEqual(len({row['native_thread_id'] for row in factory_facts}),1)
            self.assertEqual(len(workers),1);self.assertTrue(workers[0].closed)
            for name in ('candidate_history','accounting','pipeline','plane','broker','sessions'):
                self.assertEqual([thread for key,thread in closed if key==name],
                    [threading.get_native_id()])
            self.assertIsNone(runner.ACCOUNTING);self.assertIsNone(runner.CANDIDATE_HISTORY)
            self.assertIsNone(runner.PIPELINE);self.assertIsNone(runner.FILL_PERSISTENCE_CONTEXT)
            self.assert_pending_preserved(root,expected)

    def test_actual_continuous_pump_report_failure_keeps_primary_and_closes_once(self):
        from meme_machine.runtime.survivor_history import Worker
        from meme_machine.lanes.pump import pumpswap_survivor_runtime
        with tempfile.TemporaryDirectory() as directory,ExitStack() as stack:
            root=Path(directory);runner,opened,closed,expected=self.pump_fixture(stack,root)
            primary=RuntimeError('fixture_native_loop_failure')
            report_error=OSError('fixture_final_report_failure');workers=[];reported=[];owner_threads=[]
            class OwnedService:
                def __init__(self,*args):owner_threads.append(threading.get_native_id())
                def step(self,*,admit):return {}
                def close(self):closed.append(('survivor_service',threading.get_native_id()))
            stack.enter_context(patch.object(pumpswap_survivor_runtime,'Runtime',OwnedService))
            stack.enter_context(patch('meme_machine.operational.position_continuation.continuous_operation',
                return_value=True))
            stack.enter_context(patch('meme_machine.runtime.opportunity_telemetry.enrich_service',return_value={}))
            stack.enter_context(patch.object(runner,'LocalPumpTape',
                return_value=SimpleNamespace(status=lambda now:{})))
            start=runner._startup_work
            def started(identity,call,*args,**kwargs):
                value=start(identity,call,*args,**kwargs)
                if isinstance(value,Worker):
                    workers.append(value);stack.callback(self.finish_worker,value)
                return value
            stack.enter_context(patch.object(runner,'_startup_work',side_effect=started))
            def failed_loop(*args):
                workers[0].future.result(timeout=1)
                raise primary
            def save(report):
                if 'ended' in report:
                    reported.append(True);raise report_error
            stack.enter_context(patch.object(runner,'_monitor_positions',side_effect=failed_loop))
            stack.enter_context(patch.object(runner,'_save',side_effect=save))
            with self.assertRaises(RuntimeError) as caught:
                runner.main(campaign=True,discovery_seconds=600)
            self.assertIs(caught.exception,primary);self.assertEqual(reported,[True])
            self.assertEqual([name for name,thread in closed],
                ['survivor_service','sessions','broker','plane','candidate_history','accounting','pipeline'])
            self.assertEqual([thread for name,thread in closed if name=='survivor_service'],owner_threads)
            self.assertIsNone(runner.ACCOUNTING);self.assertIsNone(runner.CANDIDATE_HISTORY)
            self.assertIsNone(runner.PIPELINE);self.assertIsNone(runner.FILL_PERSISTENCE_CONTEXT)
            self.assert_pending_preserved(root,expected)

    def test_shared_owned_closer_keeps_normal_cleanup_single_and_other_owner_untouched(self):
        from meme_machine.lanes.pump import runner
        closed=[];resource=SimpleNamespace(close=lambda:closed.append('owned'))
        other=object()
        @runner._startup_lifecycle
        def running():
            runner.PIPELINE=runner._startup_work('pump.pipeline_open',lambda:resource)
            # The normal finally and fallback use the same idempotent closer.
            runner._close_startup_resource('pump.pipeline_open',resource)
            runner.PIPELINE=None
            return 'normal-cleanup-complete'
        @runner._startup_lifecycle
        def replaced():
            runner._startup_work('pump.pipeline_open',lambda:resource)
            runner.PIPELINE=other
        with patch.object(runner,'PIPELINE',None):
            self.assertEqual(running(),'normal-cleanup-complete')
            self.assertEqual(closed,['owned'])
            replaced()
            self.assertIs(runner.PIPELINE,other)
            self.assertEqual(closed,['owned','owned'])
        self.assertIsNone(runner._STARTUP_RESOURCES.get())


if __name__=='__main__':unittest.main()
