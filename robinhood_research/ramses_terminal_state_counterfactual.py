"""Fast exact-economic Ramses quiet-entry counterfactual from terminal state.

This uses the existing non-impact paper overlay unchanged. Entry proposal shares are
constructed from exact archive state; exit inventory comes from exact archive bin
state; residual inventory is unwound with exact on-chain getSwapOut. A separate
bit-for-bit equivalence proof against 12 prior full-replay variants is required
before this path is accepted.
"""
from __future__ import annotations
import json, os
from pathlib import Path

from . import BoundaryError
from .abi import calldata
from .identity import load
from .ramses import (
    authenticate_pool, freeze_proposals, paper_outcome, paper_position,
    price, quote_value, state, values,
)
from .ramses_capture import BoundedMultiRpc, _first_finalized_block_at_or_after
from .ramses_all_pool_lifecycle import _snapshot, _unwind
from .ramses_historical_quiet_mint_counterfactual import (
    INDEX, MINT_FIELDS, POOL_FIELDS, USDG, WIDTHS, HOLDS, DEPTH_BPS,
    page, swap_times, select_candidates, one_freeze,
)

OUT=Path("ramses-quiet-mint-counterfactual.json")
CANDIDATE_INDEX_ENV="RAMSES_QUIET_CANDIDATE_INDEX"

def main():
    import gzip
    with gzip.open(INDEX,"rt",encoding="utf-8") as fh:index=json.load(fh)
    by_swaps,start,end=swap_times(index)
    candidates,selection=select_candidates(
        page("DLMMMint",MINT_FIELDS),page("DLMMPool",POOL_FIELDS),
        by_swaps,start,end,
    )
    if len(candidates)<3: raise RuntimeError("terminal_counterfactual_candidate_shortfall")
    raw=str(os.environ.get(CANDIDATE_INDEX_ENV,"") or "").strip()
    if raw:
        try: idx=int(raw)
        except ValueError: raise RuntimeError("terminal_counterfactual_candidate_index") from None
        if idx<0 or idx>=len(candidates): raise RuntimeError("terminal_counterfactual_candidate_index")
        run_candidates=[candidates[idx]]
        selection=dict(selection,shard_candidate_index=idx,shard_selection_hash=candidates[idx]["selection_hash"])
    else:
        run_candidates=list(candidates)

    endpoint=os.environ.get("MM_ROBINHOOD_DLMM_RPC_URL") or os.environ.get("MM_ROBINHOOD_READ_RPC_URL") or ""
    rpc=BoundedMultiRpc(
        endpoint,max_sessions=120,batch_size=16,batch_pause=.20,
        rate_retries=3,rate_cooldown=4.0,adaptive_batch_floor=2,
    )
    rpc.verify_chain()
    frontier=rpc.call("eth_getBlockByNumber",["finalized",False],scope="terminal_counterfactual")
    factory=load("ramses_factory")["address"]
    results=[]

    for cand in run_candidates:
        pool=cand["pool"].lower()
        receipt=rpc.call("eth_getTransactionReceipt",[cand["transaction_hash"]],scope="terminal_counterfactual")
        if not receipt or int(receipt.get("status","0x0"),16)!=1:
            results.append(dict(candidate=cand,boundary="mint_receipt_unavailable"));continue
        mint_block=int(receipt["blockNumber"],16);entry=mint_block+1
        try:
            header=rpc.call("eth_getBlockByNumber",[hex(entry),False],scope="terminal_counterfactual")
            if not header or int(header["number"],16)!=entry:
                raise BoundaryError("terminal_counterfactual_entry_header")
            entry_at=int(header["timestamp"],16)
            member,code,active_raw,step_raw=rpc.batch([
                ("eth_call",[dict(to=factory,data=calldata("isPool(address)",pool)),hex(entry)]),
                ("eth_getCode",[pool,hex(entry)]),
                ("eth_call",[dict(to=pool,data=calldata("getActiveId()")),hex(entry)]),
                ("eth_call",[dict(to=pool,data=calldata("getBinStep()")),hex(entry)]),
            ],scope="terminal_counterfactual")
            if int(member,16)!=1: raise BoundaryError("terminal_counterfactual_membership")
            auth=authenticate_pool(code,factory_member=True)
            active=values(active_raw)[0];step=values(step_raw)[0]
            if step!=auth["bin_step"]: raise BoundaryError("terminal_counterfactual_step")
            quote_side="x" if auth["token_x"].lower()==USDG else "y" if auth["token_y"].lower()==USDG else None
            if quote_side is None: raise BoundaryError("terminal_counterfactual_non_usdg")
            bins=list(range(active-max(WIDTHS),active+max(WIDTHS)+1))
            pre=state(_snapshot(rpc,pool,entry,bins,initial=True))
            active_liq=quote_value(pre["bins"][active]["reserves"],price(active,step),quote_side)
            capital=max(1,active_liq*DEPTH_BPS//10000)
            freeze=freeze_proposals(
                pre,capital,quote_side=quote_side,entry_timestamp=entry_at,
                prehistory=None,gas_costs=None,widths=WIDTHS,
            )
            by_width={int(p["width"]):p for p in freeze["proposals"]}
            crow=dict(
                candidate=cand,mint_block=mint_block,entry_block=entry,
                entry_timestamp=entry_at,active_bin=active,bin_step_bps=step,
                quote_side=quote_side,active_liquidity_quote_raw=active_liq,
                capital_quote_raw=capital,depth_fraction_bps=DEPTH_BPS,holds=[],
            )
            for hold in HOLDS:
                selected,previous,reads=_first_finalized_block_at_or_after(
                    rpc,entry,frontier,entry_at+int(hold)
                )
                exit_block=int(selected["number"],16);exit_at=int(selected["timestamp"],16)
                terminal=state(_snapshot(rpc,pool,exit_block,bins,initial=False))
                if terminal["step"]!=step: raise BoundaryError("terminal_counterfactual_terminal_step")
                hrow=dict(
                    requested_hold_seconds=int(hold),exit_block=exit_block,
                    exit_timestamp=exit_at,actual_hold_seconds=exit_at-entry_at,
                    binary_search_reads=reads,
                    terminal_state_source="archive_rpc_snapshot",
                    variants=[],
                )
                for width in WIDTHS:
                    proposal=by_width[int(width)]
                    fr=one_freeze(proposal);decision={"freeze":fr}
                    try:
                        pos=paper_position(fr,0)
                        unwind=_unwind(rpc,pool,decision,{"terminal_state":terminal},exit_block)
                        outcome=paper_outcome(
                            pos,terminal,unwind=unwind,costs={},lp_fees_captured=None
                        )
                        employed=int(proposal["capital_employed"])
                        hrow["variants"].append(dict(
                            half_width_bins=int(width),total_bins=len(proposal["bins"]),
                            capital_quote_raw=employed,
                            terminal_equality_equivalent=True,
                            fee_capture_quote=None,
                            inventory_effect=outcome.get("inventory_effect"),
                            executable_slippage=outcome.get("executable_slippage"),
                            gross_result=outcome.get("gross_result"),
                            gross_return_bps=(None if outcome.get("gross_result") is None or employed<=0
                                              else int(outcome["gross_result"])*10000//employed),
                            unresolved_inventory=outcome.get("unresolved_inventory"),
                        ))
                    except BoundaryError as exc:
                        hrow["variants"].append(dict(half_width_bins=int(width),boundary=str(exc)))
                crow["holds"].append(hrow)
            results.append(crow)
        except BoundaryError as exc:
            results.append(dict(candidate=cand,boundary=str(exc)))

    resolved=[
        v for r in results for h in r.get("holds",[]) for v in h.get("variants",[])
        if v.get("gross_return_bps") is not None
    ]
    vals=sorted(v["gross_return_bps"] for v in resolved)
    body=dict(
        kind="ramses_dlmm_quiet_mint_counterfactual_v1",
        research_only=True,existing_strategy_policy_used=False,
        holdout_outcomes_read=False,
        terminal_state_counterfactual=True,
        equivalence_requirement="ramses_terminal_state_equivalence_v1 exact_equivalence=true",
        selection=selection,candidates=results,
        checkpoint=dict(completed_candidates=len(results),target_candidates=len(run_candidates),complete=len(results)==len(run_candidates)),
        summary=dict(
            selected_candidates=len(run_candidates),resolved_variants=len(resolved),
            positive_variants=sum(v["gross_return_bps"]>0 for v in resolved),
            median_gross_return_bps=(vals[len(vals)//2] if vals else None),
        ),
        provider=rpc.telemetry(),
    )
    OUT.write_text(json.dumps(body,indent=2,sort_keys=True))
    print(json.dumps({"status":"complete","summary":body["summary"],"selection":selection},sort_keys=True))

if __name__=="__main__": main()
