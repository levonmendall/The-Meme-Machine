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
from core import sha
from run import _wait_trial, _terminate_trial
from verify import verify_admissions
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
