from contextlib import suppress
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from dashboard.model import Reader, canonical as dashboard_canonical
from meme_machine.portfolio_accounting import (
    LANES,
    PortfolioAccounting,
    PortfolioIntegrityError,
    canonical,
    inception_receipt,
    validate_inception,
)


class SharedPortfolioAccountingTests(unittest.TestCase):
    EPOCH = "synthetic-test-epoch"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.database = self.root / "portfolio.db"
        self.receipt_path = self.root / "inception.json"
        self.export_path = self.root / "accounting.json"
        self.account = PortfolioAccounting(
            self.database, receipt_path=self.receipt_path, export_path=self.export_path
        )
        self.counter = 0
        self.publish_counter = 0

    def tearDown(self):
        if self.account is not None:
            with suppress(Exception):
                self.account.close()
        self.tmp.cleanup()

    def at(self, offset=None):
        if offset is None:
            self.counter += 1
            offset = self.counter
        return (datetime(2026, 9, 24, tzinfo=timezone.utc) + timedelta(seconds=offset)).isoformat()

    @staticmethod
    def identities(lane=None):
        digit = {None: "a", "pump": "1", "pons": "2", "ramses": "3", "meteora": "4"}[lane]
        return {
            "source_sha": digit * 40,
            "policy_hash": digit * 64,
            "config_hash": ("b" if digit != "b" else "c") * 64,
            "source_diff_sha256": ("c" if digit != "c" else "d") * 64,
            "strategy_id": f"{lane or 'portfolio'}-test-policy",
        }

    def provenance(self, lane, number, *, valued=False, as_of=None, valid_until=None):
        identities = self.identities(lane)
        result = {
            "source_event_id": f"source-{lane or 'portfolio'}-{number}",
            "source_kind": "synthetic_canonical_test_fact",
            "source_sha": identities["source_sha"],
            "policy_hash": identities["policy_hash"],
            "config_hash": identities["config_hash"],
            "source_diff_sha256": identities["source_diff_sha256"],
            "native_lifecycle_id": f"native-{lane or 'portfolio'}-{number}",
            "native_journal_hash": "d" * 64,
        }
        if valued:
            as_of = as_of or self.at(self.counter)
            valid_until = valid_until or self.at(self.counter + 100)
            result["value_evidence"] = {
                "evidence_id": f"usd-{lane or 'portfolio'}-{number}",
                "evidence_sha256": "e" * 64,
                "currency": "USD",
                "as_of": as_of,
                "valid_until": valid_until,
            }
        return result

    def activate(self):
        receipt = inception_receipt(self.EPOCH, self.at(0), "synthetic-inception-event")
        receipt_hash = self.account.establish_inception(
            receipt,
            portfolio_identities=self.identities(),
            lane_identities={lane: self.identities(lane) for lane in LANES},
        )
        return receipt, receipt_hash

    def reserve_enter(self, lane="pump", *, lifecycle=None, basis="100.00", fee="1.00", lane_state=None):
        lifecycle = lifecycle or f"life-{lane}-{self.counter + 1}"
        reservation = f"reserve-{lane}-{self.counter + 1}"
        reserve_at = self.at()
        self.account.reserve(
            epoch_id=self.EPOCH, event_id=f"event-reserve-{self.counter}",
            reservation_id=reservation, lifecycle_id=lifecycle, lane=lane,
            amount=str(Decimal(basis) + Decimal(fee)), at=reserve_at,
            provenance=self.provenance(lane, self.counter),
        )
        enter_at = self.at()
        self.account.enter(
            epoch_id=self.EPOCH, event_id=f"event-enter-{self.counter}",
            reservation_id=reservation, lifecycle_id=lifecycle, lane=lane,
            asset=f"ASSET-{lane.upper()}", basis=basis, fee=fee, at=enter_at,
            strategy_id=f"{lane}-test-policy",
            provenance=self.provenance(lane, self.counter, valued=True, as_of=enter_at),
            prior_stages=(
                {"stage": "qualification", "at": reserve_at},
                {"stage": "authorization", "at": reserve_at},
            ),
            lane_state=lane_state,
        )
        return lifecycle

    def current_mark(self, lane, lifecycle, value, *, valid_for=100, lane_state=None):
        at = self.at()
        valid_until = self.at(self.counter + valid_for)
        self.account.mark(
            epoch_id=self.EPOCH, event_id=f"event-mark-{self.counter}",
            lifecycle_id=lifecycle, at=at, state="CURRENT",
            net_liquidation_value=value, as_of=at, valid_until=valid_until,
            provenance=self.provenance(
                lane, self.counter, valued=True, as_of=at, valid_until=valid_until
            ),
            lane_state=lane_state,
        )
        return valid_until

    def settle(self, lane, lifecycle, gross_proceeds, fee="1.00", exit_reason="canonical_exit"):
        at = self.at()
        self.account.settle(
            epoch_id=self.EPOCH, event_id=f"event-settle-{self.counter}",
            lifecycle_id=lifecycle, gross_proceeds=gross_proceeds, fee=fee,
            exit_reason=exit_reason, at=at,
            provenance=self.provenance(lane, self.counter, valued=True, as_of=at),
        )

    def publish(self, *, as_of=None, valid_until=None):
        as_of = as_of or self.at()
        valid_until = valid_until or self.at(self.counter + 100)
        self.publish_counter += 1
        return self.account.publish(
            epoch_id=self.EPOCH, event_id=f"event-publish-{self.publish_counter}",
            as_of=as_of, valid_until=valid_until,
        )

    def reader_view(self, now=None):
        now = now if now is not None else self.at(self.counter)
        clock = datetime.fromisoformat(now).timestamp
        return Reader(
            self.receipt_path, self.export_path, mode="canonical", clock=clock
        ).view()

    def test_uninitialized_schema_does_not_create_a_real_portfolio(self):
        self.assertEqual(self.account.status()["state"], "NOT_INITIALIZED")
        self.assertEqual(self.account.verify_archive()["sequence"], 0)
        self.assertFalse(self.receipt_path.exists())
        self.assertFalse(self.export_path.exists())

    def test_exact_inception_contract_and_dashboard_hash_semantics(self):
        receipt, receipt_hash = self.activate()
        self.assertEqual(receipt["starting_capital"], "500.00")
        self.assertEqual(receipt["currency"], "USD")
        self.assertIs(receipt["paper_only"], True)
        self.assertEqual(
            receipt_hash,
            hashlib.sha256(dashboard_canonical(receipt).encode()).hexdigest(),
        )
        self.assertEqual(json.loads(self.receipt_path.read_text()), receipt)

    def test_inception_validation_rejects_any_noncanonical_fact(self):
        receipt = inception_receipt(self.EPOCH, self.at(0), "synthetic-inception-event")
        for key, value in (
            ("starting_capital", "499.99"), ("currency", "EUR"), ("paper_only", False)
        ):
            changed = dict(receipt, **{key: value})
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "inception_contract"):
                validate_inception(changed)

    def test_duplicate_and_conflicting_inception_rejected(self):
        receipt, _ = self.activate()
        arguments = dict(
            portfolio_identities=self.identities(),
            lane_identities={lane: self.identities(lane) for lane in LANES},
        )
        with self.assertRaisesRegex(PortfolioIntegrityError, "duplicate_inception"):
            self.account.establish_inception(receipt, **arguments)
        conflict = inception_receipt("other-test-epoch", self.at(0), "other-inception")
        with self.assertRaisesRegex(PortfolioIntegrityError, "conflicting_inception"):
            self.account.establish_inception(conflict, **arguments)

    def test_restart_recovers_receipt_and_export_from_journal(self):
        self.activate()
        first = self.publish()
        self.account.close()
        self.account = None
        self.export_path.unlink()
        self.account = PortfolioAccounting(
            self.database, receipt_path=self.receipt_path, export_path=self.export_path
        )
        recovered = json.loads(self.export_path.read_text())
        self.assertEqual(recovered, first)
        self.assertTrue(self.account.verify_archive()["verified"])

    def test_exact_500_no_trade_export_passes_actual_dashboard_parser(self):
        self.activate()
        export = self.publish()
        self.assertEqual(export["balances"], {
            "equity": "500.00", "available_cash": "500.00", "reserved_cash": "0",
            "deployed_capital": "0", "realized_pnl": "0", "unrealized_pnl": "0",
            "fees": "0", "shared_costs": "0",
        })
        view = self.reader_view()
        self.assertEqual(view["state"], "CURRENT")
        self.assertEqual(view["portfolio"]["metrics"]["equity"]["value"], "500.00")
        self.assertEqual(view["portfolio"]["metrics"]["trades_taken"]["value"], 0)
        self.assertTrue(all(view["portfolio"]["reconciliation"]["value"].values()))

    def test_reservation_moves_shared_cash_without_forcing_entry(self):
        self.activate()
        at = self.at()
        self.account.reserve(
            epoch_id=self.EPOCH, event_id="reserve-event", reservation_id="reservation-1",
            lane="pump", amount="100.00", at=at,
            provenance=self.provenance("pump", 1),
        )
        export = self.publish()
        self.assertEqual(export["balances"]["available_cash"], "400.00")
        self.assertEqual(export["balances"]["reserved_cash"], "100.00")
        self.assertEqual(export["positions"], [])
        self.assertEqual(export["balances"]["equity"], "500.00")

    def test_released_reservation_never_becomes_a_trade(self):
        self.activate()
        at = self.at()
        self.account.reserve(
            epoch_id=self.EPOCH, event_id="reserve-event", reservation_id="reservation-1",
            lane="pump", amount="25.00", at=at,
            provenance=self.provenance("pump", 1),
        )
        at = self.at()
        self.account.release_reservation(
            epoch_id=self.EPOCH, event_id="release-event", reservation_id="reservation-1",
            at=at, provenance=self.provenance("pump", 2),
        )
        export = self.publish()
        self.assertEqual(export["balances"]["available_cash"], "500.00")
        self.assertEqual(export["positions"], [])

    def test_profitable_losing_and_breakeven_terminal_settlements(self):
        self.activate()
        winners = []
        for lane, proceeds, fee in (
            ("pump", "112.00", "1.00"),
            ("pons", "90.00", "1.00"),
            ("ramses", "101.00", "0.00"),
        ):
            lifecycle = self.reserve_enter(lane, basis="100.00", fee="1.00")
            self.settle(lane, lifecycle, proceeds, fee)
            winners.append(lifecycle)
        export = self.publish()
        results = {row["lane"]: row["realized_pnl"] for row in export["positions"]}
        self.assertEqual(results, {"pump": "10.00", "pons": "-12.00", "ramses": "0.00"})
        view = self.reader_view()
        metrics = view["portfolio"]["metrics"]
        self.assertEqual((metrics["wins"]["value"], metrics["losses"]["value"], metrics["breakevens"]["value"]), (1, 1, 1))
        self.assertEqual(metrics["win_rate"]["value"], "50")

    def test_partial_harvest_keeps_one_runner_trade_open(self):
        self.activate()
        lifecycle = self.reserve_enter("pons", basis="100.00", fee="1.00")
        at = self.at()
        self.account.realize(
            epoch_id=self.EPOCH, event_id="harvest-event", lifecycle_id=lifecycle,
            basis_released="40.00", gross_proceeds="50.00", fee="1.00", at=at,
            provenance=self.provenance("pons", 3, valued=True, as_of=at), harvest=True,
        )
        self.current_mark("pons", lifecycle, "66.00")
        export = self.publish()
        position = export["positions"][0]
        self.assertEqual(position["remaining_basis"], "60.00")
        self.assertEqual(position["realized_pnl"], "8.00")
        self.assertEqual(position["harvest_state"], "HARVESTED")
        self.assertEqual(position["runner_state"], "ACTIVE")
        view = self.reader_view()
        metrics = view["lanes"]["pons"]["metrics"]
        self.assertEqual(metrics["trades_taken"]["value"], 1)
        self.assertEqual(metrics["open_positions"]["value"], 1)
        self.assertEqual(metrics["completed_trades"]["value"], 0)

    def test_lp_rebalance_preserves_one_lifecycle(self):
        self.activate()
        lifecycle = self.reserve_enter(
            "meteora", basis="50.00", fee="1.00",
            lane_state={"range_id": "range-10-20", "lp_state": "MAKER_ACTIVE", "in_range": True},
        )
        reserve_at = self.at()
        self.account.reserve(
            epoch_id=self.EPOCH, event_id="rebalance-reserve-event",
            reservation_id="rebalance-reservation", lifecycle_id=lifecycle,
            lane="meteora", amount="10.50", at=reserve_at,
            provenance=self.provenance("meteora", 3),
        )
        at = self.at()
        self.account.rebalance(
            epoch_id=self.EPOCH, event_id="rebalance-event", lifecycle_id=lifecycle,
            reservation_id="rebalance-reservation", basis_released="10.00",
            gross_proceeds="12.00", basis_added="10.00", fee="0.50", at=at,
            provenance=self.provenance("meteora", 4, valued=True, as_of=at),
        )
        self.current_mark(
            "meteora", lifecycle, "52.00",
            lane_state={"range_id": "range-10-20", "lp_state": "MAKER_ACTIVE", "in_range": False},
        )
        export = self.publish()
        position = export["positions"][0]
        self.assertEqual(position["rebalance_count"], 1)
        self.assertEqual(position["remaining_basis"], "50.00")
        self.assertEqual(position["realized_pnl"], "0.50")
        self.assertFalse(position["in_range"])
        self.assertEqual(self.reader_view()["portfolio"]["metrics"]["trades_taken"]["value"], 1)

    def test_simultaneous_realized_and_unrealized_pnl(self):
        self.activate()
        closed = self.reserve_enter("pump", basis="20.00", fee="0.00")
        self.settle("pump", closed, "25.00", fee="0.00")
        opened = self.reserve_enter("pons", basis="30.00", fee="0.00")
        self.current_mark("pons", opened, "34.00")
        export = self.publish()
        self.assertEqual(export["balances"]["realized_pnl"], "5.00")
        self.assertEqual(export["balances"]["unrealized_pnl"], "4.00")
        self.assertEqual(export["balances"]["equity"], "509.00")

    def test_fees_and_shared_costs_reconcile_without_double_counting(self):
        self.activate()
        lifecycle = self.reserve_enter("pump", basis="20.00", fee="1.00")
        self.settle("pump", lifecycle, "25.00", fee="1.00")
        at = self.at()
        self.account.charge_shared_cost(
            epoch_id=self.EPOCH, event_id="shared-cost-event", amount="0.50", at=at,
            provenance=self.provenance(None, 7, valued=True, as_of=at),
        )
        export = self.publish()
        self.assertEqual(export["positions"][0]["realized_pnl"], "3.00")
        self.assertEqual(export["balances"]["realized_pnl"], "2.50")
        self.assertEqual(export["balances"]["fees"], "2.50")
        self.assertEqual(export["balances"]["shared_costs"], "0.50")
        self.assertTrue(all(export["reconciliation"]["checks"].values()))

    def test_each_lane_contributes_independently_against_500(self):
        self.activate()
        for lane, result in zip(LANES, (Decimal("4"), Decimal("3"), Decimal("-2"), Decimal("0"))):
            lifecycle = self.reserve_enter(lane, basis="10.00", fee="0.00")
            self.settle(lane, lifecycle, str(Decimal("10") + result), fee="0.00")
        at = self.at()
        self.account.charge_shared_cost(
            epoch_id=self.EPOCH, event_id="shared-cost-event", amount="1.00", at=at,
            provenance=self.provenance(None, 20, valued=True, as_of=at),
        )
        self.publish()
        view = self.reader_view()
        expected = {"pump": "0.8", "pons": "0.6", "ramses": "-0.4", "meteora": "0"}
        for lane, contribution in expected.items():
            self.assertEqual(view["lanes"][lane]["metrics"]["contribution_pct"]["value"], contribution)
            self.assertIsNone(view["lanes"][lane]["metrics"]["lane_return_pct"]["value"])
        self.assertEqual(view["portfolio"]["metrics"]["realized_pnl"]["value"], "4.00")

    def test_unavailable_mark_keeps_equity_explicitly_unavailable(self):
        self.activate()
        lifecycle = self.reserve_enter("pump", basis="10.00", fee="0.00")
        at = self.at()
        self.account.mark(
            epoch_id=self.EPOCH, event_id="unavailable-mark", lifecycle_id=lifecycle,
            at=at, state="UNAVAILABLE", provenance=self.provenance("pump", 4),
        )
        export = self.publish()
        self.assertIsNone(export["balances"]["equity"])
        self.assertIsNone(export["reconciliation"]["checks"]["equity_equals_inception_plus_net"])
        self.assertEqual(self.reader_view()["portfolio"]["state"], "UNAVAILABLE")

    def test_stale_mark_is_not_converted_to_zero(self):
        self.activate()
        lifecycle = self.reserve_enter("pump", basis="10.00", fee="0.00")
        at = self.at()
        expires = self.at(self.counter + 1)
        self.account.mark(
            epoch_id=self.EPOCH, event_id="current-mark", lifecycle_id=lifecycle,
            at=at, state="CURRENT", net_liquidation_value="12.00", as_of=at,
            valid_until=expires,
            provenance=self.provenance("pump", 4, valued=True, as_of=at, valid_until=expires),
        )
        publish_at = self.at(self.counter + 2)
        export = self.publish(as_of=publish_at, valid_until=self.at(self.counter + 20))
        self.assertEqual(export["positions"][0]["mark"], {"state": "STALE"})
        self.assertIsNone(export["balances"]["equity"])
        self.assertEqual(self.reader_view(now=publish_at)["portfolio"]["state"], "STALE")

    def test_missing_or_stale_usd_conversion_is_rejected(self):
        self.activate()
        reservation = "reservation"
        at = self.at()
        self.account.reserve(
            epoch_id=self.EPOCH, event_id="reserve", reservation_id=reservation,
            lifecycle_id="life", lane="pump", amount="10.00", at=at,
            provenance=self.provenance("pump", 1),
        )
        entry_at = self.at()
        missing = self.provenance("pump", 2)
        with self.assertRaisesRegex(ValueError, "authoritative_usd_value_evidence_required"):
            self.account.enter(
                epoch_id=self.EPOCH, event_id="entry", reservation_id=reservation,
                lifecycle_id="life", lane="pump", asset="SOL", basis="10.00", fee="0",
                at=entry_at, strategy_id="pump-test-policy", provenance=missing,
            )
        stale = self.provenance(
            "pump", 3, valued=True, as_of=at, valid_until=at
        )
        with self.assertRaisesRegex(ValueError, "usd_value_evidence_stale"):
            self.account.enter(
                epoch_id=self.EPOCH, event_id="entry-2", reservation_id=reservation,
                lifecycle_id="life", lane="pump", asset="SOL", basis="10.00", fee="0",
                at=entry_at, strategy_id="pump-test-policy", provenance=stale,
            )

    def test_source_or_config_drift_fails_closed(self):
        self.activate()
        at = self.at()
        changed = self.provenance("pump", 1)
        changed["policy_hash"] = "f" * 64
        with self.assertRaisesRegex(PortfolioIntegrityError, "source_or_config_mismatch"):
            self.account.reserve(
                epoch_id=self.EPOCH, event_id="reserve", reservation_id="r",
                lane="pump", amount="1.00", at=at, provenance=changed,
            )

    def test_pre_inception_and_cross_epoch_facts_are_excluded(self):
        self.activate()
        with self.assertRaisesRegex(PortfolioIntegrityError, "pre_inception_fact"):
            self.account.reserve(
                epoch_id=self.EPOCH, event_id="old", reservation_id="old-r",
                lane="pump", amount="1.00", at=self.at(-1),
                provenance=self.provenance("pump", 1),
            )
        with self.assertRaisesRegex(PortfolioIntegrityError, "cross_epoch_fact"):
            self.account.reserve(
                epoch_id="historical-campaign", event_id="foreign", reservation_id="foreign-r",
                lane="pump", amount="1.00", at=self.at(),
                provenance=self.provenance("pump", 2),
            )
        self.assertEqual(self.publish()["positions"], [])

    def test_duplicate_event_and_duplicate_lifecycle_fail_closed(self):
        self.activate()
        at = self.at()
        kwargs = dict(
            epoch_id=self.EPOCH, event_id="same-event", reservation_id="r1",
            lane="pump", amount="1.00", at=at, provenance=self.provenance("pump", 1),
        )
        self.account.reserve(**kwargs)
        with self.assertRaisesRegex(PortfolioIntegrityError, "duplicate_canonical_event"):
            self.account.reserve(**dict(kwargs, reservation_id="r2"))
        lifecycle = self.reserve_enter("pons", lifecycle="one-life", basis="2.00", fee="0.00")
        at = self.at()
        self.account.reserve(
            epoch_id=self.EPOCH, event_id="second-reserve", reservation_id="second-r",
            lifecycle_id=lifecycle, lane="pons", amount="2.00", at=at,
            provenance=self.provenance("pons", 9),
        )
        at = self.at()
        with self.assertRaisesRegex(PortfolioIntegrityError, "duplicate_entered_lifecycle"):
            self.account.enter(
                epoch_id=self.EPOCH, event_id="second-entry", reservation_id="second-r",
                lifecycle_id=lifecycle, lane="pons", asset="ASSET-PONS", basis="2.00",
                fee="0", at=at, strategy_id="pons-test-policy",
                provenance=self.provenance("pons", 10, valued=True, as_of=at),
            )

    def test_terminal_facts_cannot_be_revised_or_counted_twice(self):
        self.activate()
        lifecycle = self.reserve_enter("pump", basis="10", fee="0")
        self.settle("pump", lifecycle, "11", fee="0")
        at = self.at()
        with self.assertRaisesRegex(PortfolioIntegrityError, "terminal_lifecycle_immutable"):
            self.account.mark(
                epoch_id=self.EPOCH, event_id="late-mark", lifecycle_id=lifecycle,
                at=at, state="UNAVAILABLE", provenance=self.provenance("pump", 8),
            )
        with self.assertRaisesRegex(PortfolioIntegrityError, "terminal_lifecycle_immutable"):
            self.account.settle(
                epoch_id=self.EPOCH, event_id="second-settlement", lifecycle_id=lifecycle,
                gross_proceeds="1", fee="0", exit_reason="again", at=self.at(),
                provenance=self.provenance("pump", 9, valued=True, as_of=self.at(self.counter)),
            )
        self.publish()
        metrics = self.reader_view()["portfolio"]["metrics"]
        self.assertEqual(metrics["trades_taken"]["value"], 1)
        self.assertEqual(metrics["completed_trades"]["value"], 1)

    def test_journal_and_inception_are_append_only(self):
        self.activate()
        lifecycle = self.reserve_enter("pump", basis="10", fee="0")
        self.settle("pump", lifecycle, "11", fee="0")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "append_only"):
            self.account.db.execute("DELETE FROM portfolio_events WHERE action='settle'")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable_inception"):
            self.account.db.execute("UPDATE portfolio_inception SET sha256='bad'")
        self.assertTrue(self.account.verify_archive()["verified"])

    def test_sequence_is_monotonic_across_restart(self):
        self.activate()
        lifecycle = self.reserve_enter("pump", basis="10", fee="0")
        before = self.account.verify_archive()["sequence"]
        sequences = [row[0] for row in self.account.db.execute(
            "SELECT sequence FROM portfolio_events ORDER BY sequence"
        )]
        self.assertEqual(sequences, list(range(1, before + 1)))
        self.account.close()
        self.account = PortfolioAccounting(
            self.database, receipt_path=self.receipt_path, export_path=self.export_path
        )
        self.current_mark("pump", lifecycle, "10")
        self.assertGreater(self.account.verify_archive()["sequence"], before)

    def test_history_is_derived_append_only_and_incomplete_by_default(self):
        self.activate()
        lifecycle = self.reserve_enter("pump", basis="10", fee="0")
        at = self.at()
        self.account.mark(
            epoch_id=self.EPOCH, event_id="unknown-mark", lifecycle_id=lifecycle,
            at=at, state="UNKNOWN", provenance=self.provenance("pump", 5),
        )
        sample_at = self.at()
        self.account.record_history_sample(
            epoch_id=self.EPOCH, event_id="history-gap", at=sample_at, complete=False
        )
        with self.assertRaisesRegex(PortfolioIntegrityError, "duplicate_history_sample"):
            self.account.record_history_sample(
                epoch_id=self.EPOCH, event_id="history-duplicate", at=sample_at, complete=False
            )
        export = self.publish()
        self.assertFalse(export["history_complete"])
        self.assertTrue(any(row["value"] is None for row in export["history"] if row["at"] == sample_at))
        with self.assertRaisesRegex(sqlite3.IntegrityError, "append_only"):
            self.account.db.execute("DELETE FROM portfolio_events WHERE action='history_sample'")

    def test_complete_history_requires_real_values_and_current_coverage(self):
        self.activate()
        lifecycle = self.reserve_enter("pump", basis="10", fee="0")
        self.current_mark("pump", lifecycle, "12")
        sample_at = self.at()
        self.account.record_history_sample(
            epoch_id=self.EPOCH, event_id="history-complete", at=sample_at, complete=True
        )
        export = self.publish(as_of=sample_at, valid_until=self.at(self.counter + 20))
        self.assertTrue(export["history_complete"])
        later = self.at(self.counter + 1)
        export = self.publish(as_of=later, valid_until=self.at(self.counter + 20))
        self.assertFalse(export["history_complete"])

    def test_all_five_reconciliation_equations_are_independently_true(self):
        self.activate()
        lifecycle = self.reserve_enter("pons", basis="100", fee="1")
        at = self.at()
        self.account.realize(
            epoch_id=self.EPOCH, event_id="partial", lifecycle_id=lifecycle,
            basis_released="25", gross_proceeds="30", fee="1", at=at,
            provenance=self.provenance("pons", 7, valued=True, as_of=at), harvest=True,
        )
        self.current_mark("pons", lifecycle, "80")
        at = self.at()
        self.account.charge_shared_cost(
            epoch_id=self.EPOCH, event_id="shared", amount="0.25", at=at,
            provenance=self.provenance(None, 8, valued=True, as_of=at),
        )
        export = self.publish()
        checks = export["reconciliation"]["checks"]
        self.assertEqual(set(checks), {
            "lane_realized_less_shared_costs", "remaining_basis", "cash_basis_conservation",
            "equity_equals_inception_plus_net", "cost_attribution",
        })
        self.assertTrue(all(checks.values()))

    def test_reconciliation_damage_fails_closed(self):
        self.activate()
        state = self.account._replay()
        state["available"] += Decimal("0.01")
        with self.assertRaisesRegex(PortfolioIntegrityError, "portfolio_reconciliation_failure"):
            self.account._reconcile(state)

    def test_float_currency_is_rejected_but_24_digit_decimal_is_exact(self):
        self.activate()
        at = self.at()
        with self.assertRaisesRegex(ValueError, "exact_decimal_required"):
            self.account.reserve(
                epoch_id=self.EPOCH, event_id="float", reservation_id="float-r",
                lane="pump", amount=0.1, at=at, provenance=self.provenance("pump", 1),
            )
        exact = Decimal("0.123456789012345678901234")
        self.account.reserve(
            epoch_id=self.EPOCH, event_id="exact", reservation_id="exact-r",
            lane="pump", amount=exact, at=self.at(), provenance=self.provenance("pump", 2),
        )
        self.assertEqual(self.publish()["balances"]["reserved_cash"], format(exact, "f"))

    def test_export_contains_exact_safe_source_and_config_identities(self):
        self.activate()
        export = self.publish()
        for key in ("source_sha", "policy_hash", "config_hash", "source_diff_sha256"):
            self.assertEqual(export[key], self.identities()[key])
        self.assertEqual(set(export["lane_identities"]), set(LANES))
        self.assertNotIn("value_evidence", canonical(export))

    def test_export_is_directly_compatible_with_current_pr_104_parser(self):
        receipt, receipt_hash = self.activate()
        lifecycle = self.reserve_enter("ramses", basis="40", fee="1", lane_state={
            "range_id": "range-A", "lp_state": "MAKER_ACTIVE", "in_range": True,
        })
        valid_until = self.current_mark("ramses", lifecycle, "43")
        export = self.publish(valid_until=valid_until)
        self.assertEqual(export["schema"], "meme-machine-portfolio-export-v1")
        self.assertEqual(export["inception_sha256"], receipt_hash)
        self.assertEqual(export["epoch_id"], receipt["epoch_id"])
        view = self.reader_view()
        self.assertEqual(view["state"], "CURRENT")
        self.assertEqual(view["positions"][0]["id"], lifecycle)
        self.assertEqual(view["positions"][0]["lp_state"], "MAKER_ACTIVE")
        self.assertTrue(view["portfolio"]["reconciliation"]["value"]["equity_equals_inception_plus_net"])

    def test_projection_failure_does_not_block_canonical_accounting(self):
        self.activate()
        self.export_path.mkdir()
        with self.assertRaises(OSError):
            self.publish()
        self.assertEqual(self.account.status()["projection_state"], "FAIL_CLOSED")
        at = self.at()
        state = self.account.reserve(
            epoch_id=self.EPOCH, event_id="after-projection-failure", reservation_id="r",
            lane="pump", amount="1", at=at, provenance=self.provenance("pump", 2),
        )
        self.assertEqual(state["available"], Decimal("499.00"))
        self.assertTrue(self.account.verify_archive()["verified"])

    def test_time_regression_fails_closed(self):
        self.activate()
        at = self.at(5)
        self.account.reserve(
            epoch_id=self.EPOCH, event_id="later", reservation_id="later-r",
            lane="pump", amount="1", at=at, provenance=self.provenance("pump", 1),
        )
        with self.assertRaisesRegex(PortfolioIntegrityError, "portfolio_time_regression"):
            self.account.reserve(
                epoch_id=self.EPOCH, event_id="earlier", reservation_id="earlier-r",
                lane="pump", amount="1", at=self.at(4),
                provenance=self.provenance("pump", 2),
            )

    def test_complete_lifecycle_coverage_contains_every_entered_lane(self):
        self.activate()
        entered = {self.reserve_enter(lane, basis="5", fee="0") for lane in LANES}
        export = self.publish()
        self.assertTrue(export["complete_lifecycle_coverage"])
        self.assertEqual({row["id"] for row in export["positions"]}, entered)

    def test_equivocal_same_sequence_projection_is_rejected(self):
        self.activate()
        self.publish()
        changed = json.loads(self.export_path.read_text())
        changed["balances"]["available_cash"] = "499.99"
        self.export_path.write_text(json.dumps(changed))
        with self.assertRaisesRegex(PortfolioIntegrityError, "equivocal_export_projection"):
            self.account.recover_projections()

    def test_history_cannot_be_claimed_complete_with_unavailable_values(self):
        self.activate()
        self.reserve_enter("pump", basis="10", fee="0")
        with self.assertRaisesRegex(PortfolioIntegrityError, "incomplete_history_declared_complete"):
            self.account.record_history_sample(
                epoch_id=self.EPOCH, event_id="false-complete-history", at=self.at(), complete=True
            )

    def test_no_provider_or_network_acquisition_occurs(self):
        self.activate()
        with patch("socket.create_connection", side_effect=AssertionError("network acquisition")):
            lifecycle = self.reserve_enter("pump", basis="10", fee="0")
            self.current_mark("pump", lifecycle, "11")
            self.publish()
        self.assertTrue(self.export_path.exists())


if __name__ == "__main__":
    unittest.main()
