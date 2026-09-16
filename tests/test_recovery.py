import copy
import json
import tempfile
import unittest
from pathlib import Path
from meme_machine.store import Store,IntegrityError
from meme_machine.engine import Engine
from meme_machine.wallets import observe
from meme_machine.__main__ import tick
from tests.support import *


class Recovery(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=str(Path(self.tmp.name)/'state.db')
        self.s=Store(self.path,'synthetic',100_000_000,'test');self.e=Engine(self.s,[SCOUT])
    def tearDown(self):self.s.close();self.tmp.cleanup()
    def test_duplicate_with_later_ingestion_is_same_economic_event(self):
        self.e.scout([event()],100)
        e=event();e['available_time']=101
        self.assertEqual(self.e.scout([e],101),[])
    def test_no_reseed_or_configuration_drift(self):
        with self.assertRaisesRegex(RuntimeError,'writer_already'):
            Store(self.path,'synthetic',100_000_000,'test')
        self.s.close()
        with self.assertRaisesRegex(IntegrityError,'genesis_mismatch'):
            Store(self.path,'synthetic',200_000_000,'changed')
        self.s=Store(self.path,'synthetic',100_000_000,'test')
        self.assertEqual(self.s.state['initial'],5_000_000_000)
        with self.assertRaisesRegex(ValueError,'configuration_changed'):
            Engine(self.s,[])
    def test_reservation_restart_and_related_limit(self):
        self.assertEqual(self.e.consider(event(),evidence(),100),'qualified')
        other=pump.b58(bytes([40])*32)
        self.assertEqual(self.e.consider(event(mint=other,id='other'),evidence(mint=other),100),'related_exposure')
        self.s.close();self.s=Store(self.path,'synthetic',100_000_000,'test');self.e=Engine(self.s,[SCOUT])
        self.assertEqual(self.e.fill('nomination',snapshot(102),102),'settled')
        self.s.reconcile()
    def test_future_finality_wait_does_not_fill_earlier_price(self):
        self.e.consider(event(),evidence(),100)
        self.assertEqual(self.e.fill('nomination',snapshot(101),102),'waiting')
        self.assertEqual(self.s.state['positions'],{})
        self.assertEqual(self.e.fill('nomination',snapshot(105,sol=65_000_000_000),105),'cancelled')
        self.assertEqual(self.s.state['positions'],{})
    def test_wallet_transfers_and_partial_sells_not_profit(self):
        w={};observe(w,event())
        sold=event(now=101,buy=False);sold['tokens']//=2
        observe(w,sold)
        self.assertIsNone(w['episodes'][MINT]['return_lamports'])
        transfer=event(now=102);transfer['type']='transfer';observe(w,transfer)
        self.assertEqual(w['episodes'][MINT]['inventory_boundary'],'transfer_or_airdrop')
        self.assertEqual(w['sizing_influence'],0)
        self.assertIsNone(w['episodes'][MINT]['follower_return'])
    def test_exit_scheduler_runs_without_new_wallet_trade(self):
        self.e.consider(event(),evidence(),100);self.e.fill('nomination',snapshot(102),102)
        class FakeRPC:
            calls=0;failures=0;cache_hits=0;limit=120
        class Adapter:
            rpc=FakeRPC()
            def snapshot(inner,mint,now,priority=False):
                self.assertTrue(priority)
                return snapshot(int(__import__('time').time()),sol=40_000_000_000)
            def history(inner,wallet,now):return [],True
        # real tick's processing time must be used for fixture availability.
        now=int(__import__('time').time())
        tick(self.e,Adapter(),now)
        self.assertIsNotNone(self.s.state['positions'][MINT]['exit_due'])
    def test_no_free_cash_on_missing_mark(self):
        self.e.consider(event(),evidence(),100);self.e.fill('nomination',snapshot(102),102)
        cash=self.s.state['cash'];self.e.monitor(MINT,{},107)
        self.assertEqual(self.s.state['cash'],cash)
        self.assertIsNone(self.e.status(107)['unrealized_lamports'])
    def test_liquidity_interface_cannot_bypass_shared_allocator(self):
        self.assertEqual(self.e.allocator.allowed('liquidity',self.s.state['initial']*10,'x','x'),'dlmm_disabled')
        self.assertEqual(self.s.state['reserved'],0)
    def test_transient_discovery_gap_quarantines_only_missing_signal_window(self):
        self.e.scout([],100)
        with self.s.transaction('test_gap'):
            self.e.quarantine('wallet_window_incomplete',100)
        self.assertEqual(self.e.allocator.allowed('spot',1,'other','other',120),'unresolved_data_gap')
        self.assertFalse(self.e.status(120)['ready'])
        # Once the potentially missed 60-second nomination window is entirely stale,
        # the historical gap remains visible but no longer blocks unrelated new evidence.
        self.e.scout([],161)
        self.assertIsNone(self.e.allocator.allowed('spot',1,'other','other',161))
        status=self.e.status(161)
        self.assertTrue(status['ready'])
        self.assertFalse(status['active_entry_quarantine'])
        self.assertEqual(status['gaps'][-1]['reason'],'wallet_window_incomplete')
    def test_funnel_distinguishes_observation_nomination_qualification_and_entry(self):
        nomination=self.e.scout([event()],100)[0]
        self.assertEqual(self.e.consider(nomination,evidence(),100),'qualified')
        self.assertEqual(self.e.fill(nomination['id'],snapshot(102),102),'settled')
        f=self.e.status(102)['funnel']
        self.assertEqual(f['scout_batches'],1)
        self.assertEqual(f['observed_events'],1)
        self.assertEqual(f['seed_events'],1)
        self.assertEqual(f['nominations'],1)
        self.assertEqual(f['qualification_attempts'],1)
        self.assertEqual(f['qualified'],1)
        self.assertEqual(f['entries'],1)
        self.assertEqual(f['settled_exits'],0)

if __name__=='__main__':unittest.main()
