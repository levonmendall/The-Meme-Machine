"""Identical-evidence native replay against the frozen pre-optimization path."""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import random
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from meme_machine.runtime.directional_continuation import (
    BRIDGE_GATES,reference_return,scale_budget)
from meme_machine.runtime.scaling_necessary_conditions import scale_necessary_budget
from meme_machine.runtime.sleeve_reservations import SleeveReservations
from meme_machine.runtime.survivor_paper_book import PaperBook
from meme_machine.runtime.survivor_commit import scale,restore_risk
from tests.proven_efficiency_baseline import original_scale,original_scale_budget


class Adapter:
    def __init__(self):
        self.at=2000;self.current_return=9000;self.qualifies=True;self.calls=[]
        self.current=dict(decision=dict(features=dict(independent_buyers=20)))
        self.hook=None;self.local=True;self.block=1;self.fee=0;self.gas=0
    def now(self):return self.at
    def fresh_state(self,candidate):
        self.calls.append('fresh_state')
        return dict(block=self.block,fee=self.fee,gas=self.gas,at=self.at)
    def necessary_scale_return(self,state,p,risk):
        if not self.local:return None
        self.calls.append('local_exit')
        q=self.proceeds(p['tokens'])
        return reference_return(q,p['tokens'],risk['original_basis'],risk['original_quantity'])
    def proceeds(self,qty):
        return max(0,qty*50000*(10000+self.current_return)//(400000*10000)-self.fee-self.gas)
    def fresh_quotes(self,state,target):self.calls.append('fresh_quotes');return self
    def reconstruct(self,state,quotes):
        self.calls.append('reconstruct')
        if self.hook:self.hook()
        return dict(candidate=self.qualifies,features=dict(independent_buyers=20))
    def turnover_cap(self,*args):return 1000000
    def loss(self,n):self.calls.append('size_probe');return 100
    def entry(self,n):self.calls.append('entry');return dict(cost=n,quantity=4000)
    def exit_quote(self,qty):self.calls.append('fresh_exit');return dict(net_proceeds=self.proceeds(qty))
    @contextmanager
    def generation_fence(self,*args):yield
    def validate_current(self,*args):self.calls.append('validate')


class ScalingNecessaryTests(unittest.TestCase):
    def fixture(self,folder,*,capital=1000000,original=50000,high=10000,tail=1000):
        sleeve=SleeveReservations(folder/'sleeve',lane='pump',capital=capital,
            policies={'current':'a','survivor':'b'},cohort='c')
        book=PaperBook(folder/'book',run_id='r',lane='survivor',policy_hash='b',initial=capital)
        sleeve.reserve('r:p',strategy='survivor',amount=original,at=1)
        book.reserve('r:p',original,1,{})
        book.transition('r:p','filled',2,amount=original,tokens=400000)
        book.transition('r:p','partial_harvest',3,amount=original//4+1000,tokens=100000)
        risk=dict(opened_at=2,original_basis=original,original_quantity=400000,
            remaining_quantity=300000,high_water_bps=high,high_at=1000,
            first_tail_crossed_at=tail,realization_taken=True,last_action=dict(action='hold'))
        book.transition('r:p','mark',1001,evidence=dict(risk_state=risk))
        from meme_machine.runtime.directional_continuation import native_sync
        native_sync(book,sleeve,'r:p')
        return book,sleeve,Adapter()

    def run_path(self,path,book,sleeve,adapter):
        with patch('meme_machine.operational.position_continuation.position_only',return_value=False):
            return path(book=book,sleeve=sleeve,identity='r:p',candidate='mint',generation=1,
                adapter=adapter,qualify=lambda x:x,ordinary_limit=600,stress_limit=600,minimum=100)

    def compare(self,**changes):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);pairs=[]
            for i,path in enumerate((original_scale,scale)):
                folder=root/str(i);folder.mkdir()
                book,sleeve,adapter=self.fixture(folder,**changes.get('fixture',{}))
                try:
                    for key,value in changes.get('adapter',{}).items():setattr(adapter,key,value)
                    if changes.get('reserve'):sleeve.reserve('other',strategy='current',amount=sleeve.reconcile()['available']-50,at=1002)
                    result=self.run_path(path,book,sleeve,adapter)
                    pairs.append((result,book.replay(),book._load('r:p'),sleeve.reconcile(),adapter.calls))
                finally:book.close();sleeve.close()
            self.assertEqual(pairs[0][:4],pairs[1][:4])
            return pairs

    def test_equity_ceiling_skips_all_deep_work_with_identical_native_result(self):
        old,new=self.compare(fixture=dict(original=80000))
        self.assertIn('reconstruct',old[-1]);self.assertEqual(new[-1],[])

    def test_high_threshold_and_reservations_skip_all_deep_work(self):
        for changes in (dict(fixture=dict(high=9999)),dict(reserve=999500)):
            with self.subTest(changes=changes):
                old,new=self.compare(**changes)
                self.assertEqual(new[-1],[])
                if 'fixture' in changes:self.assertIn('reconstruct',old[-1])
                else:self.assertEqual(old[-1],[])  # Original allocatable-target check already covers this case.

    def test_gross_high_water_boundary_and_price_recovery(self):
        for current,blocked in ((6999,True),(7000,False),(7001,False),(10000,False)):
            with self.subTest(current=current):
                old,new=self.compare(adapter=dict(current_return=current))
                self.assertEqual('reconstruct' not in new[-1],blocked)
                self.assertIn('reconstruct',old[-1])

    def test_missing_local_price_keeps_the_complete_original_path(self):
        old,new=self.compare(adapter=dict(current_return=6000,local=False))
        self.assertEqual(old[-1],new[-1])

    def test_long_held_winner_keeps_full_requalification_and_size_checks(self):
        old,new=self.compare(adapter=dict(at=200000,current_return=9000))
        self.assertIn('reconstruct',new[-1]);self.assertIn('size_probe',new[-1]);self.assertIn('validate',new[-1])

    def test_no_failed_decision_survives_price_fee_gas_quantity_block_or_time_change(self):
        with tempfile.TemporaryDirectory() as td:
            book,sleeve,adapter=self.fixture(Path(td))
            try:
                adapter.current_return=6999
                self.assertIsNone(self.run_path(scale,book,sleeve,adapter))
                adapter.current_return=9000;adapter.gas=100000
                self.assertIsNone(self.run_path(scale,book,sleeve,adapter))
                adapter.gas=0;adapter.fee=100000
                self.assertIsNone(self.run_path(scale,book,sleeve,adapter))
                adapter.fee=0;adapter.block+=1;adapter.at+=1;adapter.qualifies=False
                self.assertIsNone(self.run_path(scale,book,sleeve,adapter))
                adapter.qualifies=True
                # Another native partial changes the quantity; replay remains authoritative.
                book.transition('r:p','partial_harvest',adapter.at,amount=1000,tokens=1000)
                result=self.run_path(scale,book,sleeve,adapter)
                self.assertIsNotNone(result);self.assertTrue(restore_risk(book,'r:p')['scale_committed'])
                calls=list(adapter.calls)
                self.assertIsNone(self.run_path(scale,book,sleeve,adapter));self.assertEqual(calls,adapter.calls)
            finally:book.close();sleeve.close()

    def test_capital_reservation_release_and_equity_growth_reopen_opportunity(self):
        with tempfile.TemporaryDirectory() as td:
            book,sleeve,adapter=self.fixture(Path(td))
            try:
                sleeve.reserve('other',strategy='current',amount=sleeve.reconcile()['available']-50,at=1002)
                self.assertIsNone(self.run_path(scale,book,sleeve,adapter));self.assertEqual(adapter.calls,[])
                sleeve.release('other',pnl=10000,at=2000,terminal_hash='offline',native_verified=True,cancelled=True)
                self.assertIsNotNone(self.run_path(scale,book,sleeve,adapter))
            finally:book.close();sleeve.close()

    def test_concurrent_reservation_is_still_checked_at_final_capital_fence(self):
        with tempfile.TemporaryDirectory() as td:
            book,sleeve,adapter=self.fixture(Path(td))
            try:
                adapter.hook=lambda:sleeve.reserve('other',strategy='current',amount=sleeve.reconcile()['available']-50,at=2000)
                self.assertIsNone(self.run_path(scale,book,sleeve,adapter))
                self.assertNotIn('validate',adapter.calls);self.assertFalse(book._load('r:p').get('scale_request'))
            finally:book.close();sleeve.close()

    def test_original_expression_matches_necessary_upper_bound_on_3000_frozen_states(self):
        rng=random.Random(500)
        for _ in range(3000):
            state=dict(scale_committed=rng.choice((False,False,True)),realization_taken=rng.choice((True,False)),
                high_water_bps=rng.randrange(0,60000),first_tail_crossed_at=rng.choice((None,100)),
                original_basis=rng.randrange(1,100000),last_action=dict(action=rng.choice(('hold','full_exit'))))
            sizing=dict(realized_equity=rng.randrange(1,2000000),target=rng.randrange(1,100000),available=rng.randrange(0,100000))
            current=rng.randrange(-1000,60000);now=rng.randrange(100,3000)
            facts={g:True for g in BRIDGE_GATES};facts.update(fresh_strategy_requalified=True,
                fresh_execution_requalified=True,after_cost_return_bps=current)
            sleeve=SimpleNamespace(sizing_basis=lambda *args:sizing)
            expected=original_scale_budget(state,facts,now=now,sleeve=sleeve,execution_allowance=sizing['target'])
            self.assertEqual(scale_budget(state,facts,now=now,sleeve=sleeve,execution_allowance=sizing['target']),expected)
            self.assertEqual(scale_necessary_budget(state,now=now,sizing=sizing,after_cost_return_bps=current),expected)
            self.assertGreaterEqual(scale_necessary_budget(state,now=now,sizing=sizing),expected)

    def test_actual_pump_local_precheck_matches_native_quotes_on_changing_dependencies(self):
        from meme_machine.lanes.pump.pumpswap_survivor_runtime import Runtime,GAS
        from meme_machine.lanes.pump.postgrad import PostGraduationAdapter
        from tests.lanes.pump.test_postgrad_read_efficiency import MeteredRPC,MINT
        from tests.lanes.pump.test_postgrad import fee_config,token_account,WSOL
        rpc=MeteredRPC();native=PostGraduationAdapter(rpc,scan_rpc=object())
        runtime=SimpleNamespace(now=lambda:101,plane=SimpleNamespace(require_usable=lambda scope:None),
            _provider=lambda *args:None,current=dict(id=MINT))
        for quantity,fee,gas,reserve in ((10**9,5,GAS,50_000_000_000),
                (2*10**9,60,GAS+10,80_000_000_000)):
            rpc.fee_acc=fee_config(lp=fee,protocol=0,creator=0)
            rpc.quote_acc=token_account(WSOL,rpc.pool,reserve)
            state=native.pumpswap_snapshot(MINT,101,reuse_verified_pool=True,held_curve_inline=True)
            p=dict(tokens=quantity);risk=dict(original_basis=1000,original_quantity=quantity)
            before=len(rpc.requests)
            with patch('meme_machine.lanes.pump.pumpswap_survivor_runtime.GAS',gas):
                original_quote=Runtime.exit_quote(runtime,quantity,state=state)
                result=Runtime.necessary_scale_return(runtime,state,p,risk)
            self.assertEqual(result,reference_return(original_quote['net_proceeds'],quantity,
                risk['original_basis'],risk['original_quantity']))
            self.assertEqual(len(rpc.requests),before)
            for unavailable in (dict(state,available_time=95),dict(state,market_time=90),{}):
                self.assertIsNone(Runtime.necessary_scale_return(runtime,unavailable,p,risk))
        runtime.plane.require_usable=lambda scope:(_ for _ in ()).throw(ValueError('unusable'))
        self.assertIsNone(Runtime.necessary_scale_return(runtime,state,p,risk))
