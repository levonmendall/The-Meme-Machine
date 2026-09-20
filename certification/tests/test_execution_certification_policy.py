import json
from pathlib import Path
import unittest


class ExecutionCertificationPolicyTests(unittest.TestCase):
    def test_all_lanes_are_isolated_nonprofitability_revisions(self):
        spec=json.loads((Path(__file__).parents[1]/"sources.json").read_text())
        expected={
            "pump":"cert/pump-execution-cert-v1",
            "meteora":"cert/meteora-execution-cert-v1",
            "pons":"cert/pons-execution-cert-v1",
            "ramses":"cert/ramses-execution-cert-v1",
        }
        for lane,branch in expected.items():
            row=spec["lanes"][lane]
            self.assertEqual(row["source_branch"],branch)
            self.assertFalse(row["execution_certification"]["profitability_authority"])
            self.assertEqual(row["execution_certification"]["target_restrictiveness"],"~5/10")
            self.assertEqual(len(row["policy_hash"]),64)
            self.assertNotEqual(row["source_sha"],row["execution_certification"]["original_source_sha"])

    def test_integrity_files_do_not_relabel_relaxed_strategy_source_as_original(self):
        spec=json.loads((Path(__file__).parents[1]/"sources.json").read_text())
        changed={
            "pump":"meme_machine/pump_acceleration_strategy.py",
            "meteora":"SOLANA_DLMM_INDEPENDENT_V1.json",
            "pons":"robinhood_research/pons_selective_continuation.py",
            "ramses":"robinhood_research/ramses_strategy.py",
        }
        for lane,path in changed.items():
            self.assertNotIn(path,spec["lanes"][lane]["file_hashes"])


if __name__=="__main__":
    unittest.main()
