import unittest

from meme_machine.dlmm_tape import reconstruct
from meme_machine.dlmm_paper import ENTRY_COST, EXIT_COST
from tests.dlmm_strategy_point_in_time import _bidask_bps, evaluate, regime_features
from tests.test_dlmm_tape import interval


class DlmmPointInTimeResearch(unittest.TestCase):
    def test_pinned_one_sided_bidask_distribution_is_bounded(self):
        left=list(range(-8,0));bps=_bidask_bps(0,left)
        self.assertEqual(sum(bps),10_000)
        self.assertGreater(bps[0],bps[-1])
        right=list(range(1,9));bps=_bidask_bps(0,right)
        self.assertEqual(sum(bps),10_000)
        self.assertGreater(bps[-1],bps[0])

    def test_verified_tape_drives_after_cost_counterfactual(self):
        _start,state,end,sigs,txs=interval()
        tape=reconstruct(state,end,sigs,txs,102,[100,2**31-1,2**31-1])
        result=evaluate(state,tape,'foundation_spot',2)
        self.assertTrue(result['resolved'])
        self.assertEqual(result['fixed_cost_lamports'],ENTRY_COST+EXIT_COST)
        self.assertIn('pnl_lamports',result)
        self.assertIn('range_hit',result)

    def test_regime_features_use_only_warmup_tape(self):
        _start,state,end,sigs,txs=interval()
        tape=reconstruct(state,end,sigs,txs,102,[100,2**31-1,2**31-1])
        features=regime_features(state,tape)
        self.assertEqual(features['warmup_swaps'],1)
        self.assertGreater(features['warmup_volume_sol_lamports'],0)
        self.assertGreater(features['local_liquidity_sol_lamports'],0)
        self.assertGreaterEqual(features['direction_balance'],0)
        self.assertLessEqual(features['direction_balance'],1)


if __name__=='__main__':
    unittest.main()
