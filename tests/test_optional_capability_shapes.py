"""Malformed optional capability hints must not terminate ordinary read acquisition."""
import hashlib,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from meme_machine.lanes.pons.pons_selective_acquisition import SelectiveEvidenceContext
from meme_machine.lanes.pons import provider_topology as pons_topology
from meme_machine.lanes.ramses import provider_topology as ramses_topology

ENDPOINT='https://robinhood-mainnet.g.alchemy.com/v2/offline-test'
DOMAIN=hashlib.sha256(('4663:'+ENDPOINT).encode()).hexdigest()
BAD_SHAPES=[[],None,{'endpoints':[]},
            {'endpoints':{DOMAIN:{'methods':[]}}},
            {'endpoints':{DOMAIN:{'methods':{'eip1898_eth_call':None}}}}]
class OptionalCapabilityShapeTests(unittest.TestCase):
 def environment(self,folder,body):
  cap=Path(folder)/'capabilities.json';cap.write_text(json.dumps(body))
  return {'MM_RPC_CAPABILITIES':str(cap),'MM_PROVIDER_DB':str(Path(folder)/'provider.sqlite'),
          'MM_RPC_CACHE_DB':str(Path(folder)/'cache.sqlite'),
          'MM_ROBINHOOD_READ_RPC_URL':ENDPOINT,'MM_ROBINHOOD_DLMM_RPC_URL':ENDPOINT}
 def test_selective_context_bad_hint_keeps_ordinary_acquisition(self):
  for body in BAD_SHAPES:
   with self.subTest(body=body),tempfile.TemporaryDirectory() as folder:
    with patch.dict(os.environ,self.environment(folder,body)):
     context=SelectiveEvidenceContext(ENDPOINT)
     self.assertFalse(context.block_receipts_supported)
     self.assertFalse(context.view_batch_state['supported'])
     self.assertIsNone(context.rpc)
 def test_both_provider_factories_ignore_malformed_optional_hint(self):
  for topology in (pons_topology,ramses_topology):
   for body in BAD_SHAPES:
    with self.subTest(module=topology.__name__,body=body),tempfile.TemporaryDirectory() as folder:
     with patch.dict(os.environ,self.environment(folder,body)):
      try:
       rpc=topology.configured_rpc(ENDPOINT,limit=80,per_scope=40,retries=0,
                                  transport=lambda *args:self.fail('unexpected provider I/O'))
       self.assertEqual(rpc.hash_state_supported,set())
       self.assertFalse(rpc.chain_verified)
       self.assertEqual((rpc.limit,rpc.per_scope,rpc.retries),(80,40,0))
      finally:
       from importlib import import_module
       immutable=import_module(topology.__package__+'.immutable_rpc')
       with immutable._lock:
        for name in list(immutable._stores):
         if str(Path(folder)) in name:immutable._stores.pop(name).db.close()

 def test_valid_hint_keeps_optimization_and_cannot_grant_entry_authority(self):
  body={'endpoints':{DOMAIN:{'methods':{
       'eth_getBlockReceipts':{'supported':True},'eth_callMany':{'supported':True},
       'eip1898_eth_call':{'supported':True},'eip1898_eth_getCode':{'supported':False}}}}}
  with tempfile.TemporaryDirectory() as folder:
   with patch.dict(os.environ,self.environment(folder,body)):
    context=SelectiveEvidenceContext(ENDPOINT)
    self.assertTrue(context.block_receipts_supported)
    self.assertTrue(context.view_batch_state['supported'])
    self.assertIsNone(context.rpc)
    for topology in (pons_topology,ramses_topology):
     try:
      rpc=topology.configured_rpc(ENDPOINT,limit=80,per_scope=40,retries=0,
                                 transport=lambda *args:self.fail('unexpected provider I/O'))
      self.assertEqual(rpc.hash_state_supported,{'eth_call'})
      self.assertFalse(rpc.chain_verified)
     finally:
      from importlib import import_module
      immutable=import_module(topology.__package__+'.immutable_rpc')
      with immutable._lock:
       for name in list(immutable._stores):
        if str(Path(folder)) in name:immutable._stores.pop(name).db.close()

if __name__=='__main__':unittest.main()
