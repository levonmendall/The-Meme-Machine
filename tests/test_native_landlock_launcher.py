"""Actual disposable owned-process lifetime; no claimed Landlock/provider PASS."""
import json
from pathlib import Path
import subprocess
import sys
import unittest

from meme_machine.operational.artifact_storage import Scratch


class NativeLandlockLifetimeTests(unittest.TestCase):
    def run_fixture(self,body):
        with Scratch() as scope:
            done=subprocess.run([sys.executable,'-I','-B','-S','-c',body,
                str(Path(__file__).resolve().parents[1])],cwd=scope.path,
                stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=10)
            self.assertEqual(done.returncode,0,done.stderr.decode(errors='replace'))
            result=json.loads(done.stdout)
            self.assertIs(result['fixture_pass'],True)
            self.assertIs(result['landlock_verified'],False)
            scope.check();scope.success=True
            return result

    def test_exited_leader_keeps_pid_reserved_until_real_descendant_group_kill_then_reap(self):
        self.run_fixture(r'''
import ctypes,json,os,signal,subprocess,sys,time
sys.path.insert(0,sys.argv[1])
from meme_machine.operational.isolated_native_landlock_launcher import NativeLandlockChild
libc=ctypes.CDLL(None);assert libc.prctl(36,1,0,0,0)==0
code="""import ctypes,json,os,signal,sys,time
sys.path.insert(0,sys.argv[1])
from meme_machine.operational.isolated_native_landlock_launcher import _finish_descendants
assert ctypes.CDLL(None).prctl(36,1,0,0,0)==0
native=os.fork()
if native==0:
 child=os.fork()
 if child==0:
  signal.signal(signal.SIGTERM,signal.SIG_IGN)
  while True:time.sleep(1)
 print(json.dumps(dict(status='BLOCKED',financial_authority=False,descendant=child,
  graceful_shutdown=True,all_workers_joined=True)),flush=True)
 os._exit(0)
os.waitpid(native,0)
assert not _finish_descendants(seconds=.05)
os._exit(125)
"""
child=subprocess.Popen([sys.executable,'-I','-B','-S','-c',code,sys.argv[1]],stdin=subprocess.DEVNULL,
 stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
events=[];original_killpg=os.killpg;original_wait=child.wait
def killpg(pid,sig):events.append(('signal',sig));return original_killpg(pid,sig)
def wait(*a,**kw):events.append(('reap',None));return original_wait(*a,**kw)
os.killpg=killpg;child.wait=wait
owner=NativeLandlockChild(child,time.monotonic());receipt=owner.wait(seconds=2)
assert receipt['status']=='BLOCKED' and receipt['code']=='native_landlock_descendants_not_joined',receipt
assert receipt['graceful_shutdown'] is False and receipt['all_workers_joined'] is False
original=json.loads(bytes(owner.output['stdout']))
pid,status=os.waitpid(original['descendant'],0)
assert os.WIFSIGNALED(status) and os.WTERMSIG(status)==signal.SIGKILL
assert events[0]==('signal',signal.SIGKILL) and events[1][0]=='reap',events
assert not receipt['normal_readiness'] and not receipt['full_market_speed_proven']
print(json.dumps(dict(fixture_pass=True,landlock_verified=False)))
''')

    def test_fresh_subreaper_joins_actual_stdlib_tracker_on_original_owner_pipe_eof(self):
        self.run_fixture(r'''
import ctypes,json,os,sys
sys.path.insert(0,sys.argv[1])
from meme_machine.operational.isolated_native_landlock_launcher import _finish_descendants
libc=ctypes.CDLL(None);assert libc.prctl(36,1,0,0,0)==0
read,write=os.pipe()
native=os.fork()
if native==0:
 os.close(read)
 from multiprocessing import resource_tracker
 resource_tracker.ensure_running()
 os.write(write,str(resource_tracker._resource_tracker._pid).encode());os.close(write)
 os._exit(0)
os.close(write);raw=os.read(read,32);os.close(read)
assert raw.isdigit();tracker=int(raw)
pid,status=os.waitpid(native,0);assert os.WIFEXITED(status) and os.WEXITSTATUS(status)==0
assert _finish_descendants(), 'tracker did not exit cleanly on EOF'
try:os.waitpid(-1,os.WNOHANG)
except ChildProcessError:pass
else:raise AssertionError('adopted children still owned')
try:os.waitpid(tracker,os.WNOHANG)
except ChildProcessError:pass
else:raise AssertionError('tracker was not physically reaped')
print(json.dumps(dict(fixture_pass=True,landlock_verified=False)))
''')

    def test_uncooperative_owner_is_killed_and_reports_expired_not_success(self):
        self.run_fixture(r'''
import json,os,signal,subprocess,sys,time
sys.path.insert(0,sys.argv[1])
from meme_machine.operational.isolated_native_landlock_launcher import NativeLandlockChild
child=subprocess.Popen([sys.executable,'-I','-B','-S','-c',
 'import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(60)'],
 stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
owner=NativeLandlockChild(child,time.monotonic());receipt=owner.wait(seconds=.05)
assert receipt['status']=='BLOCKED' and receipt['code']=='native_landlock_shutdown_expired',receipt
assert child.returncode==-signal.SIGKILL and not owner._reader.is_alive()
print(json.dumps(dict(fixture_pass=True,landlock_verified=False)))
''')

    def test_original_stop_relay_preserves_real_accepted_worker_completion(self):
        self.run_fixture(r'''
import ctypes,json,os,signal,subprocess,sys,time
sys.path.insert(0,sys.argv[1])
from meme_machine.operational.isolated_native_landlock_launcher import NativeLandlockChild
ready_read,ready_write=os.pipe()
code="""import ctypes,json,os,signal,sys,time
sys.path.insert(0,sys.argv[1])
from meme_machine.operational.isolated_native_landlock_launcher import _NativeCancellation,_finish_descendants
assert ctypes.CDLL(None).prctl(36,1,0,0,0)==0
relay=_NativeCancellation();signal.signal(signal.SIGTERM,relay)
ready=int(sys.argv[2]);native=os.fork()
if native==0:
 stopped=[]
 signal.signal(signal.SIGTERM,lambda *args:stopped.append(True))
 read,write=os.pipe();worker=os.fork()
 if worker==0:
  signal.signal(signal.SIGTERM,signal.SIG_DFL);os.close(read);os.close(ready)
  os.write(write,b'1');time.sleep(.2);os.write(write,b'accepted-result');os.close(write);os._exit(0)
 os.close(write);assert os.read(read,1)==b'1';os.write(ready,b'1');os.close(ready)
 assert os.read(read,32)==b'accepted-result';os.close(read)
 pid,status=os.waitpid(worker,0);assert os.WIFEXITED(status) and os.WEXITSTATUS(status)==0
 assert stopped
 print(json.dumps(dict(status='COMPLETED',financial_authority=False,graceful_shutdown=True,all_workers_joined=True)),flush=True)
 os._exit(0)
relay.attach(native);os.close(ready);pid,status=os.waitpid(native,0)
assert _finish_descendants();os._exit(os.waitstatus_to_exitcode(status))
"""
child=subprocess.Popen([sys.executable,'-I','-B','-S','-c',code,sys.argv[1],str(ready_write)],
 stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True,pass_fds=(ready_write,))
os.close(ready_write);owner=NativeLandlockChild(child,time.monotonic())
assert os.read(ready_read,1)==b'1';os.close(ready_read)
receipt=owner.stop()
assert receipt['status']=='COMPLETED' and receipt['graceful_shutdown'] and receipt['all_workers_joined'],receipt
assert child.returncode==0
print(json.dumps(dict(fixture_pass=True,landlock_verified=False)))
''')

    def test_cancellation_before_fork_and_after_reap_preserves_kernel_pid_ownership(self):
        self.run_fixture(r'''
import json,os,signal,sys,time
sys.path.insert(0,sys.argv[1])
from meme_machine.operational.isolated_native_landlock_launcher import _NativeCancellation
signal.signal(signal.SIGTERM,signal.SIG_DFL)
read,write=os.pipe();relay=_NativeCancellation();relay()
native=os.fork()
if native==0:
 os.close(write);os.read(read,1);os._exit(99)
os.close(read);relay.attach(native)
pid,status=os.waitpid(native,0);os.close(write)
assert os.WIFSIGNALED(status) and os.WTERMSIG(status)==signal.SIGTERM
original=os.kill;called=[]
def kill(*args):called.append(args);return original(*args)
os.kill=kill;relay();assert called==[],called
print(json.dumps(dict(fixture_pass=True,landlock_verified=False)))
''')

    def test_inherited_supervisor_handler_cannot_consume_stop_before_native_reset(self):
        self.run_fixture(r'''
import json,os,signal,sys,time
sys.path.insert(0,sys.argv[1])
from meme_machine.operational.isolated_native_landlock_launcher import (
 _NativeCancellation,_reset_native_child_signals,NativePolicyBlocked)
gate_read,gate_write=os.pipe();ready_read,ready_write=os.pipe()
relay=_NativeCancellation();signal.signal(signal.SIGTERM,relay)
native=os.fork()
if native==0:
 os.close(gate_write);os.close(ready_read)
 # The forked relay has pid=None, exactly as in product setup. Keep this
 # actual inherited handler active until it records the parent's stop.
 os.write(ready_write,b'1')
 while not relay.requested:time.sleep(.001)
 os.write(ready_write,b'2');os.close(ready_write)
 assert os.read(gate_read,1)==b'1';os.close(gate_read)
 try:_reset_native_child_signals(relay)
 except NativePolicyBlocked as error:
  assert error.code=='native_landlock_cancelled_before_entry';os._exit(0)
 os._exit(99)
os.close(gate_read);os.close(ready_write)
assert os.read(ready_read,1)==b'1';relay.attach(native);relay()
assert os.read(ready_read,1)==b'2';os.close(ready_read)
os.write(gate_write,b'1');os.close(gate_write)
pid,status=os.waitpid(native,0);assert os.WIFEXITED(status) and os.WEXITSTATUS(status)==0,status
print(json.dumps(dict(fixture_pass=True,landlock_verified=False)))
''')

    def test_concurrent_wait_obeys_original_stop_deadline_without_second_grace(self):
        self.run_fixture(r'''
import json,os,signal,subprocess,sys,threading,time
from unittest.mock import patch
sys.path.insert(0,sys.argv[1])
from meme_machine.operational import isolated_native_landlock_launcher as launcher
read,write=os.pipe()
code='import os,signal,sys,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);os.write(int(sys.argv[1]),b"1");time.sleep(60)'
child=subprocess.Popen([sys.executable,'-I','-B','-S','-c',code,str(write)],
 stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True,pass_fds=(write,))
os.close(write);assert os.read(read,1)==b'1';os.close(read);child.stdin.close()
owner=launcher.NativeLandlockChild(child,time.monotonic());receipts=[]
waiter=threading.Thread(target=lambda:receipts.append(owner.wait()))
waiter.start()
while not owner._wait_lock.locked():time.sleep(.001)
started=time.monotonic()
with patch.object(launcher,'STOP_GRACE',.12):receipt=owner.stop()
elapsed=time.monotonic()-started;waiter.join(.2)
assert .08<=elapsed<.8,elapsed
assert not waiter.is_alive() and len(receipts)==1
assert receipt['code']==receipts[0]['code']=='native_landlock_shutdown_expired',receipts
assert child.returncode==-signal.SIGKILL and owner._reaped and not owner._reader.is_alive()
deadline=owner._stop_deadline
with patch.object(launcher,'STOP_GRACE',.12):owner.stop()
assert owner._stop_deadline==deadline
print(json.dumps(dict(fixture_pass=True,landlock_verified=False)))
''')

    def test_output_overflow_and_reader_start_failure_join_owned_processes(self):
        self.run_fixture(r'''
import json,os,subprocess,sys,time
from unittest.mock import patch
sys.path.insert(0,sys.argv[1])
from meme_machine.operational.isolated_native_landlock_launcher import NativeLandlockChild
def start(code):return subprocess.Popen([sys.executable,'-I','-B','-S','-c',code],stdin=subprocess.PIPE,
 stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
child=start('import os,time;os.write(1,b"x"*65537);time.sleep(60)')
owner=NativeLandlockChild(child,time.monotonic());receipt=owner.wait(seconds=2)
child.stdin.close()
assert receipt['status']=='BLOCKED' and receipt['code']=='native_landlock_output_bound',receipt
assert child.returncode is not None and not owner._reader.is_alive()
child=start('import time;time.sleep(60)')
with patch('threading.Thread.start',side_effect=RuntimeError('fixed fixture start failure')):
 try:NativeLandlockChild(child,time.monotonic())
 except RuntimeError as error:assert error.native_landlock_owner.child is child
 else:raise AssertionError('start failure accepted')
assert child.returncode is not None and child.stdin.closed and child.stdout.closed and child.stderr.closed
child=start('import time;time.sleep(60)');original_wait=child.wait
primary=RuntimeError('fixed primary startup failure')
with patch('threading.Thread.start',side_effect=primary),patch.object(child,'wait',side_effect=subprocess.TimeoutExpired('fixed child',2)):
 try:NativeLandlockChild(child,time.monotonic())
 except RuntimeError as error:
  assert error is primary and isinstance(error.__cause__,subprocess.TimeoutExpired)
  retained=error.native_landlock_owner;assert retained.child is child and not retained._reaped
 else:raise AssertionError('cleanup failure replaced or lost primary')
assert child.stdin.closed and child.stdout.closed and child.stderr.closed
receipt=retained.wait(seconds=.1);assert retained._reaped and child.returncode is not None
print(json.dumps(dict(fixture_pass=True,landlock_verified=False)))
''')


if __name__=='__main__':unittest.main()
