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
        sql=json.loads(rows['storage_maintenance'])['owner_sql_transactions']
        self.assertGreater(sql['begin.calls'],0)
        self.assertGreaterEqual(sql['commit.wall_total_microseconds'],0)
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

    def coverage_fixture(self, prefix=4):
        """An offline interval prefix, followed by a future-delivered interval."""
        db=self.state.writer.db;scope='control:solana'
        with self.state.writer.transaction():
            db.executemany('INSERT INTO coverage(scope,lo,hi,available,proof) VALUES(?,?,?,?,?)',
                ((scope,n,n,100,'offline-interval-'+str(n)) for n in range(1,prefix+1)))
            db.execute('INSERT INTO coverage(scope,lo,hi,available,proof) VALUES(?,?,?,?,?)',
                (scope,prefix+1,prefix+1,200,'offline-future'))
            db.execute('INSERT INTO stream_receipts VALUES(?,?,?,?,?,?,?,?,?,?)',
                (scope,prefix,prefix-1,'tip','parent',95,'[]','offline',100,1))
            for key,value in {'phase':'ACTIVE','heartbeat':100,'topology':'candidate_hybrid_v1',
                    'finalized_frontier:'+scope:{'slot':prefix,'time':95,'seen':100}}.items():
                self.state.fence.health(key,value)
        return scope

    def readers(self):
        from meme_machine.solana_evidence_plane import EvidenceReader
        from meme_machine.lanes.pump.solana_evidence_plane import EvidenceReader as NativeReader
        result=[cls(self.state.writer.path) for cls in (EvidenceReader,NativeReader)]
        for reader in result:self.addCleanup(reader.close)
        return result

    def test_large_prefix_does_not_scan_old_intervals_for_current_health_and_frontier(self):
        from meme_machine.solana_evidence_health import evidence_health
        from meme_machine.lanes.pump.solana_evidence_health import evidence_health as worker_health
        from meme_machine.solana_evidence_runtime import RuntimeEvidence,PUMP_SCOPE
        scope=self.coverage_fixture(16384)
        for reader in self.readers():
            for inspect in (evidence_health,worker_health):
                steps=[0]
                def count():steps[0]+=1;return 0
                reader.db.set_progress_handler(count,1)
                try:
                    observed=inspect(reader,scope,100)
                    self.assertEqual((observed['usable'],observed['frontier_slot']),(True,16384))
                    self.assertLess(steps[0],2000,'live health traversed the historical prefix')
                finally:reader.db.set_progress_handler(None,0)
        plane=RuntimeEvidence(self.state.writer.path,owner='pump',clock=lambda:100)
        self.addCleanup(plane.close)
        steps=[0]
        def count():steps[0]+=1;return 0
        plane.reader.db.set_progress_handler(count,1)
        try:
            self.assertEqual(plane.frontier(PUMP_SCOPE),16384)
            self.assertLess(steps[0],2500,'selective frontier traversed the historical prefix')
        finally:plane.reader.db.set_progress_handler(None,0)

    def test_actual_pump_worker_requires_verified_physical_storage_without_lifetime_file_cap(self):
        from meme_machine.solana_evidence_health import evidence_health
        from meme_machine.lanes.pump.solana_evidence_health import evidence_health as worker_health
        scope=self.coverage_fixture()
        self.state.fence.health('hot_limit_bytes',None)
        self.state.fence.health('storage_capacity_mode','verified_epoch_volume')
        for reader in self.readers():
            for inspect,module in ((evidence_health,'meme_machine.solana_evidence_plane'),
                    (worker_health,'meme_machine.lanes.pump.solana_evidence_plane')):
                with patch(module+'.storage_health',return_value={'state':'ok'}) as pressure:
                    self.assertTrue(inspect(reader,scope,100)['usable'])
                    pressure.assert_any_call(reader.path,required_bytes=32*1024*1024)
                def pressured(path,*,required_bytes=0):
                    return {'state':'critical' if required_bytes==32*1024*1024 else 'ok'}
                with patch(module+'.storage_health',side_effect=pressured):
                    self.assertEqual(inspect(reader,scope,100)['reason'],'evidence_physical_storage_pressure')
                self.state.fence.health('storage_capacity_mode','unverified')
                self.assertEqual(inspect(reader,scope,100)['reason'],'evidence_storage_profile_unverified')
                self.state.fence.health('storage_capacity_mode','verified_epoch_volume')
                self.state.fence.health('hot_limit_bytes',1)
                self.assertEqual(inspect(reader,scope,100)['reason'],'evidence_hot_capacity_pressure')
                self.state.fence.health('hot_limit_bytes',None)
                self.assertEqual(inspect(reader,scope,116)['reason'],'evidence_heartbeat_stale')

    def test_existing_index_and_legacy_snapshot_keep_exact_asof_gap_and_floor_semantics(self):
        from meme_machine.solana_evidence_health import evidence_health,coverage_end_hint
        scope=self.coverage_fixture()
        db=self.state.writer.db
        for modern in (True,False):
            if not modern:db.execute('DROP INDEX maintenance_coverage_end')
            for reader in self.readers():
                self.assertEqual(bool(coverage_end_hint(reader.db)),modern)
                self.assertTrue(reader.covered(scope,1,4,as_of=100))
                self.assertFalse(reader.covered(scope,1,5,as_of=199))
                self.assertTrue(reader.covered(scope,1,5,as_of=200))
                self.assertFalse(reader.covered('program:pump',1,4,as_of=100))
                self.assertEqual(evidence_health(reader,scope,100)['frontier_slot'],4)
                # An overlapping later interval cannot fabricate a missing middle.
                db.execute('DELETE FROM coverage WHERE scope=? AND lo=3',(scope,))
                self.assertFalse(reader.covered(scope,1,4,as_of=100))
                self.assertEqual(evidence_health(reader,scope,100)['reason'],'evidence_discontinuous')
                db.execute('INSERT INTO coverage(scope,lo,hi,available,proof) VALUES(?,?,?,?,?)',
                    (scope,3,3,100,'offline-restored'))
                # A later repair cannot rewrite evidence available to a past decision.
                db.execute('INSERT INTO gaps(scope,lo,hi,reason,created,repaired) VALUES(?,?,?,?,?,?)',
                    (scope,3,4,'offline-disconnect',101,120))
                self.assertFalse(reader.covered(scope,1,4,as_of=115))
                self.assertTrue(reader.covered(scope,1,4,as_of=120))
                db.execute('DELETE FROM gaps WHERE reason=?',('offline-disconnect',))
                db.execute('INSERT INTO meta VALUES(?,?)',('retention_floor:'+scope,'2'))
                self.assertFalse(reader.covered(scope,1,4,as_of=100))
                self.assertTrue(reader.covered(scope,2,4,as_of=100))
                db.execute('DELETE FROM meta WHERE key=?',('retention_floor:'+scope,))
        # Reopening a reader retains the exact same proofs, including availability.
        for reader in self.readers():
            self.assertTrue(reader.covered(scope,1,4,as_of=100))
            self.assertFalse(reader.covered(scope,1,5,as_of=100))


if __name__ == '__main__':
    unittest.main()
