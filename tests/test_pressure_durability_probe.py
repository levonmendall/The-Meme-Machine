"""Causal latency probe retains real SQLite and production health operations."""
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from certification.pressure_diagnostics import SQLTimings
from certification.pressure_durability_compare import legacy_health
from meme_machine.solana_evidence_service import ServiceState
from meme_machine.solana_provider_config import AlchemyEndpoint


class DurabilityProbeTests(unittest.TestCase):
    def test_changed_commit_delay_excludes_read_transactions_and_rolled_back_rows(self):
        timings = SQLTimings(commit_latency_seconds=.006)
        with patch('certification.pressure_diagnostics.time.sleep') as sleep, timings.enabled():
            db = sqlite3.connect(':memory:', isolation_level=None)
            try:
                db.execute('CREATE TABLE sample(value)')
                db.execute('BEGIN'); db.execute('INSERT INTO sample VALUES(1)'); db.execute('COMMIT')
                db.execute('BEGIN'); db.execute('SELECT * FROM sample').fetchall(); db.execute('COMMIT')
                db.execute('BEGIN'); db.execute('INSERT INTO sample VALUES(2)'); db.execute('ROLLBACK')
                db.execute('BEGIN'); db.execute('COMMIT')
            finally:
                db.close()
        sleep.assert_called_once_with(.006)

    def test_health_probe_conserves_fields_while_isolating_six_vs_one_durable_commits(self):
        with tempfile.TemporaryDirectory() as td:
            timings = SQLTimings(commit_latency_seconds=.006)
            with patch('certification.pressure_diagnostics.time.sleep'), timings.enabled():
                state = ServiceState(Path(td)/'db', AlchemyEndpoint.parse(
                    'https://solana-mainnet.g.alchemy.com/v2/offline-test'))
                try:
                    before = timings.snapshot()['injected_commit_wait']['calls']
                    legacy_health(state, {'calls': 1}, {'frames': 2}, {'queue': 0})
                    legacy = timings.snapshot()['injected_commit_wait']['calls'] - before
                    before += legacy
                    state.publish_health({'calls': 3}, {'frames': 4}, {'queue': 0})
                    batched = timings.snapshot()['injected_commit_wait']['calls'] - before
                    self.assertEqual((legacy, batched), (6, 1))
                    self.assertEqual(state.writer.db.execute(
                        "SELECT value FROM service_health WHERE key='repair_http'").fetchone()[0], '{"calls":3}')
                    self.assertFalse(state.writer.db.in_transaction)
                finally:
                    state.close()


if __name__ == '__main__':
    unittest.main()
