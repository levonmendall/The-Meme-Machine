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
from .evidence_queue import DeadlineEvidenceQueue
from .finality import Finality
from .identity import load
from .pons import (
    CurveState, authenticate_curve, curve_abi, factory_record, raw_event,
)
from .provider_topology import configured_discovery_rpc, configured_rpc
from .sequencer_feed import SequencerBlockClock

REPORT=Path(os.environ.get("MM_ROBINHOOD_PONS_NATURAL_REPORT","robinhood-pons-natural-report.json"))
OBSERVE_SECONDS=60
DISCOVERY_SECONDS=90
POLL_SECONDS=1.0
DISCOVERY_MAX_BLOCKS=10
DISCOVERY_FALLBACK_COALESCE_SECONDS=0.75
DISCOVERY_DEDICATED_COALESCE_SECONDS=0.20
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

def _next_discovery_end(feed,cursor,discovery,*,timeout):
    coalesce=(
        DISCOVERY_FALLBACK_COALESCE_SECONDS
        if getattr(discovery,"primary_fallback",False)
        else DISCOVERY_DEDICATED_COALESCE_SECONDS
    )
    return feed.wait_for_range_after(
        cursor,timeout=timeout,max_blocks=DISCOVERY_MAX_BLOCKS,
        coalesce_seconds=coalesce,
    )


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
    """Authenticate one current candidate in exactly two HTTP batch transports."""
    started=time.time()
    block=int(event["blockNumber"],16)
    block_hex=hex(block)
    curve=event["address"].lower()
    tx=event["transactionHash"]

    first_calls=[
        ("eth_chainId",[]),
        ("eth_getBlockByNumber",[block_hex,False]),
        ("eth_getTransactionReceipt",[tx]),
        ("eth_call",[dict(to=curve,data=calldata("token()")),block_hex]),
        ("eth_getCode",[curve,block_hex]),
        ("eth_call",[dict(to=curve,data=calldata("getReserves()")),block_hex]),
        ("eth_call",[dict(to=curve,data=calldata("realQuoteReserve()")),block_hex]),
        ("eth_call",[dict(to=curve,data=calldata("reservedTokens()")),block_hex]),
        ("eth_call",[dict(to=curve,data=calldata("graduated()")),block_hex]),
        ("eth_call",[dict(
            to=curve,
            data=calldata("currentSnipeTaxBps(address)",RESEARCH_RECIPIENT),
        ),block_hex]),
        ("eth_gasPrice",[]),
    ]
    first=rpc.batch(first_calls,scope="pons_natural")
    (chain_raw,header,receipt,token_raw,code,reserves_raw,real_raw,reserved_raw,
     graduated_raw,snipe_raw,gas_raw)=first
    if int(chain_raw,16)!=CHAIN_ID:
        raise BoundaryError("wrong_chain")
    if (
        header["hash"]!=event["blockHash"]
        or header["number"]!=event["blockNumber"]
        or receipt["transactionHash"]!=tx
        or receipt["blockHash"]!=event["blockHash"]
    ):
        raise BoundaryError("candidate_identity_disagreement")

    observed=int(time.time())
    event_at=int(header["timestamp"],16)
    if observed-event_at>5:
        raise BoundaryError("stale_state")
    decoded=raw_event(
        curve_abi(),event,address=curve,receipt=receipt,header=header,
        observed_at=observed,confirmation="confirmed",
    )
    token=_one_word(token_raw,"address")
    factory=load("pons_v2_factory")["address"].lower()

    second_calls=[
        ("eth_call",[dict(
            to=factory,data=calldata("getLaunchedToken(address)",token)
        ),block_hex]),
    ]
    second=rpc.batch(second_calls,scope="pons_natural")
    record=factory_record(second[0],"pons_v2_factory")
    auth=authenticate_curve(curve,code,factory_record=record)

    quote_reserve,token_reserve=_two_uints(reserves_raw)
    state=CurveState(
        quote_reserve=quote_reserve,token_reserve=token_reserve,
        real_quote=_one_word(real_raw),reserved_tokens=_one_word(reserved_raw),
        fee_bps=int(auth["immutables"]["feeBps"]),
        creator_tax_bps=int(auth["immutables"]["creatorTaxBps"]),
        graduated=bool(_one_word(graduated_raw,"bool")),
        launched_at=event_at,snipe_start_bps=0,snipe_seconds=1,timestamp=event_at,
    )
    current_snipe=_one_word(snipe_raw)
    maximum=9900-state.fee_bps-state.creator_tax_bps
    if not 0<=current_snipe<=maximum:
        raise BoundaryError("invalid_current_snipe_bps")
    if record["pairToken"].lower()!=ZERO:
        raise BoundaryError("natural_non_native_quote_not_supported")
    quote=state.buy_with_snipe(RESEARCH_BUY_WEI,current_snipe)
    quote=dict(
        quote_in=RESEARCH_BUY_WEI,tokens_out=quote["tokens_out"],
        spent=quote["spent"],refund=quote["refund"],fee=quote["fee"],
        creator_tax=quote["creator_tax"],snipe_tax=quote["snipe_tax"],
        ready_to_graduate=quote["ready_to_graduate"],
        current_snipe_bps=current_snipe,recipient=RESEARCH_RECIPIENT,
        execution="source_verified_arithmetic_plus_onchain_current_snipe",
    )
    gas_units=int(receipt.get("gasUsed","0x0"),16)
    gas_price=int(gas_raw,16)
    if not 21_000<=gas_units<=5_000_000:
        raise BoundaryError("sample_gas_units_bounds")
    if gas_price<=0:
        raise BoundaryError("sample_invalid_gas_price")

    quote_at=int(time.time())
    stamp=Stamp(
        CHAIN_ID,block,header["hash"],event_at,observed,"confirmed","natural",
    )
    if quote_at-event_at>5:
        raise BoundaryError("stale_state")
    report.setdefault("reads",[]).extend([
        dict(kind="candidate_batch",round=1,block=block,
             methods=[method for method,_ in first_calls],observed_at=observed),
        dict(kind="candidate_batch",round=2,block=block,
             methods=[method for method,_ in second_calls],observed_at=quote_at),
    ])
    return dict(
        curve=curve,token=token,block=block,header=header,receipt=receipt,
        source_event=event,decoded_event=decoded,record=record,auth=auth,
        state=state,quote=quote,stamp=stamp,quote_at=quote_at,
        freshness_seconds=quote_at-event_at,current_snipe_bps=current_snipe,
        roundtrip_gas_wei=2*gas_units*gas_price,
        gas_meta=dict(units_per_side=gas_units,gas_price=gas_price),
        auth_latency_ms=round((time.time()-started)*1000,2),
        auth_transport_rounds=2,
    )


def _chunks(rows,size):
    for i in range(0,len(rows),size):
        yield rows[i:i+size]


def _authenticate_followup_events(rpc,candidate,events):
    """Authenticate fixed follow-up events with bounded immutable batch reads."""
    selected=[
        event for event in events
        if event["address"].lower()==candidate["curve"]
    ]
    if len(selected)>200:
        raise BoundaryError("natural_followup_capacity")
    if not selected:
        return []

    block_hashes=list(dict.fromkeys(event["blockHash"] for event in selected))
    headers={}
    for group in _chunks(block_hashes,50):
        values=rpc.batch(
            [("eth_getBlockByHash",[block_hash,False]) for block_hash in group],
            scope="pons_natural",
        )
        for block_hash,header in zip(group,values):
            if header["hash"]!=block_hash:
                raise BoundaryError("followup_block_hash_disagreement")
            headers[block_hash]=header

    tx_rows=list(dict.fromkeys(
        (event["transactionHash"],event["blockHash"]) for event in selected
    ))
    receipts={}
    for group in _chunks(tx_rows,50):
        values=rpc.batch(
            [("eth_getTransactionReceipt",[tx]) for tx,_ in group],
            scope="pons_natural",
        )
        for (tx,block_hash),receipt in zip(group,values):
            if (
                receipt["transactionHash"]!=tx
                or receipt["blockHash"]!=block_hash
            ):
                raise BoundaryError("receipt_block_disagreement")
            receipts[(tx,block_hash)]=receipt

    observed=int(time.time())
    authentic=[]
    for event in selected:
        block_hash=event["blockHash"]
        authentic.append(raw_event(
            curve_abi(),event,address=candidate["curve"],
            receipt=receipts[(event["transactionHash"],block_hash)],
            header=headers[block_hash],observed_at=observed,
            confirmation="confirmed",
        ))
    return authentic


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
    rpc=configured_rpc(endpoint,limit=180,per_scope=170,retries=0)
    discovery=configured_discovery_rpc(
        endpoint,limit=180,per_scope=170,retries=0
    )
    feed=SequencerBlockClock()
    report=dict(
        kind="natural_pons_v2_bounded_observation",
        research_only=True,allocation_authority=False,paper_orders=0,
        selection_rule="first_current_authenticated_pons_v2_curve_trade_after_start",
        outcome_used_for_selection=False,freshness_gate_seconds=5,
        discovery_seconds=DISCOVERY_SECONDS,followup_seconds=OBSERVE_SECONDS,
        research_buy_wei=RESEARCH_BUY_WEI,reads=[],events=[],started_at=time.time(),
        discovery_mode="sequencer_range_batch_plus_deadline_queue_v3",
    )
    candidate=None
    outcome_rpc=None
    evidence_queue=DeadlineEvidenceQueue(limit=256,nominal_deadline_seconds=5.0)
    discovery_ranges=0
    discovered_events=0
    try:
        rpc.verify_chain()
        discovery.verify_chain()
        feed.connect()
        cursor=feed.wait_for_after(-1,timeout=5.0)
        if cursor is None:
            raise BoundaryError("sequencer_discovery_start_timeout")
        start_header=discovery.call(
            "eth_getBlockByNumber",[hex(cursor),False],scope="pons_natural"
        )
        if int(start_header["number"],16)!=cursor:
            raise BoundaryError("sequencer_discovery_block_disagreement")
        report["start_block"]=cursor
        deadline=time.monotonic()+DISCOVERY_SECONDS
        attempted_curves=set()

        while time.monotonic()<deadline and candidate is None:
            end=_next_discovery_end(
                feed,cursor,discovery,timeout=POLL_SECONDS
            )
            if end is None:
                continue
            start=cursor+1
            if end>=start:
                fresh=_current_curve_events(discovery,start,end)
                discovery_ranges+=1
                discovered_events+=len(fresh)
                cursor=end
                now=time.time()
                for event in fresh:
                    curve=event.get("address","").lower()
                    if curve in attempted_curves:
                        continue
                    attempted_curves.add(curve)
                    evidence_queue.enqueue(event,now=now)

            while candidate is None:
                scheduled=evidence_queue.pop(
                    now=time.time(),minimum_remaining_seconds=1.0
                )
                if scheduled is None:
                    break
                event=scheduled["event"]
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
                except BoundaryError as exc:
                    report.setdefault("candidate_rejections",[]).append(dict(
                        address=event.get("address"),block=event.get("blockNumber"),
                        reason=str(exc),
                    ))
                    if len(report["candidate_rejections"])>50:
                        raise BoundaryError("natural_rejection_capacity")

        report["sequencer_discovery"]=feed.status()
        report["discovery_ranges"]=discovery_ranges
        report["discovered_events"]=discovered_events
        report["evidence_queue"]=evidence_queue.telemetry()
        feed.close()
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
        final_header=_latest_header(discovery)
        final_block=int(final_header["number"],16)
        follow=_current_curve_events(discovery,candidate["block"],final_block)

        # Outcome reconstruction is after the candidate/quote is frozen. Use a new
        # bounded logical session on the same authoritative provider and shared 2-RPS
        # physical pacer so outcome history cannot consume the entry evidence budget.
        outcome_rpc=configured_rpc(endpoint,limit=200,per_scope=200,retries=0)
        authentic=_authenticate_followup_events(outcome_rpc,candidate,follow)
        report["events"]=authentic

        # Re-fetch the original height. A replacement block invalidates the research
        # observation rather than being silently substituted.
        canonical=outcome_rpc.call(
            "eth_getBlockByNumber",[hex(candidate["block"]),False],scope="pons_natural"
        )
        now=int(time.time())
        if canonical["hash"]!=candidate["stamp"].block_hash:
            report["dependency_status"]="invalidated"
            raise BoundaryError("confirmed_candidate_reorged")

        finalized=outcome_rpc.call(
            "eth_getBlockByNumber",["finalized",False],scope="pons_natural"
        )
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
            "mark":_final_mark(outcome_rpc,candidate,final_block,report),
            "graduated_during_followup":any(
                row["decoded"]["name"]=="CurveCompleted" for row in authentic
            ),
            "after_cost_profitability_established":False,
        }
    except BoundaryError as exc:
        report["boundary"]=str(exc)
    finally:
        feed.close()
    report["provider"]=rpc.telemetry()
    report["outcome_provider"]=(
        None if outcome_rpc is None else outcome_rpc.telemetry()
    )
    report["discovery_provider"]=discovery.telemetry()
    report.setdefault("sequencer_discovery",feed.status())
    report.setdefault("discovery_ranges",discovery_ranges)
    report.setdefault("discovered_events",discovered_events)
    report.setdefault("evidence_queue",evidence_queue.telemetry())
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