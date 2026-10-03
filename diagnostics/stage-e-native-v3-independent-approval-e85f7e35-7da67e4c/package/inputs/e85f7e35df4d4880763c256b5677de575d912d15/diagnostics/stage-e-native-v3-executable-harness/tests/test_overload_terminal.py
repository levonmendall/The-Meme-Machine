"""Deterministic terminal protocol tests; every native/process boundary is mocked."""
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'harness'))
from core import file_sha, read
from ledger import Ledger, fresh_campaign
from preserve import persist, seal
from run import _finalize_attempt
from trial import member_acceptance
import trial
from verify import OVERLOAD, stress_member_result, verify_trial, verify_source
from regression_fixtures import safe_overload_row, opaque_prefix, interval


class OverloadProtocolTests(unittest.TestCase):
    def test_safe_native_overload_is_accepted_only_as_terminal_C(self):
        row = safe_overload_row()
        self.assertEqual(member_acceptance(0,row,'C'),(True,True))
        self.assertEqual(row['diagnostic_outcome'],'FAILED_DIAGNOSTIC')
        self.assertFalse(row['capacity_credit'])
        self.assertEqual(member_acceptance(1,row,'C'),(False,False))
        self.assertEqual(member_acceptance(0,row,'A'),(False,False))

    def test_full_performance_pass_keeps_complete_profile_protocol(self):
        row = safe_overload_row();row.update(workload_valid=True,observation_valid=True)
        row.update(stress_member_result(row))
        self.assertEqual(member_acceptance(0,row,'C'),(True,False))

    def test_every_native_proof_failure_refuses_terminal_credit(self):
        mutations = [lambda r:r.update(lag_peak=45),lambda r:r.update(oldest_hot_age_peak=240),
            lambda r:r.update(oldest_retained_age_peak=240),lambda r:r.update(hot_peak=2*1024**3),
            lambda r:r['native_restart'].update(native_failure='AssertionError:wrapper_stop'),
            lambda r:r['native_restart'].update(native_failure_frames=[]),
            lambda r:r['native_restart'].update(new_generation=None),
            lambda r:r['native_restart'].update(external_stop_is_native_proof=True),
            lambda r:r['native_restart'].update(source_frames_released_after_restart=1),
            lambda r:r['native_restart']['after'].update(records_digest='changed'),
            lambda r:r['native_restart']['after']['protected'].update(stream_receipts=[['changed']]),
            lambda r:r['native_restart']['after']['counters'].update(archived_records=2),
            lambda r:r['native_restart'].update(stale_refusals=[]),
            lambda r:r['native_restart'].update(preserved_original_inventory_sha256=None),
            lambda r:r['ipc'].update({'stream.commit_messages':1}),
            lambda r:r['ipc'].pop('stream.received_messages'),lambda r:r.update(integrity=['corrupt']),
            lambda r:r.update(provider_attempts=['DNS'])]
        for mutation in mutations:
            with self.subTest(mutation=mutations.index(mutation)):
                row = safe_overload_row();mutation(row);row.update(stress_member_result(row))
                self.assertEqual(member_acceptance(0,row,'C'),(False,False))

    def test_self_asserted_classification_cannot_hide_missing_proof(self):
        row = safe_overload_row();row['native_restart']['native_failure_frames'] = []
        self.assertEqual(member_acceptance(0,row,'C'),(False,False))

    def test_trial_stops_before_next_member_without_reclassifying_diagnostic(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            params = dict(kind='C',sequence=1,mode='stress',output=folder,trial_id='UNIT ONLY',
                declaration_sha256='unit',candidate_checkout=folder,cache_path=str(output/'unused-cache'),
                environment={'python_executable':sys.executable})
            def mocked_spawn(command,**kwargs):
                path = Path(kwargs['env']['MM_STAGE_E_V3_PARAMS'])
                row = safe_overload_row()
                persist(path.parent/'MEMBER_RESULT.json',row)
                child = Mock();child.wait.return_value = 0
                return child
            with patch.object(trial.bound,'PARAMS',params),patch.object(trial.bound,'resource_admission'),\
                 patch('trial.subprocess.Popen',side_effect=mocked_spawn) as spawn:
                trial.main()
            self.assertEqual(spawn.call_count,1)
            cohort = read(output/'COHORT_RESULT.json')
            self.assertEqual(cohort['outcome'],OVERLOAD)
            self.assertEqual(cohort['diagnostic_outcome'],'FAILED_DIAGNOSTIC')
            self.assertEqual(len(cohort['members']),1)
            self.assertFalse((output/'m2').exists())

    def test_verified_overload_consumes_terminal_ledger_and_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory);published = root/'published';published.mkdir()
            ledger = Ledger.create(root/'registry','C','unit',fresh_campaign('C'))
            ledger.append('STARTED',1,{})
            folder = ledger.path.parent/'t1';folder.mkdir();persist(folder/'FAILED_DIAGNOSTIC.json',{'failed':True})
            d = dict(campaign=ledger.path.parent.name,paths={'durable_publication_root':str(published)})
            proof = dict(class_id='C',native_verified=True,passed=True,safety_only=True,capacity_credit=False,
                         diagnostic_outcome='FAILED_DIAGNOSTIC',outcome=OVERLOAD)
            with patch('run.verify_trial',return_value=proof):
                result, error, terminal = _finalize_attempt(folder,d,1,valid=True,reason=None,
                                                            declaration_sha256='unit',allocation={})
            self.assertEqual(result,proof);self.assertIsNone(error);self.assertTrue(terminal)
            self.assertEqual(ledger.events()[-1]['event'],'DIAGNOSTIC_OVERLOAD')
            self.assertTrue((published/(d['campaign']+'-t1')/'FAILED_DIAGNOSTIC.json').exists())
            with self.assertRaises(ValueError):ledger.append('STARTED',2,{})

    def test_overload_ledger_event_is_forbidden_for_A_B_and_missing_verification(self):
        with tempfile.TemporaryDirectory() as folder:
            for kind in ('A','B','C'):
                ledger = Ledger.create(folder,kind,'unit',fresh_campaign(kind));ledger.append('STARTED',1,{})
                with self.assertRaisesRegex(ValueError,'verified_C_safety_only'):
                    ledger.append('DIAGNOSTIC_OVERLOAD',1,{'verification':{}})


class IncompleteInputTests(unittest.TestCase):
    def test_partial_C_prefix_is_verified_from_opaque_bytes_without_unread_credit(self):
        with tempfile.TemporaryDirectory() as folder:
            receipt,d = opaque_prefix(folder)
            row = dict(frames=2,kind='C',member='combined-1',declaration_sha256='unit')
            verified = verify_source(receipt,row,d,allow_incomplete=True)
            self.assertEqual(verified['frames'],1)
            self.assertFalse(receipt['tape']['valid'])
            with self.assertRaises(ValueError):verify_source(receipt,row,d)
            row['kind'] = 'A'
            with self.assertRaises(ValueError):verify_source(receipt,row,d,allow_incomplete=True)

    def test_changed_partial_prefix_or_release_bytes_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            receipt,d = opaque_prefix(folder)
            row = dict(frames=2,kind='C',member='combined-1',declaration_sha256='unit')
            for target,key in [('tape','encoded_prefix_sha256'),('release','sha256')]:
                bad = deepcopy(receipt)
                (bad['tape'] if target == 'tape' else bad['raw_release_hashes'][0])[key] = 'changed'
                with self.assertRaises(ValueError):verify_source(bad,row,d,allow_incomplete=True)


class RawTerminalVerifierTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)/'trial';self.folder.mkdir()
        member = self.folder/'m1';member.mkdir()
        source,self.d = opaque_prefix(member,planned_frames=2223)
        self.d.update(class_id='C',environment_sha256='unit-env',production_workload_sha256='unit-workload',
                      trials=[dict(sequence=1,trial_id='unit-trial',mode='stress')])
        row = safe_overload_row();row['source_receipt'] = source
        persist(member/'result.json',dict(failure=row['failure'],failure_frames=row['failure_frames']))
        persist(member/'MEMBER_RESULT.json',row);persist(member/'SOURCE_RECEIPT.json',source)
        cohort = dict(kind='C',sequence=1,trial_id='unit-trial',mode='stress',declaration_sha256='unit',valid=True,
            members=[dict(member='combined-1',frames=2223,exit_code=0,valid=True,
                          member_result_sha256=file_sha(member/'MEMBER_RESULT.json'))],
            outcome=OVERLOAD,complete_profile=False,no_further_members=True,capacity_credit=False,
            diagnostic_outcome='FAILED_DIAGNOSTIC',terminal_member='combined-1')
        persist(self.folder/'COHORT_RESULT.json',cohort)
        clock = interval()
        persist(self.folder/'TRIAL_RESULT.json',dict(cohort,start_perf_ns=clock['start_perf_ns'],end_perf_ns=clock['end_perf_ns'],
                elapsed_ns=clock['end_perf_ns']-clock['start_perf_ns'],execution_interval=clock))
        persist(self.folder/'MEASURED_PERSISTENCE_COMPLETE.json',dict(cohort=cohort,all_native_helpers_terminated=True,
                resource_errors=[],no_subtraction=True,no_double_counting=True))
        persist(self.folder/'PROCESS_TERMINATION.json',dict(trial_process_terminated=True,all_native_helpers_terminated=True,
                real_monotonic_ns=clock['helpers_terminated_real_monotonic_ns']))
        seal(self.folder)

    def verify(self, **overrides):
        life = dict(pid=21,start_ticks=5,role='member',start_ns=11*10**9,end_ns=18*10**9)
        with patch('verify.native_verifier_context',return_value=nullcontext()),\
             patch('verify.verify_stress_native',return_value=False),\
             patch('verify.verify_restart_raw',**overrides) as restart,\
             patch('verify.verify_native_db'),\
             patch('verify.verify_origins',return_value={'lifetimes':[life],'constraints_sha256':'unit-constraints'}),\
             patch('verify.verify_resource_timeline',return_value={'unit_only':True,'constraints_sha256':'unit-constraints'}) as resources:
            result = verify_trial(self.folder,self.d,declaration_sha256='unit',allocation={})
            self.assertTrue(restart.called)
            self.assertEqual(resources.call_args.kwargs['execution_interval'],interval())
            self.assertEqual(resources.call_args.kwargs['source_intervals'][0]['frames'],1)
            return result

    def test_partial_raw_trial_gets_only_terminal_C_safety_credit(self):
        result = self.verify()
        self.assertEqual(result['outcome'],OVERLOAD);self.assertTrue(result['safety_only'])
        self.assertFalse(result['capacity_credit']);self.assertFalse(result['complete_cohort'])
        self.assertEqual(result['source_frames'],[1]);self.assertEqual(result['diagnostic_outcome'],'FAILED_DIAGNOSTIC')

    def test_missing_raw_restart_proof_rejects_self_asserted_safety(self):
        with self.assertRaisesRegex(ValueError,'unit raw restart missing'):
            self.verify(side_effect=ValueError('unit raw restart missing'))

    def test_original_failure_ancestry_cannot_be_replaced_by_member_claim(self):
        original = self.folder/'m1/result.json'
        original.write_text('{"failure":"AssertionError:wrapper","failure_frames":[]}')
        (self.folder/'RAW_INVENTORY.json').unlink();seal(self.folder)
        with self.assertRaisesRegex(ValueError,'original_native_failure_ancestry_changed'):self.verify()

    def test_member_after_terminal_is_rejected_even_if_inventoried(self):
        (self.folder/'m2').mkdir()
        # Refresh only the unit fixture inventory; immutable production receipts
        # cannot be rewritten. The verifier still rejects a correctly sealed extra.
        (self.folder/'RAW_INVENTORY.json').unlink();seal(self.folder)
        with self.assertRaisesRegex(ValueError,'members_after_terminal'):
            verify_trial(self.folder,self.d,declaration_sha256='unit',allocation={})
