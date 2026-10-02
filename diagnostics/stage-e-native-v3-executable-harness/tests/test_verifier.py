"""Pure native-evidence predicates and exact arithmetic; no source/service run."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'harness'))
from core import S, workload
from verify import (production_member_errors, observer_arithmetic, observer_sample_errors,
                    native_overload_errors, stress_member_result, verify_observer, gate_status)


def member():
    return dict(candidate_sha=S,kind='A',member='combined-1',shape=None,frames=2223,cadence_us=270000,
        source_seconds=600.21,errors=[],provider_attempts=[],integrity=['ok'],
        artificial_contention=workload('A')['artificial_contention'],
        setup=dict(counters={},seed_frames=0,setup_elapsed_ns=0,historical_availability_unchanged=True),
        counters=dict(stream_accepted_messages=2223,archived_records=3,compacted_records=2),
        ipc={'stream.received_messages':2224,'stream.commit_messages':2224,
             'stream.outstanding_frames_peak':1,'stream.dispatch_bytes_peak':800000,
             'stream.commit_batch_messages_peak':1,'stream.commit_batch_bytes_peak':800000,
             'stream.decode_process_messages':2223},
        final=dict(health={'owner_scheduler':{'queue_peak':3}}),
        safety_samples=[dict(source_lag=1,hot_age=181,retained_age=181,hot_bytes=100000,gaps=[])],
        source_receipt=dict(source_frames_released=2223,tape={'valid':True}),
        candidate_checks=[1,2],common_control=dict(urgent_acks=10,urgent_errors=[]),archives=[{'records':3}])


def pairs(increment=9):
    return [dict(pair_id='p'+str(i),baseline_ns=1000,observed_ns=1000+increment,
                 valid=True,same_workload_hash='production-equivalent-full-cohort-v3') for i in range(3)]


class VerifierTests(unittest.TestCase):
    def test_native_single_message_peaks_allowed_in_A(self):
        self.assertEqual(production_member_errors(member()), [])

    def test_strict_safety_equalities_all_fail(self):
        for key,value in [('source_lag',45),('hot_age',240),('retained_age',240),('hot_bytes',2*1024**3)]:
            row=member();row['safety_samples'][0][key]=value
            self.assertIn('strict_'+key,production_member_errors(row))

    def test_safety_infinities_nan_and_bool_fail(self):
        for value in (float('nan'),float('inf'),True,-1):
            row=member();row['safety_samples'][0]['source_lag']=value
            self.assertIn('strict_source_lag',production_member_errors(row))

    def test_synthetic_delays_rejected_in_A_and_B(self):
        for kind in ('A','B'):
            row=member();row['kind']=kind;row['artificial_contention']=workload('C')['artificial_contention']
            self.assertIn('synthetic_contention_in_production',production_member_errors(row))

    def test_lost_native_completion_fails(self):
        row=member();row['ipc']['stream.commit_messages']=2223
        self.assertIn('admitted_drain',production_member_errors(row))

    def test_missing_raw_safety_fails(self):
        row=member();row['safety_samples']=[]
        self.assertTrue(production_member_errors(row))

    def test_provider_attempt_fails(self):
        row=member();row['provider_attempts']=['DNS']
        self.assertTrue(production_member_errors(row))

    def test_exact_safety_maxima_are_allowed(self):
        row=member();row['ipc'].update({'stream.outstanding_frames_peak':64,
            'stream.dispatch_bytes_peak':96*1024**2,'stream.commit_batch_messages_peak':8,
            'stream.commit_batch_bytes_peak':16*1024**2})
        self.assertEqual(production_member_errors(row),[])

    def test_summed_strict_overhead_under_one_percent(self):
        self.assertEqual(observer_arithmetic(pairs())['numerator_ns'],27)

    def test_exact_one_percent_fails(self):
        with self.assertRaises(ValueError):observer_arithmetic(pairs(10))

    def test_each_pair_need_not_be_under_one_percent(self):
        p=pairs(0);p[0]['observed_ns']=1029
        self.assertEqual(observer_arithmetic(p)['numerator_ns'],29)

    def test_unweighted_pair_average_cannot_substitute_for_sum(self):
        p=pairs(0);p[0].update(baseline_ns=100000,observed_ns=101500)
        with self.assertRaises(ValueError):observer_arithmetic(p)

    def test_negative_increment_cannot_offset_positive_cost(self):
        p=pairs(100);p[1]['observed_ns']=0
        with self.assertRaises(ValueError):observer_arithmetic(p)

    def test_incomplete_invalid_duplicate_zero_and_bool_pairs_fail(self):
        mutations=[lambda p:p.pop(),lambda p:p[0].update(valid=False),
                   lambda p:p[1].update(pair_id='p0'),lambda p:p[0].update(baseline_ns=0),
                   lambda p:p[0].update(baseline_ns=True)]
        for mutation in mutations:
            p=pairs();mutation(p)
            with self.assertRaises(ValueError):observer_arithmetic(p)

    def test_wrapper_stop_is_never_native_overload_proof(self):
        row=dict(native_restart={'native_failure':'AssertionError:source_clock_fell_behind'})
        self.assertIn('native_threshold_triggered_refusal_missing',native_overload_errors(row))

    def test_C_performance_failure_stays_failed_diagnostic(self):
        row={'workload_valid':False,'observation_valid':False,'provider_attempts':[],
             'integrity':['ok'],'lag_peak':1,'oldest_hot_age_peak':180,'oldest_retained_age_peak':180,
             'hot_peak':100000,'ipc':{},'member':'combined-1'}
        result=stress_member_result(row)
        self.assertEqual(result['diagnostic_outcome'],'FAILED_DIAGNOSTIC')
        self.assertFalse(result['mandatory_native_safety_pass'])
        self.assertFalse(result['capacity_credit'])

    def test_all_47_required_gates_remain_NOT_RUN(self):
        gates=gate_status();self.assertEqual(len(gates),47)
        self.assertEqual(set(gates.values()),{'NOT_RUN'})

    def test_A_pass_required_for_B(self):
        with self.assertRaises(ValueError):verify_observer([],{},dict(native_verified=False))

    def test_missing_observer_landmarks_fail(self):
        row=dict(member='combined-1',observer_errors=[],qualification_snapshots=[],observer_samples=[])
        self.assertIn('fixed_qualification_landmarks',observer_sample_errors(row))
