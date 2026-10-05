"""Actual WAL connections cannot mix journal and projection generations."""
import tempfile,unittest
from pathlib import Path
from meme_machine.runtime.sleeve_reservations import SleeveReservations

class SleeveReconciliationSnapshotTests(unittest.TestCase):
    def books(self,path):
        return [SleeveReservations(path,lane='pump',capital=1000,policies={'current':'a','survivor':'b'},cohort='existing-fixed-epoch') for _ in range(2)]

    def test_other_connection_commit_during_replay_cannot_look_like_corruption(self):
        with tempfile.TemporaryDirectory() as td:
            reader,writer=self.books(Path(td)/'sleeve.sqlite');native=reader.db;interleaved=[]
            class Interleave:
                def __getattr__(self,name):return getattr(native,name)
                def execute(self,sql,*args):
                    cursor=native.execute(sql,*args)
                    if sql=='SELECT * FROM sleeve_journal ORDER BY seq' and not interleaved:
                        interleaved.append(True)
                        writer.reserve('existing-lifecycle',strategy='current',amount=100,at=1)
                    return cursor
            reader.db=Interleave()
            try:
                result=reader.reconcile()
                self.assertEqual(interleaved,[True]);self.assertTrue(result['reconciled'])
                self.assertEqual(result['available'],1000)
                self.assertEqual(result['reserved'],0)
                self.assertFalse(native.in_transaction)
                self.assertEqual(reader.reconcile()['available'],900)
                self.assertEqual(writer.get('existing-lifecycle')['held'],100)
            finally:
                reader.db=native;reader.close();writer.close()

    def test_reconcile_inside_mutation_does_not_commit_caller_transaction(self):
        with tempfile.TemporaryDirectory() as td:
            reader,writer=self.books(Path(td)/'sleeve.sqlite')
            try:
                with self.assertRaisesRegex(RuntimeError,'interrupted-caller'):
                    with reader.transaction():
                        reader._event('reserve',dict(id='rolled-back',strategy='current',amount=100,held=100,at=1,candidate=None,generation=None,regime=None,status='reserved',pnl=0,asset=None,scale_committed=False))
                        self.assertEqual(reader.reconcile()['available'],900)
                        self.assertTrue(reader.db.in_transaction)
                        raise RuntimeError('interrupted-caller')
                self.assertIsNone(writer.get('rolled-back'))
                self.assertEqual(writer.reconcile()['available'],1000)
                self.assertFalse(reader.db.in_transaction)
            finally:reader.close();writer.close()

    def test_real_projection_corruption_still_fails_and_releases_read_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            reader,writer=self.books(Path(td)/'sleeve.sqlite')
            try:
                writer.reserve('existing-lifecycle',strategy='current',amount=100,at=1)
                writer.db.execute("UPDATE sleeve_positions SET body='{}' WHERE id='existing-lifecycle'")
                with self.assertRaisesRegex(ValueError,'sleeve_projection_corruption'):
                    reader.reconcile()
                self.assertFalse(reader.db.in_transaction)
                self.assertFalse(writer.db.in_transaction)
            finally:
                # Deliberately corrupt disposable projections cannot reconcile.
                reader.db.close();writer.db.close()
