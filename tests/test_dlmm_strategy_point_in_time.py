import unittest

from meme_machine.dlmm_tape import reconstruct
from meme_machine.dlmm_paper import ENTRY_COST, EXIT_COST
from tests.dlmm_strategy_point_in_time import (_bidask_bps,_deposit,_replay,evaluate,regime_features)
from tests.test_dlmm_tape import interval,encode_state,remove_liquidity_transaction
from tests.dlmm_support import snapshot


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

    def test_external_removal_preserves_counterfactual_position_share_order(self):
        start=snapshot();start['kind']='real'
        state=__import__('meme_machine').dlmm.validate(start,100)
        post,removed,tx=remove_liquidity_transaction(
            state,bid=-1,slot=101,now=101,signature='remove-research')
        end=encode_state(start,post,102,102)
        sigs=[
            dict(signature='remove-research',slot=101,transactionIndex=7,
                 err=None,confirmationStatus='finalized'),
            dict(signature='anchor',slot=99,transactionIndex=2,
                 err=None,confirmationStatus='finalized')]
        tape=reconstruct(
            state,end,sigs,{'remove-research':tx},102,
            [100,2**31-1,2**31-1])
        position=_deposit(state,'foundation_spot',2)
        before_supply=position['virtual']['bins']['-1']['supply']
        replayed=_replay(position,tape)
        self.assertEqual(
            replayed['virtual']['bins']['-1']['supply'],
            before_supply-removed['share'])
        self.assertEqual(
            replayed['shares']['-1'],position['shares']['-1'])

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
