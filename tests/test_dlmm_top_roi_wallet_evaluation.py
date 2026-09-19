import json
from pathlib import Path
import tempfile
import threading
import time
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

    def test_wallet_analysis_is_bounded_concurrent_and_checkpointed(self):
        wallets=["w1","w2","w3","w4"]
        active=0
        max_active=0
        lock=threading.Lock()
        def analyzer(wallet):
            nonlocal active,max_active
            with lock:
                active+=1
                max_active=max(max_active,active)
            time.sleep(0.03)
            with lock:
                active-=1
            return {"wallet":wallet,"recent_roi_pct":1.0}

        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"checkpoint.json"
            rows=roi._analyze_wallets(
                wallets,"cohort",checkpoint_path=path,workers=2,analyzer=analyzer
            )
            self.assertEqual([r["wallet"] for r in rows],wallets)
            self.assertGreaterEqual(max_active,2)
            body=json.loads(path.read_text())
            self.assertEqual(body["status"],"complete")
            self.assertEqual(body["completed_wallets"],4)
            self.assertEqual(body["failed_wallets"],0)
            self.assertEqual(
                [body["rows"][w]["cohort_order"] for w in wallets],[1,2,3,4]
            )

    def test_checkpoint_resume_reuses_only_successful_wallets(self):
        wallets=["a","b","c"]
        first_calls=[]
        def first(wallet):
            first_calls.append(wallet)
            if wallet=="b":
                raise RuntimeError("dlmm_top_roi_test_transient")
            return {"wallet":wallet,"recent_roi_pct":1.0}

        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"checkpoint.json"
            with self.assertRaisesRegex(
                RuntimeError,"dlmm_top_roi_wallet_analysis_incomplete:1"
            ):
                roi._analyze_wallets(
                    wallets,"cohort",checkpoint_path=path,workers=2,analyzer=first
                )
            body=json.loads(path.read_text())
            self.assertEqual(set(body["rows"]),{"a","c"})
            self.assertEqual(set(body["failures"]),{"b"})

            second_calls=[]
            def second(wallet):
                second_calls.append(wallet)
                return {"wallet":wallet,"recent_roi_pct":2.0}
            rows=roi._analyze_wallets(
                wallets,"cohort",checkpoint_path=path,workers=2,analyzer=second
            )
            self.assertEqual(second_calls,["b"])
            self.assertEqual([r["wallet"] for r in rows],wallets)
            self.assertEqual(rows[0]["recent_roi_pct"],1.0)
            self.assertEqual(rows[1]["recent_roi_pct"],2.0)
            self.assertEqual(rows[2]["recent_roi_pct"],1.0)

    def test_checkpoint_rule_signature_preserves_roi_criteria(self):
        sig=roi._analysis_rule_signature("hash",["w"])
        self.assertEqual(sig["evaluation_days"],120)
        self.assertEqual(sig["robust_min_closed_positions"],20)
        self.assertEqual(sig["robust_min_distinct_pools"],3)
        self.assertEqual(sig["robust_min_profitable_position_rate_usd"],0.55)
        self.assertTrue(sig["robust_require_total_pnl_usd_positive"])
        self.assertTrue(sig["robust_require_total_pnl_sol_positive"])

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
