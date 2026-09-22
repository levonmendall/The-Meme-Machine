"""Prospective independent natural cohort for Pons Selective Continuation v1.

The cohort does not read or write any other strategy's state.  It owns a dedicated
result directory, dedicated wallet-skill ledger, dedicated paper databases, policy
hash, qualification rows and lifecycle outcomes.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import time

from . import BoundaryError
from .abi import topic
from .evidence_queue import DeadlineEvidenceQueue
from .pons_natural_observation import (
    _current_curve_events, _next_discovery_end,
)
from .provider_topology import configured_discovery_rpc
from .sequencer_feed import SequencerBlockClock, SequencerTransportError
from .pons_selective_acquisition import (
    SelectiveEvidenceContext, evaluate_candidate, public_evaluation,
)
from .pons_selective_continuation import (
    POLICY, POLICY_HASH, REENTRY_POLICY, reentry_regime_reset, wallet_convergence,
)
from .pons_selective_paper import (
    STRATEGY_CAPITAL_QUOTE, STRATEGY_NAMESPACE, run_lifecycle,
)
from .pons_selective_wallets import WalletSkillBook

REPORT=Path(os.environ.get(
    "MM_PONS_SELECTIVE_COHORT_REPORT","pons-selective-continuation-v1-cohort.json"
))
ROOT=Path(os.environ.get(
    "MM_PONS_SELECTIVE_COHORT_DIR","pons-selective-continuation-v1-cohort"
))
SKILL_DB=ROOT/"pons-selective-wallet-skill.sqlite"

COHORT_TARGET=100
MAX_ENROLLED=20_000
DISCOVERY_SECONDS=int(os.environ.get("MM_PONS_SELECTIVE_DISCOVERY_SECONDS","14400"))
if not 60<=DISCOVERY_SECONDS<=14_400:
    raise BoundaryError("invalid_pons_selective_discovery_seconds")
TAPE_WARM_SECONDS=65
TAPE_WARM_REQUIRED_CHAIN_SECONDS=60
TAPE_WARM_MAX_SECONDS=120
MAX_TAPE_EVENTS=40_000
MAX_CONCURRENT_LIFECYCLES=8
MIN_REEVALUATION_SECONDS=2.0
POLL_SECONDS=0.5
CHECKPOINT_SECONDS=15.0
SEQUENCER_RECONNECT_ATTEMPTS=5
SEQUENCER_RECONNECT_SLEEP_SECONDS=0.5
PROVIDER_RECOVERY_ATTEMPTS=3
PROVIDER_RECOVERY_SLEEP_SECONDS=0.5
PROVIDER_RATE_LIMIT_ATTEMPTS=5
PROVIDER_RATE_LIMIT_BASE_SLEEP_SECONDS=2.0
RATE_LIMIT_PROVIDER_BOUNDARIES=frozenset((
    "provider_http_429",
    "provider_rpc_429",
))
RECOVERABLE_PROVIDER_BOUNDARIES=frozenset((
    "provider_http_500",
    "provider_http_502",
    "provider_http_503",
    "provider_http_504",
    "provider_transport_failure",
))
PROGRESS=ROOT/"cohort-progress.json"
ROWS_LOG=ROOT/"candidate-rows.jsonl"
QUALIFIERS_LOG=ROOT/"qualifiers.jsonl"
PROVIDER_LOG=ROOT/"provider-sessions.jsonl"
RECOVERY_LOG=ROOT/"sequencer-recoveries.jsonl"


def _append_jsonl(path,row):
    encoded=json.dumps(row,sort_keys=True,separators=(",",":"))
    with path.open("a",encoding="utf-8") as handle:
        handle.write(encoded+"\n")
        handle.flush()
        os.fsync(handle.fileno())


def _atomic_json(path,row):
    raw=json.dumps(row,sort_keys=True,separators=(",",":")).encode()
    if len(raw)>4_000_000:
        raise BoundaryError("selective_checkpoint_capacity")
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_bytes(raw)
    os.replace(tmp,path)


def _summary_snapshot(result):
    rejection_counts={}
    for row in result["rows"]:
        vector=row.get("vector") or {}
        for reason in vector.get("all_rejections") or []:
            rejection_counts[reason]=rejection_counts.get(reason,0)+1
    lifecycle_status_counts={}
    realized=[]
    for life in result["lifecycles"]:
        status=life.get("status","unknown")
        lifecycle_status_counts[status]=lifecycle_status_counts.get(status,0)+1
        if life.get("realized_pnl_quote") is not None:
            realized.append(int(life["realized_pnl_quote"]))
    return dict(
        enrolled=len(result["rows"]),
        qualified=len(result["qualifiers"]),
        qualifiers_with_wallet_convergence=sum(
            bool(q["wallet_convergence"].get("converged"))
            for q in result["qualifiers"]
        ),
        lifecycle_status_counts=dict(sorted(lifecycle_status_counts.items())),
        rejection_counts=dict(sorted(rejection_counts.items())),
        realized_pnl_quote=realized,
        graduated_lifecycles=sum(
            bool(x.get("carried_through_graduation"))
            for x in result["lifecycles"]
        ),
    )


def _checkpoint(result,*,cursor,feed,rpc,phase):
    active_provider=rpc.telemetry()
    snapshot=dict(
        kind="pons-selective-continuation-v1-checkpoint",
        namespace=STRATEGY_NAMESPACE,
        policy=POLICY,
        policy_hash=POLICY_HASH,
        independent_strategy=True,
        shared_allocator=False,
        live_money=False,
        checkpoint_at=time.time(),
        phase=str(phase),
        started_at=result["started_at"],
        canonical_discovery_cursor=int(cursor),
        summary=_summary_snapshot(result),
        discovery_sessions=list(result["discovery_sessions"]),
        active_discovery_provider=active_provider,
        sequencer_recoveries=list(result.get("sequencer_recoveries") or []),
        sequencer_discovery=feed.status(),
        warmup=result.get("warmup"),
        target_reached=result.get("target_reached"),
        boundary=result.get("boundary"),
        persisted_candidate_rows=len(result["rows"]),
        persisted_qualifiers=len(result["qualifiers"]),
    )
    _atomic_json(PROGRESS,snapshot)
    return snapshot


def _recover_sequencer(feed,cursor,recoveries):
    last=None
    for attempt in range(1,SEQUENCER_RECONNECT_ATTEMPTS+1):
        try:
            feed.reconnect()
            anchor=feed.wait_for_after(-1,timeout=5.0)
            if anchor is None:
                raise SequencerTransportError("sequencer_reconnect_no_anchor")
        except SequencerTransportError as exc:
            last=str(exc)
            if attempt<SEQUENCER_RECONNECT_ATTEMPTS:
                time.sleep(SEQUENCER_RECONNECT_SLEEP_SECONDS)
            continue
        row=dict(
            recovered_at=time.time(),
            attempt=attempt,
            canonical_cursor_before=int(cursor),
            sequencer_anchor=int(anchor),
            canonical_cursor_advanced=False,
            catchup_authority="authenticated_discovery_rpc",
            catchup_from=int(cursor)+1,
            catchup_to=int(anchor),
        )
        recoveries.append(row)
        _append_jsonl(RECOVERY_LOG,row)
        return int(anchor)
    raise BoundaryError("sequencer_reconnect_exhausted:"+str(last or "unknown"))


def _discovery(endpoint):
    rpc=configured_discovery_rpc(endpoint,limit=200,per_scope=190,retries=0)
    rpc.verify_chain()
    return rpc


def _recoverable_provider_boundary(exc):
    boundary=str(exc)
    return (
        boundary in RECOVERABLE_PROVIDER_BOUNDARIES
        or boundary in RATE_LIMIT_PROVIDER_BOUNDARIES
    )


def _recover_discovery(
    endpoint,rpc,cursor,sessions,recoveries,*,on_failure=None,
):
    """Rotate only after a proven transient provider/session boundary."""
    boundary=str(getattr(rpc,"_last_boundary","") or "provider_session_failure")
    telemetry=dict(rpc.telemetry())
    telemetry["terminal_boundary"]=boundary
    sessions.append(telemetry)
    _append_jsonl(PROVIDER_LOG,telemetry)
    if on_failure is not None:
        on_failure(rpc,boundary,int(cursor))

    rate_limited=boundary in RATE_LIMIT_PROVIDER_BOUNDARIES
    pacer=getattr(rpc,"pacer",None)
    rps_before=(
        None if pacer is None
        else float(getattr(pacer,"requests_per_second",0) or 0)
    )
    if rate_limited and pacer is not None and rps_before:
        pacer.slow_to(max(1.0,rps_before/2.0))
    rps_after=(
        None if pacer is None
        else float(getattr(pacer,"requests_per_second",0) or 0)
    )

    last=boundary
    attempts=(
        PROVIDER_RATE_LIMIT_ATTEMPTS
        if rate_limited else PROVIDER_RECOVERY_ATTEMPTS
    )
    for attempt in range(1,attempts+1):
        if rate_limited:
            time.sleep(PROVIDER_RATE_LIMIT_BASE_SLEEP_SECONDS*attempt)
        elif attempt>1:
            time.sleep(PROVIDER_RECOVERY_SLEEP_SECONDS)
        try:
            replacement=_discovery(endpoint)
        except BoundaryError as exc:
            last=str(exc)
            if not _recoverable_provider_boundary(exc):
                raise
            if str(exc) in RATE_LIMIT_PROVIDER_BOUNDARIES:
                rate_limited=True
                attempts=max(attempts,PROVIDER_RATE_LIMIT_ATTEMPTS)
            continue
        row=dict(
            kind=("provider_rate_limit_recovery" if rate_limited else "provider_recovery"),
            recovered_at=time.time(),
            attempt=attempt,
            boundary=boundary,
            canonical_cursor_before=int(cursor),
            canonical_cursor_advanced=False,
            catchup_authority="authenticated_discovery_rpc",
            catchup_from=int(cursor)+1,
            rate_limited=bool(rate_limited),
            pacer_rps_before=rps_before,
            pacer_rps_after=rps_after,
        )
        recoveries.append(row)
        _append_jsonl(RECOVERY_LOG,row)
        return replacement
    raise BoundaryError("provider_recovery_exhausted:"+str(last))


def _single_block_range(rpc,start,end):
    rows=[]
    for block in range(int(start),int(end)+1):
        rows.extend(_current_curve_events(rpc,block,block))
    return rows


def _read_curve_range(rpc,first,observed_end):
    try:
        return observed_end,_current_curve_events(rpc,first,observed_end)
    except BoundaryError as exc:
        if str(exc)!="provider_rpc_-32602":
            raise
        frontier=int(
            rpc.call("eth_blockNumber",[],scope="pons_selective_frontier"),16
        )
        if frontier<first:
            return first-1,[]
        if frontier>=observed_end:
            return observed_end,_single_block_range(rpc,first,observed_end)
        observed_end=min(observed_end,frontier)
        return observed_end,_current_curve_events(rpc,first,observed_end)


def _poll(
    endpoint,rpc,cursor,tape,feed,sessions,recoveries=None,
    on_provider_failure=None,
):
    if recoveries is None:
        recoveries=[]
    if rpc.used>150:
        telemetry=rpc.telemetry()
        sessions.append(telemetry)
        _append_jsonl(PROVIDER_LOG,telemetry)
        rpc=_discovery(endpoint)

    while True:
        try:
            latest=_next_discovery_end(feed,cursor,rpc,timeout=POLL_SECONDS)
            break
        except SequencerTransportError:
            _recover_sequencer(feed,cursor,recoveries)
            continue
        except BoundaryError as exc:
            if not _recoverable_provider_boundary(exc):
                raise
            rpc._last_boundary=str(exc)
            rpc=_recover_discovery(
                endpoint,rpc,cursor,sessions,recoveries,
                on_failure=on_provider_failure,
            )

    if latest is None:
        return rpc,cursor,[]
    first=cursor+1;fresh=[]
    if latest>=first:
        observed_end=latest
        while True:
            try:
                observed_end,fresh=_read_curve_range(rpc,first,observed_end)
                break
            except BoundaryError as exc:
                if not _recoverable_provider_boundary(exc):
                    raise
                rpc._last_boundary=str(exc)
                rpc=_recover_discovery(
                    endpoint,rpc,cursor,sessions,recoveries,
                    on_failure=on_provider_failure,
                )
        if observed_end<first:
            return rpc,cursor,[]
        tape.extend(fresh)
        if len(tape)>MAX_TAPE_EVENTS:
            del tape[:-MAX_TAPE_EVENTS]
        cursor=observed_end
    return rpc,cursor,fresh


def _attach_wallet_overlay(vector,skill_book):
    profiles=skill_book.profiles(asof=int(vector["asof"]))
    overlay=wallet_convergence(
        profiles,vector["demand"].get("recent_buy_groups",()),
        asof=int(vector["asof"]),candidate_related_groups=(),
    )
    vector["wallet_convergence"]=overlay
    return overlay


def run(endpoint):
    ROOT.mkdir(parents=True,exist_ok=True)
    # Strategy-local artifacts only. Never delete other lanes' data.
    for path in ROOT.glob("trial-*.sqlite*"):
        path.unlink()
    for path in (PROGRESS,ROWS_LOG,QUALIFIERS_LOG,PROVIDER_LOG,RECOVERY_LOG,REPORT):
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    started=time.time()
    result=dict(
        kind="pons-selective-continuation-v1-independent-cohort",
        namespace=STRATEGY_NAMESPACE,policy=POLICY,policy_hash=POLICY_HASH,
        independent_strategy=True,shared_allocator=False,live_money=False,
        cohort_target=COHORT_TARGET,max_enrolled=MAX_ENROLLED,
        selection_rule=(
            "every distinct current authenticated Pons V2 buy, with at most one "
            "evaluation per curve per 2 wall-clock seconds; paper entry requires "
            "profitability-v1 qualification and a terminal/flat prior same-curve "
            "lifecycle plus a point-in-time regime reset; no outcome reranking"
        ),
        reentry_policy=dict(REENTRY_POLICY),
        outcome_blind=True,reranking=False,replacement=False,
        wallet_skill_namespace=STRATEGY_NAMESPACE,
        strategy_capital_quote=STRATEGY_CAPITAL_QUOTE,
        rows=[],qualifiers=[],lifecycles=[],discovery_sessions=[],
        sequencer_recoveries=[],evidence_acquisition=None,started_at=started,
    )

    skill=WalletSkillBook(str(SKILL_DB))
    evidence_context=SelectiveEvidenceContext(endpoint)
    rpc=_discovery(endpoint)
    feed=SequencerBlockClock();feed.connect()
    cursor=feed.wait_for_after(-1,timeout=5.0)
    if cursor is None:
        skill.close();feed.close()
        raise BoundaryError("selective_sequencer_start_timeout")

    start_ts=feed.state.latest_header_timestamp
    if start_ts is None:
        skill.close();feed.close()
        raise BoundaryError("selective_sequencer_timestamp_missing")
    tape=[];last_eval={};seen_event=set()
    first_observed_monotonic={}
    queue=DeadlineEvidenceQueue(limit=4096,nominal_deadline_seconds=5.0)

    def _checkpoint_provider_failure(failed_rpc,boundary,current_cursor):
        result["last_transient_provider_boundary"]=str(boundary)
        _checkpoint(
            result,cursor=current_cursor,feed=feed,rpc=failed_rpc,
            phase="provider_recovery",
        )

    try:
        warm_started=time.monotonic()
        warm_min_deadline=warm_started+TAPE_WARM_SECONDS
        warm_hard_deadline=warm_started+TAPE_WARM_MAX_SECONDS
        covered=0
        while time.monotonic()<warm_hard_deadline:
            rpc,cursor,_=_poll(
                endpoint,rpc,cursor,tape,feed,result["discovery_sessions"],
                result["sequencer_recoveries"],
                on_provider_failure=_checkpoint_provider_failure,
            )
            covered=int(feed.state.latest_header_timestamp or 0)-int(start_ts)
            if (time.monotonic()>=warm_min_deadline
                    and covered>=TAPE_WARM_REQUIRED_CHAIN_SECONDS):
                break
        result["warmup"]=dict(
            covered_seconds=covered,events=len(tape),end_block=cursor,
            wall_seconds=max(0.0,time.monotonic()-warm_started),
            required_chain_seconds=TAPE_WARM_REQUIRED_CHAIN_SECONDS,
            maximum_wall_seconds=TAPE_WARM_MAX_SECONDS,
        )
        _checkpoint(result,cursor=cursor,feed=feed,rpc=rpc,phase="warmup_complete")
        if covered<TAPE_WARM_REQUIRED_CHAIN_SECONDS:
            raise BoundaryError("selective_tape_warmup_incomplete")

        pool=ThreadPoolExecutor(max_workers=MAX_CONCURRENT_LIFECYCLES)
        futures=[]
        active_curve_futures={}
        last_authorized_vector={}
        last_terminal_by_curve={}
        collected_futures=set()

        def collect_curve_future(curve):
            item=active_curve_futures.get(curve)
            if item is None:
                return None
            qindex,future=item
            if not future.done():
                return None
            try:
                life=future.result()
            except Exception as exc:
                life=dict(
                    index=qindex,status="unexpected_boundary",
                    boundary=type(exc).__name__,
                )
            life["index"]=qindex
            result["lifecycles"].append(life)
            last_terminal_by_curve[curve]=life
            collected_futures.add(id(future))
            active_curve_futures.pop(curve,None)
            return life

        deadline=time.monotonic()+DISCOVERY_SECONDS
        next_checkpoint=time.monotonic()+CHECKPOINT_SECONDS
        while (
            time.monotonic()<deadline
            and len(result["rows"])<MAX_ENROLLED
            and len(result["qualifiers"])<COHORT_TARGET
        ):
            rpc,cursor,fresh=_poll(
                endpoint,rpc,cursor,tape,feed,result["discovery_sessions"],
                result["sequencer_recoveries"],
                on_provider_failure=_checkpoint_provider_failure,
            )
            now=time.time()
            now_monotonic=time.monotonic()
            for event in fresh:
                identity=(event["transactionHash"],event["logIndex"])
                if identity in seen_event:
                    continue
                seen_event.add(identity)
                if (
                    not event.get("topics")
                    or event["topics"][0].lower()!=topic(
                        "CurveBuy(address,address,uint256,uint256,uint256,uint256)"
                    )
                ):
                    continue
                curve=event["address"].lower()
                if now-last_eval.get(curve,0)<MIN_REEVALUATION_SECONDS:
                    continue
                last_eval[curve]=now
                if queue.enqueue(event,now=now):
                    first_observed_monotonic[identity]=now_monotonic

            if time.monotonic()>=next_checkpoint:
                _checkpoint(
                    result,cursor=cursor,feed=feed,rpc=rpc,phase="discovery"
                )
                next_checkpoint=time.monotonic()+CHECKPOINT_SECONDS
            scheduled=queue.pop(now=time.time(),minimum_remaining_seconds=1.0)
            if scheduled is None:
                continue
            event=scheduled["event"]
            sequence=len(result["rows"])
            observation_key=(event["transactionHash"],event["logIndex"])
            observed_monotonic=first_observed_monotonic.pop(
                observation_key,None
            )
            if observed_monotonic is None:
                raise BoundaryError("missing_evidence_observation_clock")
            observed_at=float(scheduled["queued_at"])
            try:
                evaluation=evaluate_candidate(
                    endpoint,event,list(tape),
                    strategy_capital_quote=STRATEGY_CAPITAL_QUOTE,
                    wallet_histories=None,creator_history=None,
                    evidence_observed_at=observed_at,
                    evidence_observed_monotonic=observed_monotonic,
                    evidence_context=evidence_context,
                )
                overlay=_attach_wallet_overlay(evaluation["vector"],skill)
                public=public_evaluation(evaluation)
                public["sequence"]=sequence
                public["wallet_convergence"]=overlay
                authorization_rejection=None
                curve=evaluation["curve"]
                if evaluation["vector"].get("current_threshold_pass"):
                    completed=collect_curve_future(curve)
                    active=active_curve_futures.get(curve)
                    if active is not None and not active[1].done():
                        authorization_rejection="same_curve_lifecycle_active"
                    elif curve in last_authorized_vector:
                        terminal=last_terminal_by_curve.get(curve)
                        terminal_status=(terminal or {}).get("status")
                        terminal_reconciliation=(terminal or {}).get("reconciliation") or {}
                        terminal_flat=bool(
                            terminal_status in ("settled","entry_failed")
                            and int(terminal_reconciliation.get("open_exposure",0) or 0)==0
                        )
                        if not terminal_flat:
                            authorization_rejection="prior_curve_lifecycle_not_flat"
                        elif not reentry_regime_reset(
                            last_authorized_vector[curve],evaluation["vector"]
                        ):
                            authorization_rejection="reentry_regime_not_reset"
                if authorization_rejection is not None:
                    public["live_authorization"]="rejected"
                    public["authorization_rejection"]=authorization_rejection
                elif evaluation["vector"].get("current_threshold_pass"):
                    public["live_authorization"]="authorized"

                result["rows"].append(public)
                result["evidence_acquisition"]=evidence_context.telemetry()
                _append_jsonl(ROWS_LOG,public)
                if (
                    evaluation["vector"].get("current_threshold_pass")
                    and authorization_rejection is None
                ):
                    qindex=len(result["qualifiers"])
                    qualifier=dict(
                        index=qindex,sequence=sequence,token=evaluation["token"],
                        curve=curve,
                        source_transaction=evaluation["source_transaction"],
                        vector=evaluation["vector"],
                        wallet_convergence=overlay,
                        live_authorization="authorized",
                    )
                    result["qualifiers"].append(qualifier)
                    _append_jsonl(QUALIFIERS_LOG,qualifier)
                    _checkpoint(
                        result,cursor=cursor,feed=feed,rpc=rpc,
                        phase="qualifier_persisted",
                    )
                    next_checkpoint=time.monotonic()+CHECKPOINT_SECONDS
                    future=pool.submit(
                        run_lifecycle,endpoint,evaluation,
                        db_path=ROOT/f"trial-{qindex:03d}.sqlite",
                    )
                    futures.append((qindex,future))
                    active_curve_futures[curve]=(qindex,future)
                    last_authorized_vector[curve]=evaluation["vector"]
            except BoundaryError as exc:
                incomplete=dict(
                    sequence=sequence,status="incomplete",
                    source_transaction=event.get("transactionHash"),
                    source_block=event.get("blockNumber"),
                    boundary=str(exc),
                )
                result["rows"].append(incomplete)
                result["evidence_acquisition"]=evidence_context.telemetry()
                _append_jsonl(ROWS_LOG,incomplete)

        terminal_provider=rpc.telemetry()
        result["discovery_sessions"].append(terminal_provider)
        _append_jsonl(PROVIDER_LOG,terminal_provider)
        result["target_reached"]=len(result["qualifiers"])>=COHORT_TARGET
        if not result["target_reached"]:
            result["boundary"]="selective_cohort_target_not_reached_in_bounded_window"

        for curve in list(active_curve_futures):
            collect_curve_future(curve)
        for qindex,future in futures:
            if id(future) in collected_futures:
                continue
            try:
                life=future.result()
            except Exception as exc:
                life=dict(
                    index=qindex,status="unexpected_boundary",
                    boundary=type(exc).__name__,
                )
            life["index"]=qindex
            result["lifecycles"].append(life)
            collected_futures.add(id(future))
        pool.shutdown(wait=True)
    except BoundaryError as exc:
        result["boundary"]=str(exc)
        terminal_provider=rpc.telemetry()
        result["discovery_sessions"].append(terminal_provider)
        _append_jsonl(PROVIDER_LOG,terminal_provider)
    finally:
        result["evidence_acquisition"]=evidence_context.telemetry()
        result["sequencer_discovery"]=feed.status()
        _checkpoint(
            result,cursor=cursor,feed=feed,rpc=rpc,phase="finalizing"
        )
        feed.close();skill.close()

    result["lifecycles"].sort(key=lambda row:row.get("index",-1))
    counts={}
    for row in result["rows"]:
        vector=row.get("vector") or {}
        for reason in vector.get("all_rejections") or []:
            counts[reason]=counts.get(reason,0)+1
    statuses={}
    returns=[]
    for life in result["lifecycles"]:
        status=life.get("status","unknown")
        statuses[status]=statuses.get(status,0)+1
        if life.get("realized_pnl_quote") is not None:
            returns.append(int(life["realized_pnl_quote"]))
    result["summary"]=dict(
        enrolled=len(result["rows"]),
        qualified=len(result["qualifiers"]),
        qualifiers_with_wallet_convergence=sum(
            bool(q["wallet_convergence"].get("converged"))
            for q in result["qualifiers"]
        ),
        lifecycle_status_counts=statuses,
        rejection_counts=dict(sorted(counts.items())),
        realized_pnl_quote=returns,
        graduated_lifecycles=sum(
            bool(x.get("carried_through_graduation"))
            for x in result["lifecycles"]
        ),
    )
    result["ended_at"]=time.time()
    return result


if __name__=="__main__":
    output=run(os.environ.get("MM_ROBINHOOD_READ_RPC_URL",""))
    raw=json.dumps(output,sort_keys=True,separators=(",",":")).encode()
    if len(raw)>12_000_000:
        raise BoundaryError("selective_cohort_report_capacity")
    REPORT.write_bytes(raw)
    print(json.dumps(dict(
        policy_hash=output["policy_hash"],boundary=output.get("boundary"),
        summary=output["summary"],
        elapsed_seconds=round(output["ended_at"]-output["started_at"],2),
    ),sort_keys=True))
