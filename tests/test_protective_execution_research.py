"""Native funded losses and bounded, non-authoritative exit research. Offline."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
import json
import os
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from meme_machine.runtime import opportunity_telemetry as telemetry, learning
from tests import test_pump_pons_capital_preparation as capital_fixtures
from tests import test_shared_portfolio_epoch as epoch_fixtures
shared_risk_candidate=epoch_fixtures.shared_risk_candidate


def quote(at, net, quantity=75):
    return dict(validated=True, native_identity='original-owner', quantity=quantity,
        currency='USD', net_proceeds=str(net), observed_at=at, available_at=at,
        valid_until=at+5, source_generation='canonical-generation', source_hash='quote:'+str(at))


def receipt():
    return dict(regime='pons_current', reason='demand_failure', at=100,
        policy_hash='original-policy', native_identity='original-owner', quantity=75,
        remaining_basis='37.5', currency='USD', source_generation='canonical-generation',
        executable_quote=quote(100,75),
        decision_evidence=dict(complete=True, source_hash='original-authenticated-synthetic-input',
            available_at=100, creator_safe=True, structure_valid=True, liquidity_valid=True,
            hard_exits_clear=True, price_retention_valid=True, independent_buyers=20, new_buyers=3),
        followup_coverage=dict(authenticated=True, native_identity='original-owner',
            source_hash='synthetic-canonical-interval', source_generation='canonical-generation',from_at=100,through_at=400))


def sample(at,net,*,adverse=False,reason=None):
    return dict(id='observation:'+str(at),at=at,available_at=at,evidence_complete=True,
        source_hash='canonical:'+str(at),source_generation='canonical-generation',
        native_identity='original-owner',executable_quote=quote(at,net),
        native_action='full_exit' if reason or adverse else 'hold',native_reason=reason or ('demand_failure' if adverse else None),
        distribution_adverse=adverse)


class ShadowTests(unittest.TestCase):
    def run_shadow(self,r=None,rows=None,now=400):
        return telemetry.shadow_demand_exit(r or receipt(),rows or [],horizon_seconds=300,now=now)

    def test_synthetic_winner_and_collapse_keep_real_equity_and_baseline_untouched(self):
        original=receipt();before=deepcopy(original)
        winner=self.run_shadow(original,[sample(105,80),sample(110,375),sample(115,375),sample(120,240,reason='tail_gain_giveback_exit')])
        self.assertEqual(winner['hypothetical_net_proceeds_difference'],'165')
        loser=self.run_shadow(original,[sample(105,74),sample(110,74),sample(115,70),sample(120,7.5,reason='risk')])
        self.assertEqual(loser['hypothetical_net_proceeds_difference'],'-135/2')
        self.assertEqual(original,before)
        self.assertFalse(winner['order_authority']);self.assertFalse(winner['portfolio_equity_authority'])
        self.assertIsNone(winner['incremental_monitoring_cost'])

    def test_no_lookahead_safety_overrides_and_native_policy_specific_reason(self):
        r=receipt();r['decision_evidence']['creator_safe']=False
        self.assertEqual(self.run_shadow(r,[sample(120,375)])['status'],'BASELINE_RETAINED')
        for regime,reason in (('pons_current','risk'),('pump_current','graduation_without_continuation'),
                ('pump_survivor','creator_distribution'),('pons_survivor','hard_stop')):
            r=receipt();r.update(regime=regime,reason=reason)
            self.assertEqual(self.run_shadow(r,[sample(120,375)])['status'],'BASELINE_RETAINED')
        r=receipt();r['decision_evidence']['available_at']=101
        self.assertEqual(self.run_shadow(r,[sample(120,375)])['status'],'INCONCLUSIVE')

    def test_original_exact_quote_and_complete_followup_are_required(self):
        for mutation in ('coverage','generation','quantity','stale','price_only','missing'):
            r=receipt();rows=[sample(120,375,reason='runner_trailing_stop')]
            if mutation=='coverage':r['followup_coverage']['through_at']=399
            elif mutation=='generation':rows[0]['source_generation']='reorganization'
            elif mutation=='quantity':rows[0]['executable_quote']['quantity']=74
            elif mutation=='stale':rows[0]['executable_quote']['valid_until']=119
            elif mutation=='price_only':rows[0].pop('executable_quote');rows[0]['price']='10'
            elif mutation=='missing':r.pop('executable_quote')
            result=self.run_shadow(r,rows)
            self.assertEqual(result['status'],'INCONCLUSIVE',mutation)
            self.assertIsNone(result['hypothetical_net_proceeds_difference'])

    def test_distinct_confirmations_future_exclusion_and_conflicts(self):
        first=sample(103,80,adverse=True)
        result=self.run_shadow(rows=[first,deepcopy(first),sample(401,10000,reason='risk')])
        self.assertEqual(result['status'],'INCONCLUSIVE')
        result=self.run_shadow(rows=[first,sample(106,70,adverse=True)])
        self.assertEqual(result['hypothetical_exit_at'],106)
        self.assertEqual(result['hypothetical_net_proceeds_difference'],'-5')
        conflict=deepcopy(first);conflict['distribution_adverse']=False
        self.assertEqual(self.run_shadow(rows=[first,conflict])['status'],'INCONCLUSIVE')
        self.assertEqual(self.run_shadow(rows=[first],now=399)['status'],'INCONCLUSIVE')
        continuous=[sample(at,80) for at in range(105,401,5)]
        self.assertEqual(self.run_shadow(rows=continuous)['status'],'UNRESOLVED_HOLD')

    def test_complete_market_history_cannot_replace_missing_protective_observations(self):
        self.assertEqual(self.run_shadow(rows=[sample(105,80),sample(120,240,reason='tail_gain_giveback_exit')])['status'],
            'INCONCLUSIVE')
        r=receipt();r.update(regime='pons_survivor',reason='persistent_demand_deterioration')
        self.assertEqual(self.run_shadow(r,[sample(104,80),sample(105,70,reason='hard_stop')])['status'],
            'INCONCLUSIVE')

    def test_shadow_quantity_change_requires_complete_partial_lineage(self):
        row=sample(103,80);row['native_action']='partial_exit'
        self.assertEqual(self.run_shadow(rows=[row])['status'],'INCONCLUSIVE')
        row=sample(103,80);row['native_action']='full_exit'
        self.assertEqual(self.run_shadow(rows=[row])['status'],'INCONCLUSIVE')

    def test_research_bounds_and_each_native_soft_policy_remain_independent(self):
        with self.assertRaisesRegex(ValueError,'exit_shadow_bound'):
            telemetry.shadow_demand_exit(receipt(),[],horizon_seconds=301,now=400)
        with self.assertRaisesRegex(ValueError,'exit_shadow_bound'):
            self.run_shadow(rows=[sample(103,80)]*513)
        r=receipt();r['oversized']='x'*telemetry.MAX_RECEIPT_BYTES
        with self.assertRaisesRegex(ValueError,'exit_shadow_byte_bound'):self.run_shadow(r)
        for regime,reason in (('pump_current','persistent_demand_deceleration'),
                ('pons_current','flow_reversal'),('pump_survivor','persistent_demand_deterioration'),
                ('pons_survivor','stale_thesis')):
            r=receipt();r.update(regime=regime,reason=reason)
            self.assertEqual(self.run_shadow(r,[sample(103,80),sample(105,75,reason='hard_stop')])['status'],
                'HYPOTHETICAL_COMPARISON')

    def test_learning_retains_original_risk_exit_and_execution_with_existing_bounds(self):
        db=sqlite3.connect(':memory:');self.addCleanup(db.close);db.execute('BEGIN')
        event=dict(action='mark',at=100,position=dict(id='original-owner',mark=75),
            identity=dict(policy_hash='original-policy'),evidence=dict(
                risk_state=dict(last_action=dict(action='full_exit',reason='persistent_demand_deterioration')),
                observation=dict(id='canonical',at=100,after_cost_return_bps=10000,
                    evidence_current=True,soft_deterioration=True),raw=dict(secret='discard')))
        execution=dict(action='settled',at=103,position=dict(id='original-owner'),
            evidence=dict(exit_reason='persistent_demand_deterioration',
                execution=dict(quantity=75,net_proceeds=75,gas=2,block_hash='canonical')))
        learning.lifecycle(db,'original-owner','pons_survivor',103,dict(id='original-owner',status='settled'),[event,execution])
        body=learning.get(db,'lifecycle:original-owner');facts=body['facts']
        self.assertEqual(facts['exit_observations'][0]['observation'],event['evidence']['observation'])
        self.assertEqual(facts['economic_actions'][0]['decision_and_execution_facts']['exit_reason'],execution['evidence']['exit_reason'])
        self.assertEqual(facts['economic_actions'][0]['decision_and_execution_facts']['execution'],execution['evidence']['execution'])
        self.assertNotIn('raw',facts['exit_observations'][0]);self.assertFalse(body['economic_authority'])
        more=[]
        for i in range(20):
            e=deepcopy(event);e['at']=100+i
            e['evidence']['risk_state']['last_action']['reason']='reason'+str(i)
            more.append(e)
        learning.lifecycle(db,'original-owner','pons_survivor',130,dict(id='original-owner',status='settled'),more)
        bounded=learning.get(db,'lifecycle:original-owner')['facts']
        self.assertEqual(len(bounded['exit_observations']),8)
        self.assertEqual(bounded['exit_observations'][0],facts['exit_observations'][0])


class FundedProtectionTests(unittest.TestCase):
    fixture=capital_fixtures.RuntimeIntegrationTests.fixture
    harness=epoch_fixtures.SharedEpochTests.harness

    def test_fundable_mixed_concurrency_uses_real_authority_and_no_count_veto(self):
        regimes=('pump_current','pump_survivor','pons_current','pons_survivor')
        rows=[]
        for count in (1,2,5,10,20):
            for size in ('50','25'):
                h=self.harness(policy=shared_risk_candidate())
                funded=0;denials=[]
                for i in range(count):
                    requests,result=h.allocate([(regimes[i%4],dict(requested='50',minimum_basis=size,
                        liquidity_capacity=size,execution_capacity=size))])
                    decision=result['decisions'][requests[0].request_id]
                    if decision['status']=='RESERVED':h.fill(requests[0]);funded+=1
                    else:denials.append(decision['reason'])
                h.restart();capital=h.check()['capital']
                self.assertTrue(capital['conservation']);self.assertLessEqual(Decimal(capital['deployed_basis']),750)
                if count==20:self.assertEqual(funded,15 if size=='50' else 20)
                rows.append(dict(requested_positions=count,execution_capacity_usd=size,
                    funded=funded,capital=capital,denials=denials,provider_capacity_proven=False))
        print('FUNDED_PROTECTIVE_CONCURRENCY',json.dumps(rows),flush=True)

    def test_operational_funding_stays_closed_without_full_protective_capacity(self):
        from meme_machine.operational.admission import available
        for mode in ('NORMAL','AUTONOMY'):
            reason=available(dict(runtime_admission=dict(mode=mode)),100,live=True)
            self.assertEqual(reason,'selected_regime_current_protection_not_ready')

    def survivor_loss(self,family,drop,delayed,*,missing=False):
        from meme_machine.lanes.pump.paper_accounting import PaperBook
        from meme_machine.runtime.directional_sleeve import open_sleeve,policies
        from meme_machine.runtime.directional_continuation import native_sync
        from meme_machine.runtime.survivor_commit import monitor,restore_risk
        root,a,now,plan=self.fixture(policy=shared_risk_candidate(),new_epoch=True)
        (root/family).mkdir(exist_ok=True)
        self.enterContext(patch.dict(os.environ,{'MM_DIRECTIONAL_SLEEVE_DB':str(root/family/'directional-sleeve.sqlite')}))
        strategy=next(s for s in policies(family) if 'survivor' in s)
        book=PaperBook(root/family/'native.sqlite',run_id='crash',lane=strategy,
            policy_hash=policies(family)[strategy],initial=1_000_000);self.addCleanup(lambda:book.close())
        sleeve=open_sleeve(family,1_000_000);self.addCleanup(sleeve.close)
        identity='crash:original'
        sleeve.reserve(identity,strategy=strategy,amount=50_000,at=now,asset=identity,
            funding_evidence=dict(qualified=True))
        book.reserve(identity,50_000,now,dict(qualified=True))
        book.transition(identity,'filled',now,amount=50_000,tokens=1000,evidence=dict(execution={'gas':0}))
        native_sync(book,sleeve,identity)
        if family=='pump':
            from meme_machine.lanes.pump.pumpswap_survivor import POLICY
            policy=POLICY['exits']
        else:
            from meme_machine.lanes.pons.pons_postgrad_survivor import risk_policy
            policy=risk_policy()
        observed=50_000*(100-drop)//100
        net=observed*90//100  # Synthetic loss of exit liquidity, after costs.
        if delayed:net=net*75//100  # Additional synthetic adverse movement.
        at=now+1+(3 if delayed else 0)
        execution=dict(quantity=1000,net_proceeds=net,acquired=at,market_time=at,gas=0)
        def validate(q,qty,clock):
            self.assertEqual(q['quantity'],qty);self.assertEqual(q['acquired'],clock)
        adapter=SimpleNamespace(now=lambda:at,exit_quote=lambda qty:None if missing else execution,validate_exit=validate)
        observation=dict(id='collapse',at=now+1,after_cost_return_bps=-drop*100,
            net_exit_proceeds=observed,evidence_current=True,exit_liquidity_valid=True,soft_deterioration=False)
        decision=monitor(book=book,sleeve=sleeve,identity=identity,
            observation=observation,policy=policy,adapter=adapter)
        self.assertEqual(restore_risk(book,identity)['last_action']['reason'],'hard_stop')
        if missing:
            self.assertEqual(decision['action'],'exit_pending')
            self.assertEqual(a.snapshot()['capital']['realized_equity'],'1000.00')
            self.assertEqual(a.snapshot()['capital']['deployed_basis'],'50')
            book.close();book=PaperBook(root/family/'native.sqlite',run_id='crash',lane=strategy,
                policy_hash=policies(family)[strategy],initial=1_000_000)
            self.assertEqual(restore_risk(book,identity)['last_action']['action'],'full_exit')
            # Recovery quote is newly observed; the original decision remains.
            observation=dict(observation,id='recovery',at=at,after_cost_return_bps=1000,net_exit_proceeds=55_000)
            adapter.exit_quote=lambda qty:execution
            monitor(book=book,sleeve=sleeve,identity=identity,observation=observation,policy=policy,adapter=adapter)
        self.assertEqual(book._load(identity)['status'],'settled');self.assertTrue(book.replay()['verified'])
        self.assertEqual(Decimal(a.snapshot()['capital']['realized_equity']),Decimal(950)+Decimal(net)/1000)
        a.verify_replay()
        from meme_machine.shared_capital.reporting import export
        from dashboard.model import position,stamp
        projection=export(a)
        display=position(projection['positions'][0],plan['seed']['inception'],stamp(projection['as_of']))
        self.assertEqual(display['protection']['stop_signal_bps'],policy['hard_stop_bps'])
        self.assertEqual(display['protection']['executed_return_bps'],(net-50_000)*10000//50_000)
        self.assertFalse(display['protection']['pending_exit'])
        self.assertEqual(display['protection']['decision_kind'],'PROTECTIVE_EXIT')
        self.assertEqual(display['protection']['trigger_return_bps'],-drop*100)
        from meme_machine.runtime.usd_valuation import utc
        self.assertEqual(display['protection']['actionable_at'],utc(now+1))
        if not missing:self.assertEqual(display['protection']['observed_return_bps'],-drop*100)
        return dict(regime=family+'_survivor',classification='SYNTHETIC_NATIVE_FUNDED_REPLAY',
            principal_usd='50',stop_signal_bps=policy['hard_stop_bps'],observed_return_bps=-drop*100,
            executed_return_bps=(net-50_000)*10000//50_000,portfolio_loss_usd=str(Decimal(50)-Decimal(net)/1000),
            extra_execution_delay_seconds=3 if delayed else 0,required_fill_delay_seconds=0,
            missing_execution_recovered=missing,provider_capacity_proven=False,capital=a.snapshot()['capital'])

    def current_loss(self,family,drop,delayed):
        root,a,now,_=self.fixture(policy=shared_risk_candidate(),new_epoch=True)
        if family=='pump':
            from meme_machine.lanes.pump.paper_accounting import PaperBook
            from meme_machine.lanes.pump.pump_acceleration_paper import PumpAccelerationPaperLifecycle
            from meme_machine.lanes.pump.pump_acceleration_strategy import MODE_POSTGRAD,POLICY,policy_hash,STRATEGY_ID
            from tests.lanes.pump.test_pump_acceleration_paper import qualification
            (root/'pump').mkdir(exist_ok=True)
            book=PaperBook(root/'pump/native.sqlite',run_id='crash',lane=STRATEGY_ID,policy_hash=policy_hash(),initial=1_000_000)
            self.addCleanup(book.close)
            life=PumpAccelerationPaperLifecycle(book=book,lifecycle_id='crash:pump-current')
            life.reserve(replace(qualification(),mode=MODE_POSTGRAD),50_000,now)
            life.fill(1000,50_000,now+2,'pumpswap')
            observed=50_000*(100-drop)//100
            action=life.mark(observed,now+3,80,True)
            self.assertEqual(action['exit_reason'],'risk_stop')
            net=observed*90//100
            if delayed:net=net*75//100
            # Same native mark/settle clock in production; this later fresh
            # synthetic quote is a counterfactual latency stress, not a live fill.
            life.settle(net,now+3+(3 if delayed else 0),evidence=dict(synthetic=True,acquired=now+3+(3 if delayed else 0)))
            self.assertTrue(book.replay()['verified']);basis=50_000;stop=POLICY.hard_stop_bps;delay=0
        else:
            from tests.lanes.pons.test_pons_partial_accounting import PartialAccountingTests
            from meme_machine.lanes.pons.evidence import Store,digest
            from meme_machine.lanes.pons.pons_selective_capital import CohortCapital
            from meme_machine.lanes.pons.pons_selective_ledger import SelectivePaper,STRATEGY_NAMESPACE
            from meme_machine.lanes.pons.pons_selective_continuation import POLICY_HASH,EXIT_POLICY,runner_action
            (root/'pons').mkdir(exist_ok=True)
            self.enterContext(patch.dict(os.environ,{'MM_DIRECTIONAL_SLEEVE_DB':str(root/'pons/directional-sleeve.sqlite')}))
            store=Store(root/'pons/native.sqlite');self.addCleanup(store.close)
            guard=CohortCapital(root/'pons/capital.sqlite',1_000_000)
            f=PartialAccountingTests();features=f.features(now);clock=[now]
            paper=SelectivePaper(store,STRATEGY_NAMESPACE,1_000_000,delay=EXIT_POLICY['entry_delay_seconds'],
                natural_policy_hash=POLICY_HASH,on_commit=guard.observe,clock_ns=lambda:clock[0]*10**9)
            guard.reserve('crash:pons-current',50_250,at=now,decision_hash=digest(features),trial_path=root/'pons/native.sqlite',
                native_reservation_intent=dict(market='m',amount=50_000,gas_budget=250,features=features,now=now,kind='natural'))
            paper.reserve('crash:pons-current',market='m',amount=50_000,gas_budget=250,now=now,features=features)
            clock[0]=now+2;p=paper.advance('crash:pons-current',now=now+2,action='entry',quote=f.quote(now+2,'buy',50_000,1000))
            basis=p['remaining_cost'];observed=basis*(100-drop)//100
            clock[0]=now+3
            p=paper.advance('crash:pons-current',now=now+3,action='mark',quote=f.quote(now+3,'sell',1000,observed+2))
            action=runner_action(tokens=1000,partial_taken=False,after_cost_return_bps=(observed-basis)*10000//basis,
                high_water_return_bps=0,seconds_since_high=0,new_buyer_growth=3,buy_quote=300,sell_quote=100)
            self.assertEqual(action['reason'],'risk')
            p=paper.advance('crash:pons-current',now=now+3,action='exit_intent',exit_tokens=action['exit_tokens'])
            original_due=p['due'];self.assertEqual(original_due,now+5)
            # No early sale, fabricated proceeds, or renewed intent.
            from meme_machine.lanes.pons import BoundaryError
            clock[0]=now+4
            with self.assertRaisesRegex(BoundaryError,'selective_exit_not_due'):
                paper.advance('crash:pons-current',now=now+4,action='exit',quote=f.quote(now+4,'sell',1000,observed))
            self.assertEqual(paper._get('crash:pons-current')['due'],original_due)
            net=observed*90//100
            if delayed:net=net*75//100
            at=original_due+(3 if delayed else 0);clock[0]=at
            p=paper.advance('crash:pons-current',now=at,action='exit',quote=f.quote(at,'sell',1000,net+2))
            guard.settle('crash:pons-current',p,at=at)
            self.assertTrue(paper.accounting('crash:pons-current')['replay_verified'])
            self.assertTrue(guard.reconcile()['cash_basis_conservation']);stop=EXIT_POLICY['risk_bps'];delay=2
        a.verify_replay();expected=Decimal(1000)+Decimal(net-basis)/1000
        self.assertEqual(Decimal(a.snapshot()['capital']['realized_equity']),expected)
        self.assertEqual(a.snapshot()['capital']['deployed_basis'],'0')
        return dict(regime=family+'_current',classification='SYNTHETIC_NATIVE_FUNDED_REPLAY',
            principal_usd='50',native_basis_usd=str(Decimal(basis)/1000),stop_signal_bps=stop,
            observed_return_bps=(observed-basis)*10000//basis,executed_return_bps=(net-basis)*10000//basis,
            portfolio_loss_usd=str(Decimal(basis-net)/1000),required_fill_delay_seconds=delay,
            extra_execution_delay_seconds=3 if delayed else 0,provider_capacity_proven=False,capital=a.snapshot()['capital'])

    def test_four_native_funded_regimes_do_not_promise_stop_threshold_fill_prices(self):
        rows=[]
        for drop in (20,40,60,80):
            for delayed in (False,True):
                for family in ('pump','pons'):
                    rows.append(self.current_loss(family,drop,delayed))
                    rows.append(self.survivor_loss(family,drop,delayed))
        for row in rows:self.assertLess(row['executed_return_bps'],row['observed_return_bps'])
        print('FUNDED_STOP_LOSS_STRESS',json.dumps(rows),flush=True)

    def test_missing_survivor_execution_preserves_irreversible_intent_and_reconciles_after_restart(self):
        for family in ('pump','pons'):
            self.survivor_loss(family,60,True,missing=True)


class NativeTimingTests(unittest.TestCase):
    def run_positions(self,*args,**kwargs):
        from tests import test_pons_shared_native_acquisition as sharing
        return sharing.SharedNativeAcquisitionTests.run_positions(self,*args,**kwargs)

    def test_original_turn_due_risk_commit_and_sale_are_distinct_clocks(self):
        from tests import test_pons_protective_capacity as capacity
        rows=[]
        for count in (1,2,5,10,15,20):
            for factor,label in ((.6,'full_exit'),(2.2,'partial_exit')):
                events=[]
                def trace(r,rpc):
                    transition=r.book.transition
                    def commit(identity,action,*args,**kwargs):
                        start=rpc.clock
                        result=transition(identity,action,*args,**kwargs)
                        observation=(kwargs.get('evidence') or {}).get('observation') or {}
                        events.append(dict(identity=identity,action=action,started=start,
                            native_at=args[0] if args else None,committed=rpc.clock,
                            observed_return_bps=observation.get('after_cost_return_bps'),
                            source_evidence_current=observation.get('evidence_current')))
                        return result
                    r.book.transition=commit
                _,risk,rpc,result=capacity.replay(self,count,price_factor=factor,before_step=trace)
                self.assertTrue(all(r['last_action']['action']==label for r in risk))
                self.assertTrue(all(b-a>=.5-1e-8 for a,b in zip(rpc.starts,rpc.starts[1:])))
                self.assertTrue(self.native_runtime.book.replay()['verified'])
                self.assertTrue(self.native_runtime.sleeve.reconcile()['reconciled'])
                complete=rpc.clock-100+rpc.local_wall_seconds
                if count==20 and label=='partial_exit':self.assertGreater(complete,3)
                rows.append(dict(owners=count,action=label,scope='NATIVE_CORE_USD_VALUATION_STUBBED',
                    rps=2,scheduled_turn=100,original_observation_due=103,
                    physical_starts=rpc.starts,last_responses=rpc.responses,
                    queue_wait_seconds=sum(rpc.waits),local_wall_seconds=rpc.local_wall_seconds,
                    native_cpu_seconds=rpc.local_cpu_seconds,events=events,
                    complete_with_local_seconds=complete,complete_by_three_seconds=complete<3,
                    sale_guarantee=False,provider_capacity_proven=False,
                    response_bytes=rpc.bytes,request_bytes=rpc.request_bytes,
                    logical_methods=dict(rpc.methods),accounting=result['accounting']))
        print('NATIVE_EXIT_TIMELINE',json.dumps(rows),flush=True)
