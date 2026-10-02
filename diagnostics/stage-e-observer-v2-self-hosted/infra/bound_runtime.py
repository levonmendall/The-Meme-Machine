"""Fresh-environment origins, shared real-speed semantic clock and child guards."""
import atexit
import asyncio
import concurrent.futures
import hashlib
import importlib.abc
import importlib.machinery
import json
import mmap
import multiprocessing
import multiprocessing.connection
import multiprocessing.resource_tracker
import multiprocessing.spawn
import multiprocessing.util
import os
from pathlib import Path
import socket
import struct
import sys
import threading
import time
import types
from core import ASSEMBLY,BASE,INFRA,S,REAL_NS,REAL_MONO,file_sha,persist,read,sha

PARAMS=None
CLOCK=None
EXPECTED={}
PROVIDER_ATTEMPTS=[]
IMPORTS={}
ROLE='uninitialized'
REAL_TIME_MODULE=types.ModuleType('observer_real_scheduler_time')
REAL_TIME_MODULE.__dict__.update(vars(time))


def real_scheduler_bindings(module):
    """Keep standard-library OS/scheduler deadlines real, including late imports."""
    origin=getattr(module,'__file__',None)
    if not origin or str(Path(origin).resolve()) not in PARAMS['environment']['stdlib_files']:return
    for name,value in list(vars(module).items()):
        if value is time:
            setattr(module,name,REAL_TIME_MODULE)
        elif CLOCK is not None:
            for clock_name in ('time','time_ns','monotonic','monotonic_ns','clock_gettime','clock_gettime_ns'):
                if value is getattr(time,clock_name):
                    setattr(module,name,getattr(REAL_TIME_MODULE,clock_name));break


class ProjectedClock:
    def __init__(self,path):
        self.file=Path(path).open('r+b',buffering=0)
        self.shared=mmap.mmap(self.file.fileno(),8)
    def anchor(self):return struct.unpack_from('=Q',self.shared)[0]
    def activate(self):
        if self.anchor():raise ValueError('semantic_epoch_reanchored')
        anchor=REAL_NS()
        struct.pack_into('=Q',self.shared,0,anchor)
        return anchor
    def elapsed_ns(self):
        anchor=self.anchor()
        return max(0,REAL_NS()-anchor) if anchor else 0
    def time_ns(self):return 1800000000*10**9+self.elapsed_ns()
    def monotonic_ns(self):return 100*10**9+self.elapsed_ns()
    def time(self):return self.time_ns()/10**9
    def monotonic(self):return self.monotonic_ns()/10**9
    def sample(self):
        return dict(anchor_real_monotonic_ns=self.anchor(),wall=self.time(),
            monotonic=self.monotonic(),real_monotonic_ns=REAL_NS())


def expected_file(path):
    name=str(Path(path).resolve())
    checksum=EXPECTED.get(name)
    if not checksum or file_sha(name)!=checksum:
        raise ImportError('unbound_executable_origin:'+name)
    return checksum


class BoundFinder(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        spec=importlib.machinery.PathFinder.find_spec(fullname,path,target)
        if spec is None:return None
        if spec.origin in ('built-in','frozen'):return spec
        if spec.origin is None:
            locations=spec.submodule_search_locations or []
            if any(not Path(p).resolve().is_relative_to(BASE/'assembly/source') for p in locations):
                raise ImportError('unbound_namespace:'+fullname)
            return spec
        checksum=expected_file(spec.origin)
        IMPORTS[fullname]=dict(origin=str(Path(spec.origin).resolve()),sha256=checksum)
        if isinstance(spec.loader,importlib.machinery.SourceFileLoader):
            loader=spec.loader
            spec.loader.get_code=lambda name,loader=loader:compile(
                loader.get_source(name),loader.get_filename(name),'exec',dont_inherit=True)
            execute=loader.exec_module
            def execute_with_scheduler(module,execute=execute):
                execute(module)
                real_scheduler_bindings(module)
            loader.exec_module=execute_with_scheduler
        elif isinstance(spec.loader,importlib.machinery.SourcelessFileLoader):
            raise ImportError('bytecode_only_origin')
        return spec


def deny_provider(kind):
    PROVIDER_ATTEMPTS.append(kind)
    persist(Path(PARAMS['output'])/f'PROVIDER_ATTEMPT-{os.getpid()}.json',
        dict(pid=os.getpid(),role=ROLE,attempts=PROVIDER_ATTEMPTS))
    raise PermissionError('benchmark_provider_access:'+kind)


def audit_event(event,args):
    if event=='exec':
        filename=args[0].co_filename
        if filename.startswith('<frozen '):return
        if filename in ('<string>','<unknown>'):
            caller=sys._getframe(1).f_code.co_filename
            if caller in PARAMS['environment']['stdlib_files']:return
            raise PermissionError('unbound_generated_code')
        expected_file(filename)
    elif event=='open' and isinstance(args[0],str) and args[0].endswith(('.pyc','.pyo')):
        # A non-existing -X pycache_prefix prevents startup cached reads too.
        if Path(args[0]).exists():raise PermissionError('cached_bytecode_read')
    elif event in ('socket.getaddrinfo','socket.gethostbyname','socket.gethostbyaddr'):
        deny_provider(event)
    elif event in ('socket.connect','socket.bind'):
        if args[0].family not in (socket.AF_UNIX,):deny_provider(event)
    elif event=='socket.sendto':
        if args[0].family!=socket.AF_UNIX:deny_provider(event)
    elif event=='subprocess.Popen':
        command=args[1]
        if ROLE=='trial':
            from core import runtime_command
            if command==runtime_command('bootstrap.py','--member'):
                return
        permitted=(['ps','-eo','pid=,ppid=,comm=,pcpu=','--sort=-pcpu'],['git','rev-parse','HEAD'])
        if command not in permitted:raise PermissionError('unbound_subprocess')
        name=command[0];tool=PARAMS['os_tools'][name]
        if file_sha(tool['path'])!=tool['sha256']:raise PermissionError('os_tool_drift')
        if name=='git' and Path.cwd()!=BASE/'candidate-checkout':raise PermissionError('git_checkout_origin')
    elif event=='os.system':raise PermissionError('unbound_shell')


def receipt(phase):
    modules={}
    for name,module in sorted(sys.modules.items()):
        spec=getattr(module,'__spec__',None)
        origin=getattr(spec,'origin',None) if spec else getattr(module,'__file__',None)
        if origin is None or origin in ('built-in','frozen'):continue
        modules[name]=dict(origin=str(Path(origin).resolve()),sha256=expected_file(origin))
    row=dict(version='observer-process-origin-receipt-v1',pid=os.getpid(),parent_pid=os.getppid(),
        role=ROLE,phase=phase,assembly_digest=ASSEMBLY,candidate_sha=S,
        infrastructure_manifest_sha256=PARAMS['infrastructure_manifest_sha256'],
        projected_clock_installed=CLOCK is not None,
        clock=CLOCK.sample() if CLOCK else None,modules=modules,
        provider_attempts=list(PROVIDER_ATTEMPTS),isolated=sys.flags.isolated,
        no_site=sys.flags.no_site,no_bytecode_writes=sys.dont_write_bytecode,
        pycache_prefix=sys.pycache_prefix,network_namespace=os.readlink('/proc/self/ns/net'))
    persist(Path(PARAMS['output'])/f'ORIGIN-{os.getpid()}-{phase}.json',row)
    return row


def fork_initializer():
    global ROLE
    ROLE='archive-fork'
    receipt('initialized')
    multiprocessing.util.Finalize(None,receipt,args=('terminated',),exitpriority=0)


def initialize(role,*,project=True):
    global PARAMS,CLOCK,ROLE,EXPECTED
    ROLE=role
    params=Path(os.environ['MM_OBSERVER_PARAMS'])
    if file_sha(params)!=os.environ['MM_OBSERVER_PARAMS_SHA']:raise ValueError('bound_parameters')
    PARAMS=read(params)
    environment=PARAMS['environment']
    if sys.version_info[:3]!=(3,12,14) or file_sha(sys.executable)!=environment['python_executable_hash']:
        raise ValueError('fresh_python_origin')
    manifest=read(BASE/'assembly/assembly.json')
    digest=manifest.pop('assembly_digest')
    if digest!=ASSEMBLY or sha(__import__('core').canonical(manifest))!=ASSEMBLY:
        raise ValueError('assembly_manifest_origin')
    source=BASE/'assembly/source'
    EXPECTED={str(source/name):info['sha256'] for name,info in manifest['files'].items()}
    EXPECTED.update(environment['stdlib_files'])
    EXPECTED.update(environment['dependencies']['websockets']['files'])
    infra=read(INFRA/'INFRASTRUCTURE.json')
    if file_sha(INFRA/'INFRASTRUCTURE.json')!=PARAMS['infrastructure_manifest_sha256']:
        raise ValueError('infrastructure_manifest')
    for name,info in infra['files'].items():
        EXPECTED[str(INFRA/name)]=info['sha256']
        if file_sha(INFRA/name)!=info['sha256']:raise ValueError('infrastructure_drift')
    sys.dont_write_bytecode=True
    sys.path[:]=[str(INFRA),str(source),environment['stdlib'],
        environment['stdlib']+'/lib-dynload',environment['dependency_root']]
    sys.meta_path.insert(0,BoundFinder())
    sys.addaudithook(audit_event)
    if project:
        CLOCK=ProjectedClock(PARAMS['anchor'])
        time.time=CLOCK.time;time.time_ns=CLOCK.time_ns
        time.monotonic=CLOCK.monotonic;time.monotonic_ns=CLOCK.monotonic_ns
        real_clock_gettime=time.clock_gettime;real_clock_gettime_ns=time.clock_gettime_ns
        time.clock_gettime=lambda which: CLOCK.time() if which==time.CLOCK_REALTIME else CLOCK.monotonic() if which==time.CLOCK_MONOTONIC else real_clock_gettime(which)
        time.clock_gettime_ns=lambda which: CLOCK.time_ns() if which==time.CLOCK_REALTIME else CLOCK.monotonic_ns() if which==time.CLOCK_MONOTONIC else real_clock_gettime_ns(which)
        # OS waits and event-loop timers stay real even during frozen bootstrap.
        asyncio.BaseEventLoop.time=lambda self:REAL_MONO()
        for module in list(sys.modules.values()):
            if module is not None:real_scheduler_bindings(module)
    multiprocessing.set_executable(str(INFRA/'child.sh'))
    receipt('initialized')
    atexit.register(receipt,'terminated')
    return PARAMS
