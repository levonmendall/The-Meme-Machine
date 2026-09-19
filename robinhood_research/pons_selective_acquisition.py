"""Independent live evidence acquisition for Pons Selective Continuation v1.

This module does not import any other strategy or cohort.  It reuses only neutral
Robinhood/Pons transport, ABI, protocol-authentication and evidence primitives.
"""
from __future__ import annotations

from dataclasses import asdict
import time

from . import BoundaryError
from .abi import calldata
from .pons import curve_abi, raw_event
from .pons_natural_observation import (
    RESEARCH_RECIPIENT, _authenticate_candidate, _one_word,
)
from .provider_topology import configured_rpc
from .pons_selective_continuation import (
    ENTRY_THRESHOLDS, curve_progress_bps, normalized_trade, qualification_vector,
)

HEADER_BATCH=50
RECEIPT_BATCH=50
MAX_TRAJECTORY_LOOKBACK_BLOCKS=8192


def _rpc(endpoint):
    rpc=configured_rpc(endpoint,limit=200,per_scope=190,retries=0)
    rpc.verify_chain()
    return rpc


def _chunks(rows,size):
    for i in range(0,len(rows),size):
        yield rows[i:i+size]


def _batched(endpoint,calls,scope):
    """Run arbitrary read calls in independent bounded sessions."""
    out=[];telemetry=[]
    for group in _chunks(calls,50):
        rpc=_rpc(endpoint)
        out.extend(rpc.batch(group,scope=scope))
        telemetry.append(rpc.telemetry())
    return out,telemetry


def _authenticate_window(endpoint,candidate,tape,seconds=60):
    end_time=int(candidate["stamp"].event_at)
    end_block=int(candidate["block"])
    curve=candidate["curve"].lower()
    raw=[
        event for event in tape
        if event.get("address","").lower()==curve
        and int(event["blockNumber"],16)<=end_block
    ]
    if len(raw)>ENTRY_THRESHOLDS["max_market_events"]*4:
        # Filtering by event timestamp happens after authenticated headers. Keep a
        # hard pre-authentication ceiling so one hyperactive curve cannot monopolize
        # the strategy's provider budget.
        raw=raw[-ENTRY_THRESHOLDS["max_market_events"]*4:]

    hashes=list(dict.fromkeys(event["blockHash"] for event in raw))
    header_values,header_sessions=_batched(
        endpoint,
        [("eth_getBlockByHash",[block_hash,False]) for block_hash in hashes],
        "pons_selective_window",
    ) if hashes else ([],[])
    headers=dict(zip(hashes,header_values))
    selected=[]
    for event in raw:
        header=headers[event["blockHash"]]
        if header["hash"]!=event["blockHash"]:
            raise BoundaryError("selective_window_header_disagreement")
        at=int(header["timestamp"],16)
        if end_time-int(seconds)<=at<=end_time:
            selected.append(event)
    selected.sort(key=lambda e:(
        int(e["blockNumber"],16),
        int(e["transactionIndex"],16),
        int(e["logIndex"],16),
    ))
    if len(selected)>ENTRY_THRESHOLDS["max_market_events"]:
        raise BoundaryError("selective_event_capacity")

    tx_rows=list(dict.fromkeys(
        (event["transactionHash"],event["blockHash"]) for event in selected
    ))
    receipt_values,receipt_sessions=_batched(
        endpoint,
        [("eth_getTransactionReceipt",[tx]) for tx,_ in tx_rows],
        "pons_selective_window",
    ) if tx_rows else ([],[])
    receipts={}
    for (tx,block_hash),receipt in zip(tx_rows,receipt_values):
        if receipt["transactionHash"]!=tx or receipt["blockHash"]!=block_hash:
            raise BoundaryError("selective_window_receipt_disagreement")
        receipts[(tx,block_hash)]=receipt

    observed=int(time.time())
    normalized=[]
    for event in selected:
        block_hash=event["blockHash"]
        row=raw_event(
            curve_abi(),event,address=curve,
            receipt=receipts[(event["transactionHash"],block_hash)],
            header=headers[block_hash],observed_at=observed,
            confirmation="confirmed",
        )
        normalized.append(normalized_trade(
            row["decoded"],
            identity=f'{row["block"]}:{row["transaction_hash"]}:{row["log_index"]}',
            event_at=row["event_at"],
        ))
    return normalized,header_sessions+receipt_sessions


def _header_search(rpc,current_block,current_at,target_at,cache):
    """Find latest block whose timestamp is <= target_at with bounded reads."""
    current_block=int(current_block);current_at=int(current_at);target_at=int(target_at)
    if target_at>=current_at:
        return dict(number=hex(current_block),timestamp=hex(current_at))
    if current_block<=0:
        raise BoundaryError("trajectory_history_incomplete")

    def read(block):
        block=max(0,int(block))
        if block not in cache:
            header=rpc.call(
                "eth_getBlockByNumber",[hex(block),False],scope="pons_selective_trajectory"
            )
            if int(header["number"],16)!=block:
                raise BoundaryError("trajectory_block_identity")
            cache[block]=header
        return cache[block]

    high=current_block
    delta=4
    low=None
    while delta<=MAX_TRAJECTORY_LOOKBACK_BLOCKS:
        probe=max(0,current_block-delta)
        header=read(probe)
        if int(header["timestamp"],16)<=target_at:
            low=probe
            break
        if probe==0:
            break
        high=probe
        delta*=2
    if low is None:
        raise BoundaryError("trajectory_history_incomplete")

    # high may already be <= target after the first probe; ensure the upper bound
    # is a block later than target for the binary search.
    high=max(high,low)
    if high==low:
        high=current_block
    while low+1<high:
        mid=(low+high)//2
        header=read(mid)
        if int(header["timestamp"],16)<=target_at:
            low=mid
        else:
            high=mid
    return read(low)


def _trajectory(endpoint,candidate):
    rpc=_rpc(endpoint)
    current_block=int(candidate["block"])
    current_header=candidate["header"]
    current_at=int(current_header["timestamp"],16)
    curve=candidate["curve"]

    launch_raw=rpc.call(
        "eth_call",[dict(to=curve,data=calldata("launchedAt()")),hex(current_block)],
        scope="pons_selective_trajectory",
    )
    launch_at=_one_word(launch_raw)
    if not 0<=launch_at<=current_at:
        raise BoundaryError("invalid_curve_launch_time")

    cache={current_block:current_header}
    targets=[
        max(launch_at,current_at-15),
        max(launch_at,current_at-5),
    ]
    prior_headers=[
        _header_search(rpc,current_block,current_at,target,cache)
        for target in targets
    ]
    blocks=[int(h["number"],16) for h in prior_headers]
    reads=rpc.batch([
        ("eth_call",[dict(to=curve,data=calldata("realQuoteReserve()")),hex(block)])
        for block in blocks
    ],scope="pons_selective_trajectory")
    threshold=int(candidate["record"]["graduationThreshold"])
    snapshots=[]
    for header,raw in zip(prior_headers,reads):
        snapshots.append(dict(
            at=int(header["timestamp"],16),
            block=int(header["number"],16),
            real_quote=_one_word(raw),
            progress_bps=curve_progress_bps(_one_word(raw),threshold),
        ))
    snapshots.append(dict(
        at=current_at,block=current_block,
        real_quote=int(candidate["state"].real_quote),
        progress_bps=curve_progress_bps(candidate["state"].real_quote,threshold),
    ))
    # Deduplicate identical block/time anchors while preserving the latest exact state.
    dedup={}
    for row in snapshots:
        dedup[(row["at"],row["block"])]=row
    return sorted(dedup.values(),key=lambda r:(r["at"],r["block"])),launch_at,rpc.telemetry()


def evaluate_candidate(
    endpoint,event,tape,*,strategy_capital_quote,wallet_histories=None,
    creator_history=None,quote_relative_strength_bps=None,
    evidence_observed_at=None,evidence_observed_monotonic=None,
):
    """Freeze one outcome-blind qualification vector from Pons-only evidence."""
    sessions=[]
    if evidence_observed_monotonic is not None:
        preflight_latency=time.monotonic()-float(evidence_observed_monotonic)
        if preflight_latency<0:
            raise BoundaryError("future_evidence_observation")
        if preflight_latency>ENTRY_THRESHOLDS["max_state_age_seconds"]:
            raise BoundaryError("stale_evidence_acquisition")
    rpc=_rpc(endpoint)
    report=dict(reads=[])
    candidate=_authenticate_candidate(
        rpc,event,report,
        evidence_observed_at=evidence_observed_at,
        evidence_observed_monotonic=evidence_observed_monotonic,
        max_evidence_latency_seconds=ENTRY_THRESHOLDS["max_state_age_seconds"],
    )
    candidate["report"]=report
    sessions.append(rpc.telemetry())
    if candidate["decoded_event"]["decoded"]["name"]!="CurveBuy":
        raise BoundaryError("selective_nomination_not_buy")

    market,market_sessions=_authenticate_window(endpoint,candidate,list(tape),seconds=60)
    sessions.extend(market_sessions)
    snapshots,launch_at,trajectory_session=_trajectory(endpoint,candidate)
    sessions.append(trajectory_session)

    available=int(time.time())
    completed_monotonic=time.monotonic()
    acquisition_latency=(
        float(available-int(candidate["stamp"].event_at))
        if evidence_observed_monotonic is None
        else completed_monotonic-float(evidence_observed_monotonic)
    )
    creator_groups=(
        candidate["record"].get("deployer"),
        candidate["record"].get("creatorFeeRecipient"),
    )
    vector=qualification_vector(
        state=candidate["state"],
        graduation_threshold=candidate["record"]["graduationThreshold"],
        launch_at=launch_at,
        snapshots=snapshots,
        events=market,
        creator_groups=creator_groups,
        current_snipe_bps=candidate["current_snipe_bps"],
        lifecycle_gas_quote=candidate["roundtrip_gas_wei"],
        strategy_capital_quote=int(strategy_capital_quote),
        asof=candidate["stamp"].event_at,
        evidence_available_at=available,
        evidence_observed_at=evidence_observed_at,
        evidence_acquisition_latency_seconds=acquisition_latency,
        pair_token=candidate["record"].get("pairToken"),
        wallet_histories=wallet_histories,
        creator_history=creator_history,
        quote_relative_strength_bps=quote_relative_strength_bps,
    )
    return dict(
        token=candidate["token"],curve=candidate["curve"],
        source_transaction=event["transactionHash"],
        source_block=candidate["block"],
        source_log_index=int(event["logIndex"],16),
        candidate=candidate,market_events=market,
        trajectory_snapshots=snapshots,launch_at=launch_at,
        vector=vector,provider_sessions=sessions,
        evaluation_completed_at=available,
        evidence_observed_at=evidence_observed_at,
        evidence_acquisition_latency_seconds=acquisition_latency,
        chain_timestamp_lag_seconds=(
            None if evidence_observed_at is None
            else float(evidence_observed_at)-float(candidate["stamp"].event_at)
        ),
    )


def public_evaluation(row):
    """Remove non-JSON dataclass/runtime objects before a study report is persisted."""
    candidate=row["candidate"]
    return dict(
        token=row["token"],curve=row["curve"],
        source_transaction=row["source_transaction"],
        source_block=row["source_block"],
        source_log_index=row["source_log_index"],
        market_events=row["market_events"],
        trajectory_snapshots=row["trajectory_snapshots"],
        launch_at=row["launch_at"],vector=row["vector"],
        evaluation_completed_at=row["evaluation_completed_at"],
        evidence_observed_at=row.get("evidence_observed_at"),
        evidence_acquisition_latency_seconds=row.get(
            "evidence_acquisition_latency_seconds"
        ),
        chain_timestamp_lag_seconds=row.get("chain_timestamp_lag_seconds"),
        candidate=dict(
            token=candidate["token"],curve=candidate["curve"],block=candidate["block"],
            record=candidate["record"],auth=candidate["auth"],
            state=asdict(candidate["state"]),quote=candidate["quote"],
            freshness_seconds=candidate["freshness_seconds"],
            evidence_observed_at=candidate.get("evidence_observed_at"),
            evidence_acquisition_latency_seconds=candidate.get(
                "evidence_acquisition_latency_seconds"
            ),
            chain_timestamp_lag_seconds=candidate.get(
                "chain_timestamp_lag_seconds"
            ),
            current_snipe_bps=candidate["current_snipe_bps"],
            gas_meta=candidate["gas_meta"],
        ),
        provider_sessions=row["provider_sessions"],
    )
