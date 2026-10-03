"""Both active Pump regimes use one durable sleeve, with separate native books."""
from pathlib import Path
from unittest.mock import patch
import os,tempfile,unittest
from certification.directional_sleeve import open_sleeve,recover_pump_terminals
from meme_machine.lanes.pump.paper_accounting import PaperBook
from meme_machine.lanes.pump.pump_acceleration_paper import PumpAccelerationPaperLifecycle
from meme_machine.lanes.pump.pumpswap_survivor import STRATEGY_ID
from tests.lanes.pump.test_pump_acceleration_paper import qualification

class SharedPump(unittest.TestCase):
 def test_native_current_reservation_and_survivor_ceiling_survive_restart(self):
  with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,MM_DIRECTIONAL_SLEEVE_DB=td+'/sleeve',MM_DIRECTIONAL_COHORT_ID='new'):
   book=PaperBook(td+'/current',run_id='r',lane='pump',policy_hash='current-test',initial=1000)
   current=PumpAccelerationPaperLifecycle(book=book,lifecycle_id='r:current')
   current.reserve(qualification(),900,100)
   sleeve=open_sleeve('pump',1000);sleeve.reserve('r:survivor',strategy=STRATEGY_ID,amount=100,at=100)
   with self.assertRaisesRegex(ValueError,'capital_exhausted'):
    sleeve.reserve('r:overflow',strategy=STRATEGY_ID,amount=1,at=100)
   sleeve.close();sleeve=open_sleeve('pump',1000)
   self.assertEqual((sleeve.reconcile()['capital'],sleeve.reconcile()['reserved']),(1000,1000))
   current.fill(100,850,102,'pump.fun');current.mark(900,110,80);current.mark(700,120,20);current.settle(700,122)
   self.assertEqual(sleeve.reconcile()['available'],750)
   sleeve.close();book.close()
 def test_startup_releases_only_proven_absent_current_native_reservation(self):
  with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,MM_DIRECTIONAL_SLEEVE_DB=td+'/sleeve',MM_DIRECTIONAL_COHORT_ID='new'):
   book=PaperBook(td+'/current',run_id='r',lane='pump',policy_hash='current-test',initial=1000)
   sleeve=open_sleeve('pump',1000)
   current=next(s for s in sleeve.identity['policies'] if 'survivor' not in s)
   sleeve.reserve('r:orphan',strategy=current,amount=900,at=100)
   sleeve.reserve('r:survivor',strategy=STRATEGY_ID,amount=100,at=100)
   recover_pump_terminals(book)
   self.assertEqual(sleeve.reconcile()['reserved'],100)
   self.assertTrue(sleeve.get('r:orphan')['cancelled'])
   with self.assertRaisesRegex(ValueError,'terminal_reservation_reused'):sleeve.reserve('r:orphan',strategy=current,amount=900,at=100)
   sleeve.close();book.close()
