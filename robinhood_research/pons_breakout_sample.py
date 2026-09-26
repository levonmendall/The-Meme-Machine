"""Independent research-only Pons post-graduation breakout observer.

This is a separate strategy from Pons Selective Continuation v1.  It discovers Pons
graduations directly from the factory, proves V2->V4 lineage, waits for a genuine
pullback/settling phase, and then tests a second-wave breakout prospectively.
It has no paper allocation or re-entry authority.
"""
import json
import os
from pathlib import Path
import time

from . import BoundaryError
from .abi import calldata, scalar, signature, topic, words
from .identity import authenticate, load
from .pons import authenticate_curve, factory_record, raw_event
from .pons_natural_paper import (\n    V4_QUOTER, _graduation_transition, _one_word, _rpc as paper_rpc,\n    _v4_quoter_calldata,\n)
from .pons_selective_acquisition import _header_search, _rpc as evidence_rpc
from .pons_selective_continuation import ZERO, breakout_vector
from .pons_selective_v4 import collect_v4_activity
from .pons_natural_observation import _latest_header
from .protocols import PoolKey
from .provider_topology import configured_discovery_rpc
from .sequencer_feed import SequencerBlockClock

REPORT=Path(os.environ.get(
    "MM_PONS_BREAKOUT_REPORT","pons-post-graduation-breakout-v1.json"
))
STRATEGY="pons-post-graduation-breakout-v1"
DISCOVERY_SECONDS=600
MONITOR_SECONDS=900
WINDOW_SECONDS=15
POLL_SECONDS=5


def _event_topic(role,name):
    abi=load(role)["abi"]
    rows=[x for x in abi if x.get("type")=="event" and x.get("name")==name]
    if len(rows)!=1:
        raise BoundaryError("breakout_event_abi")
    return topic(signature(rows[0]))


def _discovery(endpoint):
    rpc=configured_discovery_rpc(endpoint,limit=200,per_scope=190,retries=0)
    rpc.verify_chain()
    return rpc


def _factory_record_at(rpc,token,block):
    from .abi import calldata
    factory=load("pons_v2_factory")["address"].lower()
    raw=rpc.call(
        "eth_call",[dict(to=factory,data=calldata("getLaunchedToken(address)",token)),hex(block)],
        scope="pons_breakout",
    )
    return factory_record(raw,"pons_v2_factory")


def _discover_graduation(endpoint):
    discovery=_discovery(endpoint)
    feed=SequencerBlockClock();feed.connect()
    cursor=feed.wait_for_after(-1,timeout=5.0)
    if cursor is None:
        feed.close()
        raise BoundaryError("breakout_sequencer_start_timeout")
    factory=load("pons_v2_factory")["address"].lower()
    grad_topic=_event_topic("pons_v2_factory","PoolGraduated")
    deadline=time.monotonic()+DISCOVERY_SECONDS
    sessions=[]
    try:
        while time.monotonic()<deadline:
            latest=feed.wait_for_range_after(
                cursor,timeout=1.0,max_blocks=10,coalesce_seconds=0.2
            )
            if latest is None:
                continue
            start=cursor+1;cursor=latest
            if latest<start:
                continue
            if discovery.used>150:
                sessions.append(discovery.telemetry());discovery=_discovery(endpoint)
            rows=discovery.call(
                "eth_getLogs",[dict(
                    fromBlock=hex(start),toBlock=hex(latest),
                    address=factory,topics=[grad_topic],
                )],scope="pons_breakout",
            )
            for event in rows:
                rpc=paper_rpc(endpoint);rpc.verify_chain()
                header=rpc.call(
                    "eth_getBlockByHash",[event["blockHash"],False],scope="pons_breakout"
                )
                receipt=rpc.receipt(
                    event["transactionHash"],event["blockHash"],scope="pons_breakout"
                )
                decoded=raw_event(
                    load("pons_v2_factory")["abi"],event,address=factory,
                    receipt=receipt,header=header,observed_at=int(time.time()),
                    confirmation="confirmed",
                )
                if decoded["decoded"]["name"]!="PoolGraduated":
                    continue
                token=decoded["decoded"]["args"]["token"]
                block=int(event["blockNumber"],16)
                record=_factory_record_at(rpc,token,block)
                code=rpc.call(
                    "eth_getCode",[record["curve"],hex(block)],scope="pons_breakout"
                )
                authenticate_curve(record["curve"],code,factory_record=record)
                candidate=dict(
                    token=token,curve=record["curve"],report=dict(reads=[])
                )
                proven=_graduation_transition(
                    rpc,candidate,block,block,candidate["report"]
                )
                if proven is None:
                    raise BoundaryError("breakout_graduation_proof_missing")
                transition,key,grad_header,record=proven
                sessions.extend([discovery.telemetry(),rpc.telemetry()])
                return dict(
                    candidate=candidate,transition=transition,key=key,
                    graduation_header=grad_header,record=record,
                    source_transaction=event["transactionHash"],
                    sessions=sessions,
                )
        raise BoundaryError("no_current_pons_graduation")
    finally:
        feed.close()


def run(endpoint):
    result=dict(
        kind=STRATEGY,strategy=STRATEGY,research_only=True,
        allocation_authority=False,independent_strategy=True,
        source_strategy=None,paper_only=True,live_money=False,
        shadow_notional_quote=SHADOW_NOTIONAL_QUOTE,
        forward_horizons_seconds=list(FORWARD_HORIZONS_SECONDS),
        started_at=time.time(),observations=[],provider_sessions=[],
    )
    try:
        discovered=_discover_graduation(endpoint)
        result["provider_sessions"].extend(discovered.pop("sessions"))
        transition=discovered["transition"];key=discovered["key"]
        grad=discovered["graduation_header"]
        grad_block=int(grad["number"],16);grad_at=int(grad["timestamp"],16)
        result["graduation"]=dict(
            token=discovered["candidate"]["token"],
            curve=discovered["candidate"]["curve"],
            pool_id=transition["market"],block=grad_block,event_at=grad_at,
            source_transaction=discovered["source_transaction"],
            transition=transition,
        )

        seen_buyers=set();peak=None;consolidation_high=None
        max_pullback_seen=0;previous_buy=0
        deadline=time.monotonic()+MONITOR_SECONDS
        while time.monotonic()<deadline:
            time.sleep(POLL_SECONDS)
            rpc=evidence_rpc(endpoint)
            header=_latest_header(rpc)
            current_block=int(header["number"],16)
            current_at=int(header["timestamp"],16)
            cache={current_block:header}
            start_header=_header_search(
                rpc,current_block,current_at,max(grad_at,current_at-WINDOW_SECONDS),cache
            )
            result["provider_sessions"].append(rpc.telemetry())
            activity=collect_v4_activity(
                endpoint,pool_id=transition["market"],key=key,
                token=discovered["candidate"]["token"],
                start_block=max(grad_block,int(start_header["number"],16)),
                end_block=current_block,preholder_groups=(),
            )
            result["provider_sessions"].extend(activity.pop("provider_sessions"))
            current=activity["last_price_index"]
            if current is None:
                result["observations"].append(dict(
                    at=current_at,block=current_block,swaps=0,candidate=False
                ))
                previous_buy=0
                continue
            peak=current if peak is None else max(peak,current)
            pullback=(peak-current)*10_000//max(1,peak)
            max_pullback_seen=max(max_pullback_seen,pullback)
            new_buyers=len(set(activity["buyer_groups"])-seen_buyers)
            seen_buyers.update(activity["buyer_groups"])

            prior_consolidation_high=(
                current if consolidation_high is None else consolidation_high
            )
            vector=breakout_vector(
                seconds_after_graduation=current_at-grad_at,
                pullback_bps=max_pullback_seen,current_price_index=current,
                consolidation_high_index=prior_consolidation_high,
                new_independent_buyers_15s=new_buyers,
                buy_quote_15s=activity["buy_quote"],
                sell_quote_15s=activity["sell_quote"],
                previous_buy_quote_15s=previous_buy,
            )
            observation=dict(
                at=current_at,block=current_block,price_index=current,
                peak_price_index=peak,pullback_bps=pullback,
                max_pullback_seen_bps=max_pullback_seen,
                consolidation_high_index=prior_consolidation_high,
                new_independent_buyers_15s=new_buyers,
                activity=activity,vector=vector,
            )
            result["observations"].append(observation)
            previous_buy=activity["buy_quote"]

            if consolidation_high is None:
                if max_pullback_seen>=500:
                    consolidation_high=current
                continue
            if vector["candidate"]:
                result["signal"]=observation
                try:
                    entry=_shadow_v4_quote(
                        endpoint,key,transition["market"],
                        SHADOW_NOTIONAL_QUOTE,side="buy",
                    )
                    result["provider_sessions"].extend(
                        entry.pop("provider_sessions")
                    )
                    result["shadow_entry_quote"]=entry
                    started=time.monotonic()
                    marks=[]
                    for horizon in FORWARD_HORIZONS_SECONDS:
                        wait=max(
                            0.0,float(horizon)-(time.monotonic()-started)
                        )
                        if wait:
                            time.sleep(wait)
                        mark=_shadow_v4_quote(
                            endpoint,key,transition["market"],
                            entry["amount_out"],side="sell",
                        )
                        result["provider_sessions"].extend(
                            mark.pop("provider_sessions")
                        )
                        mark["target_horizon_seconds"]=int(horizon)
                        mark["observed_elapsed_seconds"]=int(
                            time.monotonic()-started
                        )
                        mark["after_cost_return_bps"]=_after_cost_return_bps(
                            entry,mark
                        )
                        marks.append(mark)
                    result["forward_marks"]=marks
                    result["status"]="breakout_candidate_forward_observed"
                except BoundaryError as exc:
                    result["status"]="breakout_candidate_quote_boundary"
                    result["shadow_boundary"]=str(exc)
                break
            consolidation_high=max(consolidation_high,current)

        if "status" not in result:
            result["status"]="no_breakout_within_bounded_window"
    except BoundaryError as exc:
        result["status"]="boundary";result["boundary"]=str(exc)
    result["ended_at"]=time.time()
    return result


if __name__=="__main__":
    output=run(os.environ.get("MM_ROBINHOOD_READ_RPC_URL",""))
    raw=json.dumps(output,sort_keys=True,separators=(",",":")).encode()
    if len(raw)>4_000_000:
        raise BoundaryError("breakout_report_capacity")
    REPORT.write_bytes(raw)
    print(json.dumps(dict(
        status=output["status"],boundary=output.get("boundary"),
        signal=output.get("signal"),
    ),sort_keys=True))
