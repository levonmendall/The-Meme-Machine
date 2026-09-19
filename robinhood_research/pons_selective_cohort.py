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
from .sequencer_feed import SequencerBlockClock
from .pons_selective_acquisition import evaluate_candidate, public_evaluation
from .pons_selective_continuation import POLICY, POLICY_HASH, wallet_convergence
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
DISCOVERY_SECONDS=14_400
TAPE_WARM_SECONDS=65
MAX_TAPE_EVENTS=40_000
MAX_CONCURRENT_LIFECYCLES=8
MIN_REEVALUATION_SECONDS=2.0
POLL_SECONDS=0.5


def _discovery(endpoint):
    rpc=configured_discovery_rpc(endpoint,limit=200,per_scope=190,retries=0)
    rpc.verify_chain()
    return rpc


def _single_block_range(rpc,start,end):
    rows=[]
    for block in range(int(start),int(end)+1):
        rows.extend(_current_curve_events(rpc,block,block))
    return rows


def _poll(endpoint,rpc,cursor,tape,feed,sessions):
    if rpc.used>150:
        sessions.append(rpc.telemetry())
        rpc=_discovery(endpoint)
    latest=_next_discovery_end(feed,cursor,rpc,timeout=POLL_SECONDS)
    if latest is None:
        return rpc,cursor,[]
    first=cursor+1;fresh=[]
    if latest>=first:
        observed_end=latest
        try:
            fresh=_current_curve_events(rpc,first,observed_end)
        except BoundaryError as exc:
            if str(exc)!="provider_rpc_-32602":
                raise
            # Robinhood's sequencer can announce L2 blocks slightly ahead of the
            # authenticated RPC frontier. Do not reinterpret the error or advance
            # the cursor. Confirm the provider frontier and consume only blocks the
            # evidence provider can already serve.
            frontier=int(
                rpc.call("eth_blockNumber",[],scope="pons_selective_frontier"),16
            )
            if frontier<first:
                return rpc,cursor,[]
            if frontier>=observed_end:
                # The provider has the full range, so isolate a range-specific
                # rejection without skipping any block or widening evidence scope.
                fresh=_single_block_range(rpc,first,observed_end)
            else:
                observed_end=min(observed_end,frontier)
                fresh=_current_curve_events(rpc,first,observed_end)
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
    # Strategy-local DBs only. Never delete other lanes' data.
    for path in ROOT.glob("trial-*.sqlite*"):
        path.unlink()

    started=time.time()
    result=dict(
        kind="pons-selective-continuation-v1-independent-cohort",
        namespace=STRATEGY_NAMESPACE,policy=POLICY,policy_hash=POLICY_HASH,
        independent_strategy=True,shared_allocator=False,live_money=False,
        cohort_target=COHORT_TARGET,max_enrolled=MAX_ENROLLED,
        selection_rule=(
            "every distinct current authenticated Pons V2 buy, with at most one "
            "evaluation per curve per 2 wall-clock seconds; no outcome reranking"
        ),
        outcome_blind=True,reranking=False,replacement=False,
        wallet_skill_namespace=STRATEGY_NAMESPACE,
        strategy_capital_quote=STRATEGY_CAPITAL_QUOTE,
        rows=[],qualifiers=[],lifecycles=[],discovery_sessions=[],
        started_at=started,
    )

    skill=WalletSkillBook(str(SKILL_DB))
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
    queue=DeadlineEvidenceQueue(limit=4096,nominal_deadline_seconds=5.0)

    try:
        warm_deadline=time.monotonic()+TAPE_WARM_SECONDS
        while time.monotonic()<warm_deadline:
            rpc,cursor,_=_poll(
                endpoint,rpc,cursor,tape,feed,result["discovery_sessions"]
            )
        covered=int(feed.state.latest_header_timestamp or 0)-int(start_ts)
        result["warmup"]=dict(
            covered_seconds=covered,events=len(tape),end_block=cursor
        )
        if covered<60:
            raise BoundaryError("selective_tape_warmup_incomplete")

        pool=ThreadPoolExecutor(max_workers=MAX_CONCURRENT_LIFECYCLES)
        futures=[]
        deadline=time.monotonic()+DISCOVERY_SECONDS
        while (
            time.monotonic()<deadline
            and len(result["rows"])<MAX_ENROLLED
            and len(result["qualifiers"])<COHORT_TARGET
        ):
            rpc,cursor,fresh=_poll(
                endpoint,rpc,cursor,tape,feed,result["discovery_sessions"]
            )
            now=time.time()
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
                queue.enqueue(event,now=now)

            scheduled=queue.pop(now=time.time(),minimum_remaining_seconds=1.0)
            if scheduled is None:
                continue
            event=scheduled["event"]
            sequence=len(result["rows"])
            try:
                evaluation=evaluate_candidate(
                    endpoint,event,list(tape),
                    strategy_capital_quote=STRATEGY_CAPITAL_QUOTE,
                    wallet_histories=None,creator_history=None,
                )
                overlay=_attach_wallet_overlay(evaluation["vector"],skill)
                public=public_evaluation(evaluation)
                public["sequence"]=sequence
                public["wallet_convergence"]=overlay
                result["rows"].append(public)
                if evaluation["vector"].get("current_threshold_pass"):
                    qindex=len(result["qualifiers"])
                    qualifier=dict(
                        index=qindex,sequence=sequence,token=evaluation["token"],
                        curve=evaluation["curve"],
                        source_transaction=evaluation["source_transaction"],
                        vector=evaluation["vector"],
                        wallet_convergence=overlay,
                    )
                    result["qualifiers"].append(qualifier)
                    futures.append((
                        qindex,pool.submit(
                            run_lifecycle,endpoint,evaluation,
                            db_path=ROOT/f"trial-{qindex:03d}.sqlite",
                        )
                    ))
            except BoundaryError as exc:
                result["rows"].append(dict(
                    sequence=sequence,status="incomplete",
                    source_transaction=event.get("transactionHash"),
                    source_block=event.get("blockNumber"),
                    boundary=str(exc),
                ))

        result["discovery_sessions"].append(rpc.telemetry())
        result["target_reached"]=len(result["qualifiers"])>=COHORT_TARGET
        if not result["target_reached"]:
            result["boundary"]="selective_cohort_target_not_reached_in_bounded_window"

        for qindex,future in futures:
            try:
                life=future.result()
            except Exception as exc:
                life=dict(
                    index=qindex,status="unexpected_boundary",
                    boundary=type(exc).__name__,
                )
            life["index"]=qindex
            result["lifecycles"].append(life)
        pool.shutdown(wait=True)
    except BoundaryError as exc:
        result["boundary"]=str(exc)
        result["discovery_sessions"].append(rpc.telemetry())
    finally:
        result["sequencer_discovery"]=feed.status()
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
