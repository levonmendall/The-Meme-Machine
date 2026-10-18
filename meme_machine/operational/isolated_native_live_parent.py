"""Explicit protected-parent integration; no action, environment or live fallback.

The original administration caller authenticates source/dependencies, the real
financial read callbacks, provider allowance/history and its continuously held
ownership fence. This module cannot establish those host facts from JSON. It
does not create a Budget, grant, financial book, signing or production writer.
Only the existing copied child receives detached sizing data and private IPC.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import os
from pathlib import Path
import secrets
import socket
import stat
import threading
import time

from .bounded_provider import Budget
from .child_transport import ChildChannel,ChildRPCPort
from .isolated_native_image import NativeImageApproval
from .isolated_native_live_scope import LiveNativeScope
from .isolated_native_landlock_launcher import launch_native,prepare_native,native_policy_record
from .isolated_native_lifetime import NativeOwnerDrainFailure
from .parent_channel import ParentChannel,serve_connected
from .parent_sizing import ParentSizingProducer,financial_basis
from .parent_transport import ParentHTTP,SourceBinding,NativeSourceBinding,NativeFactoryMap
from .pons_native_profile import ParentPonsProfiles
from .transport_bridge import EndpointAlias,READ_METHODS
from meme_machine.runtime.journal import canonical

_REAL_LAUNCH=launch_native
_REAL_PREPARE=prepare_native
FACTS_BYTES=16384
WORK_SECONDS=900
STARTUP_SECONDS=300
DRAIN_SECONDS=65
SIZING_SECONDS=5


class LiveParentRefused(ValueError):pass


def require(condition,code):
    if not condition:raise LiveParentRefused(code)


def _failure(stage,error):
    result=dict(stage=stage,error_class=type(error).__name__)
    allowed={'meme_machine.operational.isolated_native_live_parent',
        'meme_machine.operational.parent_sizing','meme_machine.runtime.usd_valuation',
        'meme_machine.operational.child_transport','meme_machine.lanes.pons.provider',
        'meme_machine.lanes.pons.provider_topology','meme_machine.lanes.pons.pons_selective_acquisition'}
    trace=error.__traceback__
    while trace is not None:
        name=trace.tb_frame.f_globals.get('__name__')
        if name in allowed and trace.tb_frame.f_code.co_name not in ('require','_require'):
            result['source_site']=dict(module=name,function=trace.tb_frame.f_code.co_name,line=trace.tb_lineno)
        trace=trace.tb_next
    return result


class ProtectedFinancialInput:
    """Trusted caller ports, not authentication of arbitrary supplied JSON.

    read_financial is the original constructor-free, read-only full replay;
    validate_scope freshly proves the protected owner's original host fence,
    exact source and unchanged financial selection/head. Both run only on the
    creating parent PID/thread. The full state never crosses child IPC.
    """
    def __init__(self,read_financial,validate_scope):
        require(callable(read_financial) and callable(validate_scope),'live_financial_callbacks')
        self._read=read_financial;self._validate=validate_scope
        self._owner=(os.getpid(),threading.get_ident());self._encoded=None

    def validate(self):
        require(self._owner==(os.getpid(),threading.get_ident()),'live_financial_owner')
        require(self._validate() is True,'live_financial_scope_unverified')
        return True

    def capture(self):
        require(self._encoded is None,'live_financial_one_snapshot')
        self.validate();financial,state=self._read();self.validate()
        financial_basis(financial,state)
        self._encoded=canonical([financial,state])
        return self.detached()

    def detached(self):
        self.validate()
        require(self._encoded is not None,'live_financial_snapshot_required')
        return json.loads(self._encoded)


def _private_root(path):
    path=Path(path)
    require(path.is_absolute() and path.resolve(strict=True)==path
        and stat.S_ISDIR(path.stat().st_mode) and path.stat().st_uid==os.geteuid()
        and stat.S_IMODE(path.stat().st_mode)==0o700,'live_parent_private_root')
    from .namespace_canary import _MARKERS
    for node in (path,*path.parents):
        require(not stat.S_ISLNK(node.lstat().st_mode)
            and not any((node/name).exists() for name in _MARKERS),'live_parent_financial_path')
    require(not any(path==Path(name) or Path(name) in path.parents for name in
        ('/srv/meme-machine','/etc/meme-machine')),'live_parent_production_path')
    return path


def _owned_file(root,path):
    path=Path(path)
    require(path.is_absolute() and path.resolve(strict=True)==path and root in path.parents,
        'live_parent_control_path')
    for name in (path,*path.parents):
        require(not stat.S_ISLNK(name.lstat().st_mode),'live_parent_control_link')
        if name==root:break
    info=path.stat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid==os.geteuid()
        and info.st_nlink==1 and not stat.S_IMODE(info.st_mode)&0o077,'live_parent_control_inode')
    return path


def _sources(environ,governor,admission):
    """The same complete native registry, from actual configured identities."""
    sol=SourceBinding.configured(EndpointAlias('pump-discovery','solana',READ_METHODS['solana']),
        'pump_discovery',environ=environ,governor=governor)
    pons=SourceBinding.configured(EndpointAlias('pons-discovery','robinhood',READ_METHODS['robinhood']),
        'pons_discovery',environ=environ,admission=admission)
    rows=[]
    for base,lane in ((sol,'pump'),(pons,'pons')):
        for regime in ('current','survivor','discovery'):
            rows.append(replace(base,alias=EndpointAlias(lane+'-'+regime,base.alias.family,base.alias.methods),
                operation=lane+'_discovery' if regime=='discovery' else lane+'_'+regime+'_qualification'))
    for operation in ('pump_history_receipt','pump_recovery_restart','pump_source_identity'):
        for priority in range(1,7):
            rows.append(replace(sol,alias=EndpointAlias(operation+'_'+str(priority),'solana',sol.alias.methods),
                operation=operation,read_class='solana_evidence_'+str(priority)))
    for alias in ('yellowstone','solana-websocket'):
        rows.append(replace(sol,alias=EndpointAlias(alias,'solana',sol.alias.methods),
            operation='pump_source_identity'))
    by_name={row.alias.name:row for row in rows}
    native=tuple(NativeSourceBinding.configured(by_name[alias],kind,environ=environ) for alias,kind in
        (('yellowstone','yellowstone'),('solana-websocket','solana_websocket'),
         ('pons-discovery','robinhood_sequencer')))
    return rows,native


class _SizingOwner:
    """One real sizing thread and its actual native RPC/cache lifetimes."""
    def __init__(self,root,stopped,seconds):
        self.root=root;self.stopped=stopped;self.seconds=seconds
        self.executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='native-parent-sizing')
        self.client=None;self.broker=None;self.store=None;self.context=None
        self.producer=None;self.futures=set();self.joined=False

    async def call(self,function,*args):
        future=asyncio.get_running_loop().run_in_executor(self.executor,function,*args)
        self.futures.add(future)
        try:return await asyncio.shield(future)
        finally:
            if future.done():self.futures.discard(future)

    def connect(self,connected):
        # The same creating thread owns native cache SQL and every acquisition.
        self.client=ChildChannel(connected,seconds=self.seconds,cancelled=self.stopped.is_set)
        from meme_machine.lanes.pump.solana_immutable_rpc import ImmutableReads
        from meme_machine.lanes.pump.solana_evidence_broker import EvidenceBroker
        from meme_machine.lanes.pump.solana_read_rpc import new_rpc
        from meme_machine.lanes.pons.immutable_rpc import EvidenceStore
        from meme_machine.lanes.pons.pons_selective_acquisition import SelectiveEvidenceContext
        sol=ChildRPCPort(self.client,'pump-discovery');pons=ChildRPCPort(self.client,'pons-discovery')
        reads=ImmutableReads(self.root/'sizing-solana-cache.sqlite',endpoint_identity=sol.source.endpoint_identity)
        self.broker=EvidenceBroker(self.root/'sizing-solana-cache.sqlite')
        self.pump=new_rpc(parent_port=sol,shared_reads=reads,evidence_broker=self.broker)
        self.store=EvidenceStore(self.root/'sizing-pons-cache.sqlite')
        profile=self.client.pons_profile(pons.source)
        self.context=SelectiveEvidenceContext(None,parent_port=pons,immutable_store=self.store,native_profile=profile)

    def produce(self,financial,state,scope,source,deadline,renew):
        require(not self.stopped.is_set() and time.monotonic()<deadline,'live_sizing_cancelled')
        # Pump's original deadline is in its RPC clock domain (wall by
        # default); Pons/IPC use monotonic. Preserve that existing translation.
        self.pump.evidence_deadline=self.pump.clock()+max(0,deadline-time.monotonic())
        self.context.deadline=deadline
        # Use the original bounded native RPC-session rotation and same shared
        # metering. Rotation creates no fresh physical allowance or USD cache.
        rpc=self.context.acquire(50,'pons_selective')
        rpc.evidence_deadline=deadline
        if self.producer is None:self.producer=ParentSizingProducer(self.pump,rpc,clock=time.time)
        else:
            self.producer.pons_rpc=rpc;self.producer._pons.rpc=rpc
        value=self.producer.produce(financial,state,scope=scope,
            source_commit=source['source_commit'],source_tree=source['source_tree'],renew_pons=renew)
        require(not self.stopped.is_set() and time.monotonic()<deadline,'live_sizing_cancelled')
        return value

    def close(self):
        errors=[]
        for close in (self.client.abort_and_join if self.client is not None else None,
                      self.broker.close if self.broker is not None else None,
                      self.store.db.close if self.store is not None else None):
            if close is not None:
                try:close()
                except BaseException as error:errors.append(error)
        if errors:raise errors[0]


class LiveNativeParent:
    """Opt-in fixed parent; the admin fence must outlive parent_owners_joined.

    Controls are existing approved objects in disposable private files. This
    constructor deliberately cannot create/reset allowance or import production
    history. The protected caller must verify remaining quotas/debt and original
    profile/pacing. No environment switch selects this class.
    """
    def __init__(self,root,*,budget,governor,admission,environ):
        from meme_machine.runtime.governor import Governor
        from meme_machine.lanes.pons.provider_admission import Admission
        require(type(budget) is Budget and type(governor) is Governor and type(admission) is Admission
            and admission.offline_profile is None,'live_parent_original_controls')
        self.root=_private_root(root)
        for path in (budget.path,governor.path,admission.path):_owned_file(self.root,path)
        usage=budget.snapshot()
        require(budget.phase=='bootstrap' and not budget.continuous and type(budget.seconds) is int
            and 0<budget.seconds<=1800 and usage.get('reason')==''
            and usage.get('new_risk_ready','false')=='false'
            and usage.get('http_reserved')==usage.get('native_reserved')=='0',
            'live_parent_bounded_funding_closed_budget')
        require(len({str(Path(row).resolve()) for row in (budget.path,governor.path,admission.path)})==3,
            'live_parent_distinct_controls')
        self.budget=budget;self.sources,self.native=_sources(environ,governor,admission)
        self.environ=dict(environ);self._owner=(os.getpid(),threading.get_ident())
        self._attempted=False;self._closed=False;self._channels=[];self._http=[];self._servers=[]
        self._sizing=None;self._stop=threading.Event();self._window_stop=asyncio.Event()
        self._child=None;self._publisher=None;self._drain_deadline=None;self._cleanup_tasks=[]

    def _owned(self):
        require(self._owner==(os.getpid(),threading.get_ident()),'live_parent_owner')

    def parent_owners_joined(self):
        self._owned()
        return self._closed and all(task.done() for task in self._servers) and (
            self._sizing is None or self._sizing.joined)

    def request_stop(self):
        self._owned();self._window_stop.set()

    async def _server(self,channel,connected):
        reader,writer=await asyncio.open_connection(sock=connected)
        task=asyncio.create_task(serve_connected(reader,writer,channel))
        self._servers.append(task)
        return task

    async def _acquire(self,financial,source,scope,previous=None):
        financial.validate();summary,state=financial.detached()
        lifetime=SIZING_SECONDS if previous is None else previous.value()['valid_until']-time.time()
        require(lifetime>0,'live_sizing_expired_before_acquisition')
        deadline=time.monotonic()+min(SIZING_SECONDS,lifetime)
        result=await self._sizing.call(self._sizing.produce,summary,state,scope,source,deadline,previous is not None)
        financial.validate()
        return result

    async def _write(self,descriptor,produced,session,financial):
        financial.validate();facts=produced.value()
        require(time.time()<facts['valid_until'],'live_sizing_expired_before_publication')
        raw=canonical(dict(schema='protected-parent-native-sizing-v1',session=session,facts=facts)).encode()+b'\n'
        require(len(raw)<=FACTS_BYTES,'live_sizing_packet_bound')
        deadline=min(time.monotonic()+2,time.monotonic()+facts['valid_until']-time.time());offset=0
        while offset<len(raw):
            require(time.monotonic()<deadline,'live_sizing_publication_timeout')
            try:offset+=os.write(descriptor,raw[offset:])
            except BlockingIOError:await asyncio.sleep(.01)
        financial.validate()

    async def _publish(self,descriptor,first,session,financial,source,scope,counters):
        current=first
        try:
            while not self._stop.is_set():
                await asyncio.sleep(.5)
                if self._stop.is_set():break
                # Give genuine native renewal the remaining original window;
                # starting only two seconds before expiry would introduce a
                # tighter acquisition bound than the native five-second fact.
                if current.value()['valid_until']-time.time()<=SIZING_SECONDS-1:
                    current=await self._acquire(financial,source,scope,current)
                    counters['genuine_renewals']+=1
                await self._write(descriptor,current,session,financial)
                counters['packets']+=1
        finally:os.close(descriptor)

    async def run(self,scope,approval,financial,*,seconds=WORK_SECONDS):
        """Real fixed launcher only; never an implicit public/provider action."""
        return await self._run(scope,approval,financial,seconds=seconds)

    async def _run(self,scope,approval,financial,*,seconds=WORK_SECONDS,
                   _prepare=_REAL_PREPARE,_launch=_REAL_LAUNCH,_opener=None,_factories=None):
        self._owned()
        require(not self._attempted and type(approval) is NativeImageApproval and type(scope) is LiveNativeScope
            and type(financial) is ProtectedFinancialInput and type(seconds) in (int,float)
            and 0<seconds<=WORK_SECONDS,'live_parent_single_attempt')
        self._attempted=True;source=approval.value();stage='financial_capture'
        result=dict(schema='isolated-native-live-processing-v1',status='BLOCKED',financial_authority=False,
            production_state_writes=0,authoritative_historical_recovery=False,normal_readiness=False,
            full_market_speed_proven=False,operational_acceptance_demonstrated=False,kernel_applied=False,
            source_commit=source['source_commit'],source_tree=source['source_tree'])
        transport=None;facts_read=None;facts_write=None;local_socket=None;primary=None;origin=None
        sizing_counts=dict(packets=0,genuine_renewals=0)
        try:
            started=time.monotonic();scope.require_launch(approval);scope.check()
            require(scope.path in self.root.parents,'live_parent_controls_outside_admitted_scope')
            scope.register_parent_owner(self)
            summary,state=financial.capture()
            result['financial_before']={k:summary[k] for k in ('epoch_id','combined_sequence',
                'journal_hash','projection_hash','cash_usd','initial_capital_usd','obligations')}
            stage='image_prepare';prepared=_prepare(scope.path,approval,scope_capability=scope);financial.validate()
            require(time.monotonic()-started<STARTUP_SECONDS,'live_parent_startup_deadline')
            stage='configured_parent'
            for workers in (4,1):
                http=ParentHTTP(self.budget,self.sources,workers=workers,opener=_opener);self._http.append(http)
                profiles=ParentPonsProfiles.configured(http,environ=self.environ)
                factories=(NativeFactoryMap(http,self.native,_factories)
                    if workers==4 and _factories is not None else None)
                channel=ParentChannel(http,native_sources=self.native if workers==4 else (),
                    native_factories=factories,pons_profiles=profiles,seconds=seconds+STARTUP_SECONDS+DRAIN_SECONDS,
                    workers=workers)
                self._channels.append(channel)
            channel,sizing_channel=self._channels
            parent_socket,transport=socket.socketpair();await self._server(channel,parent_socket)
            parent_socket,local_socket=socket.socketpair();await self._server(sizing_channel,parent_socket)
            self._sizing=_SizingOwner(self.root,self._stop,seconds+STARTUP_SECONDS+DRAIN_SECONDS)
            stage='sizing_connect';await self._sizing.call(self._sizing.connect,local_socket);local_socket=None
            stage='initial_genuine_sizing';scope_id='isolated-live-'+secrets.token_urlsafe(24)
            produced=await self._acquire(financial,source,scope_id)
            result['sizing_provenance']=produced.proof()
            facts_read,facts_write=os.pipe2(os.O_CLOEXEC|os.O_NONBLOCK)
            await self._write(facts_write,produced,channel.session,financial);sizing_counts['packets']=1
            require(time.monotonic()-started<STARTUP_SECONDS,'live_parent_startup_deadline')
            stage='kernel_launch';self._child=_launch(scope.path,approval,transport,facts_read,prepared=prepared)
            transport.close();transport=None;os.close(facts_read);facts_read=None
            self._publisher=asyncio.create_task(self._publish(facts_write,produced,channel.session,
                financial,source,scope_id,sizing_counts));facts_write=None
            stage='live_window';deadline=time.monotonic()+seconds;natural_drain=False
            next_storage=0;next_ownership=0
            while time.monotonic()<deadline and not self._window_stop.is_set():
                if time.monotonic()>=next_ownership:
                    financial.validate();next_ownership=time.monotonic()+1
                if time.monotonic()>=next_storage:scope.check();next_storage=time.monotonic()+.25
                if self._publisher.done():self._publisher.result();raise LiveParentRefused('live_sizing_owner_ended')
                if any(task.done() for task in self._servers):
                    for task in self._servers:
                        if task.done():task.result()
                    natural_drain=True
                    break
                if os.waitid(os.P_PID,self._child.child.pid,os.WEXITED|os.WNOHANG|os.WNOWAIT) is not None:
                    natural_drain=True;break
                await asyncio.sleep(.1)
            stage='native_drain'
            self._drain_deadline=time.monotonic()+DRAIN_SECONDS
            # A peer that has already closed its IPC may be completing normal
            # interpreter teardown. Do not introduce TERM after its accepted
            # work ended: Python finalization can already have restored DFL.
            # Both paths retain the same single original drain bound and the
            # launcher's owned-group kill-before-reap containment.
            result['child']=(await asyncio.to_thread(self._child.wait,seconds=DRAIN_SECONDS)
                if natural_drain else await asyncio.to_thread(self._child.stop))
            result['owned_process_reaped']=self._child._reaped
            policy=native_policy_record(bytes(self._child.output['stderr']))
            result['kernel_applied']=_prepare is _REAL_PREPARE and _launch is _REAL_LAUNCH and policy is not None
            if policy is not None:result['landlock_abi']=policy['landlock_abi']
            financial.validate()
        except BaseException as error:
            origin=error
            if isinstance(error,(KeyboardInterrupt,SystemExit)):primary=error
            elif isinstance(error,asyncio.CancelledError):primary=error
            result['failure']=_failure(stage,error)
        finally:
            cleanup=asyncio.create_task(self._cleanup(transport,facts_read,facts_write,local_socket,result,origin))
            while not cleanup.done():
                try:await asyncio.shield(cleanup)
                except asyncio.CancelledError:
                    if primary is None:primary=asyncio.CancelledError()
            cleanup.result()
        result['sizing']=sizing_counts;result['parent_owners_joined']=self.parent_owners_joined()
        # Joining and a genuine sizing basis are separate from economic work,
        # market coverage, throughput, kernel proof and production readiness.
        if ('failure' not in result and result.get('owned_process_reaped') is True
                and result['parent_owners_joined'] is True
                and result.get('child',{}).get('status')=='COMPLETED'):
            result['status']='CONTAINED_NATIVE_PROCESSING_STOPPED_REVIEW_REQUIRED'
        if primary is not None:raise primary
        return result

    async def _cleanup(self,transport,facts_read,facts_write,local_socket,result,origin=None):
        # One original shared drain bound, never a fresh grace per owner.
        deadline=self._drain_deadline if self._drain_deadline is not None else time.monotonic()+DRAIN_SECONDS
        self._drain_deadline=deadline
        errors=[];pending=[]
        def closed(operation,label):
            try:operation()
            except BaseException as error:errors.append((label,error))
        async def joined(awaitable,label,*,fatal=True):
            task=asyncio.ensure_future(awaitable)
            self._cleanup_tasks.append(task)
            done,_=await asyncio.wait((task,),timeout=max(0,deadline-time.monotonic()))
            if not done:
                pending.append(task);return False,None
            try:return True,task.result()
            except BaseException as error:
                if fatal:errors.append((label,error))
                return False,error
        if self._child is not None and not self._child._reaped:
            complete,child=await joined(asyncio.to_thread(self._child.stop),'child')
            if complete:result['child']=child
            result['owned_process_reaped']=self._child._reaped
        publisher_was_done=self._publisher is not None and self._publisher.done()
        self._stop.set()
        if self._publisher is not None:
            complete,error=await joined(self._publisher,'publisher',fatal=False)
            if not complete and isinstance(error,BaseException):
                if publisher_was_done or not isinstance(error,(BrokenPipeError,ConnectionError)):
                    result.setdefault('failure',dict(stage='sizing_publication',error_class=type(error).__name__))
        if self._sizing is not None and self._sizing.client is not None:closed(self._sizing.client.abort,'sizing_abort')
        for item in (transport,local_socket):
            if item is not None:closed(item.close,'private_socket')
        for descriptor in (facts_read,facts_write):
            if descriptor is not None:closed(lambda:os.close(descriptor),'private_pipe')
        # Both channels have separate physical worker lanes but the same
        # original Budget/Governor/Admission. EOF on one cannot close the other.
        for channel in self._channels:await joined(channel.aclose(),'channel')
        for task in self._servers:await joined(task,'server')
        for http in self._http:await joined(http.aclose(),'http')
        if self._sizing is not None:
            futures=tuple(self._sizing.futures)
            if futures:await joined(asyncio.gather(*futures,return_exceptions=True),'sizing_acquisition')
            if all(future.done() for future in futures):
                await joined(self._sizing.call(self._sizing.close),'sizing_close')
                if all(future.done() for future in self._sizing.futures):
                    try:self._sizing.executor.shutdown(wait=True,cancel_futures=True);self._sizing.joined=True
                    except BaseException as error:errors.append(('sizing_thread',error))
        if errors or pending:
            result['cleanup']=dict(joined=False,failed_operations=len(errors),pending_operations=len(pending))
            failure=NativeOwnerDrainFailure(dict(status='BLOCKED',failure_code='live_parent_drain_incomplete',
                financial_authority=False,normal_readiness=False,all_workers_joined=False,
                original_failure=result.get('failure'),cleanup=result['cleanup']))
            failure.retain(self,*self._cleanup_tasks,*(error for _,error in errors))
            raise failure from (origin if origin is not None else errors[0][1] if errors else None)
        self._closed=True
        try:
            usage=self.budget.snapshot()
            result['budget_counters']={key:int(usage[key]) for key in ('http_attempts','rpc_elements',
                'http_bytes','http_reserved','http_uncertain_bytes','native_bytes','native_reserved',
                'native_uncertain_bytes','native_opens')}
        except Exception as error:
            result['budget_counters_state']='UNAVAILABLE'
            result.setdefault('failure',_failure('budget_receipt',error))
