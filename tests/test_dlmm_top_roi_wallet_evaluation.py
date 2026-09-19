import unittest

from tests import dlmm_top_roi_wallet_evaluation as roi


class TopROIWalletEvaluationTests(unittest.TestCase):
    def test_pool_metrics_uses_deposit_weighted_roi(self):
        rows=[
            {"poolAddress":"a","totalDeposit":"100","pnlUsd":"10","pnlSol":"0.1",
             "totalDepositSol":"1","pnlPctChange":"10","pnlSolPctChange":"10"},
            {"poolAddress":"b","totalDeposit":"900","pnlUsd":"45","pnlSol":"0.45",
             "totalDepositSol":"9","pnlPctChange":"5","pnlSolPctChange":"5"},
        ]
        m=roi._pool_metrics(rows)
        self.assertAlmostEqual(m["recent_roi_pct"],5.5)
        self.assertAlmostEqual(m["recent_sol_roi_pct"],5.5)
        self.assertEqual(m["pool_count"],2)

    def test_discovery_constants_require_broader_pre_pnl_sample(self):
        self.assertEqual(roi.POOL_SAMPLE,30)
        self.assertEqual(roi.TARGET_WALLETS,80)
        self.assertEqual(roi.MIN_WALLETS,40)
        self.assertEqual(roi.ROBUST_MIN_CLOSED_POSITIONS,20)
        self.assertEqual(roi.ROBUST_MIN_DISTINCT_POOLS,3)
        self.assertEqual(roi.ROBUST_MIN_PROFITABLE_POSITION_RATE,0.55)

    def test_exhaustive_low_history_pool_is_complete_boundary(self):
        recent=[{"signature":"only","slot":1}]
        readable=[(recent[0],{"meta":{"err":None}})]
        failures=[]
        exhaustive=(
            len(recent)<roi.TX_BODY_TARGET and len(readable)==len(recent) and not failures
        )
        self.assertTrue(exhaustive)

    def test_raw_roi_does_not_imply_robust_eligibility(self):
        m=roi._pool_metrics([
            {"poolAddress":"a","totalDeposit":"1","pnlUsd":"1","pnlSol":"0.01",
             "totalDepositSol":"0.01","pnlPctChange":"100","pnlSolPctChange":"100"}
        ])
        self.assertEqual(m["recent_roi_pct"],100.0)
        self.assertEqual(m["pool_count"],1)
        self.assertLess(m["pool_count"],roi.ROBUST_MIN_DISTINCT_POOLS)


if __name__=="__main__":
    unittest.main()
