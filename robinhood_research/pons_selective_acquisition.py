"""Independent live evidence acquisition for Pons Selective Continuation v1.

This module does not import any other strategy or cohort.  It reuses only neutral
Robinhood/Pons transport, ABI, protocol-authentication and evidence primitives.
"""
from __future__ import annotations

from collections import Counter, OrderedDict
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
CACHE_HEADERS=4096
CACHE_RECEIPTS=8192
CACHE_LAUNCHES=4096
EVIDENCE_SESSION_ROTATE_AT=180


class ImmutableEvidenceCache:
    """Bounded cross-candidate cache for already authenticated immutable evidence."""

    def __init__(self):
        self.headers_by_hash=OrderedDict()
        self.headers_by_number=OrderedDict()
        self.receipts=OrderedDict()
        self.launch_at=OrderedDict()
        self.counts=Counter()

    @staticmethod
    def _remember(store,key,value,limit,conflict):
        old=store.get(key)
        if old is not None:
            if old!=value:
                raise BoundaryError(conflict)
            store.move_to_end(key)
            return False
        store[key]=value
        while len(store)>int(limit):
            store.popitem(last=False)
        return True

    def header_by_hash(self,block_hash):
        row=self.headers_by_hash.get(str(block_hash))
        self.counts["header_hash_hit" if row is not None else "header_hash_miss"]+=1
        return row

    def header_by_number(self,block):
        row=self.headers_by_number.get(int(block))
        self.counts["header_number_hit" if row is not None else "header_number_miss"]+=1
        return row

    def remember_header(self,header):
        if not isinstance(header,dict) or not header.get("hash") or header.get("number") is None:
            raise BoundaryError("selective_cached_header_shape")
        number=int(header["number"],16)
        block_hash=str(header["hash"])
        old_hash=self.headers_by_hash.get(block_hash)
        old_number=self.headers_by_number.get(number)
        if old_hash is not None and old_hash!=header:
            raise BoundaryError("selective_cached_header_hash_conflict")
        if old_number is not None and old_number.get("hash")!=block_hash:
            raise BoundaryError("selective_cached_header_number_conflict")
        self._remember(
            self.headers_by_hash,block_hash,header,CACHE_HEADERS,
            "selective_cached_header_hash_conflict",
        )
        self._remember(
            self.headers_by_number,number,header,CACHE_HEADERS,
            "selective_cached_header_number_conflict",
        )
        self.counts["header_store"]+=1
        return header

    def receipt(self,tx,block_hash):
        key=(str(tx),str(block_hash))
        row=self.receipts.get(key)
        self.counts["receipt_hit" if row is not None else "receipt_miss"]+=1
        return row

    def remember_receipt(self,tx,block_hash,receipt):
        if (
            not isinstance(receipt,dict)
            or receipt.get("transactionHash")!=tx
            or receipt.get("blockHash")!=block_hash
        ):
            raise BoundaryError("selective_cached_receipt_identity")
        self._remember(
            self.receipts,(str(tx),str(block_hash)),receipt,CACHE_RECEIPTS,
            "selective_cached_receipt_conflict",
        )
        self.counts["receipt_store"]+=1
        return receipt

    def launch(self,curve):
        key=str(curve).lower()
        value=self.launch_at.get(key)
        self.counts["launch_hit" if value is not None else "launch_miss"]+=1
        return value

    def remember_launch(self,curve,value):
        key=str(curve).lower();value=int(value)
        self._remember(
            self.launch_at,key,value,CACHE_LAUNCHES,
            "selective_cached_launch_conflict",
        )
        self.counts["launch_store"]+=1
        return value

    def telemetry(self):
        return dict(
            header_hashes=len(self.headers_by_hash),
            header_numbers=len(self.headers_by_number),
            receipts=len(self.receipts),
            launches=len(self.launch_at),
            **dict(self.counts),
        )


class SelectiveEvidenceContext:
    """Reuse one bounded authoritative RPC lane and immutable evidence across candidates."""

    def __init__(self,endpoint,cache=None):
        self.endpoint=endpoint
        self.cache=cache or ImmutableEvidenceCache()
        self.rpc=None
        self.completed_sessions=[]

    def _rotate(self):
        if self.rpc is not None:
            self.completed_sessions.append(self.rpc.telemetry())
            if len(self.completed_sessions)>32:
                self.completed_sessions=self.completed_sessions[-32:]
        self.rpc=_rpc(self.endpoint)
        return self.rpc

    def acquire(self,needed=1,scope="pons_selective"):
        needed=int(needed)
        if needed<1 or needed>50:
            raise BoundaryError("selective_evidence_request_bound")
        if self.rpc is None:
            return self._rotate()
        if (
            self.rpc.used+needed>EVIDENCE_SESSION_ROTATE_AT
            or self.rpc.counts[scope]+needed>self.rpc.per_scope
        ):
            return self._rotate()
        return self.rpc

    def call(self,method,params,scope):
        return self.acquire(1,scope).call(method,params,scope=scope)

    def batch(self,calls,scope):
        out=[]
        for group in _chunks(list(calls),50):
            rpc=self.acquire(len(group),scope)
            out.extend(rpc.batch(group,scope=scope))
        return out

    def remember_candidate(self,candidate):
        self.cache.remember_header(candidate["header"])
        self.cache.remember_receipt(
            candidate["receipt"]["transactionHash"],
            candidate["receipt"]["blockHash"],
            candidate["receipt"],
        )

    def telemetry(self):
        current=None if self.rpc is None else self.rpc.telemetry()
        return dict(
            completed_sessions=list(self.completed_sessions),
            current_session=current,
            cache=self.cache.telemetry(),
        )


def _rpc(endpoint):
    rpc=configured_rpc(endpoint,limit=200,per_scope=190,retries=0)
    rpc.verify_chain()
    return rpc


def _chunks(rows,size):
    for i in range(0,len(rows),size):
        yield rows[i:i+size]


def _batched(endpoint,calls,scope,*,evidence_context=None):
    """Run bounded read batches, reusing an authoritative session when supplied."""
    ctx=evidence_context or SelectiveEvidenceContext(endpoint)
    before=len(ctx.completed_sessions)
    out=ctx.batch(calls,scope) if calls else []
    telemetry=list(ctx.completed_sessions[before:])
    if ctx.rpc is not None:
        telemetry.append(ctx.rpc.telemetry())
    return out,telemetry


def _authenticate_window(
    endpoint,candidate,tape,seconds=60,*,evidence_context=None
):
    """Authenticate one market window with a shared immutable header/receipt cache.

    Missing block headers and receipts are deliberately fetched in one combined
    bounded batch graph. Receipt reads may include a few events later excluded by
    the 60-second timestamp filter; this trades redundant sequencing for fewer
    physical transports without changing the evidence or event-cap rules.
    """
    ctx=evidence_context or SelectiveEvidenceContext(endpoint)
    cache=ctx.cache
    end_time=int(candidate["stamp"].event_at)
    end_block=int(candidate["block"])
    curve=candidate["curve"].lower()
    raw=[
        event for event in tape
        if event.get("address","").lower()==curve
        and int(event["blockNumber"],16)<=end_block
    ]
    if len(raw)>ENTRY_THRESHOLDS["max_market_events"]*4:
        raw=raw[-ENTRY_THRESHOLDS["max_market_events"]*4:]

    hashes=list(dict.fromkeys(event["blockHash"] for event in raw))
    tx_rows=list(dict.fromkeys(
        (event["transactionHash"],event["blockHash"]) for event in raw
    ))
    headers={}
    receipts={}
    pending=[]
    labels=[]

    for block_hash in hashes:
        header=cache.header_by_hash(block_hash)
        if header is None:
            labels.append(("header",block_hash))
            pending.append(("eth_getBlockByHash",[block_hash,False]))
        else:
            headers[block_hash]=header

    for tx,block_hash in tx_rows:
        receipt=cache.receipt(tx,block_hash)
        if receipt is None:
            labels.append(("receipt",(tx,block_hash)))
            pending.append(("eth_getTransactionReceipt",[tx]))
        else:
            receipts[(tx,block_hash)]=receipt

    before=len(ctx.completed_sessions)
    values=ctx.batch(pending,"pons_selective_window") if pending else []
    for label,value in zip(labels,values):
        kind,key=label
        if kind=="header":
            block_hash=key
            if value["hash"]!=block_hash:
                raise BoundaryError("selective_window_header_disagreement")
            cache.remember_header(value)
            headers[block_hash]=value
        else:
            tx,block_hash=key
            cache.remember_receipt(tx,block_hash,value)
            receipts[(tx,block_hash)]=value

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

    observed=int(time.time())
    normalized=[]
    for event in selected:
        block_hash=event["blockHash"]
        receipt=receipts[(event["transactionHash"],block_hash)]
        row=raw_event(
            curve_abi(),event,address=curve,receipt=receipt,
            header=headers[block_hash],observed_at=observed,
            confirmation="confirmed",
        )
        normalized.append(normalized_trade(
            row["decoded"],
            identity=f'{row["block"]}:{row["transaction_hash"]}:{row["log_index"]}',
            event_at=row["event_at"],
        ))

    telemetry=list(ctx.completed_sessions[before:])
    if ctx.rpc is not None:
        telemetry.append(ctx.rpc.telemetry())
    return normalized,telemetry


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


def _trajectory(endpoint,candidate,*,evidence_context=None):
    """Resolve 5s/15s trajectory anchors from dense batched recent headers.

    The old binary search serialized one request per probe. This path walks recent
    blocks in contiguous batches, so both target anchors are proven from the same
    header set and every immutable header is reusable by later candidates.
    """
    ctx=evidence_context or SelectiveEvidenceContext(endpoint)
    cache=ctx.cache
    current_block=int(candidate["block"])
    current_header=candidate["header"]
    current_at=int(current_header["timestamp"],16)
    curve=candidate["curve"].lower()
    cache.remember_header(current_header)

    launch_at=cache.launch(curve)
    next_block=current_block-1
    looked=0
    collected={current_block:current_header}
    first=True
    before=len(ctx.completed_sessions)

    while True:
        room=49 if first and launch_at is None else 50
        low=max(0,next_block-room+1)
        blocks=list(range(next_block,low-1,-1)) if next_block>=0 else []
        labels=[];calls=[]

        if first and launch_at is None:
            labels.append(("launch",curve))
            calls.append((
                "eth_call",
                [dict(to=curve,data=calldata("launchedAt()")),hex(current_block)],
            ))

        for block in blocks:
            header=cache.header_by_number(block)
            if header is None:
                labels.append(("header",block))
                calls.append(("eth_getBlockByNumber",[hex(block),False]))
            else:
                collected[block]=header

        values=ctx.batch(calls,"pons_selective_trajectory") if calls else []
        for label,value in zip(labels,values):
            kind,key=label
            if kind=="launch":
                launch_at=_one_word(value)
                cache.remember_launch(curve,launch_at)
            else:
                block=int(key)
                if int(value["number"],16)!=block:
                    raise BoundaryError("trajectory_block_identity")
                cache.remember_header(value)
                collected[block]=value

        if launch_at is None or not 0<=int(launch_at)<=current_at:
            raise BoundaryError("invalid_curve_launch_time")
        for block in blocks:
            header=cache.header_by_number(block)
            if header is not None:
                collected[block]=header

        min_target=max(int(launch_at),current_at-15)
        oldest=min(
            (int(h["timestamp"],16) for h in collected.values()),
            default=current_at,
        )
        looked+=len(blocks)
        if oldest<=min_target:
            break
        if low==0 or looked>=MAX_TRAJECTORY_LOOKBACK_BLOCKS:
            raise BoundaryError("trajectory_history_incomplete")
        next_block=low-1
        first=False

    ordered=[collected[b] for b in sorted(collected)]
    prior_at=None
    for header in ordered:
        at=int(header["timestamp"],16)
        if prior_at is not None and at<prior_at:
            raise BoundaryError("trajectory_header_time_regression")
        prior_at=at

    targets=[
        max(int(launch_at),current_at-15),
        max(int(launch_at),current_at-5),
    ]
    prior_headers=[]
    for target in targets:
        eligible=[
            h for h in ordered
            if int(h["timestamp"],16)<=int(target)
        ]
        if not eligible:
            raise BoundaryError("trajectory_history_incomplete")
        prior_headers.append(max(eligible,key=lambda h:int(h["number"],16)))

    unique_blocks=list(dict.fromkeys(
        int(h["number"],16) for h in prior_headers
    ))
    reads=ctx.batch([
        ("eth_call",[
            dict(to=curve,data=calldata("realQuoteReserve()")),hex(block)
        ])
        for block in unique_blocks
    ],"pons_selective_trajectory")
    reserve_by_block=dict(zip(unique_blocks,reads))

    threshold=int(candidate["record"]["graduationThreshold"])
    snapshots=[]
    for header in prior_headers:
        block=int(header["number"],16)
        raw=reserve_by_block[block]
        real=_one_word(raw)
        snapshots.append(dict(
            at=int(header["timestamp"],16),block=block,
            real_quote=real,
            progress_bps=curve_progress_bps(real,threshold),
        ))
    snapshots.append(dict(
        at=current_at,block=current_block,
        real_quote=int(candidate["state"].real_quote),
        progress_bps=curve_progress_bps(candidate["state"].real_quote,threshold),
    ))
    dedup={}
    for row in snapshots:
        dedup[(row["at"],row["block"])]=row

    telemetry=list(ctx.completed_sessions[before:])
    if ctx.rpc is not None:
        telemetry.append(ctx.rpc.telemetry())
    return (
        sorted(dedup.values(),key=lambda r:(r["at"],r["block"])),
        int(launch_at),
        dict(
            sessions=telemetry,
            batched_recent_headers=True,
            recent_headers_considered=len(collected),
            cache=cache.telemetry(),
        ),
    )


def evaluate_candidate(
    endpoint,event,tape,*,strategy_capital_quote,wallet_histories=None,
    creator_history=None,quote_relative_strength_bps=None,
    evidence_observed_at=None,evidence_observed_monotonic=None,
    evidence_context=None,
):
    """Freeze one outcome-blind qualification vector from Pons-only evidence."""
    sessions=[]
    if evidence_observed_monotonic is not None:
        preflight_latency=time.monotonic()-float(evidence_observed_monotonic)
        if preflight_latency<0:
            raise BoundaryError("future_evidence_observation")
        if preflight_latency>ENTRY_THRESHOLDS["max_state_age_seconds"]:
            raise BoundaryError("stale_evidence_acquisition")
    ctx=evidence_context or SelectiveEvidenceContext(endpoint)
    rpc=ctx.acquire(16,"pons_natural")
    report=dict(reads=[])
    candidate=_authenticate_candidate(
        rpc,event,report,
        evidence_observed_at=evidence_observed_at,
        evidence_observed_monotonic=evidence_observed_monotonic,
        max_evidence_latency_seconds=ENTRY_THRESHOLDS["max_state_age_seconds"],
    )
    candidate["report"]=report
    ctx.remember_candidate(candidate)
    sessions.append(rpc.telemetry())
    if candidate["decoded_event"]["decoded"]["name"]!="CurveBuy":
        raise BoundaryError("selective_nomination_not_buy")

    snapshots,launch_at,trajectory_session=_trajectory(
        endpoint,candidate,evidence_context=ctx
    )
    sessions.append(trajectory_session)
    market,market_sessions=_authenticate_window(
        endpoint,candidate,list(tape),seconds=60,evidence_context=ctx
    )
    sessions.extend(market_sessions)

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
        evidence_context=ctx.telemetry(),
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
        evidence_context=row.get("evidence_context"),
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
