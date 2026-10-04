"""Offline mature-winner qualification; initial entry stays a separate authority."""
import copy
import unittest
from meme_machine.lanes.pons.pons_selective_continuation import (
    ongoing_scale_requalification, post_graduation_vector, ENTRY_THRESHOLDS)


class OngoingScaleTests(unittest.TestCase):
    def fixture(self,phase='pregraduation'):
        self.position=dict(status='open',opened_at=100,original_basis=5000,scale_request=None)
        self.controller=dict(opened_at=100,partial_taken=True,first_tail_crossed_at=1000,
            high_water=10000,scale_committed=False,pending_action=None)
        quality=dict(independent_groups=5,new_independent_groups_15s=1,buy_sell_ratio_bps=20000,
            current_net_quote=1000,net_flow_accelerating=True,largest_buyer_flow_bps=2000,
            top3_buyer_flow_bps=6000,creator_sell_quote_15s=0)
        self.evidence=dict(original_demand_reference={'independent_groups':5},phase=phase,window_seconds=900,acquisition_started_at=1999,
            block_hash='authenticated-head',authenticated=True,originally_qualified=True,
            no_exit_condition=True,structural_safe=True,creator_safe=True,exit_liquidity=True,
            after_cost_return_bps=9000,entry_largest=3000,
            trajectory=dict(complete=True,progress_15s_bps=300,accelerating=True,graduation_eta_seconds=50),
            horizon=dict(independent_groups=5,buy_quote=2000,sell_quote=1000,net_quote=1000,
                largest_buyer_flow_bps=2000,top3_buyer_flow_bps=6000),demand=quality)
        if phase=='postgraduation':
            self.evidence['demand']=dict(buy_quote=2000,sell_quote=1000,net_quote=1000,
                new_independent_buyers=5,largest_buyer_flow_bps=2000,top3_buyer_flow_bps=6000,
                preholder_sell_quote=0,price_retention_bps=9500)
        return self.evidence

    def evaluate(self):
        return ongoing_scale_requalification(position=self.position,controller=self.controller,
            evidence=self.evidence,now=2000)

    def test_mature_pregraduation_winner_has_scale_authority_only(self):
        self.fixture();result=self.evaluate()
        self.assertTrue(result['scale_qualified'],result)
        self.assertFalse(result['qualification_authority'])
        self.assertFalse(result['initial_entry_authority'])
        self.assertGreater(2000-self.position['opened_at'],ENTRY_THRESHOLDS['max_token_age_seconds'])

    def test_carried_winner_is_independent_of_expired_graduation_window(self):
        self.fixture('postgraduation');self.assertTrue(self.evaluate()['scale_qualified'])
        d=self.evidence['demand']
        entry=post_graduation_vector(observed_seconds=1000,price_retention_bps=9500,
            new_independent_buyers=5,buy_quote=2000,sell_quote=1000,net_quote=1000,
            preholder_sell_quote=0,largest_buyer_flow_bps_before=3000,largest_buyer_flow_bps_now=2000)
        self.assertIn('post_grad_window',entry['all_rejections'])
        self.assertFalse(entry['continuation_pass'])

    def test_failures_block_each_phase_independently(self):
        changes=[('controller','first_tail_crossed_at',1101),
            ('controller','partial_taken',False),('controller','pending_action',{'reason':'exit'}),
            ('position','status','exit_pending'),('position','scale_request','committed'),
            ('evidence','outstanding_scale_reservation',True),
            ('evidence','acquisition_started_at',1994),('evidence','authenticated',False),
            ('evidence','structural_safe',False),('evidence','exit_liquidity',False),
            ('evidence','creator_safe',False),('evidence','no_exit_condition',False),
            ('evidence','after_cost_return_bps',6999),('evidence','originally_qualified',False)]
        for phase in ('pregraduation','postgraduation'):
            for obj,key,value in changes:
                with self.subTest(phase=phase,gate=key):
                    self.fixture(phase);getattr(self,obj)[key]=value
                    self.assertFalse(self.evaluate()['scale_qualified'])
            for key,value in [('independent_groups',0),('net_quote',0),('largest_buyer_flow_bps',9000),('top3_buyer_flow_bps',9000)]:
                with self.subTest(phase=phase,horizon=key):
                    self.fixture(phase);self.evidence['horizon'][key]=value
                    self.assertFalse(self.evaluate()['scale_qualified'])
            self.fixture(phase);self.evidence['demand']={}
            self.assertFalse(self.evaluate()['scale_qualified'])

    def test_authenticated_original_breadth_still_detects_deterioration(self):
        self.fixture();self.evidence['original_demand_reference']={'independent_groups':20}
        result=self.evaluate()
        self.assertFalse(result['scale_qualified'])
        self.assertIn('fill_buyer_breadth_decay',result['all_rejections'])

    def test_original_vector_cannot_authorize_add(self):
        self.fixture();self.evidence={'originally_qualified':True,'original_vector':copy.deepcopy(self.evidence)}
        self.assertFalse(self.evaluate()['scale_qualified'])
        self.fixture();self.position['status']='reserved'
        self.assertFalse(self.evaluate()['scale_qualified'])

class ScaleIntegrationTests(unittest.TestCase):
    fixture=OngoingScaleTests.fixture
    def setUp(self):
        import tempfile
        from pathlib import Path
        from meme_machine.runtime.sleeve_reservations import SleeveReservations
        from meme_machine.lanes.pons.evidence import Store
        from meme_machine.lanes.pons.pons_selective_ledger import SelectivePaper,STRATEGY_NAMESPACE
        from meme_machine.lanes.pons.pons_selective_continuation import POLICY_HASH
        from meme_machine.lanes.pons.pons_selective_recovery import LifecycleState
        from tests.lanes.pons.test_pons_partial_accounting import PartialAccountingTests
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/'native.sqlite');self.addCleanup(self.store.close)
        self.native_quote=PartialAccountingTests().quote
        self.identity='pons:winner';self.sleeve_path=Path(self.temp.name)/'sleeve.sqlite'
        self.sleeve_args=dict(lane='pons',capital=100000,policies={'current':POLICY_HASH,'survivor':'offline-survivor'},cohort='offline')
        self.sleeve=SleeveReservations(self.sleeve_path,**self.sleeve_args)
        self.sleeve.reserve(self.identity,strategy='current',amount=5002,at=100,asset='token')
        self.paper=SelectivePaper(self.store,STRATEGY_NAMESPACE,100000,delay=1,natural_policy_hash=POLICY_HASH)
        self.paper.reserve(self.identity,market='m',amount=5000,gas_budget=2,now=100,
            features=PartialAccountingTests().features(100))
        self.candidate=dict(token='token',curve='curve',auth={'valid':True},record={'deployer':'creator','graduationThreshold':10**18})
        evaluation=dict(token='token',curve='curve',source_transaction='tx',candidate=self.candidate,
            vector={'current_threshold_pass':True,'policy_hash':POLICY_HASH,
                'trajectory':{'graduation_eta_seconds':100},'demand':{'largest_buyer_flow_bps':3000}},market_events=[])
        self.state=LifecycleState.create(self.store,self.identity,evaluation,100000,1,opened_at=101,last_block=1)
        self.paper.controller_context=self.state.checkpoint
        self.paper.advance(self.identity,now=101,action='entry',quote=self.native_quote(101,'buy',5000,1000))
        self.state.partial_taken=True;self.state.high_water=10000;self.state.first_tail_crossed_at=102
        self.paper.advance(self.identity,now=102,action='exit_intent',exit_tokens=250)
        p=self.paper.advance(self.identity,now=103,action='exit',quote=self.native_quote(103,'sell',250,2000))
        self.sleeve.acknowledge_native(self.identity,basis=p['remaining_cost'],pnl=p['realized_pnl'],
            at=103,native_hash='replay-verified',native_verified=True)
        self.before=self.paper._get(self.identity)

    def attempt(self,*,bad_demand=False,capacity_failure=False,final_demand_failure=False,postgraduation=False):
        from unittest.mock import patch
        from types import SimpleNamespace
        from meme_machine.lanes.pons import pons_selective_paper as module
        from meme_machine.runtime.sleeve_reservations import SleeveReservations
        self.fixture('postgraduation' if postgraduation else 'pregraduation');evidence=copy.deepcopy(self.evidence)
        if postgraduation:
            from meme_machine.lanes.pons.protocols import PoolKey
            self.state.transition={'proof_hash':'authenticated-transition'}
            self.state.v4_key=PoolKey('0x'+'1'*40,'0x'+'2'*40,3000,60,'0x'+'3'*40)
        evidence['acquisition_started_at']=2000
        evidence['demand']['current_net_quote']=100000
        if postgraduation:evidence['demand']['net_quote']=100000
        if bad_demand:evidence['demand']['independent_groups']=0
        mark=self.native_quote(2000,'sell',self.before['tokens'],self.before['remaining_cost']*2)
        meta=dict(block_hash='h2000')
        def quote(*args,**kwargs):
            amount=args[3]
            return self.native_quote(2000,'buy',amount,max(1,amount//10)),{'state':{}},None
        def v4quote(*args,**kwargs):
            amount=args[3];side=kwargs.get('side','sell')
            return self.native_quote(2000,side,amount,max(1,amount//10) if side=='buy' else amount*10),{},None
        reads=[0]
        def current(*args):
            reads[0]+=1
            latest=copy.deepcopy(evidence)
            if final_demand_failure and reads[0]>1:latest['demand']={}
            return latest,self.paper._get(self.identity),mark,meta
        def capacity(*args):return SimpleNamespace(final_size=0 if capacity_failure else args[1])
        with patch.object(module.time,'time',return_value=2000),patch.object(module,'_stop_sleep'), \
                patch('meme_machine.runtime.directional_sleeve.open_sleeve',
                    side_effect=lambda *a:SleeveReservations(self.sleeve_path,**self.sleeve_args)), \
                patch.object(module,'_ongoing_scale_evidence',side_effect=current), \
                patch.object(module,'_gas_quote',return_value=(2,{})), \
                patch.object(module,'_wait_curve_quote',side_effect=quote),patch.object(module,'_v4_quote',side_effect=v4quote), \
                patch.object(module,'_entry_capacity',side_effect=capacity), \
                patch.object(module,'_fresh_fill_full_exit_check'),patch.object(module,'_validate_final_entry'):
            return module._attempt_current_scale(None,None,self.paper,self.identity,self.state,
                self.candidate,1,self.store,{},self.paper._get(self.identity),demand={})

    def test_actual_add_is_exactly_once_and_preserves_native_identity(self):
        from meme_machine.lanes.pons.pons_selective_recovery import LifecycleState
        result=self.attempt();self.assertIsNotNone(result)
        self.assertEqual(result['id'],self.identity)
        self.assertEqual(result['controller_state']['opened_at'],101)
        self.assertEqual(result['controller_state']['high_water'],10000)
        self.assertEqual(result['controller_state']['first_tail_crossed_at'],102)
        from meme_machine.lanes.pons.evidence import Store
        from meme_machine.lanes.pons.pons_selective_ledger import SelectivePaper,STRATEGY_NAMESPACE
        from meme_machine.lanes.pons.pons_selective_continuation import POLICY_HASH
        path=self.store.path if hasattr(self.store,'path') else __import__('pathlib').Path(self.temp.name)/'native.sqlite'
        self.store.close();self.store=Store(path);self.addCleanup(self.store.close)
        self.paper=SelectivePaper(self.store,STRATEGY_NAMESPACE,100000,delay=1,natural_policy_hash=POLICY_HASH)
        self.state=LifecycleState.restore(self.paper,self.identity)
        self.paper.controller_context=self.state.checkpoint
        version=result['version'];self.assertIsNone(self.attempt())
        self.assertEqual(self.paper._get(self.identity)['version'],version)
        held=self.sleeve.get(self.identity)
        self.assertTrue(held['scale_committed'])
        self.assertEqual(held['scale_reservation']['status'],'committed')
        self.assertEqual(held['amount'],5002+held['scale_reservation']['amount'])
        self.assertTrue(self.paper.accounting(self.identity)['replay_verified'])
        self.sleeve.close()

    def test_carried_position_executes_add_without_new_lifecycle(self):
        result=self.attempt(postgraduation=True)
        self.assertIsNotNone(result)
        self.assertEqual(result['id'],self.identity)
        self.assertEqual(result['controller_state']['opened_at'],101)
        self.assertTrue(result['controller_state']['transition'])
        self.assertTrue(self.sleeve.get(self.identity)['scale_committed'])
        self.sleeve.close()

    def test_failed_fresh_requalification_and_capacity_make_no_reservation(self):
        self.assertIsNone(self.attempt(bad_demand=True))
        self.assertIsNone(self.attempt(capacity_failure=True))
        self.assertIsNone(self.attempt(final_demand_failure=True))
        self.assertEqual(self.paper._get(self.identity),self.before)
        self.assertIsNone(self.sleeve.get(self.identity).get('scale_reservation'))
        self.sleeve.close()

    def test_rolling_reader_authenticates_both_mature_phases(self):
        from unittest.mock import patch,Mock
        from dataclasses import asdict
        from meme_machine.lanes.pons import pons_selective_paper as module
        from meme_machine.lanes.pons.protocols import PoolKey
        from tests.lanes.pons.test_pons_selective_continuation import state as curve_state
        from meme_machine.lanes.pons.pons_selective_continuation import ongoing_scale_requalification
        mark=self.native_quote(2000,'sell',self.before['tokens'],self.before['remaining_cost']*2)
        meta=dict(block=2000,block_hash='h2000',event_at=2000,state=asdict(curve_state(timestamp=2000)))
        events=[dict(side='buy',quote=1000,group=f'buyer{i}',event_at=1990,
            price_index=100+i) for i in range(5)]
        events.append(dict(side='buy',quote=1000,group='olderbuyer',event_at=1150,price_index=100))
        events.append(dict(side='buy',quote=10**9,group='creator',event_at=1995,price_index=100))
        self.fixture();trajectory=self.evidence['trajectory'];demand=self.evidence['demand']
        for phase in ('pregraduation','postgraduation'):
            with self.subTest(phase=phase):
                if phase=='postgraduation':
                    self.state.transition={'proof_hash':'authenticated-transition'}
                    self.state.v4_key=PoolKey('0x'+'1'*40,'0x'+'2'*40,3000,60,'0x'+'3'*40)
                    self.state.graduation_at=1000
                rpc=Mock();rpc.call.return_value='0x0'
                with patch.object(module.time,'time',return_value=2000), \
                        patch.object(module,'_curve_quote',return_value=(mark,meta,None)), \
                        patch.object(module,'_v4_quote',return_value=(mark,meta,None)), \
                        patch.object(module,'_curve_logs',return_value=(events,[])) as logs, \
                        patch.object(module,'_refresh_curve_signal',return_value=(trajectory,demand,[])), \
                        patch.object(module,'evidence_rpc',return_value=rpc), \
                        patch.object(module,'_header_search',return_value={'number':'0x44c'}) as search, \
                        patch.object(module,'collect_v4_activity',return_value={'swaps':events}) as activity:
                    evidence,position,_,_=module._ongoing_scale_evidence(None,rpc,self.paper,self.identity,
                        self.state,self.candidate,1,self.store,self.sleeve)
                    result=ongoing_scale_requalification(position=position,controller=vars(self.state),
                        evidence=evidence,now=2000)
                    self.assertTrue(result['scale_qualified'],result)
                    self.assertEqual(evidence['horizon']['independent_groups'],6)
                    self.assertEqual(evidence['horizon']['net_quote'],6000)
                    self.assertEqual(evidence['window_ending_at'],2000)
                    if phase=='pregraduation':self.assertEqual(logs.call_args.kwargs['seconds'],900)
                    else:
                        self.assertEqual(search.call_args.args[3],1100)
                        self.assertEqual(activity.call_args.kwargs['start_block'],1100)
        self.sleeve.close()

    def test_mature_new_entry_still_fails_original_age_gate(self):
        from tests.lanes.pons.test_pons_selective_continuation import vector
        result=vector(launch_at=-1000)
        self.assertFalse(result['current_threshold_pass'])
        self.assertIn('token_age',result['all_rejections'])
        self.fixture()
        features=ongoing_scale_requalification(position=self.position,controller=self.controller,
            evidence=self.evidence,now=2000)
        self.assertTrue(features['scale_qualified'])
        from meme_machine.lanes.pons import BoundaryError
        with self.assertRaisesRegex(BoundaryError,'selective_policy_authority_missing'):
            self.paper.reserve('forbidden-new-entry',market='m',amount=100,gas_budget=2,now=2000,features=features)
        self.assertEqual(len(self.paper.positions()),1)
        self.sleeve.close()

if __name__=='__main__':unittest.main()

