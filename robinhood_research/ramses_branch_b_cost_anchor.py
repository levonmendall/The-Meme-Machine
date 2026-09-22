"""Freeze one conservative venue-wide Ramses cost anchor for Branch B certification."""
from __future__ import annotations
import json, os
from pathlib import Path

from .identity import authenticate, load
from .ramses_capture import BoundedMultiRpc
from .ramses_costs import observe_receipt_gas, current_native_cycle
from .ramses_universe import _enumerate_factory, _batched_logs, _decode_economic_logs

OUT=Path("ramses-branch-b-cost-anchor.json")

def main():
    endpoint=os.environ.get("MM_ROBINHOOD_DLMM_RPC_URL") or os.environ.get("MM_ROBINHOOD_READ_RPC_URL") or ""
    rpc=BoundedMultiRpc(
        endpoint,max_sessions=40,batch_size=8,batch_pause=.50,
        rate_retries=3,rate_cooldown=6.0,adaptive_batch_floor=2,
    )
    rpc.verify_chain()
    frontier=rpc.call("eth_getBlockByNumber",["finalized",False],scope="branch_b_cost")
    end=int(frontier["number"],16)
    factory_pin=load("ramses_factory")
    factory=factory_pin["address"]
    code=rpc.call("eth_getCode",[factory,hex(end)],scope="branch_b_cost")
    identity=authenticate("ramses_factory",factory,code)
    addresses=_enumerate_factory(
        rpc,factory,end,factory_runtime_sha256=identity["runtime_sha256"]
    )
    start=max(0,end-299)
    logs=_batched_logs(rpc,start,end,addresses)
    _histories,cost_events=_decode_economic_logs(logs,addresses)
    state={}
    observe_receipt_gas(rpc,cost_events,state)
    native,meta=current_native_cycle(rpc,state)
    if native is None:
        raise RuntimeError("branch_b_cost_anchor_unavailable")
    body=dict(
        kind="ramses_branch_b_cost_anchor_v1",
        frozen=True,
        research_only=True,
        finalized_block=end,
        finalized_hash=frontier["hash"],
        finalized_timestamp=int(frontier["timestamp"],16),
        lookback_start_block=start,
        factory_pool_count=len(addresses),
        economic_logs=len(logs),
        economic_transactions=len(state.get("transactions") or {}),
        native_costs={k:int(v) for k,v in native.items()},
        native_cycle_cost_raw=sum(int(v) for v in native.values()),
        model=meta,
        provider=rpc.telemetry(),
    )
    OUT.write_text(json.dumps(body,indent=2,sort_keys=True))
    print(json.dumps({k:body[k] for k in ("kind","finalized_block","economic_transactions","native_cycle_cost_raw")},sort_keys=True))

if __name__=="__main__":
    main()
