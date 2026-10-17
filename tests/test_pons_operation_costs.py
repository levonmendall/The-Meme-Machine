"""Reached Pons callbacks retain native ownership under opt-in cost recording."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, closing
from contextvars import ContextVar
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from meme_machine.runtime import operation_costs as costs, status
from meme_machine.runtime.survivor_history import History, Worker
from meme_machine.lanes.pons import pons_current_workers as current
from meme_machine.lanes.pons import pons_selective_paper as paper
from meme_machine.lanes.pons import pons_selective_recovery as recovery


class PonsOperationCostsTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ,{
            'MM_OPERATION_COST_DIAGNOSTICS':'1','MM_RUNTIME_LANE':'pons',
            'MM_PONS_USD_ACQUISITION_OVERLAP':'0'},clear=True))
        for key,value in (('_rows',costs._new_rows()),('_active',{}),('_sequence',0),
                          ('_recorder_valid',True),('_recording_lost_calls',0),
                          ('_active_overflow_calls',0),
                          ('_current',ContextVar('test_pons_operation_costs',default=None))):
            self.stack.enter_context(patch.object(costs,key,value))

    def row(self,name):return costs.snapshot()['rows'][name]

    def wait_for(self,predicate):
        until=time.monotonic()+5
        while not predicate():
            if time.monotonic()>=until:self.fail('native cost callback did not finish its turn')
            time.sleep(.005)

    def test_current_owner_turn_uses_saved_context_and_excludes_native_idle(self):
        context=ContextVar('native_owner_fixture',default=None);seen=[];created=threading.Event()
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'native.sqlite'
            def native(*args,**kwargs):
                from meme_machine.lanes.pons.evidence import Store
                context.set('retained');store=Store(path);owner=threading.get_native_id()
                try:
                    self.assertEqual(store.db.execute('SELECT 7').fetchone()[0],7)
                    seen.append(('first',costs._current.get()['name'],owner));created.set()
                    command=yield dict(kind='monitor_wait',seconds=5,position='native')
                    self.assertEqual(context.get(),'retained')
                    self.assertEqual(threading.get_native_id(),owner)
                    seen.append(('handoff',costs._current.get()['name'],owner))
                    self.assertEqual(command,'handoff')
                    return dict(status='handoff_required',identity='original-native')
                finally:
                    seen.append(('close',costs._current.get()['name'],threading.get_native_id()))
                    store.close()
            with patch.object(recovery,'_resume_receipt_steps',side_effect=native),current.LifecyclePool(max_workers=1) as pool:
                future=pool.submit(recovery._resume_receipt,'offline',None,None)
                self.assertTrue(created.wait(3))
                self.wait_for(lambda:pool.telemetry()['active_physical_workers']==0)
                before=self.row('pons.current_owner_turn')
                self.assertEqual(before['calls'],1)
                self.assertGreater(before['sql']['statement']['calls'],0)
                self.assertEqual(costs.snapshot()['active'],[])
                self.assertFalse(future.done())
                pool.request_handoff()
                self.assertEqual(future.result(timeout=3),dict(status='handoff_required',identity='original-native'))
            after=self.row('pons.current_owner_turn')
            self.assertEqual(after['calls'],3)  # next, handoff send, final close
            self.assertEqual(after['failed_calls'],0)
            self.assertEqual([part[0] for part in seen],['first','handoff','close'])
            self.assertTrue(all(part[1]=='pons.current_owner_turn' for part in seen))
            self.assertEqual(len({part[2] for part in seen}),1)
            self.assertNotEqual(seen[0][2],threading.get_native_id())

    def test_current_owner_failure_and_entry_shutdown_keep_original_future_error(self):
        from meme_machine.runtime.stop import Shutdown
        owner_error=ValueError('offline-native-error');entry_error=Shutdown()
        def failed_owner(*args,**kwargs):
            raise owner_error
            yield
        def stopped_entry(*args,**kwargs):
            raise entry_error
            yield
        with patch.object(recovery,'_resume_receipt_steps',side_effect=failed_owner), \
                patch.object(paper,'run_lifecycle_steps',side_effect=stopped_entry), \
                current.LifecyclePool(max_workers=1) as pool:
            owner=pool.submit(recovery._resume_receipt,'offline',None,None)
            entry=pool.submit(paper.run_lifecycle,'offline',{})
            with self.assertRaises(ValueError) as failed:owner.result(timeout=3)
            self.assertIs(failed.exception,owner_error)
            with self.assertRaises(Shutdown) as stopped:entry.result(timeout=3)
            self.assertIs(stopped.exception,entry_error)
        self.assertEqual(self.row('pons.current_owner_turn')['failed_calls'],1)
        self.assertEqual(self.row('pons.current_entry_turn')['submitted_calls'],1)
        self.assertEqual(self.row('pons.current_entry_turn')['queue_calls'],1)

    def test_survivor_restore_step_and_enrichment_execute_on_one_pons_owner(self):
        seen=[];closed=[]
        class Service:
            def __init__(self):seen.append(('restore',costs._current.get()['name'],threading.get_native_id()))
            def step(self,*,admit):
                seen.append(('step',costs._current.get()['name'],threading.get_native_id()))
                return dict(last_boundary=None,accounting={'open_positions':0,'reserved':0})
            def close(self):closed.append(threading.get_native_id())
        def enrich(service,*,now):
            seen.append(('enrich',costs._current.get()['name'],threading.get_native_id()))
            return dict(status='OBSERVATION_ONLY')
        with patch('meme_machine.runtime.opportunity_telemetry.enrich_service',side_effect=enrich), \
                patch('meme_machine.operational.position_continuation.position_only',return_value=False):
            worker=Worker(Service)
            try:
                result=worker.prime(timeout=3)
                self.assertEqual(result['opportunity_telemetry']['status'],'OBSERVATION_ONLY')
                self.assertEqual(result['machinery']['completed_steps'],1)
            finally:worker.close(timeout=3)
        self.assertEqual([part[1] for part in seen],
            ['pons.survivor_restore','pons.survivor_step','pons.survivor_enrich'])
        self.assertEqual(len({part[2] for part in seen}),1)
        self.assertEqual(closed,[seen[0][2]])
        for name in ('pons.survivor_restore','pons.survivor_step','pons.survivor_enrich'):
            self.assertEqual(self.row(name)['calls'],1)

    def test_pump_survivor_does_not_emit_pons_operation_rows(self):
        class Service:
            def step(self,*,admit):return dict(last_boundary=None)
            def close(self):pass
        with patch.dict(os.environ,MM_RUNTIME_LANE='pump'):
            worker=Worker(Service,enrichment_enabled=False)
            try:self.assertEqual(worker.prime(timeout=3)['machinery']['completed_steps'],1)
            finally:worker.close(timeout=3)
        self.assertEqual(costs.snapshot()['rows'],{})

    def test_cohort_dispatch_passes_original_callbacks_when_recording_disabled(self):
        from meme_machine.lanes.pons import pons_selective_cohort as cohort
        from tests.lanes.pons.test_pons_continuous_campaign import ContinuousCampaignTests
        with patch.dict(os.environ,MM_OPERATION_COST_DIAGNOSTICS='0'), \
                patch.object(cohort.operation_costs,'submit',wraps=costs.submit) as submit:
            ContinuousCampaignTests()._campaign_probe(startup=True)
        names={call.args[1] for call in submit.call_args_list}
        self.assertTrue({'pons.current_discovery','pons.current_prime','pons.current_hydration'}<=names)
        self.assertEqual(costs.snapshot()['rows'],{})

    def test_actual_hydration_callback_retains_values_and_exception(self):
        from meme_machine.lanes.pons import pons_selective_cohort as cohort
        result={'retained':'qualification'};owners=[];failure=ValueError('offline-evidence-error')
        def evaluate(*args,**kwargs):
            owners.append(threading.get_native_id())
            self.assertEqual(costs._current.get()['name'],'pons.current_hydration')
            self.assertEqual(kwargs['strategy_capital_quote'],123)
            return result
        with patch.object(cohort,'_current_pons_realized_equity',return_value=123), \
                patch.object(cohort,'evaluate_candidate',side_effect=evaluate) as evaluation, \
                ThreadPoolExecutor(max_workers=1) as executor:
            self.assertIs(costs.submit(executor,'pons.current_hydration',cohort._evaluate_current_candidate,
                'offline',{},[]).result(timeout=3),result)
            evaluation.side_effect=failure
            with self.assertRaises(ValueError) as caught:
                costs.submit(executor,'pons.current_hydration',cohort._evaluate_current_candidate,
                    'offline',{},[]).result(timeout=3)
            self.assertIs(caught.exception,failure)
        self.assertNotEqual(owners[0],threading.get_native_id())
        row=self.row('pons.current_hydration')
        self.assertEqual((row['calls'],row['failed_calls'],row['queue_calls']),(2,1,2))

    def test_selected_connection_sites_preserve_sqlite_values_errors_and_pragmas(self):
        from meme_machine.runtime.robinhood.plane import Plane
        from meme_machine.lanes.pons.evidence import Store
        from meme_machine.runtime.survivor_paper_book import PaperBook
        from meme_machine.lanes.pons.pons_selective_capital import CohortCapital
        with tempfile.TemporaryDirectory() as td,ExitStack() as stack:
            root=Path(td)
            with costs.operation('pons.survivor_restore'),patch.object(costs,'connect',wraps=costs.connect) as connect:
                plane=Plane(root/'plane.sqlite');stack.callback(plane.close)
                store=Store(root/'native.sqlite');stack.callback(store.close)
                history=History(root/'history.sqlite',policy='offline');stack.callback(history.close)
                book=PaperBook(root/'book.sqlite',run_id='offline',lane='offline',policy_hash='offline',initial=100)
                stack.callback(book.close)
                capital=CohortCapital(root/'capital.sqlite',100)
                with closing(capital._connect()) as capital_db:
                    self.assertEqual(json.loads(capital_db.execute('SELECT body FROM capital_genesis').fetchone()[0])['capital'],100)
                for db in (plane.db,store.db,history.db,book.db):
                    self.assertIsInstance(db,sqlite3.Connection)
                    self.assertIsNot(type(db),sqlite3.Connection)
                    self.assertEqual(db.execute('SELECT ?',('original-value',)).fetchone()[0],'original-value')
                    with self.assertRaises(sqlite3.OperationalError):db.execute('SELECT missing_fixture_column')
                    self.assertEqual(db.execute('PRAGMA synchronous').fetchone()[0],2)
                self.assertEqual(store.db.execute('PRAGMA journal_mode').fetchone()[0],'delete')
                self.assertEqual(history.db.execute('PRAGMA journal_mode').fetchone()[0],'wal')
                roles={call.kwargs['diagnostic_role'] for call in connect.call_args_list}
                self.assertTrue({'pons_plane','pons_native_store','survivor_history',
                    'survivor_paper_book','pons_selective_capital'}<=roles)
            row=self.row('pons.survivor_restore')
            self.assertGreaterEqual(row['selected_connection_calls'],6)
            self.assertGreaterEqual(row['sql']['statement']['failed_calls'],4)
            self.assertGreater(row['sql']['fetch']['calls'],0)

    def test_disabled_connection_sites_keep_original_factory_and_no_health_cost_field(self):
        from meme_machine.runtime.robinhood.plane import Plane
        from meme_machine.lanes.pons.evidence import Store
        with patch.dict(os.environ,MM_OPERATION_COST_DIAGNOSTICS='0'), \
                tempfile.TemporaryDirectory() as td:
            plane=Plane(Path(td)/'plane.sqlite');store=Store(Path(td)/'store.sqlite')
            try:
                self.assertIs(type(plane.db),sqlite3.Connection)
                self.assertIs(type(store.db),sqlite3.Connection)
                self.assertNotIn('operation_costs',status.snapshot())
            finally:store.close();plane.close()

    def test_reporting_costs_preserve_noop_result_and_leave_other_lane_unattributed(self):
        from meme_machine.runtime.robinhood.plane import Plane
        from meme_machine.runtime.robinhood.accounting import project
        with tempfile.TemporaryDirectory() as td:
            plane=Plane(Path(td)/'plane.sqlite')
            try:
                self.assertEqual(project(plane,SimpleNamespace(lane='pons')),0)
                self.assertEqual(project(plane,SimpleNamespace(lane='pump')),0)
            finally:plane.close()
        row=self.row('pons.reporting')
        self.assertEqual(row['calls'],1)
        self.assertGreater(row['sql']['statement']['calls'],0)
        self.assertEqual(row['failed_calls'],0)

    def test_diagnostic_environment_reaches_pump_pons_and_source_with_sqlite_fence(self):
        from meme_machine.operational.supervisor import Supervisor
        with tempfile.TemporaryDirectory() as td:
            supervisor=Supervisor(td,offline=False);supervisor.epoch='offline-diagnostic'
            with patch.dict(os.environ,MM_SQLITE_DIAGNOSTIC_REQUIRED='1',
                    MM_SQLITE_TERMINAL_RECORD_PATH=str(Path(td)/'sqlite-terminal.json')):
                children={lane:supervisor.environment(lane) for lane in ('pons','solana','pump')}
            self.assertEqual(children['pons']['MM_OPERATION_COST_DIAGNOSTICS'],'1')
            self.assertEqual(children['solana']['MM_OPERATION_COST_DIAGNOSTICS'],'1')
            self.assertEqual(children['pump']['MM_OPERATION_COST_DIAGNOSTICS'],'1')
            self.assertIn('MM_SQLITE_DIAGNOSTIC_REQUIRED',children['solana'])
            for lane in ('pons','pump'):
                self.assertNotIn('MM_SQLITE_DIAGNOSTIC_REQUIRED',children[lane])
                self.assertNotIn('MM_SQLITE_TERMINAL_RECORD_PATH',children[lane])

    def test_health_keeps_fixed_thread_roles_and_bounded_operation_snapshot(self):
        main=SimpleNamespace(native_id=1,name='main')
        names=('pons-current_0','pons-current_7','pons-current-entry_0','pons-current-entry_7',
               'pons-usd_0','pons-scale-history_0','pons-current_8','pons-current-entry_8','private-name')
        threads=[main]+[SimpleNamespace(native_id=n,name=name) for n,name in enumerate(names,2)]
        with patch.object(status.threading,'main_thread',return_value=main), \
                patch.object(status.threading,'enumerate',return_value=threads), \
                costs.operation('pons.current_discovery'):
            snapshot=status.snapshot()
        roles=[row['role'] for row in snapshot['native_threads']['threads']]
        self.assertEqual(roles,['main','pons-current','pons-current','pons-current-entry',
            'pons-current-entry','pons-usd','pons-scale-history','UNAVAILABLE','UNAVAILABLE','UNAVAILABLE'])
        self.assertEqual(snapshot['operation_costs']['active'][0]['operation'],'pons.current_discovery')
        self.assertNotIn('private-name',json.dumps(snapshot))
