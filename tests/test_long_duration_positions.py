"""Owner-approved age-independent native holding; all market facts offline."""
from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from meme_machine.runtime.survivor_commit import monitor,restore_risk
from meme_machine.runtime.directional_continuation import BRIDGE_GATES
from meme_machine.lanes.pump.pump_acceleration_paper import PumpAccelerationPaperLifecycle
from meme_machine.lanes.pump.pump_acceleration_strategy import MODE_LATE_CURVE,MODE_POSTGRAD,MODE_SECOND_LEG
from tests import test_exceptional_winner_candidate as fixtures
observation=fixtures.observation
from tests import test_position_continuation as operational_fixtures
envelope=operational_fixtures.envelope

AGES=(300,600,900,1800,36*3600,72*3600,96*3600,7*86400,14*86400,30*86400)
MULTIPLES=(1,1.1,2,5,10,25,50,100,1000)


class SourceDeltaTests(unittest.TestCase):
    def test_reviewed_stale_helper_changes_only_adverse_guard_and_confirmation_order(self):
        import ast,subprocess
        from tests.test_robinhood_usd_valuation import assert_holding_delta,opportunity_predecessor
        path='meme_machine/lanes/pons/pons_postgrad_survivor.py'
        original=subprocess.check_output(['git','show','fe7524586217c44f18fd8d39614897b2cc5f169b:'+path])
        expected=ast.parse(original)
        helper=next(n for n in expected.body if isinstance(n,ast.FunctionDef) and n.name=='exit_action')
        confirmation=next(n for n in helper.body if isinstance(n,ast.If) and isinstance(n.test,ast.Name) and n.test.id=='soft')
        stale=next(n for n in helper.body if isinstance(n,ast.If) and
            any(isinstance(v,ast.Constant) and v.value=='stale_thesis' for v in ast.walk(n)))
        helper.body.remove(confirmation)
        self.assertIsInstance(stale.test,ast.BoolOp);self.assertIsInstance(stale.test.op,ast.And)
        stale.test.values.insert(0,ast.Name(id='soft',ctx=ast.Load()))
        helper.body.insert(helper.body.index(stale)+1,confirmation)
        current=Path(path).read_text()
        # Independent review of the entire module, including original constants,
        # policy identity, qualification and every other function/interface.
        self.assertEqual(ast.dump(expected),ast.dump(ast.parse(
            opportunity_predecessor(self,path,current.encode()))))
        assert_holding_delta(self,path,original,current)
        for mutation in (current.replace('soft and int(hold_seconds)','int(hold_seconds)'),
                         current.replace('current<=x["hard_stop_bps"]','current<x["hard_stop_bps"]')):
            with self.assertRaises(AssertionError):assert_holding_delta(self,path,original,mutation)


class CurrentLongHoldTests(unittest.TestCase):
    pump=fixtures.NativeCurrentTests.pump
    pump_mark=fixtures.NativeCurrentTests.pump_mark

    def test_actual_pons_current_native_owners_resume_and_hold_through_thirty_days(self):
        from tests import test_pons_current_shared_owners as owners
        for seconds in AGES[4:]:
            f=owners.CurrentSharedOwnerTests();self.addCleanup(f.doCleanups)
            results,rpcs,trace=f.run_owners(2,sharing=True,paced=True,latency=.1,holding_seconds=seconds)
            self.assertTrue(all(r['final_position']['status']=='open' for r in results))
            self.assertTrue(all(r['monitor'][0]['action']['action']=='hold' for r in results))
            self.assertEqual(sum(len(r.transports) for r in rpcs),4)
            self.assertLess(trace['complete_modeled_with_local_seconds'],5)
            self.assertTrue(all(r['reconciliation']['cash_basis_conservation'] for r in results))

    def test_original_pump_current_lot_survives_every_boundary_and_gain_stratum(self):
        from tests.lanes.pump.test_pump_acceleration_paper import qualification
        from meme_machine.lanes.pump.pump_acceleration_strategy import POLICY
        for mode in (MODE_LATE_CURVE,MODE_POSTGRAD,MODE_SECOND_LEG):
            for multiple in MULTIPLES:
                gain=round((multiple-1)*10000)
                life,book=self.pump(gain=gain)
                # This fixture's actual entry is postgrad; both other mode
                # reducers are additionally exercised on their native surface.
                if mode!=MODE_POSTGRAD:
                    life=PumpAccelerationPaperLifecycle()
                    life.reserve(replace(qualification(),mode=mode),1000,100)
                    life.fill(tokens=100,cost_quote_units=1000,now=102,surface='pump.fun' if mode==MODE_LATE_CURVE else 'pumpswap')
                original=life.position.opened_at;quantity=life.position.tokens
                for age in AGES:
                    p=life.position
                    result=life.mark(p.basis_quote_units*(10000+gain)//10000,102+age,
                        demand_score=80,postgrad_demand_confirmed=True)
                    self.assertIsNone(result['exit_reason'],(mode,multiple,age))
                    if result['partial_harvest_bps']:
                        sold=p.tokens//4
                        life.harvest(sold,sold*10*(10000+gain)//10000,103+age)
                    if mode==MODE_POSTGRAD:
                        life=PumpAccelerationPaperLifecycle.restore(book,'run:x')
                        self.assertTrue(book.replay()['verified'])
                    self.assertEqual(life.position.opened_at,original)
                    self.assertEqual(life.position.original_basis,1000)
                    self.assertIsNone(life.position.exit_reason)
                self.assertGreater(life.position.tokens,0)
                if gain<POLICY.first_profit_bps:self.assertEqual(life.position.tokens,quantity)
                last=102+AGES[-1]+5
                self.assertEqual(life.mark(life.position.basis_quote_units*7//10,last,80)['exit_reason'],'risk_stop')

    def test_pons_current_original_owner_and_accounting_survive_pregrad_and_runner_boundaries(self):
        from tests.test_continuation_resource_efficiency import LongHoldStorageTests
        from meme_machine.lanes.pons.pons_selective_continuation import POLICY_HASH,runner_action,pregraduation_action
        from meme_machine.lanes.pons.pons_selective_recovery import LifecycleState
        from meme_machine.lanes.pons.pons_selective_paper import _bridge_action
        from meme_machine.lanes.pons.pons_selective_ledger import SelectivePaper,STRATEGY_NAMESPACE
        from meme_machine.lanes.pons.evidence import Store
        for multiple in MULTIPLES:
            f=LongHoldStorageTests();f.setUp();self.addCleanup(f.doCleanups);p=f.fill();gain=round((multiple-1)*10000)
            ev=dict(token='token',curve='m',source_transaction='fixture',market_events=[],
                candidate=dict(curve='m',token='token',auth={'fixture':True},record={}),
                vector=dict(current_threshold_pass=True,policy_hash=POLICY_HASH,trajectory={'graduation_eta_seconds':100},demand={'largest_buyer_flow_bps':100}))
            state=LifecycleState.create(f.store,'x',ev,10000,21000,opened_at=102,last_block=1020)
            f.paper.controller_context=state.checkpoint
            for age in AGES:
                at=102+age;f.clock[0]=at;state.high_water=max(state.high_water,gain)
                native=runner_action(tokens=p['tokens'],partial_taken=state.partial_taken,
                    after_cost_return_bps=gain,high_water_return_bps=gain,seconds_since_high=0,
                    new_buyer_growth=1,buy_quote=300,sell_quote=100)
                pre=pregraduation_action(tokens=p['tokens'],partial_taken=state.partial_taken,
                    elapsed_seconds=age,frozen_eta_seconds=100,trajectory=dict(complete=True,recent_progress_bps=1,accelerating=True),
                    demand=dict(current_buy_quote=300,current_sell_quote=100),after_cost_return_bps=gain,high_water_return_bps=gain)
                self.assertNotEqual(pre['action'],'full_exit',(age,multiple,pre))
                action=_bridge_action(state,{},native,p,now=at)
                self.assertNotEqual(action['action'],'full_exit',(age,multiple,action))
                state.remember_action(action,p)
                q,ledger=f.quote(at,'sell',p['tokens'],max(3,p['remaining_cost']*(10000+gain)//10000+2))
                p=f.paper.advance('x',now=at,action='mark',quote=q,finality_ledger=ledger)
                if action['action']=='partial_exit':
                    p=f.paper.advance('x',now=at,action='exit_intent',exit_tokens=action['exit_tokens'])
                    f.clock[0]=at+2;q,ledger=f.quote(at+2,'sell',action['exit_tokens'],max(3,action['exit_tokens']*(10000+gain)//100000+2),label='selective-v4-exit')
                    p=f.paper.advance('x',now=at+2,action='exit',quote=q,finality_ledger=ledger);state.acknowledge(p)
                before=f.paper.reconcile();f.store.close();f.store=Store(f.path,max_records=8192)
                f.paper=SelectivePaper(f.store,STRATEGY_NAMESPACE,10000,natural_policy_hash=POLICY_HASH,clock_ns=lambda:int(f.clock[0]*10**9))
                state=LifecycleState.restore(f.paper,'x');f.paper.controller_context=state.checkpoint;p=f.paper._get('x')
                self.assertEqual(f.paper.reconcile(),before);self.assertEqual(state.opened_at,102)
                self.assertEqual(p['status'],'open');self.assertEqual(p['cost'],102)
                self.assertGreater(p['tokens'],0)
            self.assertTrue(f.paper.reconcile()['cash_basis_conservation'])


class SurvivorLongHoldTests(unittest.TestCase):
    native=fixtures.NativeSurvivorTests.native

    def test_actual_pump_survivor_controller_keeps_healthy_below_two_times_owner(self):
        from types import SimpleNamespace
        from meme_machine.lanes.pump.pumpswap_survivor_runtime import Runtime
        f=self.native('pump_survivor');r=Runtime.__new__(Runtime);r.book=f.book;r.sleeve=f.sleeve
        row=dict(id='mint',position='run:one',generation=1)
        r.history=SimpleNamespace(save=lambda value:None);r.now=lambda:f.adapter.at
        r.fresh_state=lambda *args,**kwargs:dict(slot=f.adapter.at,market_time=f.adapter.at,available_time=f.adapter.at)
        r.reconstruct=lambda *args,**kwargs:dict(now=f.adapter.at,creator_distribution_safe=True,
            demand_events=[dict(at=f.adapter.at,buy=True,quote=100,group='organic',authenticated=True,id='fresh:'+str(f.adapter.at))])
        r.exit_quote=lambda qty,**kwargs:dict(quantity=qty,net_proceeds=110,market_time=f.adapter.at,acquired=f.adapter.at)
        for age in AGES:
            f.adapter.at=10+age;r._position(row,admit=False);f.reopen();r.book=f.book;r.sleeve=f.sleeve
            self.assertEqual(f.book._load('run:one')['tokens'],400)
            self.assertEqual(restore_risk(f.book,'run:one')['opened_at'],10)
            self.assertTrue(row['position_safety']['evidence_current']);self.assertFalse(row['position_safety']['pending_exit'])

    def test_actual_paced_pons_survivor_controller_holds_a_thirty_day_original_lot(self):
        from tests import test_pons_protective_capacity as capacity
        from tests import test_pons_shared_native_acquisition as sharing
        f=sharing.SharedNativeAcquisitionTests();self.addCleanup(f.doCleanups)
        def old_position(r,rpc):
            rpc.clock=96+30*86400;at=int(rpc.clock);value=rpc.value
            def fresh_block(method,params):
                result=value(method,params)
                if method=='eth_getBlockByNumber' and int(result['number'],16)==101:
                    result['timestamp']=hex(at)
                return result
            rpc.value=fresh_block
        positions,risks,rpc,result=capacity.replay(f,2,price_factor=1.1,before_step=old_position)
        self.assertTrue(all(p['status']=='open' for p in positions))
        self.assertTrue(all(r['opened_at']==96 and r['last_action']['action']=='hold' for r in risks))
        self.assertEqual(len(rpc.starts),4);self.assertTrue(f.native_runtime.book.replay()['verified'])
        self.assertTrue(all(row['evidence_current'] for row in result['position_safety']))

    def test_native_survivors_hold_every_boundary_without_profit_or_renewal_permission(self):
        from meme_machine.lanes.pump.pumpswap_survivor import POLICY
        from meme_machine.lanes.pons.pons_postgrad_survivor import risk_policy
        for family,policy in (('pump_survivor',POLICY['exits']),('pons_survivor',risk_policy())):
            for multiple in MULTIPLES:
                f=self.native(family);gain=round((multiple-1)*10000)
                for age in AGES:
                    f.adapter.at=10+age;f.adapter.proceeds=32
                    obs=observation(f.adapter.at,gain);obs['net_exit_proceeds']=100*(10000+gain)//10000
                    action=monitor(book=f.book,sleeve=f.sleeve,identity='run:one',observation=obs,policy=policy,adapter=f.adapter)
                    self.assertNotIn(action['action'],('full_exit','exit_pending'),(family,multiple,age))
                    f.reopen();risk=restore_risk(f.book,'run:one')
                    self.assertEqual((risk['opened_at'],risk['original_quantity'],risk['original_basis']),(10,400,100))
                    self.assertEqual(f.book._load('run:one')['status'],'open');self.assertTrue(f.book.replay()['verified'])
                    self.assertTrue(f.sleeve.reconcile()['reconciled'])
                f.adapter.at+=3;f.adapter.quote_available=False
                action=monitor(book=f.book,sleeve=f.sleeve,identity='run:one',
                    observation=observation(f.adapter.at,policy['hard_stop_bps']),policy=policy,adapter=f.adapter)
                self.assertEqual(action,dict(action='exit_pending',reason='hard_stop'));f.reopen()
                f.adapter.at+=3;f.adapter.quote_available=True;f.adapter.proceeds=90
                action=monitor(book=f.book,sleeve=f.sleeve,identity='run:one',
                    observation=observation(f.adapter.at,gain),policy=policy,adapter=f.adapter)
                self.assertEqual(action['reason'],'hard_stop');self.assertEqual(f.book._load('run:one')['status'],'settled')


class MaintenanceTests(unittest.TestCase):
    fixture=operational_fixtures.LifecycleTests.fixture;native_position=operational_fixtures.LifecycleTests.native_position;service=operational_fixtures.LifecycleTests.service

    def resources(self):
        r=envelope();r.update(schema='paper-position-maintenance-resources-v2',maximum_seconds=None,holding_time_exit=False,cumulative_usage=True)
        return r

    def test_exhaustion_uses_only_original_recovery_reserve_then_preserves_open_owner(self):
        from meme_machine.operational.position_continuation import tick,position_only
        from meme_machine.operational.bounded_provider import CeilingReached,PhaseBudget
        r=self.resources();r['continuation']['rpc_elements']=1;r['recovery']['rpc_elements']=1
        root,a,now,s=self.service(resources=r);book,_,identity=self.native_position(root,now,survivor=True)
        s.last_native_health['pump']['native_continuation']['flat']=False;before=deepcopy(book._load(identity))
        with patch('time.time',return_value=now+1800):tick(s)
        endpoint='https://robinhood-mainnet.g.alchemy.com/v2/offline';call=[dict(method='eth_gasPrice')]
        with patch('time.time',return_value=now+1800):
            s.provider_budget.reserve_http(endpoint,call)
            s.provider_budget.reserve_http(endpoint,call)
            self.assertEqual(s.provider_budget.phase(),'RECOVERY')
            with self.assertRaises(CeilingReached):s.provider_budget.reserve_http(endpoint,call)
        used=s.provider_budget.usage()['phases'];self.assertEqual(used['continuation']['rpc_elements'],'1')
        self.assertEqual(used['recovery']['rpc_elements'],'1');self.assertEqual(s.provider_budget.phase(),'FAULT')
        self.assertTrue(position_only(path=s.provider_budget.path,now=now+1800))
        resumed=PhaseBudget(s.provider_budget.path)
        with self.assertRaises(CeilingReached):resumed.reserve_http(endpoint,call)
        self.assertEqual(resumed.usage()['phases'],used);self.assertEqual(book._load(identity),before);a.verify_replay()

    def test_original_usage_and_owner_survive_thirty_days_and_restart_without_replenishment(self):
        from meme_machine.operational.position_continuation import tick
        from meme_machine.operational.bounded_provider import PhaseBudget
        from meme_machine.operational.supervisor import Supervisor
        r=self.resources();root,a,now,s=self.service(resources=r);book,_,identity=self.native_position(root,now,survivor=True)
        s.last_native_health['pump']['native_continuation']['flat']=False
        before=deepcopy(book._load(identity));path=root/'resources.json';path.write_text(json.dumps(r))
        with patch('time.time',return_value=now+1800):tick(s)
        s.provider_budget.reserve_http('https://robinhood-mainnet.g.alchemy.com/v2/offline',[dict(method='eth_getBlockByNumber')])
        used=s.provider_budget.usage()['phases']['continuation']['rpc_cu']
        for age in AGES[4:]:
            with patch('time.time',return_value=now+age):tick(s)
            self.assertFalse(s.stop_requested);self.assertEqual(s.provider_budget.phase(),'CONTINUATION')
            self.assertEqual(book._load(identity),before)
        resumed=Supervisor(root,offline=True,admission='BOOTSTRAP');resumed.shared_capital=a
        with patch.dict(os.environ,MM_POSITION_CONTINUATION_ENVELOPE=str(path)),patch('time.time',return_value=now+30*86400+1):resumed.configure_admission()
        self.assertEqual(resumed.provider_budget.usage()['phases']['continuation']['rpc_cu'],used)
        self.assertEqual(resumed.runtime_lanes(),('pump',));self.assertEqual(book._load(identity),before);a.verify_replay()
        self.assertEqual(PhaseBudget(s.provider_budget.path).envelope,r)

    def test_cumulative_spending_and_bounded_incident_fault_do_not_sell_or_renew_allowance(self):
        from meme_machine.operational.position_continuation import tick,provider_failure
        from meme_machine.operational.bounded_provider import CeilingReached,PhaseBudget
        r=self.resources();root,a,now,s=self.service(resources=r);book,_,identity=self.native_position(root,now,survivor=True)
        before=deepcopy(book._load(identity))
        with patch('time.time',return_value=now+30*86400):
            provider_failure(s,'provider_unavailable')
        self.assertEqual(s.provider_budget.usage()['provider_fault']['state'],'DEGRADED_PROTECTION')
        with patch('time.time',return_value=now+30*86400+3600):
            provider_failure(s,'provider_unavailable');tick(s)
        self.assertTrue(s.stop_requested);self.assertEqual(s.provider_budget.fault()['state'],'OPERATIONAL_FAULT')
        self.assertEqual(book._load(identity),before);self.assertFalse(s.provider_budget.fault()['protected'])
        with self.assertRaises(CeilingReached):PhaseBudget(s.provider_budget.path).reserve_http('https://robinhood-mainnet.g.alchemy.com/v2/offline',[dict(method='eth_gasPrice')])
        a.verify_replay()
