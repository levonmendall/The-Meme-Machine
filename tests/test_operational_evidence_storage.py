"""Retained history is not a lifetime allowance; real disk faults stay fatal."""
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from meme_machine.solana_evidence_plane import EvidenceUnavailable,EvidenceWriter
from meme_machine.solana_evidence_service import ServiceState,operational_storage_limit
from meme_machine.solana_evidence_health import evidence_health
from tests.test_retention_outcomes import CONFIG
from tests.test_solana_evidence_plane import record


class OperationalEvidenceStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.path=self.root/'shared/solana-evidence.sqlite'
        self.env=patch.dict(os.environ,MM_MODE='PAPER',MM_OPERATIONAL_PHASE='continuous',
            MM_STATE_ROOT=str(self.root),MM_STORAGE_GUARD_CONFIG=str(self.root/'storage.json'))
        self.env.start();self.addCleanup(self.env.stop)

    def test_epoch_guard_is_required_before_removing_the_file_allowance(self):
        with patch('meme_machine.operational.storage_guard.verify_storage') as guard:
            self.assertIsNone(operational_storage_limit(self.path));guard.assert_called_once_with(self.root)
        with patch.dict(os.environ,MM_STORAGE_GUARD_CONFIG=''):
            with self.assertRaisesRegex(EvidenceUnavailable,'operational_storage_configuration_required'):
                ServiceState(self.path,CONFIG)
        self.assertFalse(self.path.exists())
        from meme_machine.operational.storage_guard import StorageGuardError
        with patch('meme_machine.operational.storage_guard.verify_storage',side_effect=StorageGuardError('unexpected_state_path')):
            with self.assertRaises(StorageGuardError):ServiceState(self.path,CONFIG)
        self.assertFalse(self.path.exists())

    def test_only_the_selected_operational_store_uses_physical_capacity(self):
        with patch('meme_machine.operational.storage_guard.verify_storage') as guard:
            self.assertEqual(operational_storage_limit(self.root/'unrelated.sqlite'),2*1024**3)
            with patch.dict(os.environ,MM_MODE='OFFLINE'):
                self.assertEqual(operational_storage_limit(self.path),2*1024**3)
            guard.assert_not_called()

    def test_history_growth_keeps_durability_and_real_disk_failure_rolls_back(self):
        with patch('meme_machine.operational.storage_guard.verify_storage'):
            state=ServiceState(self.path,CONFIG)
        try:
            self.assertIsNone(state.writer.max_hot_bytes)
            self.assertEqual(state.writer.db.execute('PRAGMA synchronous').fetchone()[0],2)
            with patch('meme_machine.solana_evidence_plane.transient_file_size',return_value=3*1024**3):
                state.writer.ingest([record(scope='program:pump')])
            old=state.writer.db.execute('SELECT identity,hash,first_seen FROM records').fetchall()
            with patch('meme_machine.solana_evidence_plane.storage_health',return_value={'state':'critical'}):
                with self.assertRaisesRegex(EvidenceUnavailable,'storage_capacity_critical'):
                    state.writer.ingest([record(slot=11,scope='program:pump')])
            self.assertEqual(state.writer.db.execute('SELECT identity,hash,first_seen FROM records').fetchall(),old)
        finally:state.close()

    def test_selective_ingestion_checks_the_same_physical_capacity(self):
        from meme_machine.solana_selective_source import install
        from meme_machine.solana_selective_history import economic_records
        from tests.test_solana_selective_evidence import FIXTURE
        with patch('meme_machine.operational.storage_guard.verify_storage'):
            state=ServiceState(self.path,CONFIG)
        try:
            h=install(state);tx=FIXTURE['pump'][1]
            from meme_machine.solana_program_decoders import pump_events
            mint=pump_events(tx)[0]['mint']
            rows=list(economic_records('pump',mint,tx,endpoint_identity=CONFIG.identity,
                seen=1791775000.,source='alchemy_finalized_stream'))
            self.assertTrue(rows)
            with patch('meme_machine.solana_evidence_plane.transient_file_size',return_value=3*1024**3):h.ingest(rows)
            before=state.writer.db.execute('SELECT COUNT(*) FROM rolling_economic_events').fetchone()[0]
            self.assertGreater(before,0)
            with patch('meme_machine.solana_evidence_plane.storage_health',return_value={'state':'critical'}):
                with self.assertRaisesRegex(EvidenceUnavailable,'storage_capacity_critical'):h.ingest(rows)
            self.assertEqual(state.writer.db.execute('SELECT COUNT(*) FROM rolling_economic_events').fetchone()[0],before)
        finally:state.close()

    def test_default_offline_store_retains_its_explicit_file_bound(self):
        writer=EvidenceWriter(self.root/'bounded.sqlite',max_hot_bytes=1024**2)
        try:
            with patch('meme_machine.solana_evidence_plane.transient_file_size',return_value=3*1024**3):
                with self.assertRaisesRegex(EvidenceUnavailable,'hot_store_capacity'):writer.ingest([record(scope='program:pump')])
            self.assertEqual(writer.db.execute('SELECT COUNT(*) FROM records').fetchone()[0],0)
        finally:writer.close()

    def test_storage_guard_configuration_reaches_actual_family_and_source_workers(self):
        from meme_machine.operational.supervisor import Supervisor
        supervisor=Supervisor.__new__(Supervisor)
        supervisor.root=self.root;supervisor.epoch='isolated-test-epoch';supervisor.offline=False
        for lane in ('solana','pump','pons'):
            self.assertEqual(supervisor.environment(lane)['MM_STORAGE_GUARD_CONFIG'],str(self.root/'storage.json'))
        supervisor.offline=True
        self.assertNotIn('MM_STORAGE_GUARD_CONFIG',supervisor.environment('solana'))

    def test_health_requires_canonical_coverage_and_physical_capacity(self):
        db=sqlite3.connect(':memory:');self.addCleanup(db.close)
        db.executescript('CREATE TABLE meta(key,value); CREATE TABLE service_health(key,value);'
            'CREATE TABLE coverage(scope,lo,hi,available); CREATE TABLE stream_receipts(scope,slot,parent);')
        db.executemany('INSERT INTO service_health VALUES(?,?)',[(k,json.dumps(v)) for k,v in dict(
            phase='ACTIVE',heartbeat=100,hot_limit_bytes=None,storage_capacity_mode='verified_epoch_volume',
            **{'finalized_frontier:program:pump':dict(slot=2,time=100,seen=100)}).items()])
        db.execute("INSERT INTO coverage VALUES('program:pump',1,1,100)")
        db.execute("INSERT INTO stream_receipts VALUES('program:pump',2,1)")
        reader=SimpleNamespace(db=db,path=self.path,covered=lambda *a,**k:True)
        with patch('meme_machine.solana_evidence_health.transient_file_size',return_value=3*1024**3),patch(
                'meme_machine.solana_evidence_plane.storage_health',return_value={'state':'ok'}):
            self.assertTrue(evidence_health(reader,'program:pump',100)['usable'])
            with patch('meme_machine.solana_evidence_plane.storage_health',return_value={'state':'critical'}):
                result=evidence_health(reader,'program:pump',100)
                self.assertFalse(result['usable']);self.assertEqual(result['reason'],'evidence_physical_storage_pressure')
            db.execute("DELETE FROM service_health WHERE key='storage_capacity_mode'")
            self.assertEqual(evidence_health(reader,'program:pump',100)['reason'],'evidence_storage_profile_unverified')
            db.execute("INSERT INTO service_health VALUES('storage_capacity_mode','\"verified_epoch_volume\"')")
            db.execute('DELETE FROM coverage')
            self.assertFalse(evidence_health(reader,'program:pump',100)['usable'])


if __name__=='__main__':unittest.main()
