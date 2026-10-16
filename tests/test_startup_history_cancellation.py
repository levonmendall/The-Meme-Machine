"""Actual SQLite-step TERM cancellation; disposable native startup reads only.

The deliberately expensive view retains the real CandidateHistory query and
SQLite VM. It has no provider, financial journal or economic qualification.
Pons tests establish its existing read-only replay scope and attribution only;
they do not establish cancellation inside its unobserved Plane/recovery reads.
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
