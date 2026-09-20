from concurrent.futures import ThreadPoolExecutor
import tempfile
import sqlite3
from pathlib import Path
import unittest
from robinhood_research import BoundaryError
from robinhood_research.pons_selective_capital import CohortCapital
from robinhood_research.pons_selective_ledger import STRATEGY_NAMESPACE

class CohortCapitalTests(unittest.TestCase):
    def test_concurrent_trials_cannot_each_spend_the_same_genesis(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'pool.sqlite';pool=CohortCapital(path,1000)
            def reserve(i):
                try:
                    CohortCapital(path,1000).reserve(str(i),600,at=1,decision_hash='a'*64,trial_path='trial'+str(i))
                    return 'reserved'
                except BoundaryError as e:return str(e)
            with ThreadPoolExecutor(max_workers=2) as executor:results=list(executor.map(reserve,range(2)))
            self.assertEqual(sorted(results),['reserved','selective_cohort_capital_exhausted'])
            r=pool.reconcile();self.assertEqual(r['reserved'],600);self.assertEqual(r['available'],400)
            self.assertTrue(r['conservation'])

    def test_settlement_recycles_once_and_failed_trial_keeps_reservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=CohortCapital(Path(tmp)/'pool.sqlite',1000)
            p.reserve('a',600,at=1,decision_hash='a'*64,trial_path='a.sqlite')
            self.assertEqual(CohortCapital(p.path,1000).reconcile()['unsettled'],1)
            position=dict(id='a',experiment=STRATEGY_NAMESPACE,status='settled',tokens=0,reserved=0,pnl=-100)
            r=p.settle('a',position,at=2)
            self.assertEqual((r['genesis'],r['available'],r['realized']),(1000,900,-100))
            with self.assertRaisesRegex(BoundaryError,'duplicate_settlement'):p.settle('a',position,at=3)
            p.reserve('b',900,at=3,decision_hash='b'*64,trial_path='b.sqlite')
            self.assertEqual(p.reconcile()['available'],0)
            with self.assertRaisesRegex(BoundaryError,'native_settlement_required'):
                p.settle('b',dict(position,id='b',status='open',tokens=1),at=4)
            self.assertEqual(p.reconcile()['reserved'],900)

    def test_genesis_and_foreign_position_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'pool.sqlite';p=CohortCapital(path,1000)
            with self.assertRaisesRegex(BoundaryError,'genesis_mismatch'):CohortCapital(path,1001)
            p.reserve('a',100,at=1,decision_hash='a'*64,trial_path='a.sqlite')
            with self.assertRaisesRegex(BoundaryError,'native_settlement_required'):
                p.settle('a',dict(id='a',experiment='ramses',status='settled',tokens=0,reserved=0,pnl=0),at=2)
            self.assertEqual(p.reconcile()['reserved'],100)

    def test_deleted_projection_cannot_release_reserved_capital(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=CohortCapital(Path(tmp)/'pool.sqlite',1000)
            p.reserve('a',900,at=1,decision_hash='a'*64,trial_path='a.sqlite')
            with sqlite3.connect(p.path) as db:db.execute('DELETE FROM capital_positions')
            with self.assertRaisesRegex(BoundaryError,'projection_mismatch'):p.reconcile()
            with self.assertRaisesRegex(BoundaryError,'projection_mismatch'):
                p.reserve('b',900,at=2,decision_hash='b'*64,trial_path='b.sqlite')

if __name__=='__main__':unittest.main()
