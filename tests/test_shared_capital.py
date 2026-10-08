"""Capital conservation, funding constraints, evidence identity and all six regimes."""
from dataclasses import replace
from decimal import localcontext
import random
import tempfile
import unittest

from meme_machine.shared_capital import CapitalError, REGIMES, RiskPolicy, Valuation
from meme_machine.shared_capital.adapter import directional_target, sizing_comparison
from meme_machine.shared_capital.model import digest, money, amount
from tests.shared_capital_support import Harness, CONTRACTS, legacy_fixture, legacy_proof, utc, EPOCH


class SharedCapitalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.h = Harness(self.temp.name)
        self.addCleanup(lambda: self.h.close())

    def test_no_lane_owns_cash_and_idle_budgets_reserve_zero(self):
        s = self.h.check()
        self.assertEqual(money(s["capital"]["free_cash"]), 500)
        self.assertEqual(money(s["capital"]["active_reservations"]), 0)
        self.assertEqual(set(s["lanes"]), set(REGIMES))
        specs = [("pump_current", {}) for _ in range(24)]
        requests, result = self.h.allocate(specs)
        self.assertEqual(sum(d["status"] == "RESERVED" for d in result["decisions"].values()), 24)
        self.assertEqual(money(self.h.check()["capital"]["active_reservations"]), 150)
        # The family was $125. Every position is still exactly the old $6.25.
        self.assertTrue(all(money(d["basis"]) == money("6.25") for d in result["decisions"].values()))

    def test_all_six_regimes_and_sufficient_capital_preserve_request_economics(self):
        requests, result = self.h.allocate([(r, {}) for r in REGIMES])
        for q in requests:
            self.assertEqual(money(result["decisions"][q.request_id]["basis"]), money(q.requested_basis))
            self.h.fill(q)
        s = self.h.check()
        self.assertEqual(sum(money(p["deployed_basis"]) > 0 for p in s["lanes"].values()), 6)
        self.h.restart(); self.h.authority.verify_replay()

    def test_position_size_is_separate_from_shared_cash_and_lane_exposure(self):
        comparison = sizing_comparison(self.h.check()["ledger"], "pump_current")
        self.assertEqual(money(comparison["effective_request"]), money("6.25"))
        self.assertEqual(money(comparison["shared_equity_request"]), 25)
        self.assertEqual(money(comparison["incremental_per_trade_risk"]), money("18.75"))
        requests, result = self.h.allocate([("pump_current", {"requested": "25"})])
        d = result["decisions"][requests[0].request_id]
        self.assertEqual(d["status"], "QUALIFIED_BUT_CAPITAL_UNAVAILABLE")
        self.assertEqual(d["reason"], "POSITION_SIZING_BASIS")
        with self.assertRaisesRegex(CapitalError, "lp_sizing"):
            directional_target(self.h.check()["ledger"], "meteora", native_units_per_usd="1000")

    def test_native_equivalence_preserves_integer_sizing_despite_currency_price_changes(self):
        from meme_machine.runtime.sleeve_reservations import SleeveReservations
        from pathlib import Path
        sleeve = SleeveReservations(Path(self.temp.name) / "native-sleeve.sqlite", lane="pump", capital=100003,
            policies={"current": "a", "survivor": "b"}, cohort="offline-equivalence")
        try:
            old = sleeve.sizing_basis(500)
            for native_rate in ("1000", "500", "2000"):
                result = directional_target(self.h.check()["ledger"], "pump_current",
                    native_units_per_usd=native_rate, legacy_native_realized_equity=old["realized_equity"])
                self.assertEqual(result["requested_native_units"], old["target"])
            native_sizing = dict(realized_equity_units=100003, usd_per_native_unit="0.002", journal_sha256="b" * 64)
            requests, result = self.h.allocate([("pump_current", dict(requested="10", native_sizing=native_sizing))])
            self.assertEqual(result["decisions"][requests[0].request_id]["status"], "RESERVED")
            life, _ = self.h.fill(requests[0])
            self.assertEqual(self.h.check()["ledger"]["positions"][life]["original_native_basis"], 5000)
        finally: sleeve.close()

    def test_qualified_unfunded_remains_distinct_and_observable_after_restart(self):
        requests, result = self.h.allocate([("pump_current", {"execution_capacity": "0"})])
        self.assertEqual(result["decisions"][requests[0].request_id]["status"], "QUALIFIED_BUT_CAPITAL_UNAVAILABLE")
        self.h.restart()
        s = self.h.check()
        self.assertEqual(s["lanes"]["pump_current"]["qualified_but_unfunded"], 1)
        self.assertEqual(s["lanes"]["pump_current"]["strategy_rejected"], 0)
        self.assertEqual(next(iter(s["ledger"]["observations"].values()))["status"], "QUALIFIED")

    def test_capitalized_native_entry_fees_preserve_principal_and_existing_accounting(self):
        old = legacy_fixture(self.h.root / "fee-equivalence.sqlite")
        self.addCleanup(old.close)
        for r in REGIMES[:4]:
            with self.subTest(regime=r):
                native_sizing = dict(realized_equity_units=100003, usd_per_native_unit="0.002", journal_sha256="b" * 64)
                requests, decisions = self.h.allocate([(r, dict(requested="10", cost_headroom="0.05", native_sizing=native_sizing))])
                q, life = requests[0], "fee-life:" + r
                self.assertEqual(decisions["decisions"][q.request_id]["basis"], "10")
                for i, (basis, included, units) in enumerate((("10.04", "0", 5020), ("10.06", "0.06", 5030), ("10.04", "0.04", 6000))):
                    with self.assertRaisesRegex(CapitalError, "consumption_exceeds_authority"):
                        self.h.authority.consume(operation_id="invalid-fee:" + r + ":" + str(i), request_id=q.request_id,
                            lifecycle_id=life, basis=basis, cost="0", included_cost=included, native_basis_units=units,
                            at=0, native=self.h.native(r, life), valuation=self.h.valuation())
                self.h.authority.consume(operation_id="fee-fill:" + r, request_id=q.request_id, lifecycle_id=life,
                    basis="10.04", cost="0", included_cost="0.04", native_basis_units=5020,
                    at=0, native=self.h.native(r, life), valuation=self.h.valuation())
                self.h.mark(r, life)
                family = r.split("_")[0]
                proof = legacy_proof(family, 0)
                old.reserve(epoch_id=EPOCH, event_id="fee-hold:" + r, reservation_id=q.request_id,
                    lane=family, amount="10.05", at=utc(0), provenance=proof)
                old.enter(epoch_id=EPOCH, event_id="fee-fill:" + r, reservation_id=q.request_id,
                    lifecycle_id=life, lane=family, asset="fee-asset:" + r, basis="10.04", fee="0", included_fee="0.04",
                    at=utc(0), strategy_id=r, provenance=proof)
                s = self.h.check()
                self.assertEqual(money(s["capital"]["actual_cash"]), old.snapshot()["available"])
                self.assertEqual(money(s["capital"]["deployed_basis"]), sum(p["remaining_basis"] for p in old.snapshot()["positions"].values()))
                self.assertEqual(money(s["capital"]["realized_equity"]), 500)
                self.assertEqual(s["ledger"]["positions"][life]["original_native_basis"], 5020)
                self.assertEqual(money(s["lanes"][r]["costs"]), money("0.04"))
                self.h.restart()

    def test_capitalized_fee_buffer_counts_against_gross_risk_headroom(self):
        h = Harness(self.h.root / "fee-risk", RiskPolicy(asset_bps=100))
        self.addCleanup(h.close)
        requests, result = h.allocate([("pump_current", dict(requested="6.25", minimum_basis="1", cost_headroom="1"))])
        q = requests[0]
        # $499 conservative risk base, 1% asset cap, less $1 capitalizable fee.
        self.assertEqual(money(result["decisions"][q.request_id]["basis"]), money("3.99"))
        self.assertEqual(money(h.check()["risk"]["exposure"]["portfolio"]), money("4.99"))

    def test_all_funding_constraints_bound_grants(self):
        for key in ("liquidity_capacity", "execution_capacity", "strategy_capacity"):
            self.h.at += 1
            requests, result = self.h.allocate([("pump_current", {key: "1", "minimum_basis": "1"})])
            d = result["decisions"][requests[0].request_id]
            self.assertEqual(money(d["basis"]), 1)
            self.assertIn(key.upper(), d["binding_constraints"])
            self.h.authority.cancel(operation_id="cancel:" + requests[0].request_id,
                request_id=requests[0].request_id, at=self.h.at, proof_sha256="c" * 64, proof_kind="DEFINITIVELY_CANCELLED")
        self.h.authority.require_obligation(operation_id="required-fee", obligation_id="required-fee",
            regime_name="ramses", amount_usd="499", at=self.h.at, proof_sha256="c" * 64)
        requests, result = self.h.allocate([("pump_current", {"minimum_basis": "0.5", "cost_headroom": "0.5"})])
        self.assertEqual(result["decisions"][requests[0].request_id]["status"], "QUALIFIED_BUT_CAPITAL_UNAVAILABLE")
        self.assertEqual(money(self.h.check()["capital"]["free_cash"]), 1)
        self.h.authority.discharge_obligation(operation_id="paid-fee", obligation_id="required-fee", paid="0", at=self.h.at, proof_sha256="d" * 64)
        self.h.check()

    def test_atomic_accounting_costs_partial_realization_settlement_and_no_double_charge(self):
        requests, _ = self.h.allocate([("pons_current", {"cost_headroom": "1", "settlement_headroom": "2"})])
        q = requests[0]
        life, _ = self.h.fill(q, cost="0.5", included_cost="0.1")
        self.assertEqual(money(self.h.check()["capital"]["realized_equity"]), money("499.5"))
        self.h.at = 10
        self.h.realize(q.regime, life, "2.75", released="1.25", terminal=False, cost="0.25", included_cost="0.1")
        s = self.h.check()
        self.assertEqual(money(s["capital"]["realized_equity"]), money("500.75"))
        self.assertEqual(money(s["capital"]["required_funding_obligations"]), 2)
        self.h.at = 20
        self.h.realize(q.regime, life, "7", cost="0.5")
        s = self.h.check()
        self.assertEqual(money(s["capital"]["realized_equity"]), money("502.25"))
        self.assertEqual(money(s["lanes"][q.regime]["costs"]), money("1.45"))
        self.assertEqual(money(s["capital"]["required_funding_obligations"]), 0)
        self.assertEqual(money(s["lanes"][q.regime]["capital_seconds"]), money("112.50"))
        with self.assertRaisesRegex(CapitalError, "open_position"):
            self.h.realize(q.regime, life, "7", released="1")
        self.h.restart(); self.h.authority.verify_replay()

    def test_unrealized_gains_never_compound_and_losses_lower_risk_base(self):
        requests, _ = self.h.allocate([("pump_current", {})])
        life, _ = self.h.fill(requests[0])
        self.h.mark("pump_current", life, "100")
        s = self.h.check()
        self.assertEqual(money(s["capital"]["realized_equity"]), 500)
        self.assertEqual(money(sizing_comparison(s["ledger"], "pump_current")["effective_request"]), money("6.25"))
        self.assertEqual(money(s["risk"]["exposure"]["portfolio"]), 100)
        self.h.mark("pump_current", life, "1")
        s = self.h.check()
        self.assertEqual(money(s["risk"]["risk_base"]), money("494.75"))
        self.assertEqual(money(s["capital"]["realized_equity"]), 500)

    def test_missing_or_stale_valuation_fails_closed_for_new_allocation(self):
        requests, _ = self.h.allocate([("pump_current", {})])
        self.h.fill(requests[0], mark=False)
        requests, result = self.h.allocate([("ramses", {})])
        self.assertEqual(result["decisions"][requests[0].request_id]["reason"], "PORTFOLIO_VALUATION_UNAVAILABLE_OR_INVALID")
        with self.assertRaisesRegex(CapitalError, "valuation"):
            self.h.prepare("ramses", round_id="unused", valuation=Valuation("stale", "e" * 64, 0, 0)) if self.h.at > 0 else Valuation("wrong", "e" * 64, 0, 1, "SOL").value(0)

    def test_request_identity_conflicts_stale_generation_and_supersession(self):
        q = self.h.prepare("pump_current", round_id="id-round", asset="solana:mint")
        self.h.authority.open_round(operation_id="open-id", round_id=q.round_id, at=0, cutoff=0)
        self.h.authority.submit(q, at=0)
        self.assertEqual(self.h.authority.submit(q, at=0)["status"], "SUBMITTED")
        with self.assertRaisesRegex(CapitalError, "conflicting_operation"):
            self.h.authority.submit(replace(q, requested_basis="1", minimum_basis="1"), at=0)
        with self.assertRaisesRegex(CapitalError, "duplicate_or_conflicting_request"):
            self.h.authority.submit(replace(q, request_id="alias-request"), at=0)
        self.h.finish_round(q.round_id, [q]); self.h.authority.allocate(round_id=q.round_id, at=0)
        self.assertGreater(money(self.h.check()["capital"]["active_reservations"]), 0)
        self.h.authority.observe(operation_id="supersede", at=0, regime_name=q.regime,
            candidate_id=q.candidate_id, generation=2, status="QUALIFIED", economic_keys=["solana:mint"],
            evidence={"fresh": True}, policy_hash=CONTRACTS[q.regime]["policy_hash"])
        self.assertEqual(money(self.h.check()["capital"]["active_reservations"]), 0)
        self.h.restart()
        self.assertEqual(self.h.check()["ledger"]["requests"][q.request_id]["status"], "SUPERSEDED")

    def test_unbound_request_economics_and_priority_cannot_bypass_qualification(self):
        q = self.h.prepare("pump_current", round_id="binding")
        self.h.authority.open_round(operation_id="open-binding", round_id=q.round_id, at=0, cutoff=0)
        with self.assertRaisesRegex(CapitalError, "economics_or_evidence"):
            self.h.authority.submit(replace(q, native_quality_bps=10000), at=0)

    def test_required_obligation_priority_existing_commitment_and_cancellation(self):
        requests, _ = self.h.allocate([("ramses", {"requested": "75"})])
        q = requests[0]
        self.h.authority.commit(operation_id="commit", request_id=q.request_id, commitment_id="durable-intent", at=0, intent_sha256="f" * 64, lifecycle_id="life:" + q.request_id)
        s = self.h.check()
        self.assertEqual(money(s["capital"]["active_reservations"]), 0)
        self.assertEqual(money(s["capital"]["pending_authoritative_commitments"]), 75)
        self.h.restart()
        self.h.authority.cancel(operation_id="cancel-intent", request_id=q.request_id, at=0,
            proof_sha256="d" * 64, proof_kind="VERIFIED_NATIVE_ABSENCE")
        self.h.authority.cancel(operation_id="cancel-intent", request_id=q.request_id, at=0,
            proof_sha256="d" * 64, proof_kind="VERIFIED_NATIVE_ABSENCE")
        self.assertEqual(money(self.h.check()["capital"]["free_cash"]), 500)

    def test_hostile_decimal_context_does_not_change_money(self):
        with localcontext() as ctx:
            ctx.prec = 6
            requests, _ = self.h.allocate([("ramses", {"requested": "12.34567890123456789012345678901"})])
            self.h.fill(requests[0])
            self.h.at = 1
            self.h.realize("ramses", "life:" + requests[0].request_id, "13.12345678901234567890123456789")
            self.h.check(); self.h.authority.verify_replay()

    def test_generated_command_sequences_conserve_capital_and_replay(self):
        rng = random.Random(20261006)
        for i in range(60):
            self.h.at += 1
            r = rng.choice(REGIMES)
            requests, result = self.h.allocate([(r, {"requested": "1"})])
            q = requests[0]
            if result["decisions"][q.request_id]["status"] != "RESERVED":
                self.h.check(); continue
            if rng.randrange(4) == 0:
                self.h.authority.cancel(operation_id="cancel:" + q.request_id, request_id=q.request_id,
                    at=self.h.at, proof_sha256="d" * 64, proof_kind="DEFINITIVELY_CANCELLED")
            else:
                life, _ = self.h.fill(q)
                self.h.at += rng.randint(1, 100)
                if rng.randrange(3) == 0:
                    self.h.realize(r, life, "0.5", released="0.25", terminal=False)
                self.h.realize(r, life, amount(money(self.h.check()["ledger"]["positions"][life]["basis"]) + money(rng.choice(("-0.1", "0", "0.3")))))
            self.h.check()
            if i % 10 == 0:
                self.h.restart(); self.h.authority.verify_replay()
