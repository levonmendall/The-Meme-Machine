import unittest

from meme_machine.pump_acceleration_strategy import policy_hash

FROZEN="561ce76a334d9cdcd3b4888a9aaee24d11c9eb43f1ca20c5b806940297018bfc"


class FrozenPolicyIdentityTests(unittest.TestCase):
    def test_exact_frozen_policy_hash(self):
        self.assertEqual(policy_hash(),FROZEN)


if __name__=="__main__":
    unittest.main()
