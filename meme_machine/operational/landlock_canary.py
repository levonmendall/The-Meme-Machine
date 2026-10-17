"""Fixed ABI6 Landlock/seccomp canary; no providers, native workers or authority.

Only disposable canaries are touched. This is not a mount/PID/network namespace:
host metadata may remain visible. No private SHM or native-spawn parity is claimed.
The caller retains its existing outer wall/resource/stopped/source fences.
"""
import ctypes
import errno
import fcntl
import json
import os
from pathlib import Path
import platform
import resource
import re
import select
import signal
import socket
import sqlite3
import stat
import struct
import subprocess
import sys
import time

MAX_RESULT = 16384
MIN_ABI = 6
READ = (1 << 2) | (1 << 3)
FS = (1 << 16)-1
WORK = FS & ~((1 << 0) | (1 << 6) | (1 << 11) | (1 << 15))
SCOPES = 3
CHECKS = frozenset(('fs_read','fs_write','readonly_image','proc_data',
    'abstract_scope','signal_scope','anonymous_parent_ipc','facts_pipe',
    'inherited_fds_closed','internal_socketpair','internal_pipe','sqlite_FULL_WAL',
    'descendant_inheritance','copied_fixture_exec','effective_caps_empty','no_new_privileges','seccomp_socket','seccomp_connect',
    'seccomp_bind','seccomp_listen','seccomp_accept','seccomp_sendmsg','seccomp_recvmsg',
    'seccomp_ptrace','seccomp_process_vm_read','seccomp_process_vm_write',
    'seccomp_pidfd_getfd','seccomp_metadata','seccomp_namespace','seccomp_io_uring'))
PARENT_CHECKS = ('parent_cwd_unchanged','parent_namespaces_unchanged',
                 'parent_open_descriptors_preserved','outside_canary_unchanged')
_MARKERS = ('portfolio.sqlite','shared-capital.sqlite','native-genesis.json','inception.json')
# Reviewed x86_64 Linux ABI. No alternate ABI, x32 or newer syscall fallback.
_DENIED = frozenset((16,29,30,31,41,42,43,46,47,49,50,64,65,66,67,68,69,70,71,
    90,91,92,93,94,101,103,109,112,126,132,155,161,165,166,167,168,169,172,173,
    175,176,179,188,189,190,197,198,199,235,240,241,242,243,244,245,246,248,249,
    250,260,261,268,272,280,288,298,299,307,308,310,311,312,313,317,320,321,323,
    425,426,427,428,429,430,431,432,433,434,438,442))
_FAILURE_FD=None
_OBSERVED_ABI=None
_ALREADY_REPORTED=False


def _elf():
    """Exact static x86_64 exit(0) fixture, not an arbitrary executable input."""
    text=b'\xb8\x3c\x00\x00\x00\x31\xff\x0f\x05'
    size=120+len(text)
    header=struct.pack('<16sHHIQQQIHHHHHH',b'\x7fELF\x02\x01\x01'+b'\x00'*9,
        2,62,1,0x400078,64,0,0,64,56,1,0,0,0)
    program=struct.pack('<IIQQQQQQ',1,5,0,0x400000,0,size,size,4096)
    return header+program+text


class Blocked(RuntimeError):
    def __init__(self, code, number=None, abi=None, check=None):
        self.code,self.number,self.abi,self.check=code,number,abi,check
        super().__init__(code)


def _require(value,code):
    if not value:raise Blocked(code)


class _Ruleset(ctypes.Structure):
    _fields_=[('fs',ctypes.c_uint64),('net',ctypes.c_uint64),('scoped',ctypes.c_uint64)]


class _PathRule(ctypes.Structure):
    _pack_=1
    _fields_=[('access',ctypes.c_uint64),('fd',ctypes.c_int32)]


class _Filter(ctypes.Structure):
    _fields_=[('code',ctypes.c_ushort),('jt',ctypes.c_ubyte),
              ('jf',ctypes.c_ubyte),('k',ctypes.c_uint32)]


class _Program(ctypes.Structure):
    _fields_=[('length',ctypes.c_ushort),('filter',ctypes.POINTER(_Filter))]


def _filter():
    # Every special branch reloads syscall nr before the fixed deny list.
    rows=[(0x20,0,0,4),(0x15,1,0,0xc000003e),(0x06,0,0,0x80000000),
          (0x20,0,0,0),(0x35,0,1,451),(0x06,0,0,0x50000|errno.EPERM)]
    deny=(0x06,0,0,0x50000|errno.EPERM)
    # socketpair(AF_UNIX, SOCK_STREAM[|CLOEXEC|NONBLOCK], protocol=0) only.
    rows += [(0x15,0,10,53),(0x20,0,0,16),(0x15,1,0,1),deny,
             (0x20,0,0,24),(0x54,0,0,(~(socket.SOCK_CLOEXEC|socket.SOCK_NONBLOCK))&0xffffffff),
             (0x15,1,0,socket.SOCK_STREAM),deny,(0x20,0,0,32),(0x15,1,0,0),deny,
             (0x20,0,0,0)]
    # sendto only on an already-connected descriptor (NULL address, 64 bits).
    rows += [(0x15,0,6,44),(0x20,0,0,48),(0x15,1,0,0),deny,
             (0x20,0,0,52),(0x15,1,0,0),deny,(0x20,0,0,0)]
    # Ordinary clone is needed for fork/threads; all namespace flags are refused.
    rows += [(0x15,0,4,56),(0x20,0,0,16),(0x45,0,1,0x7e020080),deny,
             (0x20,0,0,0)]
    # Force libc's reviewed legacy-clone fallback; never admit clone3 flags.
    rows += [(0x15,0,1,435),(0x06,0,0,0x50000|errno.ENOSYS)]
    # Policy may be queried, never weakened/replaced through prctl.
    rows += [(0x15,0,5,157),(0x20,0,0,16),(0x15,2,0,39),
             (0x15,1,0,3),deny,(0x20,0,0,0)]
    for number in sorted(_DENIED):rows += [(0x15,0,1,number),deny]
    rows.append((0x06,0,0,0x7fff0000))
    return rows


class Kernel:
    def __init__(self):
        _require(sys.platform=='linux' and platform.machine()=='x86_64',
                 'landlock_canary_platform_unreviewed')
        self.libc=ctypes.CDLL(None,use_errno=True)
        self.libc.syscall.restype=ctypes.c_long

    def call(self,number,*args,code):
        ctypes.set_errno(0)
        result=self.libc.syscall(ctypes.c_long(number),*args)
        if result<0:raise Blocked(code,ctypes.get_errno())
        return int(result)

    def abi(self):
        global _OBSERVED_ABI
        value=self.call(444,ctypes.c_void_p(),ctypes.c_size_t(0),ctypes.c_uint32(1),
                        code='landlock_canary_abi_unavailable')
        _OBSERVED_ABI=value
        if value<MIN_ABI:raise Blocked('landlock_canary_abi_too_old',abi=value)
        return value

    def restrict(self,image,work):
        self.call(157,ctypes.c_int(38),ctypes.c_ulong(1),ctypes.c_ulong(0),
                  ctypes.c_ulong(0),ctypes.c_ulong(0),code='landlock_canary_nnp_refused')
        attrs=_Ruleset(FS,0,SCOPES)
        rules=self.call(444,ctypes.byref(attrs),ctypes.c_size_t(ctypes.sizeof(attrs)),
                        ctypes.c_uint32(0),code='landlock_canary_ruleset_refused')
        try:
            for fd,access in ((image,(1<<2)|(1<<0)),(work,WORK)):
                rule=_PathRule(access,fd)
                self.call(445,ctypes.c_int(rules),ctypes.c_int(1),ctypes.byref(rule),
                          ctypes.c_uint32(0),code='landlock_canary_path_rule_refused')
            self.call(446,ctypes.c_int(rules),ctypes.c_uint32(0),
                      code='landlock_canary_enforcement_refused')
        finally:os.close(rules)

    def seccomp(self):
        rows=_filter();instructions=(_Filter*len(rows))(*(_Filter(*r) for r in rows))
        program=_Program(len(rows),instructions)
        self.call(157,ctypes.c_int(22),ctypes.c_ulong(2),ctypes.byref(program),
                  ctypes.c_ulong(0),ctypes.c_ulong(0),code='landlock_canary_seccomp_refused')


def _private(path):
    path=Path(path)
    _require(path.is_absolute() and '..' not in path.parts,'landlock_canary_private_path')
    _require(not any(path==Path(p) or Path(p) in path.parents for p in
        ('/srv/meme-machine','/etc/meme-machine','/var/lib/meme-machine-operations')),
        'landlock_canary_production_path')
    for node in (path,*path.parents):
        info=node.lstat()
        _require(not stat.S_ISLNK(info.st_mode),'landlock_canary_symlink')
        _require(not any((node/name).exists() for name in _MARKERS),
                 'landlock_canary_financial_ancestor')
    info=path.stat()
    _require(stat.S_ISDIR(info.st_mode) and info.st_uid==os.geteuid()
        and stat.S_IMODE(info.st_mode)==0o700,'landlock_canary_private_path')
    return path


def _scratch(path):
    path=_private(path);marker=path/'engineering-artifact.json';info=marker.lstat()
    _require(stat.S_ISREG(info.st_mode) and info.st_uid==os.geteuid()
             and info.st_size<=4096,'landlock_canary_scratch_marker')
    value=json.loads(marker.read_bytes())
    _require(type(value) is dict and value.get('classification')=='DISPOSABLE_OFFLINE_FIXTURE'
        and value.get('status')=='RUNNING' and value.get('pid')==os.getpid(),
        'landlock_canary_scratch_marker')
    return path


def _spec(row):
    _require(type(row) is dict and set(row)=={'scope','parent','peer','ipc','facts','abstract'},
             'landlock_canary_spec')
    _require(type(row['scope']) is str and len(row['scope'])<=4096,
             'landlock_canary_spec')
    _require(Path(row['scope']).is_absolute() and '..' not in Path(row['scope']).parts,
             'landlock_canary_spec')
    _require(all(type(row[k]) is int and 1<row[k]<2**31 for k in ('parent','peer'))
        and all(type(row[k]) is int and 2<row[k]<65536 for k in ('ipc','facts'))
        and row['ipc']!=row['facts'],'landlock_canary_spec')
    _require(row['abstract']=='mm-landlock-canary-'+str(row['parent']),
             'landlock_canary_spec')
    return row


def _fixed_fds(ipc,facts):
    global _FAILURE_FD
    with socket.socket(fileno=os.dup(ipc)) as channel:
        _require(channel.family==socket.AF_UNIX
            and channel.getsockopt(socket.SOL_SOCKET,socket.SO_TYPE)==socket.SOCK_STREAM
            and channel.getsockname() in ('',b'') and channel.getpeername() in ('',b''),
            'landlock_canary_anonymous_channel')
    _require(stat.S_ISFIFO(os.fstat(facts).st_mode)
        and fcntl.fcntl(facts,fcntl.F_GETFL)&os.O_ACCMODE==os.O_RDONLY
        and os.readlink('/proc/self/fd/'+str(facts)).startswith('pipe:['),
        'landlock_canary_anonymous_facts')
    _FAILURE_FD=ipc
    a=fcntl.fcntl(ipc,fcntl.F_DUPFD_CLOEXEC,16)
    b=fcntl.fcntl(facts,fcntl.F_DUPFD_CLOEXEC,16)
    os.dup2(a,3,inheritable=False);os.dup2(b,4,inheritable=False)
    _FAILURE_FD=3
    for name in os.listdir('/proc/self/fd'):
        fd=int(name)
        if fd in (3,4):continue
        try:os.close(fd)
        except OSError as error:
            if error.errno!=errno.EBADF:raise
    _require(os.listdir('/proc/self/task')==[str(os.getpid())],
             'landlock_canary_single_thread')


def _empty_effective_caps(raw):
    if type(raw) is not bytes or len(raw)>65536:return False
    try:lines=raw.decode('ascii').splitlines()
    except UnicodeError:return False
    wanted={'CapEff','CapPrm','CapAmb'};values={}
    for line in lines:
        name,separator,value=line.partition(':')
        if name not in wanted:continue
        value=value.strip()
        if name in values or not re.fullmatch('[0-9a-fA-F]{1,16}',value):return False
        values[name]=int(value,16)
    return set(values)==wanted and not any(values.values())


def _base(state='BLOCKED'):
    return dict(schema='landlock-capability-canary-v1',state=state,provider_calls=0,
        production_state_writes=0,financial_authority=False,fallback_allowed=False,
        production_equivalent=False,full_market_speed_proven=False,
        actual_service_restrictions_verified=False,private_shm=False,
        private_network_namespace=False,private_pid_namespace=False,
        host_metadata_hidden=False,real_spawn_pool=False,native_execution=False)


_SAFE_CODES=frozenset(('landlock_canary_abi_unavailable','landlock_canary_abi_too_old',
    'landlock_canary_ruleset_refused','landlock_canary_path_rule_refused',
    'landlock_canary_enforcement_refused','landlock_canary_seccomp_refused',
    'landlock_canary_platform_unreviewed','landlock_canary_probe_failed',
    'landlock_canary_wall_expired','landlock_canary_result_bound',
    'landlock_canary_denial_errno','landlock_canary_denial_failed',
    'landlock_canary_incomplete','landlock_canary_unprivileged_required'))


def _project(value,exit_code):
    """No child-controlled text, nested unknown keys or permissive PASS copy."""
    result=_base();result['child_exit']=exit_code
    if type(value) is not dict:
        result['code']='landlock_canary_probe_failed';return result
    abi=value.get('landlock_abi')
    if type(abi) is int and 0<=abi<=65535:result['landlock_abi']=abi
    expected=_base()
    valid_base=all(type(value.get(k)) is type(v) and value.get(k)==v
                   for k,v in expected.items() if k!='state')
    checks=value.get('checks')
    if (valid_base and value.get('state')=='LANDLOCK_CANARY_ENFORCEMENT_VERIFIED'
            and set(value)==set(expected)|{'landlock_abi','checks'}
            and type(abi) is int and MIN_ABI<=abi<=65535
            and type(exit_code) is int and exit_code==0
            and type(checks) is dict and checks.keys()==CHECKS
            and all(part is True for part in checks.values())):
        result.update(state=value['state'],checks=dict(checks));return result
    code=value.get('code')
    result['code']=code if type(code) is str and code in _SAFE_CODES else 'landlock_canary_probe_failed'
    number=value.get('error_number')
    if type(number) is int and 0<number<4096:result['error_number']=number
    check=value.get('failed_check')
    if type(check) is str and check in CHECKS:result['failed_check']=check
    return result


def _failure(error):
    result=_base()
    result['code']=(error.code if isinstance(error,Blocked) and type(error.code) is str
        and error.code in _SAFE_CODES else 'landlock_canary_probe_failed')
    if type(_OBSERVED_ABI) is int and 0<=_OBSERVED_ABI<=65535:
        result['landlock_abi']=_OBSERVED_ABI
    if isinstance(error,Blocked):
        if type(error.number) is int and 0<error.number<4096:result['error_number']=error.number
        if type(error.abi) is int and 0<=error.abi<=65535:result['landlock_abi']=error.abi
        if type(error.check) is str and error.check in CHECKS:result['failed_check']=error.check
    return result


class _ReportChannel:
    """Publish the bounded first failure while its validated channel is open."""
    def __init__(self,channel):self.channel=channel
    def __enter__(self):
        self.channel.settimeout(1)
        return self.channel
    def __exit__(self,kind,error,traceback):
        global _ALREADY_REPORTED
        try:
            if error is not None:
                self.channel.sendall(json.dumps(_failure(error),sort_keys=True).encode()+b'\n')
                _ALREADY_REPORTED=True
        except BaseException:pass
        finally:self.channel.close()
        return False


def _probe(spec):
    spec=_spec(spec);_require(os.geteuid()!=0,'landlock_canary_nonroot_required')
    scope=_private(spec['scope']);work=_private(scope/'work');image=scope/'image'
    _require(os.getppid()==spec['parent'],'landlock_canary_parent_changed')
    _fixed_fds(spec['ipc'],spec['facts'])
    checks={}
    for fd in (0,1,2):
        try:os.fstat(fd)
        except OSError as error:_require(error.errno==errno.EBADF,'landlock_canary_fds')
        else:raise Blocked('landlock_canary_fds')
    checks['inherited_fds_closed']=True
    with open('/proc/self/status','rb') as status:raw=status.read(65537)
    uid,gid=os.geteuid(),os.getegid()
    _require(uid>0 and gid>0 and os.getresuid()==(uid,uid,uid)
        and os.getresgid()==(gid,gid,gid) and _empty_effective_caps(raw),
        'landlock_canary_unprivileged_required')
    checks['effective_caps_empty']=True
    kernel=Kernel()
    kernel.call(157,ctypes.c_int(1),ctypes.c_ulong(signal.SIGKILL),ctypes.c_ulong(0),
        ctypes.c_ulong(0),ctypes.c_ulong(0),code='landlock_canary_parent_death_refused')
    _require(os.getppid()==spec['parent'],'landlock_canary_parent_changed')
    for kind,limit in ((resource.RLIMIT_CORE,0),(resource.RLIMIT_NOFILE,128),
                       (resource.RLIMIT_FSIZE,1024*1024),(resource.RLIMIT_CPU,10)):
        soft,hard=resource.getrlimit(kind)
        bound=limit if hard==resource.RLIM_INFINITY else min(limit,hard)
        resource.setrlimit(kind,(bound,bound))
    abi=kernel.abi()
    result=_base();result['landlock_abi']=abi
    with _ReportChannel(socket.socket(fileno=3)) as channel:
        def denied(name,action,*,exact=False):
            try:action()
            except OSError as error:
                allowed=(errno.EPERM,) if exact else (errno.EPERM,errno.EACCES)
                if error.errno not in allowed:
                    raise Blocked('landlock_canary_denial_errno',error.errno,check=name) from None
                checks[name]=True
            else:raise Blocked('landlock_canary_denial_failed',check=name)
        def syscall(number,*args):
            ctypes.set_errno(0);value=kernel.libc.syscall(ctypes.c_long(number),*args)
            if value<0:raise OSError(ctypes.get_errno(),'fixed canary syscall')
            return value
        image_info=image.lstat()
        _require(stat.S_ISREG(image_info.st_mode) and image_info.st_uid==os.geteuid()
            and image_info.st_nlink==1 and stat.S_IMODE(image_info.st_mode)==0o700
            and image_info.st_size==len(_elf())
            and image.read_bytes()==_elf(),'landlock_canary_image')
        image_fd=os.open(image,os.O_PATH|os.O_NOFOLLOW|os.O_CLOEXEC)
        work_fd=os.open(work,os.O_PATH|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
        try:
            _require((os.fstat(image_fd).st_dev,os.fstat(image_fd).st_ino)==
                (image_info.st_dev,image_info.st_ino),'landlock_canary_image_changed')
            _require((os.fstat(work_fd).st_dev,os.fstat(work_fd).st_ino)==
                (work.lstat().st_dev,work.lstat().st_ino),'landlock_canary_work_changed')
            kernel.restrict(image_fd,work_fd)
        finally:os.close(image_fd);os.close(work_fd)
        # These happen BEFORE seccomp, proving Landlock independently.
        _require(image.read_bytes()==_elf(),'landlock_canary_image_read')
        denied('fs_read',lambda:(scope/'outside').read_bytes())
        denied('fs_write',lambda:(scope/'outside').write_bytes(b'wrong'))
        denied('readonly_image',lambda:image.write_bytes(b'wrong'))
        denied('proc_data',lambda:Path('/proc/'+str(spec['peer'])+'/environ').read_bytes())
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
            denied('abstract_scope',lambda:client.connect('\0'+spec['abstract']))
        denied('signal_scope',lambda:os.kill(spec['peer'],signal.SIGUSR1))
        # Pre-create only child-owned local descriptors, then individually test
        # connect/bind/listen/accept; no socket() refusal can mask those checks.
        loose=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        bound=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        bound.bind(str(work/'bound.sock'))
        listener=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        listener.bind(str(work/'listener.sock'));listener.listen(1)
        pair=socket.socketpair(socket.AF_UNIX,socket.SOCK_STREAM)
        pair[0].sendall(b'x')
        kernel.seccomp()
        try:
            denied('seccomp_socket',lambda:socket.socket(socket.AF_INET,socket.SOCK_STREAM),exact=True)
            denied('seccomp_connect',lambda:loose.connect(str(scope/'outside.sock')),exact=True)
            denied('seccomp_bind',lambda:loose.bind(str(work/'denied.sock')),exact=True)
            denied('seccomp_listen',lambda:bound.listen(1),exact=True)
            denied('seccomp_accept',lambda:listener.accept(),exact=True)
            denied('seccomp_sendmsg',lambda:pair[0].sendmsg([b'x']),exact=True)
            denied('seccomp_recvmsg',lambda:pair[1].recvmsg(1),exact=True)
            denied('seccomp_ptrace',lambda:syscall(101,ctypes.c_long(0x4206),
                ctypes.c_long(spec['peer']),ctypes.c_void_p(),ctypes.c_void_p()),exact=True)
            for name,number in (('seccomp_process_vm_read',310),('seccomp_process_vm_write',311)):
                denied(name,lambda n=number:syscall(n,ctypes.c_long(spec['peer']),
                    ctypes.c_void_p(),ctypes.c_ulong(0),ctypes.c_void_p(),
                    ctypes.c_ulong(0),ctypes.c_ulong(0)),exact=True)
            denied('seccomp_pidfd_getfd',lambda:syscall(438,ctypes.c_int(-1),
                ctypes.c_int(0),ctypes.c_uint(0)),exact=True)
            denied('seccomp_metadata',lambda:os.chmod(scope/'outside',0o777),exact=True)
            denied('seccomp_namespace',lambda:syscall(272,ctypes.c_int(0)),exact=True)
            denied('seccomp_io_uring',lambda:syscall(425,ctypes.c_uint(0),ctypes.c_void_p()),exact=True)
            channel.sendall(b'landlock canary\n')
            _require(channel.recv(32)==b'parent acknowledged','landlock_canary_ipc')
            checks['anonymous_parent_ipc']=True
            _require(os.read(4,32)==b'fixed sizing fixture','landlock_canary_facts')
            checks['facts_pipe']=True;os.close(4)
            local_a,local_b=socket.socketpair(socket.AF_UNIX,socket.SOCK_STREAM)
            with local_a,local_b:
                local_a.sendall(b'local');checks['internal_socketpair']=local_b.recv(5)==b'local'
            read_fd,write_fd=os.pipe()
            try:
                os.write(write_fd,b'pipe');checks['internal_pipe']=os.read(read_fd,4)==b'pipe'
            finally:os.close(read_fd);os.close(write_fd)
            db=sqlite3.connect(work/'canary.sqlite')
            try:
                db.execute('PRAGMA journal_mode=WAL');db.execute('PRAGMA synchronous=FULL')
                db.execute('CREATE TABLE fixture(value INTEGER)')
                db.execute('INSERT INTO fixture VALUES(42)');db.commit()
                checks['sqlite_FULL_WAL']=(db.execute('SELECT value FROM fixture').fetchone()==(42,)
                    and db.execute('PRAGMA synchronous').fetchone()==(2,))
            finally:db.close()
            pid=os.fork()
            if pid==0:
                try:
                    (work/'descendant').write_bytes(b'private')
                    try:(scope/'outside').read_bytes()
                    except PermissionError:os.execve(image,[str(image)],{})
                    os._exit(3)
                except BaseException:os._exit(4)
            _,status=os.waitpid(pid,0)
            checks['descendant_inheritance']=os.waitstatus_to_exitcode(status)==0
            checks['copied_fixture_exec']=checks['descendant_inheritance']
            checks['no_new_privileges']=syscall(157,ctypes.c_int(39),ctypes.c_ulong(0),
                ctypes.c_ulong(0),ctypes.c_ulong(0),ctypes.c_ulong(0))==1
            if set(checks)!=CHECKS or any(value is not True for value in checks.values()):
                failed=next((key for key in sorted(CHECKS) if checks.get(key) is not True),None)
                raise Blocked('landlock_canary_incomplete',check=failed)
            result.update(state='LANDLOCK_CANARY_ENFORCEMENT_VERIFIED',checks=checks)
        finally:
            for value in (loose,bound,listener,*pair):value.close()
        channel.sendall(json.dumps(result,sort_keys=True).encode()+b'\n')
    return 0


def verified(row):
    return (type(row) is dict and row.get('state')=='LANDLOCK_CANARY_ENFORCEMENT_VERIFIED'
        and type(row.get('landlock_abi')) is int and MIN_ABI<=row['landlock_abi']<=65535
        and type(row.get('checks')) is dict and row['checks'].keys()==CHECKS
        and all(x is True for x in row['checks'].values())
        and type(row.get('child_exit')) is int and row['child_exit']==0
        and all(row.get(k) is True for k in PARENT_CHECKS)
        and all(row.get(k)==v and type(row.get(k)) is type(v)
                for k,v in _base().items() if k!='state'))


def _fd_snapshot():
    result={}
    for name in os.listdir('/proc/self/fd'):
        try:
            info=os.fstat(int(name));result[int(name)]=(info.st_dev,info.st_ino,info.st_mode)
        except OSError as error:
            if error.errno!=errno.EBADF:raise
    return result


def canary(scope,*,seconds=15):
    """Run only this fixed disposable probe in an admitted Scratch directory."""
    scope=_scratch(scope)
    _require(os.geteuid()!=0,'landlock_canary_nonroot_required')
    _require(type(seconds) in (int,float) and 0<seconds<=20,'landlock_canary_wall_bound')
    _require(not any((scope/name).exists() for name in ('work','image','outside','outside.sock')),
             'landlock_canary_scope_used')
    before_fds=_fd_snapshot();cwd=Path.cwd()
    namespaces={k:os.readlink('/proc/self/ns/'+k) for k in ('user','mnt','pid','net','ipc')}
    (scope/'work').mkdir(mode=0o700)
    (scope/'image').write_bytes(_elf());(scope/'image').chmod(0o700)
    (scope/'outside').write_bytes(b'outside disposable fixture');(scope/'outside').chmod(0o600)
    parent,child=socket.socketpair();facts,write_facts=os.pipe()
    abstract='mm-landlock-canary-'+str(os.getpid());peer=None;probe=None;result=_base()
    with parent,child,socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as hidden,\
            socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as outside:
        hidden.bind('\0'+abstract);hidden.listen(1)
        outside.bind(str(scope/'outside.sock'));outside.listen(1)
        # Separate disposable signal/proc target; never a service/runner process.
        peer=subprocess.Popen([sys.executable,'-I','-B','-S','-c',
            'import signal,time;signal.signal(signal.SIGUSR1,lambda *_:None);time.sleep(20)'],
            stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env={})
        try:
            os.write(write_facts,b'fixed sizing fixture');os.close(write_facts);write_facts=None
            spec=_spec(dict(scope=str(scope),parent=os.getpid(),peer=peer.pid,
                ipc=child.fileno(),facts=facts,abstract=abstract))
            probe=subprocess.Popen([sys.executable,'-I','-B','-S',str(Path(__file__).resolve()),
                '--probe',json.dumps(spec,separators=(',',':'))],stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env={},close_fds=True,
                pass_fds=(child.fileno(),facts),start_new_session=True)
            child.close();os.close(facts);facts=None
            deadline=time.monotonic()+seconds;buffer=bytearray();acknowledged=False
            while True:
                remaining=deadline-time.monotonic()
                _require(remaining>0,'landlock_canary_wall_expired')
                ready,_,_=select.select([parent],[],[],min(.2,remaining))
                if not ready:continue
                data=parent.recv(min(4096,MAX_RESULT+1-len(buffer)))
                if not data:break
                buffer.extend(data);_require(len(buffer)<=MAX_RESULT,'landlock_canary_result_bound')
                if not acknowledged and buffer.startswith(b'landlock canary\n'):
                    del buffer[:len(b'landlock canary\n')];parent.sendall(b'parent acknowledged');acknowledged=True
            probe.wait(timeout=max(.001,deadline-time.monotonic()))
            result=_project(json.loads(buffer),probe.returncode)
        except (Blocked,OSError,ValueError,subprocess.SubprocessError) as error:
            result=_base();result['code']=(error.code if isinstance(error,Blocked)
                and error.code in _SAFE_CODES else 'landlock_canary_probe_failed')
        finally:
            if probe is not None and probe.poll() is None:
                try:os.killpg(probe.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                probe.wait(timeout=2)
            if peer is not None:
                peer.kill();peer.wait(timeout=2)
            for fd in (facts,write_facts):
                if fd is not None:os.close(fd)
    result.update(parent_cwd_unchanged=Path.cwd()==cwd,
        parent_namespaces_unchanged=all(os.readlink('/proc/self/ns/'+k)==v for k,v in namespaces.items()),
        parent_open_descriptors_preserved=all(_fd_snapshot().get(k)==v for k,v in before_fds.items()),
        outside_canary_unchanged=(scope/'outside').read_bytes()==b'outside disposable fixture'
            and (scope/'image').read_bytes()==_elf()
            and stat.S_IMODE((scope/'outside').stat().st_mode)==0o600)
    if not verified(result):result['state']='BLOCKED';result.setdefault('code','landlock_canary_enforcement_unverified')
    return result


def main():
    try:
        _require(len(sys.argv)==3 and sys.argv[1]=='--probe' and len(sys.argv[2])<=8192,
                 'landlock_canary_fixed_entry')
        return _probe(json.loads(sys.argv[2]))
    except BaseException as error:
        # Failure output uses only a descriptor whose anonymous origin was
        # validated; never guess that descriptor3 is a socket after early failure.
        try:
            if _ALREADY_REPORTED:return 2
            _require(_FAILURE_FD is not None,'landlock_canary_failure_channel_unavailable')
            with socket.socket(fileno=os.dup(_FAILURE_FD)) as channel:
                channel.settimeout(1)
                channel.sendall(json.dumps(_failure(error),sort_keys=True).encode()+b'\n')
        except BaseException:pass
        return 2


if __name__=='__main__':raise SystemExit(main())
