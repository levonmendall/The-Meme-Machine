import unittest

from robinhood_research.continuation_robinhood import POLICY, POLICY_HASH, REFERENCE_ENTRY_WEI
from robinhood_research.continuation_robinhood_cohort import (
    COHORT_TARGET, ENTRY_DELAY_SECONDS, MAX_HOLD_SECONDS, MONITOR_SECONDS,
    PAPER_AMOUNT, PAPER_CAPITAL, RISK_BPS, TAKE_PROFIT_BPS, _paper_decision,
)


class ContinuationCohortTests(unittest.TestCase):
    def test_cohort_keeps_frozen_policy_and_actual_exit_path(self):
        self.assertEqual(COHORT_TARGET,10)
        self.assertEqual(PAPER_AMOUNT,REFERENCE_ENTRY_WEI)
        self.assertEqual(PAPER_CAPITAL,REFERENCE_ENTRY_WEI*20)
        self.assertEqual(ENTRY_DELAY_SECONDS,2)
        self.assertEqual(MONITOR_SECONDS,5)
        self.assertEqual(TAKE_PROFIT_BPS,1500)
        self.assertEqual(RISK_BPS,-1000)
        self.assertEqual(MAX_HOLD_SECONDS,900)

    def test_paper_decision_requires_exact_frozen_policy(self):
        row=dict(
            curve="0x"+"11"*20,token="0x"+"22"*20,source_transaction="0xabc",
            vector=dict(
                asof=100,evidence_available_at=104,decision_state_age_seconds=4,
            ),
        )
        d=_paper_decision(row,104)
        self.assertEqual(d["policy"],POLICY)
        self.assertEqual(d["policy_hash"],POLICY_HASH)
        self.assertEqual(d["qualification"],"qualified")
        self.assertEqual(d["authority"],"frozen_policy_paper")
        self.assertFalse(d["outcome_used_for_selection"])


if __name__=="__main__":
    unittest.main()
