"""Prospective unbiased natural sample for frozen continuation-v1-robinhood.

Latency-optimized without changing policy:
- warm a global Pons CurveBuy/CurveSell tape before sampling;
- never rescan a candidate's prior 60 seconds with serial historical log queries;
- authenticate candidate state with bounded JSON-RPC batches;
- authenticate the candidate's 60-second market window from the warmed tape;
- reconstruct exact holder concentration in parallel with market-window authentication.

The frozen policy, selection rule, five-second decision-state gate and all thresholds
remain unchanged. Missing data stays explicit and fail-closed.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import json
import os
from pathlib import Path
import time

from . import BoundaryError, CHAIN_ID
from .abi import calldata, topic
from .continuation_robinhood import (
    POLICY, REFERENCE_ENTRY_WEI, THRESHOLDS, TRANSLATION_SNAPSHOT,
    normalized_trade, qualification_vector,
)
from .evidence import Stamp, digest
from .evidence_queue import DeadlineEvidenceQueue
from .identity import load
from .pons import (
    CurveState, authenticate_curve, curve_abi, factory_record, raw_event,
)
from .pons_concentration import top5_concentration_bps
from .pons_natural_observation import (
    RESEARCH_RECIPIENT, _authenticate_candidate, _current_curve_events,
    _latest_header, _next_discovery_end, _one_word, _two_uints,
)
from .provider_topology import configured_discovery_rpc, configured_rpc
from .sequencer_feed import SequencerBlockClock

REPORT=Path(os.environ.get(
    "MM_ROBINHOOD_CONTINUATION_SAMPLE_REPORT",
    "robinhood-continuation-v1-sample.json",
))
TARGET_COMPLETE=10
MAX_ENROLLED=24
RUN_SECONDS=360
FORWARD_SECONDS=60
TAPE_WARM_SECONDS=65
POLL_SECONDS=0.5
MAX_PROVIDER_SESSIONS=32
MAX_TAPE_EVENTS=20000
HEADER_BATCH=50
RECEIPT_BATCH=20


def _rpc(endpoint, *, full=False):
    return configured_rpc(
        endpoint,limit=200,per_scope=(200 if full else 190),retries=0,
    )


def _discovery_rpc(endpoint):
    return configured_discovery_rpc(
        endpoint,limit=200,per_scope=190,retries=0,
    )


def _chunks(rows,size):
    for i in range(0,len(rows),size):
        yield rows[i:i+size]


def _aggregate_telemetry(rows):
    out=dict(
        requests=0,transport_requests=0,logical_requests=0,retries=0,
        methods={},logical_methods={},scopes={},failures={},
    )
    for row in rows:
        if not row:
            continue
        for key in ("requests","transport_requests","logical_requests","retries"):
            out[key]+=int(row.get(key,0))
        for key in ("methods","logical_methods","scopes","failures"):
            dest=out[key]
            for name,value in (row.get(key) or {}).items():
                dest[name]=dest.get(name,0)+int(value)
    return out


def _fast_candidate(endpoint,event):
    """Use the shared two-transport authoritative Pons authenticator."""
    rpc=_rpc(endpoint)
    report=dict(reads=[])
    candidate=_authenticate_candidate(rpc,event,report)
    candidate.update(
        authenticated_at=int(time.time()),
        provider=rpc.telemetry(),
        report=report,
    )
    return candidate

def _window_from_tape(endpoint,candidate,tape):
    """Authenticate exact prior-60s curve events already present in the live tape."""
    rpc=_rpc(endpoint,full=True)
    end_time=int(candidate["header"]["timestamp"],16)
    end_block=candidate["block"]
    curve=candidate["curve"]

    raw=[
        event for event in tape
        if event["address"].lower()==curve
        and int(event["blockNumber"],16)<=end_block
    ]
    if not raw:
        return [],dict(
            covered=True,raw_event_count=0,accepted_event_count=0,
            capacity_exceeded=False,source="warmed_global_tape",
        ),rpc.telemetry()

    hashes=list(dict.fromkeys(event["blockHash"] for event in raw))
    headers={}
    for group in _chunks(hashes,HEADER_BATCH):
        values=rpc.batch(
            [("eth_getBlockByHash",[bh,False]) for bh in group],
            scope="pons_sample",
        )
        headers.update(zip(group,values))

    selected=[]
    for event in raw:
        header=headers[event["blockHash"]]
        event_at=int(header["timestamp"],16)
        if end_time-60<=event_at<=end_time:
            selected.append(event)
    selected.sort(key=lambda e:(
        int(e["blockNumber"],16),int(e["transactionIndex"],16),int(e["logIndex"],16)
    ))

    if len(selected)>THRESHOLDS["max_evidence_events"]:
        return [],dict(
            covered=True,raw_event_count=len(selected),accepted_event_count=0,
            capacity_exceeded=True,source="warmed_global_tape",
        ),rpc.telemetry()

    tx_rows=list(dict.fromkeys(
        (event["transactionHash"],event["blockHash"]) for event in selected
    ))
    receipts={}
    for group in _chunks(tx_rows,RECEIPT_BATCH):
        values=rpc.batch(
            [("eth_getTransactionReceipt",[tx]) for tx,_ in group],
            scope="pons_sample",
        )
        for (tx,bh),receipt in zip(group,values):
            if receipt["transactionHash"]!=tx or receipt["blockHash"]!=bh:
                raise BoundaryError("receipt_block_disagreement")
            receipts[(tx,bh)]=receipt

    out=[]
    observed=int(time.time())
    for event in selected:
        decoded=raw_event(
            curve_abi(),event,address=curve,
            receipt=receipts[(event["transactionHash"],event["blockHash"])],
            header=headers[event["blockHash"]],observed_at=observed,
            confirmation="confirmed",
        )
        out.append(normalized_trade(
            decoded["decoded"],
            identity=f'{decoded["block"]}:{decoded["transaction_hash"]}:{decoded["log_index"]}',
            event_at=decoded["event_at"],
        ))
    return out,dict(
        covered=True,raw_event_count=len(selected),accepted_event_count=len(out),
        capacity_exceeded=False,source="warmed_global_tape",
    ),rpc.telemetry()


def _concentration(endpoint,candidate):
    rpc=_rpc(endpoint)
    value,meta=top5_concentration_bps(
        rpc,token=candidate["token"],curve=candidate["curve"],
        block=candidate["block"],scope="pons_sample",
    )
    return value,meta,rpc.telemetry()


def _evaluate(endpoint,event,sequence,tape):
    started=time.time()
    sessions=[]
    try:
        candidate=_fast_candidate(endpoint,event)
        sessions.append(candidate["provider"])
        nomination=normalized_trade(
            candidate["decoded_event"]["decoded"],
            identity=f'{candidate["block"]}:{candidate["source_event"]["transactionHash"]}:{candidate["source_event"]["logIndex"]}',
            event_at=candidate["stamp"].event_at,
        )
        if nomination["side"]!="buy":
            raise BoundaryError("sample_nomination_not_buy")

        if candidate["record"].get("pairToken","").lower()!=(
            "0x0000000000000000000000000000000000000000"
        ):
            raise BoundaryError("natural_non_native_quote_not_supported")

        # These are independent evidence lanes. Run them concurrently so complete
        # evidence availability is bounded by the slower lane, not their sum.
        with ThreadPoolExecutor(max_workers=2) as pool:
            fw=pool.submit(_window_from_tape,endpoint,candidate,list(tape))
            fc=pool.submit(_concentration,endpoint,candidate)
            market,coverage,window_telemetry=fw.result()
            concentration_bps,concentration_meta,concentration_telemetry=fc.result()
        sessions.extend([window_telemetry,concentration_telemetry])

        available=int(time.time())
        if coverage["capacity_exceeded"]:
            vector=dict(
                policy=POLICY,authority="research_only",qualification_authority=False,
                thresholds=dict(THRESHOLDS),translation_snapshot=dict(TRANSLATION_SNAPSHOT),
                asof=candidate["stamp"].event_at,asof_block=candidate["block"],
                evidence_available_at=available,
                decision_state_age_seconds=available-candidate["state"].timestamp,
                decision_state_fresh=(available-candidate["state"].timestamp<=5),
                evidence_event_count=coverage["raw_event_count"],
                complete=False,current_threshold_pass=False,
                qualification="evidence_capacity",all_rejections=["evidence_capacity"],
            )
        else:
            vector=qualification_vector(
                state=candidate["state"],record=candidate["record"],
                nomination=nomination,events=market,
                concentration_bps=concentration_bps,
                concentration_meta=concentration_meta,
                current_snipe_bps=candidate["current_snipe_bps"],
                roundtrip_gas_wei=candidate["roundtrip_gas_wei"],
                asof=candidate["stamp"].event_at,asof_block=candidate["block"],
                evidence_available_at=available,
            )
            vector["gas_meta"]=candidate["gas_meta"]

        entry=None
        try:
            buy=candidate["state"].buy_with_snipe(
                REFERENCE_ENTRY_WEI,candidate["current_snipe_bps"]
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
            evaluation_latency_ms=round((time.time()-started)*1000,2),
            candidate_auth_latency_ms=candidate["auth_latency_ms"],
            nomination=nomination,coverage=coverage,vector=vector,
            entry_reference=entry,concentration_meta=concentration_meta,
            provider=_aggregate_telemetry(sessions),provider_sessions=sessions,
        )
    except BoundaryError as exc:
        return dict(
            sequence=sequence,status="incomplete",
            source_transaction=event.get("transactionHash"),
            source_block=int(event.get("blockNumber","0x0"),16),
            source_log_index=int(event.get("logIndex","0x0"),16),
            enrolled_at=int(started),evaluation_completed_at=int(time.time()),
            evaluation_latency_ms=round((time.time()-started)*1000,2),
            boundary=str(exc),provider=_aggregate_telemetry(sessions),
            provider_sessions=sessions,
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
        token=row["token"];curve=row["curve"]
        factory=load("pons_v2_factory")["address"].lower()
        values=rpc.batch([
            ("eth_call",[dict(
                to=factory,data=calldata("getLaunchedToken(address)",token)
            ),hex(block)]),
            ("eth_getCode",[curve,hex(block)]),
            ("eth_call",[dict(to=curve,data=calldata("getReserves()")),hex(block)]),
            ("eth_call",[dict(to=curve,data=calldata("realQuoteReserve()")),hex(block)]),
            ("eth_call",[dict(to=curve,data=calldata("reservedTokens()")),hex(block)]),
            ("eth_call",[dict(to=curve,data=calldata("graduated()")),hex(block)]),
            ("eth_gasPrice",[]),
        ],scope="pons_sample")
        record=factory_record(values[0],"pons_v2_factory")
        auth=authenticate_curve(curve,values[1],factory_record=record)
        qr,tr=_two_uints(values[2])
        state=CurveState(
            quote_reserve=qr,token_reserve=tr,real_quote=_one_word(values[3]),
            reserved_tokens=_one_word(values[4]),
            fee_bps=int(auth["immutables"]["feeBps"]),
            creator_tax_bps=int(auth["immutables"]["creatorTaxBps"]),
            graduated=bool(_one_word(values[5],"bool")),
            launched_at=int(header["timestamp"],16),snipe_start_bps=0,
            snipe_seconds=1,timestamp=int(header["timestamp"],16),
        )
        if state.graduated:
            return dict(
                status="incomplete",reason="graduated_requires_v4_forward_mark",
                block=block,event_at=int(header["timestamp"],16),
                provider=rpc.telemetry(),
            )
        sell=state.sell(int(entry["tokens"]))
        gas_price=int(values[6],16)
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


def _rotate_discovery(endpoint,rpc,result):
    result["discovery_sessions"].append(rpc.telemetry())
    if len(result["discovery_sessions"])>=MAX_PROVIDER_SESSIONS:
        raise BoundaryError("discovery_session_capacity")
    new=_discovery_rpc(endpoint)
    new.verify_chain()
    return new


def _poll_into_tape(endpoint,rpc,cursor,tape,result,feed):
    if rpc.used>150:
        rpc=_rotate_discovery(endpoint,rpc,result)
    latest=_next_discovery_end(feed,cursor,rpc,timeout=POLL_SECONDS)
    if latest is None:
        return rpc,cursor,[],None
    first=cursor+1
    fresh=[]
    if latest>=first:
        fresh=_current_curve_events(rpc,first,latest)
        tape.extend(fresh)
        if len(tape)>MAX_TAPE_EVENTS:
            raise BoundaryError("sample_tape_capacity")
        cursor=latest
    observed_timestamp=feed.state.latest_header_timestamp
    observation=(
        None if observed_timestamp is None else
        dict(number=hex(latest),timestamp=hex(int(observed_timestamp)))
    )
    return rpc,cursor,fresh,observation


def run(endpoint):
    started=time.time()
    result=dict(
        kind="continuation-v1-robinhood-unbiased-natural-sample",
        acquisition_version="sequencer_range_batch_two_transport_auth_v3",
        policy=POLICY,thresholds=dict(THRESHOLDS),
        translation_snapshot=dict(TRANSLATION_SNAPSHOT),
        policy_hash=digest(dict(
            policy=POLICY,thresholds=THRESHOLDS,translation=TRANSLATION_SNAPSHOT
        )),
        started_at=started,target_complete=TARGET_COMPLETE,max_enrolled=MAX_ENROLLED,
        run_seconds=RUN_SECONDS,forward_seconds=FORWARD_SECONDS,
        tape_warm_seconds=TAPE_WARM_SECONDS,
        selection_rule="first_previously_unseen_authentic_current_pons_v2_buy_after_prior_enrollment_attempt",
        reranking=False,replacement=False,outcome_blind=True,
        threshold_changes_allowed=False,rows=[],discovery_sessions=[],
        evidence_scheduler="deadline_queue_v1",
    )

    seen_tx_logs=set();seen_curves=set();complete=0;tape=[]
    evidence_queue=DeadlineEvidenceQueue(limit=MAX_TAPE_EVENTS,nominal_deadline_seconds=5.0)
    rpc=_discovery_rpc(endpoint);rpc.verify_chain()
    feed=SequencerBlockClock()
    feed.connect()
    cursor=feed.wait_for_after(-1,timeout=5.0)
    if cursor is None:
        raise BoundaryError("sequencer_discovery_start_timeout")
    start_header=rpc.call(
        "eth_getBlockByNumber",[hex(cursor),False],scope="pons_natural"
    )
    if int(start_header["number"],16)!=cursor:
        raise BoundaryError("sequencer_discovery_block_disagreement")
    latest_header=start_header
    warm_start=int(start_header["timestamp"],16)
    warm_deadline=time.monotonic()+TAPE_WARM_SECONDS

    try:
        # Warm continuously so each later nomination has its prior 60-second event
        # history already resident. No candidate is enrolled during warmup.
        while time.monotonic()<warm_deadline:
            rpc,cursor,_,observed_header=_poll_into_tape(
                endpoint,rpc,cursor,tape,result,feed
            )
            if observed_header is not None:
                latest_header=observed_header
        result["warmup"]=dict(
            start_block=int(start_header["number"],16),end_block=cursor,
            start_time=warm_start,end_time=int(latest_header["timestamp"],16),
            events=len(tape),covered_seconds=int(latest_header["timestamp"],16)-warm_start,
        )
        if result["warmup"]["covered_seconds"]<60:
            raise BoundaryError("sample_tape_warmup_incomplete")

        deadline=time.monotonic()+RUN_SECONDS
        while (
            time.monotonic()<deadline
            and len(result["rows"])<MAX_ENROLLED
            and complete<TARGET_COMPLETE
        ):
            rpc,cursor,fresh,observed_header=_poll_into_tape(
                endpoint,rpc,cursor,tape,result,feed
            )
            if observed_header is not None:
                latest_header=observed_header
            for event in fresh:
                key=(event["transactionHash"],event["logIndex"])
                if key in seen_tx_logs:
                    continue
                seen_tx_logs.add(key)
                if (
                    not event.get("topics")
                    or event["topics"][0].lower()!=topic(
                        "CurveBuy(address,address,uint256,uint256,uint256,uint256)"
                    )
                ):
                    continue
                curve=event["address"].lower()
                if curve in seen_curves:
                    continue
                seen_curves.add(curve)
                evidence_queue.enqueue(event,now=time.time())
            scheduled=evidence_queue.pop(
                now=time.time(),minimum_remaining_seconds=0.5
            )
            if scheduled is None:
                continue
            event=scheduled["event"]
            row=_evaluate(endpoint,event,len(result["rows"]),tape)
            result["rows"].append(row)
            vector=row.get("vector") or {}
            if vector.get("complete") and vector.get("decision_state_fresh"):
                complete+=1

        result["discovery_sessions"].append(rpc.telemetry())

        # Outcomes remain outcome-blind because enrollment is frozen first.
        for row in result["rows"]:
            if row.get("status")=="evaluated":
                row["forward_after_60s"]=_forward_mark(endpoint,row)

    except BoundaryError as exc:
        result["boundary"]=str(exc)
        result["discovery_sessions"].append(rpc.telemetry())
    finally:
        result["sequencer_discovery"]=feed.status()
        feed.close()

    vectors=[r.get("vector") for r in result["rows"] if r.get("vector")]
    complete_ages=[
        int(v["decision_state_age_seconds"]) for v in vectors
        if v.get("complete") and v.get("decision_state_age_seconds") is not None
    ]
    result["evidence_queue"]=evidence_queue.telemetry()
    result["summary"]=dict(
        enrolled=len(result["rows"]),
        evaluated=sum(r.get("status")=="evaluated" for r in result["rows"]),
        incomplete=sum(r.get("status")!="evaluated" for r in result["rows"]),
        complete_vectors=sum(bool(v.get("complete")) for v in vectors),
        decision_eligible_complete=sum(bool(
            v.get("complete") and v.get("decision_state_fresh")
        ) for v in vectors),
        qualified=sum(bool(v.get("current_threshold_pass")) for v in vectors),
        forward_marks_complete=sum(
            (r.get("forward_after_60s") or {}).get("status")=="complete"
            for r in result["rows"]
        ),
        complete_age_seconds=complete_ages,
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
        boundary=result.get("boundary"),policy_hash=result["policy_hash"],
        summary=result["summary"],
        elapsed_seconds=round(result["ended_at"]-result["started_at"],2),
    ),sort_keys=True))