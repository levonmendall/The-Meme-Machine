import json
from pathlib import Path
import unittest

FIXTURE=Path(__file__).parent/"fixtures"/"pons_paper_lifecycle_35382359016.json"


class CapturedNaturalPaperLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.row=json.loads(FIXTURE.read_text())

    def test_mainnet_proof_is_settled_and_has_no_residual_exposure(self):
        row=self.row
        self.assertEqual(row["source_run"],35382359016)
        self.assertFalse(row["strategy_authority"])
        self.assertEqual(row["proof_authority"],"bounded_lifecycle_proof_only")
        self.assertEqual(row["final"]["status"],"settled")
        self.assertEqual(row["final"]["tokens"],0)
        self.assertEqual(row["final"]["reserved"],0)
        self.assertEqual(row["final"]["open_exposure"],0)
        self.assertFalse(row["carried_through_graduation"])

    def test_entry_exit_and_realized_pnl_arithmetic(self):
        row=self.row
        net=row["exit"]["gross_quote_out"]-row["exit"]["gas_quote"]
        self.assertEqual(net,row["exit"]["net_quote_out"])
        self.assertEqual(net-row["entry"]["cost"],row["exit"]["realized_pnl"])
        self.assertEqual(
            10**18+row["exit"]["realized_pnl"],
            row["final"]["available_capital"],
        )
        self.assertLessEqual(row["monitor"]["return_bps"],-1000)
        self.assertEqual(row["monitor"]["exit_reason"],"risk")

    def test_provider_clean_and_no_profitability_claim(self):
        row=self.row
        self.assertEqual(row["provider"]["failures"],0)
        self.assertEqual(row["provider"]["retries"],0)
        self.assertFalse(row["profitability_claim"])


if __name__=="__main__":
    unittest.main()
