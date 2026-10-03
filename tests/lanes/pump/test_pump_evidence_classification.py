"""Lane-local attribution must not relabel normal screening as evidence loss."""
import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

from meme_machine.lanes.pump.pipeline import Pipeline
from meme_machine.lanes.pump.pump_acceleration_strategy import SignalVector,qualify
from tests.lanes.pump import pump_acceleration_natural_prospective as runner


class EvidenceClassificationTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.pipeline=Pipeline(Path(self.directory.name)/"pipeline.sqlite","pump",
                               runner.FROZEN_POLICY_HASH)
        self.addCleanup(self.pipeline.close)
        self.patch=patch.object(runner,"PIPELINE",self.pipeline)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_retirement_does_not_create_or_erase_reconstruction_loss(self):
        runner._progress("incomplete","terminal","incomplete_pumpswap_decision_window",
                         mode=runner.MODE_POSTGRAD)
        runner._progress("incomplete","terminal","postgrad_entry_horizon_expired")
        runner._progress("fully_screened","terminal","postgrad_entry_horizon_expired")
        self.assertEqual(self.pipeline.classes["reconstruction_incomplete"],{"incomplete"})
        self.assertEqual(self.pipeline.classes["superseded_candidate_state"],
                         {"incomplete","fully_screened"})
        self.assertEqual(self.pipeline.records,3)

    def test_prospect_missing_trajectory_is_neither_full_failure_nor_rejection(self):
        runner._progress("prospect","prospect_incomplete","insufficient_curve_trajectory",
                         mode=runner.MODE_LATE_CURVE)
        self.assertEqual(self.pipeline.classes["pre_admission_evidence_incomplete"],{"prospect"})
        self.assertEqual(self.pipeline.classes["reconstruction_incomplete"],set())
        self.assertEqual(self.pipeline.classes["strategy_rejection"],set())
        self.assertEqual(self.pipeline.stages["evidence_requested"],set())

    def test_missing_shape_is_rejection_only_after_complete_authenticated_history(self):
        runner._progress("complete","terminal","missing_pullback",
                         mode=runner.MODE_SECOND_LEG,history={"complete":True})
        runner._progress("unknown","terminal","missing_pullback",
                         mode=runner.MODE_SECOND_LEG)
        runner._progress("incomplete","terminal","incomplete_pumpswap_second_leg_history",
                         mode=runner.MODE_SECOND_LEG,history={"complete":False})
        self.assertEqual(self.pipeline.classes["strategy_rejection"],{"complete"})
        self.assertEqual(self.pipeline.classes["reconstruction_incomplete"],{"unknown","incomplete"})

    def test_valid_preflight_rejection_remains_distinct_from_full_completion(self):
        signal=SignalVector(mint="screened",observed_at=1000,surface="pumpswap",
                            phase=runner.MODE_POSTGRAD,graduated=True,
                            seconds_since_graduation=60,independent_buyer_clusters=1)
        report={"attempts":[],"full_evidence_candidates":[]}
        with patch.object(runner,"ACCOUNTING",None):
            runner._record_attempt(report,signal,qualify(signal),"optimistic_preflight")
        self.assertEqual(self.pipeline.classes["strategy_rejection"],{"screened"})
        self.assertEqual(self.pipeline.stages["evidence_complete"],set())
        self.assertEqual(self.pipeline.stages["evidence_not_required"],{"screened"})
        details=json.loads(self.pipeline.db.execute(
            "SELECT details FROM progress WHERE stage='evidence_not_required'").fetchone()[0])
        self.assertEqual(details["decision_at"],1000)
        self.assertIn("independent_buyers",details["reasons"])
        self.assertEqual(details["remaining_evidence"],"concentration")
        # A new state of this same mint can still require evidence and fail. The
        # earlier valid rejection never clears that later acquisition failure.
        runner._progress("screened","terminal","incomplete_pumpswap_decision_window",
                         mode=runner.MODE_POSTGRAD,decision_at=1010)
        self.assertEqual(self.pipeline.classes["reconstruction_incomplete"],{"screened"})

if __name__=="__main__":
    unittest.main()
