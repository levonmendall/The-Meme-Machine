"""Current capital recovery must compare one actual SQLite journal generation."""
from contextlib import closing
import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from meme_machine.lanes.pons.pons_selective_capital import CohortCapital
from meme_machine.runtime.directional_sleeve import policies
from meme_machine.runtime.sleeve_reservations import SleeveReservations

class PonsCapitalRecoverySnapshotTests(unittest.TestCase):
    def test_other_connection_reservation_cannot_create_false_recovery_corruption(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);path=root/'capital.sqlite'
            reader=CohortCapital(path,1000);writer=CohortCapital(path,1000)
            with closing(reader._connect()) as db:db.execute('PRAGMA journal_mode=WAL')
            def sleeve(*_):return SleeveReservations(root/'sleeve.sqlite',lane='pons',capital=1000,policies=policies('pons'),cohort='existing-fixed-epoch')
            original=reader._connect;interleaved=[]
            class Interleave:
                def __init__(self,db):self.db=db
                def __getattr__(self,name):return getattr(self.db,name)
                def execute(self,sql,*args):
                    cursor=self.db.execute(sql,*args)
                    if sql=='SELECT id,action,body,hash FROM capital_journal ORDER BY seq' and not interleaved:
                        interleaved.append(True)
                        writer.reserve('existing-lifecycle',100,at=1,decision_hash='existing-decision',trial_path=root/'existing-native.sqlite')
                    return cursor
            with patch('meme_machine.runtime.directional_sleeve.open_sleeve',side_effect=sleeve),patch.object(reader,'_connect',side_effect=lambda:Interleave(original())):
                reader.recover_shared_terminals()
                self.assertEqual(interleaved,[True])
                self.assertEqual(writer.reconcile()['reserved'],100)
                with closing(sleeve()) as shared:
                    self.assertEqual(shared.get('existing-lifecycle')['held'],100)
                    self.assertEqual(shared.reconcile()['available'],900)
