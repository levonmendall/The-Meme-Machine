import unittest

from tests.market_native_opportunity_outcomes import CONCENTRATION_ROTATE_AT, EvidenceSessions

from meme_machine.outcome_research import (
    enable_shadow_exit, high_density_features, liquidity_floor_eligibility, new_tracker,
    observe_trade, return_bps, summarize_liquidity_counterfactual,
    summarize_post_exit_tail, summarize_trackers,
)

MINT='mint'


def trade(t, amount, tokens=100, mint=MINT):
    return dict(mint=mint,market_time=t,amount=amount,tokens=tokens)


class OutcomeResearchTests(unittest.TestCase):
    def test_forward_marks_and_extrema_are_future_only(self):
        row=new_tracker(MINT,100,100,100,['feasible_unpreflighted'],horizons=(60,300))
        self.assertFalse(observe_trade(row,trade(99,200)))
        observe_trade(row,trade(160,110))
        observe_trade(row,trade(400,80))
        self.assertEqual(row['marks']['60']['return_bps'],1000)
        self.assertEqual(row['marks']['300']['return_bps'],-2000)
        self.assertEqual(row['max_favorable_bps'],1000)
        self.assertEqual(row['max_adverse_bps'],-2000)

    def test_return_ratio_is_scale_invariant(self):
        self.assertEqual(return_bps(10,2,12,2),2000)
        self.assertEqual(return_bps(100,20,120,20),2000)

    def test_shadow_exit_tracks_upside_after_take_profit(self):
        row=new_tracker(MINT,100,100,100,['natural_sample'],horizons=(60,))
        enable_shadow_exit(row,opened_time=100)
        observe_trade(row,trade(110,116))
        self.assertEqual(row['shadow_exit']['reason'],'take_profit_proxy')
        observe_trade(row,trade(410,150))
        self.assertEqual(row['shadow_exit']['post_exit_marks']['300']['entry_return_bps'],5000)
        self.assertEqual(row['shadow_exit']['post_exit_max_entry_return_bps'],5000)

    def test_liquidity_floor_uses_existing_sensitivity_only(self):
        vector={'sensitivity':{'values':{'min_real_sol_lamports':{
            '5000000000':True,'7500000000':True,'10000000000':False}}}}
        got=liquidity_floor_eligibility(vector)
        self.assertTrue(got['5000000000'])
        self.assertTrue(got['7500000000'])
        self.assertFalse(got['10000000000'])


    def test_high_density_features_are_point_in_time_only(self):
        rows=[
            dict(mint=MINT,market_time=95,amount=100,tokens=10,wallet='a',buy=True,slot=1,index=1),
            dict(mint=MINT,market_time=96,amount=50,tokens=5,wallet='b',buy=False,slot=2,index=1),
            dict(mint=MINT,market_time=101,amount=999,tokens=1,wallet='future',buy=True,slot=3,index=1),
        ]
        got=high_density_features(rows,100)
        self.assertEqual(got['event_count'],2)
        self.assertEqual(got['unique_buyers'],1)
        self.assertEqual(got['unique_sellers'],1)
        self.assertEqual(got['net_buy_lamports'],50)
        self.assertNotIn('future',str(got))
        self.assertEqual(got['windows']['5']['events'],2)



    def test_concentration_reader_rotates_before_hard_cap(self):
        class Reader:
            def status(self):
                return {'program_scan_logical_requests':CONCENTRATION_ROTATE_AT}
        class RPC:
            calls=1
        session=object.__new__(EvidenceSessions)
        session.reader=Reader()
        session.rpc=RPC()
        reasons=[]
        session.rotate=lambda reason: reasons.append(reason)
        session.maybe_rotate()
        self.assertEqual(reasons,['bounded_concentration_reader_rotation'])


    def test_summaries_do_not_create_authority(self):
        tracker=new_tracker(MINT,100,100,100,['high_density'],horizons=(60,))
        observe_trade(tracker,trade(160,120))
        cohort=summarize_trackers([tracker])
        self.assertEqual(cohort['high_density']['count'],1)
        natural=[dict(
            qualification_vector={'actual_reason':'exit_liquidity'},
            liquidity_floor_eligibility={'5000000000':True,'7500000000':False,'10000000000':False},
            future_outcomes=tracker,
        )]
        liq=summarize_liquidity_counterfactual(natural)
        self.assertEqual(liq['5000000000']['eligible'],1)
        self.assertEqual(summarize_post_exit_tail(natural)['shadow_exits'],0)


if __name__=='__main__':
    unittest.main()
