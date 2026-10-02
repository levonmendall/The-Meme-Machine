"""Mocked process waits and pure raw snapshots. No child is launched."""
from copy import deepcopy
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'harness'))
from core import ASSEMBLY, S, sha
from binding import infrastructure_identity
from preserve import persist
from run import _wait_trial, _terminate_trial, _wait_helpers
from verify import verify_admissions, verify_origins
from test_envelope import fixture


class ControllerContinuityTests(unittest.TestCase):
    def test_resource_refusal_prevents_further_wait(self):
        child=Mock();monitor=SimpleNamespace(errors=['ancestor quota changed'])
        with self.assertRaisesRegex(ValueError,'resource_monitor_refused_live_trial'):
            _wait_trial(child,monitor,10)
        child.wait.assert_not_called()

    def test_resource_refusal_during_wait_stops_next_boundary(self):
        child=Mock();monitor=SimpleNamespace(errors=[])
        def wait(**kwargs):
            self.assertLessEqual(kwargs['timeout'],.25)
            monitor.errors.append('cpu changed')
            raise subprocess.TimeoutExpired('MOCK ONLY',kwargs['timeout'])
        child.wait.side_effect=wait
        with self.assertRaises(ValueError):_wait_trial(child,monitor,10)
        self.assertEqual(child.wait.call_count,1)

    def test_normal_exit_and_deadline_use_real_clock(self):
        child=Mock();child.wait.return_value=0
        self.assertEqual(_wait_trial(child,SimpleNamespace(errors=[]),10),0)
        with patch('core.REAL_NS',side_effect=[100,1000000101]):
            with self.assertRaisesRegex(ValueError,'native_trial_deadline'):
                _wait_trial(child,SimpleNamespace(errors=[]),1)

    def test_exited_parent_still_terminates_group_and_joins_helpers(self):
        child=Mock();child.pid=999999;monitor=SimpleNamespace(known_pids={})
        with patch('run.os.killpg') as kill,patch('run._wait_helpers') as join:
            _terminate_trial(child,monitor)
        kill.assert_called_once();join.assert_called_once();child.wait.assert_called_once()

    def test_unobserved_reparented_group_helper_must_exit_before_cleanup(self):
        orphan = dict(pid=999998,ppid=1,process_group=999999,start_ticks=7,state='S')
        with patch('attest.process_inventory',side_effect=[[orphan],[]]) as census,patch('time.sleep') as pause:
            _wait_helpers(999999,{})
        self.assertEqual(census.call_count,2);pause.assert_called_once()


class RawAdmissionContinuityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        snapshot,self.allocation,bounds,runtime=fixture()
        snapshot['topology']=[]
        capability=Path(self.temp.name)/'unit-capability';capability.write_bytes(b'UNIT TEST ONLY')
        self.allocation['allocation_evidence']=[dict(path=str(capability),sha256=sha(capability.read_bytes()))]
        self.declaration=dict(storage_bounds=bounds,environment={'runtime_dependency_identities':runtime})
        self.rows=[dict(pid=20,tid=20,phase=phase,declaration_sha256='unit',errors=[],snapshot=deepcopy(snapshot))
                   for phase in ('initialized','terminated')]

    def verify(self):return verify_admissions(self.rows,self.declaration,'unit',self.allocation)

    def test_raw_valid_structure_only(self):
        self.assertEqual(self.verify()['admission_receipts'],2)

    def test_self_asserted_empty_errors_does_not_hide_affinity_escape(self):
        self.rows[1]['snapshot']['processes'][0]['threads'][0]['affinity']=[0]
        with self.assertRaisesRegex(ValueError,'raw_child_thread_envelope_invalid'):self.verify()

    def test_missing_thread_identity_fails(self):
        self.rows[1]['tid']=77
        with self.assertRaisesRegex(ValueError,'identity_missing'):self.verify()

    def test_missing_process_teardown_fails(self):
        self.rows.pop()
        with self.assertRaisesRegex(ValueError,'teardown_missing'):self.verify()

    def test_thread_start_without_stop_fails(self):
        extra=deepcopy(self.rows[0]);extra['phase']='thread-start';self.rows.append(extra)
        with self.assertRaisesRegex(ValueError,'thread_lifecycle_continuity_missing'):self.verify()

    def test_changed_constraints_even_when_individually_valid_fails(self):
        self.rows[1]['snapshot']['topology']=[{'changed':'unit'}]
        with self.assertRaisesRegex(ValueError,'constraints_changed'):self.verify()


class RawOriginLifetimeTests(unittest.TestCase):
    def setUp(self):
        RawAdmissionContinuityTests.setUp(self)
        self.folder = Path(self.temp.name)/'origins';self.folder.mkdir()
        runtime = self.declaration['environment']['runtime_dependency_identities']
        runtime['stdlib_files'] = {};runtime['dependencies']['websockets']['files'] = {}
        self.declaration.update(infrastructure=infrastructure_identity(),environment_sha256='unit-env',
                                executor={'admission_net_namespace':'unit-original'})
        for row,now in zip(self.rows,[11*10**9,179*10**8]):
            row.update(role='member',real_monotonic_ns=now+1000000)
            row['snapshot']['real_monotonic_ns'] = now
        self.origins = [dict(pid=20,parent_pid=1,role='member',phase=phase,process_start_ticks=5,real_monotonic_ns=now,
            candidate_sha=S,assembly_digest=ASSEMBLY,declaration_sha256='unit',
            infrastructure_digest=self.declaration['infrastructure']['digest'],environment_sha256='unit-env',
            isolated=1,no_site=1,no_bytecode_writes=True,provider_attempts=[],net_namespace='unit-isolated',modules={})
            for phase,now in [('initialized',1101*10**7),('terminated',18*10**9)]]

    def verify(self):
        for n,row in enumerate(self.rows):persist(self.folder/f'ADMISSION-{n}.json',row)
        for n,row in enumerate(self.origins):persist(self.folder/f'ORIGIN-{n}.json',row)
        return verify_origins(self.folder,self.declaration,'unit',self.allocation,expected_roles={'member':1})

    def test_lifetimes_come_from_raw_admission_and_origin_timestamps(self):
        result = self.verify()
        self.assertEqual(result['lifetimes'],[dict(pid=20,start_ticks=5,role='member',start_ns=11*10**9,end_ns=18*10**9)])

    def test_changed_PID_start_identity_rejects_reused_process(self):
        self.rows[1]['snapshot']['processes'][0]['start_ticks'] = 99
        with self.assertRaisesRegex(ValueError,'process_start_identity_changed'):self.verify()

    def test_origin_teardown_cannot_precede_initialization(self):
        self.origins[1]['real_monotonic_ns'] = 10*10**9
        with self.assertRaisesRegex(ValueError,'lifetime_origin_changed'):self.verify()

    def test_admission_snapshot_cannot_be_unrelated_to_its_receipt_time(self):
        self.rows[0]['real_monotonic_ns'] += 3*10**9
        with self.assertRaisesRegex(ValueError,'snapshot_time_unbound'):self.verify()

    def test_negative_snapshot_to_receipt_skew_is_rejected(self):
        self.rows[0]['real_monotonic_ns'] = self.rows[0]['snapshot']['real_monotonic_ns']-1
        with self.assertRaisesRegex(ValueError,'snapshot_time_unbound'):self.verify()

    def test_thread_cannot_claim_lifetime_before_its_process(self):
        for row in self.rows:
            row['snapshot']['processes'][0]['threads'].append(dict(tid=44,affinity=[0,1],cgroup_sha256='cg'))
        first,last = deepcopy(self.rows[0]),deepcopy(self.rows[1])
        first.update(phase='thread-start',tid=44,real_monotonic_ns=105*10**8+1000000)
        first['snapshot']['real_monotonic_ns'] = 105*10**8
        last.update(phase='thread-stop',tid=44)
        self.rows += [first,last]
        with self.assertRaisesRegex(ValueError,'outside_required_process_lifetime'):self.verify()
