"""Explicit copied-native Landlock launcher; no namespace/backend fallback.

The caller supplies the existing authenticated image approval and original parent
transport/facts. A fresh single-threaded supervisor owns subreaping; the host
caller never changes its process policy. Final native exec has only anonymous
stdio, FD3 transport and FD4 facts. The protected parent retains all authority.
"""
import ctypes
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import resource
import select
import selectors
import signal
import stat
import subprocess
import sys
import threading
import time

from . import namespace_canary as boundary
from . import isolated_native_image as image
from .isolated_native_launcher import _channel_descriptors, _prune_descriptors
from .isolated_native_landlock_image import PinnedNativeImage, PROFILE as IMAGE_PROFILE
from .native_landlock_policy import NativePolicy, NativePolicyBlocked, PROFILE

OUTPUT_BOUND=65536
SETUP_BOUND=1024*1024+16384
NATIVE_WALL=1865
STOP_GRACE=65


def _prctl(kernel,option,value,code):
    return kernel.call(157,ctypes.c_int(option),ctypes.c_ulong(value),ctypes.c_ulong(0),
        ctypes.c_ulong(0),ctypes.c_ulong(0),code=code)


def _arm_parent(kernel,expected):
    if os.getppid()!=expected:raise NativePolicyBlocked('native_landlock_parent_changed')
    _prctl(kernel,1,signal.SIGKILL,'native_landlock_parent_death_refused')
    if os.getppid()!=expected:raise NativePolicyBlocked('native_landlock_parent_changed')


def _packet(value):
    image.require(type(value) is dict and set(value)=={'scope','image','work','parent_pid',
        'transport_fd','facts_fd','approval','manifest','manifest_sha256','profile'},'native_landlock_spec')
    image.require(value['profile']==PROFILE and type(value['parent_pid']) is int
        and 1<value['parent_pid']<2**31,'native_landlock_profile')
    scope=Path(value['scope'])
    image.require(scope.is_absolute() and '..' not in scope.parts
        and value['image']==str(scope/'native-image') and value['work']==str(scope/'native-work'),
        'native_landlock_paths')
    for key in ('transport_fd','facts_fd'):
        image.require(type(value[key]) is int and 3<=value[key]<65536,'native_landlock_descriptor')
    image.require(value['transport_fd']!=value['facts_fd']
        and image._digest(value['manifest_sha256']),'native_landlock_descriptor')
    return value


def _read_setup():
    # This original anonymous parent pipe, not a candidate's own digest, is the
    # origin of the retained approval/build receipt. It is consumed before the
    # final exec and never becomes a native-data capability.
    info=os.fstat(0)
    image.require(stat.S_ISFIFO(info.st_mode)
        and fcntl.fcntl(0,fcntl.F_GETFL)&os.O_ACCMODE==os.O_RDONLY
        and os.readlink('/proc/self/fd/0').startswith('pipe:['),'native_landlock_setup_pipe')
    raw=bytearray()
    while len(raw)<=SETUP_BOUND:
        part=os.read(0,min(65536,SETUP_BOUND+1-len(raw)))
        if not part:break
        raw.extend(part)
    image.require(len(raw)<=SETUP_BOUND,'native_landlock_setup_bound')
    value=_packet(json.loads(raw))
    image.require(bytes(raw)==image.encoded(value),'native_landlock_setup_encoding')
    return value


def _entry_command(layout):
    # Only paths/source identity vary. No caller-provided module, program, source
    # expression, environment or selector is accepted by this fixed route.
    root=Path(layout.image_root)
    return ('import sys;sys.path[:0]='+repr([str(root/'app'),str(root/'deps')])+
        ';from meme_machine.operational.isolated_native_layout import NativeChildLayout;'+
        'from meme_machine.operational.isolated_native_entry import main;'+
        'layout=NativeChildLayout(profile='+repr(layout.profile)+',image_root='+repr(str(layout.image_root))+
        ',work_root='+repr(str(layout.work_root))+',parent_pid='+str(layout.parent_pid)+
        ',manifest_sha256='+repr(layout.manifest_sha256)+');sys.argv=["isolated_native_entry"];'+
        'raise SystemExit(main(layout=layout))')


def _exec_native(value,binding,supervisor):
    kernel=NativePolicy()
    signal.signal(signal.SIGTERM,signal.SIG_DFL)
    signal.signal(signal.SIGINT,signal.SIG_DFL)
    _arm_parent(kernel,supervisor)
    from .isolated_native_layout import NativeChildLayout
    layout=NativeChildLayout(profile=PROFILE,image_root=value['image'],work_root=value['work'],
        parent_pid=supervisor,manifest_sha256=value['manifest_sha256'])
    layout.native_directory.mkdir(mode=0o700)
    layout.temporary_directory.mkdir(mode=0o700)
    os.chdir(layout.native_directory)
    os.environ.clear()
    os.environ.update(layout.environment())
    _,hard=resource.getrlimit(resource.RLIMIT_NOFILE)
    image.require(hard==resource.RLIM_INFINITY or hard>=65536,'native_landlock_file_capacity')
    resource.setrlimit(resource.RLIMIT_NOFILE,(65536,65536))
    _,hard_cpu=resource.getrlimit(resource.RLIMIT_CPU)
    cpu=NATIVE_WALL if hard_cpu==resource.RLIM_INFINITY else min(NATIVE_WALL,hard_cpu)
    resource.setrlimit(resource.RLIMIT_CPU,(cpu,cpu))
    command=_entry_command(layout)
    executable=str(layout.executable)
    version=kernel.install(binding,layout.work_root)
    # A fixed bounded pre-exec observation, not a selectable child policy or
    # source of authority. The validation parent also requires the exact
    # approved fixed entry and its independently checked native output.
    installed=image.encoded(dict(profile=PROFILE,landlock_abi=version,installed=True))
    os.write(2,b'NATIVE_POLICY_INSTALLED '+installed+b'\n')
    binding.close()
    os.execv(executable,[executable,'-I','-B','-S','-c',command])


def _finish_descendants(*,seconds=2):
    """Reap EOF-complete tracker/children; refuse unjoined physical ownership."""
    deadline=time.monotonic()+seconds;clean=True
    while True:
        # Kernel ownership/ECHILD is sufficient: do not depend on optional proc
        # children files or accept a child-selected PID for signaling. This
        # fresh subreaper is the sole waiter for its direct/adopted descendants.
        try:waited,status=os.waitpid(-1,os.WNOHANG)
        except ChildProcessError:return clean
        if waited:
            if not os.WIFEXITED(status) or os.WEXITSTATUS(status)!=0:clean=False
            continue
        if time.monotonic()<deadline:
            time.sleep(min(.01,max(0,deadline-time.monotonic())));continue
        # No second graceful interval or success for unknown live descendants.
        # The protected parent still holds this unreaped session leader and
        # kills its whole group before reaping it. Return125 keeps that forced
        # physical cleanup distinct from a graceful all-owner join.
        return False


class _NativeCancellation:
    """Fresh supervisor main-thread relay to its actual unreaped child only."""
    def __init__(self):self.pid=None;self.requested=False

    def __call__(self,*_signal):
        self.requested=True
        self._forward()

    def attach(self,pid):
        image.require(self.pid is None and type(pid) is int and 1<pid<2**31,
            'native_landlock_cancel_owner')
        self.pid=pid
        if self.requested:self._forward()

    def _forward(self):
        if self.pid is None:return
        # This handler runs in the supervisor's sole thread, so waitpid cannot
        # reap between this ownership check and signal. An exited child remains
        # reserved; after reap ECHILD refuses a potentially reused numeric PID.
        try:os.waitid(os.P_PID,self.pid,os.WEXITED|os.WNOHANG|os.WNOWAIT)
        except ChildProcessError:return
        try:os.kill(self.pid,signal.SIGTERM)
        except ProcessLookupError:pass


def _reset_native_child_signals(cancellation):
    # The forked copy initially owns the supervisor's remembering handler. A
    # TERM delivered before these resets must remain a stop, rather than being
    # consumed and then forgotten when the native entry installs its handlers.
    for number in (signal.SIGTERM,signal.SIGINT):signal.signal(number,signal.SIG_DFL)
    if cancellation.requested:
        raise NativePolicyBlocked('native_landlock_cancelled_before_entry')


def _setup(value):
    value=_packet(value);kernel=NativePolicy()
    image.require(os.geteuid()!=0 and os.listdir('/proc/self/task')==[str(os.getpid())],
        'native_landlock_single_unprivileged_setup')
    image.require(value['parent_pid']==os.getppid(),'native_landlock_parent_changed')
    _arm_parent(kernel,value['parent_pid'])
    cancellation=_NativeCancellation()
    for number in (signal.SIGTERM,signal.SIGINT):signal.signal(number,cancellation)
    boundary._scratch(value['scope'],value['parent_pid'])
    boundary._private(value['work'],empty=True)
    signal.signal(signal.SIGCHLD,signal.SIG_DFL)
    # Approval/build bytes arrived only over the original protected-parent
    # setup pipe. Equality detaches that received statement; it is not an
    # invented authenticator for an unperformed source/build observation.
    retained=value['approval']
    approval=image.NativeImageApproval(retained,authenticate=lambda candidate:candidate==retained)
    image.source_objects(approval)
    # Normalize before opening any pinned handles: FD3/4 must not collide with
    # image rules when the caller's original descriptor numbers were higher.
    _prune_descriptors(value['transport_fd'],value['facts_fd'])
    binding=PinnedNativeImage(value['image'],manifest_sha256=value['manifest_sha256'],
        approval=approval,authenticate_manifest=lambda candidate:candidate==value['manifest'],
        profile=IMAGE_PROFILE)
    try:
        _prctl(kernel,36,1,'native_landlock_subreaper_refused')
        supervisor=os.getpid();child=os.fork()
        if child==0:
            try:
                _reset_native_child_signals(cancellation)
                _exec_native(value,binding,supervisor)
            except BaseException as error:
                _report_failure(error)
                os._exit(2)
        cancellation.attach(child)
        # The supervisor never participates in RPC/facts/native persistence.
        os.close(3);os.close(4);binding.close()
        while True:
            try:_,status=os.waitpid(child,0);break
            except InterruptedError:continue
        clean=_finish_descendants()
        code=os.waitstatus_to_exitcode(status) if os.WIFEXITED(status) else 2
        os._exit(code if clean and 0<=code<=125 else 125)
    finally:
        binding.close()


def _wait_unreaped(process,deadline):
    while True:
        state=os.waitid(os.P_PID,process.pid,os.WEXITED|os.WNOHANG|os.WNOWAIT)
        if state is not None:return True
        remaining=(deadline() if callable(deadline) else deadline)-time.monotonic()
        if remaining<=0:return False
        time.sleep(min(.05,remaining))


class NativeLandlockChild:
    """One reserved session-leader PID until owned-group signal and final reap."""
    def __init__(self,child,started):
        self.child=child;self.deadline=started+NATIVE_WALL
        self.output={'stdout':bytearray(),'stderr':bytearray()}
        self.failure=None;self._reaped=False;self._lock=threading.RLock();self._wait_lock=threading.Lock()
        self._stop_deadline=None
        self._reader=threading.Thread(target=self._drain,name='native-landlock-output',daemon=True)
        try:self._reader.start()
        except BaseException as primary:
            # Retain the physical owner even if cleanup itself fails. In
            # particular Thread.start may raise after actually starting it.
            primary.native_landlock_owner=self
            cleanup=None
            for operation in (lambda:self._signal(signal.SIGKILL),self._constructor_reap,
                    lambda:self.child.stdin.close() if self.child.stdin is not None else None):
                try:operation()
                except BaseException as error:
                    if cleanup is None:cleanup=error
            if self._reader.ident is not None:
                try:self._reader.join(timeout=2)
                except BaseException as error:
                    if cleanup is None:cleanup=error
            if self._reader.is_alive():
                self.failure='native_landlock_output_owner_alive'
            else:
                for stream in (self.child.stdout,self.child.stderr):
                    try:stream.close()
                    except BaseException as error:
                        if cleanup is None:cleanup=error
            if cleanup is not None:raise primary from cleanup
            raise

    def _constructor_reap(self):
        with self._lock:
            self.child.wait(timeout=2);self._reaped=True

    def _effective_deadline(self,local):
        with self._lock:
            return min(local,self.deadline,self._stop_deadline if self._stop_deadline is not None else self.deadline)

    def _signal(self,number):
        with self._lock:
            if self._reaped:return
            try:os.waitid(os.P_PID,self.child.pid,os.WEXITED|os.WNOHANG|os.WNOWAIT)
            except ChildProcessError:
                self.failure='native_landlock_leader_ownership_lost';self._reaped=True;return
            try:
                if number==signal.SIGTERM:os.kill(self.child.pid,number)
                elif number==signal.SIGKILL:os.killpg(self.child.pid,number)
                else:raise ValueError('native_landlock_signal')
            except ProcessLookupError:pass

    def _drain(self):
        try:
            with selectors.DefaultSelector() as watcher:
                for name,stream in (('stdout',self.child.stdout),('stderr',self.child.stderr)):
                    os.set_blocking(stream.fileno(),False);watcher.register(stream,selectors.EVENT_READ,name)
                while watcher.get_map():
                    if time.monotonic()>=self.deadline:
                        self.failure='native_landlock_wall_expired';self._signal(signal.SIGKILL);return
                    for key,_ in watcher.select(.1):
                        data=os.read(key.fd,4096)
                        if not data:watcher.unregister(key.fileobj);continue
                        target=self.output[key.data]
                        if len(target)+len(data)>OUTPUT_BOUND:
                            self.failure='native_landlock_output_bound';self._signal(signal.SIGKILL);return
                        target.extend(data)
        except Exception:
            self.failure='native_landlock_output_unavailable';self._signal(signal.SIGKILL)

    def stop(self):
        with self._lock:
            requested=min(self.deadline,time.monotonic()+STOP_GRACE)
            self._stop_deadline=min(requested,self._stop_deadline) if self._stop_deadline is not None else requested
        self._signal(signal.SIGTERM)
        return self.wait(seconds=STOP_GRACE)

    def wait(self,*,seconds=None):
        image.require(seconds is None or type(seconds) in (int,float) and 0<seconds<=NATIVE_WALL,
            'native_landlock_wait_bound')
        deadline=min(self.deadline,time.monotonic()+seconds) if seconds is not None else self.deadline
        with self._wait_lock:
            with self._lock:already=self._reaped
            if not already:
                if not _wait_unreaped(self.child,lambda:self._effective_deadline(deadline)):
                    self.failure=self.failure or 'native_landlock_shutdown_expired'
                # Always signal the original group BEFORE reaping the leader,
                # even after a clean leader exit, to contain any orphaned task.
                self._signal(signal.SIGKILL)
                with self._lock:
                    try:self.child.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        return self._blocked('native_landlock_child_not_reaped')
                    self._reaped=True
            if self._reader.ident is not None:self._reader.join(timeout=2)
            if self._reader.is_alive():return self._blocked('native_landlock_output_owner_alive')
            self.child.stdout.close();self.child.stderr.close()
            if self.failure:return self._blocked(self.failure)
            if self.child.returncode==125:
                return self._blocked('native_landlock_descendants_not_joined')
            try:receipt=json.loads(bytes(self.output['stdout']))
            except (ValueError,UnicodeError,RecursionError):return self._blocked('native_landlock_result_unavailable')
            if type(receipt) is not dict or receipt.get('financial_authority') is not False:
                return self._blocked('native_landlock_result_unverified')
            if self.child.returncode!=0 and receipt.get('status')!='BLOCKED':
                return self._blocked('native_landlock_child_failed')
            receipt.update(child_exit=self.child.returncode,actual_service_restrictions_verified=False,
                production_equivalent=False,full_market_speed_proven=False,normal_readiness=False,
                native_os_profile=PROFILE,owned_group_signaled_before_reap=True)
            return receipt

    def _blocked(self,code):
        return dict(status='BLOCKED',code=code,financial_authority=False,normal_readiness=False,
            graceful_shutdown=False,all_workers_joined=False,
            actual_service_restrictions_verified=False,production_equivalent=False,full_market_speed_proven=False)


def _send_setup(stream,raw):
    image.require(len(raw)<=SETUP_BOUND,'native_landlock_setup_bound')
    os.set_blocking(stream.fileno(),False);deadline=time.monotonic()+10;position=0
    try:
        while position<len(raw):
            remaining=deadline-time.monotonic()
            image.require(remaining>0,'native_landlock_setup_timeout')
            _,writable,_=select.select([],[stream],[],min(.1,remaining))
            if writable:
                try:position+=os.write(stream.fileno(),raw[position:position+65536])
                except BlockingIOError:continue
    finally:stream.close()


def launch_native(scope,approval,transport,facts_read_fd):
    """Explicit fixed native target with original provider/facts capabilities."""
    image.require(type(approval) is image.NativeImageApproval and os.geteuid()!=0
        and threading.current_thread() is threading.main_thread()
        and signal.getsignal(signal.SIGCHLD)==signal.SIG_DFL,
        'native_landlock_approved_unprivileged_parent_required')
    scope=boundary._scratch(scope,os.getpid())
    staged=image.build(scope,approval,profile=PROFILE)
    work=scope/'native-work'
    image.require(not work.exists(),'native_landlock_scope_already_used');work.mkdir(mode=0o700)
    _channel_descriptors(transport.fileno(),facts_read_fd)
    value=_packet(dict(scope=str(scope),image=str(staged['root']),work=str(work),parent_pid=os.getpid(),
        transport_fd=transport.fileno(),facts_fd=facts_read_fd,approval=approval.value(),
        manifest=staged['manifest'],manifest_sha256=staged['manifest_sha256'],profile=PROFILE))
    code='import runpy,sys;sys.path.insert(0,'+repr(str(Path(__file__).resolve().parents[2]))+');runpy.run_module("meme_machine.operational.isolated_native_landlock_launcher",run_name="__main__")'
    child=subprocess.Popen([sys.executable,'-I','-B','-S','-c',code,'--setup'],stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,env={},close_fds=True,
        pass_fds=(transport.fileno(),facts_read_fd),start_new_session=True)
    owner=NativeLandlockChild(child,time.monotonic())
    try:_send_setup(child.stdin,image.encoded(value))
    except BaseException:
        owner._signal(signal.SIGKILL);owner.wait(seconds=2);raise
    return owner


def _report_failure(error):
    if isinstance(error,NativePolicyBlocked):code=error.code;number=error.number
    elif isinstance(error,image.Refused):code=str(error);number=None
    else:code='native_landlock_setup_unavailable';number=getattr(error,'errno',None)
    raw=image.encoded(dict(status='BLOCKED',code=code,error_number=number,financial_authority=False,
        normal_readiness=False,actual_service_restrictions_verified=False)) + b'\n'
    try:os.write(1,raw)
    except OSError:pass


def main():
    try:
        image.require(sys.argv[1:]==['--setup'],'native_landlock_fixed_entry')
        _setup(_read_setup())
    except BaseException as error:
        _report_failure(error)
        return 2


if __name__=='__main__':raise SystemExit(main())
