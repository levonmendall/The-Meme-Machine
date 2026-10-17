"""Complete Pump restart costs on disposable history; no providers or authority."""
from collections import deque
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from meme_machine.lanes.pump import runner
from meme_machine.runtime import operation_costs as costs, sqlite_failure, status, stop
from meme_machine.runtime.candidate_history import CandidateHistory


OUTER='pump.observed_candidates_restore'
CHILD='pump.observed_candidate_events'
NOW=1791042000


class PumpRestoreCostAttributionTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ,{'MM_OPERATION_COST_DIAGNOSTICS':'1'}))
        for name,value in (('_rows',costs._new_rows()),('_active',{}),('_sequence',0),
                ('_recorder_valid',True),('_recording_lost_calls',0),('_active_overflow_calls',0),
                ('_current',ContextVar('test_pump_restore_costs',default=None))):
            self.stack.enter_context(patch.object(costs,name,value))
        self.stack.enter_context(patch.object(costs,'runnable_snapshot',return_value=None))
        for name,value in (('state',dict(phase='RECONCILING',reconciled=False,progress_at=42)),
                ('_operations',[]),('_completed',deque(maxlen=8)),('_signal',None)):
            self.stack.enter_context(patch.object(status,name,value))
        self.stack.enter_context(patch.object(stop,'requested',threading.Event()))
        self.stack.enter_context(patch.object(runner,'_STARTUP_RESOURCES',
            ContextVar('test_pump_restore_resources',default=None)))
        self.root=Path(self.stack.enter_context(tempfile.TemporaryDirectory()))

    def row(self,name):return costs.snapshot()['rows'][name]

    def history(self,count=12):
        history=CandidateHistory(self.root/'history.sqlite',clock=lambda:NOW)
        self.stack.callback(history.close)
        for index in range(count):
            mint='offline-mint-'+str(index)
            history.observe('pump',mint,surface='pump',observed_at=NOW+index)
            history.append_event('pump',mint,identity=mint+':create',slot=100+index,
                transaction_index=0,event_index=0,market_time=NOW+index,kind='pump_create',
                payload=dict(event_type='create',mint=mint,creator='offline-creator',market_time=NOW+index))
        return history

    def retained(self,history):
        tables=[row[0] for row in history.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {name:sorted(history.db.execute('SELECT * FROM '+name).fetchall(),key=repr)
            for name in tables}

    def assert_no_authority(self):
        self.assertEqual(status.state,dict(phase='RECONCILING',reconciled=False,progress_at=42))
        self.assertIsNone(runner._STARTUP_RESOURCES.get())
        facts=costs.snapshot()
        self.assertNotIn('safe_for_normal',facts)
        self.assertNotIn('recovery_verified',facts)
        self.assertNotIn('checkpoint_authority',facts)

    def test_only_two_fixed_pump_cost_identities_are_admitted(self):
        self.assertEqual(tuple(name for name in costs.NAMES if name.startswith('pump.')),(OUTER,CHILD))
        for identity in ('pump.accounting_restore','pump.any_candidate','pump.private-token'):
            with self.assertRaisesRegex(ValueError,'operation_cost_identity'):
                with costs.operation(identity):self.fail('unknown cost identity executed')
        self.assert_no_authority()

    def test_opt_out_preserves_calls_results_and_existing_status_without_cost_probes(self):
        marker=object();argument=object();seen=[]
        def child(value,*,keyword):
            seen.append((value,keyword,costs._current_operation()))
            return marker
        def parent():return runner._startup_work(CHILD,child,argument,keyword=marker)
        with patch.dict(os.environ,{'MM_OPERATION_COST_DIAGNOSTICS':'0'}), \
                patch.object(costs,'_sample') as sample:
            self.assertIs(runner._startup_work(OUTER,parent),marker)
            sample.assert_not_called()
            self.assertEqual(costs.snapshot()['rows'],{})
        self.assertEqual(seen,[(argument,marker,None)])
        self.assertEqual([row['operation'] for row in status._completed],[CHILD,OUTER])
        self.assertTrue(all(row['state']=='COMPLETE' for row in status._completed))
        self.assert_no_authority()

    def test_all_child_invocations_are_counted_beyond_recent_status_sampling(self):
        samples=[(0,0,None)]
        for index in range(12):samples.extend(((2*index+1,(2*index+1)/2,None),
                                               (2*index+2,(2*index+2)/2,None)))
        samples.append((30,15,None));seen=[]
        def child(index,*,private):
            self.assertEqual(costs._current_operation(),CHILD)
            seen.append(index)
            return private
        marker=object()
        def parent():
            self.assertEqual(costs._current_operation(),OUTER)
            values=[runner._startup_work(CHILD,child,index,private=marker) for index in range(12)]
            self.assertTrue(all(value is marker for value in values))
            self.assertEqual(costs._current_operation(),OUTER)
            return len(values)
        with patch.object(costs,'_sample',side_effect=samples):
            self.assertEqual(runner._startup_work(OUTER,parent),12)
        outer=self.row(OUTER);child_cost=self.row(CHILD)
        self.assertEqual(seen,list(range(12)))
        self.assertEqual((outer['calls'],outer['child_calls'],child_cost['calls']),(1,12,12))
        self.assertEqual((outer['failed_calls'],outer['unmeasured_calls'],outer['child_unmeasured_calls']),(0,0,0))
        self.assertEqual((child_cost['failed_calls'],child_cost['unmeasured_calls']),(0,0))
        self.assertEqual(outer['wall_seconds_total_microseconds'],30_000_000)
        self.assertEqual(outer['cpu_seconds_total_microseconds'],15_000_000)
        self.assertEqual(outer['child_wall_seconds_total_microseconds'],12_000_000)
        self.assertEqual(outer['child_cpu_seconds_total_microseconds'],6_000_000)
        self.assertEqual(outer['child_wall_seconds_total_microseconds'],child_cost['wall_seconds_total_microseconds'])
        self.assertEqual(outer['child_cpu_seconds_total_microseconds'],child_cost['cpu_seconds_total_microseconds'])
        self.assertEqual(len(status._completed),8)
        facts=status.snapshot()['operation_costs']
        self.assertTrue(facts['recorder_valid']);self.assertEqual(facts['recording_lost_calls'],0)
        self.assertEqual(facts['active'],[])
        self.assert_no_authority()

    def test_actual_restore_counts_all_candidates_and_selected_sql_without_mutating_history(self):
        history=self.history();before=self.retained(history)
        self.assertIsInstance(history.db,sqlite_failure.Connection)
        confirmations=SimpleNamespace(observe_creation=Mock(),observe_graduation=Mock())
        created={};postgrad={};stream=SimpleNamespace(add_address=Mock())
        with patch.object(runner,'CANDIDATE_HISTORY',history):
            restored=runner._startup_work(OUTER,runner._restore_observed_pump_candidates,
                created,postgrad,stream,object(),confirmations,NOW+60)
        self.assertEqual(restored,12);self.assertEqual(len(created),12);self.assertEqual(postgrad,{})
        self.assertEqual(confirmations.observe_creation.call_count,12)
        confirmations.observe_graduation.assert_not_called();stream.add_address.assert_not_called()
        outer=self.row(OUTER);child=self.row(CHILD)
        self.assertEqual((outer['calls'],outer['child_calls'],child['calls']),(1,12,12))
        for row in (outer,child):
            self.assertEqual((row['unmeasured_calls'],row['child_unmeasured_calls']),(0,0))
            self.assertGreater(row['sql']['statement']['calls'],0)
            self.assertGreater(row['sql']['fetch']['calls'],0)
            self.assertEqual(sum(value['failed_calls'] for value in row['sql'].values()),0)
            self.assertEqual(sum(value['unmeasured_calls'] for value in row['sql'].values()),0)
        # The selected connection existed before either cost context. Its real
        # SQLite hooks still cover execute, fetch and iteration without a new
        # connection or a fabricated "selected connection opened" counter.
        self.assertEqual((outer['selected_connection_calls'],child['selected_connection_calls']),(0,0))
        self.assertEqual(self.retained(history),before)
        self.assert_no_authority()

    def test_real_sql_failure_keeps_original_exception_and_innermost_attribution(self):
        db=sqlite_failure.connect(':memory:',diagnostic_role='pump_restore_cost_fixture')
        self.stack.callback(db.close);raised=[]
        def child():
            try:db.execute('SELECT private_column FROM private_missing_table')
            except sqlite3.OperationalError as error:raised.append(error);raise
        def parent():return runner._startup_work(CHILD,child)
        with self.assertRaises(sqlite3.OperationalError) as caught:
            runner._startup_work(OUTER,parent)
        self.assertIs(caught.exception,raised[0])
        self.assertEqual(caught.exception.sqlite_failure['current_operation'],CHILD)
        self.assertEqual((self.row(OUTER)['failed_calls'],self.row(CHILD)['failed_calls']),(1,1))
        self.assertEqual(self.row(CHILD)['sql']['statement']['failed_calls'],1)
        self.assertEqual(self.row(OUTER)['sql']['statement']['calls'],0)
        self.assertNotIn('private_column',json.dumps(status.snapshot()))
        self.assertNotIn('private_missing_table',json.dumps(status.snapshot()))
        self.assertEqual(costs.snapshot()['active'],[])
        self.assert_no_authority()

    def test_cancelled_actual_restore_preserves_pending_history_and_unfinished_readiness(self):
        history=self.history(3);read=history.events
        job=history.enqueue('pump','offline-mint-2',kind='warmup',ready_at=NOW,
            deadline=NOW+60,estimate_seconds=1)
        history.wait_for_history(job,'candidate:pumpswap:offline-mint-2',100,110,retry_at=NOW+1)
        before=self.retained(history)
        confirmations=SimpleNamespace(observe_creation=Mock(),observe_graduation=Mock())
        created={};postgrad={};stream=SimpleNamespace(add_address=Mock())
        def cancelled(*args,**kwargs):
            rows=read(*args,**kwargs);stop.requested.set();return rows
        with patch.object(runner,'CANDIDATE_HISTORY',history), \
                patch.object(history,'events',side_effect=cancelled):
            with self.assertRaises(stop.Shutdown):
                runner._startup_work(OUTER,runner._restore_observed_pump_candidates,
                    created,postgrad,stream,object(),confirmations,NOW+60)
        self.assertEqual((self.row(OUTER)['calls'],self.row(OUTER)['failed_calls']),(1,1))
        self.assertEqual((self.row(CHILD)['calls'],self.row(CHILD)['failed_calls']),(1,0))
        self.assertEqual(self.row(OUTER)['child_unmeasured_calls'],0)
        self.assertEqual(status._completed[-1]['state'],'CANCELLED')
        self.assertEqual((created,postgrad),({},{}))
        confirmations.observe_creation.assert_not_called();stream.add_address.assert_not_called()
        self.assertEqual(self.retained(history),before)
        self.assertEqual(costs.snapshot()['active'],[])
        self.assert_no_authority()

    def test_optional_cost_recorder_failure_does_not_mask_original_startup_error(self):
        original=RuntimeError('private-original-startup-failure')
        def fail():raise original
        with patch.object(costs,'_merge',side_effect=OSError('optional-recorder-failure')):
            with self.assertRaises(RuntimeError) as caught:runner._startup_work(OUTER,fail)
        self.assertIs(caught.exception,original)
        facts=costs.snapshot()
        self.assertFalse(facts['recorder_valid']);self.assertGreater(facts['recording_lost_calls'],0)
        self.assertEqual(facts['active'],[])
        self.assertEqual(status._completed[-1]['state'],'ERROR')
        self.assertNotIn(str(original),json.dumps(status.snapshot()))
        self.assert_no_authority()

    def test_accounting_replay_and_resource_ownership_are_unchanged_and_unmeasured(self):
        marker=object();owned=object();argument=object();events=[]
        @contextmanager
        def replay(cancelled):
            self.assertFalse(cancelled());events.append('replay-enter')
            try:yield
            finally:events.append('replay-exit')
        def call(value,*,keyword):
            self.assertIs(value,argument);self.assertIs(keyword,marker)
            self.assertIsNone(costs._current_operation());events.append('call');return marker
        def own(identity,value):
            self.assertEqual(identity,'pump.accounting_restore');self.assertIs(value,marker)
            events.append('own');return owned
        with patch('meme_machine.shared_capital.runtime.native_startup_replay',side_effect=replay), \
                patch.object(runner,'_own_startup_resource',side_effect=own), \
                patch.object(costs,'_sample') as sample:
            self.assertIs(runner._startup_work('pump.accounting_restore',call,argument,keyword=marker),owned)
            sample.assert_not_called()
        self.assertEqual(events,['replay-enter','call','replay-exit','own'])
        self.assertEqual(costs.snapshot()['rows'],{})
        self.assert_no_authority()
