"""Current decisions never retire independent Survivor observation/eligibility."""
import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from meme_machine.runtime.sleeve_reservations import SleeveReservations

class CurrentSurvivorIndependenceTests(unittest.TestCase):
    def sleeve(self,path,lane):
        return SleeveReservations(path,lane=lane,capital=100000,
            policies={'current':'a','survivor':'b'},cohort='preserved-epoch')

    def test_rejection_reason_cannot_suppress_later_survivor_across_restart(self):
        for lane in ('pump','pons'):
            for reason in ('alpha','creator_distribution','concentration','stale_evidence','execution','unrecognized_future_reason'):
                with self.subTest(lane=lane,reason=reason),tempfile.TemporaryDirectory() as td:
                    path=Path(td)/'sleeve.sqlite';s=self.sleeve(path,lane)
                    try:
                        s.opportunity('asset',identity='current',regime='current',status='rejected',at=1,decision={'reason':reason})
                    finally:s.close()
                    s=self.sleeve(path,lane)
                    try:
                        row=s.observe('asset',strategy='survivor',at=2,state='qualified',evidence={'fresh':True,'survivor_owned_safety_pass':True},regime={'at':2})
                        s.reserve('survivor',strategy='survivor',amount=5000,at=2,candidate='asset',generation=row['generation'],regime={'at':2})
                        self.assertEqual(s.get('survivor')['held'],5000)
                        self.assertEqual(s.identity['cohort'],'preserved-epoch')
                    finally:s.close()

    def test_exited_current_allows_survivor_but_observation_survives_active_fence(self):
        for lane in ('pump','pons'):
            with self.subTest(lane=lane),tempfile.TemporaryDirectory() as td:
                path=Path(td)/'sleeve.sqlite';s=self.sleeve(path,lane)
                try:
                    s.reserve('current',strategy='current',amount=5000,at=1,asset='asset')
                    s.opportunity('asset',identity='survivor-observation',regime='survivor',status='observed',at=2)
                    row=s.observe('asset',strategy='survivor',at=2,state='qualified',evidence={'fresh':True},regime={'at':2})
                    for status in ('rejected','closed'):
                        s.opportunity('asset',identity='current',regime='current',status=status,at=3,decision={'reason':'current_only'})
                        link=json.loads(s.db.execute('SELECT body FROM opportunity_links').fetchone()[0])
                        self.assertEqual(link['survivor']['identity'],'survivor-observation')
                        self.assertEqual(s.candidate('asset'),row)
                    with self.assertRaisesRegex(ValueError,'same_asset_exposure'):
                        s.reserve('survivor',strategy='survivor',amount=5000,at=3,candidate='asset',generation=row['generation'],regime={'at':2})
                    s.acknowledge_native('current',basis=3750,pnl=500,at=4,native_hash='partial',native_verified=True)
                    s.release('current',pnl=1000,at=5,terminal_hash='verified-exit',native_verified=True)
                finally:s.close()
                s=self.sleeve(path,lane)
                try:
                    row=s.observe('asset',strategy='survivor',at=6,state='qualified',evidence={'fresh':True},regime={'at':6})
                    s.reserve('survivor',strategy='survivor',amount=5000,at=6,candidate='asset',generation=row['generation'],regime={'at':6})
                    self.assertEqual(s.get('survivor')['held'],5000)
                    self.assertEqual(s.reconcile()['realized'],1000)
                finally:s.close()
