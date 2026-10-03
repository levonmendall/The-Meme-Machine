"""Missing-state recovery stays distinct from immutable/authentication failure."""
import io,json,unittest
from unittest.mock import patch
from meme_machine.lanes.ramses.provider import Rpc
from meme_machine.lanes.ramses import BoundaryError
from meme_machine.lanes.ramses.ramses_extended_test import _scan_with_capacity_recovery

class Run377RpcStateTests(unittest.TestCase):
 def call(self,message,*,batch=False):
  rpc=Rpc('https://offline.invalid/fixture',retries=0)
  error=dict(jsonrpc='2.0',id=1,error=dict(code=-32000,message=message))
  response=[error] if batch else error
  with patch('meme_machine.lanes.ramses.provider.urlopen',return_value=io.BytesIO(json.dumps(response).encode())):
   try:
    if batch:rpc.batch([('eth_call',[{'to':'factory','data':'0x4e937c3a'},{'blockHash':'0xabc'}])])
    else:rpc.call('eth_call',[{'to':'factory','data':'0x4e937c3a'},{'blockHash':'0xabc'}])
   except BoundaryError as exc:return str(exc),rpc.last_provider_rpc_error
  self.fail('missing state must never return positive evidence')
 def test_missing_hash_state_is_typed_and_deferred_without_partial_screen(self):
  for batch in (False,True):
   reason,detail=self.call('header not found',batch=batch)
   self.assertEqual(reason,'provider_state_unavailable')
   self.assertEqual(detail['code'],-32000)
   self.assertEqual(detail['category'],'state_unavailable')
   rows=[]
   def missing():raise BoundaryError(reason)
   result=_scan_with_capacity_recovery(missing,deadline=10,clock=lambda:1,record_failure=rows.append)
   self.assertTrue(result['_scan_deferred']);self.assertEqual(len(rows),1)
   self.assertFalse(rows[0]['qualification_inferred'])
   self.assertEqual(_scan_with_capacity_recovery(lambda:{'complete':True},deadline=10,clock=lambda:2,record_failure=rows.append),{'complete':True})
 def test_unclassified_or_revert_error_remains_terminal_and_secret_safe(self):
  for message in ('execution reverted','unknown https://offline.invalid/private-key'):
   reason,detail=self.call(message)
   self.assertEqual(reason,'provider_rpc_-32000')
   self.assertNotIn('https://offline.invalid/private-key',json.dumps(detail))
   if message=='execution reverted':self.assertEqual(detail['message_excerpt'],message)
   def failure():raise BoundaryError(reason)
   with self.assertRaisesRegex(BoundaryError,'provider_rpc_-32000'):
    _scan_with_capacity_recovery(failure,deadline=10,clock=lambda:1,record_failure=lambda row:None)

 def test_unknown_provider_message_is_bounded_and_redacted_for_causal_review(self):
  from certification.robinhood.rpc_errors import classify
  endpoint='https://alchemy.invalid/v2/PRIVATE_FIXTURE_377'
  message='unsupported state selector '+endpoint+' PRIVATE_FIXTURE_377 authorization=secret bearer OTHER_SECRET Authorization: Bearer THIRD_SECRET '+('x'*9000)
  detail=classify({'code':-32000,'message':message},endpoint)
  self.assertEqual(detail['category'],'unclassified')
  self.assertTrue(detail['truncated']);self.assertLessEqual(len(detail['message_excerpt']),512)
  self.assertIn('unsupported state selector',detail['message_excerpt'])
  for secret in (endpoint,'PRIVATE_FIXTURE_377','OTHER_SECRET','THIRD_SECRET','authorization=secret'):
   self.assertNotIn(secret,json.dumps(detail))
