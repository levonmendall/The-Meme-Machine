"""Meaningful-cohort paper trial for frozen continuation-v1-robinhood.

Qualification is exactly the existing frozen policy. No threshold, translation value,
selection rule, five-second evidence gate, or Pons/V4 adapter semantic is changed.

Each genuine qualifier immediately gets its own isolated research paper lifecycle:
2s delayed entry -> 5s monitoring -> +15% / -10% / 900s -> authenticated V2->V4
carry if naturally graduated -> delayed full-position exit -> settlement.

Trials are isolated from one another and from any shared allocator so overlapping
qualifiers are not dropped merely because this is a research cohort.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import time

from . import BoundaryError
from .continuation_robinhood import (
    EXIT_POLICY, POLICY, POLICY_HASH, REFERENCE_ENTRY_WEI,
)
from .continuation_robinhood_sample import (
    TAPE_WARM_SECONDS, _evaluate, _rpc as sample_rpc,
)
from .evidence import Store
from .paper import Paper
from .pons_natural_observation import _current_curve_events, _latest_header
from .pons_natural_paper import (
    _curve_quote, _gas_quote, _gas_units, _graduation_transition,
    _return_bps, _rpc as paper_rpc, _v4_quote, _wait_curve_quote,
)
from .abi import topic

REPORT=Path(os.environ.get(
    "MM_ROBINHOOD_CONTINUATION_COHORT_REPORT",
    "robinhood-continuation-v1-cohort.json",
))
ROOT=Path(os.environ.get(
    "MM_ROBINHOOD_CONTINUATION_COHORT_DIR",
    "robinhood-continuation-cohort",
))

COHORT_TARGET=10
MAX_ENROLLED=300
DISCOVERY_SECONDS=1800
MONITOR_SECONDS=5
MAX_HOLD_SECONDS=EXIT_POLICY["timeout_seconds"]
TAKE_PROFIT_BPS=EXIT_POLICY["take_profit_bps"]
RISK_BPS=EXIT_POLICY["risk_bps"]
ENTRY_DELAY_SECONDS=EXIT_POLICY["delayed_execution_seconds"]
PAPER_AMOUNT=REFERENCE_ENTRY_WEI
PAPER_CAPITAL=REFERENCE_ENTRY_WEI*20
MAX_TAPE_EVENTS=5000
MAX_DISCOVERY_SESSIONS=128
POLL_SECONDS=0.5


def _new_discovery(endpoint):
    rpc=sample_rpc(endpoint)
    rpc.verify_chain()
    return rpc


def _rotate_discovery(endpoint,rpc,result):
    result["discovery_sessions"].append(rpc.telemetry())
    if len(result["discovery_sessions"])>=MAX_DISCOVERY_SESSIONS:
        raise BoundaryError("cohort_discovery_session_capacity")
    return _new_discovery(endpoint)


def _poll(endpoint,rpc,cursor,tape,result):
    if rpc.used>150:
        rpc=_rotate_discovery(endpoint,rpc,result)
    latest_header=_latest_header(rpc)
    latest=int(latest_header["number"],16)
    first=max(cursor+1,latest-9)
    fresh=[]
    if latest>=first:
        fresh=_current_curve_events(rpc,first,latest)
        tape.extend(fresh)
        if len(tape)>MAX_TAPE_EVENTS:
            del tape[:-MAX_TAPE_EVENTS]
        cursor=latest
    return rpc,cursor,fresh,latest_header


def _paper_decision(row,now):
    vector=row["vector"]
    return dict(
        asof=now,market=row["curve"],authority="frozen_policy_paper",
        qualification="qualified",policy=POLICY,policy_hash=POLICY_HASH,
        vector_asof=vector["asof"],vector_available_at=vector["evidence_available_at"],
        vector_state_age_seconds=vector["decision_state_age_seconds"],
        source_transaction=row["source_transaction"],token=row["token"],
        outcome_used_for_selection=False,
    )


def _run_lifecycle(endpoint,row,event,index):
    started=time.time()
    result=dict(
        index=index,policy=POLICY,policy_hash=POLICY_HASH,
        token=row["token"],curve=row["curve"],
        source_transaction=row["source_transaction"],
        qualification_vector=row["vector"],
        monitor=[],provider_sessions=[],started_at=started,
        take_profit_bps=TAKE_PROFIT_BPS,risk_bps=RISK_BPS,
        timeout_seconds=MAX_HOLD_SECONDS,monitor_seconds=MONITOR_SECONDS,
        entry_delay_seconds=ENTRY_DELAY_SECONDS,
        shared_allocator=False,research_only=True,paper_only=True,
    )
    db=ROOT/f"qualifier-{index:02d}.sqlite"
    if db.exists():
        db.unlink()
    store=None
    rpc=None
    try:
        # Re-authenticate immutable candidate identity from the exact qualifying event.
        from .continuation_robinhood_sample import _fast_candidate
        candidate=_fast_candidate(endpoint,event)
        candidate["report"]=dict(reads=[])
        gas_units=_gas_units(candidate["receipt"])

        rpc=paper_rpc(endpoint);rpc.verify_chain()
        initial_gas,gas_price=_gas_quote(rpc,gas_units)
        gas_budget=max(initial_gas*10,10**15)
        result["gas_model"]=dict(
            units_proxy=gas_units,current_gas_price=gas_price,
            reservation_budget=gas_budget,
        )

        now=int(row["vector"]["evidence_available_at"])
        store=Store(str(db),max_records=8192)
        experiment=f"continuation-v1-robinhood-cohort-{index}"
        paper=Paper(
            store,experiment,PAPER_CAPITAL,delay=ENTRY_DELAY_SECONDS,
            natural_policy_hash=POLICY_HASH,
        )
        identity="qualified:"+row["token"]+":"+row["source_transaction"]
        reserved=paper.reserve(
            identity,market=row["curve"],amount=PAPER_AMOUNT,
            gas_budget=gas_budget,now=now,features=_paper_decision(row,now),
            kind="natural",
        )
        result["reservation"]=reserved
        min_tokens=int(row["entry_reference"]["tokens"])*9900//10000
        result["minimum_fill_tokens"]=min_tokens

        # Same delayed-fill discipline as Solana continuation-v1.
        time.sleep(max(0,reserved["due"]-int(time.time())))
        try:
            entry,entry_meta,entry_ledger=_wait_curve_quote(
                rpc,candidate,"buy",PAPER_AMOUNT,gas_units,store,
                f"cohort-{index}-entry",reserved["due"],seconds=60,
            )
        except BoundaryError as exc:
            paper.advance(
                identity,now=max(int(time.time()),reserved["last_at"]),
                action="cancel",cancel_reason="entry_quote_unavailable:"+str(exc),
            )
            result["status"]="entry_failed"
            result["entry_failure"]="entry_quote_unavailable:"+str(exc)
            result["final_position"]=paper._get(identity)
            result["reconciliation"]=paper.reconcile()
            return result
        if entry.amount_out<min_tokens:
            paper.advance(
                identity,now=entry.stamp.observed_at,action="cancel",
                cancel_reason="entry_slippage",
            )
            result["status"]="entry_failed"
            result["entry_failure"]="entry_slippage"
            result["entry_quote"]=entry_meta
            result["final_position"]=paper._get(identity)
            result["reconciliation"]=paper.reconcile()
            return result

        opened=paper.advance(
            identity,now=entry.stamp.observed_at,action="entry",quote=entry,
            finality_ledger=entry_ledger,
        )
        result["entry"]=dict(position=opened,quote=entry_meta)

        # Restart recovery is part of every cohort lifecycle.
        before=paper.reconcile();store.close()
        store=Store(str(db),max_records=8192)
        paper=Paper(
            store,experiment,PAPER_CAPITAL,delay=ENTRY_DELAY_SECONDS,
            natural_policy_hash=POLICY_HASH,
        )
        if paper.reconcile()!=before:
            raise BoundaryError("cohort_restart_reconciliation")
        result["restart_reconciliation"]=before

        opened_at=opened["last_at"]
        last_block=entry_meta["block"]
        transition=None;v4_key=None;reason=None
        monitor_index=0

        while True:
            if rpc.used>145:
                result["provider_sessions"].append(rpc.telemetry())
                rpc=paper_rpc(endpoint);rpc.verify_chain()
            time.sleep(MONITOR_SECONDS)
            header=_latest_header(rpc)
            block=int(header["number"],16)
            position=paper._get(identity)
            elapsed=int(time.time())-opened_at

            if transition is None:
                maybe=_graduation_transition(
                    rpc,candidate,last_block,block,candidate["report"]
                )
                if maybe is not None:
                    transition,v4_key,grad_header,_=maybe
                    store.put("graduation",transition["proof_hash"],transition)
                    paper.advance(
                        identity,now=int(time.time()),action="transition",
                        transition=transition,
                    )
                    result["graduation_transition"]=dict(
                        transition=transition,
                        block=int(grad_header["number"],16),
                    )
                last_block=block

            position=paper._get(identity)
            if transition is None:
                try:
                    mark,meta=_curve_quote(
                        rpc,candidate,"sell",position["tokens"],gas_units,store,
                        f"cohort-{index}-mark-{monitor_index}",
                    )
                    ledger=None
                except BoundaryError as exc:
                    if str(exc)=="curve_graduated_requires_transition":
                        continue
                    result["monitor"].append(dict(
                        at=int(time.time()),elapsed_seconds=elapsed,
                        market="curve",available=False,reason=str(exc),
                    ))
                    monitor_index+=1
                    if elapsed<MAX_HOLD_SECONDS:
                        continue
                    result["status"]="unresolved"
                    result["boundary"]="timeout_unavailable_exit"
                    result["final_position"]=paper._get(identity)
                    result["reconciliation"]=paper.reconcile()
                    return result
            else:
                try:
                    mark,meta,ledger=_v4_quote(
                        rpc,v4_key,position["market"],position["tokens"],
                        gas_units,store,f"cohort-{index}-v4mark-{monitor_index}",
                    )
                except BoundaryError as exc:
                    result["monitor"].append(dict(
                        at=int(time.time()),elapsed_seconds=elapsed,
                        market="v4",available=False,reason=str(exc),
                    ))
                    monitor_index+=1
                    if elapsed<MAX_HOLD_SECONDS:
                        continue
                    result["status"]="unresolved"
                    result["boundary"]="timeout_unavailable_v4_exit"
                    result["final_position"]=paper._get(identity)
                    result["reconciliation"]=paper.reconcile()
                    return result

            rbps=_return_bps(position,mark)
            result["monitor"].append(dict(
                at=mark.stamp.observed_at,elapsed_seconds=elapsed,
                market=("v4" if transition else "curve"),
                available=True,return_bps=rbps,quote=meta,
            ))
            monitor_index+=1
            if rbps<=RISK_BPS:
                reason="risk"
            elif rbps>=TAKE_PROFIT_BPS:
                reason="take_profit"
            elif elapsed>=MAX_HOLD_SECONDS:
                reason="timeout"
            else:
                continue

            paper.advance(
                identity,now=mark.stamp.observed_at,action="exit_intent"
            )
            pending=paper._get(identity)
            time.sleep(max(0,pending["due"]-int(time.time())))

            # Graduation may happen during the two-second exit delay.
            if transition is None:
                try:
                    exit_quote,exit_meta,exit_ledger=_wait_curve_quote(
                        rpc,candidate,"sell",pending["tokens"],gas_units,store,
                        f"cohort-{index}-exit",pending["due"],seconds=20,
                    )
                except BoundaryError as exc:
                    if str(exc)!="curve_graduated_requires_transition":
                        result["status"]="unresolved"
                        result["boundary"]="delayed_exit_unavailable:"+str(exc)
                        result["final_position"]=paper._get(identity)
                        result["reconciliation"]=paper.reconcile()
                        return result
                    newest=_latest_header(rpc)
                    newest_block=int(newest["number"],16)
                    maybe=_graduation_transition(
                        rpc,candidate,last_block,newest_block,candidate["report"]
                    )
                    if maybe is None:
                        raise BoundaryError("graduation_transition_missing_at_exit")
                    transition,v4_key,grad_header,_=maybe
                    store.put("graduation",transition["proof_hash"],transition)
                    paper.advance(
                        identity,now=int(time.time()),action="transition",
                        transition=transition,
                    )
                    result["graduation_transition"]=dict(
                        transition=transition,
                        block=int(grad_header["number"],16),
                    )

            if transition is not None:
                deadline=time.monotonic()+20
                while True:
                    exit_quote,exit_meta,exit_ledger=_v4_quote(
                        rpc,v4_key,paper._get(identity)["market"],
                        paper._get(identity)["tokens"],gas_units,store,
                        f"cohort-{index}-v4exit",
                    )
                    if exit_quote.stamp.event_at>=paper._get(identity)["due"]:
                        break
                    if time.monotonic()>=deadline:
                        raise BoundaryError("v4_delayed_exit_quote_timeout")
                    time.sleep(0.5)

            settled=paper.advance(
                identity,now=exit_quote.stamp.observed_at,action="exit",
                quote=exit_quote,finality_ledger=exit_ledger,
            )
            result["exit"]=dict(reason=reason,quote=exit_meta,position=settled)
            result["status"]="settled"
            result["carried_through_graduation"]=transition is not None
            break

        reconciliation=paper.reconcile();store.close()
        store=Store(str(db),max_records=8192)
        paper=Paper(
            store,experiment,PAPER_CAPITAL,delay=ENTRY_DELAY_SECONDS,
            natural_policy_hash=POLICY_HASH,
        )
        if paper.reconcile()!=reconciliation:
            raise BoundaryError("cohort_final_restart_reconciliation")
        result["final_position"]=paper._get(identity)
        result["reconciliation"]=reconciliation
        result["realized_pnl_wei"]=result["final_position"]["pnl"]
        result["realized_return_bps"]=(
            result["final_position"]["pnl"]*10000//
            result["entry"]["position"]["cost"]
        )
        return result
    except BoundaryError as exc:
        result["status"]="boundary"
        result["boundary"]=str(exc)
        return result
    finally:
        if store is not None:
            try:store.close()
            except Exception:pass
        if rpc is not None:
            result["provider_sessions"].append(rpc.telemetry())
        result["ended_at"]=time.time()


def run(endpoint):
    ROOT.mkdir(exist_ok=True)
    for old in ROOT.glob("qualifier-*.sqlite*"):
        old.unlink()

    result=dict(
        kind="continuation-v1-robinhood-qualified-paper-cohort",
        policy=POLICY,policy_hash=POLICY_HASH,
        cohort_target=COHORT_TARGET,meaningful_cohort_definition="10 genuine qualifiers",
        thresholds_unchanged=True,five_second_gate_unchanged=True,
        take_profit_bps=TAKE_PROFIT_BPS,risk_bps=RISK_BPS,
        timeout_seconds=MAX_HOLD_SECONDS,monitor_seconds=MONITOR_SECONDS,
        entry_delay_seconds=ENTRY_DELAY_SECONDS,
        paper_amount_wei=PAPER_AMOUNT,paper_capital_per_trial_wei=PAPER_CAPITAL,
        selection_rule="first_previously_unseen_authentic_current_pons_v2_buy_after_prior_enrollment_attempt",
        reranking=False,replacement=False,outcome_blind=True,
        shared_allocator=False,started_at=time.time(),
        enrollments=[],qualifiers=[],lifecycles=[],discovery_sessions=[],
    )

    rpc=_new_discovery(endpoint)
    start_header=_latest_header(rpc)
    cursor=int(start_header["number"],16)
    tape=[];seen_tx_logs=set();seen_curves=set()
    warm_start=int(start_header["timestamp"],16)

    try:
        warm_deadline=time.monotonic()+TAPE_WARM_SECONDS
        while time.monotonic()<warm_deadline:
            rpc,cursor,_,latest_header=_poll(endpoint,rpc,cursor,tape,result)
            time.sleep(POLL_SECONDS)
        result["warmup"]=dict(
            start_block=int(start_header["number"],16),end_block=cursor,
            start_time=warm_start,end_time=int(latest_header["timestamp"],16),
            covered_seconds=int(latest_header["timestamp"],16)-warm_start,
            events=len(tape),
        )
        if result["warmup"]["covered_seconds"]<60:
            raise BoundaryError("cohort_tape_warmup_incomplete")

        futures=[]
        pool=ThreadPoolExecutor(max_workers=COHORT_TARGET)
        deadline=time.monotonic()+DISCOVERY_SECONDS
        while (
            time.monotonic()<deadline
            and len(result["enrollments"])<MAX_ENROLLED
            and len(result["qualifiers"])<COHORT_TARGET
        ):
            rpc,cursor,fresh,_=_poll(endpoint,rpc,cursor,tape,result)
            candidates=[]
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
                candidates.append(event)
            if not candidates:
                time.sleep(POLL_SECONDS)
                continue
            candidates.sort(key=lambda e:(
                int(e["blockNumber"],16),
                int(e["transactionIndex"],16),
                int(e["logIndex"],16),
            ))
            event=candidates[0]
            seen_curves.add(event["address"].lower())
            row=_evaluate(endpoint,event,len(result["enrollments"]),list(tape))
            result["enrollments"].append(row)
            vector=row.get("vector") or {}
            if vector.get("current_threshold_pass"):
                qindex=len(result["qualifiers"])
                qualifier=dict(
                    index=qindex,token=row["token"],curve=row["curve"],
                    source_transaction=row["source_transaction"],
                    vector=vector,enrollment_sequence=row["sequence"],
                )
                result["qualifiers"].append(qualifier)
                futures.append((
                    qindex,pool.submit(
                        _run_lifecycle,endpoint,row,event,qindex
                    )
                ))

        result["discovery_sessions"].append(rpc.telemetry())
        result["discovery_complete"]=len(result["qualifiers"])>=COHORT_TARGET
        if not result["discovery_complete"]:
            result["boundary"]="cohort_target_not_reached_within_bounded_discovery"

        # Every discovered qualifier gets a lifecycle; wait for all, including 900s timeouts.
        for qindex,future in futures:
            try:
                life=future.result()
            except Exception as exc:
                life=dict(
                    index=qindex,status="unexpected_boundary",
                    boundary=type(exc).__name__,
                )
            result["lifecycles"].append(life)
        pool.shutdown(wait=True)

    except BoundaryError as exc:
        result["boundary"]=str(exc)
        result["discovery_sessions"].append(rpc.telemetry())

    result["lifecycles"].sort(key=lambda x:x.get("index",-1))
    statuses={}
    exits={}
    realized=[]
    for life in result["lifecycles"]:
        statuses[life.get("status","unknown")]=statuses.get(life.get("status","unknown"),0)+1
        reason=(life.get("exit") or {}).get("reason")
        if reason:
            exits[reason]=exits.get(reason,0)+1
        if life.get("status")=="settled" and life.get("realized_return_bps") is not None:
            realized.append(int(life["realized_return_bps"]))
    result["summary"]=dict(
        enrolled=len(result["enrollments"]),
        complete_vectors=sum(bool((r.get("vector") or {}).get("complete")) for r in result["enrollments"]),
        genuine_qualifiers=len(result["qualifiers"]),
        cohort_target=COHORT_TARGET,
        target_reached=len(result["qualifiers"])>=COHORT_TARGET,
        lifecycle_status_counts=statuses,
        exit_reason_counts=exits,
        settled_returns_bps=realized,
        graduated_lifecycles=sum(bool(x.get("carried_through_graduation")) for x in result["lifecycles"]),
    )
    result["ended_at"]=time.time()
    return result


if __name__=="__main__":
    output=run(os.environ.get("MM_ROBINHOOD_READ_RPC_URL",""))
    raw=json.dumps(output,sort_keys=True,separators=(",",":")).encode()
    if len(raw)>8_000_000:
        raise BoundaryError("cohort_report_capacity")
    REPORT.write_bytes(raw)
    print(json.dumps(dict(
        boundary=output.get("boundary"),policy_hash=output["policy_hash"],
        summary=output["summary"],
        elapsed_seconds=round(output["ended_at"]-output["started_at"],2),
    ),sort_keys=True))
