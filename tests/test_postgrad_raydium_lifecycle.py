import tempfile
import unittest
from pathlib import Path

from meme_machine import pump
from meme_machine.postgrad import GraduationHandoff, PostGraduationPaperEngine
from meme_machine.store import Store

MINT = pump.b58(bytes([121])*32)
CREATOR = pump.b58(bytes([122])*32)
POOL = pump.b58(bytes([123])*32)


def snapshot(now, slot, sol_reserve=50_000_000_000, token_reserve=500_000_000_000_000):
    return dict(
        mint=MINT, pool=POOL, creator=CREATOR,
        surface='raydium-v4', protocol='raydium-amm-v4',
        network='solana-mainnet', model='raydium-v4-sol-cp-v1',
        kind='synthetic', slot=slot, market_time=now, available_time=now,
        state=dict(
            surface='raydium-v4', pool=POOL,
            base_reserve=token_reserve, quote_reserve=sol_reserve,
            fee_numerator=25, fee_denominator=10_000,
        ),
    )


class RaydiumPaperLifecycle(unittest.TestCase):
    def test_shared_bankroll_reservation_fill_restart_monitor_exit_and_reconcile(self):
        with tempfile.TemporaryDirectory() as td:
            db = str(Path(td)/'paper.db')
            store = Store(db, 'synthetic', 100_000_000, 'test')
            engine = PostGraduationPaperEngine(store, test_allocation=True)
            handoff = GraduationHandoff(MINT, CREATOR, 'source', 1, 1, False)
            initial_cash = store.state['cash']
            budget = store.state['initial']//20

            oid = engine.reserve_for_test(handoff, snapshot(100, 100), 100, oid='raydium-postgrad')
            self.assertEqual(oid, 'raydium-postgrad')
            self.assertEqual(store.state['orders'][oid]['budget'], budget)
            self.assertGreater(store.state['reserved'], budget)
            self.assertLess(store.state['cash'], initial_cash)

            store.close()
            store = Store(db, 'synthetic', 100_000_000, 'test')
            engine = PostGraduationPaperEngine(store, test_allocation=True)
            self.assertEqual(store.state['orders'][oid]['status'], 'reserved')
            self.assertEqual(engine.fill_for_test(oid, snapshot(102, 102), 102), 'settled')
            self.assertIn(MINT, store.state['positions'])
            self.assertEqual(store.state['reserved'], 0)
            store.reconcile()

            store.close()
            store = Store(db, 'synthetic', 100_000_000, 'test')
            engine = PostGraduationPaperEngine(store, test_allocation=True)
            self.assertIn(MINT, store.state['positions'])
            # Increase SOL reserve enough that the exact-size Raydium exit clears
            # the unchanged +15% take-profit boundary.
            self.assertEqual(
                engine.monitor_for_test(MINT, snapshot(107, 107, sol_reserve=70_000_000_000), 107),
                'exit_intended')
            self.assertEqual(
                engine.monitor_for_test(MINT, snapshot(112, 112, sol_reserve=70_000_000_000), 112),
                'settled')
            self.assertNotIn(MINT, store.state['positions'])
            self.assertEqual(store.state['reserved'], 0)
            self.assertEqual(store.state['rent'], 0)
            self.assertIn('exit', store.state['orders'][oid])
            self.assertTrue(store.reconcile())
            self.assertTrue(store.verify_archive())
            store.close()

    def test_prospective_raydium_allocation_remains_disabled(self):
        with tempfile.TemporaryDirectory() as td:
            store = Store(str(Path(td)/'paper.db'), 'prospective', 100_000_000, 'test')
            engine = PostGraduationPaperEngine(store)
            handoff = GraduationHandoff(MINT, CREATOR, 'source', 1, 1, False)
            live = snapshot(100, 100)
            live['kind'] = 'real'
            self.assertEqual(
                engine.allocation_reason(handoff, live, 100),
                'post_graduation_allocation_disabled')
            store.close()


if __name__ == '__main__':
    unittest.main()
