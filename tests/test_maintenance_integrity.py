"""E24: stale interruption flags and durable, fixed-cardinality lifecycle counts."""
from contextlib import contextmanager
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from meme_machine.solana_evidence_plane import lifecycle_scope
from meme_machine.solana_evidence_service import ServiceState
from tests.test_retention_outcomes import CONFIG, seed
from tests.test_retention_progress import record


class MaintenanceIntegrityTests(unittest.TestCase):
    @contextmanager
    def state(self):
        with tempfile.TemporaryDirectory() as folder:
            state=ServiceState(Path(folder)/'db',CONFIG)
            try:yield state
            finally:state.close()

    def counts(self,state):
        return dict(state.writer.db.execute('SELECT key,value FROM counters WHERE key LIKE \'lifecycle.%\''))

    def test_one_observation_reuses_only_its_fresh_retirement_fences(self):
        from meme_machine import solana_maintenance_state as maintenance
        from meme_machine.solana_selective_source import install
        with self.state() as state:
            install(state)
            w=state.writer;db=w.db
            w.interest('offline-open','control:solana',lower_slot=100,priority=0,lifecycle='open')
            with w.transaction():
                for scope in ('control:solana','account:offline'):
                    db.execute('INSERT INTO cursors VALUES(?,?,?)',(scope,110,1000))
                    db.executemany('INSERT INTO gaps(scope,lo,hi,reason,created,repaired) VALUES(?,?,?,?,?,?)',
                        [(scope,1,20,'first-retained-gap',400,None),
                         (scope,50,60,'second-retained-gap',400,None)])
                    db.executemany('INSERT INTO coverage(scope,lo,hi,available,proof) VALUES(?,?,?,?,?)',
                        [(scope,30,30,500,'eligible-prefix'),(scope,70,70,500,'eligible-suffix')])
            suffix=maintenance.retirement_suffix
            def unshared(*args,**kwargs):
                kwargs.pop('_fences',None)
                return suffix(*args,**kwargs)
            def observe(*,shared):
                statements=[]
                db.set_trace_callback(statements.append)
                try:
                    with patch.object(maintenance,'retirement_suffix',suffix if shared else unshared):
                        result=maintenance.DebtAgeAdapter(w,wall=lambda:1000).observe('fresh-owner-command')
                finally:db.set_trace_callback(None)
                return replace(result,monotonic=0,vm_steps=0,elapsed=0),len(statements)
            before=db.total_changes
            reference,old_reads=observe(shared=False)
            current,new_reads=observe(shared=True)
            self.assertEqual(current,reference)
            # Two scopes have closed gaps; reuse removes their repeated gap,
            # pin/account and schema/CONTROL-guard lookups, not evidence checks.
            self.assertGreaterEqual(old_reads-new_reads,10)
            print('MAINTENANCE_FENCE_REUSE_QUERY_COUNTS '+json.dumps(dict(
                scopes_with_gaps=2,unshared_reads=old_reads,shared_reads=new_reads)),flush=True)
            self.assertEqual(db.total_changes,before)
            with w.transaction():
                db.execute("INSERT INTO gaps(scope,lo,hi,reason,created,repaired) VALUES(?,?,?,?,?,?)",
                    ('control:solana',25,None,'new-open-replay-gap',600,None))
            following,_=observe(shared=True)
            reference_following,_=observe(shared=False)
            self.assertEqual(following,reference_following)
            self.assertNotEqual(following.scopes,current.scopes)

    def test_retirement_suffix_rechecks_work_when_a_whole_witness_moves_its_fence(self):
        from meme_machine.solana_maintenance_state import retirement_suffix
        with self.state() as state:
            w=state.writer;db=w.db;scope='control:solana'
            with w.transaction():
                db.execute('INSERT INTO cursors VALUES(?,?,?)',(scope,100,1000))
                db.executemany('INSERT INTO gaps(scope,lo,hi,reason,created,repaired) VALUES(?,?,?,?,?,?)',
                    [(scope,1,20,'first-retained-gap',400,None),
                     (scope,50,60,'second-retained-gap',400,None)])
                db.execute('INSERT INTO coverage(scope,lo,hi,available,proof) VALUES(?,?,?,?,?)',
                    (scope,18,35,500,'whole-boundary-witness'))
                db.execute('INSERT INTO coverage(scope,lo,hi,available,proof) VALUES(?,?,?,?,?)',
                    (scope,25,25,500,'nested-work-behind-fence'))
            # The initial 21..50 witness exists, but the whole retained interval
            # raises its lower fence to36. No work remains in that exact range.
            self.assertIsNone(retirement_suffix(w,scope,100,820,recent_floor=None))

    def test_protected_future_coverage_does_not_exhaust_empty_retirement_prefix(self):
        from meme_machine.solana_maintenance_state import DebtAgeAdapter,OBSERVATION_VM_STEPS
        with self.state() as state:
            w=state.writer;db=w.db
            w.interest('pump','control:solana',lower_slot=1,priority=0,lifecycle='open')
            with w.transaction():
                db.execute('INSERT INTO cursors VALUES(?,?,?)',('control:solana',25100,1000))
                db.executemany('INSERT INTO coverage(scope,lo,hi,available,proof) VALUES(?,?,?,?,?)',
                    [('control:solana',100+i,100+i,1000,'retained-'+str(i)) for i in range(25000)])
            before=db.execute('SELECT COUNT(*),SUM(lo),SUM(hi) FROM coverage').fetchone()
            a=DebtAgeAdapter(w,wall=lambda:1000)
            observation=a.observe('protected-future')
            control=next(r for r in observation.scopes if r.scope=='control:solana')
            self.assertLessEqual(observation.vm_steps,OBSERVATION_VM_STEPS)
            self.assertEqual((control.floor,control.continuity,control.pins),(1,0,1))
            self.assertEqual(db.execute('SELECT COUNT(*),SUM(lo),SUM(hi) FROM coverage').fetchone(),before)
            # The indexed empty-prefix test must still see genuinely older
            # native witnesses. Neither observation retires or fabricates them.
            with w.transaction():
                db.execute('INSERT INTO coverage(scope,lo,hi,available,proof) VALUES(?,?,?,?,?)',
                    ('control:solana',0,0,500,'old-authenticated'))
                db.execute('INSERT INTO gaps(scope,lo,hi,reason,created,repaired) VALUES(?,?,?,?,?,?)',
                    ('control:solana',0,0,'old-gap',400,500))
            observation=a.observe('retained-prefix')
            control=next(r for r in observation.scopes if r.scope=='control:solana')
            self.assertEqual((control.floor,control.continuity),(1,2))
            self.assertEqual(db.execute('SELECT COUNT(*) FROM coverage').fetchone()[0],25001)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM records').fetchone()[0],0)

    def test_closed_gaps_share_fresh_minimum_without_erasing_retirement_debt(self):
        from meme_machine.solana_maintenance_state import DebtAgeAdapter,OBSERVATION_VM_STEPS
        with self.state() as state:
            w=state.writer;db=w.db
            with w.transaction():
                db.execute('INSERT INTO cursors VALUES(?,?,?)',('control:solana',25100,1000))
                db.executemany('INSERT INTO coverage(scope,lo,hi,available,proof) VALUES(?,?,?,?,?)',
                    [('control:solana',100+i,100+i,1000,'fresh-'+str(i)) for i in range(25000)])
                db.executemany('INSERT INTO gaps(scope,lo,hi,reason,created,repaired) VALUES(?,?,?,?,?,?)',
                    [('control:solana',1+4*i,2+4*i,'retained-gap',400,None) for i in range(15)])
            adapter=DebtAgeAdapter(w,wall=lambda:1000)
            observation=adapter.observe('closed-gaps')
            self.assertLessEqual(observation.vm_steps,OBSERVATION_VM_STEPS)
            control=next(r for r in observation.scopes if r.scope=='control:solana')
            self.assertEqual((control.floor,control.gaps,control.continuity),(1,15,0))
            with w.transaction():
                db.execute('INSERT INTO coverage(scope,lo,hi,available,proof) VALUES(?,?,?,?,?)',
                    ('control:solana',60,60,500,'actual-retirable-work'))
            observation=adapter.observe('closed-gaps-with-debt')
            control=next(r for r in observation.scopes if r.scope=='control:solana')
            self.assertEqual((control.floor,control.gaps,control.continuity),(1,15,1))
            self.assertEqual(db.execute('SELECT COUNT(*) FROM coverage').fetchone()[0],25001)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM gaps WHERE repaired IS NULL').fetchone()[0],15)

    def test_expired_protected_coverage_and_empty_gap_ranges_remain_bounded(self):
        from meme_machine.solana_maintenance_state import DebtAgeAdapter,OBSERVATION_VM_STEPS
        with self.state() as state:
            w=state.writer;db=w.db
            with w.transaction():
                db.execute('INSERT INTO cursors VALUES(?,?,?)',('control:solana',27000,500))
                db.executemany('INSERT INTO coverage(scope,lo,hi,available,proof) VALUES(?,?,?,?,?)',
                    [('control:solana',100+i,100+i,500,'expired-'+str(i)) for i in range(25000)])
                db.executemany('INSERT INTO gaps(scope,lo,hi,reason,created,repaired) VALUES(?,?,?,?,?,?)',
                    [('control:solana',1,25099,'protected-expired-prefix',400,None)]+[
                     ('control:solana',26000+4*i,26001+4*i,'empty-retained-gap',400,None) for i in range(15)])
            adapter=DebtAgeAdapter(w,wall=lambda:1000)
            observation=adapter.observe('expired-no-work')
            self.assertLessEqual(observation.vm_steps,OBSERVATION_VM_STEPS)
            control=next(r for r in observation.scopes if r.scope=='control:solana')
            self.assertEqual((control.floor,control.gaps,control.continuity),(1,16,0))
            with w.transaction():
                db.execute('INSERT INTO coverage(scope,lo,hi,available,proof) VALUES(?,?,?,?,?)',
                    ('control:solana',26002,26002,500,'actual-suffix-work'))
            observation=adapter.observe('expired-with-work')
            self.assertLessEqual(observation.vm_steps,OBSERVATION_VM_STEPS)
            control=next(r for r in observation.scopes if r.scope=='control:solana')
            self.assertEqual(control.continuity,1)
            # An authentic whole witness spanning a boundary still fences the
            # nested row. Empty-range pruning cannot discard overlap protection.
            with w.transaction():
                db.execute('INSERT INTO coverage(scope,lo,hi,available,proof) VALUES(?,?,?,?,?)',
                    ('control:solana',26000,26010,500,'whole-crossing-witness'))
            observation=adapter.observe('expired-fenced-work')
            control=next(r for r in observation.scopes if r.scope=='control:solana')
            self.assertEqual(control.continuity,0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM coverage').fetchone()[0],25002)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM gaps WHERE repaired IS NULL').fetchone()[0],16)

    def test_large_live_address_dictionary_observation_stays_bounded(self):
        from meme_machine.solana_maintenance_state import DebtAgeAdapter,OBSERVATION_VM_STEPS
        with self.state() as state:
            state.writer.ingest([record()])
            db=state.writer.db
            rowid=db.execute('SELECT rowid FROM records LIMIT 1').fetchone()[0]
            with state.writer.transaction():
                db.executemany('INSERT INTO address_keys(id,address) VALUES(?,?)',
                    [(i,'offline-address-'+str(i)) for i in range(100000,150000)])
                db.executemany('INSERT INTO address_refs VALUES(?,?,?)',
                    [(i,rowid,1) for i in range(100000,150000)])
            observation=DebtAgeAdapter(state.writer).observe(state.fence.session)
            self.assertLessEqual(observation.vm_steps,OBSERVATION_VM_STEPS)
            self.assertFalse(db.execute("SELECT 1 FROM maintenance_orphans WHERE kind='address'").fetchone())
            with self.assertRaisesRegex(RuntimeError,'rollback'):
                with state.writer.transaction():
                    db.execute('DELETE FROM address_refs WHERE address_id=100000')
                    self.assertTrue(db.execute("SELECT 1 FROM maintenance_orphans WHERE kind='address' AND key='100000'").fetchone())
                    raise RuntimeError('rollback')
            self.assertFalse(db.execute("SELECT 1 FROM maintenance_orphans WHERE kind='address' AND key='100000'").fetchone())
            with state.writer.transaction():db.execute('DELETE FROM address_refs WHERE address_id=100000')
            self.assertTrue(db.execute("SELECT 1 FROM maintenance_orphans WHERE kind='address' AND key='100000'").fetchone())

    def test_stale_interruption_flag_never_swallows_storage_error(self):
        for message in ('disk I/O error','database is locked','database or disk is full'):
            with self.subTest(message=message),self.state() as state:
                state.writer._background_sql_interrupted=True
                with patch.object(state.writer,'retain',side_effect=sqlite3.OperationalError(message)):
                    with self.assertRaisesRegex(sqlite3.OperationalError,message):state.retention()
                self.assertNotIn('retention_outcome.unknown',state.storage_metrics)
                self.assertEqual(state.storage_metrics['retention.failed'],1)

    def test_actual_interrupt_without_owner_evidence_is_not_swallowed(self):
        with self.state() as state:
            with patch.object(state.writer,'retain',side_effect=sqlite3.OperationalError('interrupted')):
                with self.assertRaises(sqlite3.OperationalError):state.retention()

    def test_new_rows_archive_retry_and_retirement_counts_are_exact(self):
        with self.state() as state:
            seed(state,256)
            initial=self.counts(state)
            self.assertEqual(initial['lifecycle.ingested.program:meteora'],256)
            self.assertEqual(initial['lifecycle.archived.program:meteora'],256)
            # Archive publication already succeeded in seed(); replaying retention
            # after drain must not book the same work twice.
            state.retention();state.retention()
            counts=self.counts(state)
            self.assertEqual(counts['lifecycle.retired.program:meteora'],256)
            self.assertEqual(state.writer.db.execute('SELECT COUNT(*) FROM records').fetchone()[0],0)

    def test_rollback_and_duplicate_ingestion_cannot_count_useful_work(self):
        with self.state() as state:
            row=replace(record(),scope='program:meteora')
            state.writer.ingest([row]);state.writer.ingest([row])
            self.assertEqual(self.counts(state)['lifecycle.ingested.program:meteora'],1)
            with self.assertRaisesRegex(RuntimeError,'rollback'):
                with state.writer.transaction():
                    state.writer.ingest([replace(row,identity='other-identity',signature='new-signature')])
                    raise RuntimeError('rollback')
            self.assertEqual(self.counts(state)['lifecycle.ingested.program:meteora'],1)
            self.assertEqual(state.writer.db.execute('SELECT COUNT(*) FROM records').fetchone()[0],1)

    def test_failed_archive_and_retirement_do_not_count_rolled_back_rows(self):
        with self.state() as state:
            state.writer.ingest([replace(record(),scope='program:meteora')])
            plan=state.writer.archive_plan(1000)
            receipt=state.writer.write_archive(state.writer.path,plan)
            db=state.writer.db
            db.execute("CREATE TRIGGER reject_archive BEFORE UPDATE OF body ON records BEGIN SELECT RAISE(ABORT,'archive_test'); END")
            with self.assertRaisesRegex(sqlite3.IntegrityError,'archive_test'):state.writer.commit_archive(plan,receipt)
            self.assertNotIn('lifecycle.archived.program:meteora',self.counts(state))
            db.execute('DROP TRIGGER reject_archive')
            state.writer.commit_archive(plan,receipt);state.writer.commit_archive(plan,receipt)
            self.assertEqual(self.counts(state)['lifecycle.archived.program:meteora'],1)
            db.execute("CREATE TRIGGER reject_retire BEFORE DELETE ON records BEGIN SELECT RAISE(ABORT,'retire_test'); END")
            with self.assertRaisesRegex(sqlite3.IntegrityError,'retire_test'):state.retention()
            self.assertNotIn('lifecycle.retired.program:meteora',self.counts(state))
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')

    def test_scope_telemetry_cardinality_never_contains_an_address(self):
        scopes=['account:secret-'+str(i) for i in range(1000)]+['custom-'+str(i) for i in range(1000)]
        self.assertEqual({lifecycle_scope(s) for s in scopes},{'account','other'})
        for name in ('program:meteora','program:pump','program:pumpswap'):
            self.assertEqual(lifecycle_scope(name),name)


if __name__=='__main__':unittest.main()
