"""Read-only SQL/predicate regressions using hand-written unit tables, no service."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'harness'));sys.path.insert(0,str(ROOT))
from core import canonical, file_sha, sha
from preserve import inventory, persist
from verify import verify_restart_raw
from regression_fixtures import safe_overload_row
from review import source_checkout


class RawRestartProofTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name);self.row = safe_overload_row()
        for phase,name in [('before','before-restart-native-state/db'),('after','d/db')]:
            path = self.root/name;path.parent.mkdir()
            proof = self.row['native_restart'][phase];proof['wall'] = 1800000001
            record = ['unit-identity','unit-hash','unit-scope',1,None,1.0,1.0]
            proof['records_digest'] = sha(canonical(record)+b'\n')
            with sqlite3.connect(path) as db:
                for table in proof['protected']:
                    if table != 'integrity':db.execute('CREATE TABLE '+table+'(a,b)')
                db.executescript('CREATE TABLE maintenance_progress(scope,side); CREATE TABLE maintenance_episodes(scope,side);'
                    'CREATE TABLE records(identity,hash,scope,slot,archive,market_time,first_seen);'
                    'CREATE TABLE counters(key,value); CREATE TABLE meta(key,value); CREATE TABLE service_health(key,value);'
                    'CREATE TABLE gaps(scope,lo,hi,reason,repaired);')
                db.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?)',record)
                db.executemany('INSERT INTO counters VALUES(?,?)',proof['counters'].items())
                db.executemany('INSERT INTO service_health VALUES(?,?)',[(k,json.dumps(v)) for k,v in proof['health'].items()])
                db.executemany('INSERT INTO gaps VALUES(?,?,?,?,NULL)',proof['gaps'])
        path = self.root/'BEFORE_RESTART_INVENTORY.json'
        persist(path,{'artifacts':inventory(self.root/'before-restart-native-state')})
        self.row['native_restart']['preserved_original_inventory_sha256'] = file_sha(path)
        # Only the frozen native pure health predicate is loaded. Its module has
        # no entrypoint, service startup, provider call or frame-release code.
        spec = importlib.util.spec_from_file_location('unit_exact_health',source_checkout()/'meme_machine/solana_evidence_health.py')
        self.health = importlib.util.module_from_spec(spec);spec.loader.exec_module(self.health)

    def verify(self):
        package = ModuleType('meme_machine');package.__path__ = []
        with patch.dict(sys.modules,{'meme_machine':package,'meme_machine.solana_evidence_health':self.health}):
            return verify_restart_raw(self.root,self.row)

    def test_native_refusal_health_generation_and_stale_authority_rechecked_from_SQL(self):
        self.assertTrue(self.verify()['native_before_after_rechecked'])

    def test_claimed_native_failed_phase_cannot_replace_raw_health(self):
        self.row['native_restart']['before']['health']['phase'] = 'OFF'
        with self.assertRaisesRegex(ValueError,'native_refusal_health_changed'):self.verify()

    def test_forged_native_refusal_event_cannot_replace_raw_health(self):
        self.row['native_restart']['before']['health']['owner_scheduler']['owner_admission']['events'] = []
        with self.assertRaisesRegex(ValueError,'native_refusal_health_changed'):self.verify()

    def test_changed_restart_gap_cannot_be_hidden_by_proof_dictionary(self):
        self.row['native_restart']['after']['gaps'] = []
        with self.assertRaisesRegex(ValueError,'native_gaps_changed'):self.verify()

    def test_claimed_generation_must_match_actual_native_generation(self):
        self.row['native_restart']['new_generation'] = 'forged'
        with self.assertRaisesRegex(ValueError,'generation_changed'):self.verify()

    def test_stale_refusal_reason_is_recomputed_by_frozen_pure_native_predicate(self):
        self.row['native_restart']['stale_refusals'][0]['reason'] = 'forged'
        with self.assertRaisesRegex(ValueError,'stale_authority_refusal_changed'):self.verify()

    def test_missing_counter_cannot_weaken_committed_work_conservation(self):
        self.row['native_restart']['before']['counters'].pop('archived_records')
        with self.assertRaisesRegex(ValueError,'committed_counters_changed'):self.verify()
