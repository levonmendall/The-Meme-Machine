import unittest
from tests.onfinality_sustained_rate_probe import classify_rate


class SustainedRateClassification(unittest.TestCase):
    def test_clean_or_single_non429_failure_can_be_stable(self):
        self.assertTrue(classify_rate(12,12,0,0)["stable"])
        self.assertTrue(classify_rate(11,12,0,1)["stable"])

    def test_any_429_makes_rate_unstable(self):
        self.assertFalse(classify_rate(11,12,1,0)["stable"])

    def test_material_failure_is_unstable(self):
        self.assertFalse(classify_rate(10,12,0,2)["stable"])


if __name__=="__main__":
    unittest.main()
