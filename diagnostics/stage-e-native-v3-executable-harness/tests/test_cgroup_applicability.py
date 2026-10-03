"""Deterministic raw-evidence/controller regressions; no executor or workload."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE/'harness'))
from attest import (V2_INTERFACES, V2_ROOT_EXCEPTIONS, _interface, admission_errors,
                    cgroup_completeness_errors, cgroup_inventory, constraint_identity,
                    verified_cgroup_inventory)
from core import RAM, canonical, sha
from cgroup_fixtures import controller_topology, diagnosed_cgroup, interface, legacy_cgroup
from test_envelope import fixture


class CgroupApplicabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.capability = Path(self.temp.name)/'UNIT-NOT-AUTHORIZED'
        self.capability.write_bytes(b'UNIT capability only; no signed production allocation')

    def errors(self, groups):
        snapshot, allocation, bounds, runtime = fixture()
        snapshot['cgroup'] = groups
        # Rebind the UNIT digest so structural rejection cannot rely on a stale
        # signed hash. Real admission still requires signed_document upstream.
        allocation['ancestor_inventory_sha256'] = sha(canonical(groups))
        allocation['allocation_evidence'] = [dict(path=str(self.capability),sha256=sha(self.capability.read_bytes()))]
        return admission_errors(snapshot, allocation, bounds, runtime)

    def reject_evidence(self, groups):
        self.assertTrue(cgroup_completeness_errors(groups))
        self.assertIn('hidden_or_changed_cgroup_ancestors', self.errors(groups))

    def reject_limit(self, groups, reason):
        self.assertEqual(cgroup_completeness_errors(groups), [])
        self.assertIn(reason, self.errors(groups))

    def test_diagnosed_host_positive_causal_completeness_only(self):
        groups = diagnosed_cgroup()
        with patch('attest.cgroup_inventory', side_effect=AssertionError('no live collection')):
            self.assertEqual(cgroup_completeness_errors(groups), [])
            self.assertEqual(self.errors(groups), [])
        self.assertEqual(len(verified_cgroup_inventory(groups)), 3)
        self.assertEqual(groups['ancestors'][-1]['interfaces']['cgroup.subtree_control']['raw'].split(), ['memory','pids'])
        self.assertTrue(all(r['interfaces']['cpu.max']['state'] == 'ABSENT' for r in groups['ancestors']))

    def test_fixture_is_exact_projection_of_unchanged_authoritative_diagnosis(self):
        fixture_data = json.loads((HERE/'tests/fixtures/diagnosed_host_cgroup_v2.json').read_bytes())
        raw_path = HERE.parent/'stage-e-native-v3-cgroup-diagnosis/CGROUP_DIAGNOSIS_RAW.json'
        raw = json.loads(raw_path.read_bytes())
        self.assertEqual(fixture_data['diagnosis_commit'],'3ba04753e531b6c5e180f49f3da94e71c079b05b')
        self.assertEqual(fixture_data['raw_evidence_sha256'], sha(raw_path.read_bytes()))
        self.assertEqual(fixture_data['raw_evidence_sha256'],'1a9bf5779ba44d30c65f522d11fe5db3bd349e846276434e0cc095cb372149a8')
        self.assertEqual(fixture_data['visible_cpu_ids'], [0,1])
        self.assertFalse(fixture_data['execution_authorized']); self.assertFalse(fixture_data['production_admission_credit'])
        for row in fixture_data['cgroup']['ancestors']:
            for sample in ('hierarchy_initial','hierarchy_final'):
                original = next(r for r in raw[sample] if r['absolute_cgroup_path'] == row['cgroup_path'])
                for name in V2_INTERFACES:
                    expected = original['files'][name]
                    self.assertEqual(row['interfaces'][name]['state'],expected['state'])
                    if expected['state'] == 'PRESENT':
                        self.assertEqual(row['interfaces'][name]['raw'],expected['text'])

    def test_enabled_unrestrictive_incoming_limits_with_empty_leaf_subtree_pass(self):
        groups = controller_topology('cpu','cpuset')
        self.assertEqual(groups['ancestors'][0]['interfaces']['cgroup.subtree_control']['raw'],'')
        self.assertEqual(cgroup_completeness_errors(groups), [])
        self.assertEqual(self.errors(groups), [])

    def test_disabled_propagation_preserves_unrestrictive_parent_limits(self):
        groups = controller_topology('cpu','cpuset',stop_after=1)
        self.assertEqual(groups['ancestors'][0]['interfaces']['cpu.max']['state'],'ABSENT')
        self.assertEqual(groups['ancestors'][1]['interfaces']['cpu.max']['state'],'PRESENT')
        self.assertEqual(self.errors(groups), [])

    def test_root_only_uses_proven_root_exceptions(self):
        groups = diagnosed_cgroup(); root = deepcopy(groups['ancestors'][-1])
        root['membership'] = '/'
        groups['ancestors'] = [root]; groups['memberships'] = [['0',[],'/']]
        groups['visibility_interfaces']['membership']['raw'] = '0::/\n'
        self.assertEqual(self.errors(groups), [])

    def test_completeness_is_recomputed_when_flag_is_false(self):
        groups = diagnosed_cgroup(); groups['complete'] = False
        self.assertEqual(cgroup_completeness_errors(groups), [])
        self.assertIn('hidden_or_changed_cgroup_ancestors',self.errors(groups))

    def test_explicit_two_cpu_quota_and_RAM_equality_pass(self):
        groups = controller_topology('cpu','cpuset')
        interface(groups['ancestors'][1],'cpu.max','200000 100000\n')
        interface(groups['ancestors'][1],'memory.max',str(RAM)+'\n')
        interface(groups['ancestors'][1],'memory.high',str(RAM)+'\n')
        self.assertEqual(self.errors(groups), [])

    def test_reject_CPU_enabled_for_child_with_cpu_max_missing(self):
        groups = controller_topology('cpu')
        interface(groups['ancestors'][0],'cpu.max',state='ABSENT')
        self.reject_evidence(groups)

    def test_reject_CPU_ancestor_quota_below_two(self):
        groups = controller_topology('cpu')
        interface(groups['ancestors'][1],'cpu.max','199999 100000\n')
        self.reject_limit(groups,'restrictive_ancestor_CPU_quota')

    def test_reject_CPU_quota_above_disabled_child_subtree(self):
        groups = controller_topology('cpu',stop_after=1)
        interface(groups['ancestors'][1],'cpu.max','100000 100000\n')
        self.reject_limit(groups,'restrictive_ancestor_CPU_quota')

    def test_reject_cpuset_enabled_with_effective_file_missing(self):
        groups = controller_topology('cpuset')
        interface(groups['ancestors'][0],'cpuset.cpus.effective',state='ABSENT')
        self.reject_evidence(groups)

    def test_reject_cpuset_excluding_production_CPU(self):
        groups = controller_topology('cpuset')
        interface(groups['ancestors'][0],'cpuset.cpus','0\n')
        interface(groups['ancestors'][0],'cpuset.cpus.effective','0\n')
        self.reject_limit(groups,'restrictive_ancestor_cpuset')

    def test_reject_cpuset_above_disabled_child_subtree(self):
        groups = controller_topology('cpuset',stop_after=1)
        interface(groups['ancestors'][1],'cpuset.cpus','0\n')
        interface(groups['ancestors'][1],'cpuset.cpus.effective','0\n')
        self.reject_limit(groups,'restrictive_ancestor_cpuset')

    def test_reject_memory_max_below_eight_GiB(self):
        groups = diagnosed_cgroup()
        interface(groups['ancestors'][0],'memory.max',str(RAM-1)+'\n')
        self.reject_limit(groups,'restrictive_ancestor_memory_max')

    def test_reject_memory_limit_at_every_applicable_ancestor(self):
        for index in (0,1):
            for name, reason in [('memory.max','memory_max'),('memory.high','memory_high')]:
                with self.subTest(ancestor=index,interface=name):
                    groups = diagnosed_cgroup(); interface(groups['ancestors'][index],name,str(RAM-1)+'\n')
                    self.reject_limit(groups,'restrictive_ancestor_'+reason)

    def test_reject_memory_limit_above_disabled_child_subtree(self):
        groups = controller_topology('memory',stop_after=1)
        interface(groups['ancestors'][1],'memory.high',str(RAM-1)+'\n')
        self.assertEqual(groups['ancestors'][0]['interfaces']['memory.high']['state'],'ABSENT')
        self.reject_limit(groups,'restrictive_ancestor_memory_high')

    def test_reject_contradictory_controllers_and_subtree_control(self):
        groups = diagnosed_cgroup()
        interface(groups['ancestors'][1],'cgroup.subtree_control','cpu memory pids\n')
        self.reject_evidence(groups)

    def test_reject_controller_enabled_without_parent_availability(self):
        groups = diagnosed_cgroup()
        interface(groups['ancestors'][0],'cgroup.controllers','cpu memory pids\n')
        interface(groups['ancestors'][0],'cgroup.subtree_control','cpu\n')
        self.reject_evidence(groups)

    def test_reject_missing_middle_ancestor(self):
        groups = diagnosed_cgroup(); groups['ancestors'].pop(1)
        self.reject_evidence(groups)

    def test_reject_hidden_true_root(self):
        groups = diagnosed_cgroup(); groups['ancestors'].pop()
        self.reject_evidence(groups)

    def test_reject_namespace_mismatch(self):
        for key in ('pid1_namespace','reader_namespace','pid1_mount_namespace','reader_mount_namespace'):
            with self.subTest(key=key):
                groups = diagnosed_cgroup(); groups[key] = 'hidden-namespace'
                self.reject_evidence(groups)

    def test_reject_delegated_mount_root(self):
        groups = diagnosed_cgroup()
        for key in ('mountinfo','pid1_mountinfo'):
            groups['visibility_interfaces'][key]['raw'] = groups['visibility_interfaces'][key]['raw'].replace(
                '0:29 / /sys/fs/cgroup ', '0:29 /system.slice /sys/fs/cgroup ')
        self.reject_evidence(groups)

    def test_reject_mount_visibility_mismatch(self):
        groups = diagnosed_cgroup()
        groups['visibility_interfaces']['pid1_mountinfo']['raw'] = groups['visibility_interfaces']['pid1_mountinfo']['raw'].replace(
            '0:29 / /sys/fs/cgroup ', '0:30 / /sys/fs/cgroup ')
        self.reject_evidence(groups)

    def test_reject_root_directory_in_subtree(self):
        groups = diagnosed_cgroup(); groups['ancestors'][-1]['directory']['inode'] = 70
        self.reject_evidence(groups)

    def test_reject_unreadable_required_controller_interface(self):
        for name in ('cpu.max','cpuset.cpus.effective','memory.max'):
            with self.subTest(interface=name):
                groups = controller_topology('cpu','cpuset')
                interface(groups['ancestors'][0],name,state='UNREADABLE')
                self.reject_evidence(groups)

    def test_reject_forged_complete_true(self):
        groups = diagnosed_cgroup(); groups['complete'] = True
        del groups['visibility_interfaces']; groups['ancestors'] = []
        self.reject_evidence(groups)

    def test_reject_root_exception_outside_root(self):
        groups = diagnosed_cgroup(); groups['ancestors'][0]['root_exceptions'] = list(V2_ROOT_EXCEPTIONS)
        self.reject_evidence(groups)

    def test_reject_missing_limit_without_disabled_controller_evidence(self):
        for name in ('cgroup.controllers','cgroup.subtree_control'):
            with self.subTest(interface=name):
                groups = diagnosed_cgroup(); interface(groups['ancestors'][-1],name,state='ABSENT')
                self.reject_evidence(groups)

    def test_reject_impossible_root_resource_interface(self):
        for name, raw in [('cpu.max','max 100000\n'),('memory.max','max\n'),('cgroup.type','domain\n')]:
            with self.subTest(interface=name):
                groups = diagnosed_cgroup(); interface(groups['ancestors'][-1],name,raw)
                self.reject_evidence(groups)

    def test_reject_unexplained_interface_on_disabled_controller(self):
        groups = diagnosed_cgroup(); interface(groups['ancestors'][0],'cpu.max','max 100000\n')
        self.reject_evidence(groups)

    def test_reject_forged_unrestricted_parsed_limit(self):
        groups = controller_topology('cpu')
        interface(groups['ancestors'][1],'cpu.max','100000 100000\n')
        groups['ancestors'][1]['quota_us'] = None
        self.reject_evidence(groups)

    def test_reject_missing_explicit_memory_limit_interface(self):
        for name in ('memory.max','memory.high','memory.swap.max'):
            with self.subTest(interface=name):
                groups = diagnosed_cgroup(); interface(groups['ancestors'][1],name,state='ABSENT')
                self.reject_evidence(groups)

    def test_reject_inconsistent_incoming_enablement(self):
        groups = controller_topology('cpu')
        interface(groups['ancestors'][1],'cgroup.controllers','memory pids\n')
        interface(groups['ancestors'][1],'cgroup.subtree_control','memory pids\n')
        self.reject_evidence(groups)

    def test_reject_empty_effective_cpuset(self):
        groups = controller_topology('cpuset'); interface(groups['ancestors'][0],'cpuset.cpus.effective','\n')
        self.reject_evidence(groups)

    def test_reject_threaded_or_invalid_domain(self):
        for kind in ('threaded','domain threaded','domain invalid'):
            with self.subTest(kind=kind):
                groups = diagnosed_cgroup(); interface(groups['ancestors'][0],'cgroup.type',kind+'\n')
                self.reject_evidence(groups)

    def test_reject_duplicate_or_extra_ancestor(self):
        groups = diagnosed_cgroup(); groups['ancestors'].append(deepcopy(groups['ancestors'][0]))
        self.reject_evidence(groups)

    def test_reject_visible_controller_mount_without_membership_ancestry(self):
        groups = diagnosed_cgroup()
        for key in ('mountinfo','pid1_mountinfo'):
            groups['visibility_interfaces'][key]['raw'] += '99 24 0:99 / /sys/fs/cgroup/cpu rw - cgroup cgroup rw,cpu\n'
        self.reject_evidence(groups)

    def test_raw_absent_unreadable_max_numeric_states_stay_distinct(self):
        path = Path(self.temp.name)/'interface'
        self.assertEqual(_interface(path),{'state':'ABSENT'})
        with patch.object(Path,'read_text',side_effect=PermissionError('UNIT denied')):
            self.assertEqual(_interface(path)['state'],'UNREADABLE')
        for value in ('max\n',str(RAM)+'\n'):
            path.write_text(value); self.assertEqual(_interface(path),dict(state='PRESENT',raw=value))

    def test_mocked_collector_preserves_the_diagnosed_raw_topology(self):
        groups = diagnosed_cgroup(); readings = {}; directories = {}; links = {}
        for row in groups['ancestors']:
            directories[row['path']] = SimpleNamespace(st_ino=row['directory']['inode'],st_dev=row['directory']['device'])
            for name, value in row['interfaces'].items():
                readings[str(Path(row['path'])/name)] = value
        for key, path in [('membership','/proc/20/cgroup'),('pid1_membership','/proc/1/cgroup'),
                          ('mountinfo','/proc/self/mountinfo'),('pid1_mountinfo','/proc/1/mountinfo')]:
            readings[path] = groups['visibility_interfaces'][key]
        for scope, prefix in [('20',''),('1','pid1_'),('self','reader_')]:
            links[f'/proc/{scope}/ns/cgroup'] = groups[prefix+'namespace']
            links[f'/proc/{scope}/ns/mnt'] = groups[prefix+'mount_namespace']
        with patch('attest._interface',side_effect=lambda p:deepcopy(readings[str(p)])), \
             patch('attest.os.readlink',side_effect=lambda p:links[str(p)]), \
             patch.object(Path,'stat',lambda p:directories[str(p)]):
            actual = cgroup_inventory(20)
        self.assertEqual(actual,groups)

    def test_constraint_identity_keeps_process_lifetime_evidence_separate(self):
        snapshot, _, _, _ = fixture(); snapshot['topology'] = []
        before = constraint_identity(snapshot)
        snapshot['processes'][0]['threads'].append(dict(tid=21,affinity=[0,1],cgroup_sha256='cg'))
        self.assertEqual(before,constraint_identity(snapshot))
        snapshot['cgroup'] = controller_topology('cpu')
        self.assertNotEqual(before,constraint_identity(snapshot))

    def test_legacy_explicit_limits_and_effective_cpuset_fallback_remain_valid(self):
        groups = legacy_cgroup()
        self.assertEqual(self.errors(groups), [])

    def test_reject_legacy_restrictive_ancestor_limits(self):
        for controller, name, value, reason in [
                ('cpu','cpu.cfs_quota_us','199999\n','CPU_quota'),
                ('cpuset','cpuset.cpus','0\n','cpuset'),
                ('memory','memory.limit_in_bytes',str(RAM-1)+'\n','memory_max')]:
            with self.subTest(controller=controller):
                groups = legacy_cgroup()
                row = next(r for r in groups['ancestors'] if r['controllers']==[controller] and r['cgroup_path']=='/')
                interface(row,name,value); self.reject_limit(groups,'restrictive_ancestor_'+reason)

    def test_reject_legacy_enabled_CPU_without_quota_interface(self):
        groups = legacy_cgroup(); interface(groups['ancestors'][0],'cpu.cfs_quota_us',state='ABSENT')
        self.reject_evidence(groups)

    def test_reject_legacy_missing_resource_controller_coverage(self):
        groups = legacy_cgroup(); groups['ancestors'] = groups['ancestors'][:2]; groups['memberships'] = groups['memberships'][:1]
        for key in groups['visibility_interfaces']:
            groups['visibility_interfaces'][key]['raw'] = groups['visibility_interfaces'][key]['raw'].splitlines()[0]+'\n'
        self.reject_evidence(groups)


if __name__ == '__main__':
    unittest.main()
