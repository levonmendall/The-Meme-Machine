"""Capacity connects to the unchanged Pump quote and qualification primitives."""
import ast,json,subprocess,unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from meme_machine.lanes.pump import runner as runtime
from meme_machine.lanes.pump import pump_acceleration_strategy as strategy
from meme_machine.lanes.pump.provider import Unavailable

class CurrentPumpCapacity(unittest.TestCase):
 def test_entry_alpha_functions_unchanged_from_preserved_source(self):
  old=subprocess.check_output(['git','show','3c9553afb3caa92ab5f3db769f870df033a9630f:meme_machine/pump_acceleration_strategy.py']).decode()
  before=ast.parse(old);after=ast.parse(Path(strategy.__file__).read_text())
  functions=lambda tree:{n.name:ast.dump(n,include_attributes=False) for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
  self.assertEqual(functions(before),functions(after))
 def test_authentic_captured_curve_capacity(self):
  fixture=json.loads((Path(__file__).parent/'fixtures/mainnet_candidate_accounts.json').read_text())
  snapshot=dict(accounts=fixture['response']['value'])
  result,telemetry=runtime._capacity(snapshot,400_000_000,10_000_000)
  self.assertGreater(result.final_size,0);self.assertLessEqual(result.final_size,10_000_000)
  self.assertLessEqual(result.ordinary_loss_bps,600);self.assertLessEqual(result.double_loss_bps,600)
  self.assertEqual(telemetry['turnover_cap'],10_000_000)
 def test_captured_pumpswap_account_map_uses_pool_quote_not_curve_decoder(self):
  fixture=json.loads((Path(__file__).parent/'fixtures/postgrad_pumpswap_mainnet.json').read_text())
  snapshot=fixture['capture']['snapshot']
  result,t=runtime._capacity(snapshot,4_000_000_000,100_000_000)
  self.assertEqual(result.final_size,100_000_000)
  self.assertLessEqual(result.ordinary_loss_bps,600);self.assertLessEqual(result.double_loss_bps,600)
  self.assertEqual(t['binding_cap'],'capital')
 def test_turnover_does_not_enlarge_and_missing_fails_closed(self):
  with patch.object(runtime,'GAS',0),patch.object(runtime,'buy_quote',side_effect=lambda s,n:SimpleNamespace(input_amount=n,output_amount=n)),patch.object(runtime,'sell_quote',side_effect=lambda s,n:SimpleNamespace(output_amount=n)):
   for turnover,expected,binding in ((4000,100,'capital'),(2000,50,'turnover'),(0,0,'turnover')):
    result,t=runtime._capacity({},turnover,100)
    self.assertEqual(result.final_size,expected);self.assertEqual(t['binding_cap'],binding)
    self.assertEqual(t['liquidity_execution_cap'],100);self.assertEqual(t['capital_cap'],100)
   with self.assertRaisesRegex(ValueError,'authenticated_turnover'):runtime._capacity({},None,100)
 def test_liquidity_cliff_preserves_smaller_entry_with_exact_two_x(self):
  sizes=[]
  def buy(s,n):sizes.append(n);return SimpleNamespace(input_amount=n,output_amount=n)
  def sell(s,n):return SimpleNamespace(output_amount=n if n<=100 else n*9//10)
  with patch.object(runtime,'GAS',0),patch.object(runtime,'buy_quote',side_effect=buy),patch.object(runtime,'sell_quote',side_effect=sell):
   result,t=runtime._capacity({},4000,100)
  self.assertEqual(result.final_size,50);self.assertIn(100,sizes)
  self.assertEqual(t['binding_cap'],'double_size_stress');self.assertEqual(strategy.POLICY.max_immediate_roundtrip_loss_bps,600)
 def test_unavailable_quote_zero_capacity(self):
  with patch.object(runtime,'buy_quote',side_effect=Unavailable('offline_missing_quote')):
   result,_=runtime._capacity({},4000,100)
  self.assertEqual(result.final_size,0)
