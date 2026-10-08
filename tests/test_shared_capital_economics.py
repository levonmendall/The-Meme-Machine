"""Controlled hard-sleeve equivalence, production reducer parity and tape replay."""
from copy import deepcopy
from dataclasses import replace
import tempfile
import unittest

from experiments.shared_capital import Opportunity, ReducerReplay, run_tape, scenario, SCENARIOS
from meme_machine.portfolio_accounting import PortfolioIntegrityError
from meme_machine.shared_capital.model import money
from tests.shared_capital_support import Harness, EPOCH, legacy_fixture, legacy_proof, utc


class EconomicsTests(unittest.TestCase):
    def test_controlled_hard_cash_comparator_matches_existing_accountant(self):
        tape = [Opportunity("cash-boundary:" + str(i), 0, "pump_current", "asset:" + str(i), 0, 1) for i in range(24)]
        replay = run_tape(tape, "A_HARD_SLEEVES")
        with tempfile.TemporaryDirectory() as td:
            old = legacy_fixture(td + "/legacy.sqlite")
            count = 0
            try:
                for i in range(24):
                    try:
                        old.reserve(epoch_id=EPOCH, event_id="event:" + str(i), reservation_id="reservation:" + str(i),
                            lane="pump", amount="6.25", at=utc(i), provenance=legacy_proof("pump", i))
                        count += 1
                    except PortfolioIntegrityError as error:
                        self.assertEqual(str(error), "family_sleeve_capital_exhausted")
            finally: old.close()
        self.assertEqual(count, replay["granted"])
        self.assertEqual(replay["granted"], 20)
        self.assertEqual(run_tape(tape, "B_SHARED_FIXED")["granted"], 24)

    def test_identical_tape_replay_is_deterministic_and_sizing_is_explicit(self):
        tape = [Opportunity("deterministic:" + str(i), 0, "pump_current", "asset:" + str(i), 500, 1) for i in range(4)]
        result = run_tape(tape, "C_SHARED_ADAPTIVE")
        self.assertEqual(result, run_tape(tape, "C_SHARED_ADAPTIVE"))
        other = run_tape(tape, "B_SHARED_FIXED", sizing_basis="shared_realized_equity")
        self.assertEqual(other["average_requested_position_usd"], 25)
        self.assertEqual(result["average_requested_position_usd"], 6.25)
        self.assertGreater(other["peak_deployed_usd"], result["peak_deployed_usd"])
        self.assertTrue(other["conservation"])

    def test_offline_reducer_and_sqlite_return_the_same_decisions_and_ledger(self):
        with tempfile.TemporaryDirectory() as td:
            h = Harness(td)
            replay = ReducerReplay(h.plan)
            q = h.prepare("pump_current", round_id="parity", request_id="parity-request")
            event = h.authority.db.execute("SELECT operation_id,body FROM shared_capital_events ORDER BY sequence DESC LIMIT 1").fetchone()
            import json
            v = json.loads(event[1]); replay._write(event[0], v["action"], v["at"], v["data"])
            h.authority.open_round(operation_id="open", round_id="parity", at=0, cutoff=0)
            replay.open_round(operation_id="open", round_id="parity", at=0, cutoff=0)
            self.assertEqual(h.authority.submit(q, at=0), replay.submit(q, at=0))
            h.finish_round("parity", [q])
            for r in h.plan["seed"]["contracts"]:
                replay.seal(operation_id="seal:parity:" + r, round_id="parity", regime_name=r,
                    request_ids=[q.request_id] if r == q.regime else [], at=0)
            self.assertEqual(h.authority.allocate(round_id="parity", at=0), replay.allocate(round_id="parity", at=0))
            self.assertEqual(h.authority.snapshot()["ledger"], replay.current)
            h.close()

    def test_all_ten_required_scenarios_are_frozen_and_cover_six_regimes(self):
        tapes = [scenario(name) for name in SCENARIOS]
        self.assertEqual(len(tapes), 10)
        self.assertEqual(len({o.regime for tape in tapes for o in tape}), 6)
        self.assertTrue(any(o.outcome_bps >= 240000 for o in scenario("rare_right_tail")))
        self.assertTrue(any(o.capacity_bps < 10000 for o in scenario("liquidity_constrains_leader")))
