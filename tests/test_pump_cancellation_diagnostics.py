"""Disposable native cancellation/reporting coverage; no market or real state."""
from collections import deque
from contextlib import closing
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import tempfile
import threading
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
