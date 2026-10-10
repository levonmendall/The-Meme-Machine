import unittest
from unittest.mock import patch

from meme_machine.lanes.pump.pump_acceleration_strategy import STRATEGY_ID,policy_hash
from meme_machine.lanes.pump import runner as prospective


class NaturalHarnessBoundaryTests(unittest.TestCase):
    def test_fill_timeout_is_rechecked_after_provider_returns(self):
        clock=[102]
        class Life:
            def __init__(self): self.cancelled=None
            def cancel(self,reason,now): self.cancelled=(reason,now)
        class Pump:
            def snapshot(self,*_args,**_kwargs):
                clock[0]=121
                return {}
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
        prospective.time.time=lambda:clock[0]
        try:
            prospective._fill_pending({},pending,{},Sessions(),{},102)
        finally:
            prospective.time.time=original
        self.assertEqual(pending,{})
        self.assertEqual(life.cancelled,("entry_fill_timeout",121))

    def test_expired_reservation_never_acquires_another_fill_quote(self):
        class Life:
            def cancel(self,reason,now):self.cancelled=(reason,now)
        class Sessions:
            def ensure(self,_needed):raise AssertionError('expired entry acquired provider capacity')
        life=Life();key=('MINT',prospective.MODE_LATE_CURVE)
        pending={key:dict(lifecycle=life,reserved_at=100,due=102,qualifier_row={})}
        with patch.object(prospective.time,'time',return_value=120):
            prospective._fill_pending({},pending,{},Sessions(),{},120)
        self.assertEqual(life.cancelled,('entry_fill_timeout',120))
        self.assertFalse(pending)

    def test_too_early_quote_is_rechecked_before_research_resumes(self):
        # Reproduce the smoke's first quote at reserve+11, too early on the
        # finalized clock. Research would take ten seconds and miss reserve+20.
        clock=[111];order=[];row=dict(reserved_at=100,due=102)
        pending={'entry':row}
        def fill(*args):
            order.append(('fill',clock[0]))
            self.assertEqual(row['reserved_at'],100)
            if clock[0]>=112:pending.clear()
        def sleep(seconds):clock[0]+=seconds
        with patch.object(prospective.time,'time',side_effect=lambda:clock[0]),\
                patch.object(prospective.time,'sleep',side_effect=sleep),\
                patch.object(prospective,'_fill_pending',side_effect=fill):
            prospective._service_pending_entries({},pending,{},None,{},
                monitor=lambda:order.append(('monitor',clock[0])))
            order.append(('research',clock[0]))
        self.assertEqual(order,[('monitor',111),('fill',111),('monitor',112),('fill',112),('research',112)])
        self.assertLess(clock[0],row['reserved_at']+prospective.ENTRY_FILL_TIMEOUT_SECONDS)

    def test_harness_is_frozen_and_paper_only(self):
        self.assertEqual(STRATEGY_ID,"pump-acceleration-independent-v1")
        self.assertEqual(len(policy_hash()),64)
        self.assertGreater(prospective.DISCOVERY_SECONDS,0)
        self.assertGreater(prospective.FOLLOWUP_SECONDS,0)
        self.assertGreater(prospective.ENTRY_BUDGET,0)


if __name__=="__main__":
    unittest.main()


class ReservationClockRegression(unittest.TestCase):
    def test_evidence_latency_cannot_backdate_reservation(self):
        from types import SimpleNamespace
        q=SimpleNamespace(mint='mint',observed_at=90,score=70,reasons=[],confirmations=[],policy_hash=policy_hash())
        signal=SimpleNamespace(repeat_buyer_clusters=3,repeat_buy_share_bps=6000)
        pending={};report={'qualifiers':[]}
        with patch.object(prospective.time,'time',return_value=107), \
                patch.object(prospective,'PumpAccelerationPaperLifecycle') as life, \
                patch.object(prospective,'ACCOUNTING',None), \
                patch.object(prospective,'FILL_PERSISTENCE_CONTEXT',None):
            prospective._reserve_position(report,pending,{},signal,q,{'available_time':100,'slot':1},prospective.MODE_POSTGRAD)
        row=report['qualifiers'][0]
        self.assertEqual(row['reserved_at'],107)
        self.assertEqual(row['decision_evidence_available_at'],100)
        self.assertEqual(row['fill_due'],107+prospective.ENTRY_DELAY_SECONDS)
        life.return_value.reserve.assert_called_once_with(q,prospective.ENTRY_BUDGET+prospective.GAS,107)
