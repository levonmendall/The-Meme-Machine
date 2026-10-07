"""Exact preserved epoch mapping, active holds and read-only migration planning."""
from copy import deepcopy
from pathlib import Path
import json
import tempfile
import unittest

from meme_machine.shared_capital import CapitalAuthority, CapitalError, REGIMES, RiskPolicy
from meme_machine.shared_capital.migration import plan_migration, validate_plan
from meme_machine.shared_capital.model import digest, money, amount
from tests.shared_capital_support import (legacy_fixture, legacy_proof, empty_mapping,
                                         utc, EPOCH, Harness)


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.path = self.root / "preserved-fixture.sqlite"
        self.old = legacy_fixture(self.path); self.addCleanup(self.old.close)
        self.mapping = empty_mapping()

    def enter(self, r, i):
        family = r.split("_")[0]; life, req = "original-life:" + r, "original-reservation:" + r
        proof = legacy_proof(family, i)
        self.old.reserve(epoch_id=EPOCH, event_id="reserve:" + r, reservation_id=req, lane=family,
            amount="7.25", lifecycle_id=life, at=utc(i), provenance=proof)
        self.old.enter(epoch_id=EPOCH, event_id="enter:" + r, reservation_id=req, lifecycle_id=life,
            lane=family, asset="economic-asset:" + r, basis="6.25", fee="1", strategy_id=r,
            at=utc(i), provenance=proof)
        self.mapping["position_meta"][life] = dict(regime=r, economic_keys=["economic-asset:" + r],
            original_basis="6.25", original_native_basis=6250, partials=0, scale_committed=False, capital_seconds="0")
        return life

    def test_all_six_regimes_epoch_basis_realized_costs_marks_and_identity_map_exactly(self):
        for i, r in enumerate(REGIMES, 1): self.enter(r, i)
        life = "original-life:pump_current"
        self.old.realize(epoch_id=EPOCH, event_id="original-partial", lifecycle_id=life,
            basis_released="1.25", gross_proceeds="3", fee="0.5", at=utc(7), provenance=legacy_proof("pump", 7))
        self.mapping["position_meta"][life]["partials"] = 1
        self.old.mark(epoch_id=EPOCH, event_id="original-mark", lifecycle_id=life, state="CURRENT",
            net_liquidation_value="10", as_of=utc(8), valid_until=utc(100008), at=utc(8), provenance=legacy_proof("pump", 8))
        before = self.old.snapshot()
        plan = plan_migration(self.path, self.mapping)
        self.assertEqual(self.old.snapshot(), before)
        h = Harness(self.root, plan=plan)
        try:
            s = h.check()
            self.assertEqual(s["epoch_id"], EPOCH)
            self.assertEqual(s["ledger"]["inception_sha256"], before["receipt_hash"])
            self.assertEqual(set(s["ledger"]["positions"]), set(before["positions"]))
            self.assertEqual(money(s["capital"]["deployed_basis"]), sum(p["remaining_basis"] for p in before["positions"].values()))
            self.assertEqual(money(s["capital"]["realized_equity"]), money("495.25"))
            self.assertEqual(s["ledger"]["positions"][life]["mark"]["net_value"], "10")
            h.restart(); h.authority.verify_replay()
            self.assertEqual(h.authority.install_migration(plan), h.authority.install_migration(plan))
        finally: h.close()

    def reserve(self):
        req = "original-active-reservation"
        self.old.reserve(epoch_id=EPOCH, event_id="active-reserve", reservation_id=req, lane="pump", amount="8.25",
            lifecycle_id="pending-life", at=utc(1), provenance=legacy_proof("pump", 1))
        self.mapping["reservation_meta"][req] = dict(regime="pump_current", economic_keys=["pending-asset"],
            basis="6.25", cost_headroom="1", settlement_headroom="1", lifecycle_id="pending-life", kind="new",
            native_sizing=dict(realized_equity_units=125000, usd_per_native_unit="0.001", journal_sha256="f" * 64))
        return req

    def test_existing_reservation_and_backed_pending_delivery_count_once(self):
        req = self.reserve()
        self.old.db.execute("INSERT INTO portfolio_native_pending VALUES(?,?,?)", ("pump", "pending-native", json.dumps({"original": "immutable-delivery"})))
        self.mapping["pending"]["pump:pending-native"] = dict(regime="pump_current", backing="reservation",
            backing_id=req, additional_total="0")
        plan = plan_migration(self.path, self.mapping)
        h = Harness(self.root, plan=plan)
        try:
            s = h.check()
            self.assertEqual(money(s["capital"]["active_reservations"]), money("8.25"))
            self.assertEqual(money(s["capital"]["pending_authoritative_commitments"]), 0)
            self.assertEqual(money(s["capital"]["free_cash"]), money("491.75"))
            self.assertEqual(len(s["ledger"]["pending_deliveries"]), 1)
            h.restart()
            with self.assertRaisesRegex(CapitalError, "still_authoritatively_committed"):
                h.authority.acknowledge_migrated_delivery(operation_id="too-early-pending", pending_key="pump:pending-native",
                    at=h.at, body_sha256=digest({"original": "immutable-delivery"}))
            h.authority.cancel(operation_id="cancel-legacy", request_id=req, at=h.at,
                proof_sha256="d" * 64, proof_kind="VERIFIED_NATIVE_ABSENCE")
            h.authority.acknowledge_migrated_delivery(operation_id="pending-ack", pending_key="pump:pending-native",
                at=h.at, body_sha256=digest({"original": "immutable-delivery"}))
            h.restart()
            self.assertEqual(len(h.check()["ledger"]["pending_deliveries"]), 0)
        finally: h.close()

    def test_incremental_native_pending_and_required_obligation_remain_funded(self):
        self.old.db.execute("INSERT INTO portfolio_native_pending VALUES(?,?,?)", ("pons", "unacknowledged-native", json.dumps({"native_usd_commitment": "20"})))
        self.mapping["pending"]["pons:unacknowledged-native"] = dict(regime="pons_current", backing="incremental",
            additional_total="20", basis="18", cost_headroom="2", settlement_headroom="0", economic_keys=["canonical-token"],
            lifecycle_id=None, kind="new", native_sizing=dict(realized_equity_units=125000, usd_per_native_unit="0.001", journal_sha256="f" * 64))
        self.mapping["obligations"]["required-settlement"] = dict(regime="ramses", amount="5", proof_sha256="c" * 64)
        plan = plan_migration(self.path, self.mapping)
        h = Harness(self.root, plan=plan)
        try:
            s = h.check()
            self.assertEqual(money(s["capital"]["pending_authoritative_commitments"]), 20)
            self.assertEqual(money(s["capital"]["required_funding_obligations"]), 5)
            self.assertEqual(money(s["capital"]["free_cash"]), 475)
        finally: h.close()

    def test_unknown_pending_duplicate_backing_and_unfunded_commitments_fail_closed(self):
        req = self.reserve()
        self.old.db.execute("INSERT INTO portfolio_native_pending VALUES(?,?,?)", ("pump", "pending", "{}"))
        with self.assertRaisesRegex(CapitalError, "pending_authority_inventory"):
            plan_migration(self.path, self.mapping)
        self.mapping["pending"]["pump:pending"] = dict(regime="pump_current", backing="reservation", backing_id=req, additional_total="1")
        with self.assertRaisesRegex(CapitalError, "counted_twice"):
            plan_migration(self.path, self.mapping)
        self.mapping["pending"]["pump:pending"]["additional_total"] = "0"
        self.mapping["obligations"]["too-large"] = dict(regime="ramses", amount="500", proof_sha256="c" * 64)
        with self.assertRaisesRegex(CapitalError, "negative_capital"):
            plan_migration(self.path, self.mapping)

    def test_plan_tampering_and_incorrect_attribution_cannot_rewrite_history(self):
        self.enter("pump_current", 1)
        plan = plan_migration(self.path, self.mapping)
        changed = deepcopy(plan); changed["seed"]["cash"] = "1000"
        with self.assertRaisesRegex(CapitalError, "checksum"):
            validate_plan(changed)
        changed["migration_sha256"] = digest({k: v for k, v in changed.items() if k != "migration_sha256"})
        with self.assertRaisesRegex(CapitalError, "seed_reconciliation"):
            validate_plan(changed)
        self.mapping["retired"]["pump_current"]["pnl"] = "1"
        with self.assertRaisesRegex(CapitalError, "cannot_be_rewritten"):
            plan_migration(self.path, self.mapping)

    def test_migration_interruption_is_atomic_and_restart_safe(self):
        plan = plan_migration(self.path, self.mapping)
        target = self.root / "migration-target.sqlite"
        a = CapitalAuthority(target)
        try:
            def fail(point):
                if point == "before_commit": raise RuntimeError("migration-interruption")
            a.fault = fail
            with self.assertRaisesRegex(RuntimeError, "migration-interruption"): a.install_migration(plan)
            a.close(); a = CapitalAuthority(target)
            self.assertEqual(a.snapshot()["state"], "NOT_INITIALIZED")
            a.install_migration(plan)
            self.assertEqual(money(a.snapshot()["capital"]["realized_equity"]), 500)
            a.verify_replay()
        finally: a.close()

    def test_preserved_alias_sequence_and_retired_native_identity_fence(self):
        self.old.db.execute("INSERT INTO portfolio_native_ids(lane,native) VALUES(?,?)", ("pump", "preserved-native"))
        plan = plan_migration(self.path, self.mapping)
        h = Harness(self.root, plan=plan)
        try:
            a = h.authority
            self.assertEqual(a.bind_native_identity(operation_id="existing-alias", family="pump", native_lifecycle_id="preserved-native", at=h.at)["lifecycle_id"], "pump:n1")
            self.assertEqual(a.bind_native_identity(operation_id="new-alias", family="pons", native_lifecycle_id="fresh-native", at=h.at)["lifecycle_id"], "pons:n2")
            requests, _ = h.allocate([("pons_current", {})]); q = requests[0]
            with self.assertRaisesRegex(CapitalError, "unbound_native_alias"):
                a.consume(operation_id="cross-family-alias", request_id=q.request_id, lifecycle_id="pump:n1",
                    basis="6.25", cost="0", at=h.at, native=h.native(q.regime, "pump:n1"),
                    valuation=h.valuation(), native_basis_units=625000000000000000000000000000)
            with self.assertRaisesRegex(CapitalError, "cross_epoch"):
                a.bind_native_identity(operation_id="wrong-epoch", family="pump", native_lifecycle_id="native:paper-epoch:wrong-epoch:42", at=h.at)
            h.restart()
            self.assertEqual(h.check()["ledger"]["native_alias_sequence"], 2)
        finally: h.close()
