"""Fixed namespace launcher for the isolated native entry; no dispatch/deploy hook.

The only launch target is isolated_native_entry.main(), with FD3 parent transport
and FD4 parent sizing facts. A separate fixed image proof creates its own offline
IPC fixtures; it cannot attach to providers. Neither route grants funding,
historical callback authority, service enforcement or production readiness.
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
import socket
import stat
import subprocess
import sys
import threading
import time

from . import namespace_canary as boundary
from .isolated_native_image import NativeImageApproval, Refused, build, encoded, require

OUTPUT_BOUND=65536
NATIVE_WALL=1865
MODES={'native':'meme_machine.operational.isolated_native_entry',
       'proof':'meme_machine.operational.isolated_native_image_probe'}


def _spec(value):
    require(type(value) is dict and set(value)=={'root','work','image','manifest_sha256',
        'parent_pid','transport_fd','facts_fd','mode'},'native_launcher_spec')
    require(all(type(value[key]) is str for key in ('root','work','image','manifest_sha256','mode')),
            'native_launcher_spec')
    root=Path(value['root'])
    require(root.is_absolute() and root.name=='native-rootfs' and '..' not in root.parts
        and value['work']==str(root.parent/'native-work')
        and value['image']==str(root.parent/'native-image'),'native_launcher_paths')
    require(value['mode'] in MODES and type(value['parent_pid']) is int
        and 1<value['parent_pid']<2**31,'native_launcher_mode')
    for name in ('transport_fd','facts_fd'):
        require(type(value[name]) is int and 3<=value[name]<65536,'native_launcher_descriptor')
    require(value['transport_fd']!=value['facts_fd'],'native_launcher_descriptor')
    require(len(value['manifest_sha256'])==64 and all(char in '0123456789abcdef'
        for char in value['manifest_sha256']),'native_launcher_manifest_identity')
    return value


def _channel_descriptors(transport,facts):
    require(stat.S_ISSOCK(os.fstat(transport).st_mode),'native_launcher_transport_descriptor')
    with socket.socket(fileno=os.dup(transport)) as channel:
        require(channel.family==socket.AF_UNIX and channel.getsockopt(socket.SOL_SOCKET,socket.SO_TYPE)==socket.SOCK_STREAM
            and channel.getsockname() in ('',b'') and channel.getpeername() in ('',b''),
            'native_launcher_transport_descriptor')
    info=os.fstat(facts)
    require(stat.S_ISFIFO(info.st_mode) and os.readlink('/proc/self/fd/'+str(facts)).startswith('pipe:[')
        and fcntl.fcntl(facts,fcntl.F_GETFL)&os.O_ACCMODE==os.O_RDONLY,
        'native_launcher_facts_descriptor')


def _prune_descriptors(transport,facts):
    _channel_descriptors(transport,facts)
    for descriptor in (1,2):
        require(stat.S_ISFIFO(os.fstat(descriptor).st_mode)
            and os.readlink('/proc/self/fd/'+str(descriptor)).startswith('pipe:['),
            'native_launcher_output_descriptor')
    # Dup above both fixed target numbers before closing; FD3/4 may be swapped.
    saved_transport=fcntl.fcntl(transport,fcntl.F_DUPFD_CLOEXEC,16)
    saved_facts=fcntl.fcntl(facts,fcntl.F_DUPFD_CLOEXEC,16)
    for raw in os.listdir('/proc/self/fd'):
        descriptor=int(raw)
        if descriptor in (1,2,saved_transport,saved_facts):continue
        try:os.close(descriptor)
        except OSError as error:
            if error.errno!=errno.EBADF:raise
    os.dup2(saved_transport,3,inheritable=True);os.dup2(saved_facts,4,inheritable=True)
    os.close(saved_transport);os.close(saved_facts)
    descriptor=os.open('/dev/null',os.O_RDONLY)
    if descriptor!=0:os.dup2(descriptor,0);os.close(descriptor)


def _verify_image(path,expected):
    path=boundary._private(path)
    manifest=path/'manifest.json'
    require(manifest.is_file() and not manifest.is_symlink() and manifest.stat().st_size<=512*1024,
            'native_launcher_manifest_missing')
    raw=manifest.read_bytes()
    require(hashlib.sha256(raw).hexdigest()==expected,'native_launcher_manifest_changed')
    value=json.loads(raw)
    require(type(value) is dict and value.get('schema')=='isolated-native-copied-image-v1'
        and value.get('financial_authority') is False and type(value.get('provider_calls')) is int
        and value['provider_calls']==0
        and value.get('actual_service_restrictions_verified') is False
        and type(value.get('files')) is list and len(value['files'])<=2048,'native_launcher_manifest')
    listed=set();total=0
    for row in value['files']:
        require(type(row) is dict and set(row)=={'path','bytes','sha256'}
            and type(row['path']) is str and type(row['bytes']) is int
            and 0<=row['bytes']<=64*1024**2,'native_launcher_manifest_file')
        name=Path(row['path'])
        require(not name.is_absolute() and '..' not in name.parts and row['path'] not in listed,
                'native_launcher_manifest_file')
        node=path/name
        require(node.resolve()==node,'native_launcher_image_link')
        info=node.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_uid==os.geteuid()
            and stat.S_IMODE(info.st_mode) in (0o400,0o500) and info.st_size==row['bytes'],
            'native_launcher_image_regular')
        require(hashlib.sha256(node.read_bytes()).hexdigest()==row['sha256'],
                'native_launcher_image_changed')
        listed.add(row['path']);total+=row['bytes']
    require(type(value.get('bytes')) is int and value['bytes']==total and total<=256*1024**2,
            'native_launcher_image_bound')
    discovered=set()
    for count,node in enumerate(path.rglob('*'),1):
        require(count<=4096,'native_launcher_image_entry_bound')
        info=node.lstat()
        require(stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode),'native_launcher_image_special')
        if stat.S_ISREG(info.st_mode):discovered.add(str(node.relative_to(path)))
    require(discovered==listed|{'manifest.json'},'native_launcher_image_unlisted')
    return value


def _setup(value):
    value=_spec(value);kernel=boundary.Kernel()
    require(os.geteuid()!=0,'native_launcher_nonroot_required')
    require(len(os.listdir('/proc/self/task'))==1,'native_launcher_single_thread_required')
    root=boundary._private(value['root'],empty=True)
    work=boundary._private(value['work'],empty=True)
    require(value['parent_pid']==os.getppid(),'native_launcher_parent_identity')
    boundary._scratch(root.parent,value['parent_pid'])
    _verify_image(value['image'],value['manifest_sha256'])
    _channel_descriptors(value['transport_fd'],value['facts_fd'])
    uid,gid=os.geteuid(),os.getegid()
    kernel.prctl(38,1,'native_launcher_no_new_privileges_refused')
    boundary._arm_parent(kernel,value['parent_pid'])
    kernel.unshare(boundary.USER)
    Path('/proc/self/setgroups').write_text('deny')
    Path('/proc/self/uid_map').write_text('0 '+str(uid)+' 1\n')
    Path('/proc/self/gid_map').write_text('0 '+str(gid)+' 1\n')
    kernel.unshare(boundary.MOUNT|boundary.NET|boundary.PID|boundary.IPC)
    kernel.mount(None,'/',flags=boundary.MS_REC|boundary.MS_PRIVATE)
    boundary._arm_parent(kernel,value['parent_pid'])
    lifeline_read,lifeline_write=os.pipe2(os.O_CLOEXEC)
    # TERM reaches the entire new process group. The waiting wrapper must stay
    # alive while the native PID1 performs its own graceful cancellation; its
    # death would otherwise trigger PID1's SIGKILL parent-death fence.
    signal.signal(signal.SIGTERM,signal.SIG_IGN)
    child=os.fork()
    if child:
        os.close(lifeline_read)
        _,status=os.waitpid(child,0)
        os._exit(os.waitstatus_to_exitcode(status) if os.WIFEXITED(status) else 3)
    signal.signal(signal.SIGTERM,signal.SIG_DFL)
    os.close(lifeline_write);boundary._arm_pid1_parent(kernel,lifeline_read);os.close(lifeline_read)
    kernel.mount('tmpfs',root,'tmpfs',boundary.MS_NOSUID|boundary.MS_NODEV,'size=16m,mode=0755')
    for name in ('image','work','tmp','proc','dev','dev/shm','oldroot'):
        (root/name).mkdir(parents=True,exist_ok=True)
    boundary._bind(kernel,value['image'],root/'image',readonly=True)
    boundary._bind(kernel,work,root/'work',readonly=False)
    boundary._bind(kernel,Path(value['image'])/'loader',root/'lib64/ld-linux-x86-64.so.2',readonly=True)
    for name in ('null','zero','urandom'):
        boundary._bind(kernel,Path('/dev')/name,root/'dev'/name,readonly=False)
    for name in ('tmp','dev/shm'):
        kernel.mount('tmpfs',root/name,'tmpfs',boundary.MS_NOSUID|boundary.MS_NODEV,'size=64m,mode=1777')
    kernel.mount('proc',root/'proc','proc',boundary.MS_RDONLY|boundary.MS_NOSUID|boundary.MS_NODEV)
    os.chdir(root)
    kernel.call('syscall',ctypes.c_long(155),ctypes.c_char_p(b'.'),ctypes.c_char_p(b'oldroot'),
                code='native_launcher_pivot_refused')
    os.chdir('/')
    kernel.call('umount2',ctypes.c_char_p(b'/oldroot'),ctypes.c_int(2),code='native_launcher_oldroot_refused')
    Path('/oldroot').rmdir()
    kernel.mount(None,'/',flags=boundary.MS_REMOUNT|boundary.MS_RDONLY|boundary.MS_NOSUID|boundary.MS_NODEV)
    _prune_descriptors(value['transport_fd'],value['facts_fd'])
    boundary._drop_capabilities(kernel);boundary._lock_namespaces(kernel)
    Path('/work/native').mkdir(mode=0o700);os.chdir('/work/native')
    os.environ.clear();os.environ.update(LANG='C',PATH='/nonexistent',TMPDIR='/tmp',
        PYTHONDONTWRITEBYTECODE='1',LD_LIBRARY_PATH='/image/runtime/lib')
    _,hard=resource.getrlimit(resource.RLIMIT_NOFILE)
    # Image proof starts no native market consumer/source. Its separately
    # declared4096-FD fixture does not certify the native65536-FD profile.
    descriptors=65536 if value['mode']=='native' else 4096
    require(hard==resource.RLIM_INFINITY or hard>=descriptors,'native_launcher_file_capacity')
    resource.setrlimit(resource.RLIMIT_NOFILE,(descriptors,descriptors))
    _,hard_cpu=resource.getrlimit(resource.RLIMIT_CPU)
    cpu=NATIVE_WALL if hard_cpu==resource.RLIM_INFINITY else min(NATIVE_WALL,hard_cpu)
    resource.setrlimit(resource.RLIMIT_CPU,(cpu,cpu))
    # Fixed path/module literals, not caller-provided argv or import targets.
    entry=MODES[value['mode']]
    command='import runpy,sys;sys.path[:0]=["/image/app","/image/deps"];sys.argv=['+repr(entry)+'];runpy.run_module('+repr(entry)+',run_name="__main__",alter_sys=True)'
    executable='/image/runtime/bin/python3.12'
    os.execv(executable,[executable,'-I','-B','-S','-c',command])


class NativeChild:
    """Own only this child group/output. Original parent owns service/resources."""
    def __init__(self,child,started,*,wall=NATIVE_WALL):
        self.child=child;self.started=started;self.deadline=started+wall
        self.output={'stdout':bytearray(),'stderr':bytearray()}
        self.failure=None;self.done=threading.Event()
        self._process_lock=threading.RLock()
        self._reader=threading.Thread(target=self._drain,name='isolated-native-output',daemon=True)
        self._reader.start()

    def _signal(self,value):
        # No other owner reaps this Popen. Keep poll/reap and group signaling
        # under one lock so an exited/reused numeric PID cannot be targeted.
        with self._process_lock:
            if self.child.poll() is not None:return
            try:os.killpg(self.child.pid,value)
            except ProcessLookupError:pass

    def _await_exit(self,seconds):
        deadline=time.monotonic()+seconds
        while True:
            with self._process_lock:
                if self.child.poll() is not None:return True
            remaining=deadline-time.monotonic()
            if remaining<=0:return False
            time.sleep(min(.05,remaining))

    def _drain(self):
        try:
            with selectors.DefaultSelector() as watcher:
                for name,stream in (('stdout',self.child.stdout),('stderr',self.child.stderr)):
                    os.set_blocking(stream.fileno(),False);watcher.register(stream,selectors.EVENT_READ,name)
                while watcher.get_map():
                    if time.monotonic()>=self.deadline:
                        self.failure='native_launcher_wall_expired';self._signal(signal.SIGKILL);break
                    for key,_ in watcher.select(.1):
                        data=os.read(key.fd,4096)
                        if not data:watcher.unregister(key.fileobj);continue
                        target=self.output[key.data]
                        if len(target)+len(data)>OUTPUT_BOUND:
                            self.failure='native_launcher_output_bound';self._signal(signal.SIGKILL)
                            return
                        target.extend(data)
        except Exception:
            self.failure='native_launcher_output_unavailable';self._signal(signal.SIGKILL)
        finally:
            self.done.set()

    def stop(self):
        """Request native cancellation, then enforce the original65s fence."""
        self._signal(signal.SIGTERM)
        return self.wait(seconds=65)

    def wait(self,*,seconds=None):
        require(seconds is None or type(seconds) in (int,float) and 0<seconds<=NATIVE_WALL,
                'native_launcher_wait_bound')
        remaining=max(.001,self.deadline-time.monotonic())
        timeout=remaining if seconds is None else min(remaining,seconds)
        if not self._await_exit(timeout):
            self.failure=self.failure or 'native_launcher_shutdown_expired'
            self._signal(signal.SIGKILL)
            if not self._await_exit(2):
                return dict(status='BLOCKED',code='native_launcher_child_not_reaped',financial_authority=False,
                            actual_service_restrictions_verified=False)
        if not self.done.wait(2):
            self.failure=self.failure or 'native_launcher_output_not_closed';self._signal(signal.SIGKILL)
        self._reader.join(timeout=2)
        if self._reader.is_alive():
            return dict(status='BLOCKED',code='native_launcher_output_owner_alive',financial_authority=False)
        self.child.stdout.close();self.child.stderr.close()
        if self.failure:
            return dict(status='BLOCKED',code=self.failure,child_exit=self.child.returncode,
                        financial_authority=False,actual_service_restrictions_verified=False)
        try:receipt=json.loads(bytes(self.output['stdout']))
        except (ValueError,UnicodeError,RecursionError):
            return dict(status='BLOCKED',code='native_launcher_result_unavailable',
                        financial_authority=False,actual_service_restrictions_verified=False)
        if type(receipt) is not dict or receipt.get('financial_authority') is not False:
            return dict(status='BLOCKED',code='native_launcher_result_unverified',financial_authority=False)
        if self.child.returncode!=0 and receipt.get('status')!='BLOCKED':
            return dict(status='BLOCKED',code='native_launcher_child_failed',child_exit=self.child.returncode,
                        financial_authority=False,actual_service_restrictions_verified=False)
        # A successful exit/receipt here is never authoritative PAPER readiness.
        receipt.update(child_exit=self.child.returncode,actual_service_restrictions_verified=False,
                       production_equivalent=False,full_market_speed_proven=False)
        return receipt


def _start(scope,image,transport,facts,*,mode,wall=NATIVE_WALL):
    started=time.monotonic();scope=boundary._scratch(scope,os.getpid())
    require(mode in MODES and type(image) is dict,'native_launcher_fixed_mode')
    require(Path(image['root'])==scope/'native-image','native_launcher_image_scope')
    _verify_image(image['root'],image['manifest_sha256'])
    _channel_descriptors(transport.fileno(),facts)
    root,work=scope/'native-rootfs',scope/'native-work'
    require(not root.exists() and not work.exists(),'native_launcher_scope_already_used')
    root.mkdir(mode=0o700);work.mkdir(mode=0o700)
    value=_spec(dict(root=str(root),work=str(work),image=str(image['root']),
        manifest_sha256=image['manifest_sha256'],parent_pid=os.getpid(),
        transport_fd=transport.fileno(),facts_fd=facts,mode=mode))
    bootstrap='import runpy,sys;sys.path.insert(0,'+repr(str(Path(__file__).resolve().parents[2]))+');runpy.run_module("meme_machine.operational.isolated_native_launcher",run_name="__main__")'
    child=subprocess.Popen([sys.executable,'-I','-B','-S','-c',bootstrap,'--setup',json.dumps(value)],
        stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env={},
        close_fds=True,pass_fds=(transport.fileno(),facts),start_new_session=True)
    return NativeChild(child,started,wall=wall)


def launch_native(scope,approval,transport,facts_read_fd):
    """Fixed isolated native entry; no start/deploy/runtime integration exists."""
    require(type(approval) is NativeImageApproval,'native_launcher_approval_required')
    scope=boundary._scratch(scope,os.getpid())
    image=build(scope,approval)
    return _start(scope,image,transport,facts_read_fd,mode='native')


def prove_image(scope,approval):
    """Fixed offline image proof; creates only synthetic private IPC/canaries."""
    scope=boundary._scratch(scope,os.getpid())
    image=build(scope,approval)
    namespaces={name:os.readlink('/proc/self/ns/'+name) for name in ('user','mnt','pid','net','ipc')}
    cwd=Path.cwd()
    secret=scope/'host-native-image-secret';secret.write_bytes(b'private native image canary')
    abstract='mm-native-image-proof-'+str(os.getpid())+'-'+str(time.time_ns())
    facts_read,facts_write=os.pipe2(os.O_CLOEXEC)
    parent,peer=socket.socketpair()
    try:
        with parent,peer,socket.socket(socket.AF_UNIX) as listener,\
                socket.socket(socket.AF_UNIX) as hidden,socket.socket(socket.AF_INET) as network:
            listener.bind(str(scope/'host.sock'));listener.listen(1)
            hidden.bind('\0'+abstract);hidden.listen(1)
            network.bind(('127.0.0.1',0));network.listen(1)
            fixture=dict(schema='nonfinancial-native-image-proof-v1',secret=str(secret),
                unix=str(scope/'host.sock'),abstract=abstract,port=network.getsockname()[1],
                parent_pid=os.getpid(),host_shm=os.stat('/dev/shm').st_dev)
            os.write(facts_write,encoded(fixture));os.close(facts_write);facts_write=None
            child=_start(scope,image,peer,facts_read,mode='proof',wall=20)
            peer.close();os.close(facts_read);facts_read=None
            parent.settimeout(15)
            try:
                request=bytearray()
                while len(request)<len(b'native image proof'):
                    piece=parent.recv(32-len(request))
                    if not piece:break
                    request.extend(piece)
                if request==b'native image proof':
                    parent.sendall(b'parent acknowledged')
                    ready=bytearray()
                    while len(ready)<len(b'proof ready'):
                        piece=parent.recv(32-len(ready))
                        if not piece:break
                        ready.extend(piece)
                    if ready==b'proof ready':child._signal(signal.SIGTERM)
                    else:child._signal(signal.SIGKILL)
                else:child._signal(signal.SIGKILL)
            except OSError:child._signal(signal.SIGKILL)
            result=child.wait(seconds=20)
    finally:
        for descriptor in (facts_read,facts_write):
            if descriptor is not None:os.close(descriptor)
    require(secret.read_bytes()==b'private native image canary','native_image_host_canary_changed')
    require(namespaces=={name:os.readlink('/proc/self/ns/'+name) for name in namespaces},
            'native_image_parent_namespace_changed')
    require(Path.cwd()==cwd,'native_image_parent_cwd_changed')
    result.update(parent_namespaces_unchanged=True,parent_cwd_unchanged=True,
                  image_manifest_sha256=image['manifest_sha256'],image_files=len(image['manifest']['files']),
                  image_bytes=image['manifest']['bytes'])
    return result


def main():
    try:
        require(len(sys.argv)==3 and sys.argv[1]=='--setup' and len(sys.argv[2])<=4096,
                'native_launcher_fixed_entry')
        _setup(json.loads(sys.argv[2]))
    except BaseException as error:
        code=error.code if isinstance(error,boundary.Blocked) else (
            error.args[0] if isinstance(error,Refused) else 'native_launcher_setup_unavailable')
        print(json.dumps(dict(status='BLOCKED',code=code,financial_authority=False,
            error_number=error.number if isinstance(error,boundary.Blocked) else None,
            actual_service_restrictions_verified=False)),flush=True)
        return 2


if __name__=='__main__':raise SystemExit(main())
