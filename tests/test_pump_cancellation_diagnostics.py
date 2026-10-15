"""Disposable native cancellation/reporting coverage; no market or real state."""
from collections import deque
from contextlib import ExitStack,closing
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from meme_machine.operational import lane
from meme_machine.operational.supervisor import Supervisor
from meme_machine.runtime import status,stop


class PumpCancellationDiagnostics(unittest.TestCase):
    def setUp(self):
        self.prior=(dict(status.state),list(status._operations),status._completed,status._signal,
                    stop.requested.is_set())
        status.state=dict(phase='RECONCILING',reconciled=False)
        status._operations=[];status._completed=deque(maxlen=8);status._signal=None
        stop.requested.clear()

    def tearDown(self):
        status.state,status._operations,status._completed,status._signal,_=self.prior
        if self.prior[-1]:stop.requested.set()
        else:stop.requested.clear()

    def test_operation_records_do_not_assert_reconciliation_or_renew_progress(self):
        status.update('RECONCILING',reconciled=False)
        original=status.snapshot()['progress_at']
        with status.operation('pump.accounting_restore'):
            active=status.snapshot()
            self.assertEqual(active['native_operation']['operation'],'pump.accounting_restore')
            self.assertEqual(active['native_operation']['pid'],os.getpid())
            self.assertFalse(active['reconciled'])
        after=status.snapshot()
        self.assertFalse(after['reconciled']);self.assertEqual(after['phase'],'RECONCILING')
        self.assertEqual(after['progress_at'],original)
        self.assertNotIn('native_operation',after)
        self.assertEqual(after['native_recent_operations'][-1]['state'],'COMPLETE')

    def test_blocked_executor_and_cancellation_signal_are_separately_identified(self):
        entered=threading.Event();released=threading.Event();errors=[];executor=[]
        def work():
            try:
                with status.operation('pump.observed_candidate_events'):
                    executor.append(threading.get_native_id());entered.set()
                    if not released.wait(2):raise RuntimeError('fixture_timeout')
                    raise stop.Shutdown()
            except stop.Shutdown:errors.append('cancelled')
        thread=threading.Thread(target=work)
        thread.start()
        try:
            self.assertTrue(entered.wait(2))
            # Recording in a signal handler must not reacquire this status lock.
            with status.lock:status.cancellation_signal(signal.SIGTERM)
            observed=status.snapshot()
            self.assertEqual(observed['native_operation']['native_thread_id'],executor[0])
            self.assertEqual(observed['cancellation_signal']['native_thread_id'],threading.get_native_id())
            self.assertNotEqual(executor[0],threading.get_native_id())
            self.assertFalse(observed['reconciled'])
        finally:released.set();thread.join(2)
        self.assertFalse(thread.is_alive());self.assertEqual(errors,['cancelled'])
        self.assertEqual(status.snapshot()['native_recent_operations'][-1]['state'],'CANCELLED')

    def test_terminal_operation_does_not_publish_exception_text_or_unbounded_history(self):
        error=RuntimeError('secret-query-bindings-must-not-be-recorded')
        with self.assertRaises(RuntimeError) as caught:
            with status.operation('pump.observed_candidates_restore'):raise error
        self.assertIs(caught.exception,error)
        self.assertNotIn(str(error),json.dumps(status.snapshot()))
        self.assertEqual(status.snapshot()['native_recent_operations'][-1]['state'],'ERROR')
        for _ in range(100):
            with status.operation('pump.observed_candidate_events'):pass
        self.assertEqual(len(status.snapshot()['native_recent_operations']),8)

    def test_optional_record_failure_preserves_original_operation_error(self):
        class Broken:
            def append(self,row):raise OSError('probe-only-error')
        error=RuntimeError('original')
        with patch.object(status,'_completed',Broken()):
            with self.assertRaises(RuntimeError) as caught:
                with status.operation('pump.current_runtime_restore'):raise error
        self.assertIs(caught.exception,error)

    def test_optional_start_record_failure_does_not_prevent_actual_operation(self):
        error=RuntimeError('original-startup-error');calls=[]
        with patch.object(status.time,'monotonic',side_effect=OSError('clock-probe-only-error')):
            with self.assertRaises(RuntimeError) as caught:
                with status.operation('pump.current_runtime_restore'):
                    calls.append('actual-operation');raise error
        self.assertIs(caught.exception,error);self.assertEqual(calls,['actual-operation'])

    def cancel_actual_lane(self,root,*,reconciled):
        def cancelled(*args):
            status.update('DISCOVERING' if reconciled else 'RECONCILING',reconciled=reconciled)
            with status.operation('pump.observed_candidates_restore'):
                status.cancellation_signal(signal.SIGTERM)
                stop.requested.set()
                raise stop.Shutdown()
        with patch('sys.argv',['lane','--lane','pump','--state-root',str(root)]), \
                patch('meme_machine.operational.bounded_provider.install'), \
                patch.object(lane,'run_native',side_effect=cancelled):
            lane.main()
        return json.loads((root/'pump'/'health.json').read_text())

    def test_actual_lane_shutdown_keeps_unfinished_reconciliation_false(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'pump').mkdir()
            row=self.cancel_actual_lane(root,reconciled=False)
        self.assertEqual(row['phase'],'STOPPED');self.assertIs(row['reconciled'],False)
        self.assertEqual(row['native_recent_operations'][-1]['state'],'CANCELLED')
        self.assertEqual(row['cancellation_signal']['signal'],signal.SIGTERM)

    def test_actual_lane_shutdown_preserves_prior_completed_reconciliation(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'pump').mkdir()
            row=self.cancel_actual_lane(root,reconciled=True)
        self.assertEqual(row['phase'],'STOPPED');self.assertIs(row['reconciled'],True)

    def test_cancelled_reporting_does_not_delete_disposable_durable_pending_work(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'pump').mkdir();path=root/'pump'/'pending.sqlite'
            # A bounded pending marker: this test establishes no state mutation
            # by the reporting correction, not production engine crash recovery.
            db=sqlite3.connect(path)
            db.execute('CREATE TABLE pending(identity PRIMARY KEY,body)')
            db.execute('INSERT INTO pending VALUES(?,?)',('accepted-event','awaiting-history'))
            db.commit();db.close();before=path.read_bytes()
            self.cancel_actual_lane(root,reconciled=False)
            self.assertEqual(path.read_bytes(),before)
            with closing(sqlite3.connect(path)) as reader:
                self.assertEqual(reader.execute('SELECT * FROM pending').fetchall(),
                    [('accepted-event','awaiting-history')])

    def test_actual_runner_startup_wrapper_identifies_failing_operation(self):
        from meme_machine.lanes.pump import runner
        error=RuntimeError('fixture-startup-error')
        with self.assertRaises(RuntimeError) as caught:
            runner._startup_work('pump.runtime_evidence_open',lambda:(_ for _ in ()).throw(error))
        self.assertIs(caught.exception,error)
        self.assertEqual(status.snapshot()['native_recent_operations'][-1]['operation'],
            'pump.runtime_evidence_open')
        self.assertIs(status.snapshot()['reconciled'],False)

    def test_observed_restore_cancels_after_completed_read_preserving_pending_and_restart(self):
        """Real retained rows and owner outbox; no market replay/capacity claim."""
        import copy
        from meme_machine.lanes.pump import runner
        from meme_machine.lanes.pump.pump_acceleration_confirmations import ConfirmationBook
        from meme_machine.runtime.candidate_history import CandidateHistory
        from meme_machine.solana_selective_history import PROGRAMS,economic_records
        from tests.test_solana_closure import NOW,state_at
        from tests.test_solana_selective_evidence import FIXTURE
        with tempfile.TemporaryDirectory() as directory,ExitStack() as resources:
            root=Path(directory);(root/'pump').mkdir()
            candidate_path=root/'candidate-history.sqlite'
            with patch.dict(os.environ,MM_SOLANA_CANDIDATE_HISTORY_DB=str(candidate_path)):
                state,canonical=state_at(root/'canonical.sqlite')
            resources.callback(state.writer.close)
            canonical.lifecycle.delivery_separated=True
            canonical.ingest([record for transaction in FIXTURE['pump'] for record in economic_records(
                'pump',PROGRAMS['pump'],copy.deepcopy(transaction),endpoint_identity='a'*64,
                seen=NOW,source='alchemy_finalized_stream')])
            history=CandidateHistory(candidate_path,clock=lambda:NOW)
            resources.callback(history.close)
            for index,mint in enumerate(('first','second','later-survivor')):
                history.observe('pump',mint,surface='pump',observed_at=int(NOW)+index)
                kind='pumpswap_trade' if mint=='later-survivor' else 'pump_create'
                history.append_event('pump',mint,identity=mint+':retained',slot=100+index,
                    transaction_index=0,event_index=0,market_time=int(NOW)+index,kind=kind,
                    payload=dict(event_type='trade' if mint=='later-survivor' else 'create',
                        mint=mint,creator='creator',market_time=int(NOW)+index))
            job=history.enqueue('pump','later-survivor',kind='warmup',ready_at=NOW,
                deadline=NOW+60,estimate_seconds=1)
            history.wait_for_history(job,'candidate:pumpswap:later-survivor',100,110,
                retry_at=NOW+1)
            def retained():
                return {table:history.db.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall()
                    for table in ('candidates','events','work','work_history_requirements',
                                  'history_coverage','work_history_proofs')}
            before=retained()
            pending=state.writer.db.execute('SELECT id,hash,consumed FROM candidate_history_outbox '
                'ORDER BY id').fetchall()
            self.assertTrue(pending);self.assertTrue(all(row[2] is None for row in pending))
            reads=[];read=history.events;created={};postgrad={}
            def cancel_after_read(*args,**kwargs):
                result=read(*args,**kwargs);reads.append(args[1])
                status.cancellation_signal(signal.SIGTERM);stop.requested.set()
                return result
            confirmations=ConfirmationBook({'cohort':[]},1)
            def restore(*args):
                runner._startup_work('pump.observed_candidates_restore',
                    runner._restore_observed_pump_candidates,created,postgrad,
                    SimpleNamespace(add_address=lambda pool:None),object(),confirmations,int(NOW)+10)
            with patch.object(runner,'CANDIDATE_HISTORY',history), \
                    patch.object(history,'events',side_effect=cancel_after_read), \
                    patch('sys.argv',['lane','--lane','pump','--state-root',str(root)]), \
                    patch('meme_machine.operational.bounded_provider.install'), \
                    patch.object(lane,'run_native',side_effect=restore):
                lane.main()
            # A completed bounded read must not lead to another candidate read
            # or reconstruction after TERM. No required coverage is ACKed early.
            self.assertEqual(reads,['first'])
            self.assertEqual(created,{})
            final=json.loads((root/'pump/health.json').read_text())
            self.assertEqual(final['phase'],'STOPPED');self.assertIs(final['reconciled'],False)
            self.assertEqual(final['native_recent_operations'][-1]['operation'],
                'pump.observed_candidates_restore')
            self.assertEqual(final['native_recent_operations'][-1]['state'],'CANCELLED')
            self.assertEqual(retained(),before)
            self.assertEqual(state.writer.db.execute('SELECT id,hash,consumed FROM candidate_history_outbox '
                'ORDER BY id').fetchall(),pending)
            history.close()
            stop.requested.clear()
            with closing(CandidateHistory(candidate_path,clock=lambda:NOW)) as resumed, \
                    patch.object(runner,'CANDIDATE_HISTORY',resumed):
                self.assertEqual(runner._restore_observed_pump_candidates(created,postgrad,
                    SimpleNamespace(add_address=lambda pool:None),object(),
                    ConfirmationBook({'cohort':[]},1),int(NOW)+10),2)
                self.assertEqual(set(created),{'first','second'})
                self.assertEqual(len(resumed.events('pump','later-survivor')),1)
                self.assertEqual(resumed.db.execute('SELECT status FROM work WHERE id=?',(job,)).fetchone()[0],
                    'pending')
                self.assertTrue(resumed.db.execute('SELECT 1 FROM work_history_requirements '
                    'WHERE work_id=?',(job,)).fetchone())
            self.assertEqual(state.writer.db.execute('SELECT id,hash,consumed FROM candidate_history_outbox '
                'ORDER BY id').fetchall(),pending)

    def test_observed_restore_does_not_enumerate_when_cancellation_already_requested(self):
        from meme_machine.lanes.pump import runner
        from unittest.mock import Mock
        history=Mock();history.candidates.return_value=[];stop.requested.set()
        with patch.object(runner,'CANDIDATE_HISTORY',history):
            with self.assertRaises(stop.Shutdown):
                runner._restore_observed_pump_candidates({},{},Mock(),object(),Mock(),1000)
        history.candidates.assert_not_called();history.events.assert_not_called()

    def test_actual_native_heartbeat_retains_operation_when_TERM_precedes_first_sample(self):
        from meme_machine.lanes.pump import runner
        captured=[];seen=threading.Event();original_health=lane.health
        def record(root,name,phase,**facts):
            original_health(root,name,phase,**facts)
            if facts.get('native_operation'):
                captured.append(dict(phase=phase,**facts));seen.set()
        def cancelled(**kwargs):
            with status.operation('pump.accounting_restore'):
                status.cancellation_signal(signal.SIGTERM);stop.requested.set()
                if not seen.wait(1):raise RuntimeError('early_TERM_operation_not_published')
                raise stop.Shutdown()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'pump').mkdir()
            (root/'pump'/'native-genesis.json').write_text(json.dumps(dict(capital=1)))
            pending=root/'pump'/'retained-pending.json'
            pending.write_text('accepted-evidence-awaiting-history');before=pending.read_bytes()
            with patch('sys.argv',['lane','--lane','pump','--state-root',str(root)]), \
                    patch('meme_machine.operational.bounded_provider.install'), \
                    patch.object(runner,'main',side_effect=cancelled), \
                    patch.object(runner,'INITIAL_LAMPORTS',runner.INITIAL_LAMPORTS), \
                    patch.object(runner,'ENTRY_BUDGET',runner.ENTRY_BUDGET), \
                    patch.object(lane,'health',side_effect=record):
                lane.main()
            final=json.loads((root/'pump'/'health.json').read_text())
            self.assertEqual(pending.read_bytes(),before)
        self.assertEqual(len(captured),1)
        self.assertEqual(captured[0]['native_operation']['operation'],'pump.accounting_restore')
        self.assertEqual(captured[0]['native_operation']['native_thread_id'],threading.get_native_id())
        self.assertEqual(captured[0]['cancellation_signal']['signal'],signal.SIGTERM)
        self.assertIs(captured[0]['reconciled'],False)
        self.assertEqual(final['phase'],'STOPPED');self.assertIs(final['reconciled'],False)
        self.assertEqual(final['native_recent_operations'][-1]['state'],'CANCELLED')

    def test_requested_heartbeat_cannot_overwrite_concurrent_terminal_health(self):
        published=[];entered=threading.Event();release=threading.Event()
        def record(root,name,phase,**facts):
            if phase!='STOPPED':
                entered.set()
                if not release.wait(1):raise RuntimeError('publication_fixture_timeout')
            published.append(dict(phase=phase,**facts))
        publish=lane.NativeHealthPublisher('/disposable','pump')
        stop.requested.set()
        with patch.object(lane,'health',side_effect=record):
            with status.operation('pump.accounting_restore'):
                heartbeat=threading.Thread(target=publish.heartbeat,args=(stop.requested,status))
                heartbeat.start();self.assertTrue(entered.wait(1))
                terminal=threading.Thread(target=publish,args=('STOPPED',),kwargs=dict(reconciled=False))
                terminal.start();self.assertTrue(publish.terminal.wait(1));release.set()
                heartbeat.join(1);terminal.join(1)
            publish.heartbeat(stop.requested,status)
        self.assertFalse(heartbeat.is_alive());self.assertFalse(terminal.is_alive())
        self.assertEqual([r['phase'] for r in published],['RECONCILING','STOPPED'])
        self.assertIs(published[-1]['reconciled'],False)

    def test_native_heartbeat_continues_changed_operation_after_TERM_until_terminal(self):
        captured=[];first=threading.Event();changed=threading.Event();errors=[]
        original_health=lane.health
        def record(root,name,phase,**facts):
            original_health(root,name,phase,**facts)
            captured.append((time.monotonic(),dict(phase=phase,**facts)))
            operation=facts.get('native_operation',{}).get('operation')
            if operation=='pump.accounting_restore':first.set()
            if operation=='pump.observed_candidate_events':changed.set()
        status.update('RECONCILING',reconciled=False)
        original_progress=status.snapshot()['progress_at']
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'pump').mkdir()
            publish=lane.NativeHealthPublisher(root,'pump')
            def heartbeat():
                try:publish.heartbeat(stop.requested,status)
                except BaseException as error:errors.append(error)
            thread=threading.Thread(target=heartbeat)
            with patch.object(lane,'health',side_effect=record):
                try:
                    with status.operation('pump.accounting_restore'):
                        thread.start()
                        status.cancellation_signal(signal.SIGTERM);stop.requested.set()
                        self.assertTrue(first.wait(1),'first_TERM_snapshot_missing')
                    with status.operation('pump.observed_candidate_events'):
                        self.assertTrue(changed.wait(4),'post_TERM_operation_snapshot_missing')
                        row=json.loads((root/'pump'/'health.json').read_text())
                        self.assertEqual(row['native_operation']['operation'],'pump.observed_candidate_events')
                        self.assertEqual(row['cancellation_signal']['signal'],signal.SIGTERM)
                        self.assertIs(row['reconciled'],False)
                        self.assertEqual(row['progress_at'],original_progress)
                        publish('STOPPED',reconciled=False)
                    thread.join(1)
                    terminal=json.loads((root/'pump'/'health.json').read_text())
                    self.assertEqual(terminal['phase'],'STOPPED')
                    self.assertIs(terminal['reconciled'],False)
                    publish('RECONCILING',reconciled=False)
                    self.assertEqual(json.loads((root/'pump'/'health.json').read_text()),terminal)
                finally:
                    publish.terminal.set();thread.join(1)
        self.assertFalse(thread.is_alive());self.assertEqual(errors,[])
        samples=[(at,row) for at,row in captured if row['phase']!='STOPPED']
        self.assertEqual(len(samples),2)
        self.assertGreaterEqual(samples[1][0]-samples[0][0],1.9)
        self.assertTrue(all(row['progress_at']==original_progress for _,row in samples))

    def test_native_heartbeat_after_TERM_waits_on_terminal_at_original_cadence(self):
        waits=[];published=[]
        class Terminal:
            value=False
            def is_set(self):return self.value
            def set(self):self.value=True
            def wait(self,seconds):
                waits.append(('terminal',seconds))
                return self.value
        requested=SimpleNamespace(wait=lambda seconds:waits.append(('requested',seconds)) or True)
        publish=lane.NativeHealthPublisher('/disposable','pump');publish.terminal=Terminal()
        snapshots=iter([
            dict(phase='RECONCILING',reconciled=False,progress_at=7,
                native_operation=dict(operation='pump.accounting_restore')),
            dict(phase='RECONCILING',reconciled=False,progress_at=7,
                native_operation=dict(operation='pump.observed_candidate_events'))])
        def record(root,name,phase,**facts):
            published.append(dict(phase=phase,**facts))
            if len(published)==2:publish.terminal.set()
        with patch.object(lane,'health',side_effect=record):
            publish.heartbeat(requested,SimpleNamespace(snapshot=lambda:next(snapshots)))
        self.assertEqual(len(published),2)
        self.assertEqual(waits,[('requested',2),('terminal',2)])
        self.assertTrue(all(row['reconciled'] is False and row['progress_at']==7 for row in published))

    def test_health_write_failure_preserves_original_startup_exception(self):
        error=RuntimeError('original-startup-error-with-private-context')
        def failed(root,name,publish):
            with status.operation('pump.accounting_restore'):
                facts=status.snapshot();facts.pop('phase',None)
                publish('RECONCILING',**facts)
                raise error
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'pump').mkdir()
            with patch('sys.argv',['lane','--lane','pump','--state-root',str(root)]), \
                    patch('meme_machine.operational.bounded_provider.install'), \
                    patch.object(lane,'run_native',side_effect=failed), \
                    patch.object(lane,'health',side_effect=OSError('optional-private-record-failure')), \
                    patch('builtins.print') as logged:
                with self.assertRaises(RuntimeError) as caught:lane.main()
        self.assertIs(caught.exception,error)
        self.assertNotIn('optional-private-record-failure',str(logged.call_args_list))

    def test_health_publication_lock_wait_is_bounded_and_optional(self):
        publish=lane.NativeHealthPublisher('/disposable','pump')
        waits=[]
        lock=SimpleNamespace(acquire=lambda **kwargs:waits.append(kwargs) or False,release=lambda:None)
        with patch.object(publish,'lock',lock),patch.object(lane,'health') as record:
            publish('STOPPED',reconciled=False)
        self.assertEqual(waits,[dict(timeout=.05)])
        self.assertTrue(publish.terminal.is_set());record.assert_not_called()

    def test_cancelled_native_constructor_preserves_pending_journal_and_fresh_resume(self):
        from meme_machine.shared_capital import runtime
        from meme_machine.lanes.pump import runner
        from tests.shared_capital_support import Harness
        with tempfile.TemporaryDirectory() as directory:
            h=Harness(directory)
            try:
                h.allocate([('pump_current',{})])
                before=h.authority.snapshot()['ledger']
                self.assertTrue(before['reservations'])
                journal=h.authority.db.execute('SELECT * FROM shared_capital_events ORDER BY sequence').fetchall()
                projection=h.authority.db.execute('SELECT * FROM shared_capital_projection').fetchall()
                applied=[];opened=[];original_apply=runtime.RuntimeCapital._apply
                original_connect=runtime.sqlite3.connect
                def connect(*args,**kwargs):
                    db=original_connect(*args,**kwargs)
                    if Path(args[0])==h.path:opened.append(db)
                    return db
                def apply(owner,state,event):
                    result=original_apply(owner,state,event);applied.append(event)
                    stop.requested.set();return result
                with patch.object(runtime.RuntimeCapital,'_apply',apply), \
                        patch.object(runtime.sqlite3,'connect',side_effect=connect):
                    with self.assertRaises(stop.Shutdown):
                        runner._startup_work('pump.accounting_restore',runtime.connection,h.path)
                self.assertEqual(len(applied),1)
                self.assertEqual(len(opened),1)
                with self.assertRaises(sqlite3.ProgrammingError):opened[0].execute('SELECT 1')
                self.assertFalse(status.snapshot()['reconciled'])
                self.assertEqual(status.snapshot()['native_recent_operations'][-1]['state'],'CANCELLED')
                self.assertEqual(h.authority.db.execute('SELECT * FROM shared_capital_events ORDER BY sequence').fetchall(),journal)
                self.assertEqual(h.authority.db.execute('SELECT * FROM shared_capital_projection').fetchall(),projection)
                stop.requested.clear();resumed=[]
                def full(owner,state,event):
                    resumed.append(event);return original_apply(owner,state,event)
                with patch.object(runtime.RuntimeCapital,'_apply',full):
                    restored=runtime.RuntimeCapital(h.path)
                try:
                    self.assertEqual(len(resumed),len(journal))
                    self.assertEqual(restored.ledger(),before)
                    self.assertIsNone(restored._startup_replay_cancel)
                finally:restored.close()
                self.assertEqual(h.authority.db.execute('SELECT * FROM shared_capital_events ORDER BY sequence').fetchall(),journal)
            finally:h.close()

    def test_warm_prefix_startup_cancellation_does_not_create_partial_verification(self):
        from meme_machine.shared_capital import runtime
        from tests.shared_capital_support import Harness
        with tempfile.TemporaryDirectory() as directory:
            h=Harness(directory)
            try:
                h.allocate([('pump_current',{})])
                owner=runtime.RuntimeCapital(h.path)
                try:before=owner.verify_replay()
                finally:owner.close()
                checks=[]
                def cancel():
                    checks.append(True);return len(checks)==3
                entered=[];prefix=runtime.RuntimeCapital._authenticated_replay_prefix
                def observed(owner,key):
                    entered.append(key);return prefix(owner,key)
                with patch.object(runtime.RuntimeCapital,'_authenticated_replay_prefix',observed):
                    with self.assertRaises(stop.Shutdown):runtime.RuntimeCapital(h.path,startup_cancel=cancel)
                self.assertEqual(len(entered),1);self.assertEqual(len(checks),3)
                restored=runtime.RuntimeCapital(h.path)
                try:self.assertEqual(restored.verify_replay(),before)
                finally:restored.close()
            finally:h.close()

    def test_outside_startup_scope_requested_shutdown_does_not_abort_monetary_settlement(self):
        from meme_machine.shared_capital import runtime
        from tests.shared_capital_support import Harness
        with tempfile.TemporaryDirectory() as directory:
            h=Harness(directory)
            try:
                requests,_=h.allocate([('pump_current',{})]);life,_=h.fill(requests[0])
                h.authority.close();stop.requested.set()
                # No native-startup scope: this fresh owner must fully verify
                # and retain the existing protection/settlement write path.
                h.authority=runtime.RuntimeCapital(h.path)
                self.assertIsNone(h.authority._startup_replay_cancel)
                h.realize('pump_current',life,'6.25',terminal=True)
                self.assertEqual(h.authority.ledger()['positions'][life]['status'],'SETTLED')
                self.assertTrue(h.authority.verify_replay()['conservation'])
            finally:h.close()

    def test_cancelled_constructor_does_not_bypass_corruption_on_resume(self):
        from meme_machine.shared_capital import runtime,CapitalError
        from tests.shared_capital_support import Harness
        with tempfile.TemporaryDirectory() as directory:
            h=Harness(directory)
            try:
                with self.assertRaises(stop.Shutdown):runtime.RuntimeCapital(h.path,startup_cancel=lambda:True)
                h.authority.db.execute('DROP TRIGGER shared_capital_no_update')
                h.authority.db.execute("UPDATE shared_capital_events SET body=body||' ' WHERE sequence=1")
                with self.assertRaisesRegex(CapitalError,'capital_journal_integrity'):
                    runtime.RuntimeCapital(h.path)
            finally:h.close()

    def test_native_attach_close_failure_preserves_original_shutdown(self):
        from meme_machine.lanes.pump.paper_accounting import PaperBook
        from meme_machine.lanes.pump.pump_acceleration_strategy import policy_hash,STRATEGY_ID
        original=stop.Shutdown();closed=[];connect=sqlite3.connect
        class BrokenClose(sqlite3.Connection):
            def close(self):
                super().close();closed.append(True)
                raise OSError('optional-close-private-context')
        def opened(*args,**kwargs):return connect(*args,factory=BrokenClose,**kwargs)
        with tempfile.TemporaryDirectory() as directory, \
                patch('meme_machine.lanes.pump.paper_accounting.sqlite3.connect',side_effect=opened), \
                patch('meme_machine.runtime.native_boundary.attach',side_effect=original):
            with self.assertRaises(stop.Shutdown) as caught:
                PaperBook(Path(directory)/'paper.sqlite',run_id='fixture',lane=STRATEGY_ID,
                    policy_hash=policy_hash(),initial=100)
        self.assertIs(caught.exception,original);self.assertEqual(closed,[True])

    def test_supervisor_retains_actual_signal_and_wait_origin_without_changing_deadlines(self):
        clock=[0.0];sent=[];waits=[]
        def child(pid):
            result=[None]
            def wait(*,timeout):
                waits.append((pid,timeout))
                if pid==11 and len([p for p,_ in waits if p==pid])==1:
                    clock[0]+=timeout;raise subprocess.TimeoutExpired('fixture-pump',timeout)
                result[0]=-9 if pid==11 else 0
                return result[0]
            return SimpleNamespace(pid=pid,poll=lambda:result[0],wait=wait)
        service=Supervisor('/unused-disposable-fixture',offline=True)
        service.run_id='offline-cancel';service.processes={'pump':child(11),'pons':child(22)}
        with patch('meme_machine.operational.supervisor.time.monotonic',side_effect=lambda:clock[0]), \
                patch('meme_machine.operational.supervisor.os.killpg',side_effect=lambda p,s:sent.append((p,s))):
            service.stop_lanes()
        self.assertEqual(sent,[(11,signal.SIGTERM),(22,signal.SIGTERM),(11,signal.SIGKILL)])
        self.assertEqual(waits,[(11,15),(11,5),(22,.1)])
        facts=service.native_shutdown
        kill=next(row for row in facts if row['operation']=='signal_sent' and row['signal']==signal.SIGKILL)
        self.assertEqual(kill['caller_pid'],os.getpid())
        self.assertEqual(kill['caller_native_thread_id'],threading.get_native_id())
        self.assertEqual(kill['target_pid'],11);self.assertEqual(kill['lane'],'pump')
        self.assertEqual(facts[-1]['exit_code'],0)

    def test_shutdown_optional_recorder_error_does_not_change_process_stop(self):
        sent=[];proc=SimpleNamespace(pid=12,poll=lambda:None,wait=lambda **kw:0)
        def unavailable(row):raise OSError('record-only-failure')
        with patch('meme_machine.operational.supervisor.os.killpg',side_effect=lambda p,s:sent.append((p,s))):
            Supervisor.stop_process(proc,observe=unavailable)
        self.assertEqual(sent,[(12,signal.SIGTERM)])
