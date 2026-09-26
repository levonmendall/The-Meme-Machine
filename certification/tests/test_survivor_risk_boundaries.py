"""Frozen v1 exits, exact boundaries and durable observation identity."""
import unittest
from certification.survivor_risk import mark,new_regime

POLICIES={
 'pump':dict(hard_stop_bps=-1200,first_profit_bps=2500,first_sell_bps=2500,trail_bps=2000,
             tight_arm_bps=6000,tight_trail_bps=1500,soft_confirmations=2,maximum_hold_seconds=259200),
 'pons':dict(hard_stop_bps=-1000,first_profit_bps=2000,first_sell_bps=2500,trail_bps=1200,
             tight_arm_bps=4000,tight_trail_bps=1000,soft_confirmations=2,maximum_hold_seconds=259200,
             stale_seconds=21600,stale_return_ceiling_bps=500)}

def state():return dict(opened_at=0,original_quantity=401,remaining_quantity=401,high_water_bps=0,
                       high_at=0,realization_taken=False,tightened=False,deterioration_streak=0)
def observation(n,value,**kw):return dict(id=str(n),at=n,after_cost_return_bps=value,exit_liquidity_valid=True,**kw)

class ExitBoundaries(unittest.TestCase):
 def test_hard_stop_exact_and_one_bps_above(self):
  for policy in POLICIES.values():
   self.assertEqual(mark(state(),observation(1,policy['hard_stop_bps']+1),policy)[1]['action'],'hold')
   self.assertEqual(mark(state(),observation(1,policy['hard_stop_bps']),policy)[1]['reason'],'hard_stop')
 def test_realization_exact_original_quantity_once(self):
  for policy in POLICIES.values():
   self.assertEqual(mark(state(),observation(1,policy['first_profit_bps']-1),policy)[1]['action'],'hold')
   s,a=mark(state(),observation(1,policy['first_profit_bps']),policy)
   self.assertEqual((a['action'],a['quantity']),('partial_exit',100))
   s.update(realization_taken=True,remaining_quantity=301)
   self.assertEqual(mark(s,observation(2,policy['first_profit_bps']+100),policy)[1]['action'],'hold')
 def test_trail_exact_price_drawdown_and_permanent_tightening(self):
  for policy in POLICIES.values():
   for high,trail in ((policy['first_profit_bps'],policy['trail_bps']),
                      (policy['tight_arm_bps'],policy['tight_trail_bps'])):
    s,_=mark(state(),observation(1,high),policy);s.update(realization_taken=True,remaining_quantity=301)
    boundary=(10000+high)*(10000-trail)//10000-10000
    self.assertEqual(mark(s,observation(2,boundary+1),policy)[1]['action'],'hold')
    self.assertEqual(mark(s,observation(2,boundary),policy)[1]['reason'],'runner_trail')
    if high==policy['tight_arm_bps']:
     s,_=mark(s,observation(2,high-1),policy)
     self.assertTrue(s['tightened']);self.assertEqual(s['high_water_bps'],high)
 def test_tightening_only_at_threshold(self):
  for p in POLICIES.values():
   self.assertFalse(mark(state(),observation(1,p['tight_arm_bps']-1),p)[0]['tightened'])
   self.assertTrue(mark(state(),observation(1,p['tight_arm_bps']),p)[0]['tightened'])
 def test_two_distinct_consecutive_soft_observations(self):
  for p in POLICIES.values():
   o=observation(1,0,soft_deterioration=True);s,a=mark(state(),o,p)
   self.assertEqual(a['action'],'hold');s,a=mark(s,o,p)
   self.assertEqual(a['action'],'hold');self.assertEqual(s['deterioration_streak'],1)
   s,a=mark(s,observation(2,0,soft_deterioration=True),p)
   self.assertEqual(a['reason'],'persistent_demand_deterioration')
 def test_good_resets_streak_unknown_does_not_invent_confirmation(self):
  for p in POLICIES.values():
   s,_=mark(state(),observation(1,0,soft_deterioration=True),p)
   s,a=mark(s,observation(2,None,soft_deterioration=None),p)
   self.assertEqual((s['deterioration_streak'],a['action']),(1,'hold'))
   s,_=mark(s,observation(3,0,soft_deterioration=False),p)
   self.assertEqual(s['deterioration_streak'],0)
 def test_seventy_two_hour_maximum_even_without_quote(self):
  for p in POLICIES.values():
   self.assertEqual(mark(state(),observation(259199,None),p)[1]['action'],'hold')
   self.assertEqual(mark(state(),observation(259200,None),p)[1]['reason'],'maximum_hold')
   s,_=mark(state(),dict(observation(259199,None),id='same_block'),p)
   self.assertEqual(mark(s,dict(observation(259200,None),id='same_block'),p)[1]['reason'],'maximum_hold')
 def test_pons_six_hour_stale_thesis_and_return_boundary(self):
  p=POLICIES['pons']
  self.assertEqual(mark(state(),observation(21599,499),p)[1]['action'],'hold')
  self.assertEqual(mark(state(),observation(21600,499),p)[1]['action'],'hold') # a new high refreshes thesis
  s=state();s.update(high_water_bps=499)
  self.assertEqual(mark(s,observation(21600,498),p)[1]['reason'],'stale_thesis')
  self.assertEqual(mark(s,observation(21600,500),p)[1]['action'],'hold')
 def test_safety_full_exits_and_pending_intent(self):
  for p in POLICIES.values():
   for key in ('creator_distribution','severe_persistent_deterioration','exit_liquidity_valid'):
    o=observation(1,0);o[key]=key!='exit_liquidity_valid'
    s,a=mark(state(),o,p);self.assertEqual(a['action'],'full_exit')
    self.assertEqual(mark(s,observation(2,100),p)[1],a)
 def test_new_regime_requires_time_and_multiple_known_changes(self):
  old=dict(at=0,base_id='base',high_reset_cycle='cycle',buyer_population=['a'])
  self.assertFalse(new_regime(old,dict(old,at=3600)))
  self.assertFalse(new_regime(old,dict(old,at=3600,base_id='new')))
  new=dict(old,at=3600,base_id='new',buyer_population=['b'])
  self.assertTrue(new_regime(old,new));new['at']=3599;self.assertFalse(new_regime(old,new))
