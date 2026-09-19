import unittest
from unittest.mock import patch

from robinhood_research import BoundaryError

from robinhood_research.continuation_robinhood import POLICY, POLICY_HASH, REFERENCE_ENTRY_WEI
from robinhood_research.continuation_robinhood_cohort import (
    COHORT_TARGET, ENTRY_DELAY_SECONDS, MAX_HOLD_SECONDS, MONITOR_SECONDS,
    PAPER_AMOUNT, PAPER_CAPITAL, RISK_BPS, TAKE_PROFIT_BPS, _paper_decision,
    _poll, _recover_discovery,
)


class _Feed:
    def __init__(self, value):
        self.value=value
    def wait_for_after(self, cursor, timeout):
        if isinstance(self.value,Exception):
            raise self.value
        return self.value


class ContinuationCohortTests(unittest.TestCase):
    def test_cohort_keeps_frozen_policy_and_actual_exit_path(self):
        self.assertEqual(COHORT_TARGET,10)
        self.assertEqual(PAPER_AMOUNT,REFERENCE_ENTRY_WEI)
        self.assertEqual(PAPER_CAPITAL,REFERENCE_ENTRY_WEI*20)
        self.assertEqual(ENTRY_DELAY_SECONDS,2)
        self.assertEqual(MONITOR_SECONDS,5)
        self.assertEqual(TAKE_PROFIT_BPS,1500)
        self.assertEqual(RISK_BPS,-1000)
        self.assertEqual(MAX_HOLD_SECONDS,900)

    def test_transport_failure_recovers_without_advancing_cursor(self):
        class Rpc:
            used=0
            def __init__(self,fail=False):
                self.fail=fail
            def call(self,method,params,scope):
                if self.fail:
                    raise BoundaryError("provider_transport_failure")
                return {"number":"0x10"}
            def telemetry(self):
                return {"requests":1}
        first=Rpc(True);replacement=Rpc(False)
        result={"discovery_sessions":[],"provider_recoveries":[]}
        with patch("robinhood_research.continuation_robinhood_cohort._current_curve_events",
                   return_value=[]),              patch("robinhood_research.continuation_robinhood_cohort._recover_discovery",
                   return_value=replacement) as recover:
            rpc,cursor,fresh,header=_poll(
                "https://example.invalid",first,10,[],result,_Feed(16)
            )
        self.assertIs(rpc,replacement)
        self.assertEqual(cursor,16)
        self.assertEqual(fresh,[])
        self.assertEqual(header["number"],"0x10")
        self.assertEqual(recover.call_args.args[3],10)

    def test_nontransport_boundary_does_not_reconnect(self):
        class Rpc:
            used=0
            def call(self,*_,**__):
                raise BoundaryError("provider_rpc_-32000")
            def telemetry(self):
                return {}
        with patch("robinhood_research.continuation_robinhood_cohort._recover_discovery") as recover:
            with self.assertRaisesRegex(BoundaryError,"provider_rpc_-32000"):
                _poll(
                    "https://example.invalid",Rpc(),77,[],
                    {"discovery_sessions":[]},_Feed(78)
                )
        recover.assert_not_called()

    def test_sequencer_gap_does_not_fallback_to_http_discovery(self):
        class Rpc:
            used=0
            def telemetry(self):
                return {}
        with patch("robinhood_research.continuation_robinhood_cohort._recover_discovery") as recover:
            with self.assertRaisesRegex(BoundaryError,"continuity_lost"):
                _poll(
                    "https://example.invalid",Rpc(),77,[],
                    {"discovery_sessions":[]},
                    _Feed(BoundaryError("sequencer_discovery_continuity_lost")),
                )
        recover.assert_not_called()

    def test_reconnect_verifies_new_session_before_resume(self):
        class Fake:
            used=0
            def __init__(self,fail=False):
                self.fail=fail
            def verify_chain(self):
                if self.fail:
                    raise BoundaryError("provider_transport_failure")
                return 4663
            def telemetry(self):
                return {"fail":self.fail}
        broken=Fake(True);good=Fake(False)
        result={"discovery_sessions":[],"provider_recoveries":[]}
        with patch(
            "robinhood_research.continuation_robinhood_cohort.sample_discovery_rpc",
            side_effect=[broken,good],
        ), patch("robinhood_research.continuation_robinhood_cohort.time.sleep"):
            recovered=_recover_discovery(
                "https://example.invalid",None,result,123,
                BoundaryError("provider_transport_failure"),
            )
        self.assertIs(recovered,good)
        self.assertEqual(result["provider_recoveries"][0]["cursor"],123)
        self.assertEqual(result["provider_recoveries"][-1]["attempt"],2)

    def test_paper_decision_requires_exact_frozen_policy(self):
        row=dict(
            curve="0x"+"11"*20,token="0x"+"22"*20,source_transaction="0xabc",
            vector=dict(
                asof=100,evidence_available_at=104,decision_state_age_seconds=4,
            ),
        )
        d=_paper_decision(row,104)
        self.assertEqual(d["policy"],POLICY)
        self.assertEqual(d["policy_hash"],POLICY_HASH)
        self.assertEqual(d["qualification"],"qualified")
        self.assertEqual(d["authority"],"frozen_policy_paper")
        self.assertFalse(d["outcome_used_for_selection"])


if __name__=="__main__":
    unittest.main()
