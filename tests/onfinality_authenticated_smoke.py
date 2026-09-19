"""Diagnostic-only authenticated OnFinality HTTP + WebSocket smoke.

OnFinality is no longer part of Pump HTTP evidence acquisition. This file remains only
for isolated provider diagnostics and never exercises the production Pump HTTP path.
"""
import json
import time
import urllib.request

from websockets.sync.client import connect

from meme_machine import pump
from meme_machine.solana_read_rpc import onfinality_rpc_url, primary_ws_url


def main():
    url=onfinality_rpc_url(required=True)
    body=json.dumps({
        'jsonrpc':'2.0','id':1,'method':'getGenesisHash','params':[]
    }).encode()
    req=urllib.request.Request(url,body,{'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=8) as response:
        payload=json.loads(response.read(200_000))
    genesis=payload.get('result') if isinstance(payload,dict) else None
    if not isinstance(genesis,str) or not genesis:
        raise SystemExit('authenticated_onfinality_http_failed')

    ws=primary_ws_url()
    with connect(ws,open_timeout=10,ping_interval=20,ping_timeout=20,
                 close_timeout=5,max_size=2_000_000,max_queue=16) as websocket:
        request={'jsonrpc':'2.0','id':1,'method':'logsSubscribe','params':[
            {'mentions':[pump.PROGRAM]},{'commitment':'finalized'}]}
        websocket.send(json.dumps(request))
        ack=json.loads(websocket.recv(timeout=10))
        if ack.get('error') or not isinstance(ack.get('result'),int):
            raise SystemExit('authenticated_onfinality_websocket_subscription_failed')

    report=dict(
        kind='authenticated_onfinality_diagnostic_smoke',
        success=True,
        pump_http_evidence_role=False,
        http_genesis_read=True,
        websocket_subscription=True,
        ended=int(time.time()),
    )
    with open('onfinality-auth-smoke.json','w') as f:
        json.dump(report,f,sort_keys=True,indent=2)
    print(json.dumps(report,sort_keys=True))


if __name__=='__main__':
    main()
