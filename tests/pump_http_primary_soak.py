"""Canonical sustained Pump HTTP provider soak at the validated 2-RPS cadence.

Uses the production new_rpc() topology with Alchemy configured as rescue. Success
requires OnFinality to serve every uncached request directly: zero primary failures,
zero failovers, zero Alchemy transports.
"""
from __future__ import annotations
import json
import urllib.request
from pathlib import Path

from meme_machine.solana_read_rpc import (
    AUTHENTICATED_PRIMARY_ENV_NAME,
    PRIMARY_PROVIDER,
    SECONDARY_PROVIDER,
    new_rpc,
    primary_rpc_url,
)

OUT=Path("pump-http-primary-soak.json")
READS=30


def _raw_finalized_slot(url):
    body=json.dumps({
        "jsonrpc":"2.0","id":1,"method":"getSlot",
        "params":[{"commitment":"finalized"}],
    }).encode()
    req=urllib.request.Request(url,body,{"Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=8) as response:
        payload=json.loads(response.read(200_000))
    slot=payload.get("result") if isinstance(payload,dict) else None
    if not isinstance(slot,int) or slot<READS+20:
        raise RuntimeError("finalized_slot_unavailable")
    return slot


def main():
    url=primary_rpc_url()
    if "onfinality.io" not in url or url.rstrip("/").endswith("/public"):
        raise SystemExit("authenticated_onfinality_required")

    slot=_raw_finalized_slot(url)
    rpc=new_rpc(limit=120)
    results=[]
    for i in range(READS):
        target=slot-20-i
        value=rpc.call("getBlockTime",[target],priority=True)
        results.append(dict(slot=target,block_time=value))

    t=rpc.provider_telemetry()
    primary_attempts=int((t.get("provider_http_requests") or {}).get(PRIMARY_PROVIDER,0))
    primary_successes=int((t.get("provider_successes") or {}).get(PRIMARY_PROVIDER,0))
    secondary_attempts=int((t.get("provider_http_requests") or {}).get(SECONDARY_PROVIDER,0))
    failovers=int(t.get("failover_count") or 0)
    primary_failures=int((t.get("provider_failures") or {}).get(PRIMARY_PROVIDER,0))

    success=bool(
        len(results)==READS
        and primary_attempts==READS
        and primary_successes==READS
        and primary_failures==0
        and failovers==0
        and secondary_attempts==0
        and float((t.get("pacing") or {}).get("minimum_interval_seconds"))==0.5
    )
    report=dict(
        kind="pump_http_primary_soak_v1",
        success=success,
        authenticated_primary=True,
        requested_reads=READS,
        completed_reads=len(results),
        primary_attempts=primary_attempts,
        primary_successes=primary_successes,
        primary_failures=primary_failures,
        failovers=failovers,
        secondary_attempts=secondary_attempts,
        minimum_interval_seconds=(t.get("pacing") or {}).get("minimum_interval_seconds"),
        topology=t,
        signing=False,submission=False,
    )
    OUT.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps({
        "success":success,"reads":len(results),
        "primary_successes":primary_successes,
        "primary_failures":primary_failures,
        "failovers":failovers,"secondary_attempts":secondary_attempts,
        "minimum_interval_seconds":report["minimum_interval_seconds"],
    },sort_keys=True))
    if not success:
        raise SystemExit(1)


if __name__=="__main__":
    main()
