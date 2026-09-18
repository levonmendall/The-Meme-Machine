import unittest

from robinhood_research import BoundaryError
from robinhood_research.evidence import Stamp, Store
from robinhood_research.finality import Finality
from robinhood_research.paper import Paper, Quote

MARKET="0x"+"11"*20


class NaturalPaperProofTests(unittest.TestCase):
    def _ledger(self,store,scope,block,at):
        stamp=Stamp(4663,block,f"h{block}",at,at,"confirmed","natural")
        ledger=Finality(store,scope=scope,max_blocks=4)
        ledger.observe(stamp,f"p{block}")
        return stamp,ledger

    def test_default_natural_authority_remains_disabled(self):
        store=Store(":memory:")
        paper=Paper(store,"default",10**18)
        decision=dict(
            asof=100,market=MARKET,authority="bounded_lifecycle_proof_only",
            qualification="policy_not_established",
        )
        with self.assertRaisesRegex(BoundaryError,"policy_not_established"):
            paper.reserve("p",market=MARKET,amount=10**16,gas_budget=10**15,
                          now=100,features=decision,kind="natural")
        store.close()

    def test_explicit_natural_proof_requires_confirmed_ledger_and_settles(self):
        store=Store(":memory:")
        paper=Paper(store,"proof",10**18,natural_proof=True,delay=2)
        decision=dict(
            asof=100,market=MARKET,authority="bounded_lifecycle_proof_only",
            qualification="policy_not_established",
            selection_rule="first_current_authenticated_pons_v2_curve_after_start",
        )
        paper.reserve("p",market=MARKET,amount=10**16,gas_budget=10**15,
                      now=100,features=decision,kind="natural")

        entry_stamp,entry_ledger=self._ledger(store,"entry",102,102)
        entry=Quote(MARKET,"buy",10**16,20_000,100,50,entry_stamp)
        with self.assertRaisesRegex(BoundaryError,"unfinalized"):
            paper.advance("p",now=102,action="entry",quote=entry)
        opened=paper.advance("p",now=102,action="entry",quote=entry,
                             finality_ledger=entry_ledger)
        self.assertEqual(opened["status"],"open")

        paper.advance("p",now=110,action="exit_intent")
        exit_stamp,exit_ledger=self._ledger(store,"exit",112,112)
        closed=paper.advance(
            "p",now=112,action="exit",
            quote=Quote(MARKET,"sell",20_000,11_000_000_000_000_000,100,50,exit_stamp),
            finality_ledger=exit_ledger,
        )
        self.assertEqual(closed["status"],"settled")
        self.assertEqual(paper.reconcile()["open_exposure"],0)
        store.close()


if __name__=="__main__":
    unittest.main()
