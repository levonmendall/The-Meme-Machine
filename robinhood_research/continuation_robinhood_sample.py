"""Prospective unbiased natural sample for frozen continuation-v1-robinhood.

No candidate is ranked, replaced, or selected by its future outcome. Each enrollment
is the first previously unseen authentic Pons V2 BUY encountered after the previous
enrollment attempt completes. Complete and incomplete vectors are both retained.
Thresholds and translation constants are imported read-only from the frozen policy.

The runner targets ten decision-eligible complete vectors within a bounded session.
It records full-position research marks after the +60s minimum horizon where available; exact-delay telemetry is retained. Missing concentration,
provider limits, stale evidence, graduation, or unavailable exits remain explicit
sample outcomes; they never cause a candidate replacement.
"""
from dataclasses import asdict
import json
import os
from pathlib import Path
import time

from . import BoundaryError
from .abi import topic
from .continuation_robinhood import (
    POLICY, REFERENCE_ENTRY_WEI, THRESHOLDS, TRANSLATION_SNAPSHOT,
    normalized_trade, qualification_vector,
)
from .evidence import digest
from .pons import curve_abi, raw_event
from .pons_concentration import top5_concentration_bps
from .pons_natural_observation import (
    _authenticate_candidate, _call, _current_curve_events, _curve_state,
    _latest_header, _one_word,
)
from .provider import Rpc

REPORT=Path(os.environ.get(
    "MM_ROBINHOOD_CONTINUATION_SAMPLE_REPORT",
    "robinhood-continuation-v1-sample.json",
))
TARGET_COMPLETE=10
MAX_ENROLLED=24
RUN_SECONDS=360
FORWARD_SECONDS=60
POLL_SECONDS=0.5
MAX_PROVIDER_SESSIONS=32


def _rpc(endpoint):
    return Rpc(endpoint,limit=200,per_scope=190,retries=0)


def _header(rpc,block,scope="pons_sample"):
    return rpc.call("eth_getBlockByNumber",[hex(block),False],scope=scope)


def _window_start(rpc,end_block,end_time):
    target=end_time-60
    low=max(0,end_block-1024)
    low_header=_header(rpc,low)
    if int(low_header["timestamp"],16)>target:
        raise BoundaryError("market_window_block_span_exceeded")
    left,right=low,end_block
    while left<right:
        mid=(left+right)//2
        h=_header(rpc,mid)
        if int(h["timestamp"],16)<target:
            left=mid+1
        else:
            right=mid
    return max(low,left-1)


def _window_events(rpc,candidate,report):
    end_block=candidate["block"]
    end_time=int(candidate["header"]["timestamp"],16)
    start_block=_window_start(rpc,end_block,end_time)
    sigs=[
        topic("CurveBuy(address,address,uint256,uint256,uint256,uint256)"),
        topic("CurveSell(address,address,uint256,uint256,uint256,uint256)"),
    ]
    raw=[]
    for first in range(start_block,end_block+1,10):
        raw.extend(rpc.call("eth_getLogs",[dict(
            fromBlock=hex(first),toBlock=hex(min(end_block,first+9)),
            address=candidate["curve"],topics=[sigs],
        )],scope="pons_sample"))
        if len(raw)>THRESHOLDS["max_evidence_events"]:
            # Event-cap rejection is already known. Retain exact count observed up
            # to the first over-cap slice; do not spend provider budget decoding a
            # candidate that the frozen strategy cannot admit.
            return [],dict(
                covered=True,start_block=start_block,end_block=end_block,
                raw_event_count=len(raw),capacity_exceeded=True,
            )
    out=[]
    receipts={}
    headers={}
    for event in raw:
        bh=event["blockHash"];tx=event["transactionHash"]
        if bh not in headers:
            h=rpc.call("eth_getBlockByHash",[bh,False],scope="pons_sample")
            headers[bh]=h
        key=(tx,bh)
        if key not in receipts:
            receipts[key]=rpc.receipt(tx,bh,scope="pons_sample")
        decoded=raw_event(
            curve_abi(),event,address=candidate["curve"],receipt=receipts[key],
            header=headers[bh],observed_at=int(time.time()),confirmation="confirmed",
        )
        if not end_time-60<=decoded["event_at"]<=end_time:
            continue
        out.append(normalized_trade(
            decoded["decoded"],
            identity=f'{decoded["block"]}:{decoded["transaction_hash"]}:{decoded["log_index"]}',
            event_at=decoded["event_at"],
        ))
    out.sort(key=lambda x:(x["event_at"],x["identity"]))
    return out,dict(
        covered=True,start_block=start_block,end_block=end_block,
        raw_event_count=len(raw),accepted_event_count=len(out),capacity_exceeded=False,
    )


def _gas_proxy(candidate,rpc):
    try:
        units=int(candidate["receipt"]["gasUsed"],16)
    except (KeyError,ValueError,TypeError):
        raise BoundaryError("sample_missing_gas_used") from None
    if not 21_000<=units<=5_000_000:
        raise BoundaryError("sample_gas_units_bounds")
    price=int(rpc.call("eth_gasPrice",[],scope="pons_sample"),16)
    if price<=0:
        raise BoundaryError("sample_invalid_gas_price")
    return 2*units*price,dict(units_per_side=units,gas_price=price)


def _evaluate(endpoint,event,sequence):
    report=dict(reads=[])
    rpc=_rpc(endpoint)
    started=time.time()
    try:
        rpc.verify_chain()
        candidate=_authenticate_candidate(rpc,event,report)
        nomination=normalized_trade(
            candidate["decoded_event"]["decoded"],
            identity=f'{candidate["block"]}:{candidate["source_event"]["transactionHash"]}:{candidate["source_event"]["logIndex"]}',
            event_at=candidate["stamp"].event_at,
        )
        if nomination["side"]!="buy":
            raise BoundaryError("sample_nomination_not_buy")

        market,coverage=_window_events(rpc,candidate,report)
        if coverage["capacity_exceeded"]:
            vector=dict(
                policy=POLICY,authority="research_only",qualification_authority=False,
                thresholds=dict(THRESHOLDS),translation_snapshot=dict(TRANSLATION_SNAPSHOT),
                asof=candidate["stamp"].event_at,asof_block=candidate["block"],
                evidence_event_count=coverage["raw_event_count"],
                complete=False,current_threshold_pass=False,
                qualification="evidence_capacity",all_rejections=["evidence_capacity"],
            )
            concentration_meta=None
        else:
            concentration_bps,concentration_meta=top5_concentration_bps(
                rpc,token=candidate["token"],curve=candidate["curve"],
                block=candidate["block"],scope="pons_sample",
            )
            roundtrip_gas,gas_meta=_gas_proxy(candidate,rpc)
            available=int(time.time())
            vector=qualification_vector(
                state=candidate["state"],record=candidate["record"],
                nomination=nomination,events=market,
                concentration_bps=concentration_bps,
                concentration_meta=concentration_meta,
                current_snipe_bps=candidate["quote"]["current_snipe_bps"],
                roundtrip_gas_wei=roundtrip_gas,
                asof=candidate["stamp"].event_at,asof_block=candidate["block"],
                evidence_available_at=available,
            )
            vector["gas_meta"]=gas_meta

        entry=None
        try:
            buy=candidate["state"].buy_with_snipe(
                REFERENCE_ENTRY_WEI,candidate["quote"]["current_snipe_bps"]
            )
            if not buy["refund"] and not buy["ready_to_graduate"]:
                entry=dict(
                    input_wei=REFERENCE_ENTRY_WEI,tokens=buy["tokens_out"],
                    spent_wei=buy["spent"],fee_wei=buy["fee"]+buy["creator_tax"],
                    asof_block=candidate["block"],asof_time=candidate["stamp"].event_at,
                )
        except BoundaryError:
            pass
        return dict(
            sequence=sequence,status="evaluated",token=candidate["token"],
            curve=candidate["curve"],source_transaction=event["transactionHash"],
            source_block=candidate["block"],source_log_index=int(event["logIndex"],16),
            enrolled_at=int(started),evaluation_completed_at=int(time.time()),
            nomination=nomination,coverage=coverage,vector=vector,
            entry_reference=entry,concentration_meta=concentration_meta,
            provider=rpc.telemetry(),
        )
    except BoundaryError as exc:
        return dict(
            sequence=sequence,status="incomplete",source_transaction=event.get("transactionHash"),
            source_block=int(event.get("blockNumber","0x0"),16),
            source_log_index=int(event.get("logIndex","0x0"),16),
            enrolled_at=int(started),evaluation_completed_at=int(time.time()),
            boundary=str(exc),provider=rpc.telemetry(),
        )


def _forward_mark(endpoint,row):
    entry=row.get("entry_reference")
    if not entry:
        return dict(status="unavailable",reason="no_reference_entry")
    rpc=_rpc(endpoint)
    try:
        rpc.verify_chain()
        deadline=time.monotonic()+90
        header=None
        while time.monotonic()<deadline:
            header=_latest_header(rpc)
            if int(header["timestamp"],16)>=int(entry["asof_time"])+FORWARD_SECONDS:
                break
            time.sleep(POLL_SECONDS)
        if header is None or int(header["timestamp"],16)<int(entry["asof_time"])+FORWARD_SECONDS:
            raise BoundaryError("forward_horizon_not_reached")
        block=int(header["number"],16)
        candidate=dict(
            curve=row["curve"],
            auth=None,
            report={"reads":[]},
        )
        # Re-authentication uses the frozen original factory record/compiled runtime
        # indirectly through current code identity from the evaluator; for the mark,
        # reconstruct state using a fresh authentication from the current token record.
        from .pons import authenticate_curve, factory_record
        from .identity import load
        token=row["token"]
        factory=load("pons_v2_factory")["address"].lower()
        raw=_call(rpc,factory,"getLaunchedToken(address)",(token,),block,candidate["report"])
        record=factory_record(raw,"pons_v2_factory")
        code=rpc.call("eth_getCode",[row["curve"],hex(block)],scope="pons_sample")
        auth=authenticate_curve(row["curve"],code,factory_record=record)
        candidate["auth"]=auth
        state,_=_curve_state(rpc,row["curve"],block,auth,candidate["report"])
        if state.graduated:
            return dict(
                status="incomplete",reason="graduated_requires_v4_forward_mark",
                block=block,event_at=int(header["timestamp"],16),
                provider=rpc.telemetry(),
            )
        sell=state.sell(int(entry["tokens"]))
        gas_price=int(rpc.call("eth_gasPrice",[],scope="pons_sample"),16)
        # Keep outcome accounting descriptive: use the same per-side gas units used
        # in qualification when available, otherwise do not invent a gas value.
        units=((row.get("vector") or {}).get("gas_meta") or {}).get("units_per_side")
        gas=None if units is None else int(units)*gas_price
        net=None if gas is None else max(0,int(sell["quote_out"])-gas)
        basis=int(entry["spent_wei"])
        return dict(
            status="complete",block=block,event_at=int(header["timestamp"],16),
            delay_seconds=int(header["timestamp"],16)-int(entry["asof_time"]),
            gross_exit_wei=int(sell["quote_out"]),gas_wei=gas,net_exit_wei=net,
            gross_return_bps=(int(sell["quote_out"])-basis)*10_000//basis,
            net_return_bps=(None if net is None else (net-basis)*10_000//basis),
            provider=rpc.telemetry(),
        )
    except BoundaryError as exc:
        return dict(status="incomplete",reason=str(exc),provider=rpc.telemetry())


def run(endpoint):
    started=time.time()
    result=dict(
        kind="continuation-v1-robinhood-unbiased-natural-sample",
        policy=POLICY,thresholds=dict(THRESHOLDS),
        translation_snapshot=dict(TRANSLATION_SNAPSHOT),
        policy_hash=digest(dict(policy=POLICY,thresholds=THRESHOLDS,
                                translation=TRANSLATION_SNAPSHOT)),
        started_at=started,target_complete=TARGET_COMPLETE,max_enrolled=MAX_ENROLLED,
        run_seconds=RUN_SECONDS,forward_seconds=FORWARD_SECONDS,
        selection_rule="first_previously_unseen_authentic_current_pons_v2_buy_after_prior_enrollment_attempt",
        reranking=False,replacement=False,outcome_blind=True,threshold_changes_allowed=False,
        rows=[],discovery_sessions=[],
    )
    seen_tx_logs=set();seen_curves=set();complete=0
    rpc=_rpc(endpoint);rpc.verify_chain()
    cursor=int(_latest_header(rpc)["number"],16)
    deadline=time.monotonic()+RUN_SECONDS

    while time.monotonic()<deadline and len(result["rows"])<MAX_ENROLLED and complete<TARGET_COMPLETE:
        if rpc.used>150:
            result["discovery_sessions"].append(rpc.telemetry())
            if len(result["discovery_sessions"])>=MAX_PROVIDER_SESSIONS:
                break
            rpc=_rpc(endpoint);rpc.verify_chain()
        latest=int(_latest_header(rpc)["number"],16)
        first=max(cursor+1,latest-9)
        candidates=[]
        if latest>=first:
            for event in _current_curve_events(rpc,first,latest):
                key=(event["transactionHash"],event["logIndex"])
                if key in seen_tx_logs:
                    continue
                seen_tx_logs.add(key)
                # Only BUY signatures are nominations. Selection uses no economics.
                if not event.get("topics") or event["topics"][0].lower()!=topic(
                    "CurveBuy(address,address,uint256,uint256,uint256,uint256)"
                ):
                    continue
                curve=event["address"].lower()
                if curve in seen_curves:
                    continue
                candidates.append(event)
            cursor=latest
        if not candidates:
            time.sleep(POLL_SECONDS)
            continue
        candidates.sort(key=lambda e:(
            int(e["blockNumber"],16),int(e["transactionIndex"],16),int(e["logIndex"],16)
        ))
        event=candidates[0]
        seen_curves.add(event["address"].lower())
        row=_evaluate(endpoint,event,len(result["rows"]))
        result["rows"].append(row)
        vector=row.get("vector") or {}
        if vector.get("complete") and vector.get("decision_state_fresh"):
            complete+=1

    result["discovery_sessions"].append(rpc.telemetry())

    # Outcomes are attached only after enrollment is frozen.
    for row in result["rows"]:
        if row.get("status")=="evaluated":
            row["forward_after_60s"]=_forward_mark(endpoint,row)

    vectors=[r.get("vector") for r in result["rows"] if r.get("vector")]
    result["summary"]=dict(
        enrolled=len(result["rows"]),
        evaluated=sum(r.get("status")=="evaluated" for r in result["rows"]),
        incomplete=sum(r.get("status")!="evaluated" for r in result["rows"]),
        complete_vectors=sum(bool(v.get("complete")) for v in vectors),
        decision_eligible_complete=sum(bool(v.get("complete") and v.get("decision_state_fresh")) for v in vectors),
        qualified=sum(bool(v.get("current_threshold_pass")) for v in vectors),
        forward_marks_complete=sum((r.get("forward_after_60s") or {}).get("status")=="complete" for r in result["rows"]),
        rejection_counts={},
    )
    counts={}
    for vector in vectors:
        for reason in vector.get("all_rejections") or []:
            counts[reason]=counts.get(reason,0)+1
    result["summary"]["rejection_counts"]=dict(sorted(counts.items()))
    result["ended_at"]=time.time()
    return result


if __name__=="__main__":
    result=run(os.environ.get("MM_ROBINHOOD_READ_RPC_URL",""))
    raw=json.dumps(result,sort_keys=True,separators=(",",":")).encode()
    if len(raw)>4_000_000:
        raise BoundaryError("sample_report_capacity")
    REPORT.write_bytes(raw)
    print(json.dumps(dict(
        policy_hash=result["policy_hash"],summary=result["summary"],
        elapsed_seconds=round(result["ended_at"]-result["started_at"],2),
    ),sort_keys=True))
