"""Fixed copied-native ABI6+ Landlock and default-deny x86_64 syscall policy.

Only the explicit native launcher calls this before its fixed private exec. This
module does not select a backend, dispatch work, grant provider/funding authority
or certify native readiness. The static Landlock canary remains independent.
"""
import ctypes
import errno
import fcntl
import os
from pathlib import Path
import platform
import resource
import signal
import socket
import stat
import sys

from . import landlock_canary as abi

PROFILE = 'native-landlock-abi6-x86_64-v1'
ALLOW = 0x7fff0000
DENY = 0x50000 | errno.EPERM
KILL = 0x80000000
# File/process queries, owned memory/FDs, clocks and ordinary private files. All
# socket destinations, process_vm/vector messages, scheduler/ioprio/PID setters,
# namespaces, metadata mutations, privilege changes and future syscalls default
# to EPERM. Special cases below do not belong in this unconditional set.
_SIMPLE = frozenset((0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,17,18,19,20,
    21,22,23,24,25,26,27,28,32,33,34,35,36,37,38,39,51,52,57,58,59,60,
    61,63,73,74,75,76,77,78,79,80,81,82,83,84,85,86,87,88,89,95,96,97,
    98,99,100,102,104,107,108,110,111,115,118,120,
    131,137,138,186,201,202,213,217,218,228,229,230,231,232,233,
    257,262,263,264,265,266,267,269,270,271,273,281,
    302,318,332,334))


def _ret(value): return (0x06,0,0,value)
def _load(offset): return (0x20,0,0,offset)
def _equal(value): return [(0x15,1,0,value),_ret(DENY)]
def _argument(index,value):
    return [_load(20+8*index),*_equal(0),_load(16+8*index),*_equal(value)]


def _case(number,body):
    # Every admitted case returns locally, keeping conditional jumps <=255.
    assert len(body)<256
    return [_load(0),(0x15,0,len(body),number),*body]


def _choice(index, values):
    rows=[_load(20+8*index),*_equal(0),_load(16+8*index)]
    for value in values: rows += [(0x15,0,1,value),_ret(ALLOW)]
    return rows+[_ret(DENY)]


def _flags(index,mask):
    return [_load(20+8*index),*_equal(0),_load(16+8*index),
        (0x54,0,0,(~mask)&0xffffffff),*_equal(0),_ret(ALLOW)]


def filter_rows(*, pid):
    """Return fixed classic-BPF rows; only the installing native PID varies."""
    if type(pid) is not int or not 1<pid<2**31: raise ValueError('native_policy_pid')
    rows=[_load(4),(0x15,1,0,0xc000003e),_ret(KILL)]
    rows += _case(435,[_ret(0x50000|errno.ENOSYS)]) # libc legacy-clone fallback
    # Actual libc fork/vfork/thread shapes only. CLONE_PARENT, namespace and
    # otherwise unreviewed flag combinations cannot change ownership.
    rows += _case(56,_choice(0,(17,0x1200011,0x4111,0x3d0f00)))
    rows += _case(53,[*_argument(0,socket.AF_UNIX),_load(28),*_equal(0),
        _load(24),(0x54,0,0,(~(socket.SOCK_CLOEXEC|socket.SOCK_NONBLOCK))&0xffffffff),
        *_equal(socket.SOCK_STREAM),*_argument(2,0),_ret(ALLOW)])
    # CPython socket.send/recv use sendto/recvfrom with NULL address fields.
    rows += _case(44,[*_argument(4,0),*_argument(5,0),_ret(ALLOW)])
    rows += _case(45,[*_argument(4,0),*_argument(5,0),_ret(ALLOW)])
    rows += _case(48,_choice(1,(socket.SHUT_RD,socket.SHUT_WR,socket.SHUT_RDWR)))
    rows += _case(55,[*_argument(1,socket.SOL_SOCKET),
        *_choice(2,(socket.SO_TYPE,socket.SO_ERROR))])
    # No F_SETOWN/F_SETSIG/F_NOTIFY, async I/O ownership or lease authority.
    commands=[]
    for command in (fcntl.F_DUPFD,fcntl.F_DUPFD_CLOEXEC,fcntl.F_GETFD,fcntl.F_GETFL,
                    fcntl.F_GETLK,fcntl.F_SETLK,fcntl.F_SETLKW):
        commands += [(0x15,0,1,command),_ret(ALLOW)]
    descriptor_flags=[_load(36),*_equal(0),_load(32),
        (0x54,0,0,(~fcntl.FD_CLOEXEC)&0xffffffff),*_equal(0),_ret(ALLOW)]
    commands += [(0x15,0,len(descriptor_flags),fcntl.F_SETFD),*descriptor_flags]
    # F_SETFL changes only append/nonblocking on already-owned descriptors.
    flags=os.O_ACCMODE|os.O_APPEND|os.O_NONBLOCK|0x8000
    file_flags=[_load(36),*_equal(0),_load(32),
        (0x54,0,0,(~flags)&0xffffffff),*_equal(0),_ret(ALLOW)]
    commands += [(0x15,0,len(file_flags),fcntl.F_SETFL),*file_flags,_ret(DENY)]
    rows += _case(72,[_load(28),*_equal(0),_load(24),*commands])
    # FIONBIO is the only socket ioctl used by native read timeouts. Inherited
    # descriptors cannot issue terminal/device, TIOCSTI or block-device ioctls.
    rows += _case(16,[*_argument(1,0x5421),_ret(ALLOW)])
    # libc's self queries remain available. The unchanged history initializer
    # lowers only AS/NOFILE, beneath hard ceilings installed before this policy.
    # BPF cannot inspect an rlimit pointer; the nonroot kernel hard ceiling is
    # therefore part of the explicit launch contract, not inferred here.
    rows += _case(302,[*_argument(0,0),_load(36),(0x15,0,3,0),_load(32),
        (0x15,0,1,0),_ret(ALLOW),*_choice(1,(resource.RLIMIT_AS,resource.RLIMIT_NOFILE))])
    rows += _case(140,[*_argument(0,os.PRIO_PROCESS),*_argument(1,0),_ret(ALLOW)])
    rows += _case(141,[*_argument(0,os.PRIO_PROCESS),*_argument(1,0),*_argument(2,5),_ret(ALLOW)])
    rows += _case(204,[*_argument(0,0),_ret(ALLOW)]) # own CPU-affinity query
    # Native pool termination only. Landlock signal scope independently keeps
    # positive foreign PIDs outside this descendant domain inaccessible.
    rows += _case(62,[_load(20),*_equal(0),_load(16),(0x25,1,0,0),_ret(DENY),
        (0x35,0,1,2**31),_ret(DENY),*_choice(1,(0,signal.SIGTERM,signal.SIGKILL))])
    rows += _case(234,[*_argument(0,pid),*_choice(2,(0,signal.SIGTERM,signal.SIGKILL,signal.SIGABRT))])
    rows += _case(436,_choice(2,(0,4))) # close_range, no UNSHARE
    rows += _case(158,_choice(0,(0x1002,0x1003))) # own TLS SET_FS/GET_FS
    rows += _case(291,_flags(0,os.O_CLOEXEC))
    rows += _case(292,_flags(2,os.O_CLOEXEC))
    rows += _case(293,_flags(1,os.O_CLOEXEC|os.O_NONBLOCK))
    # Query NNP/dumpability/seccomp, read PDEATHSIG, or arm SIGKILL only.
    control=[]
    for option in (3,21,39):control += [(0x15,0,1,option),_ret(ALLOW)]
    control += [(0x15,0,19,2),*_argument(2,0),*_argument(3,0),*_argument(4,0),_ret(ALLOW)]
    control += [(0x15,0,25,1),*_argument(1,signal.SIGKILL),*_argument(2,0),
        *_argument(3,0),*_argument(4,0),_ret(ALLOW),_ret(DENY)]
    rows += _case(157,[_load(20),*_equal(0),_load(16),*control])
    for number in sorted(_SIMPLE-{302}): rows += _case(number,[_ret(ALLOW)])
    rows.append(_ret(DENY))
    return tuple(rows)


class NativePolicyBlocked(RuntimeError):
    def __init__(self,code,number=None):
        self.code,self.number=code,number
        super().__init__(code)


class NativePolicy:
    """One installer, no policy bypass/fallback and no inherited rule handles."""
    def __init__(self):
        if sys.platform!='linux' or platform.machine()!='x86_64':
            raise NativePolicyBlocked('native_policy_platform')
        self.libc=ctypes.CDLL(None,use_errno=True)
        self.libc.syscall.restype=ctypes.c_long

    def call(self,number,*args,code):
        ctypes.set_errno(0)
        value=self.libc.syscall(ctypes.c_long(number),*args)
        if value<0: raise NativePolicyBlocked(code,ctypes.get_errno())
        return int(value)

    def seccomp(self):
        rows=filter_rows(pid=os.getpid())
        program=(abi._Filter*len(rows))(*(abi._Filter(*row) for row in rows))
        descriptor=abi._Program(len(rows),program)
        self.call(157,ctypes.c_int(22),ctypes.c_ulong(2),ctypes.byref(descriptor),
            ctypes.c_ulong(0),ctypes.c_ulong(0),code='native_policy_seccomp_refused')

    def install(self,binding,work):
        from .isolated_native_landlock_image import PinnedNativeImage
        if type(binding) is not PinnedNativeImage: raise NativePolicyBlocked('native_policy_image_required')
        if os.geteuid()==0 or not abi._empty_effective_caps(Path('/proc/self/status').read_bytes()):
            raise NativePolicyBlocked('native_policy_unprivileged_required')
        if os.listdir('/proc/self/task')!=[str(os.getpid())]:
            raise NativePolicyBlocked('native_policy_single_thread_required')
        work=abi._private(work)
        held=[]
        try:
            rules=list(binding.rules())
            for path,rights,directory in ((work,abi.WORK,True),
                (Path('/proc/self/stat'),1<<2,False),
                (Path('/proc/sys/kernel/random/boot_id'),1<<2,False)):
                flags=os.O_PATH|os.O_NOFOLLOW|os.O_CLOEXEC|(os.O_DIRECTORY if directory else 0)
                fd=os.open(path,flags);held.append(fd);info=os.fstat(fd)
                if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
                    raise NativePolicyBlocked('native_policy_path_inode')
                current=path.lstat()
                if (current.st_dev,current.st_ino)!=(info.st_dev,info.st_ino):
                    raise NativePolicyBlocked('native_policy_path_changed')
                if directory and (info.st_uid!=os.geteuid() or stat.S_IMODE(info.st_mode)!=0o700):
                    raise NativePolicyBlocked('native_policy_work_owner')
                rules.append(abi._PathRule(rights,fd))
            version=self.call(444,ctypes.c_void_p(),ctypes.c_size_t(0),ctypes.c_uint32(1),
                code='native_policy_abi_unavailable')
            if version<6: raise NativePolicyBlocked('native_policy_abi_too_old')
            self.call(157,ctypes.c_int(38),ctypes.c_ulong(1),ctypes.c_ulong(0),
                ctypes.c_ulong(0),ctypes.c_ulong(0),code='native_policy_nnp_refused')
            attributes=abi._Ruleset(abi.FS,0,abi.SCOPES)
            ruleset=self.call(444,ctypes.byref(attributes),ctypes.c_size_t(ctypes.sizeof(attributes)),
                ctypes.c_uint32(0),code='native_policy_ruleset_refused')
            held.append(ruleset)
            for rule in rules:
                row=abi._PathRule(rule.access,rule.descriptor) if hasattr(rule,'descriptor') else rule
                self.call(445,ctypes.c_int(ruleset),ctypes.c_int(1),ctypes.byref(row),
                    ctypes.c_uint32(0),code='native_policy_path_refused')
            self.call(446,ctypes.c_int(ruleset),ctypes.c_uint32(0),code='native_policy_restrict_refused')
            self.seccomp()
            return version
        finally:
            primary=sys.exc_info()[0] is not None;failure=None
            for fd in reversed(held):
                try:os.close(fd)
                except OSError as error:
                    if failure is None:failure=error
            if failure is not None and not primary:raise failure
