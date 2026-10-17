"""Offline contract tests; no repeated actual-kernel capability probe."""
import ctypes
import errno
import json
import os
from pathlib import Path
import socket
import signal
import struct
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from meme_machine.operational import landlock_canary as ll
from meme_machine.operational.artifact_storage import Scratch


def evaluate(number,args=(),arch=0xc000003e):
    """Interpret the generated classic-BPF filter, including branch offsets."""
    memory=struct.pack('<IIQ6Q',number,arch,0,*(tuple(args)+(0,)*(6-len(args))))
    rows=ll._filter();accumulator=0;pc=0
    for _ in range(4096):
        code,jt,jf,value=rows[pc];pc+=1
        if code==0x20:accumulator=struct.unpack_from('<I',memory,value)[0]
        elif code==0x15:pc+=jt if accumulator==value else jf
        elif code==0x35:pc+=jt if accumulator>=value else jf
        elif code==0x45:pc+=jt if accumulator&value else jf
        elif code==0x54:accumulator&=value
        elif code==0x06:return value
        else:raise AssertionError('unreviewed filter opcode')
    raise AssertionError('filter did not terminate')


def passing():
    return dict(ll._base('LANDLOCK_CANARY_ENFORCEMENT_VERIFIED'),landlock_abi=6,
        checks={key:True for key in ll.CHECKS})


class LandlockCanaryTests(unittest.TestCase):
    def test_filter_covers_every_denied_syscall_and_architecture(self):
        for number in ll._DENIED:
            with self.subTest(number=number):self.assertEqual(evaluate(number),0x50000|errno.EPERM)
        for number in (451,512,0x40000000,0x40000029):
            self.assertEqual(evaluate(number),0x50000|errno.EPERM)
        self.assertEqual(evaluate(1,arch=0x40000003),0x80000000)
        self.assertEqual(evaluate(435),0x50000|errno.ENOSYS)
        self.assertEqual(evaluate(1),0x7fff0000)

    def test_filter_allows_only_unnamed_stream_pairs_and_connected_writes(self):
        allow=0x7fff0000;deny=0x50000|errno.EPERM
        for flags in (0,socket.SOCK_CLOEXEC,socket.SOCK_NONBLOCK,
                      socket.SOCK_CLOEXEC|socket.SOCK_NONBLOCK):
            self.assertEqual(evaluate(53,(socket.AF_UNIX,socket.SOCK_STREAM|flags,0)),allow)
        for args in ((socket.AF_INET,socket.SOCK_STREAM,0),
                (socket.AF_UNIX,socket.SOCK_DGRAM,0),(socket.AF_UNIX,socket.SOCK_SEQPACKET,0),
                (socket.AF_UNIX,socket.SOCK_STREAM|0x10000,0),(socket.AF_UNIX,socket.SOCK_STREAM,1)):
            self.assertEqual(evaluate(53,args),deny)
        self.assertEqual(evaluate(44,(3,0,0,0,0,0)),allow)
        self.assertEqual(evaluate(44,(3,0,0,0,1,0)),deny)
        self.assertEqual(evaluate(44,(3,0,0,0,1<<32,0)),deny)

    def test_filter_preserves_fork_threads_and_only_fixed_prctl_operations(self):
        allow=0x7fff0000;deny=0x50000|errno.EPERM
        self.assertEqual(evaluate(56,(17,)),allow)
        self.assertEqual(evaluate(56,(0x3d0f00,)),allow)
        for flag in (0x80,0x20000,0x2000000,0x4000000,0x8000000,0x10000000,0x20000000,0x40000000):
            self.assertEqual(evaluate(56,(flag|17,)),deny)
        for operation in (3,39):self.assertEqual(evaluate(157,(operation,)),allow)
        self.assertEqual(evaluate(157,(1,signal.SIGKILL,0,0,0)),allow)
        for operation in (1,4,22,24,38):self.assertEqual(evaluate(157,(operation,)),deny)
        for death_signal in (0,signal.SIGTERM,signal.SIGKILL+(1<<32)):
            self.assertEqual(evaluate(157,(1,death_signal,0,0,0)),deny)
        for index in (2,3,4):
            for value in (1,1<<32):
                args=[1,signal.SIGKILL,0,0,0];args[index]=value
                self.assertEqual(evaluate(157,args),deny)
        # Kill is deliberately not seccomp-denied: the pre-seccomp Landlock
        # SIGNAL-scope check cannot be masked by this filter.
        self.assertEqual(evaluate(62,(123,10)),allow)

    def test_abi_failures_retain_observed_number_without_fallback(self):
        kernel=object.__new__(ll.Kernel)
        for value in range(6):
            with patch.object(kernel,'call',return_value=value):
                with self.assertRaises(ll.Blocked) as caught:kernel.abi()
            self.assertEqual(caught.exception.code,'landlock_canary_abi_too_old')
            self.assertEqual(caught.exception.abi,value)
        with patch.object(kernel,'call',return_value=6):self.assertEqual(kernel.abi(),6)
        with patch.object(kernel,'call',side_effect=ll.Blocked('landlock_canary_abi_unavailable',38)):
            with self.assertRaises(ll.Blocked) as caught:kernel.abi()
        self.assertEqual(caught.exception.number,38)

    def test_ruleset_contains_all_known_fs_rights_and_both_scopes(self):
        kernel=object.__new__(ll.Kernel);calls=[]
        def call(number,*args,code):
            if number==444:
                attrs=ctypes.cast(args[0],ctypes.POINTER(ll._Ruleset)).contents
                calls.append((number,attrs.fs,attrs.net,attrs.scoped,args[1].value));return 99
            if number==445:
                attrs=ctypes.cast(args[2],ctypes.POINTER(ll._PathRule)).contents
                calls.append((number,attrs.fd,attrs.access))
            else:calls.append((number,code))
            return 0
        with patch.object(kernel,'call',side_effect=call),patch.object(ll.os,'close') as close:
            kernel.restrict(10,11)
        self.assertIn((444,(1<<16)-1,0,3,24),calls)
        self.assertIn((445,10,(1<<2)|(1<<0)),calls)
        self.assertIn((445,11,ll.WORK),calls)
        self.assertEqual(ll.WORK&((1<<0)|(1<<6)|(1<<11)|(1<<15)),0)
        close.assert_called_once_with(99)

    def test_receipt_rejects_missing_partial_and_nonzero_exit(self):
        for change in ({'checks':{}},{'checks':dict.fromkeys(ll.CHECKS,1)},
                       {'landlock_abi':True},{'landlock_abi':5},{'private_shm':True},
                       {'provider_calls':False},{'financial_authority':True}):
            self.assertEqual(ll._project(dict(passing(),**change),0)['state'],'BLOCKED')
        for exit_code in (1,2,-9,None,False):
            self.assertEqual(ll._project(passing(),exit_code)['state'],'BLOCKED')
        value=ll._project(passing(),0)
        self.assertFalse(ll.verified(value))
        value.update(dict.fromkeys(ll.PARENT_CHECKS,True))
        self.assertTrue(ll.verified(value))

    def test_negative_privacy_canaries_are_never_published(self):
        secret='PRIVATE_ENDPOINT_CANARY_12345'
        for value in (dict(passing(),body=secret),dict(passing(),checks={secret:True}),
                dict(ll._base(),code=secret,error_number=secret),
                dict(ll._base(),code=['landlock_canary_abi_unavailable'],details=secret),
                dict(ll._base(),code='landlock_canary_abi_unavailable',error_number=38,body=secret)):
            projected=ll._project(value,2)
            self.assertNotIn(secret,json.dumps(projected))
            self.assertEqual(projected['state'],'BLOCKED')
        error=ll._project(dict(ll._base(),code='landlock_canary_abi_unavailable',error_number=38),2)
        self.assertEqual(error['code'],'landlock_canary_abi_unavailable')
        self.assertEqual(error['error_number'],38)

    def test_failure_inside_channel_is_reported_before_close(self):
        parent,child=socket.socketpair()
        with parent,child,patch.object(ll,'_ALREADY_REPORTED',False),\
                patch.object(ll,'_OBSERVED_ABI',6):
            with self.assertRaises(ll.Blocked):
                with ll._ReportChannel(child):
                    raise ll.Blocked('landlock_canary_ruleset_refused',errno.EPERM)
            self.assertEqual(child.fileno(),-1)
            parent.settimeout(1)
            projected=ll._project(json.loads(parent.recv(ll.MAX_RESULT)),2)
            self.assertEqual(projected['code'],'landlock_canary_ruleset_refused')
            self.assertEqual(projected['error_number'],errno.EPERM)
            self.assertEqual(projected['landlock_abi'],6)
            self.assertTrue(ll._ALREADY_REPORTED)

    def test_failure_projection_preserves_fixed_stage_errno_and_partial_checks_only(self):
        secret='PRIVATE_PATH_OR_PROVIDER_CANARY'
        class PrivateFailure(OSError):pass
        error=PrivateFailure(errno.EACCES,secret,secret)
        fields=ll.failure_fields(error,'controller_snapshots')
        self.assertEqual(fields,dict(code='landlock_canary_probe_failed',
            stage='controller_snapshots',error_class='OSError',error_number=errno.EACCES))
        self.assertNotIn(secret,json.dumps(fields))
        with patch.object(ll,'_PROBE_STAGE','child_landlock_checks'),\
                patch.object(ll,'_PROBE_CHECKS',dict(fs_read=True,fs_write=False)),\
                patch.object(ll,'_OBSERVED_ABI',6):
            value=ll._failure(PermissionError(errno.EPERM,secret,secret))
        projected=ll._project(dict(value,body=secret),2)
        self.assertEqual(projected['checks'],dict(fs_read=True,fs_write=False))
        self.assertEqual(projected['stage'],'child_landlock_checks')
        self.assertEqual(projected['error_class'],'PermissionError')
        self.assertEqual(projected['error_number'],errno.EPERM)
        self.assertEqual(projected['landlock_abi'],6)
        self.assertEqual(projected['child_exit'],2)
        malformed=ll._project(dict(value,stage=secret,error_class=secret,
            checks={secret:True,'fs_write':1}),2)
        self.assertNotIn(secret,json.dumps(malformed))
        self.assertEqual(malformed['checks'],{})

    def test_preprobe_snapshot_failure_is_bounded_instead_of_escaping_to_driver(self):
        with Scratch() as scope,patch.object(ll.os,'geteuid',return_value=1000),\
                patch.object(ll,'_scratch',return_value=scope.path),\
                patch.object(ll.os,'readlink',side_effect=PermissionError(errno.EACCES,'private path')):
            result=ll.canary(scope.path)
            self.assertEqual(result['state'],'BLOCKED')
            self.assertEqual(result['stage'],'controller_snapshots')
            self.assertEqual(result['error_class'],'PermissionError')
            self.assertEqual(result['error_number'],errno.EACCES)
            self.assertNotIn('child_exit',result)
            self.assertNotIn('landlock_abi',result)
            self.assertNotIn('private path',json.dumps(result))
            scope.success=True

    def controller_fixture(self,scope,payload,exit_code=2):
        """Real anonymous IPC/process cleanup, never any policy syscall."""
        original=subprocess.Popen
        def start(args,**kwargs):
            if '--probe' in args:
                spec=json.loads(args[-1])
                script=('import os;os.write('+str(spec['ipc'])+','+repr(payload)+');'
                    'os._exit('+str(exit_code)+')')
                return original([sys.executable,'-I','-B','-S','-c',script],**kwargs)
            return original(args,**kwargs)
        return (patch.object(ll,'_scratch',return_value=scope.path),
            patch.object(ll.os,'geteuid',side_effect=[1000,os.geteuid()]),
            patch.object(ll.subprocess,'Popen',side_effect=start))

    def test_empty_child_receipt_retains_real_exit_and_decode_stage(self):
        with Scratch() as scope:
            first,second,third=self.controller_fixture(scope,b'',3)
            with first,second,third:result=ll.canary(scope.path)
            self.assertEqual(result['state'],'BLOCKED')
            self.assertEqual(result['stage'],'controller_child_receipt')
            self.assertEqual(result['error_class'],'JSONDecodeError')
            self.assertEqual(result['child_exit'],3)
            self.assertNotIn('landlock_abi',result)
            self.assertTrue(all(result[key] is True for key in ll.PARENT_CHECKS))
            scope.check();scope.success=True

    def test_postprobe_failure_retains_real_child_partial_receipt(self):
        value=dict(ll._base(),code='landlock_canary_denial_errno',landlock_abi=6,
            error_number=errno.ENOENT,failed_check='proc_data',checks={'fs_read':True},
            stage='child_landlock_checks',error_class='Blocked')
        payload=json.dumps(value).encode()+b'\n'
        for failure in ('parent_namespaces','cleanup'):
            with self.subTest(failure=failure),Scratch() as scope:
                first,second,third=self.controller_fixture(scope,payload)
                original_link=os.readlink;original_close=ll._OwnedProcesses.close;calls=0
                def readlink(path):
                    nonlocal calls
                    if path.startswith('/proc/self/ns/'):
                        calls+=1
                        if calls>5:raise PermissionError(errno.EACCES,'private namespace path')
                    return original_link(path)
                def close(owner):
                    original_close(owner)
                    raise PermissionError(errno.EPERM,'private cleanup path')
                target=(patch.object(ll.os,'readlink',side_effect=readlink)
                    if failure=='parent_namespaces' else patch.object(ll._OwnedProcesses,'close',close))
                with first,second,third,target:result=ll.canary(scope.path)
                self.assertEqual(result['state'],'BLOCKED')
                self.assertEqual(result['stage'],'controller_'+failure)
                self.assertEqual(result['error_class'],'PermissionError')
                self.assertEqual(result['child_exit'],2)
                self.assertEqual(result['landlock_abi'],6)
                self.assertEqual(result['checks'],{'fs_read':True})
                self.assertEqual(result['failed_check'],'proc_data')
                self.assertEqual(result['child_failure'],dict(code='landlock_canary_denial_errno',
                    error_number=errno.ENOENT,failed_check='proc_data',
                    stage='child_landlock_checks',error_class='Blocked'))
                self.assertNotIn('private ',json.dumps(result))
                scope.check();scope.success=True

    def test_exact_retained_aws_path_exceeds_sockaddr_un_before_any_syscall(self):
        address=('/opt/mm-admin-runner/_work/_temp/mm-landlock-stage-39070091108-a01p34ro/'
            'mm-engineering-ju5ql__h/outside.sock')
        self.assertEqual(len(os.fsencode(address)),108)
        # CPython checks sun_path before bind(2): no host pathname is touched.
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as listener:
            with self.assertRaises(OSError) as caught:listener.bind(address)
        self.assertIsNone(caught.exception.errno)

    def test_real_long_path_child_socket_fixtures_keep_cwd_environment_and_fds(self):
        with Scratch() as scope:
            work=scope.path/('private-fixture-'+'x'*120);work.mkdir(mode=0o700)
            self.assertGreater(len(os.fsencode(work/'bound.sock')),107)
            before=ll._fd_snapshot();cwd=Path.cwd();temporary=os.environ.get('TMPDIR')
            with ll._socket_fixtures(work) as (loose,bound,listener,pair,denied):
                for address in (bound.getsockname(),listener.getsockname(),denied):
                    self.assertLess(len(os.fsencode(address)),108)
                self.assertTrue((work/'bound.sock').is_socket())
                self.assertTrue((work/'listener.sock').is_socket())
                loose.connect(listener.getsockname())
                accepted,_=listener.accept()
                with accepted:
                    loose.sendall(b'pathname fixture')
                    self.assertEqual(accepted.recv(32),b'pathname fixture')
                self.assertEqual(pair[1].recv(1),b'x')
            self.assertEqual(ll._fd_snapshot(),before)
            self.assertEqual(Path.cwd(),cwd)
            self.assertEqual(os.environ.get('TMPDIR'),temporary)
            scope.check();scope.success=True

    def test_long_path_controller_reaches_real_child_without_inheriting_directory_fd(self):
        with Scratch() as outer:
            parent=outer.path/('private-stage-'+'x'*100);parent.mkdir(mode=0o700)
            with Scratch(parent=parent) as scope:
                self.assertGreater(len(os.fsencode(scope.path/'outside.sock')),107)
                before=ll._fd_snapshot();cwd=Path.cwd();temporary=os.environ.get('TMPDIR')
                original=subprocess.Popen
                value=dict(ll._base(),code='landlock_canary_probe_failed')
                payload=json.dumps(value).encode()+b'\n'
                def start(args,**kwargs):
                    if '--probe' not in args:return original(args,**kwargs)
                    spec=json.loads(args[-1]);fd=spec['scope_fd']
                    self.assertFalse(os.get_inheritable(fd))
                    self.assertNotIn(fd,kwargs['pass_fds'])
                    # Derive as the child does; /proc/self here would refer to
                    # the fixture child rather than the controller's directory.
                    address='/proc/'+str(spec['parent'])+'/fd/'+str(fd)+'/outside.sock'
                    self.assertLess(len(os.fsencode(address)),108)
                    script=('import errno,os,socket;'
                        'closed=False;\n'
                        'try:os.fstat('+str(fd)+')\n'
                        'except OSError as e:closed=e.errno==errno.EBADF\n'
                        'assert closed\n'
                        's=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);'
                        's.connect('+repr(address)+');s.close();'
                        'os.write('+str(spec['ipc'])+','+repr(payload)+');os._exit(2)')
                    return original([sys.executable,'-I','-B','-S','-c',script],**kwargs)
                with patch.object(ll,'_scratch',return_value=scope.path),\
                        patch.object(ll.os,'geteuid',side_effect=[1000,os.geteuid()]),\
                        patch.object(ll.subprocess,'Popen',side_effect=start):
                    result=ll.canary(scope.path)
                self.assertEqual(result['child_exit'],2)
                self.assertTrue(all(result[key] is True for key in ll.PARENT_CHECKS))
                self.assertTrue((scope.path/'outside.sock').is_socket())
                self.assertEqual(ll._fd_snapshot(),before)
                self.assertEqual(Path.cwd(),cwd)
                self.assertEqual(os.environ.get('TMPDIR'),temporary)
                scope.check();scope.success=True
            outer.check();outer.success=True

    def test_child_fixture_partial_setup_closes_its_directory_and_socket_descriptors(self):
        for method in ('bind','listen'):
            with self.subTest(method=method),Scratch() as scope:
                before=ll._fd_snapshot()
                with patch.object(socket.socket,method,side_effect=OSError(errno.EPERM,'fixed failure')):
                    with self.assertRaises(OSError):
                        with ll._socket_fixtures(scope.path):self.fail('unexpected fixture')
                self.assertEqual(ll._fd_snapshot(),before)
                scope.check();scope.success=True

    def test_directory_fixture_refuses_symlink_and_spec_refuses_fd_collisions(self):
        with Scratch() as scope:
            private=scope.path/'private';private.mkdir(mode=0o700)
            link=scope.path/'link';link.symlink_to(private,target_is_directory=True)
            before=ll._fd_snapshot()
            with self.assertRaises(OSError):
                with ll._fixture_directory(link):self.fail('unexpected symlink')
            self.assertEqual(ll._fd_snapshot(),before)
            row=dict(scope=str(private),parent=os.getpid(),peer=os.getpid()+1,
                ipc=9,facts=10,scope_fd=11,abstract='mm-landlock-canary-'+str(os.getpid()))
            self.assertEqual(ll._spec(row),row)
            for bad in (True,2,65536,9,10):
                with self.subTest(scope_fd=bad),self.assertRaises(ll.Blocked):
                    ll._spec(dict(row,scope_fd=bad))
            scope.check();scope.success=True

    def test_static_fixture_is_exact_bounded_executable(self):
        raw=ll._elf()
        self.assertEqual(len(raw),129)
        header=struct.unpack('<16sHHIQQQIHHHHHH',raw[:64])
        self.assertEqual(header[1:4],(2,62,1))
        self.assertEqual(header[4:6],(0x400078,64))
        self.assertEqual(raw[120:],b'\xb8\x3c\x00\x00\x00\x31\xff\x0f\x05')

    def test_unprivileged_capability_parser_fails_closed(self):
        valid=b'CapPrm:\t0000000000000000\nCapEff:\t0\nCapAmb:\t00\n'
        self.assertTrue(ll._empty_effective_caps(valid))
        for raw in (valid.replace(b'CapEff:\t0',b'CapEff:\t1'),
                valid.replace(b'CapAmb:\t00\n',b''),valid+b'CapEff:\t0\n',
                valid.replace(b'CapEff:\t0',b'CapEff:\tprivate'),valid+b'x'*65537):
            self.assertFalse(ll._empty_effective_caps(raw))

    def test_scope_validation_requires_admitted_private_empty_fresh_scope(self):
        with Scratch() as scope:
            self.assertEqual(ll._scratch(scope.path),scope.path)
            private=scope.path/'private';private.mkdir(mode=0o700)
            link=scope.path/'link';link.symlink_to(private,target_is_directory=True)
            with self.assertRaises(ll.Blocked):ll._private(link)
            (scope.path/'portfolio.sqlite').touch()
            with self.assertRaisesRegex(ll.Blocked,'financial_ancestor'):ll._private(private)
            scope.check();scope.success=True

    def test_actual_descriptor_closure_without_kernel_query(self):
        with Scratch() as scope:
            parent,child=socket.socketpair();read_fd,write_fd=os.pipe()
            script=('import os,socket,sys;sys.path.insert(0,'+
                repr(str(Path(ll.__file__).resolve().parents[2]))+');'
                'from meme_machine.operational.landlock_canary import _fixed_fds;'
                '_fixed_fds(int(sys.argv[1]),int(sys.argv[2]));'
                'assert os.read(4,8)==b"fixture";'
                'os.write(3,b"closed");os._exit(0)')
            try:
                os.write(write_fd,b'fixture');os.close(write_fd);write_fd=None
                with parent,child:
                    process=subprocess.Popen([sys.executable,'-I','-B','-S','-c',script,
                        str(child.fileno()),str(read_fd)],stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                        pass_fds=(child.fileno(),read_fd),env={})
                    child.close();parent.settimeout(5)
                    self.assertEqual(parent.recv(32),b'closed')
                    self.assertEqual(process.wait(timeout=5),0)
            finally:
                os.close(read_fd)
                if write_fd is not None:os.close(write_fd)
            scope.check();scope.success=True

    def failed_setup(self,scope,**patches):
        from contextlib import ExitStack
        before=ll._fd_snapshot()
        with ExitStack() as context:
            context.enter_context(patch.object(ll,'_scratch',return_value=scope.path))
            context.enter_context(patch.object(ll.os,'geteuid',side_effect=[1000,os.geteuid()]))
            for target,value in patches.items():context.enter_context(patch(target,**value))
            result=ll.canary(scope.path)
        self.assertEqual(result['state'],'BLOCKED')
        self.assertEqual(ll._fd_snapshot(),before)
        self.assertTrue(result['parent_open_descriptors_preserved'])
        scope.check();scope.success=True

    def test_setup_bind_and_listen_failure_close_every_owned_descriptor(self):
        for method in ('bind','listen'):
            with self.subTest(method=method),Scratch() as scope:
                self.failed_setup(scope,**{'socket.socket.'+method:
                    dict(side_effect=OSError(errno.EPERM,'fixed setup failure'))})

    def test_peer_spawn_failure_closes_both_fixture_pipe_ends(self):
        with Scratch() as scope:
            self.failed_setup(scope,**{'subprocess.Popen':
                dict(side_effect=OSError(errno.EAGAIN,'fixed spawn failure'))})

    def test_probe_spawn_failure_kills_and_reaps_already_owned_peer(self):
        from unittest.mock import Mock
        peer=Mock(pid=12345)
        with Scratch() as scope:
            self.failed_setup(scope,**{'subprocess.Popen':
                dict(side_effect=[peer,OSError(errno.EAGAIN,'fixed spawn failure')])})
        peer.kill.assert_called_once_with()
        peer.wait.assert_called_once()

    def test_exited_leader_stays_unreaped_until_owned_group_kill(self):
        from unittest.mock import Mock
        events=[]
        leader=Mock(pid=12345)
        leader.wait.side_effect=lambda **kw:events.append('reaped')
        owner=ll._OwnedProcesses();owner.probe=leader
        state=SimpleNamespace(si_pid=leader.pid,si_code=os.CLD_EXITED,si_status=0)
        with patch.object(ll.os,'waitid',return_value=state) as waitid,\
                patch.object(ll.os,'killpg',side_effect=lambda *args:events.append('group killed')) as killpg:
            ll._wait_unreaped(leader,0)
            leader.wait.assert_not_called();leader.poll.assert_not_called()
            owner.close()
        waitid.assert_called_once_with(os.P_PID,leader.pid,os.WEXITED|os.WNOHANG|os.WNOWAIT)
        killpg.assert_called_once_with(leader.pid,signal.SIGKILL)
        self.assertEqual(events,['group killed','reaped'])

    def test_controller_signal_handler_restores_previous_handlers_after_cleanup(self):
        previous={number:signal.getsignal(number) for number in (signal.SIGTERM,signal.SIGINT)}
        with self.assertRaisesRegex(ll.Blocked,'interrupted'):
            with ll._OwnerSignals() as owner:
                try:owner.interrupted(signal.SIGTERM,None)
                finally:
                    self.assertEqual(signal.getsignal(signal.SIGTERM),signal.SIG_IGN)
                    self.assertEqual(signal.getsignal(signal.SIGINT),signal.SIG_IGN)
        self.assertEqual({number:signal.getsignal(number) for number in previous},previous)

    def test_real_controller_term_reaps_its_separate_session_and_peer_without_policy_probe(self):
        # Only signal/ownership cleanup runs. No Landlock, seccomp, provider,
        # financial database, arbitrary native worker or copied image is used.
        script=r'''
import json,subprocess,sys,time
from contextlib import ExitStack
from meme_machine.operational.landlock_canary import _OwnerSignals,_OwnedProcesses,Blocked
children=_OwnedProcesses()
with _OwnerSignals():
    try:
        with ExitStack() as owned:
            owned.callback(children.close)
            children.peer=subprocess.Popen([sys.executable,'-c','import time;time.sleep(20)'])
            children.probe=subprocess.Popen([sys.executable,'-c','import time;time.sleep(20)'],start_new_session=True)
            print('ready',flush=True)
            while True:time.sleep(1)
    except Blocked as error:
        print(json.dumps(dict(code=error.code,probe=children.probe.returncode,peer=children.peer.returncode)),flush=True)
'''
        script = ('import sys;sys.path.insert(0,' +
            repr(str(Path(ll.__file__).resolve().parents[2])) + ');\n' + script)
        controller=subprocess.Popen([sys.executable,'-B','-c',script],
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            self.assertEqual(controller.stdout.readline().strip(),'ready')
            controller.send_signal(signal.SIGTERM)
            output,error=controller.communicate(timeout=3)
            self.assertEqual(controller.returncode,0,error)
            self.assertEqual(json.loads(output),dict(code='landlock_canary_interrupted',
                probe=-signal.SIGKILL,peer=-signal.SIGKILL))
        finally:
            if controller.poll() is None:controller.kill();controller.communicate(timeout=2)


if __name__=='__main__':unittest.main()
