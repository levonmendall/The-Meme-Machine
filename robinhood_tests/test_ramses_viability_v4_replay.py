import json
from pathlib import Path
import unittest

from robinhood_research.ramses_strategy import POLICY


FIXTURE = Path(__file__).parent / "fixtures" / "ramses_viability_v4_replay.json"


class RamsesViabilityV4ReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=json.loads(FIXTURE.read_text())

    def test_rejected_branch_b_is_not_resurrected(self):
        row=self.data["rejected_branch_b"]
        self.assertLess(row["median_after_cost_return_bps_24h"],0)
        self.assertLess(row["median_after_cost_return_bps_72h"],0)
        self.assertLess(row["two_x_cost_stress_median_bps_24h"],0)
        self.assertLess(row["two_x_cost_stress_median_bps_72h"],0)

    def test_observed_prospective_cost_dominated_entry_fails_v4_structural_gate(self):
        row=self.data["prospective_natural_loss"]
        burden=row["execution_cost_quote_raw"]*10000//row["position_capital_quote_raw"]
        self.assertGreater(
            burden,
            POLICY["active_wide_maker"]["max_entry_cycle_cost_to_capital_bps"],
        )
        self.assertEqual(row["rebalances"],0)
        self.assertLess(row["net_result_quote_raw"],0)

    def test_historical_quiet_wide_operator_rows_are_not_blanket_removed_by_cost_sanity_gate(self):
        cost=self.data["historical_cost_anchor"]["max_verified_quote_cycle_cost_raw"]
        decimals=self.data["historical_cost_anchor"]["usdg_decimals"]
        limit=POLICY["active_wide_maker"]["max_entry_cycle_cost_to_capital_bps"]
        rows=self.data["historical_active_wide_quiet_rows"]
        self.assertGreaterEqual(len(rows),5)
        for row in rows:
            capital=max(1,round(row["deposit_usd"]*(10**decimals)))
            burden=cost*10000//capital
            self.assertLessEqual(
                burden,limit,
                msg=(row["symbol"],row["pool"],burden,limit),
            )

    def test_v4_replay_provenance_is_paper_only_and_existing_evidence_only(self):
        self.assertTrue(self.data["paper_only"])
        self.assertEqual(self.data["prospective_natural_loss"]["run_id"],36043064083)
        self.assertEqual(
            self.data["historical_sources"]["branch_b_final"]["run_id"],
            35685789656,
        )


if __name__ == "__main__":
    unittest.main()
