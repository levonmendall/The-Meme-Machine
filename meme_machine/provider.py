"""One bounded provider budget; monitoring gets reserved capacity."""
import json
import time
import urllib.request
from urllib.parse import urlparse
from . import pump


class Unavailable(RuntimeError):
    pass


class RPC:
    ALLOWED = {'getGenesisHash', 'getSignaturesForAddress', 'getTransaction',
               'getMultipleAccounts', 'getTokenLargestAccounts', 'getBlockTime'}

    def __init__(self, url, limit=120, transport=None, clock=time.time):
        if urlparse(url).scheme != 'https':
            raise ValueError('HTTPS RPC required')
        if not 40 <= limit <= 240:
            raise ValueError('request_limit must be 40..240')
        self.last_request = -float('inf')
        self.url, self.limit, self.clock = url, limit, clock
        self.transport = transport or self._http
        self.calls = self.failures = self.cache_hits = self.retries = 0
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

    def call(self, method, params=None, priority=False):
        if method not in self.ALLOWED:
            raise ValueError('read-only method allowlist')
        params = params or []
        key = json.dumps([method, params], sort_keys=True)
        now = self.clock()
        if key in self.cache and now-self.cache[key][0] <= 2:
            self.cache_hits += 1
            return self.cache[key][1]
        # Session lifetime cap; restarting deliberately starts a new explicitly budgeted run.
        cap = self.limit if priority else max(0, self.limit-40)
        attempts = 2 if self.transport == self._http else 1
        result = None
        last_error = None
        for attempt in range(attempts):
            if self.calls >= cap:
                raise Unavailable('provider_budget_exhausted')
            if self.transport == self._http:
                # Every physical request, including the one bounded retry, obeys the
                # same pacing and consumes the same request budget.
                time.sleep(max(0, self.last_request + 0.5 - self.clock()))
                self.last_request = self.clock()
            self.calls += 1
            try:
                response = self.transport({'jsonrpc':'2.0','id':self.calls,'method':method,'params':params})
                if response.get('error') or 'result' not in response:
                    raise Unavailable('provider_error')
                result = response['result']
                last_error = None
                break
            except Exception as exc:
                self.failures += 1
                last_error = exc
                # Custom/test transports remain single-attempt. Real HTTP gets one
                # bounded retry for transient public-RPC/network failure; no retry
                # changes a strategy decision and all attempts count toward cap.
                if attempt+1 < attempts:
                    self.retries += 1
                    time.sleep(0.5)
        if last_error is not None:
            # Never leak credential-bearing URLs/provider error bodies.
            raise Unavailable('provider_request_failed') from None
        size = len(json.dumps(result))
        if key in self.cache:
            self.cache_bytes -= self.cache.pop(key)[2]
        while self.cache and (len(self.cache) >= 128 or self.cache_bytes+size > 8*1024*1024):
            self.cache_bytes -= self.cache.pop(next(iter(self.cache)))[2]
        self.cache[key] = (self.clock(), result, size)
        self.cache_bytes += size
        return result


class PumpAdapter:
    def __init__(self, rpc):
        self.rpc = rpc
        if rpc.call('getGenesisHash', priority=True) != pump.MAINNET:
            raise Unavailable('unsupported_network')
        self.fee_address = pump.pda([b'fee_config',pump.un58(pump.PROGRAM)], pump.FEE_PROGRAM)

    def history(self, address, now, priority=False):
        signatures = self.rpc.call('getSignaturesForAddress', [address, {'limit':20,'commitment':'finalized'}], priority)
        events = []
        # Only claim a complete 60-second window if the bounded tail reaches its start.
        covered = bool(signatures) and signatures[-1].get('blockTime') is not None and signatures[-1]['blockTime'] <= now-60
        for sig in reversed(signatures):
            if sig.get('err') or sig.get('blockTime') is None or sig['blockTime'] < now-60:
                continue
            tx = self.rpc.call('getTransaction', [sig['signature'], {'encoding':'json','commitment':'finalized','maxSupportedTransactionVersion':0}], priority)
            if tx is None:
                covered = False
                continue
            for e in pump.trade_events(tx):
                e.update(id=f"{sig['signature']}:{e['index']}", available_time=int(self.rpc.clock()))
                events.append(e)
        return events, covered

    def snapshot(self, mint, now, priority=False):
        pool = pump.pda([b'bonding-curve', pump.un58(mint)])
        result = self.rpc.call('getMultipleAccounts', [[pool,mint,self.fee_address], {'encoding':'base64','commitment':'finalized'}], priority)
        c = pump.curve(result['value'][0])
        supply, decimals = pump.mint_info(result['value'][1])
        if supply != c.supply:
            raise Unavailable('supply_mismatch')
        rates = pump.fees(result['value'][2], c)
        market_time = self.rpc.call('getBlockTime', [result['context']['slot']], priority)
        if market_time is None:
            raise Unavailable('missing_block_time')
        # Exact source bytes retained with orders, not every poll.
        return dict(mint=mint,pool=pool,slot=result['context']['slot'],market_time=market_time,
                    available_time=int(self.rpc.clock()),accounts=result['value'],decimals=decimals,
                    protocol='pump.fun',network='solana-mainnet',kind='real')

    def concentration(self, mint, snapshot, priority=False):
        result = self.rpc.call('getTokenLargestAccounts',[mint, {'commitment':'finalized'}],priority)
        if result['context']['slot'] < snapshot['slot']-32:
            raise Unavailable('stale_concentration')
        # Curve custody is excluded; this metric is account concentration, not beneficial ownership.
        c = pump.curve(snapshot['accounts'][0])
        custody = pump.pda([pump.un58(snapshot['pool']), pump.un58(snapshot['accounts'][1]['owner']), pump.un58(mint)],
                           'ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL')
        amounts = sorted((int(x['amount']) for x in result['value'] if x['address'] != custody), reverse=True)
        return sum(amounts[:5])*10000//c.supply
