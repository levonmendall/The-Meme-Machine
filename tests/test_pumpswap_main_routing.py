import tempfile
import unittest
from pathlib import Path

from meme_machine.__main__ import _monitor_existing
from meme_machine.engine import Engine, GAS, RENT
from meme_machine.postgrad import buy_quote
from meme_machine.provider import Unavailable
from meme_machine.pumpswap_runtime import PumpSwapPaperRuntime
from meme_machine.store import Store
from tests.test_postgrad import MINT, CREATOR, complete_pump_snapshot, pumpswap_snapshot


class Clock:
    def __init__(self, value):
        self.value=value
    def __call__(self):
        return self.value


class RetiredPumpAdapter:
    def snapshot(self, mint, now, priority=True):
        raise Unavailable('retired_bonding_curve')


class NotGraduatedPostgradAdapter:
    def __init__(self, clock):
        self.clock=clock
    def graduation_snapshot(self, mint, now, priority=True):
        raise ValueError('bonding_curve_not_complete')
    def pumpswap_snapshot(self, handoff, now, priority=True):
        raise AssertionError('pumpswap must not be queried before graduation')


class PostgradAdapter:
    def __init__(self, clock):
        self.clock=clock
    def graduation_snapshot(self, mint, now, priority=True):
        snap=complete_pump_snapshot(now=int(self.clock()), mint=mint, creator=CREATOR, retired=True)
        snap['kind']='real'
        return snap
    def pumpswap_snapshot(self, handoff, now, priority=True):
        return pumpswap_snapshot(kind='real',now=int(self.clock()),slot=int(self.clock()),quote=50_000_000_000)


def upstream_order(store):
    amount=store.state['initial']//20
    reservation=amount+GAS+RENT
    with store.transaction('test_upstream_order'):
        s=store.state
        s['cash']-=reservation
        s['reserved']+=reservation
        s['orders']['order']=dict(
            status='reserved',mint=MINT,related=CREATOR,reservation=reservation,
            budget=amount,min_tokens=1,created=100,due=102,slot=90,
            evidence={'policy':'continuation-v1'},nomination={'id':'order'},
        )


def upstream_position(store):
    tokens=buy_quote(pumpswap_snapshot(kind='real',now=100,slot=100),100_000_000).output_amount
    with store.transaction('test_upstream_position'):
        s=store.state
        s['cash']-=100_000_000+RENT
        s['rent']+=RENT
        s['positions'][MINT]=dict(
            kind='spot',chain='solana-mainnet',tokens=tokens,basis=100_000_000,rent=RENT,
            opened=50,related=CREATOR,entry_slot=50,next_monitor=100,
            mark=None,mark_time=None,unresolved=False,last_unresolved_record=0,
            exit_due=None,exit_reason=None,
        )


class MainRuntimeRouting(unittest.TestCase):
    def test_due_reserved_order_uses_pumpswap_when_pump_curve_is_retired(self):
        with tempfile.TemporaryDirectory() as td:
            store=Store(str(Path(td)/'paper.db'),'prospective',100_000_000,'test')
            engine=Engine(store,[])
            upstream_order(store)
            clock=Clock(102)
            runtime=PumpSwapPaperRuntime(store,PostgradAdapter(clock),clock=clock)
            _monitor_existing(engine,RetiredPumpAdapter(),102,pumpswap_runtime=runtime)
            self.assertEqual(store.state['orders']['order']['status'],'settled')
            self.assertEqual(store.state['positions'][MINT]['surface'],'pumpswap')
            self.assertTrue(store.reconcile())
            store.close()

    def test_open_position_uses_pumpswap_mark_when_pump_curve_is_retired(self):
        with tempfile.TemporaryDirectory() as td:
            store=Store(str(Path(td)/'paper.db'),'prospective',100_000_000,'test')
            engine=Engine(store,[])
            upstream_position(store)
            clock=Clock(100)
            runtime=PumpSwapPaperRuntime(store,PostgradAdapter(clock),clock=clock)
            _monitor_existing(engine,RetiredPumpAdapter(),100,pumpswap_runtime=runtime)
            position=store.state['positions'][MINT]
            self.assertEqual(position['surface'],'pumpswap')
            self.assertIsNotNone(position['mark'])
            self.assertIn('postgrad_handoff',position)
            self.assertIsNone(position.get('last_exit_error'))
            self.assertEqual(store.state['counts'].get('unavailable_exit',0),0)
            self.assertTrue(store.reconcile())
            store.close()

    def test_pregraduation_pump_read_failure_preserves_exact_reason(self):
        with tempfile.TemporaryDirectory() as td:
            store=Store(str(Path(td)/'paper.db'),'prospective',100_000_000,'test')
            engine=Engine(store,[])
            upstream_position(store)
            clock=Clock(100)
            runtime=PumpSwapPaperRuntime(store,NotGraduatedPostgradAdapter(clock),clock=clock)
            _monitor_existing(engine,RetiredPumpAdapter(),100,pumpswap_runtime=runtime)
            position=store.state['positions'][MINT]
            self.assertEqual(position['last_exit_error']['reason'],'retired_bonding_curve')
            self.assertEqual(position['last_exit_error']['stage'],'pump_exit_quote')
            self.assertEqual(store.state['counts']['unavailable_exit:retired_bonding_curve'],1)
            self.assertNotIn('postgrad_handoff',position)
            self.assertTrue(store.reconcile())
            store.close()


if __name__ == '__main__':
    unittest.main()
