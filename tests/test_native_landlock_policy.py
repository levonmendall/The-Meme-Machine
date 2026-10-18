"""Pure filter interpretation plus explicit syscall-only disposable processes."""
import errno
import fcntl
import json
import os
from pathlib import Path
import resource
import signal
import socket
import struct
import subprocess
import sys
import unittest

from meme_machine.operational import native_landlock_policy as policy
from meme_machine.operational.artifact_storage import Scratch


def result(number,*arguments,arch=0xc000003e,pid=1234):
    data=struct.pack('<IIQ6Q',number,arch,0,*((*arguments,*([0]*6))[:6]))
    rows=policy.filter_rows(pid=pid);index=0;value=0
    while index<len(rows):
        code,yes,no,operand=rows[index]
        if code==0x20:value=struct.unpack_from('<I',data,operand)[0]
        elif code==0x54:value&=operand
        elif code in (0x15,0x25,0x35):
            condition=(value==operand if code==0x15 else value>operand if code==0x25 else value>=operand)
            index+=yes if condition else no
        elif code==0x06:return operand
        else:raise AssertionError(('unknown instruction',code))
        index+=1
    raise AssertionError('filter fell through')


class NativeFilterTests(unittest.TestCase):
    def test_default_deny_arch_unknown_and_new_syscalls(self):
        self.assertEqual(result(0,arch=0x40000003),policy.KILL)
        self.assertEqual(result(0x40000000),policy.DENY)
        for number in (41,42,43,46,47,49,50,54,101,105,106,109,112,113,114,116,117,119,
                126,132,142,143,144,145,146,147,148,160,161,165,166,167,168,
                169,172,173,175,176,188,189,190,200,235,240,241,242,243,244,245,
                246,248,249,250,251,252,260,261,268,272,274,280,288,298,299,307,
                308,310,311,312,313,317,319,320,321,323,324,425,426,427,428,429,
                430,431,432,433,434,437,438,442,451,452,453,454,455,999):
            with self.subTest(number=number):self.assertEqual(result(number),policy.DENY)
        self.assertEqual(result(435),0x50000|errno.ENOSYS)

    def test_actual_fork_and_thread_shapes_without_parent_namespace_or_pidfd_escape(self):
        for flags in (17,0x1200011,0x4111,0x3d0f00):self.assertEqual(result(56,flags),policy.ALLOW)
        for flags in (0,0x8000,0x1000,0x800000,0x10000000,0x3d0f00|0x80,1<<32):
            self.assertEqual(result(56,flags),policy.DENY)

    def test_only_anonymous_stream_socketpairs_and_no_address_vector_paths(self):
        for flags in (0,socket.SOCK_CLOEXEC,socket.SOCK_NONBLOCK,socket.SOCK_NONBLOCK|socket.SOCK_CLOEXEC):
            self.assertEqual(result(53,socket.AF_UNIX,socket.SOCK_STREAM|flags,0),policy.ALLOW)
        for args in ((socket.AF_INET,socket.SOCK_STREAM,0),(socket.AF_UNIX,socket.SOCK_DGRAM,0),
                (socket.AF_UNIX,socket.SOCK_STREAM,1),(socket.AF_UNIX,socket.SOCK_STREAM|0x100,0)):
            self.assertEqual(result(53,*args),policy.DENY)
        for number in (44,45):
            self.assertEqual(result(number,3,123,8,0,0,0),policy.ALLOW)
            for address in (1,1<<32):self.assertEqual(result(number,3,123,8,0,address,0),policy.DENY)
            self.assertEqual(result(number,3,123,8,0,0,1),policy.DENY)
        self.assertEqual(result(55,3,socket.SOL_SOCKET,socket.SO_TYPE),policy.ALLOW)
        self.assertEqual(result(55,3,socket.SOL_SOCKET,socket.SO_PEERCRED),policy.DENY)

    def test_fcntl_keeps_original_locks_flags_and_refuses_async_pid_ownership(self):
        for command in (fcntl.F_DUPFD,fcntl.F_DUPFD_CLOEXEC,fcntl.F_GETFD,fcntl.F_GETFL,
                        fcntl.F_GETLK,fcntl.F_SETLK,fcntl.F_SETLKW):
            self.assertEqual(result(72,3,command),policy.ALLOW)
        for flags in (0,fcntl.FD_CLOEXEC):self.assertEqual(result(72,3,fcntl.F_SETFD,flags),policy.ALLOW)
        self.assertEqual(result(72,3,fcntl.F_SETFD,2),policy.DENY)
        for flags in (0,os.O_NONBLOCK,os.O_RDWR|os.O_APPEND|0x8000):
            self.assertEqual(result(72,3,fcntl.F_SETFL,flags),policy.ALLOW)
        for command in (fcntl.F_SETOWN,fcntl.F_SETSIG,fcntl.F_NOTIFY,fcntl.F_SETLEASE,999):
            self.assertEqual(result(72,3,command),policy.DENY)
        for flags in (os.O_ASYNC,os.O_DIRECT,os.O_NOATIME,1<<32):
            self.assertEqual(result(72,3,fcntl.F_SETFL,flags),policy.DENY)
        self.assertEqual(result(16,3,0x5421),policy.ALLOW)
        self.assertEqual(result(16,3,0x5412),policy.DENY)

    def test_only_self_queries_and_original_owned_termination(self):
        self.assertEqual(result(302,0,3,0,1024),policy.ALLOW)
        self.assertEqual(result(302,1,3,0,1024),policy.DENY)
        self.assertEqual(result(302,0,3,1024,1024),policy.DENY)
        for value in (resource.RLIMIT_AS,resource.RLIMIT_NOFILE):
            self.assertEqual(result(302,0,value,1024,0),policy.ALLOW)
            self.assertEqual(result(302,0,value,1<<32,0),policy.ALLOW)
            self.assertEqual(result(302,1234,value,1024,0),policy.DENY)
        for value in (resource.RLIMIT_CPU,resource.RLIMIT_STACK,resource.RLIMIT_NPROC,resource.RLIMIT_CORE):
            self.assertEqual(result(302,0,value,1024,0),policy.DENY)
        self.assertEqual(result(140,os.PRIO_PROCESS,0),policy.ALLOW)
        self.assertEqual(result(141,os.PRIO_PROCESS,0,5),policy.ALLOW)
        for number in (140,141):
            self.assertEqual(result(number,os.PRIO_PGRP,0,5),policy.DENY)
            self.assertEqual(result(number,os.PRIO_PROCESS,1234,5),policy.DENY)
        for value in (0,4,6,20,2**32-1):
            self.assertEqual(result(141,os.PRIO_PROCESS,0,value),policy.DENY)
        self.assertEqual(result(204,0),policy.ALLOW)
        self.assertEqual(result(204,1234),policy.DENY)
        for number in (0,signal.SIGTERM,signal.SIGKILL):self.assertEqual(result(62,1235,number),policy.ALLOW)
        for pid in (0,2**31,2**32-1):self.assertEqual(result(62,pid,signal.SIGKILL),policy.DENY)
        self.assertEqual(result(62,1235,signal.SIGUSR1),policy.DENY)
        self.assertEqual(result(234,1234,1235,signal.SIGKILL),policy.ALLOW)
        self.assertEqual(result(234,1235,1235,signal.SIGKILL),policy.DENY)
        self.assertEqual(result(436,3,999,0),policy.ALLOW)
        self.assertEqual(result(436,3,999,2),policy.DENY)

    def test_parent_death_cannot_be_cleared_and_control_mutators_are_closed(self):
        for option in (3,21,39):self.assertEqual(result(157,option),policy.ALLOW)
        self.assertEqual(result(157,2,4096),policy.ALLOW)
        self.assertEqual(result(157,1,signal.SIGKILL),policy.ALLOW)
        for args in ((1,0),(1,signal.SIGTERM),(1,signal.SIGKILL,1),(4,1),(36,1),(38,1),(41,2)):
            self.assertEqual(result(157,*args),policy.DENY)
        self.assertEqual(result(158,0x1002,4096),policy.ALLOW)
        self.assertEqual(result(158,0x1001,4096),policy.DENY)

    def test_internal_descriptor_flags_cannot_open_notification_or_unreviewed_paths(self):
        for flags in (0,os.O_CLOEXEC):
            self.assertEqual(result(291,flags),policy.ALLOW)
            self.assertEqual(result(292,3,7,flags),policy.ALLOW)
        for flags in (0,os.O_CLOEXEC,os.O_NONBLOCK,os.O_CLOEXEC|os.O_NONBLOCK):
            self.assertEqual(result(293,4096,flags),policy.ALLOW)
        for flags in (0x80,os.O_DIRECT,1<<32):
            self.assertEqual(result(293,4096,flags),policy.DENY)
        self.assertEqual(result(291,os.O_NONBLOCK),policy.DENY)
        self.assertEqual(result(292,3,7,os.O_NONBLOCK),policy.DENY)
        self.assertEqual(result(290),policy.DENY)


class ActualNativeSeccompTests(unittest.TestCase):
    def test_actual_copied_two_decoder_one_history_and_tracker_under_inherited_filter(self):
        from meme_machine.operational import isolated_native_image as image
        from tests.test_isolated_native_launcher import offline_software_approval
        from tests.test_isolated_native_spawn import _COPIED_SCOPE,owned_run
        marker='scope=spawn.NativeSpawnScope(layout)'
        self.assertEqual(_COPIED_SCOPE.count(marker),1)
        setup=r'''
import ctypes,resource
from meme_machine.operational.native_landlock_policy import NativePolicy
_native_vm=int(Path('/proc/self/statm').read_text().split()[0])*os.sysconf('SC_PAGE_SIZE')
assert os.getpriority(os.PRIO_PROCESS,0)==0
resource.setrlimit(resource.RLIMIT_AS,(2*1024**3,2*1024**3))
_,hard=resource.getrlimit(resource.RLIMIT_NOFILE)
ceiling=min(65536,hard) if hard!=resource.RLIM_INFINITY else 65536
resource.setrlimit(resource.RLIMIT_NOFILE,(ceiling,ceiling))
kernel=NativePolicy()
kernel.call(157,ctypes.c_int(38),ctypes.c_ulong(1),ctypes.c_ulong(0),ctypes.c_ulong(0),ctypes.c_ulong(0),code='fixture_nnp')
kernel.seccomp()
'''
        program=_COPIED_SCOPE.replace(marker,setup+'\n'+marker).replace(
            'prctl(2,c.byref(n))','prctl(2,c.byref(n),0,0,0)').replace(
            'landlock_applied=False','landlock_applied=False,syscall_profile_applied=True,native_vms_bytes=_native_vm')
        with Scratch() as scope:
            staged=image.build(scope.path,offline_software_approval(),profile=policy.PROFILE)
            root=staged['root'];work=scope.path/'native-work';work.mkdir(mode=0o700)
            (work/'native').mkdir(mode=0o700);(work/'tmp').mkdir(mode=0o700)
            run=owned_run([str(root/'runtime/bin/python3.12'),'-I','-B','-S','-c',program,str(root)],
                env=dict(LANG='C',PATH='/nonexistent',LD_LIBRARY_PATH=str(root/'runtime/lib')),timeout=15)
            self.assertEqual(run.returncode,0,run.stderr)
            row=json.loads(run.stdout)
            self.assertEqual((row['decoder_workers'],row['history_workers']),(2,1))
            self.assertTrue(row['tracker_reaped'] and row['owner_thread_joined'] and row['original_history_limits'])
            self.assertTrue(row['syscall_profile_applied'])
            self.assertFalse(row['financial_authority'] or row['landlock_applied'])
            self.assertEqual(row['provider_calls'],0)
            self.assertGreater(row['native_vms_bytes'],0)
            print(json.dumps(dict(schema='offline-native-syscall-component-v1',
                source_commit=staged['manifest']['source_commit'],source_tree=staged['manifest']['source_tree'],
                image_manifest_sha256=staged['manifest_sha256'],actual=row),sort_keys=True))
            scope.check();scope.success=True

    def test_unchanged_history_initializer_retains_actual_limits_and_nice_under_filter(self):
        program=r'''
import ctypes,errno,json,os,resource,sys
sys.path[:0]=[sys.argv[1],sys.argv[2]]
from meme_machine.operational.native_landlock_policy import NativePolicy
from meme_machine.solana_history_work import _isolated_worker_limits
assert os.getpriority(os.PRIO_PROCESS,0)==0
resource.setrlimit(resource.RLIMIT_AS,(2*1024**3,2*1024**3))
_,hard=resource.getrlimit(resource.RLIMIT_NOFILE)
ceiling=min(65536,hard) if hard!=resource.RLIM_INFINITY else 65536
resource.setrlimit(resource.RLIMIT_NOFILE,(ceiling,ceiling))
kernel=NativePolicy()
kernel.call(157,ctypes.c_int(38),ctypes.c_ulong(1),ctypes.c_ulong(0),ctypes.c_ulong(0),ctypes.c_ulong(0),code='fixture_nnp')
kernel.seccomp();_isolated_worker_limits()
assert resource.getrlimit(resource.RLIMIT_AS)==(512*1024**2,512*1024**2)
assert resource.getrlimit(resource.RLIMIT_NOFILE)==(128,128)
assert os.getpriority(os.PRIO_PROCESS,0)==5
limit=(ctypes.c_ulong*2)(0,0)
for args in ((302,os.getppid(),resource.RLIMIT_AS,0,ctypes.byref(limit)),
 (302,0,resource.RLIMIT_CORE,ctypes.byref(limit),0),
 (141,os.PRIO_PROCESS,0,0),(141,os.PRIO_PGRP,0,5),(144,0,os.SCHED_OTHER,ctypes.byref(limit))):
 ctypes.set_errno(0)
 assert kernel.libc.syscall(*args)==-1 and ctypes.get_errno()==errno.EPERM,args
try:resource.setrlimit(resource.RLIMIT_AS,(1024**3,1024**3))
except (ValueError,PermissionError):pass
else:raise AssertionError('original hard AS protection raised')
os.write(1,b'{"actual_history_limits":true,"landlock_verified":false}\n')
'''
        with Scratch() as scope:
            done=subprocess.run([sys.executable,'-I','-B','-S','-c',program,
                str(Path(__file__).resolve().parents[1]),str(Path(sys.prefix)/'lib/python3.12/site-packages')],stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=10)
            self.assertEqual(done.returncode,0,done.stderr.decode(errors='replace'))
            self.assertEqual(json.loads(done.stdout),dict(actual_history_limits=True,landlock_verified=False))
            scope.check();scope.success=True

    def test_actual_threads_socketpair_and_sqlite_full_under_default_deny_filter(self):
        # A syscall-policy fixture only: this does not fake a successful
        # Landlock syscall, copied image or provider/native acceptance result.
        program=r'''
import ctypes,errno,json,os,signal,socket,sqlite3,sys,threading
sys.path.insert(0,sys.argv[1])
from meme_machine.operational.native_landlock_policy import NativePolicy
kernel=NativePolicy()
kernel.call(157,ctypes.c_int(38),ctypes.c_ulong(1),ctypes.c_ulong(0),ctypes.c_ulong(0),ctypes.c_ulong(0),code='fixture_nnp')
kernel.seccomp()
try:socket.socket(socket.AF_INET,socket.SOCK_STREAM)
except OSError as error:assert error.errno==errno.EPERM
else:raise AssertionError('external socket admitted')
left,right=socket.socketpair()
left.settimeout(1);right.settimeout(1)
thread=threading.Thread(target=lambda:left.sendall(b'fixed native bytes'))
thread.start();assert right.recv(32)==b'fixed native bytes';thread.join(1);assert not thread.is_alive()
left.close();right.close()
db=sqlite3.connect(sys.argv[2]);assert db.execute('PRAGMA journal_mode=WAL').fetchone()[0]=='wal'
db.execute('PRAGMA synchronous=FULL');db.execute('CREATE TABLE native_fixture(value)')
db.execute('INSERT INTO native_fixture VALUES(1)');db.commit();assert db.execute('SELECT value FROM native_fixture').fetchone()==(1,)
db.close();os.write(1,b'{"syscall_fixture":"PASS","landlock_verified":false}\n')
'''
        with Scratch() as scope:
            done=subprocess.run([sys.executable,'-I','-B','-S','-c',program,
                str(Path(__file__).resolve().parents[1]),str(scope.path/'native.sqlite')],
                stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=10)
            self.assertEqual(done.returncode,0,done.stderr.decode(errors='replace'))
            self.assertEqual(done.stdout,b'{"syscall_fixture":"PASS","landlock_verified":false}\n')
            scope.check();scope.success=True


if __name__=='__main__':unittest.main()
