"""Native record decoding and fail-closed lineage on a canonical offline tape."""
import os,tempfile,unittest
from unittest.mock import patch
from engineering.pons_history.fixtures import Tape
from meme_machine.lanes.pons import BoundaryError
from meme_machine.lanes.pons.pons_natural_paper import _graduation_transition
from meme_machine.lanes.pons.pons_survivor_runtime import Runtime

MODULE='meme_machine.lanes.pons.pons_historical'

class SurvivorGraduationTests(unittest.TestCase):
 def run_case(self,complete):
  with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,{
      'MM_DIRECTIONAL_SLEEVE_DB':td+'/sleeve','MM_DIRECTIONAL_COHORT_ID':'run379'},clear=True):
   tape=Tape(candidates=1);tape.top=tape.grad-10
   runtime=Runtime(td+'/survivor',10**18,'run379','https://robinhood-mainnet.g.alchemy.com/v2/offline')
   runtime.rpc=tape;runtime.now=lambda:int(tape.header(tape.top)['timestamp'],16)
   try:
    runtime.discover();tape.top=tape.grad
    def transition(rpc,candidate,start,end,report):
     # Preserve the actual _factory_record_at -> _call -> ABI decoding path.
     self.assertEqual(len(report['reads']),1)
     self.assertEqual(report['reads'][0]['signature'],'getLaunchedToken(address)')
     self.assertEqual(candidate,dict(token=tape.tokens[0],curve=tape.records[tape.tokens[0]]['curve']))
     return _graduation_transition(rpc,candidate,start,end,report) if complete else None
    with patch(MODULE+'._graduation_transition',side_effect=transition):
     if complete:runtime.discover()
     else:
      with self.assertRaisesRegex(BoundaryError,'historical_graduation_missing'):runtime.discover()
    self.assertEqual(runtime.history.get_meta('discovery_block'),tape.grad)
    if complete:
     self.assertEqual(runtime.history.get(tape.tokens[0])['block'],tape.grad)
     self.assertTrue(runtime.history.get(tape.tokens[0])['complete'])
     points,events=runtime.history.facts(tape.tokens[0],runtime.now())
     self.assertEqual(len(points),1);self.assertEqual(events,[])
     runtime.discover();self.assertEqual(len(runtime.history.rows()),1)
    else:
     # Raw nomination and cursor commit together. Missing lineage never creates
     # an authenticated candidate, and the nomination survives for retry.
     self.assertEqual(runtime.history.pending_graduations(),1)
     self.assertEqual(runtime.history.rows(),[])
    self.assertEqual(runtime.book.reconcile()['open_positions'],0)
    self.assertTrue(runtime.sleeve.reconcile()['reconciled'])
   finally:runtime.close()
 def test_first_graduation_advances_durable_candidate_history(self):self.run_case(True)
 def test_missing_lineage_still_fails_closed_without_advancing_candidate(self):self.run_case(False)
