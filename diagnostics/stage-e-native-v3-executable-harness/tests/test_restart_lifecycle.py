"""WARMING -> OFF regression matrix; SQL/read functions only, no native service."""
from contextlib import closing, nullcontext
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'harness'));sys.path.insert(0,str(ROOT))
from core import COHORT, file_sha, read
from overload import capture_stale_refusals
from preserve import persist, seal
from regression_fixtures import interval
from restart_fixtures import WALL, make_restart, native_reads, raw_state, rebind_raw, rewrite_refusal
from verify import OVERLOAD, SCOPES, stress_member_result, verify_restart_raw, verify_trial


class LifecycleAssertions:
    """Run every assertion for both refusal reasons and both C outcomes."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.native = self.enterContext(native_reads())
        self.row = make_restart(self.root,self.native,reason=self.reason,full_profile=self.full_profile)

    def verify(self):
        return verify_restart_raw(self.root,self.row)

    def refusal(self):
        return self.row['native_restart']['stale_refusals'][0]

    def change_raw(self, query, parameters=()):
        path = self.root/self.refusal()['raw_state_path'];path.chmod(0o600)
        with closing(sqlite3.connect(path)) as db:
            db.execute(query,parameters);db.commit()

    def test_WARMING_reason_differs_from_independently_verified_final_OFF_reason(self):
        verified = self.verify()
        self.assertEqual(verified['native_refusals_rechecked'],3)
        self.assertTrue(verified['native_final_OFF_rechecked'])
        self.assertEqual(self.row['outcome'],'FULL_PROFILE_SAFETY_PASS' if self.full_profile else OVERLOAD)
        self.assertEqual(self.row['diagnostic_outcome'],'PASS' if self.full_profile else 'FAILED_DIAGNOSTIC')
        self.assertFalse(self.row['capacity_credit'])
        for refusal in self.row['native_restart']['stale_refusals']:
            self.assertEqual(refusal['phase'],'WARMING')
            self.assertEqual(refusal['reason'],self.reason)
            with closing(self.native.plane.EvidenceReader(self.root/'d/db')) as reader:
                final = self.native.health.evidence_health(reader,refusal['scope'],self.row['native_restart']['after']['wall'])
            self.assertFalse(final['usable'])
            self.assertEqual(final['reason'],'evidence_service_unavailable')
            self.assertNotEqual(final['reason'],refusal['reason'])
        self.assertNotIn('meme_machine.solana_evidence_service',sys.modules)

    def test_exact_native_observation_times_are_preserved_per_scope(self):
        refusals = self.row['native_restart']['stale_refusals']
        self.assertEqual([r['observed_at'] for r in refusals],[WALL+.125,WALL+.375,WALL+.625])
        for refusal in refusals:
            self.assertEqual(refusal['observation']['observed_at'],refusal['observed_at'])
            self.assertNotEqual(refusal['observed_at'],self.row['native_restart']['after']['wall'])
            self.assertEqual(refusal['generation'],'unit-after')
        self.verify()

    def test_every_refusal_is_cryptographically_bound_to_receipt_and_pinned_raw_DB(self):
        for refusal in self.row['native_restart']['stale_refusals']:
            self.assertEqual(file_sha(self.root/refusal['raw_state_path']),refusal['raw_state_sha256'])
            self.assertEqual(file_sha(self.root/refusal['receipt_path']),refusal['receipt_sha256'])
            recorded = read(self.root/refusal['receipt_path'])
            self.assertEqual(recorded,{k:v for k,v in refusal.items() if k not in ('receipt_path','receipt_sha256')})
            self.assertFalse((self.root/refusal['raw_state_path']).stat().st_mode & 0o222)
        self.assertEqual(len({r['raw_state_sha256'] for r in self.row['native_restart']['stale_refusals']}),1)

    def test_missing_exact_observation_time_is_rejected(self):
        self.refusal().pop('observed_at');rewrite_refusal(self.root,self.refusal())
        with self.assertRaisesRegex(ValueError,'observation_time_missing'):self.verify()

    def test_changed_observation_time_without_receipt_rebinding_is_rejected(self):
        self.refusal()['observed_at'] += .25
        with self.assertRaisesRegex(ValueError,'stale_authority_refusal_changed'):self.verify()

    def test_changed_time_with_coherent_receipt_that_changes_native_result_is_rejected(self):
        refusal = self.refusal();refusal['observed_at'] += 20
        refusal['observation']['observed_at'] = refusal['observed_at']
        rewrite_refusal(self.root,refusal)
        with closing(self.native.plane.EvidenceReader(self.root/refusal['raw_state_path'])) as reader:
            changed = self.native.health.evidence_health(reader,refusal['scope'],refusal['observed_at'])
        self.assertEqual(changed['reason'],'evidence_heartbeat_stale')
        with self.assertRaisesRegex(ValueError,'stale_authority_refusal_changed'):self.verify()

    def test_missing_exact_refusal_generation_is_rejected(self):
        self.refusal().pop('generation');rewrite_refusal(self.root,self.refusal())
        with self.assertRaisesRegex(ValueError,'refusal_time_generation_changed'):self.verify()

    def test_changed_claimed_refusal_generation_is_rejected(self):
        self.refusal()['generation'] = 'forged';rewrite_refusal(self.root,self.refusal())
        with self.assertRaisesRegex(ValueError,'refusal_time_generation_changed'):self.verify()

    def test_changed_raw_generation_and_rebound_receipts_are_rejected(self):
        health = raw_state(self.root/self.refusal()['raw_state_path'],self.native)['health']['storage_maintenance']
        health['maintenance_arbiter']['generation'] = 'forged'
        self.change_raw('UPDATE service_health SET value=? WHERE key=?',(json.dumps(health),'storage_maintenance'))
        for refusal in self.row['native_restart']['stale_refusals']:refusal['generation'] = 'forged'
        rebind_raw(self.root,self.row)
        with self.assertRaisesRegex(ValueError,'refusal_time_generation_changed'):self.verify()

    def test_changed_refusal_reason_and_coherent_receipt_are_rejected(self):
        refusal = self.refusal()
        refusal['reason'] = 'evidence_finalized_stale' if self.reason == 'evidence_discontinuous' else 'evidence_discontinuous'
        refusal['observation']['reason'] = refusal['reason'];rewrite_refusal(self.root,refusal)
        with self.assertRaisesRegex(ValueError,'stale_authority_refusal_changed'):self.verify()

    def test_arbitrary_nonempty_refusal_reason_is_rejected(self):
        refusal = self.refusal();refusal['reason'] = refusal['observation']['reason'] = 'nonempty-forgery'
        rewrite_refusal(self.root,refusal)
        with self.assertRaisesRegex(ValueError,'stale_authority_refusal_changed'):self.verify()

    def test_changed_refusal_time_raw_state_is_rejected_by_snapshot_hash(self):
        self.change_raw('UPDATE service_health SET value=? WHERE key=?',(json.dumps(WALL-40),'heartbeat'))
        with self.assertRaisesRegex(ValueError,'refusal_time_state_changed'):self.verify()

    def test_changed_raw_health_with_coherent_hashes_is_rejected_by_native_recomputation(self):
        self.change_raw('UPDATE service_health SET value=? WHERE key=?',(json.dumps(WALL-40),'heartbeat'))
        rebind_raw(self.root,self.row)
        with self.assertRaisesRegex(ValueError,'stale_authority_refusal_changed'):self.verify()

    def test_OFF_snapshot_cannot_replace_refusal_time_WARMING_snapshot(self):
        self.change_raw('UPDATE service_health SET value=? WHERE key=?',(json.dumps('OFF'),'phase'))
        for refusal in self.row['native_restart']['stale_refusals']:
            refusal['phase'] = 'OFF'
            refusal['reason'] = refusal['observation']['reason'] = 'evidence_service_unavailable'
        rebind_raw(self.root,self.row)
        with self.assertRaisesRegex(ValueError,'refusal_time_phase_changed'):self.verify()

    def test_final_DB_path_cannot_be_substituted_for_refusal_snapshot(self):
        refusal = self.refusal();path = self.root/'d/db'
        refusal.update(raw_state_path='d/db',raw_state_sha256=file_sha(path),raw_state_bytes=path.stat().st_size)
        rewrite_refusal(self.root,refusal)
        with self.assertRaisesRegex(ValueError,'refusal_time_state_changed'):self.verify()

    def test_missing_raw_snapshot_or_cryptographic_binding_is_rejected(self):
        refusal = self.refusal();refusal.pop('raw_state_sha256');rewrite_refusal(self.root,refusal)
        with self.assertRaisesRegex(ValueError,'refusal_time_state_changed'):self.verify()
        (self.root/refusal['raw_state_path']).unlink()
        with self.assertRaisesRegex(ValueError,'refusal_time_state_changed'):self.verify()

    def test_changed_receipt_bytes_are_rejected(self):
        path = self.root/self.refusal()['receipt_path'];path.write_bytes(path.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError,'stale_authority_receipt_changed'):self.verify()

    def test_duplicate_refusal_scope_cannot_replace_required_scope(self):
        self.row['native_restart']['stale_refusals'].append(deepcopy(self.refusal()))
        with self.assertRaisesRegex(ValueError,'stale_authority_scopes_changed'):self.verify()

    def test_final_OFF_is_independently_required_even_with_coherent_endpoint_claims(self):
        path = self.root/'d/db'
        with closing(sqlite3.connect(path)) as db:
            db.execute('UPDATE service_health SET value=? WHERE key=?',(json.dumps('WARMING'),'phase'));db.commit()
        self.row['native_restart']['after'] = dict(raw_state(path,self.native),wall=WALL+2)
        with self.assertRaisesRegex(ValueError,'final_native_teardown_missing'):self.verify()

    def test_forged_final_OFF_claim_cannot_hide_raw_WARMING_state(self):
        with closing(sqlite3.connect(self.root/'d/db')) as db:
            db.execute('UPDATE service_health SET value=? WHERE key=?',(json.dumps('WARMING'),'phase'));db.commit()
        with self.assertRaisesRegex(ValueError,'native_refusal_health_changed'):self.verify()

    def test_forged_final_generation_is_rejected_even_with_coherent_endpoint_claims(self):
        health = self.row['native_restart']['after']['health']['storage_maintenance']
        health['maintenance_arbiter']['generation'] = 'forged'
        with closing(sqlite3.connect(self.root/'d/db')) as db:
            db.execute('UPDATE service_health SET value=? WHERE key=?',(json.dumps(health),'storage_maintenance'));db.commit()
        with self.assertRaisesRegex(ValueError,'generation_changed'):self.verify()

    def test_final_protected_work_gaps_and_floors_cannot_change_with_coherent_raw_claims(self):
        mutations = [('protected',"UPDATE interests SET b='forged'"),
            ('committed_counter',"UPDATE counters SET value=value+1 WHERE key='archived_records'"),
            ('record',"UPDATE records SET hash='forged'"),('progress','UPDATE maintenance_progress SET work=work+1'),
            ('episode','UPDATE maintenance_episodes SET started=started+1'),
            ('floor','UPDATE meta SET value=value+1'),('gap',"DELETE FROM gaps WHERE reason='service_restart'")]
        for name,query in mutations:
            with self.subTest(final_state=name):
                root = self.root/name
                row = make_restart(root,self.native,reason=self.reason,full_profile=self.full_profile)
                with closing(sqlite3.connect(root/'d/db')) as db:db.execute(query);db.commit()
                row['native_restart']['after'] = dict(raw_state(root/'d/db',self.native),wall=WALL+2)
                with self.assertRaisesRegex(ValueError,'native_continuity_invalid'):verify_restart_raw(root,row)

    def test_C_trial_outcome_uses_real_refusal_and_final_raw_verifier(self):
        folder = self.root/'trial';folder.mkdir()
        members = []
        expected = COHORT if self.full_profile else COHORT[:1]
        for index,(name,frames) in enumerate(expected,1):
            member = folder/f'm{index}'
            row = make_restart(member,self.native,reason=self.reason,full_profile=self.full_profile)
            source = dict(clock_samples=[])
            row.update(member=name,frames=frames,source_receipt=source)
            if name == 'recovery-1':row['observer_assessment'] = {'passed':self.full_profile}
            row.update(stress_member_result(row))
            persist(member/'result.json',dict(failure=row['failure'],failure_frames=row['failure_frames']))
            persist(member/'MEMBER_RESULT.json',row);persist(member/'SOURCE_RECEIPT.json',source)
            members.append(dict(member=name,frames=frames,valid=True,exit_code=0,
                                member_result_sha256=file_sha(member/'MEMBER_RESULT.json')))
        outcome = 'FULL_PROFILE_SAFETY_PASS' if self.full_profile else OVERLOAD
        cohort = dict(kind='C',sequence=1,trial_id='UNIT ONLY',mode='stress',declaration_sha256='unit',valid=True,
            members=members,outcome=outcome,complete_profile=self.full_profile,no_further_members=not self.full_profile,
            capacity_credit=False,diagnostic_outcome='PASS' if self.full_profile else 'FAILED_DIAGNOSTIC')
        if not self.full_profile:cohort['terminal_member'] = members[-1]['member']
        clocks = interval();persist(folder/'COHORT_RESULT.json',cohort)
        persist(folder/'TRIAL_RESULT.json',dict(cohort,start_perf_ns=clocks['start_perf_ns'],end_perf_ns=clocks['end_perf_ns'],
                elapsed_ns=clocks['end_perf_ns']-clocks['start_perf_ns'],execution_interval=clocks))
        persist(folder/'MEASURED_PERSISTENCE_COMPLETE.json',dict(cohort=cohort,all_native_helpers_terminated=True,
                resource_errors=[],no_subtraction=True,no_double_counting=True))
        persist(folder/'PROCESS_TERMINATION.json',dict(trial_process_terminated=True,all_native_helpers_terminated=True,
                real_monotonic_ns=clocks['helpers_terminated_real_monotonic_ns']))
        seal(folder)
        d = dict(class_id='C',environment_sha256='unit-env',production_workload_sha256='unit-workload',
                 trials=[dict(sequence=1,trial_id='UNIT ONLY',mode='stress')])
        life = dict(pid=21,start_ticks=5,role='member',start_ns=11*10**9,end_ns=18*10**9)
        # Unrelated input/resource/native diagnostic boundaries are mocked.
        # The lifecycle snapshots, native predicate and restart verifier are real.
        with patch('verify.native_verifier_context',return_value=nullcontext()),\
             patch('verify.verify_stress_native',return_value=self.full_profile),\
             patch('verify.verify_native_db'),\
             patch('verify.verify_source',return_value=dict(first_release_ns=12*10**9,last_release_ns=13*10**9,frames=0)),\
             patch('verify.verify_origins',return_value={'lifetimes':[life],'constraints_sha256':'UNIT ONLY'}),\
             patch('verify.verify_resource_timeline',return_value={'constraints_sha256':'UNIT ONLY'}),\
             patch('verify.verify_restart_raw',wraps=verify_restart_raw) as restart:
            result = verify_trial(folder,d,declaration_sha256='unit',allocation={})
        self.assertEqual(restart.call_count,len(expected))
        self.assertEqual(result['outcome'],outcome)
        self.assertEqual(result['complete_cohort'],self.full_profile)
        self.assertEqual(result['safety_only'],not self.full_profile)
        self.assertEqual(result['diagnostic_outcome'],'PASS' if self.full_profile else 'FAILED_DIAGNOSTIC')
        self.assertFalse(result['capacity_credit']);self.assertFalse(result['observer_credit'])


class FullProfileDiscontinuousTests(LifecycleAssertions,unittest.TestCase):
    reason = 'evidence_discontinuous'
    full_profile = True


class FullProfileFinalizedStaleTests(LifecycleAssertions,unittest.TestCase):
    reason = 'evidence_finalized_stale'
    full_profile = True


class TerminalOverloadDiscontinuousTests(LifecycleAssertions,unittest.TestCase):
    reason = 'evidence_discontinuous'
    full_profile = False


class TerminalOverloadFinalizedStaleTests(LifecycleAssertions,unittest.TestCase):
    reason = 'evidence_finalized_stale'
    full_profile = False


class PinnedCaptureTests(unittest.TestCase):
    def test_backup_preserves_predicate_read_transaction_when_live_state_changes_to_OFF(self):
        with tempfile.TemporaryDirectory() as folder,native_reads() as native:
            root = Path(folder);row = make_restart(root/'initial',native)
            path = root/'live-db'
            shutil.copyfile(root/'initial'/row['native_restart']['stale_refusals'][0]['raw_state_path'],path)
            path.chmod(0o600)
            with closing(sqlite3.connect(path)) as writer:
                writer.execute('PRAGMA journal_mode=WAL')
                calls = []
                def clock():
                    if not calls:
                        writer.execute('UPDATE service_health SET value=? WHERE key=?',(json.dumps('OFF'),'phase'))
                        writer.commit()
                    calls.append(WALL+.125+len(calls)*.25)
                    return calls[-1]
                plane = native.runtime.RuntimeEvidence(path,owner='UNIT ONLY',clock=clock)
                output = root/'captured';output.mkdir()
                try:refusals = capture_stale_refusals(plane,SCOPES,output,generation='unit-after')
                finally:plane.close()
            self.assertEqual(raw_state(path,native)['health']['phase'],'OFF')
            for refusal in refusals:
                self.assertEqual(refusal['phase'],'WARMING')
                self.assertEqual(refusal['reason'],'evidence_discontinuous')
                with closing(native.plane.EvidenceReader(output/refusal['raw_state_path'])) as reader:
                    self.assertEqual(native.health.evidence_health(reader,refusal['scope'],refusal['observed_at']),
                                     refusal['observation'])
            self.assertEqual([r['observed_at'] for r in refusals],calls)

    def test_capture_refuses_wrong_generation_before_preservation(self):
        with tempfile.TemporaryDirectory() as folder,native_reads() as native:
            root = Path(folder);row = make_restart(root/'initial',native)
            path = root/'initial'/row['native_restart']['stale_refusals'][0]['raw_state_path']
            plane = native.runtime.RuntimeEvidence(path,owner='UNIT ONLY',clock=lambda:WALL+.125)
            output = root/'captured';output.mkdir()
            try:
                with self.assertRaisesRegex(ValueError,'lifecycle_or_generation'):
                    capture_stale_refusals(plane,SCOPES,output,generation='forged')
                self.assertFalse(plane.reader.db.in_transaction)
            finally:plane.close()
            self.assertFalse((output/'refusal-native-state').exists())
