"""Independent regimes, original alpha contracts, aggregate risk, one-add scaling."""
from dataclasses import replace
from decimal import Decimal
import tempfile
import unittest

from meme_machine.shared_capital import CapitalError, REGIMES, RiskPolicy
from meme_machine.shared_capital.model import money, amount
from meme_machine.runtime.directional_continuation import BRIDGE_GATES
from tests.shared_capital_support import Harness, CONTRACTS


class StrategyCapitalTests(unittest.TestCase):
    def harness(self, policy=RiskPolicy()):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        h = Harness(temp.name, policy); self.addCleanup(h.close)
        return h

    def test_current_rejection_denial_cancel_exit_or_loss_never_suppresses_survivor(self):
        for family in ("pump", "pons"):
            for outcome in ("rejection", "capital_denial", "reservation_conflict", "cancel", "exit", "loss"):
                with self.subTest(family=family, outcome=outcome):
                    h = self.harness(); current, survivor = family + "_current", family + "_survivor"
                    if outcome == "rejection":
                        h.authority.observe(operation_id="rejection", at=0, regime_name=current, candidate_id="asset",
                            generation=1, status="STRATEGY_REJECTED", economic_keys=["asset"], evidence={"reason": "native-rejection"}, policy_hash=CONTRACTS[current]["policy_hash"])
                    else:
                        requests, result = h.allocate([(current, dict(asset="asset", execution_capacity="0" if outcome == "capital_denial" else "6.25"))])
                        q = requests[0]
                        if outcome in ("cancel", "reservation_conflict"):
                            if outcome == "reservation_conflict":
                                survivor_requests, denied = h.allocate([(survivor, dict(asset="asset"))])
                                self.assertEqual(denied["decisions"][survivor_requests[0].request_id]["reason"], "SAME_ASSET_RESERVATION_OR_POSITION_CONFLICT")
                                observation = h.check()["ledger"]["observations"][survivor + ":asset"]
                                self.assertEqual(observation["status"], "QUALIFIED")
                            h.authority.cancel(operation_id="cancel-current", request_id=q.request_id, at=0, proof_sha256="c" * 64, proof_kind="DEFINITIVELY_CANCELLED")
                        elif outcome in ("exit", "loss"):
                            life, _ = h.fill(q)
                            h.realize(current, life, "1" if outcome == "loss" else "7")
                    h.restart()
                    requests, result = h.allocate([(survivor, dict(asset="asset", requested="1"))])
                    self.assertEqual(result["decisions"][requests[0].request_id]["status"], "RESERVED")
                    self.assertEqual(h.check()["ledger"]["observations"][survivor + ":asset"]["status"], "QUALIFIED")

    def test_current_survivor_alias_and_lineage_exposure_is_not_diversification(self):
        h = self.harness()
        requests, _ = h.allocate([("pump_current", dict(asset="solana:canonical-mint"))])
        life, _ = h.fill(requests[0])
        requests, result = h.allocate([("pump_survivor", dict(asset="solana:canonical-mint"))])
        self.assertEqual(result["decisions"][requests[0].request_id]["reason"], "SAME_ASSET_RESERVATION_OR_POSITION_CONFLICT")
        self.assertEqual(money(h.check()["risk"]["exposure"]["asset"]["solana:canonical-mint"]), money("6.25"))

    def test_family_regime_portfolio_and_correlation_limits_all_apply(self):
        regimes = {r: 10000 for r in REGIMES}
        for policy, reason in (
            (RiskPolicy(regime_base_bps={r: 100 for r in REGIMES}, regime_max_bps=regimes), "REGIME_EXPOSURE_HEADROOM"),
            (RiskPolicy(portfolio_bps=100), "PORTFOLIO_EXPOSURE_HEADROOM"),
            (RiskPolicy(family_max_bps={"pump": 100, "pons": 6500, "meteora": 6500, "ramses": 6500}), "FAMILY_EXPOSURE_HEADROOM"),
            (RiskPolicy(group_bps=dict(crypto_beta=100, solana=7000, robinhood=7000, directional=8000, lp=7000)), "CORRELATED_EXPOSURE:crypto_beta"),
            (RiskPolicy(asset_bps=100), "ASSET_CONCENTRATION:asset"),
        ):
            with self.subTest(reason=reason):
                h = self.harness(policy)
                requests, result = h.allocate([("pump_current", dict(asset="asset"))])
                self.assertIn(reason, result["decisions"][requests[0].request_id]["binding_constraints"])
        h = self.harness(RiskPolicy(asset_bps=1000))
        requests, result = h.allocate([("meteora", dict(asset="shared-asset", requested="40")),
                                      ("pump_current", dict(asset="shared-asset"))])
        self.assertEqual(sum(money(d["basis"]) for d in result["decisions"].values()), money("46.25"))
        requests, result = h.allocate([("ramses", dict(asset="shared-asset", requested="10"))])
        self.assertIn("ASSET_CONCENTRATION:shared-asset", result["decisions"][requests[0].request_id]["binding_constraints"])

    def winner(self, r):
        h = self.harness()
        requests, _ = h.allocate([(r, dict(asset="winner"))]); q = requests[0]
        life, _ = h.fill(q)
        h.at = 1
        h.realize(r, life, "3.125", released="1.5625", terminal=False)
        h.mark(r, life, "9.375")
        h.at = 900
        state = dict(opened_at=0, high_water_bps=10000, first_tail_crossed_at=0,
                     original_basis=6250, realization_taken=True)
        facts = dict({gate: True for gate in BRIDGE_GATES}, fresh_strategy_requalified=True,
                     fresh_execution_requalified=True, after_cost_return_bps=7000)
        return h, life, state, facts

    def test_scaling_preserves_all_approved_gates_and_requests_only_when_eligible(self):
        for r in REGIMES[:4]:
            h, life, state, facts = self.winner(r)
            for missing in BRIDGE_GATES + ("fresh_strategy_requalified", "fresh_execution_requalified"):
                with self.subTest(regime=r, gate=missing):
                    requests, result = h.allocate([(r, dict(asset="winner", candidate="scale:" + missing,
                        requested="3.125", kind="scale", lifecycle_id=life, scale_state=state, scale_facts=dict(facts, **{missing: False})))])
                    self.assertEqual(result["decisions"][requests[0].request_id]["status"], "QUALIFIED_BUT_CAPITAL_UNAVAILABLE")
                    self.assertEqual(money(h.check()["capital"]["active_reservations"]), 0)
            for bad_state, bad_facts, now in ((dict(state, high_water_bps=9999), facts, 900),
                                               (state, dict(facts, after_cost_return_bps=6999), 900),
                                               (dict(state, first_tail_crossed_at=1), facts, 900),
                                               (dict(state, pending_exit=True), facts, 900)):
                requests, result = h.allocate([(r, dict(asset="winner", candidate="scale-invalid:" + str(h.counter),
                    requested="3.125", kind="scale", lifecycle_id=life, scale_state=bad_state, scale_facts=bad_facts))])
                self.assertEqual(result["decisions"][requests[0].request_id]["status"], "QUALIFIED_BUT_CAPITAL_UNAVAILABLE")
            requests, result = h.allocate([(r, dict(asset="winner", candidate="scale-valid", requested="3.125",
                kind="scale", lifecycle_id=life, scale_state=state, scale_facts=facts))])
            q = requests[0]
            self.assertEqual(result["decisions"][q.request_id]["status"], "RESERVED")
            original = h.check()["ledger"]["positions"][life]["original_basis"]
            h.fill(q); h.restart()
            p = h.check()["ledger"]["positions"][life]
            self.assertTrue(p["scale_committed"])
            self.assertEqual(p["original_basis"], original)
            self.assertEqual(money(p["basis"]), money("7.8125"))
            requests, result = h.allocate([(r, dict(asset="winner", candidate="second-scale", requested="1",
                kind="scale", lifecycle_id=life, scale_state=state, scale_facts=facts))])
            self.assertEqual(result["decisions"][requests[0].request_id]["status"], "QUALIFIED_BUT_CAPITAL_UNAVAILABLE")

    def test_scale_cancellation_and_interruption_preserve_original_position(self):
        h, life, state, facts = self.winner("pump_current")
        requests, _ = h.allocate([("pump_current", dict(asset="winner", candidate="scale", requested="3.125",
            kind="scale", lifecycle_id=life, scale_state=state, scale_facts=facts))]); q = requests[0]
        before = h.check()["ledger"]["positions"][life]
        def fail(point):
            if point == "during_position_creation": raise RuntimeError("interrupted-scale")
        h.authority.fault = fail
        with self.assertRaisesRegex(RuntimeError, "interrupted-scale"): h.fill(q)
        h.authority.fault = None; h.restart()
        self.assertEqual(h.check()["ledger"]["positions"][life], before)
        h.authority.cancel(operation_id="cancel-scale", request_id=q.request_id, at=h.at,
            proof_sha256="d" * 64, proof_kind="VERIFIED_NATIVE_ABSENCE")
        self.assertEqual(h.check()["ledger"]["positions"][life], before)

    def test_authoritative_terminal_cancels_unused_scale_commitment(self):
        h, life, state, facts = self.winner("pons_current")
        requests, _ = h.allocate([("pons_current", dict(asset="winner", candidate="scale", requested="3.125",
            kind="scale", lifecycle_id=life, scale_state=state, scale_facts=facts))]); q = requests[0]
        h.authority.commit(operation_id="scale-intent", request_id=q.request_id,
            commitment_id="scale-intent", at=h.at, intent_sha256="f" * 64)
        h.realize("pons_current", life, "9.375")
        s = h.check()
        self.assertEqual(s["ledger"]["requests"][q.request_id]["status"], "CANCELLED")
        self.assertEqual(money(s["capital"]["pending_authoritative_commitments"]), 0)
        h.restart()

    def test_no_new_alpha_or_operational_activation_imports(self):
        from pathlib import Path
        import subprocess
        root = Path(__file__).resolve().parents[1]
        # Whole-tree isolation described the original feature branch. This
        # requested integration still must not activate the new authority or
        # change economics. Check that contract directly, with the existing
        # native sizing/exit/bridge/add behavioral regressions alongside it.
        for path in (root/'meme_machine/operational').glob('*.py'):
            self.assertNotIn('import shared_capital',path.read_text())
            self.assertNotIn('from meme_machine.shared_capital',path.read_text())
        preserved = ('meme_machine/lanes/pump/pump_acceleration_strategy.py',
                     'meme_machine/lanes/pump/pumpswap_survivor.py',
                     'meme_machine/lanes/pons/pons_postgrad_survivor.py',
                     'operational/nine-change-implementation.json')
        for path in preserved:
            self.assertEqual(subprocess.check_output(["git", "diff", "b577cc1c67f4d64f887b430f5e933f376b607dc2", "--", path], cwd=root), b"")
