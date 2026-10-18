"""Actual SQLite-step TERM cancellation; disposable native startup reads only.

The deliberately expensive view retains the real CandidateHistory query and
SQLite VM. It has no provider, financial journal or economic qualification.
Pons audit cancellation additionally exercises the real Broker renewal and
candidate-transaction rollback; it makes no provider or throughput claim.
"""
from collections import deque
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import select
import signal
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from meme_machine.runtime.candidate_history import CandidateHistory
from meme_machine.runtime import status, stop


ROOT = Path(__file__).resolve().parents[1]
SQLITE_CHILD = r"""
import hashlib,json,signal,sys
from pathlib import Path
from operational.tests import network_guard
network_guard()
from meme_machine.runtime.candidate_history import CandidateHistory
from meme_machine.runtime import status,stop
path,mode,query=sys.argv[1:]
history=CandidateHistory(path)
history.observe('pump','retained',surface='pump',observed_at=100)
history.append_event('pump','retained',identity='retained-event',slot=1,
    transaction_index=0,event_index=0,market_time=100,kind='pump_create',
    payload=dict(event_type='create',mint='retained'))
history.enqueue('pump','retained',kind='warmup',ready_at=100,deadline=200,estimate_seconds=1)
history.db.execute('ALTER TABLE events RENAME TO retained_events')
# SQLite must evaluate this scalar aggregate before it can return the first
# event-kind match. No Python UDF, sleep, inserted delay, or synthetic row yield.
history.db.execute('''CREATE VIEW events AS WITH RECURSIVE expensive(n) AS
    (VALUES(0) UNION ALL SELECT n+1 FROM expensive WHERE n<100000000)
    SELECT lane,candidate,identity,slot,transaction_index,event_index,market_time,
    CASE WHEN (SELECT MAX(n) FROM expensive)>=0 THEN kind END AS kind,body,hash
    FROM retained_events''')
def facts():
    values={name:history.db.execute('SELECT * FROM '+name+' ORDER BY rowid').fetchall()
        for name in ('candidates','retained_events','work','history_coverage')}
    return hashlib.sha256(json.dumps(values,sort_keys=True,separators=(',',':')).encode()).hexdigest()
print('SEEDED '+facts(),flush=True)
def shutdown(signum,_frame):
    status.cancellation_signal(signum)
    stop.requested.set()
signal.signal(signal.SIGTERM,shutdown)
calls=0;marked=False
def marker():
    global marked
    if not marked:
        marked=True
        print('SQLITE_VM_ENTERED',flush=True)
    return 0
def cancelled():
    global calls
    calls+=1
    # The first call is the initial Python check. Every later call here is
    # SQLite VM progress until cancellation or first-row materialization.
    if calls==2:marker()
    return stop.requested.is_set()
if mode=='ordinary':history.db.set_progress_handler(marker,1000)
try:
    options={} if mode=='ordinary' else dict(cancelled=cancelled)
    if query=='candidates':history.candidates(lane='pump',event_prefix='pump_',**options)
    else:history.events('pump','retained',kind_prefix='pump_',**options)
except stop.Shutdown:
    # More than 1000 VM steps succeed despite requested remaining set: this
    # independently detects a leaked cancellation handler on the connection.
    probe=history.db.execute('WITH RECURSIVE p(n) AS (VALUES(0) UNION ALL '
        'SELECT n+1 FROM p WHERE n<10000) SELECT SUM(n) FROM p').fetchone()[0]
    print('CANCELLED '+json.dumps(dict(signal=status.snapshot()['cancellation_signal']['signal'],
        facts=facts(),in_transaction=history.db.in_transaction,probe=probe)),flush=True)
    history.close()
else:
    print('UNEXPECTED_COMPLETE',flush=True)
"""


PONS_AUDIT_CHILD = r"""
import hashlib,json,os,signal,sys
from pathlib import Path
from operational.tests import network_guard
network_guard()
from meme_machine.runtime import status,stop
from meme_machine.runtime.robinhood import pons
from meme_machine.runtime.robinhood.plane import Plane,canonical,digest
from meme_machine.lanes.pons.pons_selective_continuation import POLICY_HASH
from meme_machine.lanes.pons.abi import topic
from tests.lanes.pons.test_pons_candidate_plane import event
path=Path(sys.argv[1])
os.environ.pop('MM_OPERATIONAL_PHASE',None)
os.environ.pop('MM_PAPER_EPOCH',None)
broker=pons.Broker(path,POLICY_HASH,clock=lambda:100.)
nomination=event();nomination['topics']=[topic('CurveBuy(address,address,uint256,uint256,uint256,uint256)')]
broker.enqueue(nomination)
key=broker.identity(nomination)
old=dict(broker.policy,adapter_source='retained-previous-adapter')
watch=json.loads(broker.plane.db.execute('SELECT body FROM pons_current_watch WHERE candidate=?',(key,)).fetchone()[0])
watch['interpretation']=old
broker.plane.db.execute('UPDATE candidates SET interpretation=? WHERE id=?',(canonical(old),key))
broker.plane.db.execute('UPDATE pons_current_watch SET body=?,hash=? WHERE candidate=?',
    (canonical(watch),digest(watch),key))
# A retained inactive row makes the production audit predicate meaningful.
broker.plane.observe('retained-inactive','ramses','retained-observation',{},ordering=(1,),
    watermark={},interpretation={},observed=100,deadline=105,priority=4)
db=broker.plane.db
def install_audit_view(connection):
    connection.execute('ALTER TABLE transitions RENAME TO retained_transitions')
    # The real audit cutoff SELECT must evaluate this SQLite aggregate before
    # returning its filtered boundary. MAX(seq) and INSERT remain ordinary;
    # no Python UDF, artificial callback or provider creates the expensive step.
    connection.execute('''CREATE VIEW transitions AS WITH RECURSIVE expensive(n) AS
        (VALUES(0) UNION ALL SELECT n+1 FROM expensive WHERE n<100000000)
        SELECT seq,CASE WHEN (SELECT MAX(n) FROM expensive)>=0 THEN candidate END AS candidate,
            generation,at,kind,reason,watermark,interpretation,details FROM retained_transitions''')
    connection.execute('''CREATE TRIGGER insert_transition INSTEAD OF INSERT ON transitions BEGIN
        INSERT INTO retained_transitions VALUES(NEW.seq,NEW.candidate,NEW.generation,NEW.at,
            NEW.kind,NEW.reason,NEW.watermark,NEW.interpretation,NEW.details); END''')
def restore_audit_table(connection):
    connection.execute('DROP VIEW transitions')
    connection.execute('ALTER TABLE retained_transitions RENAME TO transitions')
install_audit_view(db)
def facts(connection):
    values={name:[tuple(r) for r in connection.execute('SELECT * FROM '+name+' ORDER BY rowid')]
        for name in ('candidates','pons_current_watch','observations','retained_transitions','runtime')}
    values['triggers']=[tuple(r) for r in connection.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' ORDER BY name")]
    return hashlib.sha256(canonical(values).encode()).hexdigest()
before=facts(db)
# A native constructor must see its actual table and covering index. Restore
# that schema for close/reopen, then reinstall the identical audit fixture only
# after Plane has completed its unchanged real constructor.
restore_audit_table(db)
broker.close()
os.environ['MM_OPERATIONAL_PHASE']='OBSERVATION'
captured=[]
def captured_plane(*args,**kwargs):
    # Preserve the exact native owner type and its full real constructor.
    # Only the disposable audit view is installed at the returned-owner seam.
    plane=Plane(*args,**kwargs)
    if not captured:install_audit_view(plane.db)
    captured.append(plane)
    return plane
pons.Plane=captured_plane
def shutdown(signum,_frame):
    status.cancellation_signal(signum);stop.requested.set()
signal.signal(signal.SIGTERM,shutdown)
marked=False
def cancelled():
    global marked
    if sys._getframe(1).f_code.co_name=='<lambda>' and not marked:
        marked=True;print('AUDIT_SQLITE_VM_ENTERED',flush=True)
    return stop.requested.is_set()
print('SEEDED '+before,flush=True)
try:
    pons.Broker(path,POLICY_HASH,clock=lambda:100.,startup_cancel=cancelled)
except stop.Shutdown:
    plane=captured[-1];db=plane.db
    # Requested remains true: success proves no handler leaked into subsequent
    # queries or rollback/commit, and no interrupted candidate write committed.
    probe=db.execute('WITH RECURSIVE p(n) AS (VALUES(0) UNION ALL SELECT n+1 FROM p WHERE n<10000) SELECT SUM(n) FROM p').fetchone()[0]
    result=dict(signal=status.snapshot()['cancellation_signal']['signal'],facts=facts(db),
        in_transaction=db.in_transaction,probe=probe,
        trigger=bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='history_no_delete'").fetchone()))
    restore_audit_table(db)
    plane.close();stop.requested.clear()
    resumed=pons.Broker(path,POLICY_HASH,clock=lambda:100.,startup_cancel=lambda:False)
    row=resumed.plane.get(key)
    result.update(restarted=True,generation=row['generation'],pending=row['pending'],
        reason=row['reason'],interpretation_current=json.loads(row['interpretation'])==resumed.policy,
        original_observed=row['observed'],original_deadline=row['deadline'])
    resumed.close()
    print('CANCELLED '+json.dumps(result),flush=True)
else:
    print('UNEXPECTED_COMPLETE',flush=True)
"""


class StartupHistoryCancellationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.was_requested = stop.requested.is_set()
        stop.requested.clear()
        self.prior_status = (dict(status.state), list(status._operations), status._completed, status._signal)
        status.state = dict(phase='RECONCILING', reconciled=False)
        status._operations = []
        status._completed = deque(maxlen=8)
        status._signal = None

    def tearDown(self):
        status.state, status._operations, status._completed, status._signal = self.prior_status
        if self.was_requested:
            stop.requested.set()
        else:
            stop.requested.clear()

    def history(self):
        history = CandidateHistory(self.root / 'history.sqlite')
        self.addCleanup(history.close)
        history.observe('pump', 'retained', surface='pump', observed_at=100)
        history.append_event('pump', 'retained', identity='event', slot=1, transaction_index=0,
            event_index=0, market_time=100, kind='pump_create', payload=dict(event_type='create'))
        return history

    def test_actual_sigterm_during_sqlite_vm_cancels_startup_but_ordinary_read_does_not(self):
        for query in ('candidates', 'events'):
            for mode in ('ordinary', 'startup'):
                with self.subTest(query=query, mode=mode):
                    path = self.root / (query + '-' + mode + '.sqlite')
                    child = subprocess.Popen([sys.executable, '-u', '-c', SQLITE_CHILD,
                        str(path), mode, query], cwd=ROOT, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, bufsize=0)
                    try:
                        self.assertTrue(select.select([child.stdout], [], [], 5)[0], 'child did not seed')
                        seeded = child.stdout.readline().decode().strip()
                        self.assertTrue(seeded.startswith('SEEDED '), seeded)
                        self.assertTrue(select.select([child.stdout], [], [], 5)[0], 'actual SQLite VM not reached')
                        self.assertEqual(child.stdout.readline().decode().strip(), 'SQLITE_VM_ENTERED')
                        os.kill(child.pid, signal.SIGTERM)
                        if mode == 'ordinary':
                            with self.assertRaises(subprocess.TimeoutExpired):
                                child.wait(timeout=.3)
                            child.kill()
                            child.communicate(timeout=3)
                            self.assertEqual(child.returncode, -signal.SIGKILL)
                        else:
                            output, errors = child.communicate(timeout=3)
                            output, errors = output.decode(), errors.decode()
                            self.assertEqual(child.returncode, 0, errors)
                            self.assertTrue(output.startswith('CANCELLED '), output)
                            result = json.loads(output.removeprefix('CANCELLED '))
                            self.assertEqual(result['signal'], signal.SIGTERM)
                            self.assertEqual(result['facts'], seeded.removeprefix('SEEDED '))
                            self.assertFalse(result['in_transaction'])
                            self.assertEqual(result['probe'], 50005000)
                        # Both paths preserve every seeded row, including work
                        # which was neither consumed nor falsely completed.
                        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
                            values = {name: db.execute('SELECT * FROM ' + name + ' ORDER BY rowid').fetchall()
                                for name in ('candidates', 'retained_events', 'work', 'history_coverage')}
                        after = hashlib.sha256(json.dumps(values, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
                        self.assertEqual(after, seeded.removeprefix('SEEDED '))
                    finally:
                        if child.poll() is None:
                            child.kill()
                            child.communicate(timeout=3)
                        child.stdout.close()
                        child.stderr.close()

    def test_existing_rows_and_errors_are_unchanged_without_cancellation(self):
        history = self.history()
        self.assertEqual(history.candidates(lane='pump'), history.candidates(lane='pump', cancelled=lambda:False))
        self.assertEqual(history.events('pump', 'retained'), history.events('pump', 'retained', cancelled=lambda:False))
        history.db.execute("UPDATE candidates SET hash='corrupt' WHERE candidate='retained'")
        with self.assertRaisesRegex(ValueError, 'candidate_history_corruption'):
            history.candidates(lane='pump', cancelled=lambda:False)
        # Handler cleanup leaves unrelated ordinary reads available.
        self.assertEqual(history.db.execute('SELECT COUNT(*) FROM candidates').fetchone()[0], 1)

    def test_pons_actual_sigterm_in_audit_select_rolls_back_renewal_and_restarts(self):
        child=subprocess.Popen([sys.executable,'-u','-c',PONS_AUDIT_CHILD,
            str(self.root/'pons.sqlite')],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,bufsize=0)
        try:
            self.assertTrue(select.select([child.stdout],[],[],5)[0],'Pons child did not seed')
            seeded=child.stdout.readline().decode().strip()
            self.assertTrue(seeded.startswith('SEEDED '),seeded)
            self.assertTrue(select.select([child.stdout],[],[],5)[0],'audit SQLite VM not reached')
            marker=child.stdout.readline().decode().strip()
            if not marker:
                output,errors=child.communicate(timeout=3)
                self.fail('Pons child exited before audit SQLite VM: '+errors.decode()+output.decode())
            self.assertEqual(marker,'AUDIT_SQLITE_VM_ENTERED')
            os.kill(child.pid,signal.SIGTERM)
            output,errors=child.communicate(timeout=3)
            self.assertEqual(child.returncode,0,errors.decode())
            self.assertTrue(output.startswith(b'CANCELLED '),output)
            result=json.loads(output.removeprefix(b'CANCELLED '))
            self.assertEqual(result['signal'],signal.SIGTERM)
            self.assertEqual(result['facts'],seeded.removeprefix('SEEDED '))
            self.assertFalse(result['in_transaction'])
            self.assertEqual(result['probe'],50005000)
            self.assertTrue(result['trigger'])
            self.assertTrue(result['restarted'])
            self.assertEqual(result['generation'],2)
            self.assertEqual(result['pending'],0)
            self.assertEqual(result['reason'],'adapter_change_requires_fresh_canonical_state')
            self.assertTrue(result['interpretation_current'])
            self.assertEqual((result['original_observed'],result['original_deadline']),(100.,105.))
        finally:
            if child.poll() is None:child.kill();child.communicate(timeout=3)
            child.stdout.close();child.stderr.close()

    def test_pons_audit_interrupt_is_shutdown_only_when_requested_and_never_wraps_writes(self):
        from meme_machine.runtime.storage import _audit_boundary,audit_ring
        for requested in (False,True):
            for code in (sqlite3.SQLITE_INTERRUPT,sqlite3.SQLITE_BUSY,sqlite3.SQLITE_IOERR):
                with self.subTest(requested=requested,code=code):
                    error=sqlite3.OperationalError('original audit failure');error.sqlite_errorcode=code
                    db=Mock();db.execute.side_effect=error
                    # Initial check passes; requested status changes only once
                    # the real read boundary has been entered.
                    checks=iter((False,requested))
                    expected=stop.Shutdown if requested and code==sqlite3.SQLITE_INTERRUPT else sqlite3.OperationalError
                    with self.assertRaises(expected) as caught:
                        _audit_boundary(db,'transitions',limit=2,key='seq',where='1=1',
                            startup_cancel=lambda:next(checks))
                    if expected is sqlite3.OperationalError:self.assertIs(caught.exception,error)
                    db.set_progress_handler.assert_any_call(None,0)
        class TrackedDB:
            def __init__(self):
                self.db=sqlite3.connect(':memory:',isolation_level=None);self.handler=False;self.writes=[]
            @property
            def in_transaction(self):return self.db.in_transaction
            def set_progress_handler(self,callback,steps):
                self.handler=callback is not None;return self.db.set_progress_handler(callback,steps)
            def execute(self,sql,*args):
                if sql.split()[0] in ('BEGIN','INSERT','UPDATE','DELETE','DROP','CREATE','COMMIT','ROLLBACK'):
                    self.writes.append((sql.split()[0],self.handler))
                return self.db.execute(sql,*args)
        db=TrackedDB();self.addCleanup(db.db.close)
        db.execute('CREATE TABLE transitions(seq INTEGER PRIMARY KEY,body TEXT)')
        for n in range(4):db.execute('INSERT INTO transitions VALUES(?,?)',(n,'retained'))
        db.execute("CREATE TRIGGER history_no_delete BEFORE DELETE ON transitions BEGIN SELECT RAISE(ABORT,'append_only'); END")
        audit_ring(db,'transitions','history_no_delete',limit=2,startup_cancel=lambda:False)
        self.assertEqual(db.db.execute('SELECT seq FROM transitions ORDER BY seq').fetchall(),[(2,),(3,)])
        self.assertTrue(db.writes)
        self.assertTrue(all(not handler for _,handler in db.writes),db.writes)

    def test_pons_candidate_transaction_preserves_shutdown_after_sqlite_auto_rollback(self):
        from meme_machine.runtime.robinhood.plane import Plane
        plane=Plane(self.root/'rollback.sqlite');self.addCleanup(plane.close)
        failure=stop.Shutdown()
        with self.assertRaises(stop.Shutdown) as caught:
            with plane.transaction():
                plane.db.execute('ROLLBACK')
                raise failure
        self.assertIs(caught.exception,failure)
        self.assertFalse(plane.db.in_transaction)

    def test_already_requested_cancellation_does_not_execute_read(self):
        history = self.history()
        with patch.object(history, 'db', Mock()) as db:
            for read in (lambda:history.candidates(cancelled=lambda:True),
                    lambda:history.events('pump', 'retained', cancelled=lambda:True)):
                with self.assertRaises(stop.Shutdown):
                    read()
            db.execute.assert_not_called()
            db.set_progress_handler.assert_not_called()

    def test_unrelated_sqlite_interrupt_busy_and_io_failures_are_not_shutdown(self):
        history = self.history()
        for code in (sqlite3.SQLITE_INTERRUPT, sqlite3.SQLITE_BUSY, sqlite3.SQLITE_IOERR):
            with self.subTest(code=code):
                error = sqlite3.OperationalError('original failure')
                error.sqlite_errorcode = code
                db = Mock(in_transaction=False)
                db.execute.side_effect = error
                with patch.object(history, 'db', db):
                    with self.assertRaises(sqlite3.OperationalError) as caught:
                        history.candidates(cancelled=lambda:False)
                self.assertIs(caught.exception, error)
                db.set_progress_handler.assert_any_call(None, 0)

    def test_startup_cancel_handler_never_attaches_inside_mutation_transaction(self):
        history = self.history()
        with history.transaction():
            history.db.execute("UPDATE candidates SET last_observed=101 WHERE candidate='retained'")
            with self.assertRaisesRegex(ValueError, 'startup_read_requires_idle_connection'):
                history.candidates(cancelled=lambda:False)
            self.assertTrue(history.db.in_transaction)
        self.assertEqual(history.db.execute('SELECT last_observed FROM candidates').fetchone()[0], 101)

    def test_pons_cohort_recovery_checks_term_at_boundaries_and_records_existing_replay_scope(self):
        from meme_machine.lanes.pons import pons_selective_cohort as cohort
        from meme_machine.shared_capital import runtime
        progress = self.root / 'cohort-progress.json'
        progress.write_text('{}')
        seen = []
        def recover(*args, **kwargs):
            seen.append((runtime._STARTUP_REPLAY_CANCEL.get(), status.snapshot()))
            stop.requested.set()
            return {}
        with patch.object(cohort, 'ROOT', self.root), patch.object(cohort, 'PROGRESS', progress), \
                patch.object(cohort, 'recover_cohort', recover):
            stop.requested.set()
            with self.assertRaises(stop.Shutdown):
                cohort.run('offline-provider', campaign=True)
            self.assertEqual(seen, [])
            stop.requested.clear()
            with self.assertRaises(stop.Shutdown):
                cohort.run('offline-provider', campaign=True)
        self.assertEqual(len(seen), 1)
        callback, active = seen[0]
        self.assertTrue(callable(callback))
        self.assertTrue(callback())
        self.assertEqual(active['native_operation']['operation'], 'pons.cohort_recovery')
        self.assertFalse(active['reconciled'])
        self.assertIsNone(runtime._STARTUP_REPLAY_CANCEL.get())
        self.assertEqual(status.snapshot()['native_recent_operations'][-1]['operation'], 'pons.cohort_recovery')
        self.assertFalse(status.snapshot()['reconciled'])


if __name__ == '__main__':
    unittest.main()
