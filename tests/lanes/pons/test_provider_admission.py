import json
import sqlite3
import threading
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from meme_machine.lanes.pons import BoundaryError
from meme_machine.lanes.pons.provider_admission import Admission,priority

class SharedAdmissionTests(unittest.TestCase):
    def test_two_sessions_share_physical_request_clock_and_cooldown(self):
        with tempfile.TemporaryDirectory() as td:
            now=[100.0]
            def sleep(seconds):now[0]+=seconds
            kw=dict(clock=lambda:now[0],sleeper=sleep,lane='test')
            a=Admission(str(Path(td)/'gate.db'),'https://example.com/secret',**kw)
            b=Admission(a.path,'https://example.com/secret/',**kw)
            self.assertEqual(a.endpoint,b.endpoint)
            a.acquire('discovery')
            wait=b.acquire('paper_exit')['wait_seconds']
            self.assertGreaterEqual(wait,0.5);self.assertLess(wait,0.502)
            def limited():raise BoundaryError('provider_http_429')
            with self.assertRaises(BoundaryError):a.invoke(limited,['eth_call'],'evidence')
            wait=b.acquire('paper_exit')['wait_seconds']
            self.assertGreaterEqual(wait,8.0)
            db=a.connect();raw=db.execute('SELECT body FROM transports').fetchone()[0];db.close()
            row=json.loads(raw)
            self.assertEqual(row['http_status'],429)
            self.assertNotIn('secret',raw)
    def test_open_position_precedes_research_and_queue_is_bounded(self):
        with tempfile.TemporaryDirectory() as td:
            a=Admission(str(Path(td)/'gate.db'),'https://example.com/key',lane='test')
            db=a.connect();now=a.clock()
            db.execute('INSERT INTO queue VALUES(?,?,?,?,?)',('research',a.endpoint,50,now-1,now+30))
            self.assertLess(a.acquire('lifecycle_unwind')['wait_seconds'],0.1)
            for n in range(255):
                db.execute('INSERT INTO queue VALUES(?,?,?,?,?)',(str(n),a.endpoint,50,now,now+30))
            with self.assertRaisesRegex(BoundaryError,'capacity'):a.acquire('candidate')
            db.close()
            self.assertLess(priority('pons_paper'),priority('research_history'))

class AdmissionFairnessTests(unittest.TestCase):
    def test_cleanup_receipt_and_guard_maintenance_share_one_durable_transaction(self):
        with tempfile.TemporaryDirectory() as td:
            now=[100.]
            a=Admission(str(Path(td)/'gate.db'),'https://example.com/key',lane='pons',
                clock=lambda:now[0],sleeper=lambda s:now.__setitem__(0,now[0]+s))
            connection=a.connect;states=[]
            def traced():
                db=connection()
                db.set_trace_callback(lambda sql:states.append(db.in_transaction)
                    if sql.startswith(('DELETE FROM queue_meta WHERE id=', 'INSERT INTO admissions')) else None)
                return db
            with patch.object(a,'connect',side_effect=traced):a.acquire('paper_unwind')
            self.assertEqual(states,[True,True])
            db=connection()
            self.assertEqual(db.execute('SELECT COUNT(*) FROM queue_meta').fetchone()[0],0)
            row=json.loads(db.execute('SELECT body FROM admissions').fetchone()[0])
            self.assertTrue(row['granted']);self.assertEqual(row['priority'],0)
            self.assertEqual(db.execute('SELECT next_at FROM limits').fetchone()[0],100.5)
            with self.assertRaisesRegex(sqlite3.IntegrityError,'append_only'):db.execute('DELETE FROM admissions')
            db.close()

    def test_failed_admission_audit_cannot_start_transport_or_reset_pacing(self):
        with tempfile.TemporaryDirectory() as td:
            now=[100.];calls=[]
            a=Admission(str(Path(td)/'gate.db'),'https://example.com/key',lane='pons',
                clock=lambda:now[0],sleeper=lambda s:now.__setitem__(0,now[0]+s))
            with patch('meme_machine.runtime.storage.audit_ring',side_effect=RuntimeError('audit_fault')):
                with self.assertRaisesRegex(RuntimeError,'audit_fault'):
                    a.invoke(lambda:calls.append(1),['eth_call'],'paper_unwind')
            self.assertEqual(calls,[])
            db=a.connect()
            self.assertEqual(db.execute('SELECT COUNT(*) FROM admissions').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT next_at FROM limits').fetchone()[0],100.5)
            db.close()
            self.assertGreaterEqual(a.acquire('paper_unwind')['wait_seconds'],.5)

    def test_original_deadline_prevents_transport_and_records_wait(self):
        with tempfile.TemporaryDirectory() as td:
            now=[100.]
            a=Admission(str(Path(td)/'gate.db'),'https://example.com/key',lane='pons',clock=lambda:now[0],sleeper=lambda s:now.__setitem__(0,now[0]+s))
            db=a.connect();db.execute('UPDATE limits SET next_at=110');db.close()
            calls=[]
            with self.assertRaisesRegex(BoundaryError,'deadline'):
                a.invoke(lambda:calls.append(1),['eth_call'],'pons_natural',deadline=101.)
            self.assertEqual(calls,[])
            db=a.connect();row=json.loads(db.execute('SELECT body FROM admissions').fetchone()[0]);db.close()
            self.assertFalse(row['granted']);self.assertEqual(row['deadline'],101.)
    def test_aged_research_precedes_new_candidate_but_never_exit(self):
        with tempfile.TemporaryDirectory() as td:
            now=[100.];attempt=[0]
            def sleep(seconds):
                now[0]+=seconds;attempt[0]+=1
                db=a.connect()
                # Simulate an already waiting research worker consuming its grant.
                db.execute("DELETE FROM queue WHERE id='research'");db.close()
            a=Admission(str(Path(td)/'gate.db'),'https://example.com/key',lane='pons',clock=lambda:now[0],sleeper=sleep)
            db=a.connect();db.execute('INSERT INTO queue VALUES(?,?,?,?,?)',('research',a.endpoint,50,96.,120.));db.close()
            a.acquire('pons_natural',deadline=105.)
            self.assertGreater(attempt[0],0)
            attempt[0]=0
            db=a.connect();db.execute('INSERT INTO queue VALUES(?,?,?,?,?)',('research',a.endpoint,50,96.,120.));db.execute('UPDATE limits SET next_at=0');db.close()
            a.acquire('paper_unwind')
            self.assertEqual(attempt[0],0)
            self.assertEqual(priority('pons_natural'),10)


class AuditMaintenanceTests(unittest.TestCase):
    def seed(self,path):
        db=sqlite3.connect(path,isolation_level=None);db.execute('PRAGMA journal_mode=WAL')
        db.executescript("CREATE TABLE audit(seq INTEGER PRIMARY KEY,body TEXT); CREATE TRIGGER immutable_audit BEFORE DELETE ON audit BEGIN SELECT RAISE(ABORT,'append_only'); END;")
        db.executemany('INSERT INTO audit(body) VALUES(?)',[(str(n),) for n in range(32)])
        return db

    def test_trigger_changes_and_retained_rows_are_one_atomic_commit(self):
        from meme_machine.runtime.storage import audit_ring
        with tempfile.TemporaryDirectory() as td:
            db=self.seed(Path(td)/'audit.sqlite');states=[]
            db.set_trace_callback(lambda sql:states.append(db.in_transaction) if sql.startswith(('DROP TRIGGER','DELETE FROM audit','CREATE TRIGGER')) else None)
            audit_ring(db,'audit','immutable_audit',limit=16)
            self.assertEqual(states,[True,True,True])
            self.assertEqual([r[0] for r in db.execute('SELECT seq FROM audit')],list(range(17,33)))
            with self.assertRaisesRegex(sqlite3.IntegrityError,'append_only'):db.execute('DELETE FROM audit')
            db.close()

    def test_failed_pruning_restores_rows_and_append_only_guard(self):
        from meme_machine.runtime.storage import audit_ring
        with tempfile.TemporaryDirectory() as td:
            db=self.seed(Path(td)/'audit.sqlite')
            class Fault:
                @property
                def in_transaction(self):return db.in_transaction
                def execute(self,sql,*args):
                    result=db.execute(sql,*args)
                    if sql.startswith('DELETE FROM audit'):raise RuntimeError('offline_prune_fault')
                    return result
            with self.assertRaisesRegex(RuntimeError,'offline_prune_fault'):audit_ring(Fault(),'audit','immutable_audit',limit=16)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM audit').fetchone()[0],32)
            with self.assertRaisesRegex(sqlite3.IntegrityError,'append_only'):db.execute('DELETE FROM audit')
            db.close()

    def test_parallel_autocommit_sessions_cannot_race_guard_maintenance(self):
        from meme_machine.runtime.storage import audit_ring
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'audit.sqlite';db=self.seed(path);db.close();gate=threading.Barrier(4);errors=[]
            def session():
                connection=sqlite3.connect(path,isolation_level=None,timeout=5)
                try:
                    gate.wait()
                    for n in range(24):
                        connection.execute('INSERT INTO audit(body) VALUES(?)',(str(n),))
                        audit_ring(connection,'audit','immutable_audit',limit=16)
                except Exception as error:errors.append(error)
                finally:connection.close()
            threads=[threading.Thread(target=session) for _ in range(4)]
            for thread in threads:thread.start()
            for thread in threads:thread.join(10);self.assertFalse(thread.is_alive())
            self.assertEqual(errors,[])
            db=sqlite3.connect(path,isolation_level=None)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM audit').fetchone()[0],16)
            with self.assertRaisesRegex(sqlite3.IntegrityError,'append_only'):db.execute('DELETE FROM audit')
            db.close()

    def test_existing_owner_transaction_is_not_committed_by_reporting(self):
        from meme_machine.runtime.storage import audit_ring
        with tempfile.TemporaryDirectory() as td:
            db=self.seed(Path(td)/'audit.sqlite');db.execute('BEGIN IMMEDIATE')
            audit_ring(db,'audit','immutable_audit',limit=16)
            self.assertTrue(db.in_transaction);db.execute('ROLLBACK')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM audit').fetchone()[0],32);db.close()
