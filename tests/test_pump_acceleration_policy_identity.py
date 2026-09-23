import unittest

from meme_machine.pump_acceleration_strategy import policy_hash

FROZEN="b7718de9298e4c825616bed26c87731a65f43c4b12f152b14e1d574eb86eb8d5"


class FrozenPolicyIdentityTests(unittest.TestCase):
    def test_exact_frozen_policy_hash(self):
        self.assertEqual(policy_hash(),FROZEN)


if __name__=="__main__":
    unittest.main()
