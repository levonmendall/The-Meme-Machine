import unittest

from meme_machine import dlmm
from tests import dlmm_strategy_high_activity as research


class HighActivityDiscovery(unittest.TestCase):
    def test_sol_pair_filter_rejects_wrong_or_unsupported_rows(self):
        good = dict(
            address='pool', token_x=dict(address=dlmm.WSOL), token_y=dict(address='token'),
            pool_config=dict(collect_fee_mode=0, bin_step=25), is_blacklisted=False,
            has_farm=False, volume={'30m': 100}, fees={'30m': 2}, fee_tvl_ratio={'30m': .1}, tvl=1000,
        )
        self.assertTrue(research._sol_pair(good))
        wrong = dict(good, token_x=dict(address='a'), token_y=dict(address='b'))
        self.assertFalse(research._sol_pair(wrong))
        farm = dict(good, has_farm=True)
        self.assertFalse(research._sol_pair(farm))
        fee_mode = dict(good, pool_config=dict(collect_fee_mode=1, bin_step=25))
        self.assertFalse(research._sol_pair(fee_mode))
        blacklisted = dict(good, is_blacklisted=True)
        self.assertFalse(research._sol_pair(blacklisted))

    def test_candidate_preserves_pre_entry_activity_metrics(self):
        row = dict(
            address='pool', name='TOKEN-SOL', token_x=dict(address='token'), token_y=dict(address=dlmm.WSOL),
            pool_config=dict(collect_fee_mode=0, bin_step=20), volume={'30m': 500, '1h': 900},
            fees={'30m': 5}, fee_tvl_ratio={'30m': .25}, tvl=2000,
        )
        candidate = research._candidate(row, 1, 'test')
        self.assertEqual(candidate['volume_30m'], 500)
        self.assertEqual(candidate['fees_30m'], 5)
        self.assertEqual(candidate['bin_step'], 20)
        self.assertEqual(candidate['rank'], 1)

    def test_selector_is_fixed_and_uses_only_warmup_activity(self):
        empty = dict(warmup_swaps=0, warmup_volume_sol_lamports=0)
        self.assertIsNone(research.select_variant(empty))
        active = dict(warmup_swaps=1, warmup_volume_sol_lamports=1)
        choice = research.select_variant(active)
        self.assertEqual(choice['strategy'], 'sdk_bidask')
        self.assertEqual(choice['width'], 8)
        self.assertIn('warmup', choice['rule'])


if __name__ == '__main__':
    unittest.main()
