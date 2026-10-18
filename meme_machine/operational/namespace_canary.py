"""Canary-only unprivileged namespace capability experiment; no native runtime.

No provider, credential, financial, broker or live workload is imported. This
module always runs its own fixed disposable probe, never a supplied command.
The calling parent must enforce the wall limit and retain BLOCKED/failure output.
Actual AWS service/user-namespace/AppArmor compatibility remains a separate test.
"""
import ctypes
import errno
import json
import os
from pathlib import Path
import platform
import re
import resource
import select
import selectors
import signal
import socket
import stat
import subprocess
import sys
import time

USER = 0x10000000
MOUNT = 0x00020000
PID = 0x20000000
NET = 0x40000000
IPC = 0x08000000
MS_RDONLY, MS_NOSUID, MS_NODEV = 1, 2, 4
MS_BIND, MS_REC, MS_PRIVATE, MS_REMOUNT = 4096, 16384, 1 << 18, 32
_MAX_RESULT = 16384
_MARKERS = ('portfolio.sqlite','shared-capital.sqlite','native-genesis.json','inception.json')
_CHECKS = frozenset(('caps_empty','no_new_privileges','pid_namespace_init','host_secret_read',
    'host_secret_write','host_parent_environ','oldroot_inaccessible','source_readonly',
    'host_unix_path','host_abstract_unix','host_network','no_egress_interfaces',
    'no_ipv4_routes','namespace_reentry','ptrace_parent_denied','local_unix',
    'sqlite_FULL_WAL','private_shm','real_spawn_pool','anonymous_parent_ipc',
    'site_disabled','copied_runtime_only','all'))


class Blocked(RuntimeError):
    def __init__(self, code, number=None):
        self.code, self.number = code, number
        super().__init__(code)


def _require(value, code):
    if not value:raise Blocked(code)


class Kernel:
    def __init__(self):
        _require(sys.platform == 'linux' and platform.machine() in ('x86_64', 'aarch64'),
                 'namespace_platform_unreviewed')
        self.libc = ctypes.CDLL(None, use_errno=True)

    def call(self, function, *args, code):
        ctypes.set_errno(0)
        if getattr(self.libc, function)(*args) != 0:
            raise Blocked(code, ctypes.get_errno())

    def prctl(self, operation, value, code):
        self.call('prctl', ctypes.c_int(operation), ctypes.c_ulong(value),
                  ctypes.c_ulong(0), ctypes.c_ulong(0), ctypes.c_ulong(0), code=code)

    def mount(self, source, target, kind=None, flags=0, data=None):
        def raw(value):return None if value is None else os.fsencode(value)
        self.call('mount', ctypes.c_char_p(raw(source)), ctypes.c_char_p(raw(target)),
            ctypes.c_char_p(raw(kind)), ctypes.c_ulong(flags), ctypes.c_char_p(raw(data)),
            code='namespace_mount_refused')

    def unshare(self, flags):
        self.call('unshare', ctypes.c_int(flags), code='namespace_unshare_refused')


def _private(path, *, empty=False):
    path = Path(path)
    _require(path.is_absolute() and '..' not in path.parts, 'namespace_private_path')
    _require(not any(path == Path(root) or Path(root) in path.parents for root in
        ('/srv/meme-machine','/etc/meme-machine','/var/lib/meme-machine-operations')),
        'namespace_production_path_refused')
    try:
        for node in (path, *path.parents):
            _require(not stat.S_ISLNK(node.lstat().st_mode), 'namespace_path_symlink')
            _require(not any((node/marker).exists() for marker in _MARKERS),
                     'namespace_financial_ancestor_refused')
        info = path.stat()
        _require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
            and stat.S_IMODE(info.st_mode) == 0o700, 'namespace_private_path')
        _require(not empty or not any(path.iterdir()), 'namespace_empty_path')
    except OSError:raise Blocked('namespace_path_unavailable') from None
    return path


def _ipc_only(ipc_fd):
    """Keep only result/log pipes and one explicit unnamed parent socketpair."""
    for fd in (1, 2):
        info = os.fstat(fd)
        _require(stat.S_ISFIFO(info.st_mode)
            and os.readlink('/proc/self/fd/' + str(fd)).startswith('pipe:['),
            'namespace_result_pipe_required')
    _require(stat.S_ISSOCK(os.fstat(ipc_fd).st_mode), 'namespace_private_ipc_required')
    with socket.socket(fileno=os.dup(ipc_fd)) as endpoint:
        _require(endpoint.family == socket.AF_UNIX and endpoint.type == socket.SOCK_STREAM
            and endpoint.getsockname() == '' and endpoint.getpeername() == '',
            'namespace_private_ipc_required')
    for value in os.listdir('/proc/self/fd'):
        fd = int(value)
        if fd in (1, 2, ipc_fd):continue
        try:os.close(fd)
        except OSError as error:
            if error.errno != errno.EBADF:raise


def _bind(kernel, source, target, *, readonly):
    source, target = Path(source), Path(target)
    _require(source.exists(), 'namespace_runtime_missing')
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():target.mkdir(exist_ok=True)
    else:target.touch(exist_ok=True)
    # Nonrecursive binds do not import nested host mounts into the whitelist.
    kernel.mount(source, target, flags=MS_BIND)
    if readonly:
        kernel.mount(None, target, flags=MS_BIND | MS_REMOUNT | MS_RDONLY | MS_NOSUID | MS_NODEV)


def _drop_capabilities(kernel):
    # Lock root-special handling and ambient privilege before emptying all sets.
    kernel.prctl(28, 1 | 2 | 4 | 8 | 64 | 128, 'namespace_securebits_refused')
    maximum = int(Path('/proc/sys/kernel/cap_last_cap').read_text())
    _require(0 <= maximum <= 63, 'namespace_capability_range')
    for cap in range(maximum + 1):
        kernel.prctl(24, cap, 'namespace_bounding_drop_refused')
    class Header(ctypes.Structure):
        _fields_ = [('version', ctypes.c_uint32), ('pid', ctypes.c_int)]
    class Data(ctypes.Structure):
        _fields_ = [('effective', ctypes.c_uint32), ('permitted', ctypes.c_uint32),
                    ('inheritable', ctypes.c_uint32)]
    values = (Data * 2)()
    kernel.call('capset', ctypes.byref(Header(0x20080522, 0)), ctypes.byref(values),
                code='namespace_capability_drop_refused')


def _lock_namespaces(kernel):
    """Keep fork/spawn, refuse later namespace entry or remount/escape attempts."""
    architecture, numbers, clone = (
        (0xc000003e, (165, 166, 155, 272, 308, 101, 310, 311, 428, 429, 430, 431, 432, 433, 434, 438, 442), 56)
        if platform.machine() == 'x86_64' else
        (0xc00000b7, (40, 39, 41, 97, 268, 117, 270, 271, 428, 429, 430, 431, 432, 433, 434, 438, 442), 220))
    class Filter(ctypes.Structure):
        _fields_ = [('code', ctypes.c_ushort), ('jt', ctypes.c_ubyte),
                    ('jf', ctypes.c_ubyte), ('k', ctypes.c_uint32)]
    class Program(ctypes.Structure):
        _fields_ = [('length', ctypes.c_ushort), ('filter', ctypes.POINTER(Filter))]
    deny = 0x00050000 | errno.EPERM
    rows = [(0x20,0,0,4),(0x15,1,0,architecture),(0x06,0,0,0x80000000),
            (0x20,0,0,0),(0x35,0,1,451),(0x06,0,0,deny),
            # Force libc's normal legacy-clone path; its flags are checked
            # below. EPERM here prevents pthread startup rather than fallback.
            (0x15,0,1,435),(0x06,0,0,0x00050000 | errno.ENOSYS)]
    for number in numbers:
        rows.extend(((0x15,0,1,number),(0x06,0,0,deny)))
    # clone3 is refused; CPython's fork/spawn uses ordinary clone without flags.
    # Check clone flags at seccomp_data.args[0], preserving ordinary fork.
    rows.extend(((0x15,0,3,clone),(0x20,0,0,16),
                 (0x45,0,1,0x7e020000),(0x06,0,0,deny),(0x06,0,0,0x7fff0000)))
    filters = (Filter * len(rows))(*(Filter(*row) for row in rows))
    program = Program(len(filters), filters)
    kernel.call('prctl', ctypes.c_int(22), ctypes.c_ulong(2), ctypes.byref(program),
        ctypes.c_ulong(0), ctypes.c_ulong(0), code='namespace_lock_filter_refused')


def _arm_parent(kernel, expected):
    kernel.prctl(1, signal.SIGKILL, 'namespace_parent_death_refused')
    _require(expected == os.getppid(), 'namespace_parent_changed')


def _arm_pid1_parent(kernel, lifeline):
    kernel.prctl(1, signal.SIGKILL, 'namespace_parent_death_refused')
    alive = select.poll();alive.register(lifeline, select.POLLHUP | select.POLLERR)
    _require(not alive.poll(0), 'namespace_parent_changed')


def _write_user_mapping(name, value):
    codes = {'setgroups':'namespace_setgroups_refused',
             'uid_map':'namespace_uid_map_refused', 'gid_map':'namespace_gid_map_refused'}
    _require(name in codes, 'namespace_mapping_unreviewed')
    try:
        Path('/proc/self/' + name).write_text(value)
    except OSError as error:
        number = error.errno
        if type(number) is int and 0 < number < 4096:
            raise Blocked(codes[name], number) from None
        raise


def _setup(spec):
    kernel = Kernel()
    _require(os.geteuid() != 0, 'namespace_nonroot_required')
    _require(len(os.listdir('/proc/self/task')) == 1, 'namespace_single_thread_required')
    root = _private(spec['root'], empty=True)
    work = _private(spec['work'], empty=True)
    _require(root.parent == work.parent, 'namespace_fixture_scope')
    _require(spec['parent_pid'] == os.getppid(), 'namespace_parent_identity')
    _scratch(root.parent, spec['parent_pid'])
    uid, gid = os.geteuid(), os.getegid()
    kernel.prctl(38, 1, 'namespace_no_new_privileges_refused')
    _arm_parent(kernel,spec['parent_pid'])
    kernel.unshare(USER)
    _write_user_mapping('setgroups', 'deny')
    _write_user_mapping('uid_map', '0 ' + str(uid) + ' 1\n')
    _write_user_mapping('gid_map', '0 ' + str(gid) + ' 1\n')
    kernel.unshare(MOUNT | NET | PID | IPC)
    kernel.mount(None, '/', flags=MS_REC | MS_PRIVATE)
    _arm_parent(kernel,spec['parent_pid'])
    # PID1 sees an outside parent as PID0, so getppid cannot detect its death.
    # A private lifeline catches death before the child's PDEATHSIG is armed.
    lifeline_read, lifeline_write = os.pipe2(os.O_CLOEXEC)
    child = os.fork()
    if child:
        os.close(lifeline_read)
        _, status = os.waitpid(child, 0)
        os._exit(os.waitstatus_to_exitcode(status) if os.WIFEXITED(status) else 3)
    os.close(lifeline_write)
    _arm_pid1_parent(kernel,lifeline_read)
    os.close(lifeline_read)
    signal.signal(signal.SIGTERM, lambda *_: os._exit(3))
    kernel.mount('tmpfs', root, 'tmpfs', MS_NOSUID | MS_NODEV, 'size=16m,mode=0755')
    for node in ('work','tmp','proc','dev','dev/shm','oldroot'):
        (root / node).mkdir(parents=True, exist_ok=True)
    # Only the parent's copied/verified fixed runtime enters the child. No
    # original interpreter, stdlib, library, venv or source directory is bound.
    runtime = root.parent/'runtime'
    _require(runtime.is_dir() and not runtime.is_symlink(),'namespace_runtime_missing')
    _bind(kernel, runtime, root/'runtime', readonly=True)
    _bind(kernel, runtime/'probe.py', root/'probe.py', readonly=True)
    loader='/lib64/ld-linux-x86-64.so.2' if platform.machine()=='x86_64' else '/lib/ld-linux-aarch64.so.1'
    _bind(kernel, runtime/'loader', root/loader.lstrip('/'), readonly=True)
    _bind(kernel, work, root / 'work', readonly=False)
    for node in ('null','zero','urandom'):
        _bind(kernel, Path('/dev') / node, root / 'dev' / node, readonly=False)
    kernel.mount('tmpfs', root / 'tmp', 'tmpfs', MS_NOSUID | MS_NODEV, 'size=16m,mode=1777')
    kernel.mount('tmpfs', root / 'dev/shm', 'tmpfs', MS_NOSUID | MS_NODEV, 'size=16m,mode=1777')
    kernel.mount('proc', root / 'proc', 'proc', MS_RDONLY | MS_NOSUID | MS_NODEV)
    # pivot_root into an actual mount, detach the old host root and close every
    # host descriptor/cwd reference before capability drop and target imports.
    os.chdir(root)
    syscall = 155 if platform.machine() == 'x86_64' else 41
    kernel.call('syscall', ctypes.c_long(syscall), ctypes.c_char_p(b'.'),
        ctypes.c_char_p(b'oldroot'), code='namespace_pivot_refused')
    os.chdir('/')
    kernel.call('umount2', ctypes.c_char_p(b'/oldroot'), ctypes.c_int(2),
                code='namespace_oldroot_detach_refused')
    Path('/oldroot').rmdir()
    kernel.mount(None, '/', flags=MS_REMOUNT | MS_RDONLY | MS_NOSUID | MS_NODEV)
    _ipc_only(spec['ipc_fd'])
    descriptor = os.open('/dev/null', os.O_RDONLY)
    if descriptor != 0:os.dup2(descriptor, 0);os.close(descriptor)
    _drop_capabilities(kernel)
    _lock_namespaces(kernel)
    os.chdir('/work')
    os.environ.clear()
    os.environ.update(LANG='C', PATH='/nonexistent', TMPDIR='/tmp',
                      PYTHONDONTWRITEBYTECODE='1',LD_LIBRARY_PATH='/runtime/lib')
    resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
    resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
    os.execv('/runtime/bin/python3.12', ['/runtime/bin/python3.12', '-I', '-B', '-S',
            '/probe.py', '--probe', json.dumps(spec)])


def _spec(value):
    _require(type(value) is dict and set(value) == {'root','work','secret','unix','abstract',
        'port','parent_pid','host_shm_device','ipc_fd'}, 'namespace_spec_shape')
    _require(all(type(value[key]) is str for key in ('root','work','secret','unix','abstract')),
             'namespace_spec_shape')
    root = Path(value['root'])
    _require(root.name == 'rootfs' and value['work'] == str(root.parent/'work')
        and value['secret'] == str(root.parent/'host-secret')
        and value['unix'] == str(root.parent/'host.sock')
        and re.fullmatch(r'mm-namespace-canary-[0-9]{1,10}-[0-9]{1,24}',value['abstract']),
        'namespace_spec_paths')
    _require(type(value['port']) is int and 0 < value['port'] < 65536
        and type(value['parent_pid']) is int and 1 < value['parent_pid'] < 2**31
        and type(value['host_shm_device']) is int and 0 <= value['host_shm_device'] < 2**64,
        'namespace_spec_numbers')
    _require(type(value['ipc_fd']) is int and 3 <= value['ipc_fd'] < 256,
             'namespace_spec_numbers')
    return value


def _square(value):
    return value * value


def _probe(spec):
    # These imports happen only after root detachment and capability drop.
    import concurrent.futures
    import multiprocessing
    import sqlite3
    failures = []
    checks = {}
    def denied(name, action):
        try:action()
        except (OSError, Blocked):checks[name] = True
        else:checks[name] = False;failures.append(name)
    status = dict(line.split(':',1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
    _require(os.getpid() == 1 and os.getppid() == 0 and Path.cwd() == Path('/work')
        and Path(__file__) == Path('/probe.py') and status['NoNewPrivs'].strip() == '1',
        'namespace_standalone_probe_refused')
    checks['caps_empty'] = all(int(status[key].strip(),16) == 0 for key in
                               ('CapEff','CapPrm','CapInh','CapBnd','CapAmb'))
    checks['no_new_privileges'] = status['NoNewPrivs'].strip() == '1'
    checks['site_disabled'] = (sys.flags.no_site == 1 and 'site' not in sys.modules
        and not Path('/runtime/lib/python3.12/site.py').exists()
        and not list(Path('/runtime').rglob('*.pth'))
        and not list(Path('/runtime').rglob('site-packages')))
    checks['copied_runtime_only'] = (sys.executable == '/runtime/bin/python3.12'
        and sys.prefix == sys.base_prefix == '/runtime'
        and all(path.startswith('/runtime/') for path in sys.path))
    with socket.socket(fileno=spec['ipc_fd']) as parent:
        parent.settimeout(2)
        parent.sendall(b'namespace canary')
        checks['anonymous_parent_ipc'] = parent.recv(32) == b'parent acknowledged'
    checks['pid_namespace_init'] = os.getpid() == 1 and os.getppid() == 0
    denied('host_secret_read', lambda: Path(spec['secret']).read_bytes())
    denied('host_secret_write', lambda: Path(spec['secret']).write_bytes(b'wrong'))
    denied('host_parent_environ', lambda: Path('/proc/' + str(spec['parent_pid']) + '/environ').read_bytes())
    denied('oldroot_inaccessible', lambda: Path('/oldroot').iterdir().__next__())
    denied('source_readonly', lambda: Path('/probe.py').write_text('wrong'))
    def connect(address, family):
        with socket.socket(family, socket.SOCK_STREAM) as channel:
            channel.settimeout(.2);channel.connect(address)
    denied('host_unix_path', lambda:connect(spec['unix'], socket.AF_UNIX))
    denied('host_abstract_unix', lambda:connect('\0' + spec['abstract'], socket.AF_UNIX))
    denied('host_network', lambda:connect(('127.0.0.1',spec['port']), socket.AF_INET))
    checks['no_egress_interfaces'] = socket.if_nameindex() == [(1, 'lo')]
    routes = [line for line in Path('/proc/net/route').read_text().splitlines()
              if line.strip() and not line.startswith('Iface')]
    checks['no_ipv4_routes'] = not routes
    kernel = Kernel()
    denied('namespace_reentry', lambda:kernel.unshare(USER))
    _require(not Path('/proc/' + str(spec['parent_pid'])).exists(), 'namespace_canary_pid_collision')
    ctypes.set_errno(0)
    result = kernel.libc.ptrace(16, spec['parent_pid'], None, None)
    checks['ptrace_parent_denied'] = result == -1 and ctypes.get_errno() in (errno.EPERM, errno.ESRCH)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind('/work/local.sock');server.listen(1)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.connect('/work/local.sock')
            connection, _ = server.accept()
            with connection:
                client.sendall(b'canary');checks['local_unix'] = connection.recv(6) == b'canary'
    with sqlite3.connect('/work/test.sqlite') as db:
        db.execute('PRAGMA journal_mode=WAL');db.execute('PRAGMA synchronous=FULL')
        db.execute('CREATE TABLE values_table(value INTEGER)')
        db.execute('INSERT INTO values_table VALUES(42)');db.commit()
        checks['sqlite_FULL_WAL'] = (db.execute('PRAGMA synchronous').fetchone()[0] == 2
            and db.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
            and db.execute('SELECT value FROM values_table').fetchone()[0] == 42)
    context = multiprocessing.get_context('spawn')
    semaphore = context.Semaphore(1)
    checks['private_shm'] = (bool(list(Path('/dev/shm').glob('sem.*')))
                             and os.stat('/dev/shm').st_dev != spec['host_shm_device'])
    with concurrent.futures.ProcessPoolExecutor(max_workers=2, mp_context=context) as pool:
        checks['real_spawn_pool'] = list(pool.map(_square, [1,2,3,4])) == [1,4,9,16]
    checks['all'] = all(checks.values()) and not failures
    print(json.dumps(dict(state='CANARY_ENFORCEMENT_VERIFIED' if checks['all'] else 'CANARY_FAILED',
        checks=checks, provider_calls=0, financial_authority=False,
        actual_service_restrictions_verified=False)), flush=True)
    return 0 if checks['all'] else 3


def _scratch(scope, parent):
    scope = _private(scope)
    marker = scope/'engineering-artifact.json'
    try:
        info = marker.lstat()
        _require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
            and info.st_size <= 4096, 'namespace_scratch_marker')
        value = json.loads(marker.read_bytes())
        _require(value.get('classification') == 'DISPOSABLE_OFFLINE_FIXTURE'
            and value.get('status') == 'RUNNING' and value.get('pid') == parent,
            'namespace_scratch_marker')
    except (OSError, ValueError):raise Blocked('namespace_scratch_marker') from None
    return scope


def _collect(child, channel, seconds):
    """Bound output while reading; never accumulate unbounded communicate data."""
    deadline = time.monotonic() + seconds
    buffers = {'stdout':bytearray(),'stderr':bytearray(),'ipc':bytearray()}
    with selectors.DefaultSelector() as watcher:
        for name, stream in (('stdout',child.stdout),('stderr',child.stderr),('ipc',channel)):
            os.set_blocking(stream.fileno(),False)
            watcher.register(stream,selectors.EVENT_READ,name)
        while watcher.get_map():
            remaining = deadline-time.monotonic()
            if remaining <= 0:raise subprocess.TimeoutExpired('namespace canary',seconds)
            for key, _ in watcher.select(min(.2,remaining)):
                data = os.read(key.fd,4096)
                if not data:
                    watcher.unregister(key.fileobj)
                    continue
                target = buffers[key.data]
                _require(len(target)+len(data) <= (_MAX_RESULT if key.data!='ipc' else 32),
                         'namespace_result_bound')
                target.extend(data)
                if key.data=='ipc' and len(target)>=len(b'namespace canary'):
                    _require(bytes(target)==b'namespace canary','namespace_ipc_challenge')
                    channel.settimeout(max(.001,deadline-time.monotonic()))
                    channel.sendall(b'parent acknowledged')
                    watcher.unregister(channel)
    child.wait(timeout=max(.001,deadline-time.monotonic()))
    return bytes(buffers['stdout']),bytes(buffers['stderr'])


def _kill_probe(child):
    try:os.killpg(child.pid,signal.SIGKILL)
    except ProcessLookupError:pass
    child.wait(timeout=2)


def canary(scope, *, seconds=15):
    """Fixed disposable experiment. Caller supplies an admitted Scratch scope."""
    scope = _scratch(scope, os.getpid())
    _require(type(seconds) in (int,float) and 0 < seconds <= 20, 'namespace_wall_bound')
    namespaces = {name:os.readlink('/proc/self/ns/' + name) for name in ('user','mnt','pid','net','ipc')}
    parent_cwd = Path.cwd()
    parent_fds = {}
    for name in os.listdir('/proc/self/fd'):
        try:
            info = os.fstat(int(name))
            parent_fds[int(name)] = (info.st_dev,info.st_ino,info.st_mode)
        except OSError as error:
            if error.errno != errno.EBADF:raise
    root, work = scope/'rootfs', scope/'work'
    _require(not root.exists() and not work.exists(), 'namespace_scope_already_used')
    root.mkdir(mode=0o700);work.mkdir(mode=0o700)
    try:
        from meme_machine.operational.namespace_runtime import build,Refused
        runtime=build(scope,Path(__file__).resolve())
    except (Refused,OSError,ValueError,UnicodeError) as error:
        return dict(state='BLOCKED',code=str(error) if isinstance(error,Refused)
            else 'namespace_runtime_unavailable',provider_calls=0,financial_authority=False,
            fallback_allowed=False)
    secret = scope/'host-secret';secret.write_bytes(b'private namespace canary')
    unix, abstract = scope/'host.sock', 'mm-namespace-canary-' + str(os.getpid()) + '-' + str(time.time_ns())
    parent_ipc, child_ipc = socket.socketpair()
    with (parent_ipc,child_ipc,socket.socket(socket.AF_UNIX) as listener, socket.socket(socket.AF_UNIX) as hidden,
          socket.socket(socket.AF_INET) as network):
        listener.bind(str(unix));listener.listen(1)
        hidden.bind('\0' + abstract);hidden.listen(1)
        network.bind(('127.0.0.1',0));network.listen(1)
        spec = _spec(dict(root=str(root), work=str(work), secret=str(secret), unix=str(unix),
                    abstract=abstract, port=network.getsockname()[1], parent_pid=os.getpid(),
                    host_shm_device=os.stat('/dev/shm').st_dev,ipc_fd=child_ipc.fileno()))
        bootstrap = 'import runpy,sys;sys.path.insert(0,' + repr(str(Path(__file__).resolve().parents[2])) + ');runpy.run_module("meme_machine.operational.namespace_canary",run_name="__main__")'
        # -S prevents site/.pth imports before namespace setup. Normal runtime
        # site processing happens only after pivot/capability drop on re-exec.
        child = subprocess.Popen([sys.executable,'-I','-B','-S','-c',bootstrap,'--setup',json.dumps(spec)],
            stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            close_fds=True,pass_fds=(child_ipc.fileno(),),start_new_session=True,env={})
        child_ipc.close()
        try:
            output, errors = _collect(child,parent_ipc,seconds)
        except (subprocess.TimeoutExpired,TimeoutError,Blocked) as error:
            _kill_probe(child)
            return dict(state='BLOCKED',code=error.code if isinstance(error,Blocked) else
                        'namespace_wall_expired',provider_calls=0,financial_authority=False,
                        fallback_allowed=False)
        finally:
            child.stdout.close();child.stderr.close()
    _require(len(output) <= _MAX_RESULT and len(errors) <= _MAX_RESULT, 'namespace_result_bound')
    _require(secret.read_bytes() == b'private namespace canary', 'namespace_host_canary_changed')
    _require(namespaces == {name:os.readlink('/proc/self/ns/' + name) for name in namespaces},
             'namespace_parent_context_changed')
    _require(Path.cwd() == parent_cwd, 'namespace_parent_cwd_changed')
    for descriptor, identity in parent_fds.items():
        info = os.fstat(descriptor)
        _require(identity == (info.st_dev,info.st_ino,info.st_mode), 'namespace_parent_fd_changed')
    try:receipt = json.loads(output)
    except (ValueError, UnicodeError, RecursionError):
        return dict(state='BLOCKED',code='namespace_result_unavailable',child_exit=child.returncode,
                    provider_calls=0,financial_authority=False,fallback_allowed=False)
    if (type(receipt) is not dict or receipt.get('state') not in
            ('BLOCKED','CANARY_FAILED','CANARY_ENFORCEMENT_VERIFIED')
            or receipt.get('provider_calls') != 0 or receipt.get('financial_authority') is not False):
        return dict(state='BLOCKED',code='namespace_receipt_unverified',child_exit=child.returncode,
                    provider_calls=0,financial_authority=False,fallback_allowed=False)
    if receipt['state'] == 'CANARY_ENFORCEMENT_VERIFIED':
        checks = receipt.get('checks')
        if (child.returncode != 0 or type(checks) is not dict or checks.keys() != _CHECKS
                or not all(value is True for value in checks.values())
                or receipt.get('actual_service_restrictions_verified') is not False):
            return dict(state='BLOCKED',code='namespace_receipt_unverified',child_exit=child.returncode,
                        provider_calls=0,financial_authority=False,fallback_allowed=False)
    receipt['child_exit'] = child.returncode
    receipt['fallback_allowed'] = False
    receipt['parent_namespaces_unchanged'] = True
    receipt['parent_cwd_unchanged'] = True
    receipt['parent_open_descriptors_preserved'] = True
    receipt['runtime_manifest_sha256'] = runtime['manifest_sha256']
    receipt['runtime_files'] = len(runtime['files'])
    receipt['runtime_bytes'] = runtime['bytes']
    return receipt


def main():
    try:
        _require(len(sys.argv) == 3 and sys.argv[1] in ('--setup','--probe'), 'namespace_entrypoint')
        _require(len(sys.argv[2]) <= 4096, 'namespace_spec_bound')
        spec = _spec(json.loads(sys.argv[2]))
        if sys.argv[1] == '--setup':_setup(spec)
        return _probe(spec)
    except Blocked as error:
        print(json.dumps(dict(state='BLOCKED',code=error.code,error_number=error.number,
            fallback_allowed=False,provider_calls=0,financial_authority=False)),flush=True)
        return 2
    except BaseException as error:
        frames = []
        tb = error.__traceback__
        while tb is not None:
            frames.append(dict(module=str(tb.tb_frame.f_globals.get('__name__','unknown'))[:96],
                               function=tb.tb_frame.f_code.co_name[:96],line=tb.tb_lineno))
            tb = tb.tb_next
        print(json.dumps(dict(state='BLOCKED',code='namespace_setup_or_probe_failed',
            error_type=type(error).__name__,frames=frames[-4:],fallback_allowed=False,
            provider_calls=0,financial_authority=False)),flush=True)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
