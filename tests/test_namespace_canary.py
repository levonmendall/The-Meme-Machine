"""Real isolated kernel canaries plus deterministic fail-closed setup checks."""
from contextlib import contextmanager
import ctypes
import errno
import json
import os
from pathlib import Path
import subprocess
import socket
import sys
import unittest
from unittest.mock import Mock, patch

from meme_machine.operational.artifact_storage import Scratch
from meme_machine.operational import namespace_canary as ns
from meme_machine.operational import namespace_runtime as runtime


@contextmanager
def fixture():
    skipped = None
    with Scratch() as scope:
        try:yield scope
        except unittest.SkipTest as error:skipped = error
        scope.check();scope.success = True
    if skipped is not None:raise skipped


def specification(scope):
    return dict(root=str(scope/'rootfs'),work=str(scope/'work'),secret=str(scope/'host-secret'),
        unix=str(scope/'host.sock'),abstract='mm-namespace-canary-123-456',port=12345,
        parent_pid=os.getpid(),host_shm_device=1,ipc_fd=3)


class NamespaceCanaryTests(unittest.TestCase):
    def test_actual_namespace_enforcement_and_real_spawn_pool(self):
        if os.geteuid()==0:self.skipTest('BLOCKED: actual canary requires a nonroot caller')
        if Path(sys.executable).resolve().stat().st_uid!=0:
            self.skipTest('BLOCKED: actual canary requires a root-owned installed interpreter')
        with fixture() as scope:
            result = ns.canary(scope.path)
            if result['state'] == 'BLOCKED':
                self.assertFalse(result['fallback_allowed'])
                # A real kernel/LSM refusal is an explicit availability skip.
                # Bugs, invalid receipts and missing proof remain test failures.
                self.assertIsInstance(result.get('error_number'),int,result)
                self.assertIn(result['error_number'],(errno.EPERM,errno.EACCES,errno.ENOSYS,
                                                      errno.EINVAL,errno.EOPNOTSUPP),result)
                self.skipTest('BLOCKED: namespace enforcement unavailable: ' + result['code'])
            self.assertEqual(result['state'], 'CANARY_ENFORCEMENT_VERIFIED', result)
            self.assertEqual(result['child_exit'], 0)
            self.assertTrue(all(result['checks'].values()), result)
            self.assertTrue(result['parent_namespaces_unchanged'])
            self.assertTrue(result['parent_cwd_unchanged'])
            self.assertTrue(result['parent_open_descriptors_preserved'])
            self.assertEqual(result['provider_calls'], 0)
            self.assertFalse(result['financial_authority'])
            self.assertFalse(result['actual_service_restrictions_verified'])
            import sqlite3
            with sqlite3.connect(scope.path/'work/test.sqlite') as db:
                self.assertEqual(db.execute('PRAGMA integrity_check').fetchone(), ('ok',))
                self.assertEqual(db.execute('SELECT value FROM values_table').fetchone(), (42,))
            db.close()

    def test_scratch_admission_and_freshness_are_required(self):
        with fixture() as scope:
            self.assertEqual(ns._scratch(scope.path, os.getpid()), scope.path)
            with self.assertRaisesRegex(ns.Blocked,'scratch_marker'):
                ns._scratch(scope.path, os.getpid()+1)
            (scope.path/'rootfs').mkdir(mode=0o700)
            with self.assertRaisesRegex(ns.Blocked,'already_used'):ns.canary(scope.path)
            for seconds in (0,21,True):
                with self.assertRaises(ns.Blocked):ns.canary(scope.path,seconds=seconds)

    def test_private_paths_reject_financial_ancestors_symlinks_and_shared_modes(self):
        with fixture() as scope:
            local = scope.path/'private';local.mkdir(mode=0o700)
            alias = scope.path/'alias';alias.symlink_to(local,target_is_directory=True)
            with self.assertRaisesRegex(ns.Blocked,'symlink'):ns._private(alias)
            local.chmod(0o755)
            with self.assertRaisesRegex(ns.Blocked,'private_path'):ns._private(local)
            local.chmod(0o700)
            (scope.path/'portfolio.sqlite').touch()
            with self.assertRaisesRegex(ns.Blocked,'financial_ancestor'):ns._private(local)
            with self.assertRaisesRegex(ns.Blocked,'production_path'):
                ns._private('/srv/meme-machine/anywhere')

    def test_fixed_spec_cannot_select_arbitrary_paths_commands_or_peers(self):
        with fixture() as scope:
            valid = specification(scope.path)
            self.assertEqual(ns._spec(valid),valid)
            for changed in ({'command':'anything'},{'work':'/srv/meme-machine'},
                    {'secret':'/etc/meme-machine/paper.aws.env'},{'unix':'/production.sock'},
                    {'abstract':'other'},{'port':True},{'parent_pid':1},{'host_shm_device':-1},{'ipc_fd':0}):
                with self.subTest(changed=changed),self.assertRaises(ns.Blocked):
                    ns._spec(dict(valid,**changed))

    def test_syscall_failures_are_fixed_BLOCKED_without_privileged_fallback(self):
        kernel = object.__new__(ns.Kernel)
        kernel.libc = Mock()
        kernel.libc.unshare.return_value = -1
        with patch.object(ns.ctypes,'get_errno',return_value=errno.EPERM):
            with self.assertRaises(ns.Blocked) as caught:kernel.unshare(ns.USER)
        self.assertEqual(caught.exception.code,'namespace_unshare_refused')
        self.assertEqual(caught.exception.number,errno.EPERM)
        with patch.object(ns.platform,'machine',return_value='unreviewed'):
            with self.assertRaisesRegex(ns.Blocked,'platform_unreviewed'):ns.Kernel()

    def test_root_setup_is_refused_before_namespace_or_filesystem_changes(self):
        with patch.object(ns,'Kernel') as kernel,patch.object(ns.os,'geteuid',return_value=0):
            with self.assertRaisesRegex(ns.Blocked,'nonroot_required'):ns._setup({})
        kernel.return_value.unshare.assert_not_called()
        kernel.return_value.mount.assert_not_called()

    def test_namespace_lock_preserves_ordinary_clone_but_blocks_namespace_flags(self):
        for machine, architecture, clone, unshare in (
                ('x86_64',0xc000003e,56,272),('aarch64',0xc00000b7,220,97)):
            captured = []
            class Kernel:
                def call(self,*args,**kwargs):
                    program = args[3]._obj
                    captured.extend((program.filter[i].code,program.filter[i].jt,
                                     program.filter[i].jf,program.filter[i].k)
                                    for i in range(program.length))
            with patch.object(ns.platform,'machine',return_value=machine):ns._lock_namespaces(Kernel())
            def evaluate(number,flags=0,arch=architecture):
                cursor=0;value=0
                while True:
                    code,jt,jf,k=captured[cursor]
                    if code==0x20:value={0:number,4:arch,16:flags}[k]
                    elif code==0x15:cursor+=jt if value==k else jf
                    elif code==0x35:cursor+=jt if value>=k else jf
                    elif code==0x45:cursor+=jt if value&k else jf
                    elif code==0x06:return k
                    else:self.fail('unknown_bpf')
                    cursor+=1
            self.assertEqual(evaluate(clone,17),0x7fff0000)
            self.assertEqual(evaluate(clone,ns.USER|17),0x00050000|errno.EPERM)
            self.assertEqual(evaluate(unshare),0x00050000|errno.EPERM)
            self.assertEqual(evaluate(435),0x00050000|errno.ENOSYS)
            self.assertEqual(evaluate(999),0x00050000|errno.EPERM)
            self.assertEqual(evaluate(clone,arch=0),0x80000000)

    def test_outer_timeout_kills_only_its_new_process_group_and_returns_BLOCKED(self):
        child=Mock(pid=123456)
        with fixture() as scope,patch.object(ns.subprocess,'Popen',return_value=child),\
                patch.object(ns.os,'killpg') as kill,patch.object(ns,'_collect',
                    side_effect=subprocess.TimeoutExpired('canary',.01)),\
                patch.object(runtime,'build',return_value={}):
            result=ns.canary(scope.path,seconds=.01)
            self.assertEqual(result['state'],'BLOCKED')
            self.assertEqual(result['code'],'namespace_wall_expired')
            self.assertFalse(result['fallback_allowed'])
            kill.assert_called_once_with(123456,ns.signal.SIGKILL)
            options=ns.subprocess.Popen.call_args.kwargs
            self.assertNotIn('preexec_fn',options)
            self.assertTrue(options['close_fds'])
            self.assertTrue(options['start_new_session'])
            self.assertEqual(options['env'],{})
            self.assertIn('-S',ns.subprocess.Popen.call_args.args[0])

    def test_malformed_child_receipt_never_attests_enforcement(self):
        for raw in (b'not a receipt',b'[]',b'{"state":"CANARY_ENFORCEMENT_VERIFIED",'
                b'"provider_calls":0,"financial_authority":false}'):
            with self.subTest(raw=raw),fixture() as scope:
                child=Mock(pid=123456,returncode=2)
                with patch.object(ns.subprocess,'Popen',return_value=child),\
                        patch.object(ns,'_collect',return_value=(raw,b'')),\
                        patch.object(runtime,'build',return_value={}):
                    result=ns.canary(scope.path)
                self.assertEqual(result['state'],'BLOCKED')
                self.assertIn(result['code'],('namespace_result_unavailable','namespace_receipt_unverified'))

    def test_parent_death_races_are_rechecked_after_arming(self):
        kernel=Mock()
        with patch.object(ns.os,'getppid',return_value=1):
            with self.assertRaisesRegex(ns.Blocked,'parent_changed'):ns._arm_parent(kernel,12345)
        kernel.prctl.assert_called_once_with(1,ns.signal.SIGKILL,'namespace_parent_death_refused')
        lifeline=Mock()
        lifeline.poll.return_value=[(99,ns.select.POLLHUP)]
        with patch.object(ns.select,'poll',return_value=lifeline):
            with self.assertRaisesRegex(ns.Blocked,'parent_changed'):ns._arm_pid1_parent(kernel,99)
        lifeline.poll.assert_called_once_with(0)

    def test_live_output_capture_enforces_bound_before_accumulating_large_output(self):
        with fixture():
            parent,peer=socket.socketpair()
            peer.close()
            child=subprocess.Popen([sys.executable,'-I','-B','-S','-c',
                'import os;os.write(1,b"x"*20000)'],stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True,env={})
            try:
                with self.assertRaisesRegex(ns.Blocked,'result_bound'):ns._collect(child,parent,2)
            finally:
                ns._kill_probe(child)
                child.stdout.close();child.stderr.close();parent.close()


if __name__=='__main__':unittest.main()
