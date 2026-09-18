"""One bounded current JUP-SOL host-fee live certification proof."""
from __future__ import annotations
import argparse, json, os, time
from pathlib import Path

from meme_machine import dlmm, pump
from meme_machine.postgrad import PoolScanRPC
from meme_machine.provider import Unavailable
from tests import dlmm_dense_acquisition as dense
from tests import dlmm_boundary_acquisition as boundary
from tests import dlmm_strategy_high_activity_batched as base

POOL='C8Gr6AUuq9hEdSYJzoEpNcdjpojPZwqG5MtQbeouNNwg'
OUT=Path('dlmm-live-host-fee-proof.json')


def run(window_seconds=12):
    if not 5 <= window_seconds <= 12:
        raise ValueError('dlmm_live_host_fee_window_bound')
    url=os.environ.get('MM_SOLANA_READ_RPC_URL','').strip()
    if not url:
        raise SystemExit('MM_SOLANA_READ_RPC_URL missing')
    rpc=PoolScanRPC(url,limit=240)
    adapter=dlmm.Adapter(rpc)
    base._capture_chunk=boundary.capture_chunk
    base.ENDPOINT_DIAGNOSTICS=boundary.ENDPOINT_DIAGNOSTICS
    boundary.ENDPOINT_DIAGNOSTICS.clear()
    dense.ENDPOINT_CAPTURE_HIGH_WATER.clear()

    snap=adapter.snapshot(POOL,int(time.time()),True,fresh=True)
    state=dlmm.validate(snap,snap['available_time'],'real')
    if dlmm.WSOL not in (state['x'],state['y']):
        raise Unavailable('dlmm_live_host_fee_not_sol_pair')
    states={POOL:state}
    advanced,tapes,errors=dense.pressure_advance(
        adapter,states,window_seconds,allow_snapshot_reset=True)
    tape=tapes.get(POOL)
    events=[] if tape is None else list(tape.events)
    hosted=[event for event in events
            if int((event.get('observed') or {}).get('host_fee',0))>0]
    endpoint=[item for item in boundary.ENDPOINT_DIAGNOSTICS
              if item.get('pool')==POOL]
    checks=dict(
        allocation_disabled=True,
        verified_tape=tape is not None,
        no_interval_errors=not errors,
        host_fee_exercised=bool(hosted),
        all_endpoint_captures_complete=bool(endpoint) and all(
            item.get('capture_completed') is True for item in endpoint),
        finalized_events=bool(events) and all(
            event.get('commitment')=='finalized' and event.get('kind')=='real'
            for event in events),
    )
    report=dict(
        kind='dlmm_live_jup_host_fee_certification_v1',
        allocation_authority=False,
        prospective_allocation_enabled=False,
        pool=POOL,
        start_slot=state['slot'],
        end_slot=None if tape is None else tape.terminal['slot'],
        window_seconds=window_seconds,
        checks=checks,
        host_fee_event_count=len(hosted),
        host_fee_events=[dict(
            signature=event.get('signature'),cursor=event.get('cursor'),
            instruction=event.get('instruction'),amount=event.get('amount'),
            host_fee=(event.get('observed') or {}).get('host_fee'),
            protocol_fee=(event.get('observed') or {}).get('protocol_fee'),
            fee=(event.get('observed') or {}).get('fee'),
            start=(event.get('observed') or {}).get('start'),
            end=(event.get('observed') or {}).get('end'),
        ) for event in hosted],
        reconstructed_swap_count=len(events),
        interval_errors=errors,
        endpoint_snapshot_diagnostics=endpoint,
        rpc_calls=rpc.calls,rpc_http_requests=rpc.http_requests,
        rpc_failures=rpc.failures,rpc_retries=rpc.retries,
        provider_failure_kinds=rpc.failure_kinds,
        provider_failure_methods=rpc.failure_methods,
        rpc_batch_fallbacks=rpc.batch_fallbacks,
        rpc_batch_fallback_items=rpc.batch_fallback_items,
    )
    OUT.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps(dict(
        host_fee_events=len(hosted),reconstructed_swaps=len(events),
        interval_errors=len(errors),rpc_calls=rpc.calls,
        rpc_failures=rpc.failures,rpc_retries=rpc.retries),sort_keys=True))
    failed=[name for name,ok in checks.items() if not ok]
    if failed:
        raise SystemExit('DLMM_LIVE_HOST_FEE_PROOF_FAILED:'+','.join(failed))
    print('DLMM_LIVE_HOST_FEE_PROOF_PASSED')
    return report


def main():
    p=argparse.ArgumentParser();p.add_argument('--window-seconds',type=int,default=12)
    a=p.parse_args();run(a.window_seconds)

if __name__=='__main__':
    main()
