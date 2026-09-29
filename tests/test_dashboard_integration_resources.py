from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import time
import tracemalloc
import unittest

from dashboard.model import Reader
from meme_machine.portfolio_accounting import LANES, PortfolioAccounting, inception_receipt
from meme_machine.portfolio_snapshot_transport import publish_snapshot, apply_snapshot


class DashboardIntegrationResourceTests(unittest.TestCase):
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

    def test_off_path_projection_transport_and_polling_are_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "portfolio.sqlite"
            receipt = root / "inception.json"
            export = root / "export.json"
            bundle = root / "bundle.json"
            replica = root / "replica"
            account = PortfolioAccounting(
                db, receipt_path=receipt, export_path=export
            )
            try:
                epoch = "synthetic-dashboard-resource-epoch"
                account.establish_inception(
                    inception_receipt(
                        epoch, self.at(0), "synthetic-dashboard-resource-inception"
                    ),
                    portfolio_identities=self.identities(),
                    lane_identities={
                        lane: self.identities(lane) for lane in LANES
                    },
                )
                tracemalloc.start()
                wall0 = time.perf_counter()
                cpu0 = time.process_time()
                account.publish(
                    epoch_id=epoch,
                    event_id="resource-publish",
                    as_of=self.at(1),
                    valid_until=self.at(120),
                )
                projection_wall = time.perf_counter() - wall0
                projection_cpu = time.process_time() - cpu0

                sequence_before_transport = account.snapshot()["sequence"]
                wall0 = time.perf_counter()
                cpu0 = time.process_time()
                publish_snapshot(receipt, export, bundle)
                serialization_wall = time.perf_counter() - wall0
                serialization_cpu = time.process_time() - cpu0

                wall0 = time.perf_counter()
                cpu0 = time.process_time()
                result = apply_snapshot(bundle, replica)
                replication_wall = time.perf_counter() - wall0
                replication_cpu = time.process_time() - cpu0

                reader = Reader(
                    result["inception_path"],
                    result["accounting_path"],
                    mode="canonical",
                    clock=lambda: datetime.fromisoformat(self.at(2)).timestamp(),
                )
                wall0 = time.perf_counter()
                cpu0 = time.process_time()
                for _ in range(200):
                    self.assertEqual(reader.view()["state"], "CURRENT")
                polling_wall = time.perf_counter() - wall0
                polling_cpu = time.process_time() - cpu0
                _current, peak = tracemalloc.get_traced_memory()
                tracemalloc.stop()

                metrics = {
                    "projection_wall_seconds": projection_wall,
                    "projection_cpu_seconds": projection_cpu,
                    "serialization_wall_seconds": serialization_wall,
                    "serialization_cpu_seconds": serialization_cpu,
                    "replication_wall_seconds": replication_wall,
                    "replication_cpu_seconds": replication_cpu,
                    "dashboard_200_poll_wall_seconds": polling_wall,
                    "dashboard_200_poll_cpu_seconds": polling_cpu,
                    "peak_tracemalloc_bytes": peak,
                    "portfolio_sqlite_bytes": db.stat().st_size,
                    "export_bytes": export.stat().st_size,
                    "bundle_bytes": bundle.stat().st_size,
                    "replica_accounting_bytes": Path(
                        result["accounting_path"]
                    ).stat().st_size,
                }
                print(
                    "DASHBOARD_INTEGRATION_RESOURCE_PROFILE="
                    + json.dumps(metrics, sort_keys=True)
                )

                self.assertEqual(
                    account.snapshot()["sequence"], sequence_before_transport
                )
                self.assertLess(bundle.stat().st_size, 9 * 1024 * 1024)
                self.assertLess(peak, 64 * 1024 * 1024)
                self.assertLess(
                    projection_cpu
                    + serialization_cpu
                    + replication_cpu
                    + polling_cpu,
                    10.0,
                )
            finally:
                account.close()


if __name__ == "__main__":
    unittest.main()
