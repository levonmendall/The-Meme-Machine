import unittest

from meme_machine.pump_acceleration_strategy import STRATEGY_ID,policy_hash
from tests import pump_acceleration_natural_prospective as prospective


class NaturalHarnessBoundaryTests(unittest.TestCase):
    def test_fill_timeout_is_rechecked_after_provider_returns(self):
        class Life:
            def __init__(self): self.cancelled=None
            def cancel(self,reason,now): self.cancelled=(reason,now)
        class Pump:
            def snapshot(self,*_args,**_kwargs): return {}
        class Sessions:
            pump=Pump()
            def ensure(self,_needed): return None

        life=Life()
        key=("MINT",prospective.MODE_LATE_CURVE)
        pending={key:dict(
            lifecycle=life,reserved_at=100,due=102,decision_slot=1,
            qualifier_row={},last_concentration=0,
        )}
        original=prospective.time.time
        prospective.time.time=lambda:121
        try:
            prospective._fill_pending({},pending,{},Sessions(),{},102)
        finally:
            prospective.time.time=original
        self.assertEqual(pending,{})
        self.assertEqual(life.cancelled,("entry_fill_timeout",121))

    def test_harness_is_frozen_and_paper_only(self):
        self.assertEqual(STRATEGY_ID,"pump-acceleration-independent-v1")
        self.assertEqual(len(policy_hash()),64)
        self.assertGreater(prospective.DISCOVERY_SECONDS,0)
        self.assertGreater(prospective.FOLLOWUP_SECONDS,0)
        self.assertGreater(prospective.ENTRY_BUDGET,0)


if __name__=="__main__":
    unittest.main()
