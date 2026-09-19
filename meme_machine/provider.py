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

    def __init__(self, url, limit=120, transport=None, clock=time.time, sleeper=time.sleep):
        if urlparse(url).scheme != 'https':
            raise ValueError('HTTPS RPC required')
        if not 40 <= limit <= 240:
            raise ValueError('request_limit must be 40..240')
        self.last_request = -float('inf')
        self.url, self.limit, self.clock, self.sleep = url, limit, clock, sleeper
        self.transport = transport or self._http
        # calls is the logical RPC-attempt budget. http_requests separately shows
        # physical transports so batching cannot silently increase economic scope.
        self.calls = self.http_requests = self.failures = self.cache_hits = self.retries = 0
        self.failure_kinds = {}
        # Adaptive getTransaction pressure control. Solana-specific RPC objects
        # share this state through read_pacer; plain RPC tests use the local copy.
        self.gettransaction_batch_size = 16
        self.gettransaction_429_streak = 0
        self.gettransaction_success_streak = 0
        self.gettransaction_429_events = 0
        self.gettransaction_batch_reductions = 0
        self.gettransaction_batch_recoveries = 0
        self.gettransaction_cooldown_seconds = 0.0
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

    def _transaction_controller(self):
        candidate=getattr(self,'read_pacer',None)
        if candidate is not None and hasattr(candidate,'gettransaction_batch_size'):
            return candidate
        return self

    def _adaptive_batch_size(self, method, requested):
        if method!='getTransaction':
            return int(requested)
        ctrl=self._transaction_controller()
        return max(1,min(int(requested),int(ctrl.gettransaction_batch_size)))

    def _note_gettransaction_429(self, count, attempted_batch_size=None):
        ctrl=self._transaction_controller()
        count=max(1,int(count))
        ctrl.gettransaction_429_events += count
        ctrl.gettransaction_429_streak += 1
        ctrl.gettransaction_success_streak = 0
        old=int(ctrl.gettransaction_batch_size)
        attempted=old if attempted_batch_size is None else max(1,int(attempted_batch_size))
        pressure_base=min(old,attempted)
        ctrl.gettransaction_batch_size=max(2,pressure_base//2)
        if ctrl.gettransaction_batch_size < old:
            ctrl.gettransaction_batch_reductions += 1
        delay=min(16.0,2.0*(2**min(ctrl.gettransaction_429_streak-1,3)))
        ctrl.gettransaction_cooldown_seconds += delay
        if ctrl is self:
            self.sleep(delay)
        else:
            now=float(self.clock())
            ctrl.next_request_at=max(float(ctrl.next_request_at),now+delay)
        return delay

    def _note_gettransaction_success(self):
        ctrl=self._transaction_controller()
        ctrl.gettransaction_429_streak=0
        ctrl.gettransaction_success_streak += 1
        if ctrl.gettransaction_success_streak >= 4 and ctrl.gettransaction_batch_size < 16:
            ctrl.gettransaction_batch_size=min(16,int(ctrl.gettransaction_batch_size)+2)
            ctrl.gettransaction_batch_recoveries += 1
            ctrl.gettransaction_success_streak=0

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

    def call(self, method, params=None, priority=False):
        if method not in self.ALLOWED:
            raise ValueError('read-only method allowlist')
        params = params or []
        key = self._key(method,params)
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
            self._pace(0.5)
            self.calls += 1
            if self.transport == self._http:
                self.http_requests += 1
            try:
                response = self.transport({'jsonrpc':'2.0','id':self.calls,'method':method,'params':params})
                if (response.get('error') or 'result' not in response or
                        (method == 'getTransaction' and response.get('result') is None)):
                    raise Unavailable('provider_error')
                result = response['result']
                last_error = None
                break
            except Exception as exc:
                self.failures += 1
                kind=self._failure_kind(exc)
                self.failure_kinds[kind]=self.failure_kinds.get(kind,0)+1
                last_error = exc
                if attempt+1 < attempts:
                    self.retries += 1
                    self.sleep(self._retry_delay(exc))
        if last_error is not None:
            raise Unavailable('provider_request_failed') from None
        self._cache_put(key,result)
        return result

    def call_many(self, method, params_list, priority=False, batch_size=8):
        """Batch read-only RPC with adaptive 429 handling.

        Successful members are cached immediately. getTransaction JSON-RPC/HTTP 429s
        do not fan out into immediate single-request retries: only the rate-limited
        members are requeued, the shared batch size is reduced, and a bounded
        exponential cooldown is scheduled. Non-rate-limit semantic failures retain
        the existing failed-member-only retry behavior.
        """
        if method not in self.ALLOWED:
            raise ValueError('read-only method allowlist')
        if not 1 <= batch_size <= 16:
            raise ValueError('batch_size must be 1..16')
        params_list=list(params_list)
        if not params_list:
            return []
        if self.transport != self._http:
            return [self.call(method,params,priority) for params in params_list]

        results=[None]*len(params_list)
        missing=[]
        retry_counts={}
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
            effective=self._adaptive_batch_size(method,batch_size)
            chunk=missing[:effective]
            missing=missing[effective:]
            logical=len(chunk)
            if self.calls + logical > cap:
                raise Unavailable('provider_budget_exhausted')
            self._pace(max(0.5,logical/4.0))
            first_id=self.calls+1
            requests=[
                {'jsonrpc':'2.0','id':first_id+i,'method':method,'params':params}
                for i,(_index,params,_key) in enumerate(chunk)
            ]
            self.calls += logical
            self.http_requests += 1
            failed=[]
            rate_limited=[]
            successes=0
            try:
                response=self.transport(requests)
                if not isinstance(response,list):
                    raise Unavailable('provider_error')
                by_id={
                    item.get('id'):item for item in response
                    if isinstance(item,dict)
                }
                for i,(index,params,key) in enumerate(chunk):
                    item=by_id.get(first_id+i)
                    error=item.get('error') if isinstance(item,dict) else None
                    code=error.get('code') if isinstance(error,dict) else None
                    if method=='getTransaction' and code in (429,-32005):
                        rate_limited.append((index,params,key))
                        continue
                    bad=bool(
                        not item or error or 'result' not in item or
                        (method=='getTransaction' and item.get('result') is None)
                    )
                    if bad:
                        failed.append((index,params,key))
                        continue
                    value=item['result']
                    results[index]=value
                    self._cache_put(key,value)
                    successes+=1
                if failed or rate_limited:
                    count=len(failed)+len(rate_limited)
                    self.failures += count
                    self.failure_kinds['provider_error']=(
                        self.failure_kinds.get('provider_error',0)+count)
            except Exception as exc:
                if (method=='getTransaction' and isinstance(exc,urllib.error.HTTPError)
                        and int(exc.code)==429):
                    rate_limited=list(chunk)
                    self.failures += logical
                    kind=self._failure_kind(exc)
                    self.failure_kinds[kind]=self.failure_kinds.get(kind,0)+logical
                else:
                    failed=list(chunk)
                    self.failures += logical
                    kind=self._failure_kind(exc)
                    self.failure_kinds[kind]=self.failure_kinds.get(kind,0)+logical

            if method=='getTransaction' and successes and not rate_limited:
                self._note_gettransaction_success()

            if rate_limited:
                retryable=[]
                for item in rate_limited:
                    index=item[0]
                    retry_counts[index]=retry_counts.get(index,0)+1
                    if retry_counts[index] > 2:
                        raise Unavailable('provider_request_failed')
                    retryable.append(item)
                self.retries += len(retryable)
                self._note_gettransaction_429(len(retryable),logical)
                # Retry only rate-limited members, before unrelated older backlog.
                missing=retryable+missing

            if failed:
                self.retries += len(failed)
                for index,params,key in failed:
                    try:
                        value=self.call(method,params,priority)
                    except Unavailable:
                        raise Unavailable('provider_request_failed') from None
                    results[index]=value
                    self._cache_put(key,value)
        return results


class PumpAdapter:
    def __init__(self, rpc):
        self.rpc = rpc
        if rpc.call('getGenesisHash', priority=True) != pump.MAINNET:
            raise Unavailable('unsupported_network')
        self.fee_address = pump.pda([b'fee_config',pump.un58(pump.PROGRAM)], pump.FEE_PROGRAM)
        # Lazily reuse the exact concentration evidence path already proven by the
        # natural observer. Import locally to avoid a provider/concentration module
        # cycle during module initialization.
        self._concentration_reader = None

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
                                    'maxSupportedTransactionVersion':1}]
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

    def concentration(self, mint, snapshot, priority=True):
        """Return top-five concentration through the shared bounded evidence reader.

        Prospective qualification previously called getTokenLargestAccounts directly,
        while the natural observer used the compact finalized getProgramAccounts scan.
        Reuse that same reader here so observation and executable qualification have
        identical concentration semantics and fallback behavior. The compact scan has
        its own bounded 40-request read-only budget; failures still fail closed.
        """
        if self._concentration_reader is None:
            from .concentration import ConcentrationReader
            self._concentration_reader = ConcentrationReader(self.rpc)
        value,_meta = self._concentration_reader.read(
            mint, snapshot, priority=bool(priority))
        return value

    def concentration_status(self):
        if self._concentration_reader is None:
            return dict(initialized=False)
        return dict(initialized=True, **self._concentration_reader.status())
