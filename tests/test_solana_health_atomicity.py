"""A periodic health snapshot has one durable publication boundary."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from meme_machine.solana_evidence_service import ServiceState
from meme_machine.solana_provider_config import AlchemyEndpoint


class HealthAtomicityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = ServiceState(Path(self.temp.name)/'db', AlchemyEndpoint.parse(
            'https://solana-mainnet.g.alchemy.com/v2/offline-test'))
        self.addCleanup(self.state.close)

    def snapshot(self):
        return dict(self.state.writer.db.execute('SELECT key,value FROM service_health'))

    def test_one_publication_does_not_multiply_durable_commit_latency(self):
        commits = []
        db = self.state.writer.db
        db.set_trace_callback(lambda sql: commits.append(sql) if sql == 'COMMIT' else None)
        try:
            self.state.publish_health({'rpc_calls': 17}, {'frames': 29}, {'queued': 3})
        finally:
            db.set_trace_callback(None)
        self.assertEqual(len(commits), 1,
            'periodic telemetry multiplies fsync latency in the serial evidence owner')
        rows = self.snapshot()
        self.assertEqual(json.loads(rows['repair_http']), {'rpc_calls': 17})
        self.assertEqual(json.loads(rows['ipc']), {'frames': 29})
        self.assertEqual(json.loads(rows['owner_scheduler']), {'queued': 3})
        self.assertFalse(db.in_transaction)

    def test_interruption_cannot_publish_new_heartbeat_with_old_storage_and_provider_state(self):
        self.state.publish_health({'rpc_calls': 1}, {'frames': 2}, {'queued': 0})
        before = self.snapshot()
        native = self.state.fence.health
        def interrupted(key, value):
            if key == 'storage_maintenance':
                raise RuntimeError('controlled_health_interruption')
            return native(key, value)
        with patch.object(self.state.fence, 'health', side_effect=interrupted):
            with self.assertRaisesRegex(RuntimeError, '^controlled_health_interruption$'):
                self.state.publish_health({'rpc_calls': 10}, {'frames': 20}, {'queued': 1})
        self.assertEqual(self.snapshot(), before, 'interrupted snapshot was partly durable')
        self.assertFalse(self.state.writer.db.in_transaction)
        self.state.publish_health({'rpc_calls': 11}, {'frames': 21}, {'queued': 0})
        self.assertEqual(json.loads(self.snapshot()['repair_http']), {'rpc_calls': 11})


if __name__ == '__main__':
    unittest.main()
