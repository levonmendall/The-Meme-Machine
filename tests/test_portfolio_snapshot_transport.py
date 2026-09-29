from contextlib import suppress
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from dashboard.api import Dashboard
from dashboard.model import Reader
from meme_machine.portfolio_accounting import (
    LANES,
    PortfolioAccounting,
    digest,
    inception_receipt,
)
from meme_machine.portfolio_snapshot_transport import (
    SnapshotTransportError,
    apply_snapshot,
    build_snapshot,
    current_paths,
    load_snapshot,
    mirror_once,
    publish_snapshot,
)


class PortfolioSnapshotTransportTests(unittest.TestCase):
    EPOCH = "synthetic-dashboard-transport-epoch"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "portfolio.sqlite"
        self.receipt = self.root / "producer-inception.json"
        self.export = self.root / "producer-export.json"
        self.bundle = self.root / "spool" / "snapshot.json"
        self.replica = self.root / "replica"
        self.account = PortfolioAccounting(
            self.db, receipt_path=self.receipt, export_path=self.export
        )
        value = inception_receipt(
            self.EPOCH, self.at(0), "synthetic-dashboard-transport-inception"
        )
        self.inception_hash = self.account.establish_inception(
            value,
            portfolio_identities=self.identities(),
            lane_identities={lane: self.identities(lane) for lane in LANES},
        )
        self.publish(1, "initial")

    def tearDown(self):
        if self.account is not None:
            with suppress(Exception):
                self.account.close()
        self.tmp.cleanup()

    @staticmethod
    def at(offset):
        return (
            datetime(2026, 9, 29, tzinfo=timezone.utc) + timedelta(seconds=offset)
        ).isoformat()

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

    def publish(self, offset, label, *, valid_for=20):
        return self.account.publish(
            epoch_id=self.EPOCH,
            event_id=f"publish-{label}",
            as_of=self.at(offset),
            valid_until=self.at(offset + valid_for),
        )

    def apply_current(self):
        publish_snapshot(self.receipt, self.export, self.bundle)
        return apply_snapshot(self.bundle, self.replica)

    def test_bundle_binds_epoch_inception_sequence_and_source_identities(self):
        receipt = json.loads(self.receipt.read_text())
        export = json.loads(self.export.read_text())
        bundle = build_snapshot(receipt, export)
        self.assertEqual(bundle["epoch_id"], self.EPOCH)
        self.assertEqual(bundle["inception_sha256"], self.inception_hash)
        self.assertEqual(bundle["sequence"], export["sequence"])
        self.assertEqual(bundle["export_sha256"], digest(export))
        self.assertRegex(bundle["source_identity_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(bundle["snapshot_sha256"], r"^[0-9a-f]{64}$")

    def test_publish_and_apply_expose_one_atomic_generation(self):
        result = self.apply_current()
        self.assertTrue(result["applied"])
        self.assertFalse(result["idempotent"])
        current = self.replica / "current"
        self.assertTrue(current.is_symlink())
        paths = current_paths(self.replica)
        self.assertTrue(Path(paths["inception_path"]).is_file())
        self.assertTrue(Path(paths["accounting_path"]).is_file())
        self.assertTrue(Path(paths["snapshot_path"]).is_file())
        loaded = load_snapshot(paths["snapshot_path"])
        self.assertEqual(loaded["snapshot_sha256"], result["snapshot_sha256"])
        self.assertEqual(os.stat(paths["accounting_path"]).st_mode & 0o777, 0o440)

    def test_same_bundle_redelivery_is_idempotent(self):
        first = self.apply_current()
        second = apply_snapshot(self.bundle, self.replica)
        self.assertTrue(second["idempotent"])
        self.assertFalse(second["applied"])
        self.assertEqual(first["snapshot_sha256"], second["snapshot_sha256"])

    def test_sequence_advances_monotonically_and_regression_fails_closed(self):
        self.apply_current()
        old = self.root / "old.json"
        old.write_bytes(self.bundle.read_bytes())
        self.publish(2, "next")
        publish_snapshot(self.receipt, self.export, self.bundle)
        advanced = apply_snapshot(self.bundle, self.replica)
        self.assertTrue(advanced["applied"])
        with self.assertRaisesRegex(SnapshotTransportError, "sequence_regression"):
            apply_snapshot(old, self.replica)

    def test_same_sequence_different_valid_snapshot_is_equivocation(self):
        self.apply_current()
        other_root = self.root / "other"
        other_root.mkdir()
        other_account = PortfolioAccounting(
            other_root / "portfolio.sqlite",
            receipt_path=other_root / "inception.json",
            export_path=other_root / "export.json",
        )
        try:
            other_account.establish_inception(
                inception_receipt(
                    self.EPOCH, self.at(0), "synthetic-dashboard-transport-inception"
                ),
                portfolio_identities=self.identities(),
                lane_identities={lane: self.identities(lane) for lane in LANES},
            )
            other_account.publish(
                epoch_id=self.EPOCH,
                event_id="different-publish-at-same-sequence",
                as_of=self.at(1),
                valid_until=self.at(99),
            )
            other_bundle = self.root / "other-bundle.json"
            publish_snapshot(
                other_root / "inception.json",
                other_root / "export.json",
                other_bundle,
            )
            self.assertEqual(
                load_snapshot(other_bundle)["sequence"],
                load_snapshot(self.bundle)["sequence"],
            )
            with self.assertRaisesRegex(SnapshotTransportError, "sequence_equivocation"):
                apply_snapshot(other_bundle, self.replica)
        finally:
            other_account.close()

    def test_cross_epoch_bundle_is_rejected_without_pointer_change(self):
        first = self.apply_current()
        foreign_root = self.root / "foreign"
        foreign_root.mkdir()
        foreign = PortfolioAccounting(
            foreign_root / "portfolio.sqlite",
            receipt_path=foreign_root / "inception.json",
            export_path=foreign_root / "export.json",
        )
        try:
            foreign.establish_inception(
                inception_receipt(
                    "foreign-dashboard-epoch",
                    self.at(0),
                    "foreign-dashboard-inception",
                ),
                portfolio_identities=self.identities(),
                lane_identities={lane: self.identities(lane) for lane in LANES},
            )
            foreign.publish(
                epoch_id="foreign-dashboard-epoch",
                event_id="foreign-publish",
                as_of=self.at(1),
                valid_until=self.at(20),
            )
            foreign_bundle = self.root / "foreign.json"
            publish_snapshot(
                foreign_root / "inception.json",
                foreign_root / "export.json",
                foreign_bundle,
            )
            with self.assertRaisesRegex(SnapshotTransportError, "cross_epoch"):
                apply_snapshot(foreign_bundle, self.replica)
            self.assertEqual(
                load_snapshot(self.replica / "current" / "snapshot.json")[
                    "snapshot_sha256"
                ],
                first["snapshot_sha256"],
            )
        finally:
            foreign.close()

    def test_source_identity_change_inside_epoch_is_rejected(self):
        self.apply_current()
        self.publish(2, "source-change")
        export = json.loads(self.export.read_text())
        export["lane_identities"]["pump"]["source_sha"] = "f" * 40
        changed = build_snapshot(json.loads(self.receipt.read_text()), export)
        changed_path = self.root / "changed-source.json"
        changed_path.write_text(
            json.dumps(changed, sort_keys=True, separators=(",", ":")) + "\n"
        )
        with self.assertRaisesRegex(SnapshotTransportError, "source_identity_changed"):
            apply_snapshot(changed_path, self.replica)

    def test_corrupt_or_partial_bundle_never_replaces_current_generation(self):
        first = self.apply_current()
        corrupt = self.root / "corrupt.json"
        corrupt.write_text('{"schema":"meme-machine-dashboard-snapshot-v1"')
        with self.assertRaises(SnapshotTransportError):
            apply_snapshot(corrupt, self.replica)
        after = load_snapshot(self.replica / "current" / "snapshot.json")
        self.assertEqual(after["snapshot_sha256"], first["snapshot_sha256"])

    def test_hash_tampering_is_rejected(self):
        value = publish_snapshot(self.receipt, self.export, self.bundle)
        value["export"]["valid_until"] = self.at(999)
        tampered = self.root / "tampered.json"
        tampered.write_text(
            json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
        )
        with self.assertRaisesRegex(SnapshotTransportError, "hash_mismatch"):
            apply_snapshot(tampered, self.replica)

    def test_retention_bounds_disk_generations(self):
        self.apply_current()
        for offset in range(2, 7):
            self.publish(offset, f"retain-{offset}")
            publish_snapshot(self.receipt, self.export, self.bundle)
            apply_snapshot(self.bundle, self.replica, retain=2)
        generations = [
            path for path in self.replica.iterdir()
            if path.is_dir() and path.name.startswith("generation-")
        ]
        self.assertEqual(len(generations), 2)

    def test_dashboard_reads_replica_without_provider_or_writer_calls(self):
        result = self.apply_current()
        accounting = Path(result["accounting_path"])
        before = (
            accounting.stat().st_ino,
            accounting.stat().st_mtime_ns,
            accounting.stat().st_size,
        )
        reader = Reader(
            result["inception_path"],
            result["accounting_path"],
            mode="canonical",
            clock=lambda: datetime.fromisoformat(self.at(2)).timestamp(),
        )
        with patch(
            "urllib.request.urlopen",
            side_effect=AssertionError("dashboard provider call forbidden"),
        ), patch.object(
            PortfolioAccounting,
            "_append",
            side_effect=AssertionError("dashboard portfolio write forbidden"),
        ):
            response = Dashboard(reader).response("GET", "/api/dashboard/portfolio")
        self.assertEqual(response[0], 200)
        after = (
            accounting.stat().st_ino,
            accounting.stat().st_mtime_ns,
            accounting.stat().st_size,
        )
        self.assertEqual(before, after)

    def test_dashboard_cannot_initialize_reserve_or_dispatch_through_http(self):
        result = self.apply_current()
        dashboard = Dashboard(
            Reader(
                result["inception_path"],
                result["accounting_path"],
                mode="canonical",
                clock=lambda: datetime.fromisoformat(self.at(2)).timestamp(),
            )
        )
        for method, target in (
            ("POST", "/api/dashboard/portfolio"),
            ("PUT", "/api/dashboard/positions"),
            ("PATCH", "/api/dashboard/system"),
            ("DELETE", "/api/dashboard/lanes/pump"),
        ):
            response = dashboard.response(method, target)
            self.assertEqual(response[0], 405)
        self.assertFalse(any(
            name in dir(dashboard)
            for name in ("reserve", "enter", "settle", "establish_inception", "dispatch")
        ))

    def test_stale_replica_is_rendered_stale_without_extending_validity(self):
        result = self.apply_current()
        reader = Reader(
            result["inception_path"],
            result["accounting_path"],
            mode="canonical",
            clock=lambda: datetime.fromisoformat(self.at(30)).timestamp(),
        )
        view = reader.view()
        self.assertEqual(view["state"], "STALE")
        self.assertEqual(
            json.loads(Path(result["accounting_path"]).read_text())["valid_until"],
            self.at(21),
        )

    def test_missing_replica_state_remains_not_initialized_or_unavailable(self):
        self.assertEqual(Reader().view()["state"], "NOT_INITIALIZED")
        missing = self.root / "missing"
        reader = Reader(missing / "inception.json", missing / "accounting.json")
        self.assertEqual(reader.view()["state"], "UNAVAILABLE")

    def test_replica_restart_recovers_current_pointer_and_accepts_next_sequence(self):
        first = self.apply_current()
        del first
        self.publish(2, "restart-next")
        publish_snapshot(self.receipt, self.export, self.bundle)
        second = apply_snapshot(self.bundle, Path(str(self.replica)))
        self.assertTrue(second["applied"])
        reader = Reader(
            second["inception_path"],
            second["accounting_path"],
            mode="canonical",
            clock=lambda: datetime.fromisoformat(self.at(3)).timestamp(),
        )
        self.assertEqual(reader.view()["state"], "CURRENT")

    def test_replication_failure_is_off_path_from_authoritative_publish(self):
        self.apply_current()
        self.publish(2, "producer-keeps-going")
        producer_sequence = json.loads(self.export.read_text())["sequence"]
        bad_root = self.root / "bad-root"
        bad_root.write_text("not-a-directory")
        publish_snapshot(self.receipt, self.export, self.bundle)
        with self.assertRaises(Exception):
            apply_snapshot(self.bundle, bad_root)
        self.assertEqual(
            json.loads(self.export.read_text())["sequence"],
            producer_sequence,
        )
        self.publish(3, "producer-still-going")
        self.assertGreater(
            json.loads(self.export.read_text())["sequence"],
            producer_sequence,
        )

    def test_mirror_once_is_deterministic_local_topology_proof(self):
        target = self.root / "mirror-replica"
        result = mirror_once(
            self.receipt, self.export, self.root / "mirror-bundle.json", target
        )
        again = mirror_once(
            self.receipt, self.export, self.root / "mirror-bundle.json", target
        )
        self.assertTrue(result["applied"])
        self.assertTrue(again["idempotent"])
        self.assertEqual(result["snapshot_sha256"], again["snapshot_sha256"])


if __name__ == "__main__":
    unittest.main()
