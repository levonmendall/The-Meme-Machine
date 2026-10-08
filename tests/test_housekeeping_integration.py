"""Focused deterministic checks against the disposable patched native checkout."""
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from meme_machine.solana_evidence_plane import EvidenceUnavailable
from meme_machine.solana_evidence_control import PriorityOwner
from meme_machine.solana_evidence_service import ServiceState
from meme_machine.solana_maintenance_arbiter import MaintenanceArbiter, Need, ServiceLeases
from meme_machine.solana_maintenance_runtime import ArchiveFlight, MaintenanceRuntime
from meme_machine.solana_maintenance_state import NativeObservation
from tests.test_retention_outcomes import CONFIG, seed
from tests.test_production_maintenance_arbiter import native_runtime

SCOPE='program:meteora'


@contextmanager
def state():
    with tempfile.TemporaryDirectory() as td:
        s=ServiceState(Path(td)/'db',CONFIG)
        try:
            with patch('meme_machine.solana_evidence_service.time.time',return_value=1000):
                yield s
        finally:
            s.close()


def garbage(writer,n):
    with writer.transaction():
        writer.db.executemany('INSERT INTO archives VALUES(?,?,?,?)',
            [(f'gc-{i:05d}.gz','unused',0,0) for i in range(n)])
        writer.db.executemany('INSERT INTO hot_chunks VALUES(?,?)',
            [(f'gc-{i:05d}',b'orphan') for i in range(n)])
        writer.db.executemany('INSERT INTO address_keys VALUES(?,?)',
            [(100000+i,f'gc-address-{i:05d}') for i in range(n)])


def ledger(writer):
    return writer.db.execute("SELECT units,records FROM maintenance_progress "
        "WHERE scope='__housekeeping__' AND side='retirement'").fetchone()


def trigger_case(*, hk=7.7817, other=100., origin=None, recovery=None,
                 archive_ready=True, pending=True, housekeeping=1):
    now=100.
    r=MaintenanceRuntime.__new__(MaintenanceRuntime)
    r.generation='g';r.state=SimpleNamespace(fence=SimpleNamespace(session='g'))
    r.leases=ServiceLeases();r.arbiter=MaintenanceArbiter('g',r.leases)
    if origin is not None:r.arbiter.origin['retirement',SCOPE]=origin
    observation=NativeObservation('g',now,1000.,(),housekeeping,(),0,0.)
    r.last_observation=observation
    needs=[Need(SCOPE,'archive',1,1,now+100.,None,0),
           Need(SCOPE,'retirement',2000,2000,now+other,
                now+recovery if recovery is not None else None,
                1000 if recovery is not None else 0),
           Need('__housekeeping__','retirement',housekeeping,0,now+hk,None,0)]
    ready={'archive':archive_ready,'retirement':True}
    d=r.arbiter.choose(generation='g',as_of=now,now=now,needs=needs,ready=ready)
    f=ArchiveFlight(pending=((1,),{}) if pending else None,
                    submitted=now,generation='g')
    return r,d,observation,needs,ready,f


class EligibilityTests(unittest.TestCase):
    def promoted(self,**kwargs):
        r,d,o,n,ready,f=trigger_case(**kwargs)
        return r._housekeeping_first(d,o,n,ready,f)

    def test_receipt74_window_and_inclusive_peer_boundary(self):
        self.assertTrue(self.promoted())
        self.assertTrue(self.promoted(hk=9.))
        self.assertFalse(self.promoted(hk=9.000001))

    def test_no_prefix_without_an_admitted_retirement(self):
        r,d,o,n,ready,f=trigger_case()
        self.assertFalse(r._housekeeping_first(None,o,n,ready,f))
        self.assertFalse(r._housekeeping_first(replace(d),o,n,ready,f))
        self.assertFalse(r._housekeeping_first(replace(d,side='archive'),o,n,ready,f))
        r.arbiter.complete(d,100.,{})
        self.assertFalse(r._housekeeping_first(d,o,n,ready,f))

    def test_housekeeping_at_execution_boundary_is_not_promoted(self):
        r,d,o,n,ready,f=trigger_case()
        for headroom in (3.,2.999,0.):
            nn=[replace(x,safety_deadline=100.+headroom) if x.scope=='__housekeeping__'
                else x for x in n]
            self.assertFalse(r._housekeeping_first(d,o,nn,ready,f))

    def test_other_safety_blocker_including_peer_boundary(self):
        self.assertFalse(self.promoted(other=8.))
        self.assertFalse(self.promoted(other=9.))
        self.assertTrue(self.promoted(other=9.000001))

    def test_other_effective_drought_blocks_with_raw_safety_far_away(self):
        self.assertFalse(self.promoted(other=100.,origin=63.))  # 63+45=108
        self.assertFalse(self.promoted(other=100.,origin=64.))  # exactly 109

    def test_other_effective_recovery_blocks_with_raw_safety_far_away(self):
        self.assertFalse(self.promoted(other=100.,recovery=8.))
        self.assertFalse(self.promoted(other=100.,recovery=9.))

    def test_housekeeping_effective_drought_can_be_the_sole_blocker(self):
        r,d,o,n,ready,f=trigger_case(hk=100.)
        # Rechoose with the existing successful-service clock, not raw safety.
        if d is not None:r.arbiter.complete(d,100.,{})
        r.arbiter.origin['retirement','__housekeeping__']=62.7817
        d=r.arbiter.choose(generation='g',as_of=100.,now=100.,needs=n,ready=ready)
        self.assertEqual(d.side,'retirement')
        self.assertTrue(r._housekeeping_first(d,o,n,ready,f))

    def test_unready_absent_receipt_or_native_demand(self):
        self.assertFalse(self.promoted(archive_ready=False))
        self.assertFalse(self.promoted(pending=False))
        self.assertFalse(self.promoted(housekeeping=0))

    def test_generation_and_same_observation_are_required(self):
        r,d,o,n,ready,f=trigger_case()
        self.assertFalse(r._housekeeping_first(d,replace(o),n,ready,f))
        self.assertFalse(r._housekeeping_first(d,o,n,ready,replace(f,generation='old')))
        r.state.fence.session='old'
        self.assertFalse(r._housekeeping_first(d,o,n,ready,f))

    def test_zero_unit_scope_is_not_an_active_peer_blocker(self):
        r,d,o,n,ready,f=trigger_case()
        n.append(Need('inactive','retirement',0,0,101.,101.,1))
        self.assertTrue(r._housekeeping_first(d,o,n,ready,f))


class PrefixTests(unittest.TestCase):
    def test_control_reproduces_768_retirements_and_no_housekeeping(self):
        with state() as s:
            seed(s,2000);garbage(s.writer,1)
            s.writer._retention_yield_requested=lambda:'source'
            out=s.retention()
            self.assertEqual(out.retired_records,768)
            self.assertEqual(out.housekeeping_rows,0)
            self.assertIsNone(ledger(s.writer))
            self.assertEqual(out.yield_reason,'source')

    def test_prefix_commits_then_yields_before_any_scope_or_tail_work(self):
        with state() as s:
            seed(s,2000);garbage(s.writer,1)
            w=s.writer;w._retention_next_scope=SCOPE
            commits=[];sql=[]
            w.db.set_trace_callback(sql.append)
            def waiting():
                self.assertFalse(w.db.in_transaction)
                self.assertEqual(w.last_retention_progress.housekeeping_rows,3)
                self.assertEqual(ledger(w),(3,0))
                self.assertEqual(w.db.execute('SELECT COUNT(*) FROM records').fetchone()[0],2000)
                commits.append('published')
                return 'source'
            w._retention_yield_requested=waiting
            try:out=s.retention(housekeeping_first=True)
            finally:w.db.set_trace_callback(None)
            self.assertEqual(commits,['published'])
            self.assertEqual(out.housekeeping_rows,3)
            self.assertEqual(out.retired_records,0)
            self.assertEqual(out.continuity_rows,0)
            self.assertEqual(out.floor_updates,0)
            self.assertEqual(out.examined_scopes,0)
            self.assertEqual(out.committed_slices,0)
            self.assertEqual(out.yield_reason,'source')
            self.assertEqual(w._retention_next_scope,SCOPE)
            self.assertEqual(sql.count('COMMIT'),1)
            self.assertFalse(any('wal_checkpoint' in x or 'incremental_vacuum' in x for x in sql))

    def test_one_batch_1000_per_table_with_existing_extra_key_lookahead(self):
        with state() as s:
            w=s.writer;garbage(w,1001)
            with w.transaction():
                w.db.execute("INSERT INTO archives VALUES('referenced.gz','unused',0,0)")
                w.db.execute("INSERT INTO records VALUES('r','reference',1,'sig','p',1,0,"
                    "NULL,'event',NULL,'hash',1000,'referenced.gz')")
                w.db.execute("INSERT INTO hot_chunks VALUES('referenced',X'00')")
                w.db.execute("INSERT INTO hot_refs VALUES('r','referenced')")
                w.db.execute("INSERT INTO address_keys VALUES(999999,'referenced')")
                rowid=w.db.execute("SELECT rowid FROM records WHERE identity='r'").fetchone()[0]
                w.db.execute('INSERT INTO address_refs VALUES(?,?,?)',(999999,rowid,1))
            folder=Path(str(w.path)+'.archive');folder.mkdir(exist_ok=True)
            immutable=folder/'immutable-test.gz';immutable.write_bytes(b'preserved immutable bytes')
            w._retention_yield_requested=lambda:'source'
            trace=[];w.db.set_trace_callback(trace.append)
            try:out=s.retention(housekeeping_first=True)
            finally:w.db.set_trace_callback(None)
            self.assertEqual(out.housekeeping_rows,3000)
            self.assertEqual(ledger(w),(3000,0))
            self.assertIs(out.pending,True)
            self.assertEqual(out.examined_scopes,0)
            for table in ('archives','hot_chunks','address_keys'):
                self.assertEqual(w.db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0],2)
                self.assertIn('gc:'+table,w.last_retention_progress.remaining)
            self.assertEqual(immutable.read_bytes(),b'preserved immutable bytes')
            self.assertEqual(trace.count('COMMIT'),1)
            self.assertFalse(any(getattr(w,'_retention_atomic',False) for _ in (0,)))

    def test_smaller_max_records_keeps_per_table_limits(self):
        with state() as s:
            w=s.writer;garbage(w,8)
            w._retention_yield_requested=lambda:'source'
            w.retain(900,max_records=7,archive_first=False,checkpoint=False,housekeeping_first=True)
            self.assertEqual(w.last_retention_progress.housekeeping_rows,21)
            self.assertEqual(ledger(w),(21,0))
            for table in ('archives','hot_chunks','address_keys'):
                self.assertEqual(w.db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0],1)

    def test_empty_prefix_has_no_transaction_or_progress(self):
        with state() as s:
            w=s.writer;w._retention_yield_requested=lambda:'source'
            sql=[];w.db.set_trace_callback(sql.append)
            try:out=s.retention(housekeeping_first=True)
            finally:w.db.set_trace_callback(None)
            self.assertFalse(out.made_progress)
            self.assertIsNone(ledger(w))
            self.assertEqual(sql.count('COMMIT'),0)

    def test_rollback_never_credits_attempted_deletion(self):
        with state() as s:
            w=s.writer;garbage(w,1)
            w.db.execute("CREATE TRIGGER fail_gc BEFORE DELETE ON hot_chunks "
                         "BEGIN SELECT RAISE(ABORT,'gc_rollback'); END")
            with self.assertRaisesRegex(sqlite3.IntegrityError,'gc_rollback'):
                with s.housekeeping_retention():
                    s.retention()
            self.assertFalse(s._housekeeping_retention)
            self.assertEqual(w.last_retention_progress.housekeeping_rows,0)
            self.assertIsNone(ledger(w))
            self.assertFalse(w.db.in_transaction)
            for table in ('archives','hot_chunks','address_keys'):
                self.assertEqual(w.db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0],1)
            self.assertEqual(w.db.execute('PRAGMA integrity_check').fetchone()[0],'ok')

    def test_urgent_sql_keeps_housekeeping_interruptible_and_rolls_back(self):
        with state() as s:
            w=s.writer;garbage(w,1000);observed=[]
            def interrupt():
                if w.db.in_transaction:
                    observed.append(getattr(w,'_retention_atomic',False))
                    w._background_sql_interrupted=True
                    return 1
                return 0
            w.db.set_progress_handler(interrupt,1000)
            try:out=s.retention(housekeeping_first=True)
            finally:w.db.set_progress_handler(None,0)
            self.assertTrue(observed)
            self.assertFalse(any(observed))
            self.assertEqual(out.yield_reason,'urgent_sql')
            self.assertEqual(out.housekeeping_rows,0)
            self.assertIsNone(ledger(w))
            self.assertFalse(w.db.in_transaction)
            for table in ('archives','hot_chunks','address_keys'):
                self.assertEqual(w.db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0],1000)

    def test_urgent_at_committed_prefix_keeps_progress_and_cursor(self):
        with state() as s:
            seed(s,10);w=s.writer;garbage(w,1)
            w._retention_next_scope='saved'
            w._retention_yield_requested=lambda:'urgent'
            out=s.retention(housekeeping_first=True)
            self.assertEqual(out.housekeeping_rows,3)
            self.assertEqual(out.retired_records,0)
            self.assertEqual(out.yield_reason,'urgent')
            self.assertEqual(w._retention_next_scope,'saved')
            self.assertEqual(ledger(w),(3,0))

    def test_no_waiter_continues_rotated_cursor_without_second_batch(self):
        with state() as s:
            seed(s,10,scope='a');seed(s,10,scope='b')
            w=s.writer;garbage(w,1);w._retention_next_scope='b'
            native=w._retention_housekeeping;sql=[]
            w.db.set_trace_callback(sql.append)
            try:
                with patch.object(w,'_retention_housekeeping',wraps=native) as batch:
                    out=s.retention(housekeeping_first=True)
                    self.assertEqual(batch.call_count,1)
            finally:w.db.set_trace_callback(None)
            deletes=[q for q in sql if q.startswith('DELETE FROM records')]
            self.assertIn('b:outcome',deletes[0])
            self.assertEqual(out.retired_records,20)
            self.assertIsNone(out.pending)
            self.assertEqual(out.housekeeping_rows,3)
            self.assertGreater(w.db.execute('SELECT COUNT(*) FROM archives').fetchone()[0],0)
            # A later ordinary call recomputes ordering and can drain new orphans.
            later=s.retention()
            self.assertGreater(later.housekeeping_rows,0)

    def test_real_owner_source_request_waiting_at_prefix_runs_next(self):
        with tempfile.TemporaryDirectory() as td:
            owner=PriorityOwner(lambda:ServiceState(Path(td)/'db',CONFIG))
            entered=threading.Event();release=threading.Event()
            try:
                owner.ready.result(timeout=5)
                def prepare(s):
                    seed(s,2000);garbage(s.writer,1)
                owner.submit(prepare,priority=1).result(timeout=5)
                def background(s):
                    native=s.writer._retention_housekeeping
                    def hold(*args):
                        entered.set()
                        if not release.wait(5):raise RuntimeError('test_release_timeout')
                        return native(*args)
                    with patch.object(s.writer,'_retention_housekeeping',side_effect=hold):
                        return s.retention(housekeeping_first=True)
                bg=owner.submit(background,priority=4)
                self.assertTrue(entered.wait(5))
                src=owner.submit(lambda s:(ledger(s.writer),
                    s.writer.db.execute('SELECT COUNT(*) FROM records').fetchone()[0]),priority=2)
                release.set();out=bg.result(timeout=5)
                self.assertEqual(out.retired_records,0)
                self.assertEqual(out.housekeeping_rows,3)
                self.assertEqual(out.yield_reason,'source')
                self.assertEqual(src.result(timeout=5),((3,0),2000))
            finally:
                release.set();owner.close()


class TurnTests(unittest.TestCase):
    def test_single_fresh_choice_progress_isolation_and_fresh_next_turn(self):
        with native_runtime() as (s,r,clock):
            seed(s,2000);garbage(s.writer,1)
            before=s.writer.db.execute('SELECT scope,side,at,units,record_at,records '
                                      'FROM maintenance_progress').fetchall()
            r.last_progress={(row[1],row[0]):row for row in before}
            at=clock.monotonic()
            o=NativeObservation(r.generation,at,clock.time(),(),3,tuple(before),0,0.)
            needs=[Need(SCOPE,'retirement',2000,2000,at+100.,None,0),
                   Need('__housekeeping__','retirement',3,0,at+7.7817,None,0)]
            f=ArchiveFlight(pending=((1,),{}),submitted=at,generation=r.generation)
            s.writer._retention_next_scope=SCOPE
            def yield_source():
                clock.advance(.1)
                return 'source'
            s.writer._retention_yield_requested=yield_source
            with patch.object(r.adapter,'observe',return_value=o) as observe, \
                 patch.object(r,'_demands',return_value=list(needs)), \
                 patch.object(s,'retention',wraps=s.retention) as retention:
                result=r.turn(f,at)
                observe.assert_called_once_with(r.generation)
                retention.assert_called_once_with()
            self.assertFalse(s._housekeeping_retention)
            out=result['retention_outcome']
            self.assertEqual(out.housekeeping_rows,3)
            self.assertEqual(out.retired_records,0)
            event=r.ring[-1]
            self.assertEqual(event['durable_progress'].get('__housekeeping__'),3)
            self.assertEqual(event['durable_records'],{})
            self.assertEqual(r.arbiter.origin['retirement','__housekeeping__'],clock.monotonic())
            self.assertEqual(r.arbiter.origin['retirement',SCOPE],at)
            self.assertEqual(r.arbiter.origin['archive','__archive_receipt__'],at)
            self.assertEqual(s.writer._retention_next_scope,SCOPE)
            # New fresh observation moves HK outside the window; no sticky prefix.
            garbage(s.writer,1)
            now=clock.monotonic()
            before=s.writer.db.execute('SELECT scope,side,at,units,record_at,records '
                                      'FROM maintenance_progress').fetchall()
            r.last_progress={(row[1],row[0]):row for row in before}
            fresh=NativeObservation(r.generation,now,clock.time(),(),3,tuple(before),0,0.)
            later=[replace(n,safety_deadline=now+30.) if n.scope=='__housekeeping__'
                   else n for n in needs]
            with patch.object(r.adapter,'observe',return_value=fresh) as observe, \
                 patch.object(r,'_demands',return_value=later), \
                 patch.object(s,'retention',wraps=s.retention) as retention:
                second=r.turn(f,now)
                observe.assert_called_once_with(r.generation)
                retention.assert_called_once_with()
            self.assertEqual(second['retention_outcome'].retired_records,768)
            self.assertEqual(second['retention_outcome'].housekeeping_rows,0)
            self.assertEqual(ledger(s.writer),(3,0))


if __name__=='__main__':unittest.main(verbosity=2)
