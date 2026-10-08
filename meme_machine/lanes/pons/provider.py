"""Bounded, allowlisted read transport. Errors never contain endpoint secrets."""
from collections import Counter, OrderedDict
import json
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from . import BoundaryError, CHAIN_ID
from meme_machine.runtime.robinhood.provider_usage import http_started, http_received
from meme_machine.runtime.robinhood.provider_authority import failure_class, protect_response

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

    def _http(self, method, params):
        self.last_retry_after_seconds = None
        body = json.dumps(dict(jsonrpc='2.0', id=1, method=method, params=params)).encode()
        request = Request(self._endpoint, data=body, headers=RPC_HTTP_HEADERS)
        try:
            timeout=self._transport_timeout()
            http_started(len(body))
            self.physical_http_requests += 1
            self.request_bytes += len(body)
            with urlopen(request, timeout=timeout) as response:
                raw = response.read(self.max_response + 1)
                self.response_bytes += len(raw)
                http_received(len(raw))
        except HTTPError as exc:
            # Never include str(exc): a URL can include the full credential.
            if exc.code == 400:
                try:
                    error_body = exc.read(8192)
                    self.response_bytes += len(error_body)
                    http_received(len(error_body))
                    error = json.loads(error_body).get('error', {})
                    message = str(error.get('message', '')).lower()
                    if 'block' in message and ('range' in message or 'limit' in message):
                        raise BoundaryError('provider_log_block_range_limit') from None
                except BoundaryError:
                    raise
                except (ValueError, AttributeError):
                    pass
            if exc.code == 429:
                try:
                    retry_after = (
                        None if exc.headers is None
                        else exc.headers.get('Retry-After')
                    )
                    retry_after = float(retry_after)
                    if 0.0 <= retry_after <= 1.0:
                        self.last_retry_after_seconds = retry_after
                except (TypeError, ValueError, AttributeError):
                    self.last_retry_after_seconds = None
            raise BoundaryError(f'provider_http_{exc.code}') from None
        except (URLError, TimeoutError, OSError):
            self._check_transport_deadline()
            raise BoundaryError('provider_transport_failure') from None
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
                    raise BoundaryError(failure_class(exc)) from None
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

    def _http_batch(self, calls):
        body=json.dumps([
            dict(jsonrpc='2.0',id=i+1,method=method,params=params)
            for i,(method,params) in enumerate(calls)
        ]).encode()
        request=Request(self._endpoint,data=body,headers=RPC_HTTP_HEADERS)
        try:
            timeout=self._transport_timeout()
            http_started(len(body))
            self.physical_http_requests += 1
            self.request_bytes += len(body)
            with urlopen(request,timeout=timeout) as response:
                raw=response.read(self.max_response+1)
                self.response_bytes += len(raw)
                http_received(len(raw))
        except HTTPError as exc:
            if exc.code == 400:
                try:
                    error_body=exc.read(8192)
                    self.response_bytes += len(error_body)
                    http_received(len(error_body))
                    error=json.loads(error_body).get('error',{})
                    message=str(error.get('message','')).lower()
                    if 'block' in message and ('range' in message or 'limit' in message):
                        raise BoundaryError('provider_log_block_range_limit') from None
                except BoundaryError:raise
                except (ValueError,AttributeError):pass
            raise BoundaryError(f'provider_http_{exc.code}') from None
        except (URLError,TimeoutError,OSError):
            self._check_transport_deadline()
            raise BoundaryError('provider_transport_failure') from None
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
            reason=failure_class(exc)
            self.failures[reason]+=1
            raise BoundaryError(reason) from None

    def verify_chain(self):
        result = self.call('eth_chainId', [])
        if int(result, 16) != CHAIN_ID:
            raise BoundaryError('wrong_chain')
        return CHAIN_ID

    def telemetry(self):
        return dict(requests=self.used, transport_requests=self.transport_used,
                    physical_http_requests=self.physical_http_requests,
                    request_bytes=self.request_bytes,response_bytes=self.response_bytes,
                    byte_basis='HTTP request payload attempted; response payload read; excludes headers/TLS/unread error bodies',
                    logical_requests=self.logical, retries=self.retry_count,
                    methods=dict(self.methods), logical_methods=dict(self.logical_methods),
                    scopes=dict(self.counts), failures=dict(self.failures))

    def receipt(self, tx_hash, block_hash, *, scope):
        # A receipt is immutable only under the (transaction, block) identity.
        key = 'receipt:' + tx_hash + ':' + block_hash
        if key in self.cache:
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
