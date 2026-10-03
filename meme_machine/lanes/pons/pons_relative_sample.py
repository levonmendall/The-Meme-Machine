"""Prospective independent sample for Pons quote-relative-value research."""
import json
import os
from pathlib import Path
import time

from . import BoundaryError
from .abi import topic
from .evidence_queue import DeadlineEvidenceQueue
from .pons_natural_observation import _current_curve_events, _next_discovery_end
from .pons_relative_value import STRATEGY, evaluate_relative_candidate
from .provider_topology import configured_discovery_rpc
from .sequencer_feed import SequencerBlockClock

REPORT=Path(os.environ.get(
    "MM_PONS_RELATIVE_REPORT","pons-quote-relative-value-v1-sample.json"
))
TARGET_COMPLETE=20
MAX_ENROLLED=100
RUN_SECONDS=600
WARM_SECONDS=65
MAX_TAPE_EVENTS=40_000


def _discovery(endpoint):
    rpc=configured_discovery_rpc(endpoint,limit=200,per_scope=190,retries=0)
    rpc.verify_chain()
    return rpc


def run(endpoint):
    result=dict(
        kind=STRATEGY+"-prospective-sample",strategy=STRATEGY,
        independent_strategy=True,research_only=True,allocation_authority=False,
        outcome_blind=True,rows=[],discovery_sessions=[],started_at=time.time(),
    )
    rpc=_discovery(endpoint)
    feed=SequencerBlockClock();feed.connect()
    cursor=feed.wait_for_after(-1,timeout=5.0)
    if cursor is None:
        feed.close();raise BoundaryError("relative_sequencer_start_timeout")
    tape=[];seen=set()
    queue=DeadlineEvidenceQueue(limit=4096,nominal_deadline_seconds=5.0)
    start_ts=feed.state.latest_header_timestamp
    try:
        warm=time.monotonic()+WARM_SECONDS
        while time.monotonic()<warm:
            latest=_next_discovery_end(feed,cursor,rpc,timeout=0.5)
            if latest is None:
                continue
            first=cursor+1
            if latest>=first:
                tape.extend(_current_curve_events(rpc,first,latest))
                if len(tape)>MAX_TAPE_EVENTS:
                    del tape[:-MAX_TAPE_EVENTS]
            cursor=latest
            if rpc.used>150:
                result["discovery_sessions"].append(rpc.telemetry())
                rpc=_discovery(endpoint)
        covered=int(feed.state.latest_header_timestamp or 0)-int(start_ts or 0)
        if covered<60:
            raise BoundaryError("relative_tape_warmup_incomplete")
        result["warmup"]=dict(covered_seconds=covered,events=len(tape))

        deadline=time.monotonic()+RUN_SECONDS
        complete=0
        while (
            time.monotonic()<deadline
            and len(result["rows"])<MAX_ENROLLED
            and complete<TARGET_COMPLETE
        ):
            latest=_next_discovery_end(feed,cursor,rpc,timeout=0.5)
            if latest is None:
                continue
            first=cursor+1;fresh=[]
            if latest>=first:
                fresh=_current_curve_events(rpc,first,latest)
                tape.extend(fresh)
                if len(tape)>MAX_TAPE_EVENTS:
                    del tape[:-MAX_TAPE_EVENTS]
            cursor=latest
            if rpc.used>150:
                result["discovery_sessions"].append(rpc.telemetry())
                rpc=_discovery(endpoint)
            for event in fresh:
                identity=(event["transactionHash"],event["logIndex"])
                if identity in seen:
                    continue
                seen.add(identity)
                if (
                    event.get("topics")
                    and event["topics"][0].lower()==topic(
                        "CurveBuy(address,address,uint256,uint256,uint256,uint256)"
                    )
                ):
                    queue.enqueue(event,now=time.time())
            scheduled=queue.pop(now=time.time(),minimum_remaining_seconds=1.0)
            if scheduled is None:
                continue
            event=scheduled["event"]
            try:
                row=evaluate_relative_candidate(endpoint,event,list(tape))
                row["sequence"]=len(result["rows"])
                result["rows"].append(row);complete+=1
            except BoundaryError as exc:
                if str(exc)=="relative_value_requires_non_native_quote":
                    continue
                result["rows"].append(dict(
                    sequence=len(result["rows"]),status="incomplete",
                    source_transaction=event.get("transactionHash"),
                    boundary=str(exc),
                ))
        result["discovery_sessions"].append(rpc.telemetry())
        result["summary"]=dict(
            evaluated=len(result["rows"]),
            complete=sum("vector" in row for row in result["rows"]),
            candidates=sum(
                bool((row.get("vector") or {}).get("candidate"))
                for row in result["rows"]
            ),
        )
    except BoundaryError as exc:
        result["boundary"]=str(exc)
        result.setdefault("summary",dict(evaluated=len(result["rows"]),complete=0,candidates=0))
    finally:
        result["sequencer_discovery"]=feed.status();feed.close()
    result["ended_at"]=time.time()
    return result


if __name__=="__main__":
    output=run(os.environ.get("MM_ROBINHOOD_READ_RPC_URL",""))
    raw=json.dumps(output,sort_keys=True,separators=(",",":")).encode()
    if len(raw)>4_000_000:
        raise BoundaryError("relative_report_capacity")
    REPORT.write_bytes(raw)
    print(json.dumps(dict(
        boundary=output.get("boundary"),summary=output["summary"]
    ),sort_keys=True))
