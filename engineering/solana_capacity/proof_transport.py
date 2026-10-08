"""One physical HTTP/native boundary for pump_pons_proof, installed explicitly.

Alternative Python clients have no socket dispatch context. gRPC's C transport
is endpoint-restricted by the independent kernel supervisor and byte-metered by
its deserializer, before routing/dedup. No provider endpoint is opened on import.
"""
import asyncio
from contextvars import ContextVar
import json
import os
import socket
import sys
import threading
import time
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener
from urllib.parse import urlsplit
from .proof_limits import CeilingReached, MAX_FRAME, STREAM_HOST, endpoint_family

_NETWORK = ContextVar('finite_proof_transport',default=None)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*a,**kw):raise CeilingReached('http_redirect_forbidden')


class Response:
    def __init__(self,raw,receipt,deadline):self.raw=raw;self.receipt=receipt;self.deadline=deadline
    @property
    def headers(self):return self.raw.headers
    @property
    def status(self):return getattr(self.raw,'status',200)
    def getcode(self):return self.status
    def read(self,n=-1):
        def acquire(size):
            if self.receipt.budget.clock()>=self.deadline:self.receipt.budget.fail('http_deadline')
            reader=getattr(self.raw,'read1',self.raw.read)
            try:return reader(size)
            except Exception:self.receipt.budget.fail('http_acquisition_failure')
        raw=self.receipt.acquire(acquire,n)
        if n<0 or len(raw)<n:
            try:
                value=json.loads(raw)
                if any(isinstance(row,dict) and row.get('error') is not None for row in (value if isinstance(value,list) else [value])):
                    self.receipt.budget.fail('rpc_error_no_retry')
            except (ValueError,TypeError):self.receipt.budget.fail('rpc_response_shape')
        return raw
    def read1(self,n=-1):return self.read(n)
    def readinto(self,buffer):
        raw=self.read(len(buffer));buffer[:len(raw)]=raw;return len(raw)
    def close(self):
        try:self.raw.close()
        finally:self.receipt.close()
    def __enter__(self):return self
    def __exit__(self,*a):self.close()


class Transports:
    def __init__(self,budget,queues,*,opener=None,offline=True):
        self.budget=budget;self.queues=queues;self.offline=offline;self.opener=opener;self.originals=[]
        self.pid=os.getpid();self.owner_count=0;self.owner_lock=threading.Lock();self.owners=[];self.disconnect=False;self.disconnect_receipt=None
        self.recovery_probe=None
        self.ws_opening=0
        self.admission_sequence=0
    def replace(self,obj,name,value):
        self.originals.append((obj,name,getattr(obj,name)));setattr(obj,name,value)
    def open(self,request,*a,**kw):
        b=self.budget
        if os.getpid()!=self.pid:b.fail('provider_dispatch_in_descendant')
        try:
            payload=json.loads(request.data);calls=payload if isinstance(payload,list) else [payload]
        except (AttributeError,ValueError,TypeError):b.fail('non_rpc_http_dispatch')
        receipt=b.reserve_http(request.full_url,calls)
        remaining=b.started+b.time['total_wall_seconds']-b.clock()
        timeout=min(8.0,remaining,float(kw.get('timeout',8)))
        if timeout<=0:receipt.close();b.fail('wall_time_ceiling')
        token=_NETWORK.set(('http',urlsplit(request.full_url).hostname))
        try:
            with b.lock:
                if b.reason:raise CeilingReached(b.reason)
                if b.clock()-b.started>=b.time['stop_new_work_at_seconds'] or (b.admissions_stopped.is_set() and not receipt.exhausted):
                    raise CeilingReached('admission_closed')
                if self.offline:b.fake_dispatches+=1
                else:b.dispatched+=1
            raw=self.opener(request,timeout=timeout)
            return Response(raw,receipt,b.clock()+timeout)
        except HTTPError as exc:
            try:
                with Response(exc,receipt,b.clock()+timeout) as response:response.read()
            finally:b.fail('provider_http_'+str(exc.code))
        except CeilingReached as exc:
            receipt.close()
            if exc.reason=='admission_closed':raise
            b.fail(exc.reason)
        except Exception:receipt.close();b.fail('http_transport_failure')
        finally:_NETWORK.reset(token)
    def install(self):
        import urllib.request
        from meme_machine.lanes.pons import provider
        from meme_machine.solana_evidence_control import PriorityOwner
        import grpc
        from meme_machine import solana_selective_source as source
        if self.opener is None:
            if self.offline:raise ValueError('offline_transport_required')
            # No proxy/redirect can add unmetered physical HTTP attempts. This
            # host must provide direct TLS to the explicitly approved endpoints.
            self.opener=build_opener(ProxyHandler({}),NoRedirect()).open
        self.replace(urllib.request,'urlopen',self.open);self.replace(provider,'urlopen',self.open)
        # Imports with urlopen aliases are covered by a process-wide audit hook;
        # they cannot use a different client or SDK's Python sockets.
        def audit(event,args):
            # asyncio performs WS DNS in an executor without ContextVar
            # propagation. Its sole approved hostname may resolve only while
            # a metered handshake is actually being established.
            ws_dns=event=='socket.getaddrinfo' and args[0]==STREAM_HOST.split(':')[0] and self.ws_opening>0
            if event=='socket.getaddrinfo' and (self.offline or _NETWORK.get() is None and not ws_dns):
                self.budget.fail('unmetered_dns_dispatch')
            if event in ('socket.connect','socket.sendto'):
                sock=args[0]
                if sock.family!=socket.AF_UNIX and (self.offline or _NETWORK.get() is None):
                    self.budget.fail('unmetered_socket_dispatch')
        sys.addaudithook(audit)
        original_rpc=provider.Rpc.__init__
        def rpc_init(rpc,*a,**kw):
            # Defaults in older wrappers must not accidentally retry. Explicit
            # incompatible retry requests are refused before constructing them.
            if kw.get('retries',0)!=0:self.budget.fail('rpc_retries')
            kw['retries']=0;return original_rpc(rpc,*a,**kw)
        self.replace(provider.Rpc,'__init__',rpc_init)
        # Solana native read RPCs may otherwise retry result/RPC errors inside
        # their base class. The first physical error is terminal, so none of
        # those loops can make a second HTTP attempt.
        from meme_machine.runtime import evidence_worker
        delivered=evidence_worker.RepairRPC.call_delivered
        def delivered_once(rpc,*a,**kw):
            try:return delivered(rpc,*a,**kw)
            except Exception:self.budget.fail('rpc_failure_no_retry')
        self.replace(evidence_worker.RepairRPC,'call_delivered',delivered_once)
        original_submit=PriorityOwner.submit;original_init=PriorityOwner.__init__
        def init(owner,*a,**kw):
            if kw.get('capacity',64)>self.budget.limits['queue_capacity']:self.budget.fail('queue_capacity')
            original_init(owner,*a,**kw);self.owners.append(owner)
        def submit(owner,fn,**kw):
            with owner.cv:
                with self.owner_lock:self.owner_count+=1;identity='owner:'+str(self.owner_count)
                expires=kw.get('expires')
                deadline=None if expires is None else self.budget.clock()+expires-time.time()
                self.queues.enqueue(identity,deadline=deadline,queue='owner',control=True)
                def observed(state):
                    self.queues.dispatch(identity);error=None
                    try:return fn(state)
                    except BaseException as exc:error=type(exc).__name__;raise
                    finally:self.queues.finish(identity,error=error)
                try:
                    future=original_submit(owner,observed,**kw)
                    def disposed(f):
                        # Owner expiry/rejection can occur before observed()
                        # runs. Capture the native disposal and original expiry.
                        with self.queues.lock:
                            if identity in self.queues.pending or identity in self.queues.running:
                                error='cancelled' if f.cancelled() else type(f.exception()).__name__ if f.exception() is not None else None
                                self.queues.finish(identity,cancelled=f.cancelled(),error=error)
                    future.add_done_callback(disposed);return future
                except BaseException as exc:
                    with self.queues.lock:
                        if identity in self.queues.pending or identity in self.queues.running:
                            self.queues.finish(identity,cancelled=True,error=type(exc).__name__)
                    raise
        self.replace(PriorityOwner,'__init__',init);self.replace(PriorityOwner,'submit',submit)
        # These hooks execute at native durable enqueue, plan/claim and commit,
        # rather than inferring service from a later single queue snapshot.
        from meme_machine.solana_selective_history import SelectiveHistory
        def census(h,claimed=None):
            c=h.db.execute('SELECT * FROM acquisition_jobs');keys=[d[0] for d in c.description]
            self.queues.scheduler_snapshot([dict(zip(keys,r)) for r in c],source_now=h.clock(),claimed=claimed)
        request=SelectiveHistory.request;plan=SelectiveHistory.plan;page=SelectiveHistory.commit_page
        def requested(h,*a,**kw):
            self.budget.admission();identity=request(h,*a,**kw);census(h);return identity
        def planned(h,*a,**kw):
            value=plan(h,*a,**kw);census(h,None if value is None else value[0]['id']);return value
        def committed(h,*a,**kw):
            value=page(h,*a,**kw);census(h);return value
        self.replace(SelectiveHistory,'request',requested);self.replace(SelectiveHistory,'plan',planned)
        self.replace(SelectiveHistory,'commit_page',committed)
        from meme_machine.runtime.candidate_history import CandidateHistory
        enqueue=CandidateHistory.enqueue;claim=CandidateHistory.claim;complete=CandidateHistory.complete
        def candidates(h):
            c=h.db.execute('SELECT * FROM work');keys=[d[0] for d in c.description]
            self.queues.scheduler_snapshot([dict(zip(keys,r)) for r in c],queue='candidate-work',source_now=h.clock())
        def enqueued(h,*a,**kw):
            self.budget.admission();value=enqueue(h,*a,**kw);candidates(h);return value
        def claimed(h,*a,**kw):
            try:return claim(h,*a,**kw)
            finally:candidates(h)
        def completed(h,*a,**kw):
            value=complete(h,*a,**kw);candidates(h);return value
        self.replace(CandidateHistory,'enqueue',enqueued);self.replace(CandidateHistory,'claim',claimed)
        self.replace(CandidateHistory,'complete',completed)
        decision=CandidateHistory.record_decision
        def decided(h,lane,candidate,**kw):
            original=h.candidate(lane,candidate)
            if original and original.get('decision_deadline') is not None:
                deadline=original['decision_deadline'];now=h.clock()
                identity='qualification:'+lane+':'+candidate+':'+str(kw['observed_at'])
                self.queues.enqueue(identity,kind='candidate',queue='qualification',
                    deadline=self.budget.clock()+deadline-now,original_deadline=deadline,
                    enqueued=self.budget.clock()+original['first_observed']-now,control=True)
                self.queues.dispatch(identity)
                try:return decision(h,lane,candidate,**kw)
                finally:self.queues.finish(identity)
            return decision(h,lane,candidate,**kw)
        self.replace(CandidateHistory,'record_decision',decided)

        # The production provider queues have their own admission clocks and
        # capacities. Observe their actual waits too; owner depth alone cannot
        # diagnose provider backpressure or enforce the proof's tighter 64 cap.
        from meme_machine.runtime.governor import Governor
        from meme_machine.lanes.pons.provider_admission import Admission
        from meme_machine.lanes.pons.provider_topology import ProviderPacer
        def measured_admission(original,queue):
            def admitted(instance,*a,**kw):
                with self.owner_lock:self.admission_sequence+=1;identity=queue+':'+str(self.admission_sequence)
                now=self.budget.clock()
                deadline=now+kw.get('deadline_seconds',30)
                if queue=='robinhood-provider' and len(a)>1 and a[1] is not None:deadline=min(now+30,a[1])
                row=self.queues.enqueue(identity,queue=queue,deadline=deadline)
                row['deadline_clock']='monotonic_native_admission';error=None;dispatched=False
                try:
                    result=original(instance,*a,**kw)
                    self.queues.dispatch(identity);dispatched=True;return result
                except BaseException as exc:error=type(exc).__name__;raise
                finally:self.queues.finish(identity,cancelled=not dispatched,error=error)
            return admitted
        self.replace(Governor,'acquire',measured_admission(Governor.acquire,'solana-provider'))
        self.replace(Admission,'acquire',measured_admission(Admission.acquire,'robinhood-provider'))
        self.replace(ProviderPacer,'pace',measured_admission(ProviderPacer.pace,'robinhood-pacer'))

        native_queue=asyncio.Queue;transport=self
        class ObservedQueue(native_queue):
            def __init__(self,maxsize=0):
                if maxsize>transport.budget.limits['queue_capacity']:transport.budget.fail('queue_capacity')
                super().__init__(maxsize or transport.budget.limits['queue_capacity'])
                self.proof_id='async:'+str(id(self));self.proof_sequence=0;self.proof_pending=[];self.proof_running=[]
            def put_nowait(self,value):
                super().put_nowait(value);self.proof_sequence+=1;identity=self.proof_id+':'+str(self.proof_sequence)
                transport.queues.enqueue(identity,queue=self.proof_id,control=True);self.proof_pending.append(identity)
            def get_nowait(self):
                value=super().get_nowait();identity=self.proof_pending.pop(0)
                transport.queues.dispatch(identity);self.proof_running.append(identity);return value
            def task_done(self):
                super().task_done()
                if not self.proof_running:transport.budget.fail('queue_completion_unobserved')
                transport.queues.finish(self.proof_running.pop(0))
        self.replace(asyncio,'Queue',ObservedQueue)

        native_channel=grpc.aio.secure_channel
        def channel(target,*a,**kw):
            if os.getpid()!=self.pid:self.budget.fail('provider_dispatch_in_descendant')
            if target!=STREAM_HOST or self.offline:self.budget.fail('unapproved_native_endpoint')
            options=dict(kw.get('options',()))
            if options.get('grpc.max_receive_message_length',MAX_FRAME)>MAX_FRAME:self.budget.fail('unbounded_native_receive')
            options.update({'grpc.max_receive_message_length':MAX_FRAME,'grpc.enable_retries':0,
                'grpc.http2.bdp_probe':0,'grpc.http2.initial_stream_window_size':MAX_FRAME,
                'grpc.http2.initial_connection_window_size':MAX_FRAME})
            kw['options']=tuple(options.items())
            self.budget.admission()
            return Channel(native_channel(target,*a,**kw),self)
        self.replace(grpc.aio,'secure_channel',channel)
        def unsupported_channel(*a,**kw):self.budget.fail('unmetered_native_channel')
        self.replace(grpc,'secure_channel',unsupported_channel);self.replace(grpc,'insecure_channel',unsupported_channel)
        self.replace(grpc.aio,'insecure_channel',unsupported_channel)
        original_ws=source.connect
        def connect(url,*a,**kw):
            p=urlsplit(url)
            try:
                # Model B's native WS hostname is distinct from its HTTP RPC
                # hostname. Validate the actual configured streaming endpoint,
                # keeping the RPC path/credential/port restrictions intact.
                if p.scheme!='wss' or p.hostname!=STREAM_HOST.split(':')[0]:raise ValueError()
                endpoint_family('https://solana-mainnet.g.alchemy.com'+
                    (':'+str(p.port) if p.port is not None else '')+p.path+
                    ('?'+p.query if p.query else '')+('#'+p.fragment if p.fragment else ''))
                if p.username is not None or p.password is not None:raise ValueError()
            except ValueError:self.budget.fail('unapproved_websocket_endpoint')
            if self.offline:self.budget.fail('offline_native_transport_required')
            kw.update(max_size=MAX_FRAME,max_queue=2,compression=None,open_timeout=8,close_timeout=1)
            return WebSocketContext(original_ws(url,*a,**kw),self)
        self.replace(source,'connect',connect)
    def close(self):
        for obj,name,value in reversed(self.originals):setattr(obj,name,value)
        self.originals.clear()


class Channel:
    def __init__(self,raw,transports):self.raw=raw;self.t=transports
    async def __aenter__(self):await self.raw.__aenter__();return self
    async def __aexit__(self,*a):return await self.raw.__aexit__(*a)
    def stream_stream(self,path,**kw):
        if path!='/geyser.Geyser/Subscribe':self.t.budget.fail('unapproved_native_method')
        original=kw.get('response_deserializer',lambda x:x)
        def decoded(raw):self.t.budget.native('yellowstone',len(raw));return original(raw)
        kw['response_deserializer']=decoded;factory=self.raw.stream_stream(path,**kw)
        def call(*a,**kw):
            reserve=self.t.budget.stream_open('yellowstone')
            try:return Stream(factory(*a,**kw),self.t,reserve)
            except BaseException:self.t.budget.stream_close(reserve);raise
        return call


class Stream:
    def __init__(self,raw,transports,reserve):self.raw=raw;self.t=transports;self.reserve=reserve;self.control=False
    async def write(self,request):
        self.t.budget.admission()
        from meme_machine.solana_selective_history import PROGRAMS
        # No EVM subscription and no Meteora native producer can enter here.
        if any(PROGRAMS['meteora'] in list(f.owner) for f in request.accounts.values()) or any(
            PROGRAMS['meteora'] in list(f.account_include)+list(f.account_required)
            for f in list(request.transactions.values())+list(request.transactions_status.values())):
            self.t.budget.fail('paused_meteora_workload')
        # Ping writes must not erase the identity of the control subscription.
        if request.blocks_meta or request.accounts or request.transactions_status or request.transactions:
            self.control=bool(request.blocks_meta) and not request.transactions_status and not request.accounts and not request.transactions
        if request.blocks_meta and self.control and self.t.disconnect_receipt and not self.t.disconnect_receipt.get('resubscribed'):
            receipt=self.t.disconnect_receipt
            before=receipt['checkpoint_before'];checkpoint=before['control_checkpoint']
            current=await self.t.recovery_probe()
            upper=current['control_checkpoint']
            if checkpoint is None or upper is None or not max(1,checkpoint-256)<=request.from_slot<=max(1,upper-256):
                self.t.budget.fail('checkpoint_resume_floor_changed')
            receipt.update(resubscribed=True,resume_from_slot=request.from_slot,
                checkpoint_at_resume=current,
                resume_at=self.t.budget.clock()-self.t.budget.started)
        return await self.raw.write(request)
    async def read(self):
        b=self.t.budget
        if self.control and b.ready_at is not None and b.clock()-b.ready_at>=60 and not self.t.disconnect:
            import grpc
            if self.t.recovery_probe is None:b.fail('checkpoint_measurement_unavailable')
            before=await self.t.recovery_probe()
            self.t.disconnect=True;self.t.disconnect_receipt=dict(at=b.clock()-b.started,transport='yellowstone_control',
                checkpoint_before=before,resubscribed=False,resumed=False,
                checkpoint_source='native durable coverage and candidate checkpoint identities; unchanged source clocks')
            self.raw.cancel();return grpc.aio.EOF
        return await self.raw.read()
    def cancel(self):
        try:return self.raw.cancel()
        finally:
            if self.reserve:
                reserve=self.reserve;self.reserve=0
                self.t.budget.stream_close(reserve,transport='yellowstone',unread_possible=True)


class WebSocketContext:
    def __init__(self,raw,transports):self.raw=raw;self.t=transports;self.reserve=0;self.token=None
    async def __aenter__(self):
        self.reserve=self.t.budget.stream_open('solana_websocket');self.token=_NETWORK.set(('websocket',STREAM_HOST.split(':')[0]))
        self.t.ws_opening+=1
        try:self.ws=await self.raw.__aenter__();return self
        except BaseException:
            self.t.budget.stream_close(self.reserve,transport='solana_websocket',unread_possible=True)
            raise
        finally:
            self.t.ws_opening-=1;_NETWORK.reset(self.token);self.token=None
    async def __aexit__(self,*a):
        try:return await self.raw.__aexit__(*a)
        finally:
            self.t.budget.stream_close(self.reserve,transport='solana_websocket',unread_possible=True)
    async def send(self,value):
        self.t.budget.admission()
        try:method=json.loads(value)['method']
        except (ValueError,KeyError,TypeError):self.t.budget.fail('websocket_request_shape')
        if method not in ('logsSubscribe','logsUnsubscribe'):self.t.budget.fail('unapproved_websocket_method')
        return await self.ws.send(value)
    async def recv(self,*a,**kw):
        raw=await self.ws.recv(*a,**kw)
        self.t.budget.native('solana_websocket',len(raw.encode() if isinstance(raw,str) else raw));return raw
