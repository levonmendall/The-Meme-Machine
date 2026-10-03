"""Pure synthetic snapshots; no resource benchmark or native capacity claim."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'harness'))
from core import RAM, HEADROOM, canonical, sha
from attest import admission_errors, cpus, reserve_storage
from cgroup_fixtures import diagnosed_cgroup


def fixture():
    cg = diagnosed_cgroup()
    snapshot = dict(cpu={'present':[0,1],'possible':[0,1],'online':[0,1]}, affinity=[0,1],
        boot_id='b',hostname='h',real_utc_ns=100,memory={'MemTotal':RAM-4096,'SwapTotal':0},
        cgroup=cg,balloon_modules=[],scope_pid=20,scope_cgroup_sha256='cg',
        processes=[dict(pid=20,ppid=1,kernel=False,start_ticks=5,executable_sha256='python',
                        threads=[dict(tid=20,affinity=[0,1],cgroup_sha256='cg')])],
        storage=[dict(path='/data',mount='/data',device='8:0',fs_type='ext4',options='rw',
                      total_bytes=100*1024**3,free_bytes=HEADROOM)])
    allocation = dict(allocation=dict(allocated_vcpu=2,dedicated_vcpu=2,ram_bytes=RAM,
        visible_cpu_ids=[0,1],executor_kind='dedicated-vm',ballooning=False,swap=False,competing_workload=False),
        boot_id='b',hostname='h',valid_from_utc_ns=0,expires_utc_ns=200,usable_ram_bytes=RAM-4096,
        ancestor_inventory_sha256=sha(canonical(cg)),allocation_evidence=[],system_processes=[],
        durable_mounts=[dict(device='8:0',mount='/data',file_and_directory_fsync=True,
                            sqlite_WAL_locking=True,physical_durability=True)])
    bounds = dict(headroom_bytes=HEADROOM,immutable_tape_bytes=2442975789,working_bytes=2*1024**3,
        retained_evidence_bytes=1024,publication_copy_bytes=4*1024**3,requirements=[dict(path='/data')])
    runtime = dict(python='3.12.14',machine='x86_64',dependencies={'websockets':{'version':'17.1'}},
                   python_executable_hash='python',os_tools={})
    return snapshot,allocation,bounds,runtime


class EnvelopeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.args = fixture()
        path = Path(self.directory.name)/'capability'
        path.write_bytes(b'unit fixture, never authentic allocation proof')
        self.args[1]['allocation_evidence'] = [dict(path=str(path),sha256=sha(path.read_bytes()))]

    def errors(self):
        return admission_errors(*self.args)

    def test_structural_exact_envelope_fixture(self):
        self.assertEqual(self.errors(), [])

    def test_larger_allocation_even_with_two_cpu_affinity_and_quota(self):
        for count in (3,4,8,16,64):
            with self.subTest(count=count):
                self.args[1]['allocation']['allocated_vcpu'] = count
                self.args[0]['cgroup']['ancestors'][0]['quota_us'] = 200000
                self.assertIn('allocation_allocated_vcpu', self.errors())

    def test_false_two_cpu_label_with_larger_visible_machine(self):
        self.args[0]['cpu']['present'] = [0,1,2,3]
        self.assertIn('executor_allocation_larger_than_two_or_offline_CPUs',self.errors())

    def test_offline_cpu_is_still_larger_allocation(self):
        self.args[0]['cpu']['possible'] = [0,1,2,3]
        self.assertTrue(self.errors())

    def test_any_restrictive_ancestor_quota_fails(self):
        self.args[0]['cgroup']['ancestors'].append(dict(period_us=100000,quota_us=199999,
            cpuset='0-1',cpuset_effective='0-1',memory_max=None,memory_high=None))
        self.assertIn('restrictive_ancestor_CPU_quota', self.errors())

    def test_any_restrictive_ancestor_memory_fails(self):
        self.args[0]['cgroup']['ancestors'][0]['memory_max'] = RAM-1
        self.assertIn('restrictive_ancestor_memory_max', self.errors())

    def test_hidden_ancestors_fail(self):
        self.args[0]['cgroup']['complete'] = False
        self.assertIn('hidden_or_changed_cgroup_ancestors', self.errors())

    def test_child_thread_affinity_and_cgroup_escape(self):
        self.args[0]['processes'][0]['threads'][0].update(affinity=[0],cgroup_sha256='escaped')
        self.assertIn('child_or_thread_affinity',self.errors())
        self.assertIn('child_or_thread_cgroup_escape',self.errors())

    def test_competing_workload_fails(self):
        self.args[0]['processes'].append(dict(pid=33,ppid=1,kernel=False,start_ticks=3,
            executable_sha256='python',threads=[]))
        self.assertIn('competing_or_unattested_process', self.errors())

    def test_changed_ancestor_attestation_fails(self):
        self.args[1]['ancestor_inventory_sha256'] = 'changed'
        self.assertTrue(self.errors())

    def test_allocation_not_dedicated(self):
        self.args[1]['allocation']['dedicated_vcpu'] = 1
        self.assertTrue(self.errors())

    def test_greater_than_eight_GiB_allocation_fails(self):
        self.args[1]['allocation']['ram_bytes'] = 16*1024**3
        self.assertTrue(self.errors())

    def test_swap_and_ballooning_fail(self):
        self.args[0]['memory']['SwapTotal'] = 1
        self.args[0]['balloon_modules'] = ['virtio_balloon']
        self.assertIn('swap_is_not_RAM', self.errors())
        self.assertIn('ballooning', self.errors())

    def test_insufficient_storage_and_tmpfs_fail(self):
        self.args[0]['storage'][0].update(free_bytes=HEADROOM-1,fs_type='tmpfs')
        self.assertIn('storage_capacity_or_headroom', self.errors())
        self.assertIn('nondurable_or_readonly_storage', self.errors())

    def test_exact_headroom_equality_is_permitted(self):
        self.assertEqual(self.args[0]['storage'][0]['free_bytes'], HEADROOM)
        self.assertEqual(self.errors(), [])

    def test_headroom_alone_does_not_admit_new_work_or_publication(self):
        with self.assertRaisesRegex(ValueError,'insufficient_free_reserved'):
            reserve_storage(self.args[0],self.args[2])

    def test_exact_work_and_publication_reservation_equality(self):
        snapshot,_,bounds,_=self.args
        snapshot['storage'][0]['free_bytes']=HEADROOM+bounds['working_bytes']+bounds['publication_copy_bytes']
        self.assertEqual(reserve_storage(snapshot,bounds)['required_free_bytes'],snapshot['storage'][0]['free_bytes'])

    def test_no_member_can_start_without_bound_work_reservation(self):
        self.args[2]['member_working_bytes']={}
        with self.assertRaisesRegex(ValueError,'missing_member_storage_reservation'):
            reserve_storage(self.args[0],self.args[2],member='combined-1')

    def test_unattested_fsync_or_sqlite_fails(self):
        self.args[1]['durable_mounts'][0]['sqlite_WAL_locking'] = False
        self.assertTrue(self.errors())

    def test_stale_allocation_fails(self):
        self.args[1]['expires_utc_ns'] = 100
        self.assertIn('allocation_expired', self.errors())

    def test_capability_bytes_changed_fails(self):
        Path(self.args[1]['allocation_evidence'][0]['path']).write_bytes(b'changed')
        self.assertIn('capability_evidence_bytes', self.errors())

    def test_cpus_parse_ranges_and_invalid_input(self):
        self.assertEqual(cpus('0-1,4,4'), [0,1,4])
        for raw in ('2-1','-1','0-1-2'):
            with self.assertRaises(ValueError):
                cpus(raw)
