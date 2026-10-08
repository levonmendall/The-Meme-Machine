"""Run 377: use the real provider constructor under the existing governor."""
import os,tempfile,unittest
from unittest.mock import patch
from meme_machine.lanes.pons.pons_survivor_runtime import Runtime
from meme_machine.lanes.pons.provider import Rpc
from meme_machine.lanes.pons.provider_topology import PacedRpc
from meme_machine.lanes.pons import BoundaryError
from meme_machine.lanes.pons.provider_topology import configured_rpc
from engineering.pons_history.fixtures import Tape

URL='https://robinhood-mainnet.g.alchemy.com/v2/OFFLINE_RUN377_FIXTURE'

class SurvivorProviderTests(unittest.TestCase):
 def test_survivor_constructs_governed_session_and_advances_discovery(self):
  with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,{
    'MM_ROBINHOOD_READ_RPC_URL':URL,'MM_ROBINHOOD_STATE_DIR':td+'/provider',
    'MM_DIRECTIONAL_SLEEVE_DB':td+'/sleeve','MM_DIRECTIONAL_COHORT_ID':'run377'},clear=True):
   runtime=Runtime(td+'/survivor',10**18,'run377',URL)
   try:
    # Preserve the real configured/PacedRpc/Rpc constructors and chain guard;
    # only their transport is injected. No provider connection is opened.
    tape=Tape(candidates=0);tape.top=tape.grad
    def provider(endpoint,**kwargs):return configured_rpc(endpoint,transport=tape._read,**kwargs)
    with patch('meme_machine.lanes.pons.pons_survivor_runtime.configured_rpc',side_effect=provider):
     result=runtime.step(admit=True)
    self.assertIsNone(result['last_boundary'])
    self.assertEqual(runtime.history.get_meta('discovery_block'),tape.top)
    self.assertLessEqual(runtime.rpc.limit,200)
    self.assertLessEqual(runtime.rpc.per_scope,runtime.rpc.limit)
    self.assertTrue(runtime.rpc.canonical_authority)
    self.assertTrue(runtime.rpc.chain_verified)
    self.assertEqual(runtime.rpc.shared_admission.interval,.5)
    first=runtime.rpc;first.used=151
    with patch('meme_machine.lanes.pons.pons_survivor_runtime.configured_rpc',side_effect=provider):
     self.assertIsNone(runtime.step(admit=True)['last_boundary'])
    self.assertIsNot(first,runtime.rpc)
    self.assertTrue(runtime.rpc.chain_verified)
    self.assertEqual(runtime.book.reconcile()['open_positions'],0)
    self.assertTrue(runtime.sleeve.reconcile()['reconciled'])
   finally:runtime.close()
 def test_provider_still_rejects_original_invalid_bounds(self):
  with self.assertRaisesRegex(BoundaryError,'invalid_request_bounds'):
   Rpc(URL,limit=240,per_scope=220,retries=0)
