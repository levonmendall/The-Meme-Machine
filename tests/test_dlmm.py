import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from meme_machine import dlmm,pump
from meme_machine.dlmm_paper import (Replay,RESERVATION,CAPITAL,ENTRY_COST,EXIT_COST,RENT,
    prospective_reserve,monitoring_tick,inventory)
from meme_machine.store import Store,IntegrityError,digest
from meme_machine.provider import RPC,Unavailable
from meme_machine.engine import Engine,Allocator
from tests.support import SCOUT,event as pump_event,evidence,snapshot as pump_snapshot,MINT
from tests.dlmm_support import snapshot,event,change_account,POOL,VAULT_X


class Protocol(unittest.TestCase):
    def test_decoders_and_price(self):
        p=dlmm.validate(snapshot(),100)
        self.assertEqual(p['active'],0);self.assertEqual(len(p['bins']),140)
        self.assertEqual(p['bins']['-1']['y'],200_000_000)
        self.assertEqual(dlmm.price(0,10),1<<64)
        self.assertEqual(dlmm.array_address(POOL,-1),dlmm.array_address(POOL,-1))
        for bid in (-1000,-2,-1,1,2,1000):self.assertGreater(dlmm.price(bid,10),0)

    def test_fee_and_single_multi_bin(self):
        p=dlmm.validate(snapshot(),100)
        self.assertEqual(dlmm.total_fee(p),1_000_000)
        one,q=dlmm.swap(p,1_000_000,True,101)
        self.assertEqual((q['output'],q['fee'],q['protocol_fee']),(999000,1000,200))
        self.assertEqual(one['bins']['0']['x'],200_999_000)
        self.assertEqual(p['bins']['0']['x'],200_000_000)
        many,q=dlmm.swap(p,450_000_000,True,101)
        self.assertEqual([t['bin'] for t in q['traversed']],[0,-1,-2])
        self.assertEqual(many['bins']['-1']['y'],0)
        self.assertGreater(q['fee'],450000)  # volatility grows during traversal

    def test_supported_scope_and_identity_fail_closed(self):
        base=snapshot()
        cases=[change_account(base,POOL,82,b'\1'),change_account(base,POOL,36,b'\1'),
            change_account(base,POOL,120,pump.un58(SCOUT)),
            change_account(base,POOL,880,b'\1'),
            change_account(base,VAULT_X,32,pump.un58(SCOUT)),
            change_account(base,dlmm.array_address(POOL,-1),24,pump.un58(SCOUT)),
            change_account(change_account(base,dlmm.array_address(POOL,-1),16,b'\3'),dlmm.array_address(POOL,-1),56+112,b'\1')]
        for s in cases:
            with self.subTest(s=digest(s)),self.assertRaises((ValueError,KeyError)):dlmm.validate(s,100)
        with self.assertRaises(ValueError):dlmm.scout(base,121)
        with self.assertRaises(ValueError):dlmm.scout(base,99)
        with self.assertRaises(ValueError):dlmm.scout(base,100,dict(pool=POOL,x=SCOUT,y=dlmm.WSOL))
        del base['accounts'][dlmm.array_address(POOL,0)]
        with self.assertRaises(KeyError):dlmm.validate(base,100)

    def test_scout_non_authoritative_and_missing_research_explicit(self):
        candidate=dlmm.scout(snapshot(),100)
        self.assertFalse(candidate['allocation_eligible'])
        self.assertIsNone(candidate['research']['volume'])
        self.assertEqual(candidate['pool'],POOL)
        with self.assertRaises(PermissionError):prospective_reserve(candidate,enabled=True)

    def test_provider_reuses_finalized_budget(self):
        snap=snapshot();calls=[]
        def transport(req):
            calls.append(req);method=req['method']
            if method=='getGenesisHash':result=pump.MAINNET
            elif method=='getBlockTime':result=100
            else:
                self.assertEqual(req['params'][1]['commitment'],'finalized')
                result=dict(context=dict(slot=100),value=[snap['accounts'].get(k) for k in req['params'][0]])
            return dict(result=result)
        rpc=RPC('https://test.invalid',transport=transport,clock=lambda:100)
        adapter=dlmm.Adapter(rpc);out=adapter.snapshot(POOL,100)
        self.assertEqual(dlmm.validate(out,100)['pool'],POOL)
        self.assertEqual(rpc.calls,4)
        self.assertLessEqual(len(rpc.cache),128)
        with self.assertRaises(Unavailable):adapter.swap_history(POOL,[100,0,0])
        with self.assertRaises(ValueError):adapter.discover([POOL]*5,100)

    def test_missing_traversal_does_not_modify_input(self):
        p=dlmm.validate(snapshot(),100);before=digest(p)
        with self.assertRaises(Unavailable):dlmm.swap(p,100_000_000_000,True,101)
        self.assertEqual(before,digest(p))


class Lifecycle(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'paper.db'
        self.s=Store(self.path,'synthetic',100_000_000,'DLMM synthetic')
        self.r=Replay(self.s)

    def tearDown(self):
        self.s.close();self.tmp.cleanup()

    def reopen(self):
        old=digest(self.s.state);self.s.close()
        self.s=Store(self.path,'synthetic',100_000_000,'DLMM synthetic');self.r=Replay(self.s)
        self.assertEqual(old,digest(self.s.state));self.assertTrue(self.s.reconcile());self.assertTrue(self.s.verify_archive())

    def enter(self,sol_x=False):
        s=snapshot(sol_x=sol_x);self.r.reserve('lp',s,100);return self.r.deposit('lp',s,100)

    def test_connected_lifecycle_restart_every_stage_and_no_double_release(self):
        initial=self.s.state['initial'];snap=snapshot()
        self.r.reserve('lp',snap,100);self.reopen()
        self.assertEqual(self.s.state['cash'],initial-RESERVATION)
        p=self.r.deposit('lp',snap,100);self.reopen()
        self.assertEqual(p['initial_y'],CAPITAL);self.assertEqual(p['initial_x'],0)
        self.assertEqual(p['lower'],-2);self.assertEqual(p['upper'],-1)
        e=event(p,450_000_000);self.r.process('lp',e);self.reopen()
        p=self.s.state['liquidity_positions']['lp']
        self.assertGreater(p['inventory']['x'],0);self.assertGreater(p['inventory']['fee_x'],0)
        before=digest(self.s.state)
        with self.assertRaises(ValueError):self.r.process('lp',e)
        self.assertEqual(digest(self.s.state),before)
        self.r.process('lp',event(p,800_000_000));self.reopen()
        p=self.s.state['liquidity_positions']['lp'];self.assertEqual(p['range_state'],'out_of_range')
        self.assertEqual(p['inventory']['y'],0)
        now=p['last_time'];mark=self.r.mark('lp',now)
        self.assertTrue(mark['resolved']);self.assertGreater(mark['token_input'],0)
        self.assertEqual(mark['token_input'],mark['liquidation']['input'])
        self.r.exit_intent('lp','test_exit',now);self.reopen()
        assets=self.r.withdraw('lp',now);self.reopen()
        self.assertEqual(assets,inventory(self.s.state['liquidity_positions']['lp']))
        with self.assertRaises(ValueError):self.r.withdraw('lp',now)
        settlement=self.r.settle('lp',now);self.reopen()
        self.assertEqual(settlement['realized'],settlement['sol']-CAPITAL-ENTRY_COST-EXIT_COST)
        self.assertEqual(self.s.state['cash'],initial+settlement['realized'])
        self.assertEqual(self.s.state['rent'],0);self.assertEqual(self.s.state['reserved'],0)
        self.assertEqual(settlement['costs'],ENTRY_COST+EXIT_COST)
        with self.assertRaises(ValueError):self.r.settle('lp',now)
        with self.assertRaises(ValueError):self.r.reserve('lp',snap,100)

    def test_sol_x_orientation(self):
        p=self.enter(True);self.assertEqual(p['initial_y'],0)
        self.r.process('lp',event(p,450_000_000,False));p=self.s.state['liquidity_positions']['lp']
        self.assertGreater(p['inventory']['y'],0);self.assertGreater(p['inventory']['fee_y'],0)
        self.assertTrue(self.r.mark('lp',101)['resolved'])
        self.r.exit_intent('lp','test',101);self.r.withdraw('lp',101);self.r.settle('lp',101)
        self.assertTrue(self.s.reconcile())

    def test_stale_missing_mark_does_not_free_capital(self):
        p=self.enter();before=self.s.state['cash']
        self.assertFalse(self.r.mark('lp',121)['resolved'])
        self.r.unresolved('lp','missing finalized history',101)
        seq=self.s.state['journal_seq'];self.r.unresolved('lp','missing finalized history',102)
        self.assertEqual(seq,self.s.state['journal_seq'])
        self.assertIsNone(self.r.mark('lp',102)['net_sol'])
        self.r.exit_intent('lp','test',102)
        with self.assertRaises(Unavailable):self.r.withdraw('lp',102)
        self.assertEqual(self.s.state['cash'],before);self.reopen()

    def test_fixed_horizon_exit_and_unavailable_liquidation(self):
        p=self.enter();self.r.process('lp',event(p,450_000_000,now=160))
        status=self.r.monitor('lp',160)
        self.assertTrue(status['mark']['resolved'])
        self.assertEqual(self.s.state['liquidity_positions']['lp']['exit_reason'],'fixed_mechanical_horizon')
        self.r.withdraw('lp',160);before=self.s.state['cash']
        with patch('meme_machine.dlmm.swap',side_effect=Unavailable('dlmm_missing_traversal_bins')):
            self.assertIsNone(self.r.mark('lp',160)['net_sol'])
            with self.assertRaises(Unavailable):self.r.settle('lp',160)
        self.assertEqual(self.s.state['cash'],before)
        self.r.settle('lp',160);self.reopen()

    def test_gap_future_real_event_and_observed_totals_rejected(self):
        p=self.enter();e=event(p);before=digest(self.s.state)
        with self.assertRaisesRegex(ValueError,'future'):self.r.process('lp',e,now=100)
        cases=[]
        for key,value in [('previous_cursor',[99,0,0]),('prestate_hash','wrong'),('kind','real'),
                          ('pool',SCOUT),('commitment','confirmed'),('time',99)]:
            v=copy.deepcopy(e);v[key]=value;cases.append(v)
        v=copy.deepcopy(e);v['observed']['fee']+=1;cases.append(v)
        for v in cases:
            with self.subTest(v=v),self.assertRaises((ValueError,Unavailable)):self.r.process('lp',v)
            self.assertEqual(digest(self.s.state),before)

    def test_shared_pump_bankroll_and_insufficient_capital(self):
        eng=Engine(self.s,[SCOUT])
        # Distinct token: Pump reserves and fills its normal unchanged 5% budget.
        mint=pump.b58(bytes([55])*32)
        self.assertEqual(eng.consider(pump_event(mint=mint),evidence(mint=mint),100),'qualified')
        eng.fill('nomination',pump_snapshot(102,mint=mint),102)
        cash=self.s.state['cash'];self.enter()
        self.assertEqual(self.s.state['cash'],cash-RESERVATION)
        self.assertTrue(self.s.reconcile());self.reopen()
        # A different initial SOL valuation legitimately makes fixed test capital unaffordable.
        with tempfile.TemporaryDirectory() as d:
            s=Store(Path(d)/'s.db','synthetic',10_000_000_000_000,'tiny SOL genesis')
            try:
                with self.assertRaisesRegex(ValueError,'capital'):Replay(s).reserve('lp',snapshot(),100)
                self.assertEqual(s.state['initial'],s.state['cash'])
            finally:s.close()

    def test_cancel_restart_and_duplicate_cancellation(self):
        self.r.reserve('lp',snapshot(),100);self.reopen();self.r.cancel('lp');self.reopen()
        self.assertEqual(self.s.state['cash'],self.s.state['initial'])
        with self.assertRaises(ValueError):self.r.cancel('lp')

    def test_atomic_rollback_and_lost_ack(self):
        p=self.enter();e=event(p);before=digest(self.s.state)
        def fail(stage):
            if stage=='before_commit':raise RuntimeError('crash')
        self.s.hook=fail
        with self.assertRaises(RuntimeError):self.r.process('lp',e)
        self.assertEqual(before,digest(self.s.state));self.s.hook=lambda stage:None;self.reopen()
        def lost(stage):
            if stage=='after_commit':raise RuntimeError('lost ack')
        self.s.hook=lost
        with self.assertRaises(RuntimeError):self.r.process('lp',e)
        self.s.hook=lambda stage:None;self.reopen()
        with self.assertRaises(ValueError):self.r.process('lp',e)

    def test_monitor_precedes_discovery_and_records_unresolved(self):
        self.enter();calls=[]
        class Adapter:
            def snapshot(self,*args,**kwargs):calls.append(('monitor',kwargs['priority']))
            def swap_history(self,*args,**kwargs):raise Unavailable('gap')
            def discover(self,*args):calls.append(('discovery',False))
        out=monitoring_tick(self.s,Adapter(),101,[POOL])
        self.assertEqual(calls,[('monitor',True)]);self.assertTrue(out['discovery_deferred'])
        self.assertFalse(self.r.mark('lp',101)['resolved'])

    def test_invariant_detects_forged_shares_and_authority(self):
        self.enter()
        with self.assertRaises(IntegrityError):
            with self.s.transaction('invalid') as s:s['dlmm_allocation_enabled']=True
        with self.assertRaises(IntegrityError):
            with self.s.transaction('invalid') as s:s['liquidity_positions']['lp']['shares']['-1']=10**100
        self.assertTrue(self.s.reconcile())


class Authority(unittest.TestCase):
    def test_prospective_every_entry_path_disabled(self):
        with tempfile.TemporaryDirectory() as d:
            s=Store(Path(d)/'live.db','prospective',100_000_000,'test')
            try:
                before=digest(s.state)
                with self.assertRaises(PermissionError):Replay(s)
                with self.assertRaises(PermissionError):prospective_reserve(s,dlmm.scout(snapshot(),100))
                replay=object.__new__(Replay);replay.store=s
                with self.assertRaises(PermissionError):replay.reserve('x',snapshot(),100)
                with self.assertRaises(PermissionError):replay.deposit('x',snapshot(),100)
                self.assertEqual(before,digest(s.state))
                self.assertEqual(Allocator(s).allowed('dlmm',1,MINT,'test'),'dlmm_disabled')
                self.assertFalse(dlmm.DLMM_ALLOCATION_ENABLED)
                with patch.object(dlmm,'DLMM_ALLOCATION_ENABLED',True):
                    with self.assertRaises(PermissionError):prospective_reserve(s,enabled=True)
            finally:s.close()
