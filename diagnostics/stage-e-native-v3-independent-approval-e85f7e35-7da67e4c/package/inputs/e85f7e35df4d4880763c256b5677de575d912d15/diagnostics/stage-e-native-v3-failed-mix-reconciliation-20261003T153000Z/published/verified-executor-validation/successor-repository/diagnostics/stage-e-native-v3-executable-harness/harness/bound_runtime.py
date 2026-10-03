"""Isolated origins, single real-speed shared semantic clock, child/thread guards."""
import atexit
import asyncio
import importlib.abc
import importlib.machinery
import mmap
import multiprocessing
import multiprocessing.util
import os
from pathlib import Path
import socket
import struct
import sys
import threading
import time
import types

from core import ASSEMBLY, INFRA, REAL_MONO, REAL_NS, S, canonical, file_sha, read, require, sha
from preserve import persist

PARAMS = None
CLOCK = None
EXPECTED = {}
PROVIDER_ATTEMPTS = []
ROLE = 'uninitialized'
RELEASE_ALLOWED = False
ADMISSION_ERRORS = []
REAL_TIME = types.ModuleType('stagee_v3_real_scheduler_time')
REAL_TIME.__dict__.update(vars(time))


class ProjectedClock:
    def __init__(self, path):
        self.file = Path(path).open('r+b', buffering=0)
        self.shared = mmap.mmap(self.file.fileno(), 8)

    def anchor(self):
        return struct.unpack_from('=Q', self.shared)[0]

    def activate(self):
        require(self.anchor() == 0, 'semantic_epoch_reanchored')
        anchor = REAL_NS()
        struct.pack_into('=Q', self.shared, 0, anchor)
        return anchor

    def elapsed_ns(self):
        anchor = self.anchor()
        return max(0, REAL_NS()-anchor) if anchor else 0

    def time_ns(self):
        return 1800000000*10**9 + self.elapsed_ns()

    def monotonic_ns(self):
        return 100*10**9 + self.elapsed_ns()

    def time(self):
        return self.time_ns()/10**9

    def monotonic(self):
        return self.monotonic_ns()/10**9

    def sample(self):
        return dict(anchor_real_monotonic_ns=self.anchor(), wall=self.time(),
                    monotonic=self.monotonic(), real_monotonic_ns=REAL_NS())


def expected_file(path):
    name = str(Path(path).resolve())
    expected = EXPECTED.get(name)
    require(expected is not None and file_sha(name) == expected, 'unbound_executable_origin:' + name)
    return expected


def real_scheduler(module):
    origin = getattr(module, '__file__', None)
    if not origin or str(Path(origin).resolve()) not in PARAMS['environment']['stdlib_files']:
        return
    for name, value in list(vars(module).items()):
        if value is time:
            setattr(module, name, REAL_TIME)
        elif CLOCK is not None:
            for clock_name in ('time', 'time_ns', 'monotonic', 'monotonic_ns', 'clock_gettime', 'clock_gettime_ns'):
                if value is getattr(time, clock_name):
                    setattr(module, name, getattr(REAL_TIME, clock_name))
                    break


class BoundFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        spec = importlib.machinery.PathFinder.find_spec(fullname, path, target)
        if spec is None:
            return None
        if spec.origin in ('built-in', 'frozen'):
            return spec
        if spec.origin is None:
            source = Path(PARAMS['assembly'])/'source'
            require(all(Path(p).resolve().is_relative_to(source) for p in spec.submodule_search_locations or []),
                    'unbound_namespace')
            return spec
        expected_file(spec.origin)
        if isinstance(spec.loader, importlib.machinery.SourceFileLoader):
            loader = spec.loader
            loader.get_code = lambda name: compile(loader.get_source(name), loader.get_filename(name), 'exec', dont_inherit=True)
            original_exec = loader.exec_module
            def execute(module):
                original_exec(module)
                real_scheduler(module)
            loader.exec_module = execute
        elif isinstance(spec.loader, importlib.machinery.SourcelessFileLoader):
            raise ImportError('cached_bytecode_origin')
        return spec


def provider_attempt(kind):
    PROVIDER_ATTEMPTS.append(kind)
    persist(Path(PARAMS['output'])/f'PROVIDER-{os.getpid()}-{len(PROVIDER_ATTEMPTS)}.json',
            dict(pid=os.getpid(), role=ROLE, attempts=list(PROVIDER_ATTEMPTS)))
    raise PermissionError('provider_attempt_forbidden:' + kind)


def audit(event, args):
    if event == 'exec':
        filename = args[0].co_filename
        if filename.startswith('<frozen '):
            return
        if filename in ('<string>', '<unknown>'):
            caller = sys._getframe(1).f_code.co_filename
            require(caller in PARAMS['environment']['stdlib_files'], 'unbound_generated_code')
            return
        expected_file(filename)
    elif event == 'open' and isinstance(args[0], str) and args[0].endswith(('.pyc', '.pyo')):
        require(not Path(args[0]).exists(), 'cached_bytecode_read')
    elif event in ('socket.getaddrinfo', 'socket.gethostbyname', 'socket.gethostbyaddr'):
        provider_attempt(event)
    elif event in ('socket.connect', 'socket.bind', 'socket.sendto'):
        if args[0].family != socket.AF_UNIX:
            provider_attempt(event)
    elif event == 'subprocess.Popen':
        command = args[1]
        if ROLE == 'trial':
            from trial import member_command
            if command == member_command():
                return
        if command == ['ps', '-eo', 'pid=,ppid=,comm=,pcpu=', '--sort=-pcpu']:
            expected_file(PARAMS['environment']['os_tools']['ps']['path'])
            return
        if command == ['git', 'rev-parse', 'HEAD']:
            require(Path.cwd() == Path(PARAMS['candidate_checkout']), 'git_candidate_origin')
            expected_file(PARAMS['environment']['os_tools']['git']['path'])
            return
        raise PermissionError('unbound_subprocess')
    elif event in ('os.system', 'os.exec'):
        raise PermissionError('unbound_process_escape')


def resource_admission(phase, *, member=None):
    from attest import admission_errors, inspect
    d = PARAMS['declaration']
    snapshot = inspect(d['paths']['storage_paths'], PARAMS['controller_pid'])
    errors = admission_errors(snapshot, PARAMS['allocation'], d['storage_bounds'], PARAMS['environment'])
    ADMISSION_ERRORS.extend(errors)
    reserve = None
    if member is not None and not errors:
        from attest import reserve_storage
        try:
            reserve = reserve_storage(snapshot,d['storage_bounds'],member=member)
        except (KeyError,ValueError) as exc:
            errors.append('member_storage_reserve:'+str(exc))
            ADMISSION_ERRORS.append(errors[-1])
    persist(Path(PARAMS['output'])/f'ADMISSION-{os.getpid()}-{threading.get_native_id()}-{phase}.json',
            dict(version='v3-child-thread-admission', pid=os.getpid(), tid=threading.get_native_id(),
                 role=ROLE, phase=phase, declaration_sha256=PARAMS['declaration_sha256'],
                 snapshot=snapshot, errors=errors, storage_reserve=reserve, real_monotonic_ns=REAL_NS()))
    require(not errors, 'child_thread_resource_admission:' + ','.join(errors))


def receipt(phase):
    modules = {}
    for name, module in sorted(sys.modules.items()):
        spec = getattr(module, '__spec__', None)
        origin = getattr(spec, 'origin', None) if spec else getattr(module, '__file__', None)
        if origin is None or origin in ('built-in', 'frozen'):
            continue
        modules[name] = dict(origin=str(Path(origin).resolve()), sha256=expected_file(origin))
    process_stat = Path('/proc/self/stat').read_text()
    start_ticks = int(process_stat[process_stat.rfind(')')+2:].split()[19])
    persist(Path(PARAMS['output'])/f'ORIGIN-{os.getpid()}-{phase}.json',
        dict(version='v3-process-origin', pid=os.getpid(), parent_pid=os.getppid(), role=ROLE, phase=phase,
             process_start_ticks=start_ticks, real_monotonic_ns=REAL_NS(),
             candidate_sha=S, assembly_digest=ASSEMBLY, declaration_sha256=PARAMS['declaration_sha256'],
             infrastructure_digest=PARAMS['declaration']['infrastructure']['digest'],
             environment_sha256=PARAMS['declaration']['environment_sha256'], modules=modules,
             clock=CLOCK.sample() if CLOCK else None, provider_attempts=list(PROVIDER_ATTEMPTS),
             isolated=sys.flags.isolated, no_site=sys.flags.no_site, no_bytecode_writes=sys.dont_write_bytecode,
             net_namespace=os.readlink('/proc/self/ns/net')))


def ensure_release():
    require(RELEASE_ALLOWED and PARAMS is not None and CLOCK is not None, 'source_release_not_authorized')
    require(not PROVIDER_ATTEMPTS, 'provider_attempt_before_release')
    require(not ADMISSION_ERRORS, 'thread_admission_failed_before_release')


def initialize(role, *, project=True):
    global PARAMS, CLOCK, EXPECTED, ROLE, RELEASE_ALLOWED
    ROLE = role
    path = Path(os.environ['MM_STAGE_E_V3_PARAMS'])
    require(file_sha(path) == os.environ['MM_STAGE_E_V3_PARAMS_SHA'], 'child_bound_parameters')
    PARAMS = read(path)
    from declaration import authorize
    d = authorize(PARAMS['declaration_path'], PARAMS['owner_permit_path'], PARAMS['owner_key'], kind=PARAMS['kind'])
    require(PARAMS['declaration'] == d and file_sha(PARAMS['declaration_path']) == PARAMS['declaration_sha256'],
            'child_declaration_drift')
    ancestor = os.getpid()
    ancestry = []
    while ancestor > 1:
        ancestry.append(ancestor)
        stat = Path(f'/proc/{ancestor}/stat').read_text()
        ancestor = int(stat[stat.rfind(')')+2:].split()[1])
    require(PARAMS['controller_pid'] in ancestry, 'child_outside_admitted_controller_tree')
    from binding import verify_assembly
    manifest = verify_assembly(PARAMS['assembly'])
    environment = PARAMS['environment']
    require(environment == d['environment']['runtime_dependency_identities'], 'child_runtime_manifest')
    require(sys.version_info[:3] == (3, 12, 14) and file_sha(sys.executable) == environment['python_executable_hash'],
            'child_python_identity')
    source = Path(PARAMS['assembly'])/'source'
    EXPECTED = {str(source/name): row['sha256'] for name, row in manifest['files'].items()}
    EXPECTED.update(environment['stdlib_files'])
    EXPECTED.update(environment['dependencies']['websockets']['files'])
    EXPECTED.update(environment['mapped_libraries'])
    EXPECTED.update({row['path']: row['sha256'] for row in environment['os_tools'].values()})
    EXPECTED.update({str(INFRA/name): row['sha256'] for name, row in d['infrastructure']['files'].items()})
    sys.path[:] = [str(INFRA), str(source), environment['stdlib'], environment['stdlib']+'/lib-dynload',
                   environment['dependency_root']]
    require(sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode, 'nonisolated_child')
    require(not Path(sys.pycache_prefix).exists(), 'pycache_origin')
    require(os.readlink('/proc/self/ns/net') != d['executor']['admission_net_namespace'], 'network_namespace_not_isolated')
    interfaces = [p.name for p in Path('/sys/class/net').iterdir()]
    require(interfaces == ['lo'], 'network_namespace_external_interfaces')
    for line in Path('/proc/self/maps').read_text().splitlines():
        parts = line.split()
        if len(parts) >= 6 and parts[-1].startswith('/'):
            expected_file(parts[-1])
    sys.meta_path.insert(0, BoundFinder())
    resource_admission('initialized')
    if project:
        CLOCK = ProjectedClock(PARAMS['anchor'])
        time.time, time.time_ns = CLOCK.time, CLOCK.time_ns
        time.monotonic, time.monotonic_ns = CLOCK.monotonic, CLOCK.monotonic_ns
        time.clock_gettime = lambda which: CLOCK.time() if which == time.CLOCK_REALTIME else CLOCK.monotonic() if which == time.CLOCK_MONOTONIC else REAL_TIME.clock_gettime(which)
        time.clock_gettime_ns = lambda which: CLOCK.time_ns() if which == time.CLOCK_REALTIME else CLOCK.monotonic_ns() if which == time.CLOCK_MONOTONIC else REAL_TIME.clock_gettime_ns(which)
        asyncio.BaseEventLoop.time = lambda self: REAL_MONO()
        for module in list(sys.modules.values()):
            if module is not None:
                real_scheduler(module)
    native_thread_entry = threading.Thread._bootstrap_inner
    def guarded_thread(thread):
        # Covers subclasses overriding run too. _bootstrap_inner establishes the
        # native TID before calling this guarded target; no target runs unadmitted.
        actual_run = thread.run
        def guarded_run():
            resource_admission('thread-start')
            try:
                return actual_run()
            finally:
                resource_admission('thread-stop')
        thread.run = guarded_run
        return native_thread_entry(thread)
    threading.Thread._bootstrap_inner = guarded_thread
    multiprocessing.set_executable(str(INFRA/'child.sh'))
    # Audit is installed after signature-tool subprocesses and before native imports.
    sys.addaudithook(audit)
    receipt('initialized')
    terminated_once = []
    def terminated():
        if terminated_once:
            return
        terminated_once.append(True)
        resource_admission('terminated')
        receipt('terminated')
    atexit.register(terminated)
    if role == 'decoder-spawn':
        multiprocessing.util.Finalize(None, terminated, exitpriority=0)
    RELEASE_ALLOWED = role == 'member'
    return PARAMS
