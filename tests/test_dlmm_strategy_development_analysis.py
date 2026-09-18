"""Regression coverage for development-only DLMM rule proposal analysis."""
import unittest

from tests import dlmm_strategy_development_analysis as analysis
from tests import dlmm_strategy_economics as economics


def _features(surplus=0, flow=1, away=1):
    return dict(
        projected_60s_range_fee_surplus_lamports=surplus,
        flow_into_range_volume_sol_lamports=flow,
        away_from_range_volume_sol_lamports=away,
        reversal_count=1 if away else 0,
        touch_then_revert=False,
        two_way_balance=0.5 if away else 0,
    )


class DevelopmentAnalysis(unittest.TestCase):
    def test_insufficient_sample_never_proposes_rule(self):
        report = dict(
            study_phase="development",
            opportunities=[
                dict(pool="p", entry_slot=1, end_slot=2),
            ],
            normalized_results=[],
        )
        result = analysis.propose_rule([report])
        self.assertEqual(result["status"], "insufficient_development_sample")

    def test_holdout_report_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "non_development_report"):
            analysis.propose_rule([
                dict(study_phase="holdout", opportunities=[], normalized_results=[])
            ])

    def test_supported_development_sample_proposes_but_does_not_freeze(self):
        opportunities = []
        rows = []
        for i in range(economics.DEVELOPMENT_MIN_COMPLETED):
            pool = f"p{i % economics.DEVELOPMENT_MIN_DISTINCT_POOLS}"
            opportunities.append(dict(pool=pool, entry_slot=i, end_slot=i + 1))
            for target in economics.NORMALIZED_TARGET_BPS:
                # Make 200 bps the strongest development-only candidate.
                pnl = 12.0 if target == 200 else -5.0
                rows.append(dict(
                    sample_role="development",
                    resolved=True,
                    pool=pool,
                    target_distance_bps=target,
                    pnl_bps=pnl,
                    pre_entry_features=_features(surplus=analysis.FIXED_COST),
                ))
        report = dict(
            study_phase="development",
            opportunities=opportunities,
            normalized_results=rows,
        )
        result = analysis.propose_rule([report])
        self.assertEqual(result["status"], "proposed")
        self.assertFalse(result["automatic_freeze"])
        self.assertEqual(result["proposal"]["target_distance_bps"], 200)
        self.assertIn(
            result["proposal"]["min_projected_60s_fee_surplus_lamports"],
            analysis.SURPLUS_MARGIN_LAMPORTS,
        )
        self.assertIn("Human review", result["next_step"])


if __name__ == "__main__":
    unittest.main()
