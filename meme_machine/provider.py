"""One bounded provider budget; monitoring gets reserved capacity."""
import json
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse
from . import pump


class Unavailable(RuntimeError):
    pass


class RPC:
    ALLOWED = {'getGenesisHash', 'getSignaturesForAddress', 'getTransaction',
               'getMultipleAccounts', 'getTokenLargestAccounts', 'getBlockTime'}

    def __init__(self, url, limit=120, transport=None, clock=time.time, sleeper=time.sleep,
                 request_interval_seconds=0.5):
        if urlparse(url).scheme != 'https':
            raise ValueError('HTTPS RPC required')
        if not 40 <= limit <= 240:
            raise ValueError('request_limit must be 40..240')
        if not 0.2 <= float(request_interval_seconds) <= 5.0:
            raise ValueError('request_interval_seconds must be 0.2..5.0')
        self.last_request = -float('inf')
        self.url, self.limit, self.clock, self.sleep = url, limit, clock, sleeper
        self.request_interval_seconds = float(request_interval_seconds)
        self.transport = transport or self._http
        # calls is the logical RPC-attempt budget. http_requests separately shows
        # physical transports so batching cannot silently increase economic scope.
        self.calls = self.http_requests = self.failures = self.cache_hits = self.retries = 0
        self.batch_fallbacks = self.batch_fallback_items = self.null_retries = 0
        self.failure_kinds = {}
        self.failure_methods = {}
        self.cache = {}
        self.cache_bytes = 0
        self.started = clock()

    def _http(self, request):
        data = json.dumps(request).encode()
        req = urllib.request.Request(self.url, data, {'Content-Type':'application/json'})
        with urllib.request.urlopen(req, timeout=8) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise Unavailable('response_size_limit')
        return json.loads(raw)

    @staticmethod
    def _failure_kind(exc):
        # Keep diagnostics useful without ever returning URLs, response bodies,
        # credentials, or provider messages.
        if isinstance(exc, urllib.error.HTTPError):
            return f'http_{int(exc.code)}'
        if isinstance(exc, (TimeoutError, urllib.error.URLError)):
            return 'network_or_timeout'
        if isinstance(exc, json.JSONDecodeError):
            return 'invalid_json'
        if isinstance(exc, Unavailable):
            text=str(exc)
            return text if text in ('provider_error','response_size_limit') else 'provider_unavailable'
        return 'transport_exception'

    @staticmethod
    def _retry_delay(exc):
        # Solana's public endpoint explicitly asks 429 clients to honor Retry-After.
        # Bound the wait so a stale signal fails closed rather than holding a worker
        # indefinitely. Provider bodies/URLs are never surfaced.
        if isinstance(exc, urllib.error.HTTPError) and int(exc.code) == 429:
            try:
                value=float(exc.headers.get('Retry-After'))
                return max(0.5,min(value,30.0))
            except (TypeError,ValueError,AttributeError):
                return 1.0
        return 0.5

    def _cap(self, priority):
        return self.limit if priority else max(0, self.limit-40)

    @staticmethod
    def _key(method, params):
        return json.dumps([method, params], sort_keys=True)

    def _cache_get(self, key):
        now=self.clock()
        if key in self.cache and now-self.cache[key][0] <= 2:
            self.cache_hits += 1
            return True,self.cache[key][1]
        return False,None

    def _cache_put(self, key, result):
        size=len(json.dumps(result))
        if key in self.cache:
            self.cache_bytes -= self.cache.pop(key)[2]
        while self.cache and (len(self.cache) >= 128 or self.cache_bytes+size > 8*1024*1024):
            self.cache_bytes -= self.cache.pop(next(iter(self.cache)))[2]
        self.cache[key]=(self.clock(),result,size)
        self.cache_bytes += size

    def _pace(self, interval=0.5):
        if self.transport == self._http:
            self.sleep(max(0, self.last_request + interval - self.clock()))
            self.last_request = self.clock()

    def call(self, method, params=None, priority=False, fresh=False):
        if method not in self.ALLOWED:
            raise ValueError('read-only method allowlist')
        params = params or []
        if type(fresh) is not bool:
            raise ValueError('fresh must be bool')
        key = self._key(method,params)
        if not fresh:
            hit,result=self._cache_get(key)
            if hit:
                return result
        cap=self._cap(priority)
        attempts = 2 if self.transport == self._http else 1
        result = None
        last_error = None
        for attempt in range(attempts):
            if self.calls >= cap:
                raise Unavailable('provider_budget_exhausted')
            self._pace(self.request_interval_seconds)
            self.calls += 1
            if self.transport == self._http:
                self.http_requests += 1
            try:
                response = self.transport({'jsonrpc':'2.0','id':self.calls,'method':method,'params':params})
                if response.get('error') or 'result' not in response:
                    raise Unavailable('provider_error')
                result = response['result']
                if method=='getTransaction' and result is None and attempt+1 < attempts:
                    self._record_failure(method,'null_result')
                    self.null_retries += 1
                    self.retries += 1
                    self.sleep(0.5)
                    continue
                last_error = None
                break
            except Exception as exc:
                kind=self._failure_kind(exc)
                self._record_failure(method,kind)
                last_error = exc
                if attempt+1 < attempts:
                    self.retries += 1
                    delay=self._retry_delay(exc)
                    # A finalized getTransaction JSON-RPC provider error may be a
                    # throughput collision returned inside HTTP 200. Keep the same
                    # single retry, but do not immediately collide again.
                    if method=='getTransaction' and kind=='provider_error':
                        delay=max(delay,1.5)
                    self.sleep(delay)
        if last_error is not None:
            raise Unavailable('provider_request_failed') from None
        self._cache_put(key,result)
        return result

    def _record_failure(self, method, kind, count=1):
        self.failures += count
        self.failure_kinds[kind]=self.failure_kinds.get(kind,0)+count
        key=f'{method}:{kind}'
        self.failure_methods[key]=self.failure_methods.get(key,0)+count

    def call_many(self, method, params_list, priority=False, batch_size=8):
        """Read-only bounded JSON-RPC batching with fail-closed item recovery.

        A batch is only a transport optimization. Successful subresponses are retained.
        Missing/error/null `getTransaction` items are retried individually so one public
        RPC batch anomaly cannot discard an otherwise complete finalized interval. The
        fallback consumes the normal logical request budget and never widens evidence
        scope, transaction count, commitment, or freshness bounds.
        """
        if method not in self.ALLOWED:
            raise ValueError('read-only method allowlist')
        if not 1 <= batch_size <= 8:
            raise ValueError('batch_size must be 1..8')
        params_list=list(params_list)
        if not params_list:
            return []
        if self.transport != self._http:
            return [self.call(method,params,priority) for params in params_list]

        results=[None]*len(params_list)
        missing=[]
        for index,params in enumerate(params_list):
            params=params or []
            key=self._key(method,params)
            hit,value=self._cache_get(key)
            if hit:
                results[index]=value
            else:
                missing.append((index,params,key))

        cap=self._cap(priority)
        while missing:
            chunk=missing[:batch_size]
            missing=missing[batch_size:]
            logical=len(chunk)
            if self.calls + logical > cap:
                raise Unavailable('provider_budget_exhausted')
            self._pace(max(0.5,logical/4.0))
            first_id=self.calls+1
            requests=[{'jsonrpc':'2.0','id':first_id+i,'method':method,'params':params}
                      for i,(_,params,_) in enumerate(chunk)]
            self.calls += logical
            self.http_requests += 1
            fallback=[]
            try:
                response=self.transport(requests)
                if not isinstance(response,list):
                    raise Unavailable('provider_error')
                by_id={}
                for item in response:
                    if not isinstance(item,dict) or item.get('id') in by_id:
                        continue
                    by_id[item.get('id')]=item
                for i,(index,params,key) in enumerate(chunk):
                    item=by_id.get(first_id+i)
                    if not item or item.get('error') or 'result' not in item:
                        self._record_failure(method,'provider_error')
                        fallback.append((index,params,key))
                        continue
                    value=item['result']
                    if method=='getTransaction' and value is None:
                        self._record_failure(method,'null_result')
                        fallback.append((index,params,key))
                        continue
                    results[index]=value
                    self._cache_put(key,value)
            except Exception as exc:
                kind=self._failure_kind(exc)
                self._record_failure(method,kind,logical)
                fallback=list(chunk)
            if fallback:
                self.batch_fallbacks += 1
                self.batch_fallback_items += len(fallback)
                for index,params,key in fallback:
                    # Individual calls retain finalized commitment and retry once on
                    # the real HTTP path. This is intentionally narrower than
                    # repeating an identical failing batch.
                    value=self.call(method,params,priority)
                    if method=='getTransaction' and value is None:
                        # A finalized signature with a still-null body is incomplete
                        # evidence. Never convert it into an empty/benign mutation.
                        raise Unavailable('provider_transaction_unavailable')
                    results[index]=value
                    self._cache_put(key,value)
        return results


class PumpAdapter:
    def __init__(self, rpc):
        self.rpc = rpc
        if rpc.call('getGenesisHash', priority=True) != pump.MAINNET:
            raise Unavailable('unsupported_network')
        self.fee_address = pump.pda([b'fee_config',pump.un58(pump.PROGRAM)], pump.FEE_PROGRAM)

    def history(self, address, now, priority=False, require_coverage=False):
        # Qualification must prove the complete unchanged 60-second window. One
        # maximum bounded signature census is cheaper and fresher than pagination;
        # if even 1,000 references do not reach strictly before the cutoff, fail
        # closed instead of pretending a partial high-volume window is complete.
        limit = 1000 if require_coverage else 20
        signatures = self.rpc.call('getSignaturesForAddress',
            [address, {'limit':limit,'commitment':'finalized'}], priority)
        cutoff=now-60
        covered=False
        relevant=[]
        unknown_before_boundary=False
        for sig in signatures:
            block_time=sig.get('blockTime')
            if block_time is None:
                unknown_before_boundary=True
                continue
            if block_time < cutoff:
                covered=not unknown_before_boundary
                break
            relevant.append(sig)
        if require_coverage and not covered:
            return [],False

        successful=[sig for sig in relevant if not sig.get('err')]
        params=[[sig['signature'], {'encoding':'json','commitment':'finalized',
                                    'maxSupportedTransactionVersion':0}]
                for sig in successful]
        txs=self.rpc.call_many('getTransaction',params,priority,batch_size=8) if params else []
        events=[]
        for sig,tx in zip(successful,txs):
            if tx is None:
                covered=False
                continue
            for e in pump.trade_events(tx):
                e.update(id=f"{sig['signature']}:{e['index']}", available_time=int(self.rpc.clock()))
                events.append(e)
        return events,covered

    def snapshot(self, mint, now, priority=False):
        pool = pump.pda([b'bonding-curve', pump.un58(mint)])
        result = self.rpc.call('getMultipleAccounts', [[pool,mint,self.fee_address], {'encoding':'base64','commitment':'finalized'}], priority)
        c = pump.curve(result['value'][0])
        supply, decimals = pump.mint_info(result['value'][1])
        mode = pump.validate_mint_supply(result['value'][0], c, supply, decimals)
        # Validate the current fee schedule using actual mint supply. Mayhem mints
        # have additional circulating/agent inventory beyond token_total_supply.
        pump.fees(result['value'][2], c, supply)
        market_time = self.rpc.call('getBlockTime', [result['context']['slot']], priority)
        if market_time is None:
            raise Unavailable('missing_block_time')
        # Exact source bytes retained with orders, not every poll.
        return dict(mint=mint,pool=pool,slot=result['context']['slot'],market_time=market_time,
                    available_time=int(self.rpc.clock()),accounts=result['value'],decimals=decimals,
                    mint_supply=supply,mayhem_mode=mode['mayhem'],
                    protocol='pump.fun',network='solana-mainnet',kind='real')

    def concentration(self, mint, snapshot, priority=False):
        result = self.rpc.call('getTokenLargestAccounts',[mint, {'commitment':'finalized'}],priority)
        if result['context']['slot'] < snapshot['slot']-32:
            raise Unavailable('stale_concentration')
        # Curve custody is excluded; this metric is account concentration, not beneficial ownership.
        # Use actual mint supply so Mayhem's additional documented supply does not
        # mechanically double the concentration ratio.
        c = pump.curve(snapshot['accounts'][0])
        supply, decimals = pump.mint_info(snapshot['accounts'][1])
        pump.validate_mint_supply(snapshot['accounts'][0], c, supply, decimals)
        custody = pump.pda([pump.un58(snapshot['pool']), pump.un58(snapshot['accounts'][1]['owner']), pump.un58(mint)],
                           'ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL')
        amounts = sorted((int(x['amount']) for x in result['value'] if x['address'] != custody), reverse=True)
        return sum(amounts[:5])*10000//supply