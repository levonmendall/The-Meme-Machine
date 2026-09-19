import unittest
from tests import rejected_winner_preentry_analysis as study


def row(reason="concentration",events=25,groups=1,mfe=2000,mae=-500,current=False):
    return dict(
        evidence_stage="complete",actual_reason=reason,mint="m",qualified_at=1,
        qualification_vector=dict(
            current_threshold_pass=current,concentration_bps=5000,
            real_sol_lamports=1_000_000_000,evidence_event_count=events,
            independent_buyer_groups=groups,independent_net_buy_lamports=0,
            price_extension_bps=9000,roundtrip_loss_bps=400,
            signal_age_seconds=10,quote_age_seconds=5,all_rejections=[reason],
        ),
        future_outcomes=dict(max_favorable_bps=mfe,max_adverse_bps=mae),
    )


class RejectedWinnerStudyTests(unittest.TestCase):
    def test_membership_uses_preentry_fields_only(self):
        a=row(mfe=5000,mae=2000)
        b=row(mfe=-9000,mae=-9000)
        self.assertTrue(study.hypothesis_match(a))
        self.assertTrue(study.hypothesis_match(b))

    def test_membership_requires_frozen_dense_concentration_shape(self):
        self.assertFalse(study.hypothesis_match(row(reason="exit_liquidity")))
        self.assertFalse(study.hypothesis_match(row(events=24)))
        self.assertFalse(study.hypothesis_match(row(events=50,groups=0)))
        self.assertTrue(study.hypothesis_match(row(events=50,groups=1)))

    def test_analysis_never_grants_trading_authority(self):
        body=dict(kind="x",qualification_policy="continuation-v1",natural_results=[
            row(),row(mfe=2500,mae=0),row(mfe=3000,mae=100),
            row(mfe=-100,mae=-2000),row(reason="exit_liquidity",mfe=2000,mae=0),
        ])
        got=study.analyze(body)
        self.assertTrue(got["continuation_v1_unchanged"])
        self.assertFalse(got["automatic_threshold_change"])
        self.assertFalse(got["trading_rule_freeze_permitted"])
        self.assertEqual(got["frozen_hypothesis"]["authority"],"research_only")


    def test_prospective_validation_requires_fresh_sample_and_downside_safety(self):
        rows=[row(mfe=2000,mae=-500) for _ in range(30)]
        controls=[row(events=10,mfe=-500,mae=-1500) for _ in range(30)]
        got=study.prospective_validation_summary(rows+controls)
        self.assertTrue(got["sample_ready"])
        self.assertTrue(got["validation_passed"])
        self.assertFalse(got["trading_authority_granted"])

        risky=[row(mfe=2000,mae=-2000) for _ in range(30)]
        got=study.prospective_validation_summary(risky+controls)
        self.assertTrue(got["sample_ready"])
        self.assertFalse(got["validation_passed"])



if __name__=="__main__":
    unittest.main()
