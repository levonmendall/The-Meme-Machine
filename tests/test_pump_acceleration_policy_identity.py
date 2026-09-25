import unittest

from meme_machine.pump_acceleration_strategy import policy_hash

FROZEN="825084f162efdc10ca4d1faad747902b858bb6e7b4441f7ff48bf089a182f28b"


class FrozenPolicyIdentityTests(unittest.TestCase):
    def test_exact_frozen_policy_hash(self):
        self.assertEqual(policy_hash(),FROZEN)


if __name__=="__main__":
    unittest.main()
