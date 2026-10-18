"""Unchanged evidence avoids scans; real retention/protection remains native."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, closing, contextmanager
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from meme_machine.runtime.robinhood.plane import Plane, _EVIDENCE_RETENTION_SCHEMA


class EvidenceRetentionRevisionTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ,dict(MM_MODE='PAPER',MM_OPERATIONAL_PHASE='OFFLINE_TEST'),clear=True))
        self.root=Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.path=self.root/'plane.sqlite';self.now=200000.;self.serial=0
        self.plane=Plane(self.path,clock=lambda:self.now)
        self.addCleanup(lambda:self.plane.close())

    def seed(self,namespace='pons:test',count=4097,*,protected=True):
        with self.plane.transaction():
            self.plane.db.executemany('INSERT INTO evidence VALUES(?,?,?,?,?)',
                ((namespace,f'{n:05d}','{}','{}',float(n)) for n in range(count)))
            if protected:self.plane.db.execute('INSERT INTO receipt_obligations VALUES(?,?,?,?,?)',
                (namespace,'00000','survivor','original-owner','generation'))
        return namespace

    def counts(self,fn=None):
        statements=[];self.plane.db.set_trace_callback(statements.append)
        try:(fn or self.plane.maintain)()
        finally:self.plane.db.set_trace_callback(None)
        return [s for s in statements if s.startswith('SELECT COUNT(*) FROM evidence WHERE namespace=')]

    def dirty(self):
        self.serial+=1;self.plane.checkpoint('unrelated',dict(sequence=self.serial))

    def peer(self):
        db=sqlite3.connect(self.path,isolation_level=None,check_same_thread=False)
        db.execute('PRAGMA foreign_keys=ON');self.addCleanup(db.close);return db

    def test_unrelated_peer_reuses_overlimit_protected_sweep_but_real_release_evicts(self):
        ns=self.seed();self.assertEqual(len(self.counts()),1)
        peer=self.peer();peer.execute("INSERT INTO runtime VALUES('unrelated_peer','{}')")
        self.assertEqual(self.counts(),[])
        self.assertEqual(self.plane.db.execute('SELECT COUNT(*) FROM evidence').fetchone()[0],4097)
        peer.execute('DELETE FROM receipt_obligations WHERE namespace=?',(ns,))
        self.assertEqual(len(self.counts()),1)
        self.assertIsNone(self.plane.db.execute('SELECT 1 FROM evidence WHERE namespace=? AND key=?',(ns,'00000')).fetchone())
        self.assertEqual(self.plane.db.execute('SELECT COUNT(*) FROM evidence').fetchone()[0],4096)

    def test_all_plain_peer_mutations_invalidate_old_and_new_namespaces(self):
        self.seed(count=4);self.seed('pons:other',count=4);self.plane.maintain();peer=self.peer()
        changes=(
            ("INSERT INTO evidence VALUES('pons:test','extra','{}','{}',9)",(),1),
            ("UPDATE evidence SET body='changed' WHERE namespace='pons:test' AND key='extra'",(),1),
            ("UPDATE evidence SET key='moved',created=50 WHERE namespace='pons:test' AND key='extra'",(),1),
            ("UPDATE evidence SET namespace='pons:other' WHERE namespace='pons:test' AND key='moved'",(),2),
            ("DELETE FROM evidence WHERE namespace='pons:other' AND key='moved'",(),1),
            ("INSERT INTO receipt_obligations VALUES('pons:test','00001','current','owner','g')",(),1),
            ("UPDATE receipt_obligations SET namespace='pons:other',key='00002',consumer='survivor',owner='o',generation='new' WHERE consumer='current'",(),2),
            ("DELETE FROM receipt_obligations WHERE owner='o'",(),1),
            ("INSERT OR REPLACE INTO evidence VALUES('pons:test','00001','replacement','{}',80)",(),1),
        )
        for sql,args,expected in changes:
            with self.subTest(sql=sql):
                peer.execute(sql,args);self.assertEqual(len(self.counts()),expected)

    def test_peer_opened_before_install_uses_new_engine_triggers(self):
        path=self.root/'legacy.sqlite';legacy=sqlite3.connect(path,isolation_level=None)
        self.addCleanup(legacy.close);owner=Plane(path,clock=lambda:self.now);self.addCleanup(owner.close)
        legacy.execute("INSERT INTO evidence VALUES('pons:old','a','{}','{}',1)")
        owner.maintain();before=owner._evidence_retention_cache['pons:old'][0]
        legacy.execute("UPDATE evidence SET created=2 WHERE namespace='pons:old'")
        owner.maintain();self.assertGreater(owner._evidence_retention_cache['pons:old'][0],before)

    def test_reordering_and_obligation_move_preserve_exact_newest_and_protected_sets(self):
        ns=self.seed();self.plane.maintain();peer=self.peer()
        peer.execute("UPDATE evidence SET created=99999 WHERE namespace=? AND key='00000'",(ns,))
        self.plane.maintain()
        self.assertIsNone(self.plane.db.execute("SELECT 1 FROM evidence WHERE namespace=? AND key='00001'",(ns,)).fetchone())
        self.assertIsNotNone(self.plane.db.execute("SELECT 1 FROM evidence WHERE namespace=? AND key='00000'",(ns,)).fetchone())
        self.assertEqual(self.plane.db.execute('SELECT COUNT(*) FROM receipt_obligations').fetchone()[0],1)

    def test_rollback_and_failed_commit_never_publish_speculative_clean_revision(self):
        ns=self.seed();self.plane.maintain();before=dict(self.plane._evidence_retention_cache)
        original=self.plane.transaction
        @contextmanager
        def rollback():
            with original():
                self.plane.db.execute('DELETE FROM receipt_obligations WHERE namespace=?',(ns,))
                yield
                raise RuntimeError('injected_after_retention')
        self.dirty()
        with patch.object(self.plane,'transaction',rollback):
            with self.assertRaisesRegex(RuntimeError,'injected_after_retention'):self.plane.maintain()
        self.assertEqual(dict(self.plane._evidence_retention_cache),before)
        self.assertIsNotNone(self.plane.db.execute("SELECT 1 FROM evidence WHERE key='00000'").fetchone())
        self.peer().execute('DELETE FROM receipt_obligations WHERE namespace=?',(ns,))
        original_db=self.plane.db
        class FailCommit:
            def __getattr__(self,name):return getattr(original_db,name)
            def execute(self,sql,*args):
                if sql=='COMMIT':raise sqlite3.OperationalError('injected_commit')
                return original_db.execute(sql,*args)
        with patch.object(self.plane,'db',FailCommit()):
            with self.assertRaisesRegex(sqlite3.OperationalError,'injected_commit'):self.plane.maintain()
        self.assertEqual(dict(self.plane._evidence_retention_cache),before)
        self.assertEqual(len(self.counts()),1)
        self.assertIsNone(self.plane.db.execute("SELECT 1 FROM evidence WHERE key='00000'").fetchone())

    def test_schema_rollback_does_not_cache_a_reused_schema_version(self):
        self.seed(count=4);self.plane.maintain();prior=self.plane._evidence_retention_schema_version
        original=self.plane.transaction
        @contextmanager
        def rollback():
            with original():
                self.plane.db.execute('CREATE TABLE unrelated_schema(x)')
                yield
                raise RuntimeError('rollback_schema')
        self.dirty()
        with patch.object(self.plane,'transaction',rollback):
            with self.assertRaisesRegex(RuntimeError,'rollback_schema'):self.plane.maintain()
        self.assertEqual(self.plane._evidence_retention_schema_version,prior)
        self.plane.db.execute("CREATE TRIGGER revision_suppress BEFORE UPDATE ON evidence_retention_revision BEGIN SELECT RAISE(IGNORE); END")
        self.plane.db.execute("UPDATE evidence SET created=20 WHERE key='00001'")
        self.assertEqual(len(self.counts()),1);self.assertIsNone(self.plane._evidence_retention_schema_version)

    def test_successful_no_write_rollback_does_not_publish_speculative_schema(self):
        self.seed(count=4);self.plane.maintain();self.dirty()
        original=self.plane.transaction
        @contextmanager
        def speculative_schema():
            with original():
                self.plane.db.execute('CREATE TABLE uncommitted_schema(x)')
                yield
        with patch.object(self.plane,'transaction',speculative_schema):self.plane.maintain()
        self.assertIsNone(self.plane._evidence_retention_schema_version)
        self.assertEqual(self.plane._evidence_retention_cache,{})
        self.assertIsNone(self.plane.db.execute("SELECT 1 FROM sqlite_master WHERE name='uncommitted_schema'").fetchone())
        self.plane.db.execute("CREATE TRIGGER revision_suppress BEFORE UPDATE ON evidence_retention_revision BEGIN SELECT RAISE(IGNORE); END")
        self.plane.db.execute("UPDATE evidence SET created=40 WHERE key='00001'")
        self.assertEqual(len(self.counts()),1)
        self.assertIsNone(self.plane._evidence_retention_schema_version)

    def test_missing_changed_extra_trigger_metadata_falls_back_and_reset_is_refused(self):
        ns=self.seed(count=4);self.plane.maintain()
        for sql in ("DELETE FROM evidence_retention_revision", "UPDATE evidence_retention_revision SET generation=0",
                "UPDATE evidence_retention_revision SET namespace='different'", "INSERT OR REPLACE INTO evidence_retention_revision VALUES('pons:test',0)"):
            with self.subTest(sql=sql),self.assertRaises(sqlite3.IntegrityError):self.plane.db.execute(sql)
        self.plane.db.execute('DROP TRIGGER evidence_retention_evidence_update')
        self.plane.db.execute("UPDATE evidence SET created=30 WHERE namespace=?",(ns,))
        self.assertEqual(len(self.counts()),1);self.dirty();self.assertEqual(len(self.counts()),1)
        self.plane.db.execute(_EVIDENCE_RETENTION_SCHEMA['evidence_retention_evidence_update'])
        self.dirty();self.assertEqual(len(self.counts()),1);self.dirty();self.assertEqual(self.counts(),[])

    def test_restart_validates_schema_and_sweeps_again_even_with_persisted_revisions(self):
        self.seed();self.plane.maintain();self.plane.close()
        self.plane=Plane(self.path,clock=lambda:self.now)
        self.assertEqual(self.plane._evidence_retention_cache,{})
        self.assertEqual(len(self.counts()),1)

    def test_foreign_partial_metadata_never_authorizes_skip_or_prevents_native_sweep(self):
        path=self.root/'partial.sqlite'
        with closing(sqlite3.connect(path)) as db:
            db.execute('CREATE TABLE evidence_retention_revision(unknown TEXT)');db.commit()
        owner=Plane(path,clock=lambda:self.now);self.addCleanup(owner.close)
        with owner.transaction():
            owner.db.executemany('INSERT INTO evidence VALUES(?,?,?,?,?)',
                (('pons:partial',str(n),'{}','{}',n) for n in range(4097)))
        owner.maintain()
        self.assertIsNone(owner._evidence_retention_schema_version)
        self.assertEqual(owner._evidence_retention_cache,{})
        self.assertEqual(owner.db.execute('SELECT COUNT(*) FROM evidence').fetchone()[0],4096)

    def test_paused_namespace_and_scope_change_keep_original_retention_selection(self):
        self.seed('ramses:paused');self.plane.maintain()
        self.assertNotIn('ramses:paused',self.plane._evidence_retention_cache)
        self.assertEqual(self.plane.db.execute('SELECT COUNT(*) FROM evidence').fetchone()[0],4097)
        with patch.dict(os.environ,dict(MM_MODE='PAPER'),clear=True):
            self.assertEqual(len(self.counts()),1)
            self.assertIn('ramses:paused',self.plane._evidence_retention_cache)

    def test_concurrent_peer_after_sweep_cannot_stamp_unseen_write_clean(self):
        ns=self.seed();self.plane.maintain();peer=self.peer();ready=threading.Event();done=threading.Event()
        original=self.plane.transaction
        @contextmanager
        def delayed_publication():
            with original():yield
            ready.set();self.assertTrue(done.wait(2))
        def write():
            self.assertTrue(ready.wait(2));peer.execute('DELETE FROM receipt_obligations WHERE namespace=?',(ns,));done.set()
        self.dirty()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(write)
            with patch.object(self.plane,'transaction',delayed_publication):self.plane.maintain()
            future.result(2)
        self.assertEqual(len(self.counts()),1)
        self.assertIsNone(self.plane.db.execute("SELECT 1 FROM evidence WHERE key='00000'").fetchone())

    def test_local_posttransaction_write_is_not_certified_by_completed_stamp(self):
        ns=self.seed();self.plane.maintain();original=self.plane.transaction
        @contextmanager
        def local_write():
            with original():yield
            with original():self.plane.db.execute('DELETE FROM receipt_obligations WHERE namespace=?',(ns,))
        self.dirty()
        with patch.object(self.plane,'transaction',local_write):self.plane.maintain()
        self.assertEqual(len(self.counts()),1)
        self.assertIsNone(self.plane.db.execute("SELECT 1 FROM evidence WHERE key='00000'").fetchone())

    def test_concurrent_plain_writer_mutations_wait_for_snapshot_and_invalidate_after_commit(self):
        ns=self.seed(count=4);self.plane.maintain();peer=self.peer()
        operations=(
            "INSERT INTO evidence VALUES('pons:test','new','{}','{}',20)",
            "UPDATE evidence SET created=40 WHERE namespace='pons:test' AND key='new'",
            "INSERT INTO receipt_obligations VALUES('pons:test','new','current','o','g')",
            "UPDATE receipt_obligations SET generation='next' WHERE owner='o'",
            "DELETE FROM receipt_obligations WHERE owner='o'",
            "DELETE FROM evidence WHERE namespace='pons:test' AND key='new'",
        )
        for sql in operations:
            with self.subTest(sql=sql):
                ready=threading.Event();attempted=threading.Event();done=threading.Event()
                original=self.plane._evidence_retention_revision
                def gate(namespace):
                    result=original(namespace);ready.set();self.assertTrue(attempted.wait(2))
                    self.assertFalse(done.wait(.01));return result
                def write():
                    self.assertTrue(ready.wait(2));attempted.set();peer.execute(sql);done.set()
                self.dirty()
                with ThreadPoolExecutor(max_workers=1) as pool:
                    future=pool.submit(write)
                    with patch.object(self.plane,'_evidence_retention_revision',gate):self.plane.maintain()
                    future.result(2)
                self.assertEqual(len(self.counts()),1)

    def test_cache_capacity_never_changes_native_namespace_work(self):
        for n in range(132):self.seed('pons:bounded:'+str(n),count=1,protected=False)
        self.assertEqual(len(self.counts()),132)
        self.assertLessEqual(len(self.plane._evidence_retention_cache),128)
        self.dirty();self.assertGreaterEqual(len(self.counts()),4)
        self.assertEqual(self.plane.db.execute('SELECT COUNT(*) FROM evidence').fetchone()[0],132)
