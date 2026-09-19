"""Live validation of DLMM public-discovery / direct-Alchemy HTTP topology."""
import json
from pathlib import Path
import time

from meme_machine import pump
from tests import dlmm_alchemy_provider as provider

OUT=Path("dlmm-provider-5rps-validation.json")

def run():
    meta=provider.metadata()
    if meta["primary_provider"]!="alchemy_solana_mainnet_existing_secret":
        raise RuntimeError("dlmm_primary_provider_drift")
    if meta["dlmm_primary_requests_per_second"]!=5:
        raise RuntimeError("dlmm_primary_rps_drift")
    if abs(meta["dlmm_minimum_request_interval_seconds"]-0.2)>1e-12:
        raise RuntimeError("dlmm_primary_interval_drift")
    if meta["secondary_provider"] is not None or meta["secondary_configured"]:
        raise RuntimeError("dlmm_unexpected_secondary_provider")

    pacer=provider.AlchemyPacer()
    rpc=provider.new_rpc(limit=40,pacer=pacer)
    started=time.time()
    results=[]
    for _ in range(5):
        value=rpc.call("getGenesisHash",priority=True,fresh=True)
        if value!=pump.MAINNET:
            raise RuntimeError("dlmm_wrong_network")
        results.append(value)
    elapsed=time.time()-started
    telemetry=rpc.provider_telemetry()
    primary_successes=telemetry["provider_successes"].get(
        "alchemy_solana_mainnet_existing_secret",0)
    if primary_successes!=5:
        raise RuntimeError(f"dlmm_alchemy_primary_incomplete:{primary_successes}")
    if telemetry["failover_count"]!=0:
        raise RuntimeError(f"dlmm_unexpected_failover:{telemetry['failover_count']}")
    report=dict(
        kind="dlmm_provider_5rps_validation_v1",
        success=True,
        logical_reads=len(results),
        elapsed_wall_seconds=elapsed,
        provider_metadata=meta,
        provider_topology=telemetry,
        legacy_half_second_floor_removed=True,
    )
    OUT.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps(dict(
        success=True,
        logical_reads=len(results),
        elapsed_wall_seconds=elapsed,
        primary_http_requests=telemetry["provider_http_requests"].get(
            "alchemy_solana_mainnet_existing_secret",0),
        primary_successes=telemetry["provider_successes"].get(
            "alchemy_solana_mainnet_existing_secret",0),
        failovers=telemetry["failover_count"],
        secondary_successes=0,
        pacer_minimum_interval_seconds=telemetry["pacing"]["minimum_interval_seconds"],
        pacer_throttle_sleep_seconds=telemetry["pacing"]["throttle_sleep_seconds"],
    ),sort_keys=True))
    return report

if __name__=="__main__":
    run()
