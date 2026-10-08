"""Independent Linux supervision for the existing finite proof.

cgroup v2 bounds memory/CPU and contains descendants. Seccomp notification admits
file writes before the kernel executes them; polling /proc alone cannot bound a
sudden write burst. This module creates no group/filter until explicitly called.
"""
import array
from collections import deque
import ctypes as C
import ctypes.util
import errno
import os
import math
from pathlib import Path
import platform
import select
import signal
import socket
import stat
import struct
import time
import threading

RECEIPT_RESERVE=2*1024*1024
CGROOT=Path('/sys/fs/cgroup')


class HostUnavailable(RuntimeError):pass


class LinuxGroup:
    def __init__(self, limits, *, root=CGROOT, output=None):
        if platform.system()!='Linux' or platform.machine()!='x86_64':raise HostUnavailable('linux_x86_64_required')
        self.path=root/('mm-provider-proof-'+str(os.getpid())+'-'+str(time.monotonic_ns()))
        self.limits=limits;self.created=False
        try:
            controllers=set((root/'cgroup.controllers').read_text().split())
            enabled=set((root/'cgroup.subtree_control').read_text().split())
            if not {'cpu','memory','io'}<=controllers:raise HostUnavailable('cgroup_controllers_unavailable')
            if not {'cpu','memory','io'}<=enabled:raise HostUnavailable('delegated_cpu_memory_io_controllers_required')
            self.path.mkdir();self.created=True
            (self.path/'memory.max').write_text(str(limits['proof_group_rss_bytes']-128*1024*1024))
            (self.path/'memory.swap.max').write_text('0')
            # Hard sustained CPU admission, independently measured against the
            # contractual 30-second window too. No application thread needed.
            (self.path/'cpu.max').write_text('175000 100000')
            device=os.stat(output or '/tmp').st_dev
            major,minor=os.major(device),os.minor(device);block=Path(f'/sys/dev/block/{major}:{minor}')
            if (block/'partition').exists():major,minor=map(int,(block/'../dev').read_text().strip().split(':'))
            if not (Path(f'/sys/dev/block/{major}:{minor}')/'queue/max_sectors_kb').exists():
                raise HostUnavailable('block_io_accounting_required')
            self.device=f'{major}:{minor}'
            # The independent kernel rate guard caps physical writeback, including
            # mapped SQLite WAL-index pages and exited workers. A 16 MiB margin
            # covers the one-second throttle slice plus the supervisor receipt.
            rate=(limits['cumulative_process_write_bytes']-16*1024*1024)//300
            self.io_rate=rate
            (self.path/'io.max').write_text(self.device+f' wbps={rate}')
            if not (self.path/'cgroup.kill').exists():raise HostUnavailable('cgroup_kill_unavailable')
        except (OSError,ValueError) as exc:
            self.close();raise HostUnavailable('cgroup_enforcement_unavailable') from None
    def attach_self(self):
        (self.path/'cgroup.procs').write_text(str(os.getpid()))
    def pids(self):return [int(p) for p in (self.path/'cgroup.procs').read_text().split()]
    def populated(self):return 'populated 1' in (self.path/'cgroup.events').read_text()
    def kill(self):
        (self.path/'cgroup.kill').write_text('1')
    def cpu(self):
        rows=dict(line.split() for line in (self.path/'cpu.stat').read_text().splitlines())
        return int(rows['usage_usec'])/1e6
    def writes(self):
        rows={line.split()[0]:dict(field.split('=') for field in line.split()[1:])
              for line in (self.path/'io.stat').read_text().splitlines()}
        # Count all devices: unknown additional output devices fail closed.
        active={dev for dev,v in rows.items() if int(v.get('wbytes',0))}
        if active-{self.device}:raise HostUnavailable('unapproved_output_device')
        return sum(int(v.get('wbytes',0)) for v in rows.values())
    def memory_events(self):
        return {k:int(v) for k,v in (line.split() for line in (self.path/'memory.events').read_text().splitlines())}
    def close(self):
        if self.created:
            try:self.path.rmdir();self.created=False
            except OSError:pass


def output_stock(root):
    total=0;seen=set();todo=[Path(root)];entries=0;deadline=time.monotonic()+.05
    while todo:
        base=todo.pop()
        with os.scandir(base) as scan:
            for entry in scan:
                entries+=1
                if entries>16384 or time.monotonic()>deadline:raise HostUnavailable('output_measurement_bound')
                try:q=entry.stat(follow_symlinks=False)
                except FileNotFoundError:continue
                if stat.S_ISLNK(q.st_mode):raise HostUnavailable('output_symlink')
                if stat.S_ISDIR(q.st_mode):todo.append(Path(entry.path))
                key=(q.st_dev,q.st_ino)
                if stat.S_ISREG(q.st_mode) and key not in seen:total+=q.st_size;seen.add(key)
    return total


def supervisor_sample():
    fields=Path('/proc/self/stat').read_text().rsplit(')',1)[1].split()
    io={k:int(v) for k,v in (line.split(':') for line in Path('/proc/self/io').read_text().splitlines())}
    return dict(rss=int(fields[21])*os.sysconf('SC_PAGE_SIZE'),
        cpu=(int(fields[11])+int(fields[12]))/os.sysconf('SC_CLK_TCK'),writes=io['write_bytes'])


def group_sample(group,root):
    """Sum every process RSS; CPU includes exited descendants via cgroup stats."""
    pids=group.pids();rss=0;writes=0;processes=[]
    for pid in pids:
        try:
            fields=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()
            if fields[0]=='Z':continue
            memory=int(fields[21])*os.sysconf('SC_PAGE_SIZE')
            ios={k:int(v) for k,v in (line.split(':') for line in Path(f'/proc/{pid}/io').read_text().splitlines())}
            rss+=memory;writes+=ios['write_bytes'];processes.append(dict(pid=pid,rss_bytes=memory,write_bytes=ios['write_bytes']))
        except FileNotFoundError:continue # PID exited; cgroup CPU + write reservations retain history
        except (OSError,ValueError,KeyError,IndexError):raise HostUnavailable('process_group_measurement_unavailable') from None
    try:
        memory={k:int(v.split()[0])*1024 for k,v in (line.split(':') for line in Path('/proc/meminfo').read_text().splitlines())}
        return dict(at=time.monotonic(),pids=pids,processes=processes,group_rss_bytes=rss,
          cpu_seconds=group.cpu(),cumulative_process_write_bytes=group.writes(),minimum_system_available_bytes=memory['MemAvailable'],
          living_process_write_bytes=writes,output_stock_bytes=output_stock(root),memory_events=group.memory_events())
    except (OSError,KeyError,ValueError):raise HostUnavailable('host_measurement_unavailable') from None


class ResourceWatch:
    def __init__(self,limits):self.limits=limits;self.cpu=deque();self.peak_rss=0;self.peak_stock=0;self.peak_cpu=0;self.last=None
    def check(self,row):
        required={'at','cpu_seconds','group_rss_bytes','minimum_system_available_bytes','output_stock_bytes','memory_events','cumulative_process_write_bytes'}
        if not required<=row.keys():raise HostUnavailable('incomplete_resource_measurement')
        for key in required-{'memory_events'}:
            value=row[key]
            if type(value) not in (int,float) or not math.isfinite(value) or value<0:raise HostUnavailable('invalid_resource_measurement')
        if self.last and (row['at']<self.last['at'] or row['cpu_seconds']<self.last['cpu_seconds']):raise HostUnavailable('nonmonotonic_resource_measurement')
        self.last=row;l=self.limits;now=row['at'];self.cpu.append((now,row['cpu_seconds']))
        while len(self.cpu)>2 and self.cpu[1][0]<=now-30:self.cpu.popleft()
        self.peak_rss=max(self.peak_rss,row['group_rss_bytes']);self.peak_stock=max(self.peak_stock,row['output_stock_bytes'])
        if row['group_rss_bytes']>=l['proof_group_rss_bytes']:return 'proof_group_rss_bytes'
        if row['minimum_system_available_bytes']<l['minimum_system_available_bytes']:return 'minimum_system_available_bytes'
        if row['output_stock_bytes']>=l['output_stock_bytes']-RECEIPT_RESERVE:return 'output_stock_bytes'
        if any(row['memory_events'].get(k,0) for k in ('max','oom','oom_kill')):return 'cgroup_memory_limit'
        if row.get('cumulative_process_write_bytes',0)>=l['cumulative_process_write_bytes']-16*1024*1024:return 'cumulative_process_write_bytes'
        if 'reserved_process_write_bytes' in row and row['reserved_process_write_bytes']>=l['cumulative_process_write_bytes']-RECEIPT_RESERVE:
            return 'cumulative_process_write_bytes'
        if len(self.cpu)>=2 and now-self.cpu[0][0]>=30:
            # Linear interpolation obtains the actual trailing 30-second window;
            # exited workers are in the cgroup's cumulative CPU counter.
            a,b=self.cpu[0],self.cpu[1];target=now-30
            baseline=a[1] if b[0]==a[0] else a[1]+(b[1]-a[1])*max(0,target-a[0])/(b[0]-a[0])
            cores=(row['cpu_seconds']-baseline)/30;self.peak_cpu=max(self.peak_cpu,cores)
            if cores>l['maximum_group_cpu_cores_30_second_average']:return 'maximum_group_cpu_cores_30_second_average'
        return None


class WriteAdmission:
    """Independent cumulative-write and stock reservations, before dispatch.

    Stock reserves each inode's maximum admitted extent, including temporarily
    deleted files until shutdown. That conservative stock is stronger than the
    current directory size, and does not treat overwrites as new storage.
    """
    def __init__(self,limits,root):self.limits=limits;self.root=Path(root).resolve();self.writes=0;self.extents={};self.stock=0;self.denied=0
    def reserve(self,size,*,key=None,end=0):
        if type(size) is not int or not 0<=size<=self.limits['cumulative_process_write_bytes']:raise HostUnavailable('write_measurement_unavailable')
        growth=max(0,end-self.extents.get(key,0)) if key is not None else 0
        reason=('cumulative_process_write_bytes' if self.writes+size>self.limits['cumulative_process_write_bytes']-RECEIPT_RESERVE else
                'output_stock_bytes' if self.stock+growth>self.limits['output_stock_bytes']-RECEIPT_RESERVE else None)
        if reason:self.denied+=1;return reason
        self.writes+=size;self.stock+=growth
        if key is not None:self.extents[key]=max(end,self.extents.get(key,0))
        return None


class Data(C.Structure):_fields_=[('nr',C.c_int),('arch',C.c_uint),('instruction_pointer',C.c_ulonglong),('args',C.c_ulonglong*6)]
class Notification(C.Structure):_fields_=[('id',C.c_ulonglong),('pid',C.c_uint),('flags',C.c_uint),('data',Data)]
class Response(C.Structure):_fields_=[('id',C.c_ulonglong),('val',C.c_longlong),('error',C.c_int),('flags',C.c_uint)]


def seccomp_library():
    name=ctypes.util.find_library('seccomp')
    if not name:raise HostUnavailable('libseccomp_required')
    lib=C.CDLL(name,use_errno=True)
    if lib.seccomp_api_get()<6:raise HostUnavailable('seccomp_notification_api_required')
    lib.seccomp_init.argtypes=[C.c_uint];lib.seccomp_init.restype=C.c_void_p
    lib.seccomp_syscall_resolve_name.argtypes=[C.c_char_p];lib.seccomp_syscall_resolve_name.restype=C.c_int
    lib.seccomp_rule_add.argtypes=[C.c_void_p,C.c_uint,C.c_int,C.c_uint];lib.seccomp_rule_add.restype=C.c_int
    lib.seccomp_load.argtypes=[C.c_void_p];lib.seccomp_load.restype=C.c_int
    lib.seccomp_notify_fd.argtypes=[C.c_void_p];lib.seccomp_notify_fd.restype=C.c_int
    lib.seccomp_release.argtypes=[C.c_void_p]
    lib.seccomp_notify_receive.argtypes=[C.c_int,C.POINTER(Notification)];lib.seccomp_notify_receive.restype=C.c_int
    lib.seccomp_notify_respond.argtypes=[C.c_int,C.POINTER(Response)];lib.seccomp_notify_respond.restype=C.c_int
    lib.seccomp_notify_id_valid.argtypes=[C.c_int,C.c_ulonglong];lib.seccomp_notify_id_valid.restype=C.c_int
    return lib


WRITE_CALLS=('write','pwrite64','writev','pwritev','pwritev2','ftruncate','mmap','msync','fsync','fdatasync','lseek')
PROCESS_CALLS=('fork','vfork','clone','clone3')
REFUSED_CALLS=('io_uring_setup','copy_file_range','sendfile','splice','vmsplice','truncate','fallocate',
               'mount','unshare','setns','ptrace','execve','execveat','mremap')
OPEN_CALLS=('open','openat','openat2')
METADATA_CALLS=('mkdir','mkdirat','unlink','unlinkat','rename','renameat','renameat2','link','linkat','symlink','symlinkat')
NETWORK_CALLS=('socket','connect','sendto')


def install_notifications(control_socket):
    lib=seccomp_library();ctx=lib.seccomp_init(0x7fff0000)
    if not ctx:raise HostUnavailable('seccomp_initialization')
    try:
        for name in WRITE_CALLS+REFUSED_CALLS+NETWORK_CALLS+OPEN_CALLS+METADATA_CALLS+PROCESS_CALLS:
            number=lib.seccomp_syscall_resolve_name(name.encode())
            if number<0 or lib.seccomp_rule_add(ctx,0x7fc00000,number,0)!=0:raise HostUnavailable('seccomp_rule_unavailable')
        # AF_UNIX sendmsg transfers the listener before notification servicing.
        if lib.seccomp_load(ctx)!=0:raise HostUnavailable('seccomp_load_unavailable')
        fd=lib.seccomp_notify_fd(ctx)
        if fd<0:raise HostUnavailable('seccomp_listener_unavailable')
        control_socket.sendmsg([b'F'],[(socket.SOL_SOCKET,socket.SCM_RIGHTS,array.array('i',[fd]))])
        os.close(fd)
    finally:lib.seccomp_release(ctx)

# AF_UNIX sendmsg is needed to hand off the listener and by multiprocessing.
# Internet socket creation/connect/sendto is enforced instead; an unconnected
# Internet sendmsg is also prevented in offline mode by denying socket().
NETWORK_CALLS=('socket','connect','sendto')


def receive_listener(sock):
    raw,anc,_,_=sock.recvmsg(1,socket.CMSG_SPACE(array.array('i').itemsize))
    if raw!=b'F':raise HostUnavailable('seccomp_handoff_identity')
    for level,kind,data in anc:
        if level==socket.SOL_SOCKET and kind==socket.SCM_RIGHTS:
            fds=array.array('i');fds.frombytes(data[:fds.itemsize]);os.set_blocking(fds[0],False);return fds[0]
    raise HostUnavailable('seccomp_listener_missing')


def memory(pid,address,length):
    if length>65536:raise HostUnavailable('notification_memory_bound')
    fd=os.open(f'/proc/{pid}/mem',os.O_RDONLY)
    try:return os.pread(fd,length,address)
    finally:os.close(fd)


class KernelAdmission:
    def __init__(self,fd,limits,root,*,offline=True,allowed_ips=(),group=None,provider_deadline=None):
        self.fd=fd;self.lib=seccomp_library();self.writes=WriteAdmission(limits,root);self.offline=offline
        self.allowed_ips=set(allowed_ips);self.reason=None;self.network_denied=0;self.network_connections=0;self.shm_bytes=0;self.shm_extents={}
        self.thread=None;self.closed=threading.Event();self.old_signal=None
        self.group=group;self.fork_rss_reserved=0
        self.provider_deadline=provider_deadline;self.network_closed=False
        self.names={self.lib.seccomp_syscall_resolve_name(n.encode()):n for n in WRITE_CALLS+REFUSED_CALLS+NETWORK_CALLS+OPEN_CALLS+METADATA_CALLS+PROCESS_CALLS}
    def target(self,pid,fd):
        if fd>=2**31:raise HostUnavailable('invalid_write_descriptor')
        path=Path(f'/proc/{pid}/fd/{fd}');s=path.stat();name=os.readlink(path)
        if stat.S_ISREG(s.st_mode):
            # Only disposable output is writable; no production DB/epoch path.
            resolved=Path(name.removesuffix(' (deleted)')).resolve()
            if not resolved.is_relative_to(self.writes.root):
                if str(resolved).startswith('/dev/shm/sem.') and s.st_size<=4096:return None,0
                raise HostUnavailable('write_outside_isolated_output')
            position=int(next(line.split(':')[1] for line in Path(f'/proc/{pid}/fdinfo/{fd}').read_text().splitlines() if line.startswith('pos:')))
            key=(s.st_dev,s.st_ino)
            # O_APPEND writes advance from file length, not fd's prior seek.
            flags=int(next(line.split(':')[1] for line in Path(f'/proc/{pid}/fdinfo/{fd}').read_text().splitlines() if line.startswith('flags:')),8)
            if flags&os.O_APPEND:position=max(position,s.st_size,self.writes.extents.get(key,0))
            return key,position
        if stat.S_ISFIFO(s.st_mode) or stat.S_ISSOCK(s.st_mode) or name in ('/dev/null','/dev/urandom'):
            return None,0
        raise HostUnavailable('unknown_write_descriptor')
    def path(self,pid,address,dirfd=0xffffff9c):
        # Bounded path read; a pathname must terminate within Linux PATH_MAX.
        raw=memory(pid,address,4096).split(b'\0',1)[0]
        if not raw or len(raw)>=4096:raise HostUnavailable('kernel_path_bound')
        p=Path(os.fsdecode(raw))
        if not p.is_absolute():
            base=Path(os.readlink(f'/proc/{pid}/cwd' if dirfd in (0xffffff9c,0xffffffffffffff9c) else f'/proc/{pid}/fd/{dirfd}'))
            p=base/p
        p=p.resolve()
        if p in (Path('/dev/null'),Path('/dev/urandom')):return p
        if str(p).startswith('/dev/shm/sem.'):return p
        if not p.is_relative_to(self.writes.root):raise HostUnavailable('write_outside_isolated_output')
        return p
    def validate(self,n):
        name=self.names.get(n.data.nr);args=n.data.args;pid=n.pid
        if name in PROCESS_CALLS:
            flags=struct.unpack('Q',memory(pid,args[0],8))[0] if name=='clone3' else args[0] if name=='clone' else 0
            if flags&0x10000:return None # CLONE_THREAD: same process RSS
            if self.group is None:return 'fork_group_accounting_unavailable'
            fields=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()
            reserve=int(fields[21])*os.sysconf('SC_PAGE_SIZE')
            self.fork_rss_reserved+=reserve
            maximum=self.writes.limits['proof_group_rss_bytes']-128*1024*1024-self.fork_rss_reserved
            if maximum<=0:return 'proof_group_rss_bytes'
            # RSS sums duplicated fork pages; memory.max counts shared pages
            # once. Reserving the parent's entire RSS before every process fork
            # closes that gap, even if the descendant later escapes its session.
            (self.group.path/'memory.max').write_text(str(maximum))
            return None
        if name in REFUSED_CALLS:return 'unsupported_resource_or_namespace_syscall'
        if name in OPEN_CALLS:
            address,flags=(args[0],args[1]) if name=='open' else (args[1],args[2])
            if name=='openat2':flags=struct.unpack('Q',memory(pid,args[2],8))[0]
            if flags&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC):
                self.path(pid,address,args[0] if name!='open' else 0xffffff9c)
                return self.writes.reserve(4096)
            return None
        if name in METADATA_CALLS:
            if name in ('symlink','symlinkat'):return 'unsupported_output_symlink'
            if name in ('mkdirat','unlinkat'):self.path(pid,args[1],args[0])
            elif name in ('renameat','renameat2','linkat'):
                self.path(pid,args[1],args[0]);self.path(pid,args[3],args[2])
            else:
                self.path(pid,args[0])
                if name in ('rename','link'):self.path(pid,args[1])
            return self.writes.reserve(4096)
        if name=='socket':
            if args[0]==socket.AF_UNIX:return None
            if self.offline or args[0] not in (socket.AF_INET,socket.AF_INET6):
                self.network_denied+=1;return 'offline_network_attempt' if self.offline else 'unapproved_socket_family'
            if args[1]&15 not in (socket.SOCK_STREAM,socket.SOCK_DGRAM):return 'unapproved_socket_type'
            return None
        if name in ('connect','sendto'):
            address,length=(args[1],args[2]) if name=='connect' else (args[4],args[5])
            if not address:return None # connected transport already validated
            raw=memory(pid,address,min(length,128));family=int.from_bytes(raw[:2],'little')
            if family==socket.AF_UNIX:return None
            if self.network_closed or self.provider_deadline is not None and time.monotonic()>=self.provider_deadline:
                return 'provider_admission_deadline'
            if self.offline:self.network_denied+=1;return 'offline_network_attempt'
            if family not in (socket.AF_INET,socket.AF_INET6) or len(raw)<8:return 'unapproved_socket_address'
            port=int.from_bytes(raw[2:4],'big');ip=socket.inet_ntop(family,raw[4:8] if family==socket.AF_INET else raw[8:24])
            if (ip,port) not in self.allowed_ips:return 'unapproved_kernel_endpoint'
            if name=='connect':self.network_connections+=1
            return None
        if name=='mmap':
            # Anonymous/private mappings cannot write files. Reserve shared
            # mapped extents before mapping; msync is charged separately too.
            if args[3]&0x20 or not args[3]&1:return None
            key,pos=self.target(pid,args[4])
            if key is None:return None # bounded transient POSIX semaphore in tmpfs
            target=os.readlink(f'/proc/{pid}/fd/{args[4]}').removesuffix(' (deleted)')
            if not target.endswith('-shm') or args[1]>32768:return 'unaccountable_shared_file_mapping'
            # SQLite's WAL index is the only disk-backed shared writable map.
            # Physical repeated writeback is separately metered and throttled
            # by cgroup io.stat/io.max, including exited process descendants.
            self.shm_extents[key]=max(args[1],self.shm_extents.get(key,0))
            self.shm_bytes=sum(self.shm_extents.values())
            return self.writes.reserve(args[1],key=key,end=args[5]+args[1])
        if name=='msync':return self.writes.reserve(((args[1]+4095)//4096)*4096)
        if name in ('fsync','fdatasync'):return self.writes.reserve(4096)
        if name=='lseek':
            descriptor=Path(f'/proc/{pid}/fdinfo/{args[0]}').read_text().splitlines()
            flags=int(next(line.split(':')[1] for line in descriptor if line.startswith('flags:')),8)
            if flags&os.O_ACCMODE==os.O_RDONLY:return None
            key,pos=self.target(pid,args[0]);offset=C.c_longlong(args[1]).value
            if args[2]==os.SEEK_SET:end=offset
            elif args[2]==os.SEEK_CUR:end=pos+offset
            elif args[2]==os.SEEK_END:end=Path(f'/proc/{pid}/fd/{args[0]}').stat().st_size+offset
            else:return 'unsupported_write_seek'
            if end<0:return 'unbounded_write_offset'
            return self.writes.reserve(0,key=key,end=end)
        key,pos=self.target(pid,args[0])
        if name=='ftruncate':
            if key is None and args[1]>4096:return 'ipc_mapping_bound'
            return self.writes.reserve(4096 if key is not None else 0,key=key,end=args[1])
        if name in ('writev','pwritev','pwritev2'):
            if args[2]>1024:return 'unbounded_write_iovec'
            raw=memory(pid,args[1],args[2]*16);size=sum(length for _,length in struct.iter_unpack('QQ',raw))
        else:size=args[2]
        if name in ('pwrite64','pwritev','pwritev2'):pos=args[3]
        if pos>=2**63:return 'unbounded_write_offset'
        return self.writes.reserve(0 if key is None else ((pos%4096+size+4095)//4096)*4096,key=key,end=pos+size)
    def service(self,maximum=128):
        # SECCOMP_IOCTL_NOTIF_RECV may block after a task cancels between poll
        # and ioctl, even with O_NONBLOCK. It must never block the watchdog.
        if self.thread is None:
            self.old_signal=signal.signal(signal.SIGUSR1,lambda *_:None)
            def broker():
                try:
                    while not self.closed.is_set():
                        self.receive(maximum)
                        self.closed.wait(.001)
                except BaseException:self.reason=self.reason or 'kernel_broker_failure'
            self.thread=threading.Thread(target=broker,name='independent-kernel-admission',daemon=True)
            self.thread.start()
    def close(self):
        self.closed.set()
        if self.thread is not None and self.thread.is_alive():
            signal.pthread_kill(self.thread.ident,signal.SIGUSR1)
            self.thread.join(timeout=.1)
        alive=self.thread is not None and self.thread.is_alive()
        os.close(self.fd)
        if self.old_signal is not None:signal.signal(signal.SIGUSR1,self.old_signal)
        return not alive
    def receive(self,maximum=128):
        for _ in range(maximum):
            if not select.select([self.fd],[],[],0)[0]:break
            n=Notification();code=self.lib.seccomp_notify_receive(self.fd,C.byref(n))
            if code in (-errno.EAGAIN,-errno.ENOENT,-errno.ECANCELED,-errno.EINTR):break
            if code<0:raise HostUnavailable('seccomp_notification_unavailable_'+str(-code))
            if self.lib.seccomp_notify_id_valid(self.fd,n.id)!=0:continue
            try:reason=self.validate(n)
            except HostUnavailable as exc:reason=str(exc)
            except (OSError,ValueError,StopIteration,struct.error):reason='kernel_admission_measurement_unavailable'
            self.reason=self.reason or reason
            r=Response(n.id,0,-errno.EPERM if reason else 0,0 if reason else 1)
            code=self.lib.seccomp_notify_respond(self.fd,C.byref(r))
            if code not in (0,-errno.ENOENT):raise HostUnavailable('seccomp_response_unavailable')
            if reason:break
