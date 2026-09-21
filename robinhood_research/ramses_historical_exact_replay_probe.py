"""Exact archive-RPC replay probe for blank-slate Ramses historical candidates."""
from __future__ import annotations
import hashlib,json,os
from pathlib import Path

from . import BoundaryError
from .abi import calldata
from .identity import load
from .ramses import (
    authenticate_pool, freeze_proposals, paper_fee_capture, paper_outcome,
    paper_position, quote_value, price, state, values
)
from .ramses_capture import BoundedMultiRpc, _first_finalized_block_at_or_after
from .ramses_all_pool_lifecycle import _snapshot,_build_segment_replay,_unwind

NOMS=Path("ramses-historical-strategy-nominations.json")
OUT=Path("ramses-historical-exact-replay-probe.json")
USDG="0x5fc5360d0400a0fd4f2af552add042d716f1d168"
WIDTHS=(1,2,3,5)
HOLD=300
DEPTH_BPS=50  # 0.5% of active-bin quote liquidity; diagnostic only.

def one_freeze(proposal):
    row=dict(frozen=True,allocation_authority=False,hurdle_bps=None,proposals=[proposal])
    row["proposal_hash"]=hashlib.sha256(
        json.dumps(row["proposals"],sort_keys=True,separators=(",",":")).encode()
    ).hexdigest()
    return row

def pick(rows):
    out=[];seen=set()
    for r in rows:
        if r.get("cohort")!="two_way_opportunity" or r.get("split")!="derivation" or r.get("signal_seconds")!=300:
            continue
        if not str(r.get("symbol") or "").endswith("/USDG"):
            continue
        p=r["pool"]
        if p in seen:continue
        seen.add(p);out.append(r)
        if len(out)>=3:break
    return out

def main():
    noms=json.loads(NOMS.read_text())
    candidates=pick(noms.get("nominations") or [])
    if len(candidates)<2:raise RuntimeError("ramses_exact_probe_candidate_shortfall")
    endpoint=os.environ.get("MM_ROBINHOOD_DLMM_RPC_URL") or os.environ.get("MM_ROBINHOOD_READ_RPC_URL") or ""
    rpc=BoundedMultiRpc(endpoint,max_sessions=80,batch_size=12,batch_pause=.25,
                        rate_retries=3,rate_cooldown=4.0,adaptive_batch_floor=2)
    rpc.verify_chain()
    frontier=rpc.call("eth_getBlockByNumber",["finalized",False],scope="exact_probe")
    factory=load("ramses_factory")["address"]
    results=[]
    for cand in candidates:
        pool=cand["pool"].lower();entry=int(cand["entry_block"]);entry_at=int(cand["entry_timestamp"])
        member,code,active_raw,step_raw=rpc.batch([
          ("eth_call",[dict(to=factory,data=calldata("isPool(address)",pool)),hex(entry)]),
          ("eth_getCode",[pool,hex(entry)]),
          ("eth_call",[dict(to=pool,data=calldata("getActiveId()")),hex(entry)]),
          ("eth_call",[dict(to=pool,data=calldata("getBinStep()")),hex(entry)]),
        ],scope="exact_probe")
        if int(member,16)!=1:raise BoundaryError("exact_probe_not_factory_member")
        auth=authenticate_pool(code,factory_member=True)
        active=values(active_raw)[0];step=values(step_raw)[0]
        if step!=auth["bin_step"]:raise BoundaryError("exact_probe_step_mismatch")
        bins=list(range(active-max(WIDTHS),active+max(WIDTHS)+1))
        raw=_snapshot(rpc,pool,entry,bins,initial=True)
        pre=state(raw)
        token_y="0x"+raw["values"]["getTokenY()"][-40:]
        if token_y.lower()!=USDG:raise BoundaryError("exact_probe_non_usdg_quote")
        active_liq=quote_value(pre["bins"][active]["reserves"],price(active,step),"y")
        capital=max(1,active_liq*DEPTH_BPS//10000)
        freeze=freeze_proposals(pre,capital,quote_side="y",entry_timestamp=entry_at,
                                prehistory=None,gas_costs=None,widths=WIDTHS)
        selected,previous,reads=_first_finalized_block_at_or_after(
            rpc,entry,frontier,entry_at+HOLD
        )
        end=int(selected["number"],16);end_at=int(selected["timestamp"],16)
        if end_at<entry_at+HOLD:raise BoundaryError("exact_probe_horizon")
        variants=[]
        for proposal in freeze["proposals"]:
            fr=one_freeze(proposal);decision={"freeze":fr}
            try:
                capture,replayed=_build_segment_replay(rpc,pool,decision,entry,end)
                unwind=_unwind(rpc,pool,decision,replayed,end)
                pos=paper_position(fr,0)
                fees=paper_fee_capture(pos,replayed)
                outcome=paper_outcome(pos,replayed["terminal_state"],unwind=unwind,costs={},
                                      lp_fees_captured=fees)
                variants.append(dict(
                    width=proposal["width"],bins=len(proposal["bins"]),
                    capital_quote_raw=proposal["capital_employed"],
                    terminal_equality=replayed["terminal_equality"],
                    event_count=replayed.get("events"),transaction_count=replayed.get("transactions"),
                    fee_capture_quote=fees["quote_value"],
                    inventory_effect=outcome["inventory_effect"],
                    executable_slippage=outcome["executable_slippage"],
                    gross_result=outcome["gross_result"],
                    gross_return_bps=(None if outcome["gross_result"] is None else
                                      outcome["gross_result"]*10000//proposal["capital_employed"]),
                    unresolved_inventory=outcome["unresolved_inventory"],
                ))
            except BoundaryError as exc:
                variants.append(dict(width=proposal["width"],boundary=str(exc)))
        results.append(dict(
            pool=pool,symbol=cand.get("symbol"),entry_block=entry,entry_timestamp=entry_at,
            end_block=end,end_timestamp=end_at,hold_seconds=end_at-entry_at,
            signal={k:cand.get(k) for k in ("swap_count","volume_usd","lp_fees_usd","lp_fee_bps",
                                            "two_way_share","chop_ratio","net_bin_displacement",
                                            "fee_percentile","volume_percentile")},
            active_bin=active,bin_step_bps=step,active_liquidity_quote_raw=active_liq,
            depth_fraction_bps=DEPTH_BPS,capital_quote_raw=capital,
            variants=variants,binary_search_reads=reads,
        ))
    body=dict(kind="ramses_dlmm_historical_exact_replay_probe_v1",research_only=True,
              existing_strategy_policy_used=False,hold_seconds=HOLD,
              depth_fraction_bps=DEPTH_BPS,candidates=results,provider=rpc.telemetry())
    OUT.write_text(json.dumps(body,indent=2,sort_keys=True))
    print(json.dumps({"status":"complete","candidates":len(results),
      "resolved":sum(1 for r in results for v in r["variants"] if v.get("gross_result") is not None),
      "boundaries":sum(1 for r in results for v in r["variants"] if v.get("boundary"))},sort_keys=True))

if __name__=="__main__":main()
