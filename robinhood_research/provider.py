"""Bounded, allowlisted read transport. Errors never contain endpoint secrets."""
from collections import Counter, OrderedDict
import json
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from . import BoundaryError, CHAIN_ID

READ_METHODS = frozenset({
    'eth_chainId', 'eth_blockNumber', 'eth_getBlockByNumber',
    'eth_getBlockByHash', 'eth_getLogs', 'eth_getTransactionReceipt',
    'eth_getCode', 'eth_call', 'eth_gasPrice', 'eth_getBalance',
    'eth_getStorageAt', 'eth_getTransactionByHash',
})


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
        self.logical = 0
        self.retry_count = 0
        self.methods, self.logical_methods = Counter(), Counter()

    def _http(self, method, params):
        body = json.dumps(dict(jsonrpc='2.0', id=1, method=method, params=params)).encode()
        request = Request(self._endpoint, data=body, headers={'Content-Type': 'application/json'})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read(self.max_response + 1)
        except HTTPError as exc:
            # Never include str(exc): a URL can include the full credential.
            if exc.code == 400:
                try:
                    error = json.loads(exc.read(8192)).get('error', {})
                    message = str(error.get('message', '')).lower()
                    if 'block' in message and ('range' in message or 'limit' in message):
                        raise BoundaryError('provider_log_block_range_limit') from None
                except BoundaryError:
                    raise
                except (ValueError, AttributeError):
                    pass
            raise BoundaryError(f'provider_http_{exc.code}') from None
        except (URLError, TimeoutError, OSError):
            raise BoundaryError('provider_transport_failure') from None
        if len(raw) > self.max_response:
            raise BoundaryError('provider_response_capacity')
        try:
            reply = json.loads(raw)
            if reply.get('error'):
                code = reply['error'].get('code')
                code = code if isinstance(code, int) else 'unknown'
                raise BoundaryError(f'provider_rpc_{code}')
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
            self.counts[scope] += 1
            self.methods[method] += 1
            self.retry_count += int(attempt > 0)
            try:
                result = self.transport(method, params)
                if result is None:
                    raise BoundaryError('provider_missing_result')
                if cacheable:
                    self.cache[key] = json.dumps(result)
                    while len(self.cache) > 128:
                        self.cache.popitem(last=False)
                return result
            except BoundaryError as exc:
                self.failures[str(exc)] += 1
                # A quota boundary is terminal for this session, never retry it.
                if '429' in str(exc) or attempt == self.retries:
                    raise
                time.sleep(0.1 * (attempt + 1))

    def verify_chain(self):
        result = self.call('eth_chainId', [])
        if int(result, 16) != CHAIN_ID:
            raise BoundaryError('wrong_chain')
        return CHAIN_ID

    def telemetry(self):
        return dict(requests=self.used, transport_requests=self.used,
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
