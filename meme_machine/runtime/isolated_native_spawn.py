"""Fixed pre-Python owner-death fence for the explicit copied native profile.

No compiler, preexec_fn, environment-selected executable or privileged helper.
The same static shim is used by both pinned CPython spawn and resource_tracker.
The original native source owns its retained thread/tracker under the same
shutdown fence as the actual decoder/history workers.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from contextvars import ContextVar
import errno
import fcntl
import multiprocessing.resource_tracker as tracker
import multiprocessing.util as util
import os
from pathlib import Path
import signal
import stat
import struct
import sys
import threading

from meme_machine.operational.isolated_native_layout import NativeChildLayout

SHIM_PATH='runtime/bin/native-spawn'
_ROLE=ContextVar('isolated_native_spawn_role',default=None)
_ACTIVE=None
# Auditable x86_64 Linux code, SHA256 d14fe952caf0533b585a7755b877e77570d2635cedd2f0889cec002850393761.
# Source assembly is engineering/diagnostics/native_spawn_shim_v1.S. No absolute
# address relocations: the final RIP-relative label is the appended Python path.
_MACHINE=bytes.fromhex(
 '4989e44881ecb00000004989e64c8d7c2410b805000000bf050000004c89fe0f054885c0'
 '0f88b3000000418b47182500f000003d001000000f859f000000b848000000bf05000000'
 'be0300000031d20f054885c00f888300000083e003757e41c706050000006641c7460419'
 '00e879000000b86e0000000f054989c5b89d000000bf01000000be0900000031d24531d2'
 '4531c00f054885c07843b86e0000000f054c39e87537e840000000b803000000bf0500'
 '00000f054885c07821488d3d4600000049897c2408498d742408498b1424498d54d410'
 'b83b0000000f05bf7d000000b83c0000000f050f0b6641c7460600004c89f7be010000'
 '0031d2b8070000000f054885c075d5c3')


class NativeSpawnRefused(RuntimeError):pass


def _require(value,code):
    if not value:raise NativeSpawnRefused(code)


def trampoline(python):
    """Exact immutable static ELF; argv/env cannot select its exec target."""
    path=Path(python)
    _require(path.is_absolute() and '..' not in path.parts and path.name=='python3.12'
        and path.parent.name=='bin' and path.parent.parent.name=='runtime'
        and path.parent.parent.parent.name=='native-image','isolated_native_spawn_executable')
    raw=os.fsencode(path)
    _require(0<len(raw)<=4095 and b'\0' not in raw,'isolated_native_spawn_executable')
    size=176+len(_MACHINE)+len(raw)+1
    header=struct.pack('<16sHHIQQQIHHHHHH',b'\x7fELF\x02\x01\x01'+b'\0'*9,
        2,62,1,0x4000b0,64,0,0,64,56,2,0,0,0)
    load=struct.pack('<IIQQQQQQ',1,5,0,0x400000,0,size,size,4096)
    stack=struct.pack('<IIQQQQQQ',0x6474e551,6,0,0,0,0,0,16)
    return header+load+stack+_MACHINE+raw+b'\0'


def current_spawn_scope():
    if _ACTIVE is not None:
        _require(os.getpid()==_ACTIVE.pid,'isolated_native_spawn_foreign_process')
    return _ACTIVE


@contextmanager
def pool_start(role):
    scope=current_spawn_scope()
    if scope is None:yield;return
    _require(role in ('decoder','history') and scope._registered and not scope._closing,
        'isolated_native_spawn_owner_required')
    token=_ROLE.set(role)
    try:yield
    finally:_ROLE.reset(token)


class NativeSpawnScope:
    def __init__(self,layout):
        global _ACTIVE
        self._closed=False;self._closing=False;self._registered=False
        self._owner=None;self._owner_ident=None;self._tracker_pid=None;self._joined=True;self._lock=threading.RLock()
        self._read=self._write=None;self._original=None
        self._kernel_executors={'decoder':None,'history':None};self._kernel_tracker_spawned=False
        self._kernel_spawned={'decoder':0,'history':0}
        _require(_ACTIVE is None and type(layout) is NativeChildLayout,'isolated_native_spawn_scope')
        layout.require_entry();self.layout=layout;self.pid=os.getpid()
        _require(tracker._resource_tracker._fd is None and tracker._resource_tracker._pid is None,
            'isolated_native_spawn_preexisting_tracker')
        _require(Path(sys.executable).resolve()==layout.executable
            and os.environ.get('LD_LIBRARY_PATH')==layout.environment()['LD_LIBRARY_PATH'],
            'isolated_native_spawn_runtime')
        for key in ('LD_PRELOAD','LD_AUDIT','LD_DEBUG','LD_PROFILE','PYTHONHOME','PYTHONPATH'):
            _require(key not in os.environ,'isolated_native_spawn_environment')
        path=Path(layout.image_root)/SHIM_PATH;info=path.lstat()
        _require(stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode)==0o500
            and info.st_uid==os.geteuid() and info.st_nlink==1
            and path.resolve()==path and path.read_bytes()==trampoline(layout.executable),
            'isolated_native_spawn_shim_identity')
        self.shim=os.fsencode(path)
        try:
            for fd in (5,6):
                try:os.fstat(fd)
                except OSError as error:_require(error.errno==errno.EBADF,'isolated_native_spawn_reserved_fds')
                else:raise NativeSpawnRefused('isolated_native_spawn_reserved_fds')
            self._read,self._write=os.pipe2(os.O_CLOEXEC)
            _require((self._read,self._write)==(5,6),'isolated_native_spawn_reserved_fds')
            from .isolated_native_execution import install_isolated_native_execution
            self._owner=ThreadPoolExecutor(max_workers=1,thread_name_prefix='isolated-native-spawn-owner',
                initializer=install_isolated_native_execution)
            self._original=util.spawnv_passfds
            util.spawnv_passfds=self._spawn
            _ACTIVE=self
        except BaseException:
            self._release();raise

    def register_source(self,resources):
        from .isolated_native_resources import require_resources
        cap=require_resources(resources)
        _require(cap.root==self.layout.state_directory and not self._registered and not self._closing,
            'isolated_native_spawn_source_owner')
        self._registered=True

    def _spawn(self,path,args,passfds):
        _require(os.getpid()==self.pid and _ROLE.get() in ('decoder','history')
            and self._registered and not self._closing,'isolated_native_spawn_owner_required')
        expected=os.fsencode(self.layout.executable)
        _require(os.fsencode(path)==expected and args and os.fsencode(args[0])==expected,
            'isolated_native_spawn_executable')
        original=tuple(passfds)
        _require(all(type(fd) is int and fd>=0 for fd in original)
            and not {3,4,5,6}.intersection(original),'isolated_native_spawn_descriptor_authority')
        _require(os.environ.get('LD_LIBRARY_PATH')==self.layout.environment()['LD_LIBRARY_PATH']
            and not any(key in os.environ for key in ('LD_PRELOAD','LD_AUDIT','LD_DEBUG','LD_PROFILE',
                'PYTHONHOME','PYTHONPATH')),'isolated_native_spawn_environment')
        # PDEATHSIG belongs to the creating THREAD. Every fork/exec therefore
        # runs on this one retained owner, not a short-lived submitting thread.
        mask=signal.pthread_sigmask(signal.SIG_BLOCK,set())
        return self._owner.submit(self._launch,list(args),original,mask,_ROLE.get()).result()

    def _launch(self,args,passfds,mask,role):
        with self._lock:
            _require(not self._closing,'isolated_native_spawn_stopped')
            self._owner_ident=threading.get_ident()
            args[0]=self.shim
            # Pinned CPython's tracker command is source-owned, never supplied
            # by a provider. Keep its actual PID in this lifetime owner.
            text=[os.fsdecode(arg) for arg in args]
            is_tracker=('-c' in text and text[text.index('-c')+1].startswith(
                    'from multiprocessing.resource_tracker import main;main('))
            _require(not is_tracker or self._tracker_pid is None,'isolated_native_spawn_tracker_replacement')
            # resource_tracker deliberately blocks TERM/INT around its spawn.
            # Moving fork_exec to this owner must preserve that exact caller
            # mask, including for ordinary workers, then restore our own mask.
            previous=signal.pthread_sigmask(signal.SIG_SETMASK,mask)
            try:pid=self._original(self.shim,args,tuple(sorted((*passfds,5))))
            finally:signal.pthread_sigmask(signal.SIG_SETMASK,previous)
            if is_tracker:
                self._tracker_pid=pid;self._joined=False;self._kernel_tracker_spawned=True
            else:self._kernel_spawned[role]+=1
            return pid

    @property
    def owners_joined(self):return self._joined and self._closed

    @property
    def unjoined_processes(self):return self._tracker_pid is not None and not self._joined

    def record_kernel_executor(self,role,summary):
        _require(os.getpid()==self.pid and role in self._kernel_executors and self._registered,
            'isolated_native_kernel_executor_owner')
        with self._lock:self._kernel_executors[role]=dict(summary)

    def kernel_lifecycle_snapshot(self):
        # Fixed entry calls only after the original shutdown/close succeeded.
        if not self.owners_joined:return dict(state='UNJOINED')
        return dict(state='JOINED',tracker_spawned=self._kernel_tracker_spawned,
            tracker_joined=self._kernel_tracker_spawned and self._tracker_pid is not None
                and tracker._resource_tracker._pid is None,
            spawn_owner_joined=True,workers_spawned=dict(self._kernel_spawned),
            executors={role:(dict(value) if value is not None else
                dict(state='UNAVAILABLE')) for role,value in self._kernel_executors.items()})

    def _release(self):
        global _ACTIVE
        if self._original is not None and util.spawnv_passfds==self._spawn:
            util.spawnv_passfds=self._original
        for name in ('_read','_write'):
            fd=getattr(self,name)
            if fd is not None:
                setattr(self,name,None);os.close(fd)
        if _ACTIVE is self:_ACTIVE=None

    def close(self):
        if self._closed:return
        _require(os.getpid()==self.pid,'isolated_native_spawn_foreign_process')
        _require(threading.get_ident()!=self._owner_ident,'isolated_native_spawn_owner_self_join')
        with self._lock:self._closing=True
        # The source registry invokes this AFTER actual decoder/history joins,
        # within its original drain fence. A blocked tracker remains owned by
        # this same close thread; fixed-entry fatal handoff never closes it.
        if self._tracker_pid is not None:
            _require(tracker._resource_tracker._pid==self._tracker_pid,
                'isolated_native_spawn_tracker_owner')
            tracker._resource_tracker._stop()
            _require(tracker._resource_tracker._pid is None,'isolated_native_spawn_tracker_unjoined')
        self._joined=True
        if self._owner is not None:self._owner.shutdown(wait=True,cancel_futures=True)
        self._release();self._closed=True
