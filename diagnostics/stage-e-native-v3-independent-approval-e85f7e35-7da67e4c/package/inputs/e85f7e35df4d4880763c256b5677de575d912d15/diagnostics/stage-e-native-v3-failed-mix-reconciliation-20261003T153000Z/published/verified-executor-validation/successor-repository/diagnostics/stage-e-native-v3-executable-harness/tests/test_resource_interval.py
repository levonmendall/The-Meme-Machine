"""Finite resource dictionaries bound to counterfactual execution times only."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'harness'))
from core import canonical, sha, RESOURCE_SAMPLING
from attest import constraint_identity
from preserve import persist
from verify import RESOURCE_TOLERANCE_NS, verify_resource_timeline
from regression_fixtures import interval
from test_envelope import fixture


class ResourceIntervalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name);self.resources = self.root/'resources';self.resources.mkdir()
        snapshot,self.allocation,bounds,runtime = fixture();snapshot['topology'] = []
        proof = self.root/'unit-capability';proof.write_bytes(b'UNIT NOT AUTHORIZED')
        self.allocation['allocation_evidence'] = [dict(path=str(proof),sha256=sha(proof.read_bytes()))]
        process = deepcopy(snapshot['processes'][0]);process.update(pid=21,ppid=20,start_ticks=7)
        process['threads'] = [dict(tid=21,affinity=[0,1],cgroup_sha256='cg'),dict(tid=22,affinity=[0,1],cgroup_sha256='cg')]
        snapshot['processes'].append(process)
        self.d = dict(storage_bounds=bounds,environment={'runtime_dependency_identities':runtime},executor={'boot_id':'b','hostname':'h'},
                      resource_sampling=deepcopy(RESOURCE_SAMPLING))
        self.interval = interval()
        self.lifetimes = [dict(pid=21,start_ticks=7,start_ns=11*10**9,end_ns=18*10**9),
                          dict(pid=21,tid=22,start_ticks=7,start_ns=11*10**9,end_ns=18*10**9)]
        self.sources = [dict(first_release_ns=12*10**9,last_release_ns=17*10**9)]
        self.snapshots = [dict(deepcopy(snapshot),real_monotonic_ns=t*10**8) for t in range(100,196,5)]

    def write(self):
        for path in self.resources.glob('RESOURCE-*'):path.unlink()
        previous = '0'*64
        for n,snapshot in enumerate(self.snapshots,1):
            row = dict(ordinal=n,previous=previous,boundary='admission' if n == 1 else
                       'teardown' if n == len(self.snapshots) else 'continuous',snapshot=snapshot,errors=[],
                       constraints_sha256=sha(canonical(constraint_identity(snapshot))))
            previous = sha(canonical(row));persist(self.resources/f'RESOURCE-{n:06d}.json',dict(row,sha256=previous))

    def verify(self, **changes):
        self.write()
        arguments = dict(execution_interval=self.interval,lifetimes=self.lifetimes,source_intervals=self.sources)
        arguments.update(changes)
        return verify_resource_timeline(self.resources,self.d,self.allocation,**arguments)

    def test_complete_interval_and_process_thread_lifetimes_are_required(self):
        result = self.verify()
        self.assertEqual(result['required_lifetimes_verified'],2)
        self.assertEqual(result['sampling_tolerance_ns'],RESOURCE_TOLERANCE_NS)

    def test_missing_trial_interval_refuses_old_unbound_call(self):
        self.write()
        with self.assertRaisesRegex(ValueError,'execution_interval_and_lifetimes_required'):
            verify_resource_timeline(self.resources,self.d,self.allocation)

    def test_100_ms_admission_teardown_cannot_cover_measured_trial(self):
        self.snapshots = [self.snapshots[0],dict(self.snapshots[-1],real_monotonic_ns=101*10**8)]
        with self.assertRaisesRegex(ValueError,'does_not_cover_execution'):self.verify()

    def test_unrelated_shifted_timeline_is_rejected_despite_valid_chain_and_resources(self):
        for row in self.snapshots:row['real_monotonic_ns'] += 100*10**9
        with self.assertRaisesRegex(ValueError,'does_not_cover_execution'):self.verify()

    def test_truncation_at_source_end_does_not_cover_helper_termination(self):
        self.snapshots = [r for r in self.snapshots if r['real_monotonic_ns'] <= 17*10**9]
        with self.assertRaisesRegex(ValueError,'does_not_cover_execution'):self.verify()

    def test_source_release_outside_execution_fails(self):
        self.sources[0]['last_release_ns'] = 19*10**9+1
        with self.assertRaisesRegex(ValueError,'source_release_outside'):self.verify()

    def test_late_helper_or_early_startup_outside_interval_fails(self):
        for name,value in [('end_ns',19*10**9+1),('start_ns',10*10**9)]:
            life = deepcopy(self.lifetimes);life[0][name] = value
            with self.assertRaisesRegex(ValueError,'lifetime_outside'):self.verify(lifetimes=life)

    def test_missing_required_process_in_continuous_sample_fails(self):
        self.snapshots[10]['processes'].pop()
        with self.assertRaisesRegex(ValueError,'missing_during_lifetime'):self.verify()

    def test_PID_reuse_does_not_satisfy_required_lifetime(self):
        self.snapshots[10]['processes'][1]['start_ticks'] = 999
        with self.assertRaisesRegex(ValueError,'missing_during_lifetime'):self.verify()

    def test_missing_thread_during_its_lifetime_fails(self):
        self.snapshots[10]['processes'][1]['threads'].pop()
        with self.assertRaisesRegex(ValueError,'missing_during_lifetime'):self.verify()

    def test_boundary_tolerance_equality_is_explicit_and_one_ns_excess_fails(self):
        self.interval['end_real_monotonic_ns'] = self.snapshots[-1]['real_monotonic_ns']+RESOURCE_TOLERANCE_NS
        self.interval['end_perf_ns'] = self.interval['start_perf_ns']+self.interval['end_real_monotonic_ns']-self.interval['start_real_monotonic_ns']
        self.verify()
        self.interval['end_real_monotonic_ns'] += 1;self.interval['end_perf_ns'] += 1
        with self.assertRaisesRegex(ValueError,'does_not_cover_execution'):self.verify()

    def test_measured_and_resource_clocks_cannot_describe_different_intervals(self):
        self.interval['end_perf_ns'] += 10**9
        with self.assertRaisesRegex(ValueError,'measured_clocks_unbound'):self.verify()

    def test_clock_pair_uncertainty_cannot_expand_sampling_tolerance(self):
        self.interval['start_clock_read_span_ns'] = 10**9
        with self.assertRaisesRegex(ValueError,'measured_clocks_unbound'):self.verify()

    def test_declared_sampling_tolerances_cannot_be_loosened(self):
        self.d['resource_sampling']['boundary_tolerance_ns'] += 1
        with self.assertRaisesRegex(ValueError,'sampling_tolerance_changed'):self.verify()

    def test_resource_sample_gap_limit_is_still_enforced(self):
        self.snapshots = self.snapshots[:2]+self.snapshots[8:]
        with self.assertRaisesRegex(ValueError,'resource_monitor_gap'):self.verify()

    def test_pure_timeline_rejects_forged_complete_and_rebound_inventory_hash(self):
        for snapshot in self.snapshots:
            snapshot['cgroup']['complete'] = True
            del snapshot['cgroup']['ancestors'][-1]['interfaces']['cgroup.subtree_control']
        self.allocation['ancestor_inventory_sha256'] = sha(canonical(self.snapshots[0]['cgroup']))
        with self.assertRaisesRegex(ValueError,'raw_resource_admission'):self.verify()

    def test_pure_timeline_enforces_quota_above_disabled_child_controller(self):
        from cgroup_fixtures import controller_topology, interface
        groups = controller_topology('cpu',stop_after=1)
        interface(groups['ancestors'][1],'cpu.max','199999 100000\n')
        for snapshot in self.snapshots:
            snapshot['cgroup'] = deepcopy(groups)
        self.allocation['ancestor_inventory_sha256'] = sha(canonical(groups))
        with self.assertRaisesRegex(ValueError,'raw_resource_admission'):self.verify()
