import json
import sqlite3
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import unittest
from meme_machine.paper_accounting import PaperBook
from meme_machine.pump_acceleration_paper import PumpAccelerationPaperLifecycle
from tests.test_pump_acceleration_paper import qualification


class PaperAccountingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=str(Path(self.temp.name)/'book.sqlite')
        self.book=self.open()
    def tearDown(self):
        self.book.db.close()
        self.temp.cleanup()
    def open(self):
        return PaperBook(self.path,run_id='r',lane='pump',policy_hash='frozen',initial=1000)
    def test_actual_lifecycle_replays_after_close_without_recycling_genesis(self):
        life=PumpAccelerationPaperLifecycle(book=self.book,lifecycle_id='r:one')
        life.reserve(qualification(),600,100)
        life.fill(100,550,102,'pump.fun',evidence={'gas':10,'fee':5})
        life.mark(700,110,80)
        life.mark(550,120,20)
        life.settle(550,122)
        self.assertEqual(self.book.reconcile()['cash'],1000)
        self.assertEqual(self.book.reconcile()['capital_unit_seconds'],12200)
        self.book.close();self.book=self.open()
        self.assertEqual(self.book.replay()['cash'],1000)
        self.book.reserve('r:two',600,123,{})
        self.assertEqual(self.book.reconcile()['cash'],400)
    def test_atomic_reservation_across_independent_connections(self):
        other=self.open()
        def reserve(pair):
            b,name=pair
            try:b.reserve(name,600,10,{});return True
            except ValueError as e:
                self.assertEqual(str(e),'paper_capital_exhausted');return False
        with ThreadPoolExecutor(2) as pool:
            out=list(pool.map(reserve,[(self.book,'r:a'),(other,'r:b')]))
        self.assertEqual(sorted(out),[False,True]);other.close()
        self.assertEqual(self.book.reconcile()['reserved'],600)
    def test_duplicate_settlement_and_namespace_fail_closed(self):
        self.book.reserve('r:a',400,10,{})
        self.book.transition('r:a','filled',12,amount=390,tokens=10)
        self.book.transition('r:a','settled',20,amount=420)
        with self.assertRaisesRegex(ValueError,'duplicate'):
            self.book.transition('r:a','settled',21,amount=420)
        self.assertEqual(self.book.reconcile()['cash'],1030)
        with self.assertRaisesRegex(ValueError,'identity'):
            self.book.reserve('other:a',10,21,{})
    def test_append_only_and_mutable_projection_corruption_detected(self):
        self.book.reserve('r:a',400,10,{})
        with self.assertRaises(sqlite3.IntegrityError):
            self.book.db.execute('DELETE FROM journal')
        p=json.loads(self.book.db.execute('SELECT body FROM positions').fetchone()[0])
        p['reserved']=0
        self.book.db.execute('UPDATE positions SET body=?',(json.dumps(p),))
        with self.assertRaisesRegex(ValueError,'projection'):
            self.book.replay()
    def test_float_money_time_regression_and_overfill_fail(self):
        with self.assertRaises(ValueError):self.book.reserve('r:a',400.0,10,{})
        self.book.reserve('r:a',400,10,{})
        with self.assertRaises(ValueError):self.book.transition('r:a','filled',12,amount=401,tokens=5)
        with self.assertRaises(ValueError):self.book.transition('r:a','cancelled',9)
        self.assertEqual(self.book.reconcile()['reserved'],400)

if __name__=='__main__':unittest.main()
