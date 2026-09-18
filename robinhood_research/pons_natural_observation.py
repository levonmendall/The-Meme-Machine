"""One bounded natural Pons V2 observation with unchanged five-second freshness.

Selection is prospective and outcome-blind: after startup, take the first current
CurveBuy/CurveSell whose deployed curve bytecode and factory record authenticate.
The entry observation uses a confirmed block in the existing Finality ledger and
must still satisfy the repository's five-second state gate after all quote inputs
have been read.  No order/reservation/allocation authority exists here.

The observer then waits a fixed 60 seconds, records subsequent authentic curve events,
rechecks canonical block identity, and promotes the original dependency to finalized
only if the finalized frontier has actually reached it with the same hash.
"""
from dataclasses import asdict
import json
import os
from pathlib import Path
import tempfile
import time

from . import BoundaryError, CHAIN_ID
from .abi import calldata, decode_event, topic, words, scalar
from .evidence import Stamp, Store
from .finality import Finality
from .identity import load
from .pons import (
    CurveState, authenticate_curve, curve_abi, factory_record, raw_event,
)
from .provider import Rpc

REPORT=Path(os.environ.get("MM_ROBINHOOD_PONS_NATURAL_REPORT","robinhood-pons-natural-report.json"))
OBSERVE_SECONDS=60
DISCOVERY_SECONDS=90
POLL_SECONDS=1.0
RESEARCH_BUY_WEI=10**16
RESEARCH_RECIPIENT="0x1111111111111111111111111111111111111111"
ZERO="0x0000000000000000000000000000000000000000"


def _one_word(raw,typ="uint256"):
    data=words(raw)
    if len(data)!=1:
        raise BoundaryError("natural_call_shape")
    return scalar(typ,data[0])


def _two_uints(raw):
    data=words(raw)
    if len(data)!=2:
        raise BoundaryError("natural_reserve_shape")
    return tuple(scalar("uint256",x) for x in data)


def _call(rpc,address,sig,args,block,report):
    raw=rpc.call(
        "eth_call",
        [dict(to=address,data=calldata(sig,*args)),hex(block)],
        scope="pons_natural",
    )
    report["reads"].append(dict(
        address=address,signature=sig,args=list(args),block=block,
        value=raw,observed_at=time.time(),
    ))
    return raw


def _latest_header(rpc):
    return rpc.call("eth_getBlockByNumber",["latest",False],scope="pons_natural")


def _current_curve_events(rpc,start,end):
    if end<start:
        return []
    rows=[]
    signatures=[
        topic("CurveBuy(address,address,uint256,uint256,uint256,uint256)"),
        topic("CurveSell(address,address,uint256,uint256,uint256,uint256)"),
    ]
    # Provider already proved small-range log reads. Never widen past 10 blocks.
    for first in range(start,end+1,10):
        rows.extend(rpc.call("eth_getLogs",[dict(
            fromBlock=hex(first),toBlock=hex(min(end,first+9)),
            topics=[signatures],
        )],scope="pons_natural"))
        if len(rows)>1000:
            raise BoundaryError("natural_event_capacity")
    rows.sort(key=lambda e:(int(e["blockNumber"],16),int(e["transactionIndex"],16),int(e["logIndex"],16)))
    return rows


def _curve_state(rpc,curve,block,auth,report):
    quote_reserve,token_reserve=_two_uints(_call(rpc,curve,"getReserves()",(),block,report))
    real_quote=_one_word(_call(rpc,curve,"realQuoteReserve()",(),block,report))
    reserved=_one_word(_call(rpc,curve,"reservedTokens()",(),block,report))
    graduated=_one_word(_call(rpc,curve,"graduated()",(),block,report),"bool")
    header=rpc.call("eth_getBlockByNumber",[hex(block),False],scope="pons_natural")
    timestamp=int(header["timestamp"],16)
    # Sell arithmetic does not use snipe parameters.  Current buy execution is quoted
    # by eth_call against the actual deployed contract below rather than recreating
    # the snipe schedule from stale local inputs.
    return CurveState(
        quote_reserve=quote_reserve,token_reserve=token_reserve,real_quote=real_quote,
        reserved_tokens=reserved,fee_bps=int(auth["immutables"]["feeBps"]),
        creator_tax_bps=int(auth["immutables"]["creatorTaxBps"]),graduated=bool(graduated),
        launched_at=timestamp,snipe_start_bps=0,snipe_seconds=1,timestamp=timestamp,
    ),header


def _quote_native_buy(rpc,curve,block,record,state,report):
    if record["pairToken"].lower()!=ZERO:
        raise BoundaryError("natural_non_native_quote_not_supported")
    current_snipe=_one_word(_call(
        rpc,curve,"currentSnipeTaxBps(address)",(RESEARCH_RECIPIENT,),block,report
    ))
    quote=state.buy_with_snipe(RESEARCH_BUY_WEI,current_snipe)
    return dict(
        quote_in=RESEARCH_BUY_WEI,tokens_out=quote["tokens_out"],
        spent=quote["spent"],refund=quote["refund"],fee=quote["fee"],
        creator_tax=quote["creator_tax"],snipe_tax=quote["snipe_tax"],
        ready_to_graduate=quote["ready_to_graduate"],
        current_snipe_bps=current_snipe,recipient=RESEARCH_RECIPIENT,
        execution="source_verified_arithmetic_plus_onchain_current_snipe",
    )


def _authenticate_candidate(rpc,event,report):
    block=int(event["blockNumber"],16)
    header=rpc.call("eth_getBlockByNumber",[hex(block),False],scope="pons_natural")
    observed=int(time.time())
    event_at=int(header["timestamp"],16)
    if observed-event_at>5:
        raise BoundaryError("stale_state")
    receipt=rpc.receipt(event["transactionHash"],event["blockHash"],scope="pons_natural")
    curve=event["address"].lower()
    decoded=raw_event(
        curve_abi(),event,address=curve,receipt=receipt,header=header,
        observed_at=observed,confirmation="confirmed",
    )
    token_raw=_call(rpc,curve,"token()",(),block,report)
    token=_one_word(token_raw,"address")
    factory=load("pons_v2_factory")["address"].lower()
    raw_record=_call(
        rpc,factory,"getLaunchedToken(address)",(token,),block,report
    )
    record=factory_record(raw_record,"pons_v2_factory")
    code=rpc.call("eth_getCode",[curve,hex(block)],scope="pons_natural")
    auth=authenticate_curve(curve,code,factory_record=record)
    state,_=_curve_state(rpc,curve,block,auth,report)
    quote=_quote_native_buy(rpc,curve,block,record,state,report)

    # The entire executable observation, not merely the first log read, must remain
    # inside the unchanged five-second gate.
    quote_at=int(time.time())
    stamp=Stamp(
        CHAIN_ID,block,header["hash"],event_at,observed,"confirmed","natural",
    )
    if quote_at-event_at>5:
        raise BoundaryError("stale_state")

    return dict(
        curve=curve,token=token,block=block,header=header,receipt=receipt,
        source_event=event,decoded_event=decoded,record=record,auth=auth,
        state=state,quote=quote,stamp=stamp,quote_at=quote_at,
        freshness_seconds=quote_at-event_at,
    )


def _final_mark(rpc,candidate,block,report):
    try:
        state,_=_curve_state(rpc,candidate["curve"],block,candidate["auth"],report)
        if state.graduated:
            return dict(available=False,reason="graduated_requires_v4_mark")
        sell=state.sell(candidate["quote"]["tokens_out"])
        return dict(
            available=True,quote_out=sell["quote_out"],gross_quote=sell["gross_quote"],
            fee=sell["fee"],creator_tax=sell["creator_tax"],
            gross_return_bps=(sell["quote_out"]-candidate["quote"]["quote_in"])*10000
                             // candidate["quote"]["quote_in"],
            gas_unmodeled=True,after_cost_return=None,
        )
    except BoundaryError as exc:
        return dict(available=False,reason=str(exc),after_cost_return=None)


def run(endpoint):
    rpc=Rpc(endpoint,limit=180,per_scope=170,retries=0)
    report=dict(
        kind="natural_pons_v2_bounded_observation",
        research_only=True,allocation_authority=False,paper_orders=0,
        selection_rule="first_current_authenticated_pons_v2_curve_trade_after_start",
        outcome_used_for_selection=False,freshness_gate_seconds=5,
        discovery_seconds=DISCOVERY_SECONDS,followup_seconds=OBSERVE_SECONDS,
        research_buy_wei=RESEARCH_BUY_WEI,reads=[],events=[],started_at=time.time(),
    )
    candidate=None
    try:
        rpc.verify_chain()
        start_header=_latest_header(rpc)
        cursor=int(start_header["number"],16)
        report["start_block"]=cursor
        deadline=time.monotonic()+DISCOVERY_SECONDS
        attempted_curves=set()

        while time.monotonic()<deadline and candidate is None:
            latest=_latest_header(rpc)
            end=int(latest["number"],16)
            start=max(cursor+1,end-9)
            if end>=start:
                for event in _current_curve_events(rpc,start,end):
                    curve=event.get("address","").lower()
                    if curve in attempted_curves:
                        continue
                    attempted_curves.add(curve)
                    try:
                        item=_authenticate_candidate(rpc,event,report)
                        with tempfile.TemporaryDirectory() as td:
                            store=Store(td+"/natural.sqlite",max_records=128)
                            ledger=Finality(store,scope="pons-natural",max_blocks=16)
                            ledger.observe(item["stamp"],item["header"]["parentHash"])
                            item["stamp"].check(item["quote_at"],5,finality_ledger=ledger)
                            dependency="candidate:"+item["token"]+":"+item["source_event"]["transactionHash"]
                            ledger.bind(dependency,[item["stamp"]],asof=item["quote_at"])
                            item["dependency_status_at_quote"]=ledger.check_dependency(dependency)
                            store.close()
                        candidate=item
                        break
                    except BoundaryError as exc:
                        report.setdefault("candidate_rejections",[]).append(dict(
                            address=event.get("address"),block=event.get("blockNumber"),
                            reason=str(exc),
                        ))
                        if len(report["candidate_rejections"])>50:
                            raise BoundaryError("natural_rejection_capacity")
                cursor=end
            if candidate is None:
                time.sleep(POLL_SECONDS)

        if candidate is None:
            raise BoundaryError("no_current_authenticated_pons_candidate")

        report["candidate"]={
            key:value for key,value in candidate.items()
            if key not in ("stamp","state")
        }
        report["candidate"]["stamp"]=asdict(candidate["stamp"])
        report["candidate"]["state"]=asdict(candidate["state"])

        # Outcome clock starts only after the candidate/quote is frozen.
        time.sleep(OBSERVE_SECONDS)
        final_header=_latest_header(rpc)
        final_block=int(final_header["number"],16)
        follow=_current_curve_events(rpc,candidate["block"],final_block)
        authentic=[]
        for event in follow:
            if event["address"].lower()!=candidate["curve"]:
                continue
            block=int(event["blockNumber"],16)
            header=rpc.call("eth_getBlockByNumber",[hex(block),False],scope="pons_natural")
            receipt=rpc.receipt(event["transactionHash"],event["blockHash"],scope="pons_natural")
            authentic.append(raw_event(
                curve_abi(),event,address=candidate["curve"],receipt=receipt,header=header,
                observed_at=int(time.time()),confirmation="confirmed",
            ))
            if len(authentic)>200:
                raise BoundaryError("natural_followup_capacity")
        report["events"]=authentic

        # Re-fetch the original height. A replacement block invalidates the research
        # observation rather than being silently substituted.
        canonical=rpc.call(
            "eth_getBlockByNumber",[hex(candidate["block"]),False],scope="pons_natural"
        )
        now=int(time.time())
        if canonical["hash"]!=candidate["stamp"].block_hash:
            report["dependency_status"]="invalidated"
            raise BoundaryError("confirmed_candidate_reorged")

        finalized=rpc.call("eth_getBlockByNumber",["finalized",False],scope="pons_natural")
        finalized_number=int(finalized["number"],16)
        report["finalized_frontier"]={
            k:finalized[k] for k in ("number","hash","timestamp","parentHash")
        }
        report["dependency_status"]=(
            "finalized" if finalized_number>=candidate["block"] else "confirmed"
        )
        report["finalization_preserves_original_observed_at"]=candidate["stamp"].observed_at
        report["outcome"]={
            "seconds":OBSERVE_SECONDS,
            "end_block":final_block,
            "authenticated_trade_events":len(authentic),
            "mark":_final_mark(rpc,candidate,final_block,report),
            "graduated_during_followup":any(
                row["decoded"]["name"]=="CurveCompleted" for row in authentic
            ),
            "after_cost_profitability_established":False,
        }
    except BoundaryError as exc:
        report["boundary"]=str(exc)
    report["provider"]=rpc.telemetry()
    report["ended_at"]=time.time()
    return report


if __name__=="__main__":
    result=run(os.environ.get("MM_ROBINHOOD_READ_RPC_URL",""))
    raw=json.dumps(result,sort_keys=True,separators=(",",":")).encode()
    if len(raw)>2_000_000:
        raise BoundaryError("natural_report_capacity")
    REPORT.write_bytes(raw)
    print(json.dumps(dict(
        boundary=result.get("boundary"),
        candidate=(result.get("candidate") or {}).get("token"),
        freshness=(result.get("candidate") or {}).get("freshness_seconds"),
        dependency_status=result.get("dependency_status"),
        outcome=result.get("outcome"),
        provider=result["provider"],
    ),sort_keys=True))
