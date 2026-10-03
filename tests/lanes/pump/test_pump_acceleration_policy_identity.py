import unittest

from meme_machine.lanes.pump.pump_acceleration_strategy import policy_hash

FROZEN="a57c69b4eddfbcff624834869c6ceb34900828d1c59cf84d3d3e004197c24b4d"


class FrozenPolicyIdentityTests(unittest.TestCase):
    def test_exact_frozen_policy_hash(self):
        self.assertEqual(policy_hash(),FROZEN)


if __name__=="__main__":
    unittest.main()
