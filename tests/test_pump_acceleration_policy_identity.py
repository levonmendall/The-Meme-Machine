import unittest

from meme_machine.pump_acceleration_strategy import policy_hash

FROZEN="b273bc6be47d4f5a65f39d5d4f616777e02cbe547e19b7a07b0fefe23970c246"


class FrozenPolicyIdentityTests(unittest.TestCase):
    def test_exact_frozen_policy_hash(self):
        self.assertEqual(policy_hash(),FROZEN)


if __name__=="__main__":
    unittest.main()
