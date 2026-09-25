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
        alchemy_stream_endpoint(endpoint)
        self.endpoint=endpoint;self.governor=governor
    def call(self,method,params,priority=False):
        if method!='getTransactionsForAddress':raise ValueError('repair_method_forbidden')
        self.governor.acquire('solana','evidence',2 if priority else 50,deadline_seconds=8,methods=(method,))
        request=urllib.request.Request(self.endpoint,json.dumps(dict(jsonrpc='2.0',id=1,method=method,params=params)).encode(),{'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(request,timeout=8) as response:raw=response.read(16*1024*1024+1)
        except urllib.error.HTTPError as exc:
            if exc.code==429:self.governor.rate_limited('solana',(method,))
            raise
        if len(raw)>16*1024*1024:raise ValueError('repair_response_bound')
        value=json.loads(raw)
        if value.get('id')!=1 or 'error' in value or 'result' not in value:raise ValueError('repair_response_unavailable')
        return value['result']

async def main_async():
    endpoint=os.environ['MM_SOLANA_READ_RPC_URL']
    path=Path(os.environ['MM_SOLANA_EVIDENCE_PLANE_DB'])
    governor=Governor(os.environ['MM_CERT_GOVERNOR_DB'])
    stop=asyncio.Event();loop=asyncio.get_running_loop()
    for sig in (signal.SIGINT,signal.SIGTERM):loop.add_signal_handler(sig,stop.set)
    await serve(path,endpoint,repair_rpc=RepairRPC(endpoint,governor),stop=stop)

if __name__=='__main__':asyncio.run(main_async())
