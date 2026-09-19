import hashlib
import json
import os
import tempfile
import unittest

from robinhood_research import BoundaryError
from robinhood_research.ramses_paper import AUTHORITY, RamsesPaper


def _freeze():
    proposal=dict(
        quote_side="y",
        capital_employed=100,
        token_requirements=[0,100],
        bins=[10],
        allocations=[dict(bin_id=10,shares=5,deposited=[0,100])],
    )
    h=hashlib.sha256(json.dumps([proposal],sort_keys=True,separators=(",",":")).encode()).hexdigest()
    return dict(frozen=True,allocation_authority=False,hurdle_bps=35,proposal_hash=h,proposals=[proposal])


class ForcedRamsesPaperTests(unittest.TestCase):
    def _path(self):
        fd,path=tempfile.mkstemp(prefix="ramses-paper-",suffix=".sqlite")
        os.close(fd);os.unlink(path)
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))
        return path

    def test_forced_lifecycle_survives_entry_and_settlement_restart(self):
        path=self._path();freeze=_freeze();identity="forced:test"
        paper=RamsesPaper(path,100)
        reserved=paper.reserve(identity,pool="0x"+"11"*20,freeze=freeze,proposal_index=0,
                               block=123,block_hash="0x"+"22"*32,at=1000)
        self.assertEqual(reserved["status"],"reserved")
        opened=paper.enter(identity,at=1000)
        self.assertEqual(opened["status"],"open")
        first=paper.reconcile();paper.close()

        paper=RamsesPaper(path,100)
        self.assertEqual(paper.reconcile(),first)
        self.assertEqual(paper.position(identity)["status"],"open")
        paper.exit_intent(identity,at=1060)
        outcome=dict(unresolved_inventory=None,gross_result=7,after_cost_result=None)
        settled=paper.finish(identity,outcome=outcome,at=1060)
        self.assertEqual(settled["status"],"settled")
        final=paper.reconcile();paper.close()

        paper=RamsesPaper(path,100)
        self.assertEqual(paper.reconcile(),final)
        got=paper.position(identity)
        self.assertEqual(got["authority"],AUTHORITY)
        self.assertFalse(got["strategy_evidence_eligible"])
        self.assertEqual(got["realized_before_costs"],7)
        self.assertEqual(got["reserved"],0)
        self.assertEqual(paper.reconcile()["open_positions"],0)
        paper.close()

    def test_unresolved_unwind_preserves_open_capital(self):
        path=self._path();freeze=_freeze();identity="forced:unresolved"
        paper=RamsesPaper(path,100)
        paper.reserve(identity,pool="0x"+"33"*20,freeze=freeze,proposal_index=0,
                      block=1,block_hash="0x"+"44"*32,at=10)
        paper.enter(identity,at=10)
        paper.exit_intent(identity,at=70)
        outcome=dict(unresolved_inventory="unwind_liquidity_unavailable",gross_result=None,after_cost_result=None)
        got=paper.finish(identity,outcome=outcome,at=70)
        self.assertEqual(got["status"],"unresolved")
        rec=paper.reconcile()
        self.assertEqual(rec["committed"],100)
        self.assertEqual(rec["open_positions"],1)
        paper.close()

    def test_duplicate_reservation_and_authority_cannot_be_reused(self):
        path=self._path();freeze=_freeze();identity="forced:duplicate"
        paper=RamsesPaper(path,100)
        paper.reserve(identity,pool="0x"+"55"*20,freeze=freeze,proposal_index=0,
                      block=1,block_hash="0x"+"66"*32,at=1)
        with self.assertRaisesRegex(BoundaryError,"duplicate_ramses_paper_reservation"):
            paper.reserve(identity,pool="0x"+"55"*20,freeze=freeze,proposal_index=0,
                          block=1,block_hash="0x"+"66"*32,at=1)
        self.assertFalse(paper.reconcile()["strategy_evidence_eligible"])
        paper.close()


if __name__=="__main__":
    unittest.main()
