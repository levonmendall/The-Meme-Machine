import unittest

from meme_machine.pump_acceleration_strategy import policy_hash

FROZEN="d623ff03ad19b2c4dcd8a82d4883c188ba1acd35a721582175d85cd1b0191770"


class FrozenPolicyIdentityTests(unittest.TestCase):
    def test_exact_frozen_policy_hash(self):
        self.assertEqual(policy_hash(),FROZEN)


if __name__=="__main__":
    unittest.main()
