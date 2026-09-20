import unittest

from meme_machine.pump_acceleration_strategy import policy_hash

FROZEN="bb2631d83f5be287a0afc01dfc6d7a4da8b7086ae0afd09dfbf27df6d9d66a6e"


class FrozenPolicyIdentityTests(unittest.TestCase):
    def test_exact_frozen_policy_hash(self):
        self.assertEqual(policy_hash(),FROZEN)


if __name__=="__main__":
    unittest.main()
