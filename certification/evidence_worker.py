"""Shared read-only Solana ingestion process, launched by the paper supervisor.

Importing this module opens no network. Explicit process startup requires the same
existing authenticated Alchemy endpoint and the unchanged shared governor.
"""
import asyncio
import json
import os
import signal
import urllib.error
import urllib.request
from pathlib import Path
from certification.governor import Governor
from meme_machine.solana_evidence_transport import alchemy_stream_endpoint
from meme_machine.solana_evidence_service import serve

class RepairRPC:
    def __init__(self,endpoint,governor):
        from meme_machine.solana_provider_config import AlchemyEndpoint
        from collections import Counter
        import threading
        self.config=AlchemyEndpoint.parse(endpoint)
        self.endpoint=self.config.http_url;self.governor=governor
        self.counts=Counter({k:0 for k in ('physical_requests','logical_calls','repair_calls','identity_calls','failures','429s','unsupported_methods','queue_microseconds','transport_microseconds')});self.lock=threading.Lock()
    def _count(self,key,n=1):
        with self.lock:self.counts[key]+=n
    def telemetry(self):
        from certification.cu import estimate
        with self.lock:counts=dict(self.counts)
        methods={k.split(':',1)[1]:v for k,v in counts.items() if k.startswith('method:')}
        return dict(counters=counts,estimated_alchemy=estimate(methods),
                    endpoint_identity=self.config.identity,provider=self.config.provider)
    def validate_network(self):
        from meme_machine.solana_provider_config import GENESIS
        if self.call('getGenesisHash',[],False)!=GENESIS:
            raise ValueError('solana_network_identity_mismatch')
    def call(self,method,params,priority=False):
        import time
        if method not in ('getTransactionsForAddress','getGenesisHash'):
            raise ValueError('repair_method_forbidden')
        started=time.monotonic();transport=None
        try:
            self.governor.acquire('solana','evidence',2 if priority else 50,deadline_seconds=8,methods=(method,))
            self._count('queue_microseconds',int((time.monotonic()-started)*1e6))
            transport=time.monotonic()
            self._count('physical_requests');self._count('logical_calls');self._count('method:'+method)
            self._count('repair_calls' if method=='getTransactionsForAddress' else 'identity_calls')
            request=urllib.request.Request(self.endpoint,json.dumps(dict(jsonrpc='2.0',id=1,method=method,params=params)).encode(),{'Content-Type':'application/json'})
            with urllib.request.urlopen(request,timeout=8) as response:raw=response.read(16*1024*1024+1)
            if len(raw)>16*1024*1024:raise ValueError('repair_response_bound')
            value=json.loads(raw)
            code=(value.get('error') or {}).get('code')
            if code in (429,-32005):
                self._count('429s');self.governor.rate_limited('solana',(method,))
            if code==-32601:self._count('unsupported_methods')
            if value.get('id')!=1 or 'error' in value or 'result' not in value:
                raise ValueError('repair_response_unavailable')
            self.config.public(value)
            self.governor.succeeded('solana',(method,))
            return value['result']
        except urllib.error.HTTPError as exc:
            if exc.code==429:
                self._count('429s');self.governor.rate_limited('solana',(method,))
            self._count('failures')
            raise ValueError('repair_http_'+str(int(exc.code))) from None
        except Exception:
            self._count('failures')
            raise ValueError('repair_response_unavailable') from None
        finally:
            if transport is not None:self._count('transport_microseconds',int((time.monotonic()-transport)*1e6))


async def main_async():
    endpoint=os.environ['MM_SOLANA_READ_RPC_URL']
    path=Path(os.environ['MM_SOLANA_EVIDENCE_PLANE_DB'])
    governor=Governor(os.environ['MM_CERT_GOVERNOR_DB'])
    stop=asyncio.Event();loop=asyncio.get_running_loop()
    for sig in (signal.SIGINT,signal.SIGTERM):loop.add_signal_handler(sig,stop.set)
    rpc=RepairRPC(endpoint,governor)
    await asyncio.to_thread(rpc.validate_network)
    await serve(path,endpoint,repair_rpc=rpc,stop=stop)

if __name__=='__main__':
    # Final process diagnostic never formats third-party exceptions/URLs.
    try:asyncio.run(main_async())
    except Exception as exc:
        raise SystemExit('evidence_worker_failed:'+type(exc).__name__) from None
