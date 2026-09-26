from pathlib import Path
import unittest
from certification.pons_entry_confirmation_replay import replay

class RetainedPonsEntryReplayTests(unittest.TestCase):
    def test_preserved_attempts_keep_hard_and_persistence_failures(self):
        result=replay(Path(__file__).resolve().parents[1]/'evidence/robinhood-runs-355-368.json.gz')
        self.assertEqual(len(result['attempts']),7)
        self.assertEqual(result['stale_only_among_hard_invalidators'],4)
        self.assertEqual(result['additional_hard_invalidators'],3)
        for row in result['attempts']:
            self.assertEqual(row['counterfactual_fill'],'UNMEASURABLE')
            self.assertEqual(row['profit'],'UNMEASURABLE')
            self.assertTrue(row['retained_persistence_reasons'])
