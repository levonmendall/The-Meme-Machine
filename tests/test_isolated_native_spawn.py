"""Real unprivileged pre-Python fences; no Landlock/provider readiness claim."""
import copy
import hashlib
import json
import os
from pathlib import Path
import signal
import struct
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from meme_machine.operational.artifact_storage import Scratch
from meme_machine.operational import isolated_native_image as image
from meme_machine.operational import isolated_native_landlock_image as binding
from meme_machine.operational.isolated_native_layout import PROFILE
from meme_machine.runtime import isolated_native_spawn as spawn
from tests.test_isolated_native_landlock_image import fixture,bind,rewrite


def owned_run(args,*,timeout=8,env=None):
    """Retain leader unreaped until the disposable group has been killed."""
    process=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        env=env,start_new_session=True)
    deadline=time.monotonic()+timeout
    try:
        while os.waitid(os.P_PID,process.pid,os.WEXITED|os.WNOHANG|os.WNOWAIT) is None:
            if time.monotonic()>=deadline:raise TimeoutError('owned fixture deadline')
            time.sleep(.005)
    finally:
        try:os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        stdout,stderr=process.communicate(timeout=3)
    return subprocess.CompletedProcess(args,process.returncode,stdout.decode(),stderr.decode())


# Separate owned fixture process: subreaper changes never touch the test runner.
# SIGSTOP is before exec, so owner death precedes the shim's FIRST getppid.
_BEFORE_FIRST=r'''
import ctypes,fcntl,json,os,signal,sys
assert ctypes.CDLL(None,use_errno=True).prctl(36,1,0,0,0)==0
pipe=os.pipe2(os.O_CLOEXEC)
owner=os.fork()
if owner==0:
    os.close(pipe[0])
    r,w=os.pipe2(os.O_CLOEXEC)
    reader=fcntl.fcntl(r,fcntl.F_DUPFD_CLOEXEC,20)
    writer=fcntl.fcntl(w,fcntl.F_DUPFD_CLOEXEC,20)
    os.close(r);os.close(w);os.dup2(reader,5,inheritable=True);os.close(reader)
    child=os.fork()
    if child==0:
        os.close(writer);os.close(pipe[1])
        os.kill(os.getpid(),signal.SIGSTOP)
        os.execve(sys.argv[1],[sys.argv[1],'-c','raise AssertionError("unexpected exec")'],{})
    assert os.waitpid(child,os.WUNTRACED)[1]==(signal.SIGSTOP<<8)|0x7f
    os.write(pipe[1],str(child).encode());os._exit(0)
os.close(pipe[1]);child=int(os.read(pipe[0],64));os.close(pipe[0])
assert os.waitpid(owner,0)[1]==0
os.kill(child,signal.SIGCONT)
pid,status=os.waitpid(child,0)
assert pid==child and os.waitstatus_to_exitcode(status)==125,(pid,status)
try:os.waitpid(-1,os.WNOHANG)
except ChildProcessError:pass
else:raise AssertionError('unreaped fixture child')
print(json.dumps(dict(pre_first_instruction_owner_death=True,exit_code=125)))
'''


# Executed by the REAL copied CPython, with the common actual stdlib adapter.
# The host-authored fixture never supplies providers or a financial database.
_COPIED_SCOPE=r'''
import hashlib,json,os,signal,sys,threading,time
from pathlib import Path
root=Path(sys.argv[1]);work=root.parent/'native-work'
sys.path[:0]=[str(root/'app'),str(root/'deps')]
from meme_machine.operational.isolated_native_layout import NativeChildLayout,PROFILE
from meme_machine.runtime import isolated_native_spawn as spawn
from meme_machine.runtime.isolated_native_executor import IsolatedSpawnExecutor
from meme_machine.runtime.isolated_native_execution import install_isolated_native_execution
from meme_machine.runtime.isolated_native_resources import IsolatedNativeResources,AuthenticatedSizingFacts
from meme_machine.runtime.directional_sleeve import policies
from meme_machine.solana_evidence_service import source_decoder_probe
from meme_machine.solana_history_work import HistoryExecutor
import multiprocessing.resource_tracker as tracker
import multiprocessing.util as util
os.chdir(work/'native')
layout=NativeChildLayout(PROFILE,str(root),str(work),os.getppid(),hashlib.sha256((root/'manifest.json').read_bytes()).hexdigest())
# Fixed fixture stand-ins occupy external capability numbers; they are never
# passed to workers. Neither has provider, financial or directory authority.
assert os.open('/dev/null',os.O_RDONLY|os.O_CLOEXEC)==3
assert os.open('/dev/null',os.O_RDONLY|os.O_CLOEXEC)==4
original=util.spawnv_passfds
# Deliberate constructor failure after pipe creation must close both reserved
# FDs without modifying the common stdlib hook or starting an unowned thread.
factory=spawn.ThreadPoolExecutor
def fail_factory(**kwargs):raise RuntimeError('offline owner allocation failure')
spawn.ThreadPoolExecutor=fail_factory
try:
    try:spawn.NativeSpawnScope(layout)
    except RuntimeError as error:assert str(error)=='offline owner allocation failure'
    else:raise AssertionError('partial constructor accepted')
finally:spawn.ThreadPoolExecutor=factory
assert util.spawnv_passfds==original and spawn.current_spawn_scope() is None
for fd in (5,6):
    try:os.fstat(fd)
    except OSError:pass
    else:raise AssertionError('partial constructor FD leak')
calls=[]
def record(path,args,passfds):
    calls.append(dict(thread=threading.get_ident(),args=tuple(args),
        mask=signal.pthread_sigmask(signal.SIG_BLOCK,set()),passfds=tuple(passfds)))
    return original(path,args,passfds)
util.spawnv_passfds=record
scope=spawn.NativeSpawnScope(layout)
assert util.spawnv_passfds!=record
value=dict(schema='isolated-native-sizing-v1',scope='offline-spawn-fixture',source_commit='a'*40,
 source_tree='b'*40,epoch_reference='no-financial-epoch',portfolio_sequence=0,observed_at=1000,valid_until=1005,
 lanes={lane:dict(realized_equity=0,available=0,reserved=0,policies=policies(lane),
 native_unit='lamports' if lane=='pump' else 'wei',usd_evidence_hash='c'*64,
 valuation_observed_at=1000,valuation_valid_until=1000+(120 if lane=='pump' else 5)) for lane in ('pump','pons')})
facts=AuthenticatedSizingFacts(value,authenticate=lambda candidate:candidate==value)
resources=IsolatedNativeResources(layout.state_directory,sizing_facts=facts,clock=lambda:1000)
scope.register_source(resources)
decoder=IsolatedSpawnExecutor(max_workers=2,initializer=install_isolated_native_execution,role='decoder')
history=HistoryExecutor(native_resources=resources)
jobs=[];errors=[]
def short_lived_submitter():
    try:
        signal.pthread_sigmask(signal.SIG_BLOCK,{signal.SIGUSR1})
        jobs.extend([decoder.submit(source_decoder_probe),history.submit(source_decoder_probe)])
    except BaseException as error:errors.append(error)
thread=threading.Thread(target=short_lived_submitter)
thread.start();thread.join()
assert not errors,errors
# PDEATHSIG follows the creating THREAD. Exiting the submitting thread must
# not kill children: actual fork_exec ran on the retained dedicated owner.
assert all(job.result(5) is True for job in jobs)
time.sleep(.05)
history_pool=history.pool
assert len(decoder._processes)==2 and len(history_pool._processes)==1
assert all(p.is_alive() for pool in (decoder,history_pool) for p in pool._processes.values())
query="(lambda c:(lambda n:(c.CDLL(None).prctl(2,c.byref(n)),n.value)) (c.c_int()))(__import__('ctypes'))"
assert decoder.submit(eval,query).result(5)==(0,9)
assert history.submit(eval,query).result(5)==(0,9)
limits="(lambda r,o:(r.getrlimit(r.RLIMIT_AS),r.getrlimit(r.RLIMIT_NOFILE),o.getpriority(o.PRIO_PROCESS,0)))(__import__('resource'),__import__('os'))"
assert history.submit(eval,limits).result(5)==((512*1024**2,512*1024**2),(128,128),os.getpriority(os.PRIO_PROCESS,0)+5)
tracker_pid=tracker._resource_tracker._pid
assert tracker_pid==scope._tracker_pid and tracker_pid is not None
assert scope._owner_ident!=thread.ident and not scope.owners_joined
assert len(calls)==4 and all(call['thread']==scope._owner_ident for call in calls)
assert all(5 in call['passfds'] and not {3,4,6}.intersection(call['passfds']) for call in calls)
for call in calls:
    is_tracker=any(b'resource_tracker import main' in os.fsencode(arg) for arg in call['args'])
    assert call['mask']==({signal.SIGUSR1,signal.SIGTERM,signal.SIGINT} if is_tracker else {signal.SIGUSR1}),call
assert decoder.submit(eval,"{int(x) for x in __import__('signal').pthread_sigmask(0,set())}").result(5)=={int(signal.SIGUSR1)}
assert decoder.kernel_lifecycle_snapshot()==dict(state='UNJOINED')
# The source registry, not an arbitrary caller, is the actual close owner.
history.close();decoder.shutdown(wait=True,cancel_futures=True)
assert all(not p.is_alive() for pool in (decoder,history_pool) for p in pool._processes.values())
assert all(not t.is_alive() for pool in (decoder,history_pool) for t in pool._threads)
for role,pool,count in (('decoder',decoder,2),('history',history_pool,1)):
    summary=pool.kernel_lifecycle_snapshot()
    assert summary['state']=='JOINED' and summary['spawned']==summary['joined']==summary['zero_exit']==count,summary
    assert summary['returned']==summary['successful']==summary['submitted']==3,summary
    assert summary['probe_successful']==1 and summary['nonprobe_successful']==2 and summary['broken'] is False,summary
    scope.record_kernel_executor(role,summary)
scope.close()
assert scope.owners_joined and tracker._resource_tracker._pid is None
summary=scope.kernel_lifecycle_snapshot()
assert summary['state']=='JOINED' and summary['workers_spawned']==dict(decoder=2,history=1),summary
assert summary['tracker_spawned'] and summary['tracker_joined'] and summary['spawn_owner_joined'],summary
assert all(row['probe_successful']==1 and row['successful']==3 for row in summary['executors'].values()),summary
assert util.spawnv_passfds==record and spawn.current_spawn_scope() is None
util.spawnv_passfds=original
for fd in (5,6):
    try:os.fstat(fd)
    except OSError:pass
    else:raise AssertionError('lifeline leaked')
try:os.waitpid(tracker_pid,os.WNOHANG)
except ChildProcessError:pass
else:raise AssertionError('tracker not reaped')
resources.close();os.close(3);os.close(4)
print(json.dumps(dict(actual_copied_python=True,decoder_workers=2,history_workers=1,
 tracker_reaped=True,submitting_thread_exited=True,owner_thread_joined=True,
 worker_pdeathsig=9,original_history_limits=True,financial_authority=False,
 provider_calls=0,landlock_applied=False)))
'''


_RAW_STATES=r'''
import fcntl,json,os,sys
results={}
for mode in ('live','missing','regular','writer','data','hup'):
    r,w=os.pipe2(os.O_CLOEXEC)
    reader=fcntl.fcntl(r,fcntl.F_DUPFD_CLOEXEC,20)
    writer=fcntl.fcntl(w,fcntl.F_DUPFD_CLOEXEC,20)
    os.close(r);os.close(w)
    if mode=='data':os.write(writer,b'unexpected')
    if mode=='hup':os.close(writer);writer=None
    child=os.fork()
    if child==0:
        if mode!='missing':
            fd=(os.open(sys.argv[2],os.O_RDONLY|os.O_CLOEXEC) if mode=='regular'
                else writer if mode=='writer' else reader)
            os.dup2(fd,5,inheritable=True)
            if fd not in (reader,writer,5):os.close(fd)
        os.close(reader)
        if writer is not None:os.close(writer)
        os.execve(sys.argv[1],[sys.argv[1],'-I','-B','-S','-c','raise SystemExit(42)'],
            {'LANG':'C','PATH':'/nonexistent','LD_LIBRARY_PATH':sys.argv[3]})
    os.close(reader)
    status=os.waitpid(child,0)[1]
    if writer is not None:os.close(writer)
    results[mode]=os.waitstatus_to_exitcode(status)
assert results==dict(live=42,missing=125,regular=125,writer=125,data=125,hup=125),results
print(json.dumps(results))
'''


_IMPORT_DEATH=r'''
import ctypes,json,os,select,signal,sys
assert ctypes.CDLL(None,use_errno=True).prctl(36,1,0,0,0)==0
owner_read,owner_write=os.pipe2(os.O_CLOEXEC)
ready_read,ready_write=os.pipe2(os.O_CLOEXEC)
owner=os.fork()
if owner==0:
    os.close(owner_read);os.close(ready_read)
    # Move the genuine status writer away from lifeline5 before duplication.
    import fcntl
    status=fcntl.fcntl(ready_write,fcntl.F_DUPFD_CLOEXEC,20)
    os.close(ready_write)
    r,w=os.pipe2(os.O_CLOEXEC)
    reader=fcntl.fcntl(r,fcntl.F_DUPFD_CLOEXEC,20)
    writer=fcntl.fcntl(w,fcntl.F_DUPFD_CLOEXEC,20)
    os.close(r);os.close(w);os.dup2(reader,5,inheritable=True);os.close(reader)
    child=os.fork()
    if child==0:
        os.close(writer);os.close(owner_write)
        os.set_inheritable(status,True)
        os.execve(sys.argv[1],[sys.argv[1],'-I','-B','-S','-c',
            "import sys;sys.path.insert(0,sys.argv[1]);import blocked_import",sys.argv[2],str(status)],
            {'LANG':'C','PATH':'/nonexistent','LD_LIBRARY_PATH':sys.argv[3]})
    os.close(status)
    os.write(owner_write,str(child).encode())
    signal.pause()
os.close(owner_write);os.close(ready_write)
child=int(os.read(owner_read,64));os.close(owner_read)
assert select.select([ready_read],[],[],5)[0], 'copied Python import did not start'
assert os.read(ready_read,16)==b'importing'
os.kill(owner,signal.SIGKILL);assert os.waitpid(owner,0)[0]==owner
pid,status=os.waitpid(child,0)
assert pid==child and os.waitstatus_to_exitcode(status)==-signal.SIGKILL,(pid,status)
os.close(ready_read)
try:os.waitpid(-1,os.WNOHANG)
except ChildProcessError:pass
else:raise AssertionError('unreaped fixture child')
print(json.dumps(dict(owner_death_during_python_import=True,signal=9)))
'''


class SpawnShimTests(unittest.TestCase):
    def test_owned_builder_intermediates_are_private_under_permissive_umask(self):
        with Scratch() as scope:
            previous=os.umask(0)
            try:
                writer=image._ImageWriter(scope.path/'native-image')
                writer.copy(b'fixture','a/b/c/module.py')
            finally:os.umask(previous)
            for name in ('','a','a/b','a/b/c'):
                self.assertEqual((writer.root/name).stat().st_mode&0o777,0o700)
            self.assertEqual((writer.root/'a/b/c/module.py').stat().st_mode&0o777,0o400)
            scope.check();scope.success=True

    def test_fixed_machine_code_static_elf_and_no_environment_selected_exec(self):
        self.assertEqual(hashlib.sha256(spawn._MACHINE).hexdigest(),
            'd14fe952caf0533b585a7755b877e77570d2635cedd2f0889cec002850393761')
        path=Path('/explicit/private/native-image/runtime/bin/python3.12')
        raw=spawn.trampoline(path)
        self.assertEqual(raw[-len(os.fsencode(path))-1:],os.fsencode(path)+b'\0')
        self.assertEqual(image.runtime._elf(raw),(None,[]))
        self.assertEqual(struct.unpack_from('<Q',raw,24)[0],0x4000b0)
        for name in ('/bin/python3.12','relative/native-image/runtime/bin/python3.12',
                '/private/native-image/../native-image/runtime/bin/python3.12'):
            with self.assertRaises(spawn.NativeSpawnRefused):spawn.trampoline(name)

    def test_shim_refuses_missing_readonly_lifeline_and_pre_first_instruction_owner_death(self):
        with Scratch() as scope:
            target=scope.path/'native-image/runtime/bin/python3.12'
            target.parent.mkdir(mode=0o700,parents=True)
            # Executable negative control: if the lifeline checks were bypassed
            # this fixed static target would exit42, not the expected125.
            header=bytearray(spawn.trampoline(target)[:176])
            terminal=bytes.fromhex('bf2a000000b83c0000000f05')
            struct.pack_into('<QQ',header,96,176+len(terminal),176+len(terminal))
            target.write_bytes(header+terminal);target.chmod(0o500)
            self.assertEqual(owned_run([str(target)]).returncode,42)
            shim=scope.path/'shim';shim.write_bytes(spawn.trampoline(target));shim.chmod(0o500)
            result=owned_run([str(shim)],timeout=5)
            self.assertEqual(result.returncode,125)
            run=owned_run([sys.executable,'-I','-B','-S','-c',_BEFORE_FIRST,str(shim)],timeout=8)
            self.assertEqual(run.returncode,0,run.stderr)
            self.assertTrue(json.loads(run.stdout)['pre_first_instruction_owner_death'])
            scope.check();scope.success=True

    def test_manifest_accepts_only_exact_generated_helper_bytes_and_exec_rule(self):
        for altered in (False,True):
            with self.subTest(altered=altered),Scratch() as scope:
                staged=fixture(scope.path);root=staged['root'];path=root/spawn.SHIM_PATH
                data=spawn.trampoline(root/'runtime/bin/python3.12')
                if altered:data=data[:-2]+b'x\0'
                path.write_bytes(data);path.chmod(0o500)
                rewrite(staged,lambda row: (row['files'].append(dict(path=spawn.SHIM_PATH,
                    bytes=len(data),sha256=hashlib.sha256(data).hexdigest())),
                    row.update(bytes=row['bytes']+len(data))))
                if altered:
                    with self.assertRaisesRegex(image.Refused,'spawn_shim'):bind(staged)
                else:
                    with bind(staged) as pinned:
                        rule=next(rule for rule in pinned.rules() if rule.name==spawn.SHIM_PATH)
                        self.assertEqual(rule.access,binding.READ_FILE|binding.EXECUTE)
                scope.check();scope.success=True

    def test_invalid_profile_refuses_before_build_or_source_access(self):
        with patch.object(image,'source_objects',side_effect=AssertionError('source accessed')):
            with self.assertRaisesRegex(image.Refused,'image_profile'):image.build('/unused',None,profile='other')


class ActualCopiedSpawnTests(unittest.TestCase):
    def test_actual_copied_runtime_spawn_tracker_lifetime_and_import_death(self):
        from tests.test_isolated_native_launcher import offline_software_approval
        with Scratch() as scope:
            approval=offline_software_approval();staged=image.build(scope.path,approval,profile=PROFILE)
            expected=copy.deepcopy(staged['manifest'])
            with binding.PinnedNativeImage(staged['root'],manifest_sha256=staged['manifest_sha256'],
                    approval=approval,authenticate_manifest=lambda row:row==expected,profile=binding.PROFILE) as pinned:
                self.assertTrue(any(row.name==spawn.SHIM_PATH and row.access&binding.EXECUTE for row in pinned.rules()))
            root=staged['root'];work=scope.path/'native-work';work.mkdir(mode=0o700)
            (work/'native').mkdir(mode=0o700);(work/'tmp').mkdir(mode=0o700)
            environment=dict(LANG='C',PATH='/nonexistent',LD_LIBRARY_PATH=str(root/'runtime/lib'))
            run=owned_run([str(root/'runtime/bin/python3.12'),'-I','-B','-S','-c',
                _COPIED_SCOPE,str(root)],env=environment,timeout=15)
            self.assertEqual(run.returncode,0,run.stderr)
            actual=json.loads(run.stdout);self.assertEqual(actual['decoder_workers'],2)
            self.assertEqual(actual['history_workers'],1);self.assertTrue(actual['tracker_reaped'])
            self.assertFalse(actual['landlock_applied']);self.assertFalse(actual['financial_authority'])
            run=owned_run([sys.executable,'-I','-B','-S','-c',_RAW_STATES,
                str(root/spawn.SHIM_PATH),str(root/'manifest.json'),str(root/'runtime/lib')],timeout=8)
            self.assertEqual(run.returncode,0,run.stderr)
            states=json.loads(run.stdout);self.assertEqual(states['live'],42)
            module=work/'tmp'/'blocked_import.py'
            module.write_text("import os,sys,time\nos.write(int(sys.argv[2]),b'importing')\ntime.sleep(30)\n")
            run=owned_run([sys.executable,'-I','-B','-S','-c',_IMPORT_DEATH,
                str(root/spawn.SHIM_PATH),str(work/'tmp'),str(root/'runtime/lib')],
                timeout=10)
            self.assertEqual(run.returncode,0,run.stderr)
            self.assertEqual(json.loads(run.stdout)['signal'],9)
            print(json.dumps(dict(schema='offline-copied-spawn-component-v1',
                source_commit=staged['manifest']['source_commit'],
                source_tree=staged['manifest']['source_tree'],
                image_manifest_sha256=staged['manifest_sha256'],actual=actual,
                lifeline_states=states,owner_death_during_python_import=True),sort_keys=True))
            scope.check();scope.success=True


class SpawnSourceOwnershipTests(unittest.IsolatedAsyncioTestCase):
    async def order(self,failed):
        from meme_machine import solana_evidence_service as service
        closed=[]
        class Owner:
            def __init__(self,name):self.name=name
            def close(self):
                closed.append(self.name)
                if self.name==failed:raise RuntimeError('offline close failure')
            def shutdown(self,*,wait,cancel_futures):
                assert wait and cancel_futures
                self.close()
        async def run(*args,_workers,**kwargs):
            _workers.update({name:Owner(name) for name in
                ('owner','delivery','history','decoder','checkpoint','spawn')})
        with patch.object(service,'_serve_owned',run):
            if failed:
                with self.assertRaisesRegex(RuntimeError,'offline close failure'):
                    await service.serve('/never-opened',None)
            else:await service.serve('/never-opened',None)
        return closed

    async def test_tracker_and_retained_thread_close_only_after_all_native_workers_join(self):
        self.assertEqual(await self.order(None),
            ['owner','delivery','history','decoder','checkpoint','spawn'])

    async def test_failed_native_join_retains_spawning_thread_for_fixed_entry_fatal_handoff(self):
        self.assertEqual(await self.order('history'),
            ['owner','delivery','history','decoder','checkpoint'])


if __name__=='__main__':unittest.main()
