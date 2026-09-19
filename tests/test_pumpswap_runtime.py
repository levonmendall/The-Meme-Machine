import tempfile
import unittest
from pathlib import Path

from meme_machine.engine import GAS, RENT
from meme_machine.postgrad import buy_quote
from meme_machine.provider import Unavailable
from meme_machine.pumpswap_runtime import PumpSwapPaperRuntime
from meme_machine.store import Store
from tests.test_postgrad import MINT, CREATOR, complete_pump_snapshot, pumpswap_snapshot


class Clock:
    def __init__(self, value=100):
        self.value=value
    def __call__(self):
        return self.value


class Adapter:
    def __init__(self, clock, missing=False, not_graduated=False):
        self.clock=clock
        self.missing=missing
        self.not_graduated=not_graduated
        self.graduation_calls=0
        self.pumpswap_calls=0
    def graduation_snapshot(self, mint, now, priority=True):
        self.graduation_calls+=1
        if self.not_graduated:
            raise ValueError('bonding_curve_not_complete')
        snap=complete_pump_snapshot(now=int(self.clock()), mint=mint, creator=CREATOR, retired=True)
        snap['kind']='real'
        return snap
    def pumpswap_snapshot(self, handoff, now, priority=True):
        self.pumpswap_calls+=1
        if self.missing:
            raise Unavailable('pumpswap_pool_missing')
        quote=70_000_000_000 if int(self.clock()) >= 107 else 50_000_000_000
        return pumpswap_snapshot(kind='real', now=int(self.clock()), slot=int(self.clock()), quote=quote)


def reserve_upstream(store, created=100, due=102, min_tokens=1, oid='upstream-order'):
    amount=store.state['initial']//20
    reservation=amount+GAS+RENT
    with store.transaction('test_upstream_authorized_reservation'):
        s=store.state
        s['cash']-=reservation
        s['reserved']+=reservation
        s['orders'][oid]=dict(
            status='reserved',mint=MINT,related=CREATOR,reservation=reservation,
            budget=amount,min_tokens=min_tokens,created=created,due=due,slot=90,
            evidence={'frozen_policy':'continuation-v1'},nomination={'id':'upstream'},
        )
    return oid,reservation


def open_upstream_position(store, tokens, basis=100_000_000, opened=50):
    with store.transaction('test_upstream_pump_position'):
        s=store.state
        s['cash']-=basis+RENT
        s['rent']+=RENT
        s['positions'][MINT]=dict(
            kind='spot',chain='solana-mainnet',tokens=tokens,basis=basis,rent=RENT,
            opened=opened,related=CREATOR,entry_slot=50,next_monitor=100,
            mark=None,mark_time=None,unresolved=False,last_unresolved_record=0,
            exit_due=None,exit_reason=None,
        )
        s['orders']['prior-entry']=dict(
            status='settled',mint=MINT,related=CREATOR,reservation=0,
            fill={'upstream':True},
        )


class DurablePumpSwapRuntime(unittest.TestCase):
    def test_reserved_upstream_order_fills_on_canonical_pumpswap_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as td:
            db=str(Path(td)/'paper.db')
            clock=Clock(102)
            store=Store(db,'prospective',100_000_000,'test')
            oid,reservation=reserve_upstream(store,created=100,due=102,min_tokens=1)
            runtime=PumpSwapPaperRuntime(store,Adapter(clock),clock=clock)
            self.assertEqual(runtime.fill_existing_order(oid),'settled')
            self.assertEqual(store.state['reserved'],0)
            self.assertLess(store.state['cash'],store.state['initial'])
            self.assertIn(MINT,store.state['positions'])
            self.assertEqual(store.state['positions'][MINT]['surface'],'pumpswap')
            self.assertEqual(store.state['orders'][oid]['surface'],'pumpswap')
            self.assertIn('postgrad_handoff',store.state['positions'][MINT])
            self.assertTrue(store.reconcile())
            store.close()

            store=Store(db,'prospective',100_000_000,'test')
            self.assertEqual(store.state['positions'][MINT]['surface'],'pumpswap')
            self.assertEqual(store.state['reserved'],0)
            self.assertTrue(store.reconcile())
            self.assertTrue(store.verify_archive())
            store.close()

    def test_existing_pump_position_transitions_restart_monitors_and_settles(self):
        with tempfile.TemporaryDirectory() as td:
            db=str(Path(td)/'paper.db')
            clock=Clock(100)
            store=Store(db,'prospective',100_000_000,'test')
            baseline=pumpswap_snapshot(kind='real',now=100,slot=100)
            tokens=buy_quote(baseline,100_000_000).output_amount
            open_upstream_position(store,tokens,basis=100_000_000,opened=50)
            runtime=PumpSwapPaperRuntime(store,Adapter(clock),clock=clock)
            self.assertEqual(runtime.monitor_existing_position(MINT),'holding')
            self.assertEqual(store.state['positions'][MINT]['surface'],'pumpswap')
            handoff=store.state['positions'][MINT]['postgrad_handoff']
            self.assertEqual(handoff['mint'],MINT)
            self.assertTrue(store.reconcile())
            store.close()

            clock.value=107
            store=Store(db,'prospective',100_000_000,'test')
            adapter=Adapter(clock)
            runtime=PumpSwapPaperRuntime(store,adapter,clock=clock)
            self.assertEqual(runtime.monitor_existing_position(MINT),'exit_intended')
            # Durable handoff means restart monitoring no longer needs to rediscover graduation.
            self.assertEqual(adapter.graduation_calls,0)
            store.close()

            clock.value=112
            store=Store(db,'prospective',100_000_000,'test')
            adapter=Adapter(clock)
            runtime=PumpSwapPaperRuntime(store,adapter,clock=clock)
            self.assertEqual(runtime.monitor_existing_position(MINT),'settled')
            self.assertNotIn(MINT,store.state['positions'])
            self.assertEqual(store.state['rent'],0)
            self.assertIn('exit',store.state['orders']['prior-entry'])
            self.assertEqual(store.state['orders']['prior-entry']['exit']['surface'],'pumpswap')
            self.assertEqual(adapter.graduation_calls,0)
            self.assertTrue(store.reconcile())
            self.assertTrue(store.verify_archive())
            store.close()

    def test_missing_pumpswap_is_fail_closed_and_bounded_for_position_and_order(self):
        with tempfile.TemporaryDirectory() as td:
            db=str(Path(td)/'paper.db')
            clock=Clock(102)
            store=Store(db,'prospective',100_000_000,'test')
            oid,reservation=reserve_upstream(store,created=100,due=102,min_tokens=1)
            tokens=buy_quote(pumpswap_snapshot(kind='real',now=102,slot=102),100_000_000).output_amount
            open_upstream_position(store,tokens,basis=100_000_000,opened=50)
            runtime=PumpSwapPaperRuntime(store,Adapter(clock,missing=True),clock=clock)
            self.assertEqual(runtime.fill_existing_order(oid),'waiting_postgrad')
            self.assertEqual(store.state['reserved'],reservation)
            self.assertEqual(runtime.monitor_existing_position(MINT),'unresolved')
            self.assertIn(MINT,store.state['positions'])
            self.assertEqual(store.state['positions'][MINT]['surface'],'graduating-pumpswap')
            self.assertTrue(store.state['positions'][MINT]['unresolved'])
            self.assertEqual(
                store.state['positions'][MINT]['last_exit_error']['reason'],
                'pumpswap_quote_unavailable')
            self.assertEqual(store.state['counts']['unavailable_exit:pumpswap_quote_unavailable'],1)

            clock.value=161
            self.assertEqual(runtime.fill_existing_order(oid),'cancelled')
            self.assertEqual(store.state['reserved'],0)
            self.assertIn(MINT,store.state['positions'])
            self.assertTrue(store.reconcile())
            store.close()

    def test_not_graduated_never_creates_postgrad_authority(self):
        with tempfile.TemporaryDirectory() as td:
            store=Store(str(Path(td)/'paper.db'),'prospective',100_000_000,'test')
            oid,reservation=reserve_upstream(store,created=100,due=100,min_tokens=1)
            clock=Clock(100)
            runtime=PumpSwapPaperRuntime(store,Adapter(clock,not_graduated=True),clock=clock)
            self.assertEqual(runtime.fill_existing_order(oid),'not_graduated')
            self.assertEqual(store.state['reserved'],reservation)
            self.assertNotIn('postgrad_handoff',store.state['orders'][oid])
            self.assertFalse(runtime.status()['new_allocation_authority'])
            self.assertFalse(runtime.status()['legacy_raydium_authority'])
            store.close()


if __name__ == '__main__':
    unittest.main()
