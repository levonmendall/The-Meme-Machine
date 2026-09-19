import ast
import os
from pathlib import Path
import tempfile
import unittest

from robinhood_research import BoundaryError
from robinhood_research.ramses_strategy import (
    POLICY_HASH,
    STRATEGY_DOMAIN,
    STRATEGY_VERSION,
)
from robinhood_research.ramses_strategy_ledger import RamsesStrategyLedger


class RamsesStrategyIsolationTests(unittest.TestCase):
    def _path(self):
        fd, path = tempfile.mkstemp(prefix="ramses-strategy-", suffix=".sqlite")
        os.close(fd)
        os.unlink(path)
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))
        return path

    def _decision(self, capital=100):
        return dict(
            mode="fee_pulse",
            qualified=True,
            allocation_authority=False,
            strategy_domain=STRATEGY_DOMAIN,
            strategy_version=STRATEGY_VERSION,
            policy_hash=POLICY_HASH,
            freeze=dict(
                proposal_hash="frozen-test",
                proposals=[dict(capital_employed=capital)],
            ),
        )

    def test_independent_ledger_never_uses_shared_allocator(self):
        ledger = RamsesStrategyLedger(
            self._path(), paper_capital=1000, quote_asset="0x" + "11" * 20
        )
        reserved = ledger.reserve(
            "one", pool="0x" + "22" * 20, decision=self._decision(100), at=1
        )
        self.assertFalse(reserved["shared_allocator"])
        ledger.open("one", at=2)
        settled = ledger.settle(
            "one",
            pnl=dict(
                strategy_domain=STRATEGY_DOMAIN,
                net_result_quote=7,
                unresolved_inventory=None,
            ),
            at=3,
        )
        self.assertEqual(settled["status"], "settled")
        rec = ledger.reconcile()
        self.assertFalse(rec["shared_allocator"])
        self.assertEqual(rec["realized"], 7)
        self.assertEqual(rec["committed"], 0)
        ledger.close()

    def test_foreign_strategy_decision_cannot_enter_ledger(self):
        ledger = RamsesStrategyLedger(
            self._path(), paper_capital=1000, quote_asset="0x" + "11" * 20
        )
        foreign = self._decision()
        foreign["strategy_domain"] = "pons-directional"
        with self.assertRaisesRegex(
            BoundaryError, "foreign_or_unqualified_strategy_decision"
        ):
            ledger.reserve(
                "foreign", pool="0x" + "22" * 20, decision=foreign, at=1
            )
        ledger.close()

    def test_foreign_outcome_cannot_settle_ramses_position(self):
        ledger = RamsesStrategyLedger(
            self._path(), paper_capital=1000, quote_asset="0x" + "11" * 20
        )
        ledger.reserve(
            "one", pool="0x" + "22" * 20, decision=self._decision(100), at=1
        )
        ledger.open("one", at=2)
        with self.assertRaisesRegex(BoundaryError, "foreign_strategy_outcome"):
            ledger.settle(
                "one",
                pnl=dict(
                    strategy_domain="continuation-v1-robinhood",
                    net_result_quote=5,
                    unresolved_inventory=None,
                ),
                at=3,
            )
        ledger.close()

    def test_strategy_modules_have_no_other_strategy_imports(self):
        root = Path(__file__).parents[1] / "robinhood_research"
        modules = [
            "ramses_strategy.py",
            "ramses_strategy_ledger.py",
            "ramses_strategy_sample.py",
            "ramses_universe.py",
            "ramses_all_pool_lifecycle.py",
        ]
        forbidden = (
            "meme_machine",
            "pons",
            "continuation_robinhood",
            "directional",
            "fomo",
        )
        for name in modules:
            tree = ast.parse((root / name).read_text())
            imported = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    imported.append(node.module or "")
            for module in imported:
                self.assertFalse(
                    any(token in module for token in forbidden),
                    (name, module),
                )


if __name__ == "__main__":
    unittest.main()
