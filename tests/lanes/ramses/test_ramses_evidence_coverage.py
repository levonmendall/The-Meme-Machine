from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from meme_machine.lanes.ramses import BoundaryError
from meme_machine.lanes.ramses import ramses_all_pool_lifecycle as connected
from meme_machine.lanes.ramses import ramses_costs
from meme_machine.lanes.ramses import ramses_extended_test as extended
from meme_machine.lanes.ramses.ramses import authenticate_pool, values
from meme_machine.lanes.ramses.ramses_evidence_coverage import (
    NO_COST_ROUTE, screen_evidence_status, screening_evidence_summary,
)
from meme_machine.lanes.ramses.ramses_strategy import POLICY_HASH, STRATEGY_DOMAIN
from tests.lanes.ramses.test_ramses_extended_market import _decision


FIXTURE = Path(__file__).parent / "fixtures/ramses_cost_routes_35949285193.json"


def _key(method, params):
    return json.dumps([method, params], sort_keys=True, separators=(",", ":"))


class CapturedCostRpc:
    def __init__(self, fixture):
        self.frontiers = {case["block"]: case["block_hash"] for case in fixture["cases"]}
        self.records = {_key(row["method"], row["params"]): row["response"]
                        for row in fixture["rpc_records"]}

    def call(self, method, params, scope=""):
        params = deepcopy(params)
        if isinstance(params[-1], str):
            params[-1] = {"blockHash": self.frontiers[int(params[-1], 16)]}
        if method == "eth_call":
            params[0]["to"] = params[0]["to"].lower()
        elif method == "eth_getCode":
            params[0] = params[0].lower()
        # Missing or differently pinned requests cannot use invented data.
        return self.records[_key(method, params)]

    def batch(self, calls, scope=""):
        return [self.call(method, params, scope) for method, params in calls]


class RamsesEvidenceCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(FIXTURE.read_text())

    def _screen_row(self, case, conversion):
        observed = case["observed_screen"]
        return dict(pool=case["candidate"]["pool"],
            decision=dict(qualified=False, reasons=observed["reasons"]),
            cost_evidence=dict(observed["cost_evidence"], conversion=conversion))

    def test_all_seventeen_captured_screens_have_completed_negative_cost_routes(self):
        rpc = CapturedCostRpc(self.fixture)
        screens = []
        for case in self.fixture["cases"]:
            with self.subTest(pool=case["candidate"]["pool"], block=case["block"]):
                auth = authenticate_pool(case["candidate_runtime"], factory_member=True)
                self.assertEqual(auth["token_x"], case["candidate"]["token_x"])
                self.assertEqual(auth["token_y"], case["candidate"]["token_y"])
                with patch.object(ramses_costs, "_wnative", return_value=self.fixture["wnative"]):
                    costs, conversion = ramses_costs.quote_native_cycle(
                        rpc, self.fixture["factory"], case["candidate"], case["block"],
                        {"captured_cycle": case["native_cycle_cost_raw"]}, {},
                    )
                self.assertIsNone(costs)
                self.assertEqual(conversion, case["expected_conversion"])
                row = self._screen_row(case, conversion)
                status = screen_evidence_status(row)
                self.assertEqual(status["causal_bucket"], "valid_early_structural_rejection")
                self.assertFalse(status["full_reconstruction_required"])
                self.assertFalse(status["evidence_complete"])
                screens.append(extended._screen_summary(dict(rows=[row])))
        summary = screening_evidence_summary(screens)
        self.assertEqual(summary["screening_attempts"], 17)
        self.assertEqual(summary["screened_candidates"], 7)
        self.assertEqual(summary["candidates_requiring_full_evidence"], 0)
        self.assertEqual(summary["evidence_requested"], 0)
        self.assertEqual(summary["evidence_completed_in_time"], 0)
        self.assertEqual(summary["required_evidence_failed"], 0)
        self.assertEqual(summary["causal_candidate_counts"], {"valid_early_structural_rejection": 7})

    def test_every_observed_quote_retains_all_input_and_returns_zero_output(self):
        quotes = self.fixture["all_observed_route_quotes"]
        self.assertEqual(len(quotes), 81)
        for row in quotes:
            amount = int(row["params"][0]["data"][10:74], 16)
            self.assertGreater(amount, 0)
            self.assertEqual(values(row["response"]), [amount, 0, 0])

    def test_unproven_route_absence_and_provider_failures_stay_required(self):
        case = self.fixture["cases"][0]
        for reason in (NO_COST_ROUTE, "no_ramses_gas_samples", "cost_acquisition_boundary:provider_http_429"):
            with self.subTest(reason=reason):
                row = self._screen_row(case, {})
                row["cost_evidence"]["reason"] = reason
                status = screen_evidence_status(row)
                self.assertTrue(status["required_for_strategy_decision"])
                self.assertEqual(status["failed_stage"], "cost_evidence")
                self.assertFalse(status["evidence_complete"])
                if "provider" in reason:
                    self.assertEqual(status["classification"], "provider_failed")

    def test_valid_earlier_strategy_rejection_does_not_require_missing_cost(self):
        row = dict(decision=dict(qualified=False, reasons=["prior_30m_not_quiet", "cost_evidence_unavailable"]))
        status = screen_evidence_status(row)
        self.assertFalse(status["required_for_strategy_decision"])
        self.assertEqual(status["causal_bucket"], "valid_early_strategy_rejection")

    def test_qualified_screen_is_not_authenticated_reconstruction(self):
        status = screen_evidence_status(dict(decision=dict(qualified=True, reasons=[]),
            cost_evidence=dict(available=True)))
        self.assertTrue(status["required_for_strategy_decision"])
        self.assertFalse(status["evidence_complete"])
        self.assertFalse(status["full_reconstruction_requested"])

    def test_missing_wide_state_does_not_turn_into_a_valid_range_rejection(self):
        row = dict(decision=dict(qualified=False, reasons=["no_wide_entry_candidate"]),
            cost_evidence=dict(available=True), wide_state_hydrated=False)
        self.assertTrue(screen_evidence_status(row)["required_for_strategy_decision"])
        row["wide_state_hydrated"] = True
        status = screen_evidence_status(row)
        self.assertFalse(status["required_for_strategy_decision"])
        self.assertEqual(status["causal_bucket"], "full_reconstruction_became_unnecessary")

    def test_captured_rejection_never_requests_full_reconstruction_in_campaign(self):
        case = self.fixture["cases"][0]
        row = self._screen_row(case, case["expected_conversion"])
        clock = [0.0]
        header = dict(number=hex(case["block"]), hash=case["block_hash"],
            timestamp=hex(1000), parentHash="0x" + "11" * 32)

        class Rpc:
            def verify_chain(self): return 4663
            def telemetry(self): return {}
            def call(self, *_args, **_kwargs): return header

        def scan(_endpoint, **_kwargs):
            return dict(policy_hash=POLICY_HASH, strategy_domain=STRATEGY_DOMAIN,
                finalized_block=case["block"], finalized_hash=case["block_hash"],
                finalized_timestamp=1000, finalized_frontier_source="pinned_external_finalized_header",
                rows=[row], provider={})

        with tempfile.TemporaryDirectory() as td, \
             patch.object(extended, "REPORT", Path(td) / "report.json"), \
             patch.object(extended, "BoundedMultiRpc", return_value=Rpc()), \
             patch.object(extended, "scan", side_effect=scan), \
             patch.object(extended, "run_connected", side_effect=AssertionError("unnecessary reconstruction")), \
             patch.object(extended.time, "monotonic", side_effect=lambda: clock[0]), \
             patch.object(extended.time, "sleep", side_effect=lambda seconds: clock.__setitem__(0, clock[0] + seconds)):
            dbpath = Path(td) / "paper.sqlite"
            result = extended.run("unused", campaign=True, discovery_seconds=60, db_path=dbpath)
            with sqlite3.connect(str(dbpath) + ".pipeline.sqlite") as db:
                stages = [r[0] for r in db.execute("SELECT stage FROM progress")]
            self.assertIn("evidence_not_required", stages)
            self.assertNotIn("evidence_requested", stages)
            self.assertNotIn("reconstruction_started", stages)
            self.assertNotIn("evidence_complete", stages)
            self.assertEqual(result["evidence_reconstruction"]["causal_candidate_counts"],
                {"valid_early_structural_rejection": 1})
            self.assertEqual(result["opportunity_coverage"]["unique_classes"]["reconstruction_incomplete"], 0)

    def test_canonical_successful_negative_decision_promotes_but_failure_does_not(self):
        header = "0x" + "11" * 32
        row = dict(pool="pool", decision=_decision(qualified=True))
        screen = dict(policy_hash=POLICY_HASH, strategy_domain=STRATEGY_DOMAIN,
            finalized_block=100, finalized_hash=header, finalized_timestamp=1000, rows=[row])

        class Rpc:
            def verify_chain(self): return 4663
            def telemetry(self): return {}

        for failure in (False, True):
            events = []
            canonical = dict(row, decision=_decision(qualified=False))
            outcome = BoundaryError("qualifier_receipt_identity") if failure else (canonical, dict(reclassified=True))
            with self.subTest(failure=failure), \
                 patch.object(connected, "BoundedMultiRpc", return_value=Rpc()), \
                 patch.object(connected, "_canonicalize_selected_row", side_effect=outcome if failure else None,
                              return_value=None if failure else outcome):
                def progress(candidate, stage, **details):
                    events.append((candidate, stage, details))
                if failure:
                    with self.assertRaisesRegex(BoundaryError, "qualifier_receipt_identity"):
                        connected.run("unused", initial_screen=screen, evidence_progress=progress)
                else:
                    result = connected.run("unused", initial_screen=screen, evidence_progress=progress)
                    self.assertEqual(result["reason"], "no_authenticated_all_pool_qualifier")
            self.assertEqual(events[0][1], "reconstruction_started")
            self.assertEqual(events[1][1], "reconstruction_incomplete" if failure else "reconstruction_complete")
            self.assertEqual(events[1][2]["frontier"], (100, header))


if __name__ == "__main__":
    unittest.main()
