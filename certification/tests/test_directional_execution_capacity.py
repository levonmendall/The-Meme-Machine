import tempfile
import unittest
from pathlib import Path

from certification.execution_capacity import resize, turnover_capacity, buyer_persistence, breadth_retained
from certification.sleeve_reservations import SleeveReservations
from certification.survivor_risk import mark, new_regime


class CapacityTests(unittest.TestCase):
    def test_deep_liquidity_exact_double(self):
        calls=[]
        answer=resize(100,10,lambda n: calls.append(n) or 20,ordinary_limit=600)
        self.assertEqual(answer.final_size,100)
        self.assertEqual(calls,[100,200])

    def test_liquidity_cliff_smaller_signal_survives(self):
        answer=resize(100,10,lambda n: 50 if n<=100 else 900,ordinary_limit=600)
        self.assertEqual(answer.final_size,50)
        self.assertEqual(answer.binding_reason,'double_size_stress')
        self.assertEqual(answer.double_loss_bps,50)

    def test_boundaries_minimum_zero_and_missing(self):
        self.assertEqual(resize(10,10,lambda n:600,ordinary_limit=600).final_size,10)
        self.assertEqual(resize(10,10,lambda n:601,ordinary_limit=600).final_size,0)
        self.assertEqual(resize(10,10,lambda n:None,ordinary_limit=600).binding_reason,'unavailable_quote')
        self.assertEqual(resize(0,1,lambda n:0,ordinary_limit=600).final_size,0)

    def test_fixed_cost_does_not_imply_minimum_is_feasible(self):
        a=resize(100,1,lambda n:900 if n<20 or n>120 else 100,ordinary_limit=600)
        self.assertEqual(a.final_size,60)

    def test_ordinary_limit_cannot_be_loosened_by_stress(self):
        a=resize(100,100,lambda n:601 if n==100 else 500,ordinary_limit=600,stress_limit=800)
        self.assertEqual(a.final_size,0)
        self.assertEqual(a.binding_reason,'ordinary_execution')

    def test_turnover_unknown_and_exact_divisor(self):
        self.assertEqual(turnover_capacity(3999,authenticated=True),99)
        for value,auth in [(None,True),(4000,False),(-1,True),(True,True)]:
            with self.assertRaises(ValueError):turnover_capacity(value,authenticated=auth)

    def test_breadth_cross_multiplication_boundary(self):
        self.assertTrue(breadth_retained(20,13,6500))
        self.assertFalse(breadth_retained(20,12,6500))
        self.assertTrue(breadth_retained(5,3,6000))
        self.assertFalse(breadth_retained(0,1,6000))

    def test_repeat_buyer_windows_future_duplicate_and_agent(self):
        def e(i,t,g,q=10):return dict(id=i,at=t,group=g,quote=q,buy=True,authenticated=True)
        rows=[e('1',69,'A'),e('2',70,'A'),e('3',80,'B'),e('4',101,'C'),e('5',90,'agent')]
        result=buyer_persistence(rows+[rows[1]],now=100,window_seconds=30,excluded_groups=['agent'])
        self.assertEqual(result['independent_buyers'],2)
        self.assertEqual(result['repeat_buyers'],1)
        self.assertEqual(result['repeat_buyer_share_bps'],5000)
        self.assertEqual(result['persistent_buyer_groups'],['A'])
        with self.assertRaises(ValueError):buyer_persistence(rows+[dict(rows[1],quote=11)],now=100,window_seconds=30)


class SleeveTests(unittest.TestCase):
    def test_shared_capital_restart_and_idempotent_settlement(self):
        with tempfile.TemporaryDirectory() as td:
            args=dict(lane='pump',capital=100,policies={'current':'a','survivor':'b'},cohort='new')
            path=Path(td)/'sleeve.sqlite'
            book=SleeveReservations(path,**args)
            book.reserve('a',strategy='current',amount=75,at=1)
            with self.assertRaisesRegex(ValueError,'exhausted'):
                book.reserve('b',strategy='survivor',amount=30,at=1)
            book.reserve('b',strategy='survivor',amount=25,at=1)
            book.close();book=SleeveReservations(path,**args)
            self.assertEqual(book.reconcile()['available'],0)
            for _ in range(2):book.release('a',pnl=5,at=2,terminal_hash='proof',native_verified=True)
            self.assertEqual(book.reconcile()['available'],80)
            book.close()

    def test_generation_supersession_blocks_commit_across_restart(self):
        with tempfile.TemporaryDirectory() as td:
            args=dict(lane='pons',capital=100,policies={'current':'a','survivor':'b'},cohort='new')
            path=Path(td)/'sleeve.sqlite';b=SleeveReservations(path,**args)
            row=b.observe('token',strategy='survivor',at=1,state='qualified',evidence={'x':1},regime={})
            b.reserve('r',strategy='survivor',amount=1,at=1,candidate='token',generation=row['generation'],regime={})
            b.observe('token',strategy='survivor',at=2,state='qualified',evidence={'x':2},regime={})
            b.close();b=SleeveReservations(path,**args)
            with self.assertRaisesRegex(ValueError,'superseded_commit'):
                with b.commit_fence('r'):self.fail('superseded fill executed')
            b.close()


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.policy=dict(hard_stop_bps=-1200,first_profit_bps=2500,first_sell_bps=2500,
                         trail_bps=2000,tight_arm_bps=6000,tight_trail_bps=1500,
                         soft_confirmations=2,maximum_hold_seconds=259200)
        self.state=dict(opened_at=0,original_quantity=101,remaining_quantity=101,high_water_bps=0)

    def obs(self,i,ret,**kw):
        return dict(id=str(i),at=i,after_cost_return_bps=ret,exit_liquidity_valid=True,**kw)

    def test_realization_is_original_quantity_once(self):
        state,action=mark(self.state,self.obs(1,2500),self.policy)
        self.assertEqual(action['quantity'],25)
        state.update(realization_taken=True,remaining_quantity=76)
        _,action=mark(state,self.obs(2,3000),self.policy)
        self.assertEqual(action['action'],'hold')

    def test_tightening_permanent_and_exact_trail(self):
        s,_=mark(self.state,self.obs(1,6000),self.policy)
        self.assertTrue(s['tightened'])
        s,a=mark(s,self.obs(2,3601),self.policy)
        self.assertEqual(a['action'],'partial_exit')
        _,a=mark(s,self.obs(3,3600),self.policy)
        self.assertEqual(a['reason'],'runner_trail')

    def test_maximum_hold_cannot_be_masked_by_soft_confirmation(self):
        _,a=mark(self.state,self.obs(259200,0,soft_deterioration=True),self.policy)
        self.assertEqual(a['reason'],'maximum_hold')

    def test_deterioration_distinct_consecutive_observations(self):
        s,a=mark(self.state,self.obs(1,0,soft_deterioration=True),self.policy)
        self.assertEqual(a['action'],'hold')
        duplicate,_=mark(s,self.obs(1,0,soft_deterioration=True),self.policy)
        self.assertEqual(duplicate['deterioration_streak'],1)
        _,a=mark(s,self.obs(2,0,soft_deterioration=True),self.policy)
        self.assertEqual(a['action'],'full_exit')

    def test_hard_stop_boundary(self):
        self.assertEqual(mark(self.state,self.obs(1,-1200),self.policy)[1]['reason'],'hard_stop')
        self.assertEqual(mark(self.state,self.obs(1,-1199),self.policy)[1]['action'],'hold')

    def test_reentry_needs_time_and_multiple_real_changes(self):
        before=dict(at=0,base_id='a',flow_regime='a')
        self.assertFalse(new_regime(before,dict(at=3600,base_id='b',flow_regime='a')))
        self.assertFalse(new_regime(before,dict(at=3599,base_id='b',flow_regime='b')))
        self.assertTrue(new_regime(before,dict(at=3600,base_id='b',flow_regime='b')))


if __name__=='__main__':unittest.main()
