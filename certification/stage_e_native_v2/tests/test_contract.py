import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from certification.stage_e_native_v2.contract import HERE,ROOT,read,sha256,validate_inputs,identities
from certification.stage_e_native_v2.firewall import classification,classified_tests
from certification.stage_e_native_v2.observer import verify


class ContractTests(unittest.TestCase):
    def test_plan_and_all_input_hashes_validate(self):
        self.assertEqual(validate_inputs(),identities())
    def test_every_predecessor_requirement_has_a_named_required_successor(self):
        rows=read(HERE/'gate-map-v2.json')['gates'];plan=read(HERE/'plan-v2.json')
        self.assertEqual({r['new_gate'] for r in rows},set(plan['required_gates']))
        for row in rows:
            self.assertTrue(row['old_input_identity']);self.assertTrue(row['old_purpose']);self.assertTrue(row['new_purpose'])
            self.assertIn(row['classification'],{'RETAINED','REPLACED_BY_EQUIVALENT','REPLACED_BY_STRONGER','UNRESOLVED'})
            self.assertNotEqual(row['classification'],'UNRESOLVED')
    def test_historical_plans_and_pinned_inputs_stay_exact(self):
        for path,digest in read(HERE/'plan-v2.json')['historical_inputs'].items():
            self.assertEqual(sha256((ROOT/path).read_bytes()),digest,path)
    def test_all_46_historical_skips_are_explicit_and_never_count_as_passes(self):
        rows=read(HERE/'historical-skips-v2.json')['skips'];self.assertEqual(len(rows),46)
        self.assertEqual(len({r['test_id'] for r in rows}),46)
        for row in rows:
            self.assertFalse(row['passing']);self.assertEqual(row['status'],'NOT_EXECUTED')
            self.assertIn(row['disposition'],{'executed in deterministic v2 qualification','executed only in prepared assembly qualification','executed only in future canonical qualification','obsolete because replaced by stronger named gate'})
    def test_firewall_denies_full_shapes_observer_and_unknown_cases(self):
        for case in ('run373-full','run379-full','run380-full','combined-1','recovery-1','observer-measurement','unknown'):
            with self.subTest(case=case),self.assertRaises(PermissionError):classification(case)
        from certification.stage_e_native_v2.material import execute_full_fixture,construct_full_fixture
        for run in ('run373','run379','run380'):
            with self.assertRaises(PermissionError):construct_full_fixture(run)
            with self.assertRaises(PermissionError):execute_full_fixture(run,'/tmp/never-created')
    def test_unknown_test_classification_blocks_before_any_execution(self):
        suite=unittest.TestSuite([ContractTests('test_historical_plans_and_pinned_inputs_stay_exact')])
        with self.assertRaises(PermissionError):classified_tests(suite,{})


class ObserverTests(unittest.TestCase):
    def fixture(self,ratio=.005):
        spec=read(HERE/'observer-contract-v2.json');identity={'candidate_sha':'a'*40,'assembly_digest':'b'*64,'plan_hash':'c'*64}
        measurement=dict(contract=spec['version'],identity=identity,workload_identity=spec['workload_identity'],
            **{k:spec[k] for k in ('baseline','metric','estimator','repetition_policy')},
            raw_pairs=[dict(pair_id=str(i),baseline_ns=10000,observed_ns=10000+int(ratio*10000),
                valid=True,same_workload_hash=spec['workload_identity']) for i in range(3)],
            numerator_ns=3*int(ratio*10000),denominator_ns=30000,ratio=ratio)
        return measurement,identity
    def test_strict_less_than_one_percent_only(self):
        row,identity=self.fixture();self.assertTrue(verify(row,identity))
        for ratio in (.01,.0101):
            row,identity=self.fixture(ratio)
            with self.subTest(ratio=ratio),self.assertRaises(ValueError):verify(row,identity)
    def test_nan_infinity_missing_components_and_malformed_raw_pairs_rejected(self):
        mutations=[('ratio',float('nan')),('ratio',float('inf')),('numerator_ns',None),('denominator_ns',None),('raw_pairs',[]),('raw_pairs','malformed')]
        for key,value in mutations:
            row,identity=self.fixture();row[key]=value
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):verify(row,identity)
    def test_wrong_candidate_assembly_plan_or_workload_rejected(self):
        for key in ('candidate_sha','assembly_digest','plan_hash'):
            row,identity=self.fixture();row['identity']=dict(identity,**{key:'foreign'})
            with self.subTest(key=key),self.assertRaises(ValueError):verify(row,identity)
        row,identity=self.fixture();row['workload_identity']='historical-workload'
        with self.assertRaises(ValueError):verify(row,identity)
    def test_missing_denominator_bad_estimator_and_invalid_pair_rejected(self):
        row,identity=self.fixture();row.pop('denominator_ns')
        with self.assertRaises(ValueError):verify(row,identity)
        row,identity=self.fixture();row['estimator']='pick_the_passing_pair'
        with self.assertRaises(ValueError):verify(row,identity)
        row,identity=self.fixture();row['raw_pairs'][0]['valid']=False
        with self.assertRaises(ValueError):verify(row,identity)


if __name__=='__main__':unittest.main()
