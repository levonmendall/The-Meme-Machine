import base64
import copy
import json
import struct
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from meme_machine.store import Store, IntegrityError, digest
from meme_machine.engine import Engine, GAS, RENT, LiquidityPosition
from meme_machine.provider import RPC, Unavailable
from meme_machine import pump
from meme_machine.__main__ import replay
from tests.support import *


def with_real_sol(snap, real_sol):
    row=copy.deepcopy(snap)
    raw=bytearray(base64.b64decode(row['accounts'][0]['data'][0]))
    struct.pack_into('<Q',raw,32,int(real_sol))
    row['accounts'][0]['data'][0]=base64.b64encode(raw).decode()
    return row


class Lifecycle(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=str(Path(self.tmp.name)/'paper.db')
        self.store=Store(self.path,'synthetic',100_000_000,'synthetic $100/SOL')
        self.e=Engine(self.store,[SCOUT])
    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()
    def enter(self,now=100):
        nom=self.e.scout([event(now)],now)[0]
        self.assertEqual(self.e.consider(nom,evidence(now),now),'qualified')
        self.assertEqual(self.e.fill(nom['id'],snapshot(now+2),now+2),'settled')
    def test_winning_complete_path(self):
        self.enter()
        self.assertEqual(self.e.monitor(MINT,snapshot(107,sol=65_000_000_000),107),'exit_intended')
        self.assertEqual(self.e.monitor(MINT,snapshot(112,sol=65_000_000_000),112),'settled')
        self.assertGreater(self.store.state['realized'],0)
        self.assertEqual(self.store.state['rent'],0)
        self.assertEqual(self.store.state['cash'],self.store.state['initial']+self.store.state['realized'])
        self.assertTrue(self.store.verify_archive())
    def test_losing_path_and_failed_exit(self):
        self.enter()
        self.assertEqual(self.e.monitor(MINT,snapshot(107,sol=40_000_000_000),107),'exit_intended')
        self.assertEqual(self.e.monitor(MINT,snapshot(112,sol=40_000_000_000),112,failed=True),'exit_failed')
        self.assertIn(MINT,self.store.state['positions'])
        self.assertEqual(self.e.monitor(MINT,snapshot(117,sol=40_000_000_000),117),'settled')
        self.assertLess(self.store.state['realized'],0)
        self.store.reconcile()
    def test_restart_open_and_lost_ack(self):
        self.enter()
        before=copy.deepcopy(self.store.state)
        self.store.close()
        self.store=Store(self.path,'synthetic',100_000_000,'synthetic $100/SOL')
        self.e=Engine(self.store,[SCOUT])
        self.assertEqual(self.e.fill('nomination',snapshot(102),102),'settled')
        self.assertEqual(before,self.store.state)
        self.assertEqual(self.e.monitor(MINT,snapshot(1007),1007),'exit_intended')
        self.assertEqual(self.e.monitor(MINT,snapshot(1012),1012),'settled')
    def test_independent_rejection(self):
        ev=evidence();ev['events']=[]
        self.assertEqual(self.e.consider(event(),ev,100),'independent_demand')
        self.assertEqual(self.store.state['reserved'],0)
    def test_related_buyers_not_independent(self):
        self.e.groups={pump.b58(bytes([i])*32):'same-funder-uncertain' for i in (10,11,12)}
        self.assertEqual(self.e.consider(event(),evidence(),100),'independent_demand')
    def test_stale_future_tax_and_unsupported(self):
        for mutation in ('stale','future','network','token2022','future_event'):
            ev=evidence()
            if mutation=='stale':ev['snapshot']['market_time']=50
            if mutation=='future':ev['snapshot']['available_time']=101
            if mutation=='network':ev['snapshot']['network']='devnet'
            if mutation=='token2022':ev['snapshot']['accounts'][1]['owner']='Token2022'
            if mutation=='future_event':ev['events'][0]['available_time']=101
            self.assertNotEqual(self.e.qualify(event(),ev,100) if mutation=='future_event' else self.e.consider(event(id=mutation),ev,100),'qualified')
    def test_stale_fill_cancel_and_failed_fee(self):
        self.e.consider(event(),evidence(),100)
        self.assertEqual(self.e.fill('nomination',snapshot(100),130),'cancelled')
        self.assertEqual(self.store.state['cash'],self.store.state['initial'])
        self.e.consider(event(id='second'),evidence(),100)
        self.assertEqual(self.e.fill('second',snapshot(102),102,failed=True),'cancelled')
        self.assertEqual(self.store.state['realized'],-GAS)
    def test_duplicate_conflict(self):
        self.assertEqual(len(self.e.scout([event()],100)),1)
        self.assertEqual(self.e.scout([event()],100),[])
        bad=event();bad['amount']+=1
        with self.assertRaisesRegex(ValueError,'conflicting'):
            self.e.scout([bad],100)
    def test_unavailable_exit_unknown_mark(self):
        self.enter()
        self.assertEqual(self.e.monitor(MINT,{},107),'unresolved')
        self.assertIsNone(self.e.status(107)['unrealized_lamports'])
        self.assertIn(MINT,self.store.state['positions'])

    def test_collapsing_pump_liquidity_sets_liquidity_exit_before_sell(self):
        self.enter()
        thin=with_real_sol(snapshot(107),4_000_000_000)
        self.assertEqual(self.e.monitor(MINT,thin,107),'exit_intended')
        position=self.store.state['positions'][MINT]
        self.assertEqual(position['exit_reason'],'liquidity_invalidation')
        self.assertIsNone(position.get('last_exit_error'))

    def test_impossible_full_position_sell_is_explicit_and_not_falsely_settled(self):
        self.enter()
        impossible=with_real_sol(snapshot(107),1)
        self.assertEqual(self.e.monitor(MINT,impossible,107),'unresolved')
        position=self.store.state['positions'][MINT]
        self.assertEqual(position['exit_reason'],'liquidity_invalidation')
        self.assertEqual(position['last_exit_error']['reason'],'insufficient_real_exit_liquidity')
        self.assertIn(MINT,self.store.state['positions'])
        self.assertEqual(self.store.state['funnel']['settled_exits'],0)
        self.assertEqual(self.store.state['counts']['unavailable_exit:insufficient_real_exit_liquidity'],1)
        # Identical failures inside the durable coalescing interval do not write again.
        self.assertEqual(self.e.monitor(MINT,with_real_sol(snapshot(112),1),112),'unresolved_coalesced')
        self.assertEqual(self.store.state['counts']['unavailable_exit:insufficient_real_exit_liquidity'],1)
    def test_shared_capital_and_dlmm_disabled(self):
        self.assertEqual(self.e.allocator.allowed('liquidity',1,MINT,'x'),'dlmm_disabled')
        for i in range(4):
            mint=pump.b58(bytes([30+i])*32);creator=pump.b58(bytes([40+i])*32)
            self.assertEqual(self.e.consider(event(mint=mint,id=str(i)),evidence(mint=mint,creator=creator),100),'qualified')
        self.assertEqual(self.e.consider(event(mint=pump.b58(bytes([50])*32),id='overflow'),evidence(mint=pump.b58(bytes([50])*32)),100),'aggregate_exposure')
        self.store.reconcile()
    def test_checkpoint_corruption(self):
        self.store.db.execute("UPDATE state SET hash='bad'")
        self.store.close()
        with self.assertRaisesRegex(IntegrityError,'checkpoint_hash'):
            Store(self.path,'synthetic',100_000_000,'synthetic $100/SOL')
        # Reopen ownership is released by failed-constructor cleanup/GC.
    def test_archive_corruption(self):
        self.store.db.execute("UPDATE journal SET event='corrupt' WHERE seq=1")
        with self.assertRaisesRegex(IntegrityError,'journal_corruption'):
            self.store.verify_archive()
    def test_reconciliation_detects_balance_damage(self):
        self.store.state['cash']+=1
        with self.assertRaisesRegex(IntegrityError,'capital_conservation'):
            self.store.reconcile()
    def test_synthetic_contamination(self):
        self.store.state['mode']='prospective'
        with self.assertRaisesRegex(ValueError,'contamination'):
            self.e.validate_snapshot(snapshot(),100)
    def test_pressure_keeps_exits(self):
        self.enter()
        self.store.state['entry_count']=100
        self.assertEqual(self.e.allocator.allowed('spot',1,'other','other'),'storage_or_experiment_limit')
        self.assertEqual(self.e.monitor(MINT,snapshot(107,sol=65_000_000_000),107),'exit_intended')
        self.assertEqual(self.e.monitor(MINT,snapshot(112,sol=65_000_000_000),112),'settled')
    def test_replay_is_same_path(self):
        path=Path(self.tmp.name)/'tape.jsonl'
        frames=[dict(now=100,events=[event()],evidence={MINT:evidence()}),
                dict(now=102,snapshots={MINT:snapshot(102)}),
                dict(now=107,snapshots={MINT:snapshot(107,sol=65_000_000_000)}),
                dict(now=112,snapshots={MINT:snapshot(112,sol=65_000_000_000)})]
        path.write_text('\n'.join(json.dumps(f) for f in frames))
        result=replay(self.e,path)
        self.assertGreater(result['realized_lamports'],0)
        self.assertEqual(result['positions'],{})
    def test_process_termination_before_after_commit(self):
        self.store.close()
        for stage in ('before_commit','after_commit'):
            path=str(Path(self.tmp.name)/(stage+'.db'))
            initial=Store(path,'synthetic',100_000_000,'test');initial.close()
            code='''import os,sys
from meme_machine.store import Store
from meme_machine.engine import Engine
from tests.support import *
s=Store(sys.argv[1],'synthetic',100_000_000,'test')
e=Engine(s,[SCOUT])
e.consider(event(),evidence(),100)
s.hook=lambda stage: os._exit(77) if stage==sys.argv[2] else None
e.fill('nomination',snapshot(102),102)
'''
            proc=subprocess.run([sys.executable,'-c',code,path,stage])
            self.assertEqual(proc.returncode,77)
            s=Store(path,'synthetic',100_000_000,'test');e=Engine(s,[SCOUT])
            if stage=='before_commit':self.assertEqual(s.state['orders']['nomination']['status'],'reserved')
            else:self.assertEqual(s.state['orders']['nomination']['status'],'settled')
            self.assertEqual(e.fill('nomination',snapshot(102),102),'settled')
            self.assertEqual(len(s.state['positions']),1)
            s.reconcile();s.close()
        self.store=Store(self.path,'synthetic',100_000_000,'synthetic $100/SOL')


class AdapterTests(unittest.TestCase):
    def test_math_conservative_roundtrip_and_impact(self):
        snap=snapshot();c=pump.curve(snap['accounts'][0]);rates=pump.fees(snap['accounts'][2],c)
        small=pump.buy(c,100_000_000,rates);large=pump.buy(c,1_000_000_000,rates)
        self.assertLess(large[0],small[0]*10)
        out,fee=pump.sell(c,small[0],rates)
        self.assertLess(out,small[1])
        self.assertEqual(small[2],pump.ceildiv((small[1]-small[2])*100,10000))
    def test_known_global_pda(self):
        self.assertEqual(pump.pda([b'global']),'4wTV1YmiEkRvAtNtsSGPtUrqRYQMe5SKy2uB4Jjaxnjf')
    def test_provider_budget_cache_and_readonly(self):
        rpc=RPC('https://example.invalid',limit=42,transport=lambda q:{'result':q['id']})
        self.assertEqual(rpc.call('getGenesisHash'),1)
        self.assertEqual(rpc.call('getGenesisHash'),1)
        rpc.call('getBlockTime',[1])
        with self.assertRaises(Unavailable):rpc.call('getBlockTime',[2])
        self.assertEqual(rpc.call('getBlockTime',[2],priority=True),3)
        for method in ('sendTransaction','requestAirdrop','simulateTransaction'):
            with self.assertRaises(ValueError):rpc.call(method)
    def test_provider_redacts_errors(self):
        def failure(q):raise RuntimeError('SECRET_URL')
        rpc=RPC('https://example.invalid',transport=failure)
        with self.assertRaisesRegex(Unavailable,'^provider_request_failed$'):rpc.call('getGenesisHash')

if __name__=='__main__':unittest.main()
