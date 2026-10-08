"""Recovery snapshot must close even when candidate-plane construction fails."""
import sqlite3,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
from meme_machine.runtime.robinhood import pons

class PonsRecoveryConnectionTests(unittest.TestCase):
    def test_plane_construction_failure_closes_native_snapshot(self):
        original=sqlite3.connect;opened=[];closed=[]
        class Tracked(sqlite3.Connection):
            def close(self):closed.append(threading.get_ident());return super().close()
        def connect(*args,**kwargs):
            db=original(*args,**kwargs,factory=Tracked);opened.append(db);return db
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'capital.sqlite';db=original(path)
            db.execute('CREATE TABLE capital_positions(body TEXT)');db.commit();db.close()
            try:
                with patch('sqlite3.connect',side_effect=connect),patch.object(pons,'Plane',side_effect=ValueError('original-plane-failure')):
                    with self.assertRaisesRegex(ValueError,'original-plane-failure'):
                        pons.restore_position_needs(Path(td)/'plane.sqlite',path)
                self.assertEqual(len(opened),1)
                self.assertEqual(closed,[threading.get_ident()])
            finally:
                for db in opened:db.close()

    def test_empty_old_native_schema_success_closes_both_connections(self):
        original=sqlite3.connect;opened=[];closed=[]
        class Tracked(sqlite3.Connection):
            def close(self):closed.append(self);return super().close()
        def connect(*args,**kwargs):
            db=original(*args,**kwargs,factory=Tracked);opened.append(db);return db
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'capital.sqlite';db=original(path)
            db.execute('CREATE TABLE capital_positions(body TEXT)');db.commit();db.close()
            try:
                with patch('sqlite3.connect',side_effect=connect):
                    self.assertEqual(pons.restore_position_needs(Path(td)/'plane.sqlite',path),0)
                self.assertEqual(len(opened),2)
                self.assertCountEqual(closed,opened)
            finally:
                for db in opened:db.close()

    def test_lifecycle_reconciliation_failure_still_closes_native_store(self):
        from meme_machine.lanes.pons import pons_selective_paper as runtime
        from tests.lanes.pons.test_pons_position_provider_recovery import PositionRecoveryTests
        stores=[]
        original=runtime.Store
        def tracked(*args,**kwargs):
            store=original(*args,**kwargs);stores.append(store);return store
        with tempfile.TemporaryDirectory() as td:
            try:
                with patch.object(runtime,'Store',side_effect=tracked),patch.object(runtime.CohortCapital,'reconcile',side_effect=RuntimeError('reconciliation-failure')):
                    with self.assertRaisesRegex(RuntimeError,'reconciliation-failure'):
                        PositionRecoveryTests().run_case(td,'exit')
                self.assertTrue(stores)
                for store in stores:
                    with self.assertRaises(sqlite3.ProgrammingError):store.db.execute('SELECT 1')
            finally:
                for store in stores:store.close()
