"""Current Pons capacity uses native curve state; repeat features never qualify."""
from dataclasses import asdict
import unittest
from meme_machine.lanes.pons import BoundaryError
from meme_machine.lanes.pons.pons_selective_paper import _entry_capacity
from meme_machine.lanes.pons.pons_selective_continuation import demand_metrics,ENTRY_THRESHOLDS
from tests.lanes.pons.test_pons_selective_continuation import state,trade,vector,events

class CapacityPersistence(unittest.TestCase):
 def test_actual_curve_exact_two_x_resize(self):
  c=_entry_capacity({'state':asdict(state())},3*10**16,21000)
  self.assertGreater(c.final_size,0);self.assertLess(c.final_size,3*10**16)
  self.assertEqual(c.binding_reason,'double_size_stress')
  self.assertLessEqual(c.ordinary_loss_bps,600);self.assertLessEqual(c.double_loss_bps,600)
  self.assertEqual(c,_entry_capacity({'state':asdict(state())},3*10**16,21000))
 def test_deep_capacity_preserved_and_unusable_gas_cancels(self):
  self.assertEqual(_entry_capacity({'state':asdict(state())},10**15,21000).final_size,10**15)
  self.assertEqual(_entry_capacity({'state':asdict(state())},10**15,10**20).final_size,0)
  self.assertEqual(ENTRY_THRESHOLDS['max_roundtrip_loss_bps'],600)
 def test_missing_authoritative_state_fails_closed(self):
  with self.assertRaisesRegex(BoundaryError,'state_missing'):_entry_capacity({},10**15,21000)
 def test_repeat_point_in_time_boundary_and_no_future_information(self):
  rows=[trade('a0','a',10,170),trade('a1','a',30,185),trade('b','b',70,200),trade('future','b',900,201)]
  with self.assertRaisesRegex(BoundaryError,'invalid_selective_market_window'):
   demand_metrics(rows,asof=200,creator_groups=())
  d=demand_metrics(rows[:-1],asof=200,creator_groups=())
  self.assertEqual(d['repeat_independent_groups'],1)
  self.assertEqual(d['repeat_buyer_share_bps'],3000)
  self.assertEqual(d['persistent_buyer_groups'],['a'])
 def test_repeat_context_cannot_bypass_entry_qualification(self):
  rows=events();rows += [trade('repeat'+str(i),e['group'],1,180) for i,e in enumerate(rows)]
  qualified=vector(events=rows)
  failed=vector(events=rows,current_snipe_bps=1)
  self.assertGreater(failed['confirmation_context']['repeat_independent_groups'],0)
  self.assertFalse(failed['current_threshold_pass']);self.assertFalse(failed['ranking_context']['qualified'])
