"""Actual current-Pons cohort reservations share Survivor's unchanged ceiling."""
from pathlib import Path
from unittest.mock import patch
import os,tempfile,unittest
from certification.directional_sleeve import open_sleeve
from meme_machine.lanes.pons import BoundaryError
from meme_machine.lanes.pons.pons_selective_capital import CohortCapital
from meme_machine.lanes.pons.pons_selective_ledger import STRATEGY_NAMESPACE
from meme_machine.lanes.pons.pons_postgrad_survivor import STRATEGY_VERSION

class SharedPons(unittest.TestCase):
 def test_current_plus_survivor_share_ceiling_and_restart(self):
  with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,MM_DIRECTIONAL_SLEEVE_DB=td+'/sleeve',MM_DIRECTIONAL_COHORT_ID='new'):
   path=Path(td)/'current';current=CohortCapital(path,1000)
   current.reserve('current',900,at=1,decision_hash='a',trial_path='missing')
   sleeve=open_sleeve('pons',1000);sleeve.reserve('survivor',strategy=STRATEGY_VERSION,amount=100,at=1)
   with self.assertRaisesRegex(BoundaryError,'capital_exhausted'):
    current.reserve('overflow',1,at=1,decision_hash='b',trial_path='missing')
   self.assertEqual(sleeve.reconcile()['reserved'],1000)
   current=CohortCapital(path,1000);self.assertEqual(sleeve.reconcile()['reserved'],1000)
   position=dict(id='current',experiment=STRATEGY_NAMESPACE,status='settled',tokens=0,reserved=0,pnl=-100)
   current.settle('current',position,at=2)
   self.assertEqual(sleeve.reconcile()['available'],800)
   current=CohortCapital(path,1000);self.assertEqual(sleeve.reconcile()['available'],800)
   sleeve.close()
 def test_startup_orphan_recovery_never_releases_survivor(self):
  with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,MM_DIRECTIONAL_SLEEVE_DB=td+'/sleeve',MM_DIRECTIONAL_COHORT_ID='new'):
   current=CohortCapital(Path(td)/'current',1000);sleeve=open_sleeve('pons',1000)
   sleeve.reserve('orphan',strategy=STRATEGY_NAMESPACE,amount=900,at=1)
   sleeve.reserve('survivor',strategy=STRATEGY_VERSION,amount=100,at=1)
   current.recover_shared_terminals();self.assertEqual(sleeve.reconcile()['reserved'],1000)
   current.recover_shared_terminals(release_absent=True)
   self.assertEqual(sleeve.reconcile()['reserved'],100);sleeve.close()
