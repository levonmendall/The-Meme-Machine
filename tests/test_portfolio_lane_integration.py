from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dashboard.model import Reader
from meme_machine.portfolio_accounting import (
    LANES,
    PortfolioAccounting,
    PortfolioIntegrityError,
    digest,
    inception_receipt,
)
from meme_machine.portfolio_lane_integration import (
    DormantPortfolioLaneProducer,
    LaneEvent,
    PortfolioLaneProducer,
    producer_from_environment,
    usd_evidence,
)


class PortfolioLaneIntegrationTests(unittest.TestCase):
    EPOCH = "synthetic-lane-integration-epoch"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.database = self.root / "portfolio.sqlite"
        self.receipt_path = self.root / "inception.json"
        self.export_path = self.root / "export.json"
        self.account = PortfolioAccounting(
            self.database,
            receipt_path=self.receipt_path,
            export_path=self.export_path,
        )
        receipt = inception_receipt(
            self.EPOCH, self.at(0), "synthetic-lane-integration-inception"
        )
        self.receipt_hash = self.account.establish_inception(
            receipt,
            portfolio_identities=self.identities(),
            lane_identities={lane: self.identities(lane) for lane in LANES},
        )
        self.producer = PortfolioLaneProducer(
            self.account,
            epoch_id=self.EPOCH,
            inception_sha256=self.receipt_hash,
        )
        self.clock = 0
        self.native_sequences = {}

    def tearDown(self):
        if self.account is not None:
            with suppress(Exception):
                self.account.close()
        self.tmp.cleanup()

    @staticmethod
    def identities(lane=None):
        digit = {
            None: "a", "pump": "1", "pons": "2", "ramses": "3", "meteora": "4"
        }[lane]
        return {
            "source_sha": digit * 40,
            "policy_hash": digit * 64,
            "config_hash": ("b" if digit != "b" else "c") * 64,
            "source_diff_sha256": ("c" if digit != "c" else "d") * 64,
            "strategy_id": f"{lane or 'portfolio'}-policy-v1",
        }

    @staticmethod
    def at(offset):
        return (
            datetime(2026, 9, 24, tzinfo=timezone.utc) + timedelta(seconds=offset)
        ).isoformat()

    def next_at(self):
        self.clock += 1
        return self.at(self.clock)

    def event_args(self, lane, lifecycle, label, *, at=None, sequence=None):
        key = (lane, lifecycle)
        if sequence is None:
            sequence = self.native_sequences.get(key, 0) + 1
        self.native_sequences[key] = max(self.native_sequences.get(key, 0), sequence)
        return {
            "native_lifecycle_id": lifecycle,
            "native_event_id": f"{lane}-{lifecycle}-{label}",
            "native_sequence": sequence,
            "native_journal_hash": digest([lane, lifecycle, label, sequence]),
            "at": at or self.next_at(),
        }

    def evidence(self, lane, label, at, *, valid_for=100):
        origin = datetime(2026, 9, 24, tzinfo=timezone.utc)
        offset = int((datetime.fromisoformat(at) - origin).total_seconds())
        return usd_evidence(
            f"usd-{lane}-{label}", digest([lane, label, "usd"]),
            at, self.at(offset + valid_for),
        )

    def reserve_enter(
        self, lane, lifecycle, *, reserved="50", basis="49", fee="1",
        lane_state=None,
    ):
        adapter = self.producer.lane(lane)
        adapter.reserve(
            amount=reserved,
            **self.event_args(lane, lifecycle, "reserve"),
        )
        args = self.event_args(lane, lifecycle, "enter")
        adapter.enter(
            asset=f"ASSET-{lane.upper()}", basis=basis, fee=fee,
            strategy_id=f"{lane}-policy-v1",
            value_evidence=self.evidence(lane, "enter", args["at"]),
            prior_stages=(
                {"stage": "qualification", "at": self.at(self.clock - 1)},
                {"stage": "authorization", "at": self.at(self.clock - 1)},
            ),
            lane_state=lane_state,
            **args,
        )
        return adapter

    def test_normal_startup_is_dormant_and_creates_no_files(self):
        untouched = self.root / "must-not-exist.sqlite"
        env = {key: value for key, value in os.environ.items() if not key.startswith("MM_PORTFOLIO_")}
        with patch.dict(os.environ, env, clear=True):
            producer = producer_from_environment()
            self.assertIsInstance(producer, DormantPortfolioLaneProducer)
            self.assertEqual(producer.status()["state"], "NOT_INITIALIZED")
            self.assertFalse(untouched.exists())
            receipt = producer.lane("pump").reserve_before_fill(amount="50")
            self.assertFalse(receipt["accepted"])

    def test_partial_activation_configuration_fails_without_creating_database(self):
        missing = self.root / "not-created.sqlite"
        with self.assertRaisesRegex(
            PortfolioIntegrityError, "incomplete_portfolio_integration_binding"
        ):
            producer_from_environment({"MM_PORTFOLIO_ACCOUNTING_DB": str(missing)})
        self.assertFalse(missing.exists())

    def test_open_existing_requires_exact_initialized_epoch_and_hash(self):
        self.account.close()
        self.account = None
        opened = PortfolioLaneProducer.open_existing(
            self.database,
            epoch_id=self.EPOCH,
            inception_sha256=self.receipt_hash,
        )
        self.producer = opened
        self.assertEqual(opened.status()["epoch_id"], self.EPOCH)
        opened.close()
        self.producer = None

        with self.assertRaisesRegex(PortfolioIntegrityError, "inception_identity_mismatch"):
            PortfolioLaneProducer.open_existing(
                self.database, epoch_id=self.EPOCH, inception_sha256="f" * 64
            )

    def test_all_four_lane_adapters_map_real_boundary_names(self):
        pump = self.producer.lane("pump")
        pons = self.producer.lane("pons")
        ramses = self.producer.lane("ramses")
        meteora = self.producer.lane("meteora")
        for adapter, names in (
            (pump, ("reserve_before_fill", "fill_committed", "partial_harvest", "settlement")),
            (pons, ("reserve_before_entry", "entry_committed", "partial_exit", "runner_mark")),
            (ramses, ("reserve_before_open", "open_committed", "checkpoint_rebalance")),
            (meteora, ("reserve_before_deposit", "deposit_committed", "range_rebalance")),
        ):
            for name in names:
                self.assertTrue(callable(getattr(adapter, name)))

    def test_reservation_release_and_insufficient_shared_capital(self):
        pump = self.producer.lane("pump")
        pump.reserve_before_fill(
            amount="125", **self.event_args("pump", "cancelled", "reserve")
        )
        pump.release_failed_fill(
            **self.event_args("pump", "cancelled", "release")
        )
        for lane in LANES:
            self.producer.lane(lane).reserve(
                amount="125", **self.event_args(lane, f"{lane}-position", "reserve")
            )
        with self.assertRaisesRegex(PortfolioIntegrityError, "portfolio_capital_exhausted"):
            self.producer.lane("pump").reserve(
                amount="0.000000000000000000000001",
                **self.event_args("pump", "overcommit", "reserve"),
            )
        state = self.account.snapshot()
        self.assertEqual(state["available"], Decimal("0"))
        self.assertEqual(sum(x["amount"] for x in state["reservations"].values()), Decimal("500"))
        self.assertEqual(state["positions"], {})

    def test_missing_authoritative_usd_entry_conversion_fails_closed(self):
        adapter = self.producer.lane("ramses")
        adapter.reserve(
            amount="20", **self.event_args("ramses", "native-quote", "reserve")
        )
        args = self.event_args("ramses", "native-quote", "enter")
        with self.assertRaisesRegex(
            PortfolioIntegrityError, "authoritative_usd_value_evidence_required"
        ):
            adapter.event(
                "enter",
                data={
                    "asset": "NATIVE-QUOTE-POOL", "basis": "20", "fee": "0",
                    "strategy_id": "ramses-policy-v1", "prior_stages": [],
                    "lane_state": {"range_id": "range-1", "lp_state": "OPEN"},
                },
                value_evidence=None,
                **args,
            )
        self.assertEqual(self.account.snapshot()["sequence"], 2)

    def test_duplicate_delivery_is_idempotent_and_conflict_fails_closed(self):
        adapter = self.producer.lane("pump")
        args = self.event_args("pump", "duplicate", "reserve")
        first = adapter.reserve(amount="25", **args)
        second = adapter.reserve(amount="25", **args)
        self.assertFalse(first["idempotent"])
        self.assertTrue(second["idempotent"])
        self.assertEqual(first["event_id"], second["event_id"])
        changed = dict(args, native_journal_hash="f" * 64)
        with self.assertRaisesRegex(
            PortfolioIntegrityError, "conflicting_duplicate_native_event"
        ):
            adapter.reserve(amount="25", **changed)
        self.assertEqual(len(self.account.snapshot()["reservations"]), 1)

    def test_native_sequence_gap_regression_and_cross_epoch_fail_closed(self):
        adapter = self.producer.lane("pons")
        with self.assertRaisesRegex(PortfolioIntegrityError, "native_sequence_gap_or_regression"):
            adapter.reserve(
                amount="10",
                **self.event_args("pons", "sequence", "gap", sequence=2),
            )
        args = self.event_args("pons", "foreign", "reserve")
        with self.assertRaisesRegex(PortfolioIntegrityError, "cross_epoch_fact"):
            adapter.event(
                "reserve", data={"amount": "10"}, epoch_id="old-epoch", **args
            )
        self.assertEqual(self.account.snapshot()["sequence"], 1)

    def test_partial_harvest_runner_and_rebalance_do_not_add_trades(self):
        pons = self.reserve_enter(
            "pons", "runner", reserved="101", basis="100", fee="1",
            lane_state={
                "harvest_state": "PENDING", "runner_state": "FULL",
                "remaining_runner_exposure": "100",
            },
        )
        args = self.event_args("pons", "runner", "harvest")
        pons.partial_exit(
            basis_released="25", gross_proceeds="31", fee="1",
            value_evidence=self.evidence("pons", "harvest", args["at"]),
            **args,
        )
        ramses = self.reserve_enter(
            "ramses", "maker", reserved="101", basis="100", fee="1",
            lane_state={
                "range_id": "ramses-range", "lp_state": "OPEN", "in_range": True,
                "rebalance_state": "MONITORING",
            },
        )
        ramses.reserve_rebalance(
            native_reservation_id="maker-rebalance-1", amount="11",
            **self.event_args("ramses", "maker", "rebalance-reserve"),
        )
        args = self.event_args("ramses", "maker", "rebalance")
        ramses.checkpoint_rebalance(
            native_reservation_id="maker-rebalance-1",
            basis_released="20", gross_proceeds="22", basis_added="10", fee="1",
            lane_state={
                "range_id": "ramses-range-2", "lp_state": "OPEN", "in_range": False,
                "rebalance_state": "MONITORING",
            },
            value_evidence=self.evidence("ramses", "rebalance", args["at"]),
            **args,
        )
        export = self.account.publish(
            epoch_id=self.EPOCH, event_id="publish-runner-rebalance",
            as_of=self.next_at(), valid_until=self.at(self.clock + 100),
        )
        self.assertEqual(len(export["positions"]), 2)
        by_lane = {row["lane"]: row for row in export["positions"]}
        self.assertEqual(by_lane["pons"]["remaining_basis"], "75")
        self.assertEqual(by_lane["pons"]["runner_state"], "ACTIVE")
        self.assertEqual(by_lane["ramses"]["rebalance_count"], 1)
        self.assertEqual(by_lane["ramses"]["remaining_basis"], "90")
        self.assertEqual(by_lane["ramses"]["range_id"], "ramses-range-2")
        self.assertIs(by_lane["ramses"]["in_range"], False)

    def test_current_stale_and_unavailable_marks_preserve_state(self):
        pump = self.reserve_enter("pump", "marked", reserved="51", basis="50", fee="1")
        args = self.event_args("pump", "marked", "current-mark")
        pump.mark(
            state="CURRENT", net_liquidation_value="55.25",
            value_evidence=self.evidence("pump", "mark", args["at"]), **args,
        )
        args = self.event_args("pump", "marked", "stale-mark")
        pump.mark(state="STALE", **args)
        self.assertEqual(
            self.account.snapshot()["positions"]["pump:marked"]["mark"]["state"],
            "STALE",
        )
        args = self.event_args("pump", "marked", "unavailable-mark")
        pump.mark(state="UNAVAILABLE", **args)
        export = self.account.publish(
            epoch_id=self.EPOCH, event_id="publish-unavailable",
            as_of=self.next_at(), valid_until=self.at(self.clock + 100),
        )
        self.assertIsNone(export["balances"]["equity"])
        self.assertIsNone(export["balances"]["unrealized_pnl"])
        self.assertEqual(export["positions"][0]["mark"]["state"], "UNAVAILABLE")

    def test_terminal_settlement_is_immutable_and_retry_safe(self):
        adapter = self.reserve_enter("meteora", "terminal", reserved="51", basis="50", fee="1")
        args = self.event_args("meteora", "terminal", "settle")
        evidence = self.evidence("meteora", "settle", args["at"])
        first = adapter.settlement(
            gross_proceeds="60", fee="1", exit_reason="range_exit",
            value_evidence=evidence, **args,
        )
        retry = adapter.settlement(
            gross_proceeds="60", fee="1", exit_reason="range_exit",
            value_evidence=evidence, **args,
        )
        self.assertTrue(retry["idempotent"])
        self.assertEqual(first["event_id"], retry["event_id"])
        later = self.event_args("meteora", "terminal", "mutate-terminal")
        with self.assertRaisesRegex(PortfolioIntegrityError, "terminal_lifecycle_immutable"):
            adapter.settlement(
                gross_proceeds="61", fee="1", exit_reason="changed_exit",
                value_evidence=self.evidence("meteora", "mutate", later["at"]),
                **later,
            )

    def test_restart_recovers_native_cursors_and_ambiguous_entry(self):
        adapter = self.producer.lane("pump")
        adapter.reserve(amount="31", **self.event_args("pump", "restart", "reserve"))
        args = self.event_args("pump", "restart", "enter")
        evidence = self.evidence("pump", "enter-restart", args["at"])
        entered = adapter.enter(
            asset="RESTART-ASSET", basis="30", fee="1",
            strategy_id="pump-policy-v1", value_evidence=evidence, **args,
        )
        self.account.close()
        self.account = PortfolioAccounting(
            self.database,
            receipt_path=self.receipt_path,
            export_path=self.export_path,
        )
        self.producer = PortfolioLaneProducer(
            self.account, epoch_id=self.EPOCH, inception_sha256=self.receipt_hash
        )
        retry = self.producer.lane("pump").enter(
            asset="RESTART-ASSET", basis="30", fee="1",
            strategy_id="pump-policy-v1", value_evidence=evidence, **args,
        )
        self.assertTrue(retry["idempotent"])
        self.assertEqual(entered["event_id"], retry["event_id"])
        mark_args = self.event_args("pump", "restart", "mark")
        result = self.producer.lane("pump").mark(state="UNKNOWN", **mark_args)
        self.assertFalse(result["idempotent"])
        self.assertEqual(len(self.account.snapshot()["positions"]), 1)

    def test_cross_lane_concurrency_prevents_overcommit_and_lost_updates(self):
        common_time = self.next_at()
        requests = []
        for lane in LANES:
            lifecycle = f"concurrent-{lane}"
            args = self.event_args(lane, lifecycle, "reserve", at=common_time)
            requests.append((lane, args))

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(
                lambda row: self.producer.lane(row[0]).reserve(amount="125", **row[1]),
                requests,
            ))
        self.assertEqual(len(results), 4)
        self.assertTrue(all(row["accepted"] for row in results))
        state = self.account.snapshot()
        self.assertEqual(state["available"], Decimal("0"))
        self.assertEqual(len(state["reservations"]), 4)

        duplicate_args = requests[0][1]
        with ThreadPoolExecutor(max_workers=2) as pool:
            duplicate = list(pool.map(
                lambda _index: self.producer.lane("pump").reserve(
                    amount="125", **duplicate_args
                ),
                range(2),
            ))
        self.assertTrue(all(row["idempotent"] for row in duplicate))
        with self.assertRaisesRegex(PortfolioIntegrityError, "portfolio_capital_exhausted"):
            self.producer.lane("pump").reserve(
                amount="1", **self.event_args("pump", "fifth", "reserve", at=common_time)
            )

        expected = self.account.snapshot()
        self.account.close()
        self.account = PortfolioAccounting(self.database)
        recovered = self.account.snapshot()
        self.assertEqual(recovered, expected)
        self.producer = PortfolioLaneProducer(
            self.account, epoch_id=self.EPOCH, inception_sha256=self.receipt_hash
        )
        self.assertEqual(self.account.verify_archive()["sequence"], 5)

    def test_synthetic_all_lane_flow_reconciles_and_parses_in_pr104_reader(self):
        cancelled = self.producer.lane("pump")
        cancelled.reserve_before_fill(
            amount="10", **self.event_args("pump", "cancelled-all-lane", "reserve")
        )
        cancelled.release_failed_fill(
            **self.event_args("pump", "cancelled-all-lane", "release")
        )
        adapters = {
            "pump": self.reserve_enter("pump", "pump-life", reserved="80", basis="79", fee="1"),
            "pons": self.reserve_enter(
                "pons", "pons-life", reserved="100", basis="99", fee="1",
                lane_state={
                    "harvest_state": "PENDING", "runner_state": "FULL",
                    "remaining_runner_exposure": "99",
                },
            ),
            "ramses": self.reserve_enter(
                "ramses", "ramses-life", reserved="120", basis="119", fee="1",
                lane_state={
                    "range_id": "ramses-pool-range", "lp_state": "OPEN",
                    "in_range": True, "rebalance_state": "MONITORING",
                },
            ),
            "meteora": self.reserve_enter(
                "meteora", "meteora-life", reserved="140", basis="139", fee="1",
                lane_state={
                    "range_id": "meteora-pool-range", "lp_state": "OPEN",
                    "in_range": False, "rebalance_state": "MONITORING",
                },
            ),
        }
        with self.assertRaisesRegex(PortfolioIntegrityError, "portfolio_capital_exhausted"):
            self.producer.lane("pump").reserve(
                amount="61", **self.event_args("pump", "all-lane-overcommit", "reserve")
            )

        pons_args = self.event_args("pons", "pons-life", "harvest")
        adapters["pons"].partial_exit(
            basis_released="20", gross_proceeds="25", fee="1",
            value_evidence=self.evidence("pons", "harvest-all", pons_args["at"]),
            **pons_args,
        )
        adapters["ramses"].reserve_rebalance(
            native_reservation_id="ramses-rebalance-1", amount="11",
            **self.event_args("ramses", "ramses-life", "rebalance-reserve"),
        )
        rebalance_args = self.event_args("ramses", "ramses-life", "rebalance")
        adapters["ramses"].checkpoint_rebalance(
            native_reservation_id="ramses-rebalance-1",
            basis_released="20", gross_proceeds="22", basis_added="10", fee="1",
            value_evidence=self.evidence("ramses", "rebalance-all", rebalance_args["at"]),
            **rebalance_args,
        )

        last_mark = None
        for lane, lifecycle, value, state in (
            ("pump", "pump-life", "82", "CURRENT"),
            ("pons", "pons-life", "85", "CURRENT"),
            ("ramses", "ramses-life", None, "STALE"),
            ("meteora", "meteora-life", None, "UNAVAILABLE"),
        ):
            args = self.event_args(lane, lifecycle, "mark")
            kwargs = dict(state=state, **args)
            if state == "CURRENT":
                kwargs.update(
                    net_liquidation_value=value,
                    value_evidence=self.evidence(lane, "all-mark", args["at"]),
                )
            receipt = adapters[lane].mark(**kwargs)
            last_mark = (lane, dict(kwargs), receipt)

        self.account.close()
        self.account = PortfolioAccounting(
            self.database,
            receipt_path=self.receipt_path,
            export_path=self.export_path,
        )
        self.producer = PortfolioLaneProducer(
            self.account, epoch_id=self.EPOCH, inception_sha256=self.receipt_hash
        )
        adapters = {lane: self.producer.lane(lane) for lane in LANES}
        lane, retry_kwargs, original_mark = last_mark
        retry = adapters[lane].mark(**retry_kwargs)
        self.assertTrue(retry["idempotent"])
        self.assertEqual(retry["event_id"], original_mark["event_id"])

        for lane, lifecycle, proceeds in (
            ("pump", "pump-life", "83"),
            ("pons", "pons-life", "80"),
            ("ramses", "ramses-life", "111"),
            ("meteora", "meteora-life", "135"),
        ):
            args = self.event_args(lane, lifecycle, "settle")
            adapters[lane].settlement(
                gross_proceeds=proceeds, fee="1", exit_reason=f"{lane}_exit",
                value_evidence=self.evidence(lane, "all-settle", args["at"]),
                **args,
            )

        history_at = self.next_at()
        self.account.record_history_sample(
            epoch_id=self.EPOCH, event_id="all-lane-history", at=history_at,
            complete=True,
        )
        publish_at = self.next_at()
        export = self.account.publish(
            epoch_id=self.EPOCH, event_id="all-lane-publish",
            as_of=publish_at, valid_until=self.at(self.clock + 100),
        )
        self.assertEqual(export["schema"], "meme-machine-portfolio-export-v1")
        self.assertEqual(len(export["positions"]), 4)
        self.assertTrue(all(export["reconciliation"]["checks"].values()))
        self.assertEqual(export["balances"]["equity"], "500.00")
        self.assertEqual(export["balances"]["available_cash"], "500.00")
        self.assertEqual(export["balances"]["deployed_capital"], "0")
        self.assertEqual(export["balances"]["realized_pnl"], "0")
        self.assertEqual(export["balances"]["fees"], "10")

        view = Reader(
            self.receipt_path, self.export_path, mode="canonical",
            clock=datetime.fromisoformat(publish_at).timestamp,
        ).view()
        self.assertEqual(view["state"], "CURRENT")
        self.assertEqual(view["portfolio"]["metrics"]["trades_taken"]["value"], 4)
        self.assertEqual(view["portfolio"]["metrics"]["completed_trades"]["value"], 4)
        self.assertEqual(
            {row["id"] for row in view["positions"]},
            {f"{lane}:{lane}-life" for lane in LANES},
        )

    def test_float_money_and_network_acquisition_are_never_used(self):
        adapter = self.producer.lane("pump")
        with self.assertRaisesRegex(ValueError, "exact_decimal_required"):
            adapter.reserve(amount=10.5, **self.event_args("pump", "float", "reserve"))
        with patch("urllib.request.urlopen", side_effect=AssertionError("network forbidden")):
            adapter.reserve(
                amount="10.50", **self.event_args("pump", "decimal", "reserve")
            )


if __name__ == "__main__":
    unittest.main()
