import unittest
from pathlib import Path

from meme_machine.engine import EXIT_TIMEOUT_SECONDS, SIGNAL_WINDOW
from meme_machine.market_native_runtime import (
    DEFAULT_FULL_EVIDENCE_BUDGET,
    DEFAULT_PREFLIGHT_BUDGET,
    MAX_DISCOVERED_MINTS,
)
from meme_machine.research import CURRENT_THRESHOLDS
from meme_machine.stream import WINDOW_SECONDS
from tests import market_native_active_paper as active
from tests import market_native_opportunity_outcomes as outcomes
from tests import market_native_paper_cohort as cohort


class ThroughputPolicyTests(unittest.TestCase):
    def test_economic_timing_and_strategy_thresholds_remain_frozen(self):
        self.assertEqual(WINDOW_SECONDS,60)
        self.assertEqual(SIGNAL_WINDOW,60)
        self.assertEqual(EXIT_TIMEOUT_SECONDS,900)
        self.assertEqual(CURRENT_THRESHOLDS,{
            'max_concentration_bps':3500,
            'min_real_sol_lamports':10_000_000_000,
            'max_evidence_events':100,
            'min_independent_groups':3,
            'min_net_buy_lamports':1_000_000_000,
            'max_price_extension_bps':12_000,
            'max_roundtrip_loss_bps':500,
        })

    def test_authenticated_five_rps_capacity_is_used_for_more_evidence_not_shorter_time(self):
        self.assertEqual(DEFAULT_PREFLIGHT_BUDGET,150)
        self.assertEqual(DEFAULT_FULL_EVIDENCE_BUDGET,40)
        self.assertEqual(MAX_DISCOVERED_MINTS,10_000)

        self.assertEqual(active.DISCOVERY_SECONDS,3300)
        self.assertEqual(active.PREFLIGHT_BUDGET,150)
        self.assertEqual(active.FULL_EVIDENCE_BUDGET,40)
        self.assertEqual(active.RPC_ROTATE_AT,160)

        self.assertEqual(cohort.DISCOVERY_SECONDS,5400)
        self.assertEqual(cohort.POST_SECONDS,1100)
        self.assertEqual(cohort.PREFLIGHT_BUDGET,150)
        self.assertEqual(cohort.FULL_EVIDENCE_BUDGET,40)

        self.assertEqual(outcomes.DISCOVERY_SECONDS,3300)
        self.assertEqual(outcomes.FOLLOWUP_SECONDS,3600)
        self.assertEqual(outcomes.NATURAL_BUDGET,180)
        self.assertEqual(outcomes.PRIORITY_BUDGET,240)
        self.assertEqual(outcomes.EXTRA_EVIDENCE_BUDGET,240)
        self.assertEqual(outcomes.EXTRA_EVIDENCE_PER_SLOT,5)

    def test_live_workflows_use_authenticated_pump_lane_and_keep_long_windows(self):
        workflow=(Path(__file__).resolve().parents[1]/'.github'/'workflows'/'ci.yml').read_text()
        self.assertIn('group: solana-onfinality-auth-pump-live',workflow)
        self.assertIn("MM_MARKET_NATIVE_COHORT_DISCOVERY_SECONDS: '5400'",workflow)
        self.assertIn("MM_MARKET_NATIVE_COHORT_PREFLIGHT_BUDGET: '150'",workflow)
        self.assertIn("MM_MARKET_NATIVE_COHORT_FULL_EVIDENCE_BUDGET: '40'",workflow)
        self.assertIn("MM_MARKET_NATIVE_OUTCOME_DISCOVERY_SECONDS: '3300'",workflow)
        self.assertIn("MM_MARKET_NATIVE_OUTCOME_FOLLOWUP_SECONDS: '3600'",workflow)
        self.assertIn("MM_MARKET_NATIVE_OUTCOME_NATURAL_BUDGET: '180'",workflow)
        self.assertIn("MM_MARKET_NATIVE_OUTCOME_PRIORITY_BUDGET: '240'",workflow)
        self.assertIn("MM_MARKET_NATIVE_OUTCOME_EXTRA_EVIDENCE_BUDGET: '240'",workflow)
        self.assertIn("MM_MARKET_NATIVE_OUTCOME_EXTRA_EVIDENCE_PER_SLOT: '5'",workflow)


if __name__=='__main__':
    unittest.main()
