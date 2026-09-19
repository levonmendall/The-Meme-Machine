import ast
import inspect
from pathlib import Path
import tempfile
import unittest

from robinhood_research.pons_relative_value import (
    reserve_relative_return_bps, relative_value_vector, STRATEGY as RELATIVE_STRATEGY,
)
from robinhood_research.paper import Paper
from robinhood_research.pons_selective_ledger import SelectivePaper
from robinhood_research.pons_selective_wallets import (
    WalletSkillBook, NAMESPACE as WALLET_NAMESPACE,
)


ROOT=Path(__file__).resolve().parents[1]
SELECTIVE_FILES=[
    ROOT/"robinhood_research"/"pons_selective_continuation.py",
    ROOT/"robinhood_research"/"pons_selective_ledger.py",
    ROOT/"robinhood_research"/"pons_selective_acquisition.py",
    ROOT/"robinhood_research"/"pons_selective_wallets.py",
    ROOT/"robinhood_research"/"pons_selective_v4.py",
    ROOT/"robinhood_research"/"pons_selective_paper.py",
    ROOT/"robinhood_research"/"pons_selective_cohort.py",
    ROOT/"robinhood_research"/"pons_breakout_sample.py",
    ROOT/"robinhood_research"/"pons_relative_value.py",
    ROOT/"robinhood_research"/"pons_relative_sample.py",
]
FORBIDDEN_PREFIXES=(
    "robinhood_research.continuation_robinhood",
    "robinhood_research.ramses",
    "meme_machine.",
)


class StrategyIndependenceTests(unittest.TestCase):
    def test_selective_lane_imports_no_other_strategy_module(self):
        bad=[]
        for path in SELECTIVE_FILES:
            tree=ast.parse(path.read_text(),filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node,ast.Import):
                    names=[alias.name for alias in node.names]
                elif isinstance(node,ast.ImportFrom):
                    if node.level:
                        # Resolve the relative module under robinhood_research.
                        module="robinhood_research."+str(node.module or "")
                    else:
                        module=str(node.module or "")
                    names=[module]
                else:
                    continue
                for name in names:
                    if any(name.startswith(prefix) for prefix in FORBIDDEN_PREFIXES):
                        bad.append((path.name,name))
        self.assertEqual(bad,[])


    def test_partial_exit_surface_exists_only_on_selective_ledger(self):
        generic=inspect.signature(Paper.advance)
        selective=inspect.signature(SelectivePaper.advance)
        self.assertNotIn("exit_tokens",generic.parameters)
        self.assertIn("exit_tokens",selective.parameters)
        generic_source=inspect.getsource(Paper)
        self.assertNotIn("pending_exit_tokens",generic_source)
        self.assertNotIn("pons_selective_paper",generic_source)

    def test_strategy_owned_artifact_namespaces_are_distinct(self):
        cohort=(ROOT/"robinhood_research"/"pons_selective_cohort.py").read_text()
        self.assertIn("pons-selective-continuation-v1-cohort",cohort)
        self.assertIn("shared_allocator=False",cohort)
        self.assertNotIn("robinhood-continuation-v1-cohort.json",cohort)
        self.assertNotIn("RAMSES",cohort.upper())

    def test_wallet_skill_book_is_strategy_local_and_point_in_time(self):
        with tempfile.TemporaryDirectory() as td:
            book=WalletSkillBook(td+"/skill.sqlite")
            self.assertEqual(WALLET_NAMESPACE,"pons-selective-continuation-v1")
            for i in range(20):
                book.record_completed_trade(
                    trade_id=f"t{i}",group="0x"+"11"*20,
                    token="0x"+f"{i+1:040x}",entry_at=10+i,exit_at=20+i,
                    observed_at=20+i,realized_after_cost_pnl=10,
                )
            early=book.profiles(asof=25)
            self.assertEqual(early[0]["completed_trades"],6)
            full=book.profiles(asof=100)
            self.assertEqual(full[0]["completed_trades"],20)
            self.assertGreater(full[0]["realized_after_cost_pnl"],0)
            self.assertEqual(full[0]["namespace"],WALLET_NAMESPACE)
            book.close()

    def test_relative_value_is_separate_research_lane(self):
        self.assertEqual(RELATIVE_STRATEGY,"pons-quote-relative-value-v1")
        # Quote/token price rises from 1 to 1.10 => +10% versus quote asset.
        self.assertEqual(
            reserve_relative_return_bps(100,100,110,100),1000
        )


if __name__=="__main__":
    unittest.main()
