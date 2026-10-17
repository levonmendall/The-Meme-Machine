"""Fixed contained child entrypoint; no ordinary operational authority.

The reviewed copied-image launcher owns the OS boundary and FD provenance.
FD3 is its checked anonymous parent channel; FD4 is its checked anonymous,
read-only sizing pipe. A JSON checksum is not parent authentication. This reader
trusts only that protected descriptor origin, binds its session and reviewed
image identity, and retains the native valuation deadlines unchanged.
"""
import fcntl
import json
import os
from pathlib import Path
import select
import signal
import socket
import stat
import sys
import threading
import time
from .isolated_native_lifetime import NativeOwnerDrainFailure


class IsolatedEntryBlocked(ValueError):
    pass


def _require(condition, code):
    if not condition:
        raise IsolatedEntryBlocked(code)


class ParentSizingReader:
    """Bounded, source/session-bound facts from the existing protected parent.

    This is a receiving contract. It neither produces financial observations nor
    proves that a producer read a journal or USD source. The protected parent
    must perform those genuine reads under the original fences before writing.
    There is currently no live producer/workflow integration for this contract.
    """
    def __init__(self, descriptor, *, session, source_commit, source_tree, stopped):
        _require(type(descriptor) is int and descriptor >= 0
            and stat.S_ISFIFO(os.fstat(descriptor).st_mode)
            and fcntl.fcntl(descriptor,fcntl.F_GETFL) & os.O_ACCMODE == os.O_RDONLY
            and str(Path('/proc/self/fd/'+str(descriptor)).readlink()).startswith('pipe:[')
            and type(session) is str and len(session) == 43 and callable(stopped),
            'isolated_native_parent_sizing_pipe_required')
        for value in (source_commit,source_tree):
            _require(type(value) is str and len(value) == 40
                and all(char in '0123456789abcdef' for char in value),
                'isolated_native_parent_source_identity')
        self.descriptor=descriptor
        self.session=session
        self.source_commit,self.source_tree=source_commit,source_tree
        self.stopped=stopped
        self.closed=False
        self.buffer=bytearray()
        self.messages=0

    def receive(self, *, seconds=5):
        _require(type(seconds) in (int,float) and 0 < seconds <= 5,
            'isolated_native_sizing_deadline')
        _require(not self.closed and not self.stopped(),'isolated_native_stopped')
        deadline=time.monotonic()+seconds
        while b'\n' not in self.buffer:
            _require(not self.closed and not self.stopped(), 'isolated_native_stopped')
            remaining=deadline-time.monotonic()
            _require(remaining>0,'isolated_native_parent_sizing_unavailable')
            readable,_,_=select.select([self.descriptor],[],[],min(.25,remaining))
            if not readable:
                continue
            chunk=os.read(self.descriptor,min(4096,65537-len(self.buffer)))
            _require(bool(chunk),'isolated_native_parent_sizing_eof')
            self.buffer.extend(chunk)
            _require(len(self.buffer)<=65536,'isolated_native_parent_sizing_bound')
        line,_,tail=self.buffer.partition(b'\n')
        self.buffer=bytearray(tail)
        self.messages+=1
        _require(self.messages<=1024,'isolated_native_parent_sizing_message_bound')
        from .child_transport import _json
        packet=_json(line)
        _require(type(packet) is dict and set(packet)=={'schema','session','facts'}
            and packet['schema']=='protected-parent-native-sizing-v1'
            and packet['session']==self.session and type(packet['facts']) is dict,
            'isolated_native_parent_sizing_envelope')
        receipt=packet['facts']
        _require(receipt.get('source_commit')==self.source_commit
            and receipt.get('source_tree')==self.source_tree,
            'isolated_native_parent_sizing_source_changed')
        from meme_machine.runtime.isolated_native_resources import AuthenticatedSizingFacts
        from meme_machine.runtime.journal import canonical
        retained=canonical(receipt)
        # The protected anonymous descriptor is the origin authenticator. Exact
        # detached equality prevents later mutation, and is not a hash/signature
        # pretending to prove an unperformed parent financial/USD read.
        return AuthenticatedSizingFacts(receipt,authenticate=lambda candidate:
            not self.closed and canonical(candidate)==retained)

    def apply_next(self, resources, *, seconds=5):
        from meme_machine.runtime.isolated_native_resources import require_resources
        resources=require_resources(resources)
        return resources.replace_authenticated_sizing_facts(self.receive(seconds=seconds))

    def close(self):
        if not self.closed:
            self.closed=True
            os.close(self.descriptor)


def _image_identity():
    path=Path('/image/manifest.json')
    _require(path.is_file() and not path.is_symlink() and path.stat().st_size<=512*1024,
        'isolated_native_image_manifest_required')
    value=json.loads(path.read_bytes())
    _require(type(value) is dict and value.get('schema')=='isolated-native-copied-image-v1'
        and value.get('financial_authority') is False and type(value.get('provider_calls')) is int
        and value['provider_calls']==0 and value.get('actual_service_restrictions_verified') is False,
        'isolated_native_image_manifest_required')
    for field in ('source_commit','source_tree'):
        _require(type(value.get(field)) is str and len(value[field])==40
            and all(char in '0123456789abcdef' for char in value[field]),
            'isolated_native_image_identity')
    return value


def _new_resources(facts):
    from meme_machine.runtime.isolated_native_resources import IsolatedNativeResources
    return IsolatedNativeResources('/work/native/state',sizing_facts=facts,clock=time.time)


def _terminal_process_exit(receipt):
    """Fixed entry only: bounded nonblocking failure output, then owned exit.

    No second graceful-drain interval is added. Kernel PID1 termination and the
    original parent own process/transport uncertainty cleanup after this point.
    """
    try:
        raw=json.dumps(receipt,sort_keys=True,separators=(',',':'),allow_nan=False).encode()+b'\n'
        if len(raw)>65536:
            raw=json.dumps(dict(schema='isolated-native-child-v1',status='BLOCKED',
                financial_authority=False,normal_readiness=False,graceful_shutdown=False,
                all_workers_joined=False,failure_code='isolated_native_shutdown_incomplete',
                cleanup_disposition='OWNED_PROCESS_TERMINATION_REQUIRED'),separators=(',',':')).encode()+b'\n'
        os.set_blocking(1,False)
        deadline=time.monotonic()+.1
        while raw and time.monotonic()<deadline:
            try:count=os.write(1,raw)
            except BlockingIOError:
                select.select([], [1], [], min(.01,max(0,deadline-time.monotonic())))
                continue
            if count<=0:break
            raw=raw[count:]
    except BaseException:
        pass
    finally:
        os._exit(2)


def main():
    """Only the fixed launcher may call this with its two retained capabilities."""
    from meme_machine.runtime import stop
    stopped=threading.Event()
    def cancel(_signum,_frame):
        stopped.set()
        stop.requested.set()
    # Namespace PID1 must install these before any blocking IPC/import/startup.
    for number in (signal.SIGTERM,signal.SIGINT):
        signal.signal(number,cancel)
    receipt=dict(schema='isolated-native-child-v1',status='BLOCKED',
        financial_authority=False,normal_readiness=False,provider_workload_started=False,
        held_protection='UNEXERCISED',fills='UNEXERCISED',settlement='UNEXERCISED')
    channel=None;reader=None;resources=None;ports=None;terminal=None
    try:
        _require(len(sys.argv)==1 and Path.cwd()==Path('/work/native'),
            'isolated_native_fixed_entry_required')
        image=_image_identity()
        receipt.update(source_commit=image['source_commit'],source_tree=image['source_tree'])
        from .child_transport import ChildChannel
        channel=ChildChannel(socket.socket(fileno=3),seconds=1800,cancelled=stopped.is_set)
        reader=ParentSizingReader(4,session=channel.session,
            source_commit=image['source_commit'],source_tree=image['source_tree'],stopped=stopped.is_set)
        # A sampler is never substituted for the source owner. This literal
        # reviewed module must implement the actual native source/ProcessPool,
        # FULL delivery, consumers, backpressure and cancellation before launch.
        try:
            from .isolated_native_source import run_contained
        except ModuleNotFoundError as error:
            if error.name!='meme_machine.operational.isolated_native_source':
                raise
            raise IsolatedEntryBlocked('isolated_native_source_executor_unavailable') from None
        facts=reader.receive()
        from meme_machine.runtime.isolated_native_bootstrap import NativeRunnerPorts
        resources=_new_resources(facts)
        ports=NativeRunnerPorts(resources,channel)
        resources.enable_native_commit_measurement(ports)
        from meme_machine.runtime.isolated_native_execution import isolated_native_execution
        with isolated_native_execution(resources):
            result=run_contained(resources=resources,ports=ports,sizing_reader=reader,stopped=stopped)
        _require(type(result) is dict and result.get('financial_authority') is False,
            'isolated_native_source_result_required')
        receipt.update(status='COMPLETED',observation=result,provider_workload_started=True)
    except NativeOwnerDrainFailure as error:
        terminal=error # Retain live Runner/threads until process death.
        receipt.update(failure_code='isolated_native_shutdown_incomplete',
            provider_workload_started=None,native_lifecycle_started=True,
            graceful_shutdown=False,all_workers_joined=False,
            cleanup_disposition='OWNED_PROCESS_TERMINATION_REQUIRED',
            physical_process_cleanup='UNVERIFIED_UNTIL_PARENT_REAP',observation=error.receipt)
    except IsolatedEntryBlocked as error:
        receipt['failure_code']=str(error)
    except BaseException as error:
        # Only fixed local classification is published, never a packet, provider
        # body, arbitrary exception message or hidden successful readiness flag.
        receipt['failure_code']='isolated_native_child_failed'
        receipt['failure_type']=type(error).__name__
    finally:
        stopped.set()
        stop.requested.set()
        if terminal is not None:
            # Closing channel/reader/cache/SQLite here would race the owners
            # whose failed drain triggered this handoff. Generic libraries do
            # not exit; only this fixed descriptor/image-checked entry does.
            _terminal_process_exit(receipt)
        closing=[owner.close for owner in (ports,resources,reader) if owner is not None]
        if channel is not None:closing.append(channel.abort_and_join)
        for close in closing:
            try:close()
            except BaseException as error:
                receipt.update(status='BLOCKED',failure_code='isolated_native_child_cleanup_failed',
                    failure_type=type(error).__name__)
        print(json.dumps(receipt,sort_keys=True,separators=(',',':')),flush=True)
    return 0 if receipt['status']=='COMPLETED' else 2


if __name__=='__main__':
    raise SystemExit(main())
