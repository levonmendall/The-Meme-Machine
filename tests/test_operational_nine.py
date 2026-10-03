"""Frozen owner directive boundaries; entirely offline native execution and replay."""
import json
import tempfile
import unittest
from dataclasses import asdict,replace
from pathlib import Path
from unittest.mock import patch

from meme_machine.runtime.sleeve_reservations import SleeveReservations
from meme_machine.runtime.survivor_paper_book import PaperBook
from meme_machine.runtime.survivor_risk import mark as survivor_mark
from meme_machine.runtime.survivor_commit import restore_risk
from meme_machine.runtime.directional_continuation import BRIDGE_GATES,bridge_state,scale_budget,reference_return,native_sync
from meme_machine.lanes.pump.pump_acceleration_strategy import POLICY,ExitObservation,MODE_LATE_CURVE,exit_decision
from meme_machine.lanes.pump.pump_acceleration_paper import PumpAccelerationPaperLifecycle
from meme_machine.lanes.pump.paper_accounting import PaperBook as PumpBook
from meme_machine.lanes.pons.pons_selective_continuation import EXIT_POLICY,ENTRY_THRESHOLDS,runner_action
from tests.lanes.pump.test_pump_acceleration_paper import qualification

FACTS={k:True for k in BRIDGE_GATES}

class NineChanges(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.sleeve=SleeveReservations(Path(self.temp.name)/'sleeve.sqlite',lane='pump',capital=100000,
            policies={'current':'a','survivor':'b'},cohort='offline')
        self.addCleanup(self.sleeve.close)

    def pump_exit(self,current,high,**kw):
        return exit_decision(ExitObservation(mode=MODE_LATE_CURVE,now=100,opened_at=0,
            return_bps=current,peak_return_bps=high,demand_score=80,surface='pump.fun',**kw))

    def pons_exit(self,current,high,**kw):
        return runner_action(tokens=1000,partial_taken=True,after_cost_return_bps=current,
            high_water_return_bps=high,seconds_since_high=0,new_buyer_growth=1,buy_quote=100,sell_quote=100,**kw)

    def test_four_targets_share_existing_family(self):
        from meme_machine.lanes.pump.pumpswap_survivor import POLICY as pump_survivor
        from meme_machine.lanes.pons.pons_postgrad_survivor import POLICY as pons_survivor
        self.assertEqual([POLICY.entry_fraction_bps,pump_survivor['target_sleeve_bps'],
            ENTRY_THRESHOLDS['capital_size_bps'],pons_survivor['execution']['target_capital_bps']],[500]*4)
        self.sleeve.reserve('c',strategy='current',amount=5000,at=0,asset='mint')
        self.assertEqual(self.sleeve.sizing_basis(500)['target'],5000)
        self.assertEqual(self.sleeve.reconcile()['available'],95000)

    def test_realized_only_compounding_partial_and_terminal(self):
        self.sleeve.reserve('c',strategy='current',amount=5000,at=0)
        self.sleeve.acknowledge_native('c',basis=3750,pnl=500,at=5,native_hash='replayed-partial',native_verified=True)
        self.assertEqual(self.sleeve.sizing_basis(500)['target'],5025)
        self.sleeve.release('c',pnl=800,at=10,terminal_hash='terminal',native_verified=True)
        self.assertEqual(self.sleeve.reconcile()['realized'],800)
        self.assertEqual(self.sleeve.sizing_basis(500)['target'],5040)
        # Native marks never have a sleeve write or sizing method.
        self.assertNotIn('unrealized',self.sleeve.sizing_basis(500))

    def test_nonpositive_equity_has_no_entry(self):
        self.sleeve.reserve('loss',strategy='current',amount=100000,at=0)
        self.sleeve.release('loss',pnl=-100000,at=1,terminal_hash='loss',native_verified=True)
        self.assertEqual(self.sleeve.sizing_basis(500)['allocatable_target'],0)
        with self.assertRaisesRegex(ValueError,'capital_exhausted'):
            self.sleeve.reserve('new',strategy='survivor',amount=1,at=2)

    def test_current_stop_profit_and_proportional_trails(self):
        self.assertEqual(self.pump_exit(-800,0),'risk_stop')
        self.assertIsNone(self.pump_exit(-799,0))
        # 1.5x price with 14% giveback is 1.29x, independent of gain points.
        self.assertEqual(self.pump_exit(2900,5000),'trailing_momentum_exit')
        self.assertIsNone(self.pump_exit(2901,5000))
        self.assertEqual(self.pons_exit(3200,5000)['action'],'full_exit')
        self.assertEqual(self.pons_exit(3201,5000)['action'],'hold')
        self.assertEqual(EXIT_POLICY['first_profit_sell_bps'],2500)
        self.assertEqual((POLICY.first_profit_bps,EXIT_POLICY['first_profit_bps']),(1500,1800))

    def test_pons_immediate_ratio_boundary(self):
        for sell,expected in ((119,'hold'),(120,'full_exit')):
            action=runner_action(tokens=100,partial_taken=True,after_cost_return_bps=2000,high_water_return_bps=2000,
                seconds_since_high=0,new_buyer_growth=1,buy_quote=100,sell_quote=sell)
            self.assertEqual(action['action'],expected)

    def test_two_confirmation_deterioration_survives(self):
        self.assertIsNone(self.pump_exit(100,100,demand_deterioration_streak=1))
        for streak,expected in ((1,'hold'),(2,'full_exit')):
            action=runner_action(tokens=100,partial_taken=True,after_cost_return_bps=2000,high_water_return_bps=2000,
                seconds_since_high=120,new_buyer_growth=0,buy_quote=100,sell_quote=100,soft_deterioration_streak=streak)
            self.assertEqual(action['action'],expected)

    def test_current_outcomes_never_tombstone_survivor_observation(self):
        for outcome in ('rejected','no_fill','cancelled','timeout','closed'):
            self.sleeve.opportunity('mint',identity='current:'+outcome,regime='current',status=outcome,at=1,decision={'reason':outcome})
            row=self.sleeve.observe('mint',strategy='survivor',at=2,state='qualified',evidence={'fresh':True},regime={'at':2})
            self.assertEqual(row['state'],'qualified')
        self.sleeve.reserve('current',strategy='current',amount=5000,at=3,asset='mint')
        row=self.sleeve.observe('mint',strategy='survivor',at=4,state='qualified',evidence={'fresh':True},regime={'at':4})
        with self.assertRaisesRegex(ValueError,'same_asset_exposure'):
            self.sleeve.reserve('survivor',strategy='survivor',amount=5000,at=4,candidate='mint',generation=row['generation'],regime={'at':4})
        self.sleeve.release('current',pnl=0,at=5,terminal_hash='cancelled',native_verified=True,cancelled=True)
        self.sleeve.reserve('survivor',strategy='survivor',amount=5000,at=5,candidate='mint',generation=row['generation'],regime={'at':4})

    def test_all_four_tail_examples_and_safety_precedence(self):
        from meme_machine.lanes.pump.pumpswap_survivor import POLICY as ps
        from meme_machine.lanes.pons.pons_postgrad_survivor import risk_policy
        for peak,threshold in ((10000,6000),(40000,24000),(90000,54000),(240000,144000),(490000,294000)):
            with self.subTest(peak=peak):
                self.assertEqual(self.pump_exit(threshold,peak),'tail_gain_giveback_exit')
                self.assertIsNone(self.pump_exit(threshold+1,peak))
                self.assertEqual(self.pons_exit(threshold,peak)['action'],'full_exit')
                self.assertEqual(self.pons_exit(threshold+1,peak)['action'],'hold')
                for policy in (ps['exits'],risk_policy()):
                    state=dict(opened_at=0,original_quantity=100,remaining_quantity=75,realization_taken=True,high_water_bps=peak)
                    _,a=survivor_mark(state,dict(id='mark',at=10,after_cost_return_bps=threshold),policy)
                    self.assertEqual(a['reason'],'tail_gain_giveback')
                    _,a=survivor_mark(state,dict(id='mark',at=10,after_cost_return_bps=threshold,creator_distribution=True),policy)
                    self.assertEqual(a['reason'],'creator_distribution')

    def test_bridge_exact_age_and_all_required_evidence(self):
        original=dict(opened_at=100,high_water_bps=5000,realization_taken=True)
        bridged,expired=bridge_state(original,FACTS,now=1000,ordinary_expired=True)
        self.assertFalse(expired);self.assertEqual(bridged['bridge_deadline'],129700)
        self.assertEqual(bridged['opened_at'],100)
        for gate in BRIDGE_GATES:
            self.assertTrue(bridge_state(original,dict(FACTS,**{gate:False}),now=1000,ordinary_expired=True)[1])
        for now,expected in ((129699,False),(129700,True)):
            self.assertEqual(bridge_state(bridged,FACTS,now=now,ordinary_expired=True)[1],expected)
        self.assertTrue(bridge_state(dict(original,high_water_bps=4999),FACTS,now=1000,ordinary_expired=True)[1])

    def test_scale_time_price_and_capital_boundaries(self):
        s=dict(opened_at=0,original_basis=5000,high_water_bps=10000,first_tail_crossed_at=100,realization_taken=True)
        facts=dict(FACTS,fresh_strategy_requalified=True,fresh_execution_requalified=True,after_cost_return_bps=7000)
        self.assertEqual(scale_budget(s,facts,now=999,sleeve=self.sleeve,execution_allowance=10000),0)
        self.assertEqual(scale_budget(s,facts,now=1000,sleeve=self.sleeve,execution_allowance=10000),2500)
        self.assertEqual(scale_budget(s,dict(facts,after_cost_return_bps=6999),now=1000,sleeve=self.sleeve,execution_allowance=10000),0)
        self.assertEqual(scale_budget(s,facts,now=1000,sleeve=self.sleeve,execution_allowance=900),900)
        self.assertEqual(scale_budget(dict(s,scale_committed=True),facts,now=1000,sleeve=self.sleeve,execution_allowance=10000),0)
        self.assertEqual(reference_return(18000,900,5000,500),10000)

    def test_native_scale_replay_duplicate_and_interrupted_ack(self):
        book=PaperBook(Path(self.temp.name)/'paper.sqlite',run_id='offline',lane='current',policy_hash='a',initial=100000)
        self.addCleanup(book.close);identity='offline:winner'
        self.sleeve.reserve(identity,strategy='current',amount=5000,at=1)
        book.reserve(identity,5000,1,{})
        book.transition(identity,'filled',2,amount=5000,tokens=500,evidence={})
        native_sync(book,self.sleeve,identity)
        book.transition(identity,'partial_harvest',3,amount=2000,tokens=125,evidence={})
        native_sync(book,self.sleeve,identity)
        before=book._load(identity)
        request=identity+':scale:1'
        self.sleeve.reserve_scale(identity,amount=2500,original_basis=5000,at=4,request=request)
        book.transition(identity,'scale_add',4,amount=2500,tokens=125,evidence={'request':request})
        # Simulated crash before sleeve acknowledgement; replay is authoritative.
        native_sync(book,self.sleeve,identity)
        result=book._load(identity)
        self.assertEqual((result['basis'],result['tokens'],result['realized']),(6250,500,750))
        events=book.replay()['events']
        book.transition(identity,'scale_add',4,amount=2500,tokens=125,evidence={'request':request})
        self.assertEqual(book.replay()['events'],events)
        self.assertTrue(self.sleeve.get(identity)['scale_committed'])
        with self.assertRaisesRegex(ValueError,'scale_lifecycle_state'):
            self.sleeve.reserve_scale(identity,amount=1,original_basis=5000,at=4,request='second')
        with self.assertRaisesRegex(ValueError,'scale_duplicate_conflict'):
            book.transition(identity,'scale_add',4,amount=2501,tokens=125,evidence={'request':request})
        self.assertEqual(book._load(identity),result)

    def test_failed_incremental_reservation_preserves_original(self):
        self.sleeve.reserve('winner',strategy='current',amount=5000,at=1)
        self.sleeve.acknowledge_native('winner',basis=3750,pnl=500,at=2,native_hash='partial',native_verified=True)
        before=self.sleeve.reconcile()
        self.sleeve.reserve_scale('winner',amount=2500,original_basis=5000,at=3,request='scale:1')
        self.sleeve.recover_scale('winner',request='scale:1',committed=False,native_verified=True)
        after=self.sleeve.reconcile()
        self.assertEqual({k:before[k] for k in ('available','reserved','realized')},{k:after[k] for k in ('available','reserved','realized')})

    def test_current_pump_bridge_scale_and_controller_replay(self):
        from meme_machine.lanes.pump.pump_acceleration_strategy import STRATEGY_ID,policy_hash
        book=PumpBook(Path(self.temp.name)/'pump.sqlite',run_id='offline',lane=STRATEGY_ID,policy_hash=policy_hash(),initial=100000)
        self.addCleanup(book.close)
        life=PumpAccelerationPaperLifecycle(book=book,lifecycle_id='offline:pump')
        life.reserve(qualification(),5000,1);life.fill(500,5000,2,'pump.fun')
        life.mark(7500,3,80,evidence={'continuation':FACTS});life.harvest(125,1875,4)
        life.mark(7500,5,80,evidence={'continuation':FACTS})
        life.mark(7500,1802,80,evidence={'continuation':FACTS})
        self.assertTrue(life.position.bridged)
        before=asdict(life.position)
        life.add(2500,125,1803,request='offline:pump:scale:1',evidence={})
        recovered=PumpAccelerationPaperLifecycle.restore(book,'offline:pump')
        self.assertEqual(asdict(recovered.position),asdict(life.position))
        for field in ('opened_at','peak_return_bps','demand_deterioration_streak','bridged_at','bridge_deadline','first_tail_crossed_at'):
            self.assertEqual(before[field],asdict(recovered.position)[field])

    def test_meteora_three_verified_segments_and_entry_unchanged(self):
        from meme_machine.lanes.meteora import runner
        policy=runner.load_policy()
        self.assertEqual(policy['exit']['economic_collapse_confirmation_segments'],3)
        for streak,expected in ((2,[]),(3,['fee_density_collapse'])):
            self.assertEqual(runner._eligible_exit_reasons(['fee_density_collapse'],elapsed_seconds=14400,
                collapse_streaks={'fee_density_collapse':streak,'volume_collapse':0},policy=policy),expected)
        self.assertEqual(runner._eligible_exit_reasons(['fee_density_collapse'],elapsed_seconds=14399,
            collapse_streaks={'fee_density_collapse':3,'volume_collapse':0},policy=policy),[])

    def test_meteora_adverse_flow_strict_and_conjunctive_boundary(self):
        from meme_machine.lanes.meteora import runner
        p=runner.load_policy();position={'lower':90,'upper':110,'entry_active':100}
        for balance,drift,expected in ((.1799,.8201,True),(.18,.8201,False),(.1799,.82,False),(.19,.9,False),(.1,.8,False)):
            flow=dict(touch_swaps=2,two_way_balance=balance,drift_ratio=drift,
                volume_rate_sol_lamports_per_second=1,fee_density=1)
            with patch.object(runner,'_range_flow_features',return_value=flow),patch.object(runner,'_mark',return_value={'non_sol_inventory_fraction_of_initial_capital':.5}),patch.object(runner,'_fee_uplift',return_value={}):
                reasons,_,_,_=runner._segment_exit(position,{},None,{'active':100},flow,p)
            self.assertEqual('one_way_flow' in reasons,expected)
        self.assertEqual((p['qualification']['min_two_way_balance'],p['qualification']['max_drift_ratio']),(.2,.8))

    def test_current_pons_bridge_scale_same_lifecycle_native_replay(self):
        from meme_machine.lanes.pons.evidence import Store
        from meme_machine.lanes.pons.pons_selective_ledger import SelectivePaper,STRATEGY_NAMESPACE
        from meme_machine.lanes.pons.pons_selective_continuation import POLICY_HASH
        from meme_machine.lanes.pons.pons_selective_recovery import LifecycleState
        from meme_machine.lanes.pons.pons_selective_paper import _bridge_action
        from tests.lanes.pons.test_pons_partial_accounting import PartialAccountingTests
        fixture=PartialAccountingTests();store=Store(str(Path(self.temp.name)/'pons.sqlite'))
        self.addCleanup(store.close)
        paper=SelectivePaper(store,STRATEGY_NAMESPACE,100000,delay=1,natural_policy_hash=POLICY_HASH)
        identity='pons:winner'
        decision=dict(asof=100,market='m',authority='frozen_policy_paper',qualification='qualified',policy_hash=POLICY_HASH,strategy_namespace=STRATEGY_NAMESPACE,shared_allocator=False)
        paper.reserve(identity,market='m',amount=5000,gas_budget=10,now=100,features=decision)
        evaluation=dict(token='token',curve='curve',source_transaction='tx',candidate={'curve':'curve','token':'token','auth':{'valid':True},'record':{}},
            vector={'current_threshold_pass':True,'policy_hash':POLICY_HASH,'trajectory':{'graduation_eta_seconds':100},'demand':{'largest_buyer_flow_bps':100}},market_events=[])
        state=LifecycleState.create(store,identity,evaluation,100000,21000,opened_at=101,last_block=1)
        paper.controller_context=state.checkpoint
        p=paper.advance(identity,now=101,action='entry',quote=fixture.quote(101,'buy',5000,1000))
        state.partial_taken=True;state.high_water=10000;state.first_tail_crossed_at=102
        paper.advance(identity,now=102,action='exit_intent',exit_tokens=250)
        p=paper.advance(identity,now=103,action='exit',quote=fixture.quote(103,'sell',250,2000))
        a=_bridge_action(state,FACTS,{'action':'hold'},p,now=1100)
        self.assertEqual(a['action'],'hold');self.assertTrue(state.bridged)
        p=paper.advance(identity,now=1100,action='mark',quote=fixture.quote(1100,'sell',750,7500))
        before=dict(p['controller_state'])
        p=paper.advance(identity,now=1101,action='scale_add',quote=fixture.quote(1101,'buy',2000,200),cancel_reason='pons:winner:scale:1')
        restored=LifecycleState.restore(paper,identity)
        self.assertTrue(restored.scale_committed);self.assertEqual(restored.opened_at,101)
        self.assertTrue(restored.partial_taken);self.assertTrue(restored.bridged)
        self.assertEqual(restored.first_tail_crossed_at,102)
        for field in ('opened_at','high_water','high_at','bridged_at','bridge_deadline','pregrad_soft_deterioration_streak','runner_soft_deterioration_streak','pending_action'):
            self.assertEqual(p['controller_state'][field],before[field])
        self.assertTrue(paper.accounting(identity)['replay_verified'])
        count=p['version'];again=paper.advance(identity,now=1101,action='scale_add',quote=fixture.quote(1101,'buy',2000,200),cancel_reason='pons:winner:scale:1')
        self.assertEqual(again['version'],count)
