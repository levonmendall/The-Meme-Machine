"""Bounded, allowlisted read transport. Errors never contain endpoint secrets."""
from collections import Counter, OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import timezone
from email.utils import parsedate_to_datetime
import hashlib
import io
import json
import math
import re
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from . import BoundaryError, CHAIN_ID
from meme_machine.runtime.robinhood.provider_usage import http_started, http_received
from meme_machine.runtime.robinhood.provider_authority import failure_class, protect_response
from meme_machine.runtime.provider_purchases import account_transport,ledger

RPC_HTTP_HEADERS = {
    'Content-Type': 'application/json',
    'Accept': 'application/json',
    'User-Agent': 'Meme-Machine/1.0 (+https://github.com/levonmendall/The-Meme-Machine)',
}

READ_METHODS = frozenset({
    'eth_chainId', 'eth_blockNumber', 'eth_getBlockByNumber',
    'eth_getBlockByHash', 'eth_getLogs', 'eth_getTransactionReceipt',
    'eth_getCode', 'eth_call', 'eth_gasPrice', 'eth_getBalance',
    'eth_getStorageAt', 'eth_getTransactionByHash',
    'alchemy_getAssetTransfers', 'eth_getBlockReceipts', 'eth_callMany',
})


def rpc_boundary(method, error):
    """Classify log range rejection without persisting provider error text."""
    code=error.get('code')
    message=str(error.get('message','')).lower()
    if method=='eth_getLogs' and 'block' in message and ('range' in message or 'limit' in message):
        return 'provider_log_block_range_limit'
    return f'provider_rpc_{code if isinstance(code,int) else "unknown"}'


NO_RETRY = frozenset({'provider_log_block_range_limit','provider_response_capacity',
    'provider_http_400','provider_http_401','provider_http_403','provider_http_429',
    'provider_rpc_429','provider_rpc_-32005','provider_invalid_envelope',
    'provider_invalid_json','provider_response_contains_credential',
    'evidence_deadline_before_transport','evidence_deadline_during_transport'})

HTTP_ERROR_BYTES = 8192
_http_inflight = Counter()
_http_inflight_lock = threading.Lock()
_http_retry_path = ContextVar('pons_http_retry_path', default=())
_HTTP_WRAPPERS = frozenset({'public_same_endpoint_retry','canonical_exact_fallback'})


@contextmanager
def http_retry_context(kind, prior_error):
    """Fixed, bounded ancestry around existing retry/fallback calls only."""
    if kind not in _HTTP_WRAPPERS:
        raise ValueError('provider_http_retry_context_kind')
    facts = getattr(prior_error, 'provider_http_context', {})
    parent = _http_retry_path.get()
    if not parent and isinstance(facts, dict):
        # A fallback after the same-public retry inherits that failed attempt's
        # lineage even though the first wrapper has already unwound.
        parent = tuple(row for row in facts.get('wrapper_retry_path', ())[-4:]
            if isinstance(row, dict) and row.get('wrapper') in _HTTP_WRAPPERS)
    entry = dict(wrapper=kind, cause_boundary=failure_class(prior_error))
    if isinstance(facts, dict):
        for name in ('endpoint_fingerprint','request_fingerprint'):
            value=facts.get(name)
            if isinstance(value,str) and re.fullmatch(r'[0-9a-f]{64}',value):
                entry['cause_'+name]=value
    token = _http_retry_path.set((parent+(entry,))[-4:])
    try:yield
    finally:_http_retry_path.reset(token)


def error_with_context(error, boundary=None):
    """Preserve already sanitized HTTP facts across existing boundary wrappers."""
    wrapped = BoundaryError(boundary or failure_class(error))
    facts = getattr(error, 'provider_http_context', None)
    if isinstance(facts, dict):
        wrapped.provider_http_context = facts
        wrapped.add_note('provider_http_context=' + json.dumps(facts, sort_keys=True))
    original=getattr(error,'provider_original_boundary',None)
    if isinstance(original,str):
        original=failure_class(BoundaryError(original))
        wrapped.provider_original_boundary=original
        wrapped.add_note('original_transport_boundary='+original)
    from meme_machine.runtime.sqlite_failure import payload
    sqlite_failure=payload(error)
    if sqlite_failure is not None:
        wrapped.sqlite_failure=sqlite_failure
        wrapped.add_note('sqlite_failure='+json.dumps(sqlite_failure,sort_keys=True))
    return wrapped


def _error_fields(raw):
    """Extract fixed classifications/numbers, never provider messages or data."""
    try:
        parsed = json.loads(raw)
    except (ValueError, UnicodeError):
        return dict(json_valid=False), False
    items = parsed if isinstance(parsed, list) else [parsed]
    rows = []
    range_limit = False
    for item in items[:8]:
        if not isinstance(item, dict):
            continue
        error = item.get('error')
        if not isinstance(error, dict):
            continue
        row = {}
        code = error.get('code')
        if type(code) is int and -(2**31) <= code < 2**31:
            row['code'] = code
        message = str(error.get('message', '')).lower()
        classes = []
        for label, words in (
            ('rate_limit', ('rate limit', 'rate-limit', 'too many requests')),
            ('concurrency_limit', ('concurrency', 'concurrent requests')),
            ('compute_unit_limit', ('compute unit', 'compute-unit', 'throughput')),
            ('quota_limit', ('quota', 'allowance')),
            ('response_size', ('response size', 'too many results', 'too many logs')),
        ):
            if any(word in message for word in words):
                classes.append(label)
        if 'block' in message and ('range' in message or 'limit' in message):
            range_limit = True
            classes.append('block_range_limit')
        if classes:
            row['message_classes'] = classes
        if row:
            rows.append(row)
    return dict(json_valid=True, errors=rows, errors_truncated=len(items) > 8), range_limit


class Rpc:
    def __init__(self, endpoint, *, limit=80, per_scope=40, retries=1,
                 timeout=10, max_response=2_000_000, transport=None):
        parsed = urlsplit(endpoint)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username:
            raise BoundaryError('MM_ROBINHOOD_READ_RPC_URL_requires_full_https_url')
        if not (1 <= limit <= 200 and 1 <= per_scope <= limit and 0 <= retries <= 2):
            raise BoundaryError('invalid_request_bounds')
        self._endpoint = endpoint
        self.limit, self.per_scope, self.retries = limit, per_scope, retries
        self.timeout, self.max_response = timeout, max_response
        self.transport = transport or self._http
        self.counts, self.failures, self.cache = Counter(), Counter(), OrderedDict()
        self.last_transport_failure = None
        self.used = 0
        self.transport_used = 0
        self.physical_http_requests = 0
        self.request_bytes = 0
        self.response_bytes = 0
        self.logical = 0
        self.retry_count = 0
        self.methods, self.logical_methods = Counter(), Counter()
        self.last_retry_after_seconds = None

    def _transport_timeout(self):
        deadline = getattr(self, 'evidence_deadline', None)
        if deadline is None:
            return self.timeout
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise BoundaryError('evidence_deadline_before_transport')
        return min(self.timeout, remaining)

    def _check_transport_deadline(self):
        deadline = getattr(self, 'evidence_deadline', None)
        if deadline is not None and time.monotonic() >= deadline:
            raise BoundaryError('evidence_deadline_during_transport')

    def _wire_context(self, methods, timeout, *, batch=False):
        from meme_machine.runtime.robinhood.provider_usage import _active
        from meme_machine.runtime.provider_purchases import work_label
        from .provider_admission import transport_clock, fingerprint as endpoint_fingerprint
        attempt = _active.get()
        clock = transport_clock
        fingerprint = endpoint_fingerprint(self._endpoint)
        with _http_inflight_lock:
            _http_inflight[fingerprint] += 1
            inflight = _http_inflight[fingerprint]
        started = clock()
        deadline = started + timeout
        evidence_deadline = getattr(self, 'evidence_deadline', None)
        if evidence_deadline is not None:
            deadline = min(deadline, evidence_deadline)
        facts = dict(endpoint_fingerprint=fingerprint, methods=list(methods),
            logical_elements=len(methods), batch=batch, dispatch_monotonic=started,
            completion_monotonic=None, transport_deadline_monotonic=deadline,
            inflight_at_dispatch=inflight, inflight_scope='process_endpoint',
            rpc_retry_attempt=getattr(self, 'retry_attempt', 0),
            wrapper_retry_ancestry=work_label(family='pons'),
            wrapper_retry_path=[dict(row) for row in _http_retry_path.get()])
        if attempt:
            facts['admission_retry_attempt'] = attempt['retry_attempt']
            facts['admission_session'] = attempt['session']
            attempt['transport_dispatch_monotonic'] = started
            attempt['transport_inflight_at_dispatch'] = inflight
            attempt['transport_inflight_scope'] = 'process_endpoint'
        return facts, clock, attempt

    @staticmethod
    def _wire_complete(wire):
        if wire is None:
            return
        facts, clock, attempt = wire
        if facts['completion_monotonic'] is not None:
            return
        completed = clock()
        facts['completion_monotonic'] = completed
        if attempt is not None:
            attempt['transport_complete_monotonic'] = completed
        fingerprint = facts['endpoint_fingerprint']
        with _http_inflight_lock:
            _http_inflight[fingerprint] -= 1
            if not _http_inflight[fingerprint]:
                del _http_inflight[fingerprint]

    def _http_error(self, exc, wire, methods, calls, *, batch=False):
        """Essential facts precede optional, bounded response inspection.

        The HTTP boundary remains the original status if capture fails or its
        original deadline has expired. No provider error message/body is retained.
        """
        from meme_machine.runtime.robinhood.provider_usage import _active
        from .provider_admission import fingerprint as endpoint_fingerprint
        attempt = _active.get()
        clock = wire[1] if wire else time.monotonic
        facts = wire[0] if wire else dict(
            endpoint_fingerprint=endpoint_fingerprint(self._endpoint),
            methods=list(methods), logical_elements=len(methods), batch=batch,
            dispatch_monotonic=None, completion_monotonic=None)
        facts.update(http_status=exc.code, response_headers={}, body_bytes_read=0,
            body_limit_bytes=HTTP_ERROR_BYTES, body_truncated=False,
            body_read_failed=False, body_read_skipped=False,
            body_read_complete=False, context_complete=False)
        facts['error_response_monotonic'] = clock()
        error = BoundaryError(f'provider_http_{exc.code}')
        error.provider_http_context = facts
        if attempt is not None:
            attempt['http_error_context'] = facts
        # Essential status/correlation is present even if any optional probe fails.
        try:
            # Only failed requests need duplicate correlation. Canonical method /
            # parameter digests preserve exact equality without retaining inputs.
            fingerprints = [hashlib.sha256(json.dumps([method,params],sort_keys=True,
                separators=(',',':')).encode()).hexdigest() for method,params in calls]
            facts['logical_request_fingerprints'] = fingerprints
            facts['request_fingerprint'] = hashlib.sha256(json.dumps(fingerprints,
                separators=(',',':')).encode()).hexdigest()
            facts['method_counts'] = dict(Counter(methods))
            self._error_headers(exc, facts)
            deadline = facts.get('transport_deadline_monotonic')
            raw = self._error_body(exc, facts, deadline, clock)
            if raw:
                fields, range_limit = _error_fields(raw)
                facts['error_fields'] = fields
                if exc.code == 400 and range_limit:
                    error = BoundaryError('provider_log_block_range_limit')
                    error.provider_http_context = facts
            if deadline is not None and clock() >= deadline:
                facts['capture_deadline_expired'] = True
            facts['context_complete'] = True
        except Exception:
            facts['context_capture_failed'] = True
        finally:
            self._wire_complete(wire)
            try:exc.close()
            except Exception:facts['response_close_failed']=True
            error.add_note('provider_http_context=' + json.dumps(facts, sort_keys=True))
        return error

    def _error_headers(self, exc, facts):
        headers = exc.headers
        if headers is None:
            return
        safe = facts['response_headers']
        for name in ('Retry-After', 'RateLimit-Limit', 'RateLimit-Remaining',
                     'RateLimit-Reset', 'RateLimit-Policy', 'X-RateLimit-Limit',
                     'X-RateLimit-Remaining', 'X-RateLimit-Reset',
                     'X-Request-ID', 'Request-ID', 'X-Correlation-ID', 'CF-Ray'):
            raw = headers.get(name)
            if not isinstance(raw, str) or len(raw) > 256:
                continue
            raw = raw.strip()
            secret = self._endpoint.rstrip('/').rsplit('/', 1)[-1]
            if self._endpoint in raw or (len(secret) >= 8 and secret in raw):
                facts['header_value_redacted'] = True
                continue
            key = name.lower()
            if name == 'Retry-After':
                try:
                    number = float(raw)
                    if math.isfinite(number) and 0 <= number <= 86400:
                        safe[key] = number
                        if facts['http_status']==429 and not facts['batch'] and number<=1:
                            # Keep the existing bounded single-call retry hint.
                            self.last_retry_after_seconds=number
                        continue
                except ValueError:
                    pass
                try:
                    date = parsedate_to_datetime(raw)
                    if date.tzinfo is None:
                        date = date.replace(tzinfo=timezone.utc)
                    safe[key] = date.astimezone(timezone.utc).isoformat()
                except (TypeError, ValueError, OverflowError):
                    pass
            elif name in ('X-Request-ID', 'Request-ID', 'X-Correlation-ID', 'CF-Ray'):
                if re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', raw):
                    safe[key] = raw
            elif re.fullmatch(r'[0-9 .,:;=w]{1,256}', raw):
                safe[key] = raw

    @staticmethod
    def _error_read_timeout(exc, remaining):
        # urllib's HTTPError wraps HTTPResponse.fp.raw._sock. Bind a shorter
        # failure-body read to the original transport deadline. In-memory test
        # responses cannot block; unknown wrappers are left unread.
        if isinstance(exc.fp, io.BytesIO):
            return True
        for path in (('fp', 'raw', '_sock'), ('raw', '_sock'), ('_sock',)):
            value = exc.fp
            try:
                for name in path:
                    value = getattr(value, name)
                value.settimeout(remaining)
                return True
            except (AttributeError, OSError, ValueError):
                pass
        return False

    def _error_body(self, exc, facts, deadline, clock):
        """At most one raw receive per read, bounded by the original deadline.

        A socket timeout alone bounds each receive, not a buffered read's total
        duration. Rebind it to remaining time before each read1. Chunk-header
        parsing and unknown read wrappers cannot provide this bound; leave their
        body unread rather than extending an evidence deadline.
        """
        remaining = 0 if deadline is None else deadline-clock()
        if remaining <= 0:
            facts.update(body_read_skipped=True, body_read_skip_reason='original_deadline')
            return b''
        memory = isinstance(exc.fp, io.BytesIO)
        reader = exc.read if memory else getattr(exc.fp, 'read1', None)
        if not memory and getattr(exc.fp, 'chunked', False):
            facts.update(body_read_skipped=True, body_read_skip_reason='chunked_deadline_unbounded')
            return b''
        if not callable(reader) or not self._error_read_timeout(exc, remaining):
            facts.update(body_read_skipped=True, body_read_skip_reason='timeout_binding_unavailable')
            return b''
        facts['body_read_mode'] = 'in_memory' if memory else 'single_receive_read1'
        raw = bytearray()
        while len(raw) < HTTP_ERROR_BYTES:
            remaining = deadline-clock()
            if remaining <= 0:
                facts['body_read_deadline_expired'] = True
                break
            if not self._error_read_timeout(exc, remaining):
                facts.update(body_read_skipped=True, body_read_skip_reason='timeout_binding_unavailable')
                break
            try:
                chunk = reader(HTTP_ERROR_BYTES-len(raw) if memory else
                    min(1024, HTTP_ERROR_BYTES-len(raw)))
            except Exception:
                facts['body_read_failed'] = True
                facts['body_read_bytes_unknown'] = True
                break
            if not chunk:
                facts['body_read_complete'] = True
                break
            # Count each delivered chunk immediately, including a partial body
            # followed by timeout/read failure. Unread bytes remain unknown.
            self.response_bytes += len(chunk)
            facts['body_bytes_read'] += len(chunk)
            http_received(len(chunk))
            raw.extend(chunk)
        facts['body_truncated'] = len(raw) >= HTTP_ERROR_BYTES
        return bytes(raw)

    @account_transport('pons')
    def _http(self, method, params):
        self.last_retry_after_seconds = None
        body = json.dumps(dict(jsonrpc='2.0', id=1, method=method, params=params)).encode()
        request = Request(self._endpoint, data=body, headers=RPC_HTTP_HEADERS)
        wire = None
        try:
            timeout=self._transport_timeout()
            from .provider_admission import transport_ready
            transport_ready()
            timeout=self._transport_timeout()
            http_started(len(body))
            self.physical_http_requests += 1
            self.request_bytes += len(body)
            transport_ready(final=True)
            timeout=self._transport_timeout()
            wire = self._wire_context([method], timeout)
            with urlopen(request, timeout=timeout) as response:
                raw = response.read(self.max_response + 1)
                self.response_bytes += len(raw)
                http_received(len(raw))
        except HTTPError as exc:
            # Never include str(exc): a URL can include the full credential.
            raise self._http_error(exc, wire, [method], [(method,params)]) from None
        except (URLError, TimeoutError, OSError):
            self._check_transport_deadline()
            raise BoundaryError('provider_transport_failure') from None
        finally:
            self._wire_complete(wire)
        self._check_transport_deadline()
        if len(raw) > self.max_response:
            raise BoundaryError('provider_response_capacity')
        try:
            reply = json.loads(raw)
            if reply.get('error'):
                raise BoundaryError(rpc_boundary(method,reply['error']))
            if reply.get('id') != 1 or 'result' not in reply:
                raise BoundaryError('provider_invalid_envelope')
            return reply['result']
        except (ValueError, AttributeError, TypeError) as exc:
            if isinstance(exc, BoundaryError):
                raise
            raise BoundaryError('provider_invalid_json') from None

    def call(self, method, params, *, scope='connectivity'):
        if method not in READ_METHODS:
            raise BoundaryError('rpc_method_not_read_only')
        if scope not in self.counts and len(self.counts) >= 32:
            raise BoundaryError('provider_scope_capacity')
        self.logical += 1
        self.logical_methods[method] += 1
        # Cache only immutable receipts after the caller verifies their block hash.
        # Latest/state/log requests never reuse stale cache entries.
        key = json.dumps([method, params], sort_keys=True)
        cacheable = method == 'eth_getBlockByHash'
        ledger(self).consumer([method],cache_hit=cacheable and key in self.cache,family='pons')
        if cacheable and key in self.cache:
            return json.loads(self.cache[key])
        for attempt in range(self.retries + 1):
            if self.counts[scope] >= self.per_scope:
                raise BoundaryError('provider_pool_budget_exhausted')
            if self.used >= self.limit:
                raise BoundaryError('provider_session_budget_exhausted')
            self.used += 1
            self.transport_used += 1
            self.counts[scope] += 1
            self.methods[method] += 1
            self.retry_count += int(attempt > 0)
            self.retry_attempt = attempt
            try:
                try:
                    result = protect_response(self.transport(method, params), self._endpoint)
                except Exception as exc:
                    self._failure_location(exc)
                    raise error_with_context(exc) from None
                if result is None:
                    raise BoundaryError('provider_missing_result')
                if cacheable:
                    self.cache[key] = json.dumps(result)
                    while len(self.cache) > 128:
                        self.cache.popitem(last=False)
                return result
            except BoundaryError as exc:
                self.failures[failure_class(exc)] += 1
                # A quota boundary is terminal for this session, never retry it.
                if str(exc) in NO_RETRY or '429' in str(exc) or attempt == self.retries:
                    raise
                _stop_sleep(0.1 * (attempt + 1))

    @account_transport('pons')
    def _http_batch(self, calls):
        body=json.dumps([
            dict(jsonrpc='2.0',id=i+1,method=method,params=params)
            for i,(method,params) in enumerate(calls)
        ]).encode()
        request=Request(self._endpoint,data=body,headers=RPC_HTTP_HEADERS)
        wire=None
        try:
            timeout=self._transport_timeout()
            from .provider_admission import transport_ready
            transport_ready()
            timeout=self._transport_timeout()
            http_started(len(body))
            self.physical_http_requests += 1
            self.request_bytes += len(body)
            transport_ready(final=True)
            timeout=self._transport_timeout()
            wire=self._wire_context([method for method,_ in calls],timeout,batch=True)
            with urlopen(request,timeout=timeout) as response:
                raw=response.read(self.max_response+1)
                self.response_bytes += len(raw)
                http_received(len(raw))
        except HTTPError as exc:
            raise self._http_error(exc,wire,[method for method,_ in calls],calls,batch=True) from None
        except (URLError,TimeoutError,OSError):
            self._check_transport_deadline()
            raise BoundaryError('provider_transport_failure') from None
        finally:
            self._wire_complete(wire)
        self._check_transport_deadline()
        if len(raw)>self.max_response:
            raise BoundaryError('provider_response_capacity')
        try:
            reply=json.loads(raw)
            if not isinstance(reply,list) or len(reply)!=len(calls):
                raise BoundaryError('provider_invalid_batch_envelope')
            rows={item.get('id'):item for item in reply if isinstance(item,dict)}
            if set(rows)!=set(range(1,len(calls)+1)):
                raise BoundaryError('provider_invalid_batch_ids')
            out=[]
            for i in range(1,len(calls)+1):
                item=rows[i]
                if item.get('error'):
                    raise BoundaryError(rpc_boundary(calls[i-1][0],item['error']))
                if 'result' not in item or item['result'] is None:
                    raise BoundaryError('provider_missing_result')
                out.append(item['result'])
            return out
        except (ValueError,AttributeError,TypeError) as exc:
            if isinstance(exc,BoundaryError):
                raise
            raise BoundaryError('provider_invalid_json') from None

    def batch(self,calls,*,scope='connectivity'):
        """Bounded JSON-RPC batch: logical budget is unchanged; transport is reduced."""
        if not isinstance(calls,list) or not calls or len(calls)>50:
            raise BoundaryError('provider_batch_capacity')
        if any(not isinstance(row,(list,tuple)) or len(row)!=2 for row in calls):
            raise BoundaryError('provider_batch_shape')
        methods=[row[0] for row in calls]
        if any(method not in READ_METHODS for method in methods):
            raise BoundaryError('rpc_method_not_read_only')
        if scope not in self.counts and len(self.counts)>=32:
            raise BoundaryError('provider_scope_capacity')
        needed=len(calls)
        if self.counts[scope]+needed>self.per_scope:
            raise BoundaryError('provider_pool_budget_exhausted')
        if self.used+needed>self.limit:
            raise BoundaryError('provider_session_budget_exhausted')
        self.logical+=needed
        ledger(self).consumer(methods,cache_hit=False,family='pons')
        self.used+=needed
        self.transport_used+=1
        self.counts[scope]+=needed
        for method in methods:
            self.logical_methods[method]+=1
            self.methods[method]+=1
        try:
            if self.transport != self._http:
                # Custom unit-test transports remain deterministic and do not gain
                # implicit network semantics. Batch through the injected transport.
                return [protect_response(self.transport(method,params),self._endpoint) for method,params in calls]
            self.retry_attempt = 0
            return protect_response(self._http_batch(calls),self._endpoint)
        except Exception as exc:
            self._failure_location(exc)
            reason=failure_class(exc)
            self.failures[reason]+=1
            raise error_with_context(exc,reason) from None

    def _failure_location(self,exc):
        # Unknown faults previously became an opaque boundary and lost their
        # repair location. Retain code identities, never exception text, locals,
        # request parameters or credential-bearing URLs.
        frames=[];tb=exc.__traceback__
        while tb is not None:
            frame=tb.tb_frame;module=frame.f_globals.get('__name__','')
            if module.startswith(('meme_machine.','urllib.','http.')):
                frames.append(dict(module=module,function=frame.f_code.co_name,line=tb.tb_lineno))
            tb=tb.tb_next
        self.last_transport_failure=dict(boundary=failure_class(exc),
            exception_type=type(exc).__name__,frames=frames[-6:])
        facts=getattr(exc,'provider_http_context',None)
        if isinstance(facts,dict):self.last_transport_failure['http_context']=facts

    def verify_chain(self):
        result = self.call('eth_chainId', [])
        if int(result, 16) != CHAIN_ID:
            raise BoundaryError('wrong_chain')
        return CHAIN_ID

    def telemetry(self):
        return dict(requests=self.used, transport_requests=self.transport_used,
                    provider_purchases=ledger(self).snapshot(),
                    physical_http_requests=self.physical_http_requests,
                    request_bytes=self.request_bytes,response_bytes=self.response_bytes,
                    byte_basis='HTTP request payload attempted; response payload read; excludes headers/TLS/unread error bodies',
                    logical_requests=self.logical, retries=self.retry_count,
                    methods=dict(self.methods), logical_methods=dict(self.logical_methods),
                    scopes=dict(self.counts), failures=dict(self.failures),
                    last_transport_failure=self.last_transport_failure)

    def receipt(self, tx_hash, block_hash, *, scope):
        # A receipt is immutable only under the (transaction, block) identity.
        key = 'receipt:' + tx_hash + ':' + block_hash
        if key in self.cache:
            ledger(self).consumer(['eth_getTransactionReceipt'],cache_hit=True,family='pons')
            self.logical += 1
            self.logical_methods['eth_getTransactionReceipt'] += 1
            return json.loads(self.cache[key])
        result = self.call('eth_getTransactionReceipt', [tx_hash], scope=scope)
        if result['transactionHash'] != tx_hash or result['blockHash'] != block_hash:
            raise BoundaryError('receipt_block_disagreement')
        self.cache[key] = json.dumps(result)
        while len(self.cache) > 128:
            self.cache.popitem(last=False)
        return result


def _stop_sleep(seconds):
    from meme_machine.runtime.stop import sleep
    return sleep(seconds,sleeper=time.sleep)
