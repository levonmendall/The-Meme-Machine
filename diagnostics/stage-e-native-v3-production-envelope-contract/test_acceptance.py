"""Acceptance-rule negative tests with synthetic dictionaries, never runtime data."""
from copy import deepcopy
import unittest
from resource_rules import (S, T, HEADROOM_BYTES, canonical_sha256,
                            capacity_claim_errors, observer_claim_errors)
from test_resource_rules import synthetic_fixture


class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.claim, self.bounds = synthetic_fixture()
        self.workload_hash = canonical_sha256({'fixture': 'SYNTHETIC_NO_CERTIFICATION'})
        self.native = {'candidate_sha': S, 'candidate_tree': T, 'native_verified': True, 'passed': True,
            'workload_hash': self.workload_hash, 'source_frames': [2223,2223,2223,4445],
            'provider_attempts': [], 'environment_hash': self.claim['environment_manifest_sha256'],
            'source_lag_peak': 2, 'hot_age_peak': 181, 'retained_age_peak': 182,
            'hot_db_wal_peak': 1024**3, 'integrity': 'ok', 'unresolved_runtime_gaps': 0,
            'synthetic_floor_seconds': {'owner':0,'archive':0,'commit':0}}
        self.measurement = {'candidate_sha': S, 'candidate_tree': T,
            'execution_key':'stage-e-native-v3-observer-synthetic-fixture',
            'modes':['baseline','observed','observed','baseline','baseline','observed'],
            'retries':0, 'replacements':0, 'raw_pairs':[
                {'pair_id':str(i), 'baseline_ns':10000, 'observed_ns':10099, 'valid':True,
                 'both_arms_capacity_valid':True, 'workload_hash':self.workload_hash,
                 'environment_hash':self.claim['environment_manifest_sha256']} for i in range(3)],
            'numerator_ns':297, 'denominator_ns':30000, 'ratio':297/30000}

    def capacity(self):
        return capacity_claim_errors(self.claim,self.bounds,self.native,self.workload_hash)

    def observer(self):
        return observer_claim_errors(self.measurement,self.capacity(),self.workload_hash,
                                     self.claim['environment_manifest_sha256'])

    def test_structurally_eligible_fixture_grants_no_runtime_certification(self):
        self.assertEqual(self.capacity(), ())
        self.assertEqual(self.observer(), ())

    def test_all_more_than_two_cpu_allocations_reject_even_with_passing_native_claim(self):
        for cpus in (3,4,8,16,64):
            with self.subTest(cpus=cpus):
                self.claim['allocated_vcpu']=cpus
                self.assertTrue(self.capacity())
                self.assertEqual(self.observer(),('baseline production capacity blocks observer measurement',))

    def test_larger_visible_executor_cannot_be_hidden_by_two_cpu_allocation_label(self):
        self.claim['executor_visible_vcpu']=4
        self.assertTrue(self.capacity())

    def test_unchanged_strict_safety_equality_and_exceedance_fail(self):
        for field,limit in (('source_lag_peak',45),('hot_age_peak',240),
                            ('retained_age_peak',240),('hot_db_wal_peak',2*1024**3)):
            with self.subTest(field=field):
                prior=self.native[field]
                self.native[field]=limit
                self.assertTrue(self.capacity())
                self.assertTrue(self.observer())
                self.native[field]=limit+1
                self.assertTrue(self.capacity())
                self.native[field]=prior

    def test_overhead_just_below_one_percent_passes_arithmetic(self):
        self.assertEqual(self.observer(), ())

    def test_overhead_equality_and_above_fail(self):
        for observed in (10100,10101):
            with self.subTest(observed=observed):
                for pair in self.measurement['raw_pairs']:pair['observed_ns']=observed
                self.measurement['numerator_ns']=(observed-10000)*3
                self.measurement['ratio']=self.measurement['numerator_ns']/30000
                self.assertIn('observer overhead must be strictly less than one percent',self.observer())

    def test_observed_faster_than_baseline_remains_v2_invalid(self):
        self.measurement['raw_pairs'][0]['observed_ns']=9999
        self.assertTrue(self.observer())

    def test_incomplete_or_invalid_pairs_never_create_overhead_credit(self):
        self.measurement['raw_pairs'].pop()
        self.assertTrue(self.observer())
        self.setUp()
        self.measurement['raw_pairs'][0]['valid']=False
        self.assertTrue(self.observer())

    def test_wrong_order_or_duplicate_pair_rejected(self):
        self.measurement['modes'].reverse()
        self.assertTrue(self.observer())
        self.setUp()
        self.measurement['raw_pairs'][2]['pair_id']='0'
        self.assertTrue(self.observer())

    def test_equal_workload_and_environment_require_exact_hashes(self):
        for field in ('workload_hash','environment_hash'):
            with self.subTest(field=field):
                prior=self.measurement['raw_pairs'][0][field]
                self.measurement['raw_pairs'][0][field]='changed'
                self.assertTrue(self.observer())
                self.measurement['raw_pairs'][0][field]=prior

    def test_historical_campaign_namespace_cannot_reuse_five_slots(self):
        self.measurement['execution_key']='observer-v2-20261002-exact-7a516a6a'
        self.assertTrue(self.observer())

    def test_retries_replacements_and_failed_observed_capacity_rejected(self):
        for field in ('retries','replacements'):
            with self.subTest(field=field):
                self.measurement[field]=1
                self.assertTrue(self.observer())
                self.measurement[field]=0
        self.measurement['raw_pairs'][1]['both_arms_capacity_valid']=False
        self.assertTrue(self.observer())

    def test_synthetic_normalization_cannot_be_smuggled_into_capacity(self):
        self.native['synthetic_floor_seconds']['commit']=.006
        self.assertTrue(self.capacity())

    def test_same_tree_with_different_commit_cannot_earn_capacity(self):
        self.native['candidate_sha']='0'*40
        self.assertTrue(self.capacity())

    def test_no_capacity_credit_from_incomplete_or_failed_native_evidence(self):
        self.native['source_frames']=[2223]
        self.assertTrue(self.capacity())
        self.setUp()
        self.native['native_verified']=False
        self.assertTrue(self.capacity())

    def test_headroom_cannot_be_reduced_to_make_fixture_pass(self):
        self.bounds['required_free_headroom_bytes']=5*1024**3
        self.assertTrue(self.capacity())


if __name__ == '__main__':
    unittest.main()
