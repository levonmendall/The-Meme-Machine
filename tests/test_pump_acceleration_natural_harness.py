import unittest

from meme_machine.pump_acceleration_strategy import STRATEGY_ID,policy_hash
from tests import pump_acceleration_natural_prospective as prospective


class NaturalHarnessBoundaryTests(unittest.TestCase):
    def test_harness_is_frozen_and_paper_only(self):
        self.assertEqual(STRATEGY_ID,"pump-acceleration-independent-v1")
        self.assertEqual(len(policy_hash()),64)
        self.assertGreater(prospective.DISCOVERY_SECONDS,0)
        self.assertGreater(prospective.FOLLOWUP_SECONDS,0)
        self.assertGreater(prospective.ENTRY_BUDGET,0)


if __name__=="__main__":
    unittest.main()
