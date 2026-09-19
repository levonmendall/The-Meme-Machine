"""Authenticated OnFinality HTTP + WebSocket smoke.

This is read-only and deliberately fails if the configured primary is absent or if
HTTP succeeds only because Alchemy rescued it. URLs and credentials are never printed.
"""
import json
import time

from websockets.sync.client import connect

from meme_machine import pump
from meme_machine.solana_read_rpc import (
    PRIMARY_PROVIDER,
    metadata,
    new_rpc,
    primary_ws_url,
)


def main():
    meta=metadata()
    if meta.get('primary_public'):
        raise SystemExit('authenticated_onfinality_primary_not_configured')

    rpc=new_rpc(limit=40)
    genesis=rpc.call('getGenesisHash',priority=True)
    telemetry=rpc.provider_telemetry()
    if not isinstance(genesis,str) or not genesis:
        raise SystemExit('authenticated_primary_genesis_failed')
    if int(telemetry.get('failover_count',0)) != 0:
        raise SystemExit('authenticated_primary_used_rescue')
    if int((telemetry.get('provider_successes') or {}).get(PRIMARY_PROVIDER,0)) < 1:
        raise SystemExit('authenticated_primary_no_http_success')

    ws=primary_ws_url()
    with connect(ws,open_timeout=10,ping_interval=20,ping_timeout=20,
                 close_timeout=5,max_size=2_000_000,max_queue=16) as websocket:
        request={'jsonrpc':'2.0','id':1,'method':'logsSubscribe','params':[
            {'mentions':[pump.PROGRAM]},{'commitment':'finalized'}]}
        websocket.send(json.dumps(request))
        ack=json.loads(websocket.recv(timeout=10))
        if ack.get('error') or not isinstance(ack.get('result'),int):
            raise SystemExit('authenticated_primary_websocket_subscription_failed')

    report=dict(
        kind='authenticated_onfinality_primary_smoke',
        success=True,
        http_genesis_read=True,
        websocket_subscription=True,
        primary_provider=telemetry.get('primary_provider'),
        secondary_configured=telemetry.get('secondary_configured'),
        primary_http_successes=int((telemetry.get('provider_successes') or {}).get(PRIMARY_PROVIDER,0)),
        failover_count=int(telemetry.get('failover_count',0)),
        physical_http_requests=int(telemetry.get('physical_http_requests',0)),
        minimum_interval_seconds=(telemetry.get('pacing') or {}).get('minimum_interval_seconds'),
        ended=int(time.time()),
    )
    with open('onfinality-auth-smoke.json','w') as f:
        json.dump(report,f,sort_keys=True,indent=2)
    print(json.dumps(report,sort_keys=True))


if __name__=='__main__':
    main()
