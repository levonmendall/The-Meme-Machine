import unittest
from types import SimpleNamespace
from tests.lanes.pump import pump_acceleration_natural_prospective as runner

class MarketScopeEfficiencyTests(unittest.TestCase):
    def test_postgrad_holder_scan_only_needed_after_optimistic_pass(self):
        reject=SimpleNamespace(qualified=False)
        accept=SimpleNamespace(qualified=True)
        self.assertFalse(runner._postgrad_concentration_required(reject,None))
        self.assertTrue(runner._postgrad_concentration_required(reject,accept))
        self.assertTrue(runner._postgrad_concentration_required(accept,reject))

if __name__ == "__main__":
    unittest.main()
