import unittest

from robinhood_research import ramses_historical_market_review as review


class RamsesHistoricalMarketReviewTests(unittest.TestCase):
    def test_windows_separate_two_way_chop_from_one_way_flow(self):
        rows=[
            dict(pool="p",timestamp=100,block=1,transaction_index=0,log_index=0,
                 bin_id=100,direction=0,volume_y=100,lp_fee_y=2),
            dict(pool="p",timestamp=120,block=2,transaction_index=0,log_index=0,
                 bin_id=102,direction=1,volume_y=80,lp_fee_y=2),
            dict(pool="p",timestamp=140,block=3,transaction_index=0,log_index=0,
                 bin_id=100,direction=0,volume_y=100,lp_fee_y=2),
        ]
        out=review._windows(rows)
        self.assertEqual(len(out),1)
        row=out[0]
        self.assertEqual(row["swap_count"],3)
        self.assertGreater(row["two_way_share"],0.25)
        self.assertEqual(row["net_displacement_bins"],0)
        self.assertEqual(row["gross_bin_crossings"],4)
        self.assertGreater(row["chop_ratio"],3)

    def test_windows_keep_one_way_flow_visible(self):
        rows=[
            dict(pool="p",timestamp=400,block=1,transaction_index=0,log_index=0,
                 bin_id=100,direction=0,volume_y=100,lp_fee_y=1),
            dict(pool="p",timestamp=410,block=2,transaction_index=0,log_index=0,
                 bin_id=101,direction=0,volume_y=100,lp_fee_y=1),
        ]
        row=review._windows(rows)[0]
        self.assertEqual(row["two_way_share"],0)
        self.assertEqual(row["flow_imbalance"],1)


if __name__=="__main__":
    unittest.main()
