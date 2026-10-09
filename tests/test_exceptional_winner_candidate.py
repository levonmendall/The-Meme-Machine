"""Inactive proposal mechanics on existing native journals. Every market input
and readiness assertion here is synthetic; none establishes capacity or P&L.
The supported offline driver prohibits market I/O and bounds fixture storage.
"""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from meme_machine.runtime import exceptional_winner as candidate
from meme_machine.runtime.directional_continuation import BRIDGE_GATES,bridge_state
from meme_machine.runtime.survivor_risk import mark
from engineering.extended_survivor_hold.research import policies


def risk_state():
    return dict(opened_at=10,original_basis=100,original_quantity=400,remaining_quantity=300,
        realization_taken=True,realized_profit=7,high_water_bps=40000,high_at=11,
        tightened=True,deterioration_streak=0,bridged=True,bridged_at=1000,bridge_deadline=129610)


def context(family,at,quantity=300,*,spent=0):
    # Deliberately small synthetic demand to isolate finite-ledger mechanics.
    # These numbers are NOT a claim about actual one-hour provider demand.
    evidence={key:True for key in candidate.SAFETY}
    evidence.update(observed_at=at,quantity=quantity,native_net_profit_usd='100',entry_buyers=20,minimum_buyers=4,
        independent_buyers=20,buy_flow=300,sell_flow=100,new_buyers=2)
    resources=dict(family=family,phase='CONTINUATION',observed_at=at,capacity_verified=True,
        readiness={key:True for key in candidate.HEALTH},position_owner_count=1,
        queue_depth=0,queue_wait_seconds=0,rss_bytes=1024,cpu_cores='1',
        safety_latency_seconds=1,cadence_seconds=3 if family=='pons_survivor' else 5,
        recovery_available=True,maintenance_until=10+400*3600,
        recovery_until=10+400*3600+3600,service_until=10+400*3600+3665,
        run_id='synthetic-original-run',started_at=10,
        used=dict(rpc_cu=spent*1000,rpc_elements=spent*20,http_attempts=spent*10,
            http_bytes=spent*1000,native_bytes=0),
        limits=dict(rpc_cu=24000000,rpc_elements=500000,http_attempts=500000,
            http_bytes=1024**3,native_bytes=32*1024**3),
        next_window_demand=dict(rpc_cu=1000,rpc_elements=20,http_attempts=10,http_bytes=1000,native_bytes=0),
        next_window_demand_verified=True,spend_used=str(Decimal(spent)*Decimal('.000525')),
        spend_limit='20',next_window_spend='.000525')
    return dict(version=candidate.VERSION,family=family,evidence=evidence,resources=resources)


def observation(at,gain=40000,**kw):
    return dict(id=str(at),at=at,after_cost_return_bps=gain,net_exit_proceeds=375,
        exit_liquidity_valid=True,**kw)


def apply(state,family,at,ctx,gain=40000):
    if family.endswith('survivor'):
        return candidate.survivor_mark(state,observation(at,gain),policies()[family.split('_')[0]],
            family=family,context=ctx)
    facts={key:True for key in BRIDGE_GATES};facts['after_cost_return_bps']=gain
    native,expired,reason=candidate.current_bridge(state,facts,now=at,ordinary_expired=True,context=ctx)
    return native,dict(action='full_exit' if expired else 'hold',reason=reason)


class RenewalRulesTests(unittest.TestCase):
    def test_default_native_policy_and_initial_current_bridge_remain_identical(self):
        for family,seconds in candidate.CHECKPOINTS.items():
            s=risk_state();at=10+seconds
            if family.endswith('survivor'):
                policy=policies()[family.split('_')[0]]
                self.assertEqual(candidate.survivor_mark(s,observation(at),policy,family=family,context=None),
                    mark(s,observation(at),policy))
            else:
                facts={key:True for key in BRIDGE_GATES}
                expected=bridge_state(s,facts,now=at,ordinary_expired=True)
                got=candidate.current_bridge(s,facts,now=at,ordinary_expired=True,context=None)
                self.assertEqual(got[:2],expected)
            early=risk_state();early['bridged']=False
            facts={key:True for key in BRIDGE_GATES}
            self.assertEqual(candidate.current_bridge(early,facts,now=1000,ordinary_expired=True,
                context=context('pump_current',1000))[:2],bridge_state(early,facts,now=1000,ordinary_expired=True))

    def test_entry_bound_automatic_renewals_through_14_days_for_all_four_families(self):
        for family,seconds in candidate.CHECKPOINTS.items():
            s=risk_state();original={k:s[k] for k in ('opened_at','original_basis','original_quantity','remaining_quantity')}
            first=seconds//3600;lengths=[]
            for hour in range(first,337):
                at=10+hour*3600;s,action=apply(s,family,at,context(family,at,spent=hour-first))
                self.assertEqual(action['action'],'hold',(family,hour,action))
                self.assertEqual(s['exceptional']['until'],at+3600)
                self.assertEqual(s['exceptional']['renewals'],hour-first+1)
                self.assertEqual({k:s[k] for k in original},original)
                lengths.append(len(json.dumps(s['exceptional'])))
                s=json.loads(json.dumps(s))  # restart representation, no rebasing
            self.assertLess(max(lengths)-min(lengths),100)
            self.assertLess(max(lengths),2048)

    def test_accelerated_original_cadences_through_extended_current_and_survivor_windows(self):
        counts={}
        for family in candidate.CHECKPOINTS:
            first=candidate.CHECKPOINTS[family];cadence=3 if family=='pons_survivor' else 5
            # 36 -> 72 hours Current; 72 -> 96 hours Survivor. Native cadence,
            # immutable entry clocks and fresh synthetic evidence on EVERY turn.
            end=72*3600 if family.endswith('current') else 96*3600
            s=risk_state();count=0
            for age in range(first,end+1,cadence):
                at=10+age;ctx=context(family,at,spent=(age-first)//3600)
                s,action=apply(s,family,at,ctx)
                self.assertEqual(action['action'],'hold');count+=1
            counts[family]=count
            self.assertEqual(s['opened_at'],10);self.assertEqual(s['high_water_bps'],40000)
        print('EXCEPTIONAL_CADENCE',json.dumps(counts),flush=True)

    def test_current_appreciation_strata_qualify_without_lookahead_or_peak_only_qualification(self):
        for family,seconds in candidate.CHECKPOINTS.items():
            for multiple in (2,5,10,25,50):
                s=risk_state();gain=(multiple-1)*10000;s['high_water_bps']=gain
                _,action=apply(s,family,10+seconds,context(family,10+seconds),gain=gain)
                self.assertEqual(action['action'],'hold')
            s=risk_state();s['high_water_bps']=499000
            # Native trail exits take precedence; positive profit alone does not renew.
            _,action=apply(s,family,10+seconds,context(family,10+seconds),gain=9999)
            self.assertEqual(action['action'],'full_exit')

    def test_current_requires_preexisting_bridge_and_prior_positive_realization(self):
        for changes in ({'bridged':False},{'realization_taken':False},{'realized_profit':0},{'realized_profit':-1}):
            for family in candidate.CHECKPOINTS:
                if 'bridged' in changes and family.endswith('survivor'):continue
                at=10+candidate.CHECKPOINTS[family]
                s,action=apply(dict(risk_state(),**changes),family,at,context(family,at))
                self.assertEqual(action['action'],'full_exit');self.assertFalse(s['exceptional']['protected'])

    def test_missing_stale_incomplete_or_unauthenticated_evidence_never_renews(self):
        at=259210
        for key in candidate.SAFETY:
            ctx=context('pons_survivor',at);ctx['evidence'][key]=False
            _,action=apply(risk_state(),'pons_survivor',at,ctx)
            self.assertEqual(action['action'],'full_exit',key)
        for changes in ({'observed_at':at-6},{'observed_at':at+1},{'quantity':299},
                        {'independent_buyers':9},{'buy_flow':100},{'new_buyers':0}):
            ctx=context('pons_survivor',at);ctx['evidence'].update(changes)
            _,action=apply(risk_state(),'pons_survivor',at,ctx)
            self.assertEqual(action['action'],'full_exit',changes)
        ctx=context('pons_survivor',at);ctx['evidence']=None
        _,action=apply(risk_state(),'pons_survivor',at,ctx);self.assertEqual(action['action'],'full_exit')

    def test_stops_trails_structure_and_irreversible_exits_precede_renewal(self):
        for family in ('pump_survivor','pons_survivor'):
            policy=policies()[family.split('_')[0]];at=259210
            for obs in (observation(at,policy['hard_stop_bps']),observation(at,24000),
                        observation(at,creator_distribution=True),observation(at,severe_persistent_deterioration=True),
                        dict(observation(at),exit_liquidity_valid=False),observation(at,soft_deterioration=True)):
                s=risk_state();s['deterioration_streak']=policy['soft_confirmations']-1
                expected=mark(s,obs,dict(policy,maximum_hold_seconds=259201))
                got=candidate.survivor_mark(s,obs,policy,family=family,context=context(family,at))
                self.assertEqual(got,expected);self.assertEqual(got[1]['action'],'full_exit')
            s=risk_state();s['last_action']=dict(action='full_exit',reason='earlier_exit')
            _,action=apply(s,family,at,context(family,at))
            self.assertEqual(action['reason'],'earlier_exit')

    def test_failed_requalification_stays_pending_after_restart_and_rebound(self):
        family='pons_survivor';at=259210;s,_=apply(risk_state(),family,at,context(family,at))
        broken=context(family,at+3);broken['evidence']['history_complete']=False
        s,action=apply(s,family,at+3,broken);reason=action['reason'];first=s['exceptional']['exit_required_at']
        s=json.loads(json.dumps(s));s,action=apply(s,family,at+6,context(family,at+6))
        self.assertEqual(action['reason'],reason);self.assertEqual(s['exceptional']['exit_required_at'],first)

    def test_missing_boundary_cannot_be_retroactively_renewed(self):
        for family,seconds in candidate.CHECKPOINTS.items():
            at=10+seconds+6;s,action=apply(risk_state(),family,at,context(family,at))
            self.assertEqual(action['action'],'full_exit');self.assertIn('checkpoint_missed',action['reason'])

    def test_each_finite_resource_counter_and_spend_fail_before_budget_overrun(self):
        at=259210
        for key in candidate.COUNTERS:
            ctx=context('pons_survivor',at);ctx['resources']['used'][key]=ctx['resources']['limits'][key]
            if key=='native_bytes':ctx['resources']['next_window_demand'][key]=1
            _,action=apply(risk_state(),'pons_survivor',at,ctx)
            self.assertIn(key,action['reason'])
        ctx=context('pons_survivor',at);ctx['resources']['spend_used']='20'
        _,action=apply(risk_state(),'pons_survivor',at,ctx);self.assertIn('spend_insufficient',action['reason'])

    def test_readiness_owner_latency_and_budget_regressions_are_actionable(self):
        at=259210;family='pons_survivor'
        mutations=({'capacity_verified':False},{'position_owner_count':2},{'cadence_seconds':5},
            {'queue_depth':65},{'safety_latency_seconds':4},{'cpu_cores':'NaN'},
            {'next_window_demand_verified':False},{'recovery_available':False},{'readiness':None},
            {'phase':'RECOVERY'},{'phase':'FAULT'},{'phase':'BOOTSTRAP'})
        for changes in mutations:
            ctx=context(family,at);ctx['resources'].update(changes)
            s,action=apply(risk_state(),family,at,ctx)
            self.assertEqual(action['action'],'full_exit',changes);self.assertFalse(s['exceptional']['protected'])
        s,_=apply(risk_state(),family,at,context(family,at,spent=2))
        for change in ('used','spend_used','run_id','limits','maintenance_until'):
            ctx=context(family,at+3,spent=3)
            if change=='used':ctx['resources']['used']['rpc_cu']=0
            elif change=='spend_used':ctx['resources']['spend_used']='0'
            elif change=='run_id':ctx['resources']['run_id']='restarted-new-run'
            elif change=='limits':ctx['resources']['limits']['rpc_elements']+=1
            else:ctx['resources']['maintenance_until']+=1
            _,action=apply(s,family,at+3,ctx);self.assertEqual(action['action'],'full_exit',change)

    def test_finite_operating_window_cannot_grant_speculative_recovery_hold(self):
        at=259210;family='pons_survivor';ctx=context(family,at)
        ctx['resources'].update(maintenance_until=at+3599,recovery_until=at+7199,service_until=at+7264)
        _,action=apply(risk_state(),family,at,ctx)
        self.assertIn('operating_window_exhausted',action['reason'])

    def test_native_profit_must_remain_positive_after_existing_continuation_costs(self):
        at=259210;family='pons_survivor'
        for profit in ('0','-1','NaN','.00105'):
            ctx=context(family,at,spent=2);ctx['evidence']['native_net_profit_usd']=profit
            _,action=apply(risk_state(),family,at,ctx)
            self.assertIn('profit_after_continuation_costs',action['reason'])


class NativeSurvivorTests(unittest.TestCase):
    def native(self,family,*,execution_gas=None):
        from tests.test_survivor_commit import SurvivorCommitTests
        from meme_machine.runtime.survivor_paper_book import PaperBook
        fixture=SurvivorCommitTests()
        lane={'pump_survivor':'pumpswap-survivor-momentum-v1','pons_survivor':'pons-postgrad-survivor-momentum-v1'}[family]
        fixture.new_book=lambda:PaperBook(str(fixture.root/'paper'),run_id='run',lane=lane,policy_hash='b',initial=1000)
        fixture.setUp();self.addCleanup(fixture.tearDown)
        if execution_gas is not None:
            original=fixture.adapter.entry
            fixture.adapter.entry=lambda n:dict(original(n),gas=execution_gas)
        fixture.fill()
        return fixture

    def test_native_books_keep_original_owner_partial_state_and_accounting_through_14_days(self):
        from meme_machine.runtime.survivor_commit import monitor,restore_risk
        for family in ('pump_survivor','pons_survivor'):
            f=self.native(family);policy=policies()[family.split('_')[0]];f.adapter.at=11;f.adapter.proceeds=32
            first=monitor(book=f.book,sleeve=f.sleeve,identity='run:one',observation=observation(11),policy=policy,adapter=f.adapter)
            self.assertEqual(first['action'],'partial_exit');remaining=f.book._load('run:one')['tokens']
            original=restore_risk(f.book,'run:one');identity=deepcopy(f.book.identity)
            for hour in range(1,337):
                at=10+hour*3600;f.adapter.at=at
                action=monitor(book=f.book,sleeve=f.sleeve,identity='run:one',observation=observation(at),policy=policy,
                    adapter=f.adapter,exceptional_context=context(family,at,remaining,spent=hour))
                self.assertEqual(action['action'],'hold',(family,hour))
                if hour in (71,72,96,168,335):f.reopen()
                state=restore_risk(f.book,'run:one')
                for key in ('opened_at','original_quantity','original_basis','remaining_quantity','high_water_bps'):
                    self.assertEqual(state[key],original[key])
                self.assertEqual(f.book.identity,identity)
            f.adapter.at=10+336*3600+3;f.adapter.proceeds=210
            action=monitor(book=f.book,sleeve=f.sleeve,identity='run:one',observation=observation(f.adapter.at,20000),
                policy=policy,adapter=f.adapter,exceptional_context=context(family,f.adapter.at,remaining,spent=337))
            self.assertEqual(action['reason'],'tail_gain_giveback');f.reopen();before=f.book.reconcile()
            self.assertEqual(monitor(book=f.book,sleeve=f.sleeve,identity='run:one',observation=observation(f.adapter.at),
                policy=policy,adapter=f.adapter,exceptional_context=context(family,f.adapter.at))['action'],'settled')
            self.assertEqual(f.book.reconcile(),before);self.assertEqual(f.sleeve.reconcile()['reserved'],0)

    def test_missing_exit_evidence_preserves_native_intent_across_restart(self):
        from meme_machine.runtime.survivor_commit import monitor,restore_risk
        for family in ('pump_survivor','pons_survivor'):
            f=self.native(family);policy=policies()[family.split('_')[0]];f.adapter.at=11;f.adapter.proceeds=32
            monitor(book=f.book,sleeve=f.sleeve,identity='run:one',observation=observation(11),policy=policy,adapter=f.adapter)
            at=259210;f.adapter.at=at;f.adapter.quote_available=False;remaining=f.book._load('run:one')['tokens']
            obs=dict(observation(at),after_cost_return_bps=None)
            action=monitor(book=f.book,sleeve=f.sleeve,identity='run:one',observation=obs,policy=policy,adapter=f.adapter,
                exceptional_context={})
            self.assertEqual(action['action'],'exit_pending');before=f.book.reconcile();f.reopen()
            self.assertEqual(f.book.reconcile(),before);self.assertFalse(restore_risk(f.book,'run:one')['exceptional']['protected'])
            f.adapter.at+=3;f.adapter.quote_available=True;f.adapter.proceeds=210
            action=monitor(book=f.book,sleeve=f.sleeve,identity='run:one',observation=observation(f.adapter.at),policy=policy,
                adapter=f.adapter,exceptional_context=context(family,f.adapter.at,remaining))
            self.assertEqual(action['reason'],restore_risk(f.book,'run:one')['last_action']['reason'])
            self.assertEqual(f.book._load('run:one')['status'],'settled')

    def test_failure_before_provider_monitoring_persists_exit_once_without_provider_work(self):
        from meme_machine.runtime.survivor_commit import exceptional_evidence_failure,restore_risk,monitor
        for family in ('pump_survivor','pons_survivor'):
            f=self.native(family);row={'position':'run:one'};saved=[];at=259210
            runtime=SimpleNamespace(book=f.book,now=lambda:at,
                history=SimpleNamespace(rows=lambda:[row],save=lambda r:saved.append(deepcopy(r))))
            before=f.book.reconcile();journal=f.book.db.execute('SELECT COUNT(*) FROM journal').fetchone()[0]
            exceptional_evidence_failure(runtime,family=family,blocker='subscription_rejected')
            self.assertEqual(f.book.db.execute('SELECT COUNT(*) FROM journal').fetchone()[0],journal)
            runtime.exceptional_context=lambda *args:None
            with patch.object(f.adapter,'exit_quote',side_effect=AssertionError('fault publication must not retry provider')):
                exceptional_evidence_failure(runtime,family=family,blocker='subscription_rejected')
                after=f.book.db.execute('SELECT COUNT(*) FROM journal').fetchone()[0]
                exceptional_evidence_failure(runtime,family=family,blocker='subscription_rejected')
                self.assertEqual(f.book.db.execute('SELECT COUNT(*) FROM journal').fetchone()[0],after)
            expected=dict(before,capital_unit_seconds=before['capital_unit_seconds']+before['basis']*(at-10))
            self.assertEqual(f.book.reconcile(),expected);self.assertFalse(saved[-1]['position_safety']['protected'])
            f.reopen();risk=restore_risk(f.book,'run:one');self.assertEqual(risk['opened_at'],10)
            self.assertEqual(risk['exceptional']['exit_required_at'],at)
            self.assertEqual(risk['exceptional']['blocker'],'subscription_rejected')
            f.adapter.at=at+3;f.adapter.proceeds=210
            result=monitor(book=f.book,sleeve=f.sleeve,identity='run:one',observation=observation(at+3),
                policy=policies()[family.split('_')[0]],adapter=f.adapter,
                exceptional_context=context(family,at+3,400))
            self.assertEqual(result['reason'],'exceptional_authenticated_evidence_unavailable')
            self.assertEqual(f.book._load('run:one')['status'],'settled')

    def test_existing_survivor_workers_publish_pre_monitor_provider_failure_without_new_worker(self):
        from meme_machine.lanes.pons.pons_survivor_runtime import Runtime as Pons
        from meme_machine.lanes.pump.pumpswap_survivor_runtime import Runtime as Pump
        from meme_machine.lanes.pons import BoundaryError
        from meme_machine.runtime.survivor_commit import restore_risk
        for family,kind in (('pump_survivor',Pump),('pons_survivor',Pons)):
            f=self.native(family,execution_gas=0);row=dict(id='mint',position='run:one');runtime=kind.__new__(kind)
            runtime.book=f.book;runtime.sleeve=f.sleeve;runtime.now=lambda:259210
            runtime.exceptional_context=lambda *args:None
            runtime.history=SimpleNamespace(rows=lambda:[row],save=lambda r:None,
                get_meta=lambda key:None,pending_graduations=lambda:[])
            runtime.attempts=SimpleNamespace(maintain=lambda *args,**kwargs:None)
            def failure(*args,**kwargs):raise BoundaryError('provider_disconnected')
            def pump_failure(*args,**kwargs):raise ValueError('provider_disconnected')
            runtime._provider=failure;runtime._position=pump_failure
            with patch('meme_machine.runtime.storage.compact_survivor'):
                result=runtime.step(admit=False)
            self.assertEqual(result['last_boundary'],'provider_disconnected')
            self.assertFalse(result['position_safety'][0]['protected'])
            self.assertTrue(result['position_safety'][0]['pending_exit'])
            if family=='pons_survivor':self.assertEqual(result['native_execution_cost'],0)
            self.assertEqual(restore_risk(f.book,'run:one')['last_action']['reason'],
                'exceptional_authenticated_evidence_unavailable')


class NativeCurrentTests(unittest.TestCase):
    def pump(self,*,gain=40000):
        from tests.lanes.pump.test_pump_acceleration_paper import qualification
        from meme_machine.lanes.pump.pump_acceleration_strategy import MODE_POSTGRAD,STRATEGY_ID,policy_hash
        from meme_machine.lanes.pump.pump_acceleration_paper import PumpAccelerationPaperLifecycle
        from meme_machine.runtime.survivor_paper_book import PaperBook
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);path=Path(tmp.name)/'paper.sqlite'
        book=PaperBook(str(path),run_id='run',lane=STRATEGY_ID,policy_hash=policy_hash(),initial=10000)
        self.addCleanup(lambda:book.close())
        life=PumpAccelerationPaperLifecycle(book=book,lifecycle_id='run:x')
        life.reserve(replace(qualification(),mode=MODE_POSTGRAD),1000,100)
        life.fill(tokens=100,cost_quote_units=1000,now=102,surface='pumpswap')
        life.mark(1000*(10000+gain)//10000,now=110,demand_score=80)
        life.harvest(25,250*(10000+gain)//10000,now=111)
        return life,book

    def pump_mark(self,life,at,*,candidate_enabled=True,gain=40000):
        p=life.position;facts={key:True for key in BRIDGE_GATES};facts['after_cost_return_bps']=gain
        evidence=dict(continuation=facts)
        if candidate_enabled:evidence['exceptional_candidate']=context('pump_current',at,p.tokens,spent=(at-102)//3600)
        return life.mark(p.basis_quote_units*(10000+gain)//10000,now=at,demand_score=80,evidence=evidence)

    def test_pump_native_current_bridge_renewal_restart_and_existing_trail_exit(self):
        from meme_machine.lanes.pump.pump_acceleration_paper import PumpAccelerationPaperLifecycle
        life,book=self.pump();self.pump_mark(life,3702);self.assertTrue(life.position.bridged)
        for hour in range(36,337):
            result=self.pump_mark(life,102+hour*3600);self.assertIsNone(result['exit_reason'])
            if hour in (36,72,96,168,335):life=PumpAccelerationPaperLifecycle.restore(book,'run:x')
            self.assertEqual(life.position.opened_at,102);self.assertEqual(life.position.peak_return_bps,40000)
            self.assertEqual((life.position.tokens,life.position.realized_quote_units),(75,1000))
        result=self.pump_mark(life,102+336*3600+5,gain=20000)
        self.assertEqual(result['exit_reason'],'tail_gain_giveback_exit')
        life=PumpAccelerationPaperLifecycle.restore(book,'run:x');life.settle(2250,now=102+336*3600+6)
        self.assertIsNone(PumpAccelerationPaperLifecycle.restore(book,'run:x').position);self.assertTrue(book.replay()['verified'])

    def test_pump_unavailable_evidence_intent_is_durable_without_synthetic_mark_or_fill(self):
        from meme_machine.lanes.pump.pump_acceleration_paper import PumpAccelerationPaperLifecycle
        life,book=self.pump();self.pump_mark(life,3702);self.pump_mark(life,129702)
        before=book.reconcile();life.exceptional_exit_intent('exceptional_authenticated_evidence_unavailable',129707)
        self.assertEqual(book.reconcile(),before)
        life=PumpAccelerationPaperLifecycle.restore(book,'run:x');self.assertEqual(life.position.exit_intended_at,129707)
        self.assertEqual(self.pump_mark(life,129712)['exit_reason'],'exceptional_authenticated_evidence_unavailable')
        life.settle(3750,now=129713);self.assertIsNone(PumpAccelerationPaperLifecycle.restore(book,'run:x').position)

    def test_pump_default_candidate_absence_still_exits_at_original_36_hours(self):
        life,_=self.pump();self.pump_mark(life,3702,candidate_enabled=False)
        self.assertEqual(self.pump_mark(life,129702,candidate_enabled=False)['exit_reason'],'timeout')

    def test_pump_extension_gain_comes_from_native_quote_not_exaggerated_context(self):
        life,_=self.pump(gain=10000)
        self.pump_mark(life,3702,gain=10000)
        # Stay above the original 60%-of-peak gain trail while below 2x now.
        facts={key:True for key in BRIDGE_GATES};facts['after_cost_return_bps']=40000
        evidence=dict(continuation=facts,exceptional_candidate=context('pump_current',129702,75))
        result=life.mark(1499,now=129702,demand_score=80,evidence=evidence)
        self.assertIn('current_after_cost_two_times_required',result['exit_reason'])

    def test_pons_native_current_controller_partial_renewal_restart_and_pending_exit(self):
        from tests.test_continuation_resource_efficiency import LongHoldStorageTests
        from meme_machine.lanes.pons.pons_selective_continuation import POLICY_HASH,runner_action
        from meme_machine.lanes.pons.pons_selective_recovery import LifecycleState
        from meme_machine.lanes.pons.pons_selective_paper import _bridge_action
        from meme_machine.lanes.pons.evidence import Store
        from meme_machine.lanes.pons.pons_selective_ledger import SelectivePaper,STRATEGY_NAMESPACE
        f=LongHoldStorageTests();f.setUp();self.addCleanup(f.doCleanups);p=f.fill()
        evaluation=dict(token='token',curve='m',source_transaction='fixture',market_events=[],
            candidate=dict(curve='m',token='token',auth={'fixture':True},record={}),
            vector=dict(current_threshold_pass=True,policy_hash=POLICY_HASH,
                trajectory={'graduation_eta_seconds':100},demand={'largest_buyer_flow_bps':100}))
        state=LifecycleState.create(f.store,'x',evaluation,10000,21000,opened_at=102,last_block=1020)
        f.paper.controller_context=state.checkpoint;state.high_water=40000;state.high_at=104;state.first_tail_crossed_at=104
        f.clock[0]=104;f.paper.advance('x',now=104,action='exit_intent',exit_tokens=250)
        f.clock[0]=106;q,ledger=f.quote(106,'sell',250,130,label='selective-v4-exit')
        p=f.paper.advance('x',now=106,action='exit',quote=q,finality_ledger=ledger);state.acknowledge(p)
        for hour in (1,*range(36,337)):
            at=102+hour*3600;f.clock[0]=at;facts={key:True for key in BRIDGE_GATES};facts['after_cost_return_bps']=40000
            facts['exceptional_candidate']=context('pons_current',at,750,spent=hour)
            native=runner_action(tokens=750,partial_taken=True,after_cost_return_bps=40000,high_water_return_bps=40000,
                seconds_since_high=0,new_buyer_growth=1,buy_quote=300,sell_quote=100,soft_deterioration_streak=0)
            action=_bridge_action(state,facts,native,p,now=at);self.assertEqual(action['action'],'hold')
            state.remember_action(action,p);q,ledger=f.quote(at,'sell',750,387)
            p=f.paper.advance('x',now=at,action='mark',quote=q,finality_ledger=ledger)
            if hour in (36,72,96,168,335):
                before=f.paper.reconcile();f.store.close();f.store=Store(f.path,max_records=8192)
                f.paper=SelectivePaper(f.store,STRATEGY_NAMESPACE,10000,natural_policy_hash=POLICY_HASH,
                    clock_ns=lambda:int(f.clock[0]*10**9))
                state=LifecycleState.restore(f.paper,'x');f.paper.controller_context=state.checkpoint
                self.assertEqual(f.paper.reconcile(),before)
            self.assertEqual(state.opened_at,102);self.assertEqual(state.high_water,40000)
            self.assertEqual((p['tokens'],p['realized_pnl']),(750,103))
        at+=5;facts['exceptional_candidate']['evidence']['history_complete']=False
        facts['exceptional_candidate']['evidence']['observed_at']=at
        action=_bridge_action(state,facts,dict(action='hold',reason=None),p,now=at)
        self.assertEqual(action['action'],'full_exit');state.remember_action(action,p);f.clock[0]=at
        p=f.paper.advance('x',now=at,action='exit_intent',exit_tokens=750)
        state=LifecycleState.restore(f.paper,'x');self.assertEqual(p['status'],'exit_pending')
        self.assertFalse(state.exceptional['protected']);f.paper.controller_context=state.checkpoint
        f.clock[0]=at+2;q,ledger=f.quote(at+2,'sell',750,387,label='selective-v4-exit')
        p=f.paper.advance('x',now=at+2,action='exit',quote=q,finality_ledger=ledger)
        self.assertEqual(p['status'],'settled');self.assertTrue(f.paper.reconcile()['cash_basis_conservation'])
        self.assertLess(f.store.db.execute('SELECT COUNT(*) FROM records').fetchone()[0],8192)
        self.assertLess(f.path.stat().st_size,64*1024**2)


class OperationalWindowTests(unittest.TestCase):
    from tests.test_position_continuation import LifecycleTests as Native
    fixture=Native.fixture;native_position=Native.native_position;service=Native.service

    def test_same_supervisor_persists_finite_window_without_refunding_or_allowance_reset(self):
        from meme_machine.operational.exceptional_window import prepare,tick,read,systemd_dropin
        from meme_machine.operational.bounded_provider import PhaseBudget
        from meme_machine.operational.admission import available
        root,a,now,s=self.service();book,_,identity=self.native_position(root,now,survivor=True)
        s.last_native_health['pump']['native_continuation']['flat']=False
        original=deepcopy(a.ledger()['runtime_admission']);original_envelope=deepcopy(s.provider_budget.envelope)
        window=prepare(s.provider_budget,maintenance_until=now+336*3600)
        duration=window['recovery_until']-window['started_at']
        self.assertEqual(systemd_dropin(window),'[Service]\nRuntimeMaxSec='+str(duration)+'\nTimeoutStopSec=65\n')
        self.assertEqual(window['service_until']-window['recovery_until'],65)
        self.assertEqual(prepare(s.provider_budget,maintenance_until=now+336*3600),window)
        with self.assertRaisesRegex(ValueError,'immutable'):prepare(s.provider_budget,maintenance_until=now+336*3600+1)
        with patch('time.time',return_value=now+1200):tick(s)
        self.assertEqual(available(a.ledger(),now+1200),'bootstrap_funding_deadline')
        with patch('time.time',return_value=now+1800):tick(s)
        self.assertEqual(s.provider_budget.phase(),'CONTINUATION');self.assertFalse(s.stop_requested)
        with patch('time.time',return_value=now+96*3600):
            s.provider_budget.reserve_http('https://solana-mainnet.g.alchemy.com/v2/offline',[dict(method='getSlot')])
            before=s.provider_budget.usage()['phases'];s.provider_budget=PhaseBudget(s.provider_budget.path);tick(s)
        self.assertEqual(s.provider_budget.usage()['phases'],before);self.assertEqual(read(s.provider_budget),window)
        for name in ('continuation','recovery'):self.assertEqual(s.provider_budget.envelope[name],original_envelope[name])
        self.assertEqual(book._load(identity)['status'],'open');self.assertFalse(s.stop_requested)
        for key in ('started_at','funding_until','stop_at','lifecycle_id','gross_reserved'):
            self.assertEqual(a.ledger()['runtime_admission'][key],original[key])
        self.assertEqual(available(a.ledger(),now+1),'observation_only_funding_closed')
        with patch('time.time',return_value=window['maintenance_until']):tick(s)
        self.assertEqual(s.provider_budget.phase(),'RECOVERY');self.assertFalse(s.provider_budget.fault()['protected'])
        with patch('time.time',return_value=window['recovery_until']):tick(s)
        self.assertEqual(s.provider_budget.phase(),'FAULT');self.assertTrue(s.stop_requested)
        self.assertEqual(book._load(identity)['status'],'open');a.verify_replay()

    def test_native_flat_reconciliation_cleans_up_extended_work_automatically(self):
        from meme_machine.operational.exceptional_window import prepare,tick
        from meme_machine.runtime.directional_continuation import native_sync
        root,a,now,s=self.service();book,sleeve,identity=self.native_position(root,now,survivor=True)
        prepare(s.provider_budget,maintenance_until=now+336*3600)
        with patch('time.time',return_value=now+1800):tick(s)
        book.transition(identity,'settled',now+1801,amount=6250);native_sync(book,sleeve,identity)
        s.last_native_health['pump']['native_continuation']['flat']=False
        with patch('time.time',return_value=now+1802):tick(s)
        self.assertFalse(s.stop_requested)
        s.last_native_health['pump']['native_continuation']['flat']=True
        with patch('time.time',return_value=now+1803):tick(s)
        self.assertTrue(s.stop_requested);self.assertEqual(s.provider_budget.phase(),'FLAT');a.verify_replay()


class EvidenceReuseAndOwnershipTests(unittest.TestCase):
    def test_integrated_current_and_survivor_model_has_no_fabricated_economics_or_renewal_savings(self):
        from engineering.extended_survivor_hold.candidate import build
        model=build();self.assertFalse(model['activation']);self.assertEqual(model['market_provider_calls'],0)
        self.assertIsNone(model['maximum_safely_demonstrated_operating_seconds'])
        self.assertEqual(len(model['economic_comparison']),130)
        for cell in model['economic_comparison']:
            self.assertIsNone(cell['realized_net_portfolio_pnl'])
            self.assertEqual(cell['complete_authenticated_market_lifecycles'],0)
        daily=model['incremental_additional_day']
        self.assertEqual(daily['pons_survivor']['quiet']['rpc_only_modeled_usd'],'5.624640000')
        self.assertEqual(daily['pons_current']['quiet_reference']['rpc_only_modeled_usd'],'4.826304000')
        self.assertEqual(daily['pump_survivor']['quiet_reference']['rpc_only_modeled_usd'],'0.910691250')
        self.assertEqual(daily['pump_current']['quiet_reference']['rpc_only_modeled_usd'],'1.092824250')
        for scenarios in daily.values():
            for row in scenarios.values():
                self.assertEqual(row['renewal_gate_provider_calls'],0)
                self.assertIsNone(row['complete_additional_day_cost_usd'])

    def test_current_renewal_reuses_same_incremental_history_and_rpc_session_without_acquisition(self):
        from tests.test_continuation_resource_efficiency import RollingV4Tests
        from meme_machine.lanes.pons import pons_selective_v4 as v4
        f=RollingV4Tests();f.setUp();self.addCleanup(f.doCleanups)
        at=129610;n=at*10
        with patch.object(v4,'collect_v4_activity',side_effect=f.tape),\
             patch('meme_machine.lanes.pons.pons_selective_acquisition._rpc',return_value=f.rpc):
            first=f.turn(n);prior=f.history.get(f.pool);calls=deepcopy(f.requests)
            history,rpc=f.history,f.rpc
            s,action=apply(risk_state(),'pons_current',at,context('pons_current',at))
            self.assertEqual(action['action'],'hold');self.assertEqual(f.requests,calls)
            self.assertEqual(f.history.get(f.pool),prior);self.assertIs(f.history,history);self.assertIs(f.rpc,rpc)
            second=f.turn(n+50)
            self.assertEqual([params for method,params in f.requests[len(calls):] if method=='range'],[(n+1,n+50)])
            calls=deepcopy(f.requests);s,action=apply(s,'pons_current',at+5,context('pons_current',at+5))
            self.assertEqual(f.requests,calls);self.assertEqual(action['action'],'hold')
            from meme_machine.lanes.pons.pons_selective_acquisition import _header_search
            first_block=int(_header_search(f.rpc,n+50,(n+50)//10,(n+50)//10-15,{})['number'],16)
            original=f.tape('unused',start_block=first_block,end_block=n+50)
            self.assertEqual(second,original)
            self.assertGreater(len(first['swaps']),0)

    def test_extended_current_preserves_independent_survivor_eligibility_and_same_asset_owner_fence(self):
        from meme_machine.runtime.sleeve_reservations import SleeveReservations
        for lane in ('pump','pons'):
            with tempfile.TemporaryDirectory() as td:
                sleeve=SleeveReservations(Path(td)/'native.sqlite',lane=lane,capital=10000,
                    policies={'current':'a','survivor':'b'},cohort='original-epoch')
                try:
                    sleeve.reserve('current',strategy='current',amount=100,at=10,asset='asset')
                    before=deepcopy(sleeve.get('current'));at=129610
                    _,action=apply(risk_state(),lane+'_current',at,context(lane+'_current',at))
                    self.assertEqual(action['action'],'hold');self.assertEqual(sleeve.get('current'),before)
                    row=sleeve.observe('asset',strategy='survivor',at=at,state='qualified',
                        evidence={'fresh':True,'survivor_owned_qualification':True},regime={'at':at})
                    self.assertEqual(sleeve.candidate('asset'),row)
                    with self.assertRaisesRegex(ValueError,'same_asset_exposure'):
                        sleeve.reserve('survivor',strategy='survivor',amount=100,at=at,
                            candidate='asset',generation=row['generation'],regime={'at':at})
                    self.assertEqual(sleeve.get('current'),before);self.assertEqual(sleeve.reconcile()['reserved'],100)
                    self.assertEqual(sleeve.identity['cohort'],'original-epoch')
                finally:sleeve.close()
