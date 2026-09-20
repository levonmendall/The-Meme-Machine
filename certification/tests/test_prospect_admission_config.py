import json
from pathlib import Path
import unittest

from certification import run


class ProspectAdmissionConfigurationTests(unittest.TestCase):
    def test_only_overbroad_lanes_receive_behavioral_overrides(self):
        self.assertIn("pump",run.OVERRIDES)
        self.assertIn("pons",run.OVERRIDES)
        self.assertNotIn("meteora",run.OVERRIDES)
        self.assertNotIn("ramses",run.OVERRIDES)

    def test_manifest_distinguishes_observation_from_investment_evaluation(self):
        spec=json.loads((Path(__file__).parents[1]/"sources.json").read_text())
        self.assertFalse(spec["prospect_admission"]["strategy_thresholds_changed"])
        for lane in ("pump","pons","meteora","ramses"):
            row=spec["lanes"][lane]["prospect_admission"]
            self.assertIn("market_observation_scope",row)
            self.assertIn("investment_evaluation_scope",row)
            self.assertFalse(row["strategy_thresholds_changed"])


if __name__=="__main__":
    unittest.main()
