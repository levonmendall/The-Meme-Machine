"""Read-only SQL/predicate regressions using hand-written unit tables, no service."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'harness'));sys.path.insert(0,str(ROOT))
from verify import verify_restart_raw
from restart_fixtures import make_restart, native_reads


class RawRestartProofTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.native = self.enterContext(native_reads())
        self.row = make_restart(self.root,self.native)

    def verify(self):
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
