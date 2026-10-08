"""Physical-boundary limits for the existing capability.compare, never a scan.

The caller supplies one existing canonical PacedRpc. Only its urllib boundary
is replaced; native pacing, shared admission, authority and witnesses still run.
The transport has no redirects or retries. A terminal stop cannot be recovered.
"""
from collections import Counter
from contextlib import contextmanager
import io
import hashlib
import json
from pathlib import Path
import signal
import time
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, build_opener
from unittest.mock import patch

from meme_machine.lanes.pons import provider as transport_module
from meme_machine.lanes.pons.pons_historical import Preparation
from meme_machine.runtime.robinhood import provider_authority as authority

FIRST, LAST = 56882701, 56882740
REFERENCE_TX = '0x1d49a28a0e27ecdd952094c4aaa9de2105253a2d62924ec36e761c13e43493c9'
STORAGE = 128 * 1024 * 1024
RESPONSE = 2_000_000
METHODS = frozenset(('eth_chainId', 'eth_getBlockByNumber', 'eth_getBlockByHash',
                     'eth_getCode', 'eth_getLogs', 'eth_getTransactionReceipt'))


class Stop(BaseException):
    # Native provider exception sanitizers/retry loops must not swallow a stop.
    def __init__(self, classification, reason):
        self.classification, self.reason = classification, reason


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise Stop('BLOCKED', 'unauthorized_http_redirect')


@contextmanager
def wall_guard(deadline, *, clock=time.monotonic):
    """Independent real-time alarm, including blocked I/O and admission waits."""
    if signal.getitimer(signal.ITIMER_REAL)[0]:
        raise Stop('BLOCKED', 'existing_wall_alarm')
    previous = signal.getsignal(signal.SIGALRM)
    def expired(*_):
        raise Stop('BUDGET_STOP', 'wall_deadline')
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, max(.000001, deadline-clock()))
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


class Execution:
    def __init__(self, rpc, root, deadline, *, clock=time.monotonic, opener=None):
        self.rpc, self.root, self.deadline, self.clock = rpc, Path(root), deadline, clock
        self.endpoint = rpc._endpoint
        self.fingerprint = authority.fingerprint(self.endpoint)
        self.opener = opener or build_opener(NoRedirect()).open
        self.logical = self.physical = self.wire_elements = 0
        self.request_bytes = self.response_bytes = self.peak_storage = 0
        self.methods, self.wire_methods = Counter(), Counter()
        self.attempts, self.hashes, self.transactions = [], set(), set()
        self.log_spans = Counter()
        self.stopped = None
        self.native_started = transport_module.http_started

    def stop(self, classification, reason):
        self.stopped = self.stopped or (classification, reason)
        raise Stop(*self.stopped)

    def storage(self):
        size = sum(p.stat().st_size for p in self.root.rglob('*') if p.is_file())
        self.peak_storage = max(self.peak_storage, size)
        return size

    def check(self):
        if self.stopped:
            raise Stop(*self.stopped)
        if self.clock() >= self.deadline:
            self.stop('BUDGET_STOP', 'wall_deadline')
        if self.storage() >= STORAGE:
            self.stop('BUDGET_STOP', 'temporary_storage_ceiling')

    def save(self, name, raw):
        # Includes the old file and new atomic replacement at peak occupancy.
        if len(raw) > 2_000_000 or self.storage()+len(raw) > STORAGE:
            self.stop('BUDGET_STOP', 'temporary_storage_reservation')
        target = self.root / name
        temp = target.with_suffix(target.suffix+'.tmp')
        with temp.open('wb') as stream:
            stream.write(raw)
            stream.flush()
            import os
            os.fsync(stream.fileno())
        temp.replace(target)
        self.storage()

    def persist(self):
        self.save('usage.json', json.dumps(self.usage(), sort_keys=True).encode())

    def usage(self):
        return dict(logical_rpc_elements=self.logical, physical_http_attempts=self.physical,
            dispatched_logical_elements=self.wire_elements, estimated_cu=100*self.wire_elements,
            methods=dict(self.methods), dispatched_methods=dict(self.wire_methods),
            request_bytes=self.request_bytes, response_bytes=self.response_bytes,
            peak_temporary_bytes=self.peak_storage, attempts=self.attempts,
            application_retries=0, transport_retries=0,
            actual_billed_cu=None, actual_dollars=None,
            byte_basis='attempted JSON request payload and response payload actually read; excludes HTTP headers/TLS',
            provider_fingerprint=self.fingerprint)

    def validate(self, calls, *, wire=False):
        query = Preparation.population_filter()
        for method, params in calls:
            if method not in METHODS:
                self.stop('BLOCKED', 'unauthorized_rpc_method')
            valid = False
            if method == 'eth_chainId':
                valid = params == []
            elif method == 'eth_getBlockByNumber':
                try:
                    b = int(params[0],16)
                    valid = params == [hex(b),False] and (b == 0 or FIRST-1 <= b <= LAST)
                except (TypeError, ValueError, IndexError):
                    pass
            elif method == 'eth_getBlockByHash':
                valid = len(params)==2 and params[0] in self.hashes and params[1] is False
            elif method == 'eth_getTransactionReceipt':
                valid = len(params)==1 and params[0] in self.transactions
            elif method == 'eth_getCode':
                valid = params == [query['address'], hex(FIRST)]
            elif method == 'eth_getLogs':
                allowed = {(b,b+9) for b in range(FIRST,LAST+1,10)} | {(FIRST,LAST)}
                if len(params)==1 and isinstance(params[0],dict):
                    q=params[0]
                    for a,b in allowed:
                        if q==dict(query,fromBlock=hex(a),toBlock=hex(b)):
                            valid=True
                            if wire:
                                if self.log_spans[(a,b)]:
                                    self.stop('BLOCKED', 'repeated_log_query')
                                self.log_spans[(a,b)]+=1
                            break
            if not valid:
                self.stop('BLOCKED', 'unauthorized_rpc_parameters')

    def demand(self, calls):
        self.check()
        self.validate(calls)
        if self.logical+len(calls)>64:
            self.stop('BUDGET_STOP', 'logical_element_ceiling')
        self.logical+=len(calls)
        self.methods.update(m for m,_ in calls)
        self.persist()

    def read(self, response, attempt):
        raw=bytearray()
        length=response.headers.get('Content-Length') if response.headers else None
        if length is not None:
            try:
                length=int(length)
                if length<0:raise ValueError()
            except ValueError:
                self.stop('CANONICAL_COMPARISON_FAILED', 'invalid_content_length')
            if length>RESPONSE:
                self.stop('BUDGET_STOP', 'response_size_ceiling')
        while True:
            self.check()
            remaining=RESPONSE-len(raw)
            if not remaining:
                # Never read a byte beyond the owner's ceiling, even chunked.
                if length==RESPONSE:break
                self.stop('BUDGET_STOP', 'response_size_ceiling')
            reader=getattr(response,'read1',response.read)
            chunk=reader(min(65536,remaining))
            if not chunk:break
            if len(chunk)>remaining:
                self.stop('BLOCKED', 'transport_read_bound_not_respected')
            raw.extend(chunk)
            self.response_bytes+=len(chunk)
            attempt['response_bytes']=len(raw)
            self.persist()
        if length is not None and length!=len(raw):
            self.stop('CANONICAL_COMPARISON_FAILED', 'incomplete_http_payload')
        return bytes(raw)

    def http(self, request, *, timeout):
        self.check()
        if request.full_url!=self.endpoint or request.get_method()!='POST':
            self.stop('BLOCKED', 'unauthorized_http_endpoint')
        from meme_machine.runtime.robinhood.provider_usage import _active
        active=_active.get()
        if (active is None or active['endpoint_fingerprint']!=self.fingerprint
                or str(active['path'])!=str(self.rpc.shared_admission.path)
                or active['retry_attempt']!=0):
            self.stop('BLOCKED', 'shared_admission_not_verified')
        body=request.data
        decoded=json.loads(body)
        batch=decoded if isinstance(decoded,list) else [decoded]
        calls=[(r['method'],r['params']) for r in batch]
        self.validate(calls,wire=True)
        if self.physical>=32:
            self.stop('BUDGET_STOP', 'physical_attempt_ceiling')
        if self.wire_elements+len(calls)>64 or 100*(self.wire_elements+len(calls))>6400:
            self.stop('BUDGET_STOP', 'diagnostic_cu_or_wire_element_ceiling')
        # 2 MB raw, bounded cache/SQLite writes, and metadata have reserved stock.
        if self.storage()+16*1024*1024>STORAGE:
            self.stop('BUDGET_STOP', 'temporary_storage_dispatch_reservation')
        self.physical+=1
        self.wire_elements+=len(calls)
        self.wire_methods.update(m for m,_ in calls)
        self.request_bytes+=len(body)
        attempt=dict(index=self.physical,calls=batch,started=self.clock(),
            request_bytes=len(body),request_sha256=hashlib.sha256(body).hexdigest(),
            response_bytes=0,status='dispatched')
        self.attempts.append(attempt)
        self.persist()  # durable reservation before external dispatch, including failures
        error=None
        try:
            try:
                response=self.opener(request, timeout=min(timeout,self.deadline-self.clock()))
            except HTTPError as exc:
                response,error=exc,exc.code
            with response:
                raw=self.read(response,attempt)
            attempt['response_sha256']=hashlib.sha256(raw).hexdigest()
            payload=json.loads(raw)
            authority.protect_response(payload,self.endpoint)
            self.save(f'response-{self.physical:02d}.json',raw)
            rows=payload if isinstance(payload,list) else [payload]
            candidate=any(m=='eth_getLogs' and p[0]['fromBlock']==hex(FIRST)
                and p[0]['toBlock']==hex(LAST) for m,p in calls)
            for row in rows:
                message=str((row.get('error') or {}).get('message','')).lower() if isinstance(row,dict) else ''
                if candidate and 'block' in message and any(word in message for word in
                        ('limit','maximum','exceed','up to','more than')):
                    self.stop('UNSUPPORTED_40_BLOCK_RANGE','explicit_40_block_range_rejection')
            if error:
                from meme_machine.lanes.pons import BoundaryError
                raise BoundaryError(f'provider_http_{error}')
            ids={r['id'] for r in batch}
            if (isinstance(decoded,list)!=isinstance(payload,list) or len(rows)!=len(batch)
                    or any(not isinstance(r,dict) or r.get('jsonrpc')!='2.0'
                        or type(r.get('id')) is not int or (('result' in r)==('error' in r)) for r in rows)
                    or {r['id'] for r in rows}!=ids):
                self.stop('CANONICAL_COMPARISON_FAILED','invalid_complete_rpc_envelope')
            by_id={r['id']:r for r in rows}
            for req in batch:
                value=by_id[req['id']].get('result')
                if req['method'] in ('eth_getBlockByNumber','eth_getBlockByHash') and isinstance(value,dict):
                    self.hashes.add(value.get('hash'))
                if req['method']=='eth_getLogs' and isinstance(value,list):
                    self.transactions.update(e.get('transactionHash') for e in value if isinstance(e,dict))
            attempt.update(status='response',http_status=200)
            return io.BytesIO(raw)
        except Stop as exc:
            self.stopped=(exc.classification,exc.reason)
            attempt.update(status='stopped',reason=exc.reason,http_status=error)
            raise
        except BaseException:
            attempt.update(status='failed',http_status=error)
            raise
        finally:
            attempt['ended']=self.clock()
            self.persist()

    def before_http(self):
        # Reject exhausted work before native http_started also records a start.
        # The URL boundary below additionally validates the full actual payload.
        self.check()
        from meme_machine.runtime.robinhood.provider_usage import _active
        active=_active.get()
        if active is None or active['retry_attempt']!=0:
            self.stop('BLOCKED','shared_admission_not_verified')
        if self.physical>=32:self.stop('BUDGET_STOP','physical_attempt_ceiling')
        if self.wire_elements+len(active['methods'])>64:
            self.stop('BUDGET_STOP','diagnostic_cu_or_wire_element_ceiling')
        if self.storage()+16*1024*1024>STORAGE:
            self.stop('BUDGET_STOP','temporary_storage_dispatch_reservation')
        self.native_started()

    @contextmanager
    def install(self):
        if (self.rpc.retries!=0 or self.rpc.max_response!=RESPONSE
                or not self.rpc.canonical_authority or self.rpc.provider_fingerprint!=self.fingerprint
                or self.rpc._injected_transport is not None or self.rpc.shared_admission is None):
            self.stop('BLOCKED','canonical_executor_preflight')
        original_call,original_batch=self.rpc.call,self.rpc.batch
        def invoke(function,*args,**kwargs):
            try:return function(*args,**kwargs)
            except Stop as exc:
                self.stopped=(exc.classification,exc.reason)
                raise
            except Exception as exc:
                self.stopped=('BLOCKED',authority.failure_class(exc))
                raise
        def call(method,params,**kwargs):
            self.demand([(method,params)])
            return invoke(original_call,method,params,**kwargs)
        def batch(calls,**kwargs):
            self.demand(calls)
            return invoke(original_batch,calls,**kwargs)
        self.rpc.evidence_deadline=self.deadline
        self.rpc.evidence_timing={}
        with patch.object(self.rpc,'call',call),patch.object(self.rpc,'batch',batch), \
                patch.object(transport_module,'urlopen',self.http), \
                patch.object(transport_module,'http_started',self.before_http):
            yield self
