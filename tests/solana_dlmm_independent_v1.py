"""Independent Solana Meteora DLMM strategy v1.

Strategy decisions consume only:
- frozen SOLANA_DLMM_INDEPENDENT_V1.json,
- Solana-mainnet Meteora public pool metrics,
- authenticated Solana DLMM state/tapes.

No prior DLMM strategy, wallet strategy, Robinhood, Pons, or Ramses strategy is an
input. Shared code is limited to generic DLMM integer mechanics and Solana provider
transport.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import statistics
import sys
import threading
import time
import urllib.parse
import urllib.request

from meme_machine import dlmm
from meme_machine.dlmm_tape import (
    MAX_TRANSACTIONS,
    apply_external_adjustment,
    chain_verified_tapes,
    ordered_tape_actions,
    reconstruct,
    replay_swap_event,
    transaction_swaps,
)
from meme_machine.provider import Unavailable
from meme_machine.solana_evidence_broker import (
    EvidenceBroker,ProgramAccountWakeStream,
)
from meme_machine.store import encode
from tests import dlmm_alchemy_provider as provider

POLICY_PATH=Path("SOLANA_DLMM_INDEPENDENT_V1.json")
OUT=Path("solana-dlmm-independent-v1-live.json")
API_BASE="https://dlmm.datapi.meteora.ag"

CAPITAL=100_000_000
ENTRY_NETWORK_COST=200_000
EXIT_NETWORK_COST=200_000
ROUND_TRIP_NETWORK_COST=ENTRY_NETWORK_COST+EXIT_NETWORK_COST

DISCOVERY_PAGE_SIZE=250
DISCOVERY_PAGES_PER_SORT=2
DISCOVERY_SORTS=("volume_5m:desc","fee_tvl_ratio_5m:desc","volume_30m:desc")
PER_RPC_LIMIT=240
ROTATE_AT_CALLS=190
CHUNK_SECONDS=2
MAX_WARMUP_RESETS=2
SIGNATURE_PAGE_LIMIT=64
MAX_SIGNATURE_CENSUS_PAGES=16
FRESH_SWAP_TRIGGER_POLL_SECONDS=2
FRESH_SWAP_TRIGGER_MAX_SECONDS=60
FRESH_SWAP_TRIGGER_SIGNATURE_LIMIT=16
FRESH_SWAP_TRIGGER_ACCEL_REFRESH_SECONDS=12
RATE_LIMIT_RECOVERY_MAX_CONSECUTIVE=8
NETWORK_IDENTITY_MAX_ATTEMPTS=3
NETWORK_IDENTITY_RETRY_SECONDS=1
DEFAULT_MAX_RUNTIME_SECONDS=1200
METEORA_MIN_INTERVAL_SECONDS=0.10
DLMM_DISCOVERY_WS_URL="wss://api.mainnet-beta.solana.com"
DLMM_WAKE_STREAM_KEY="dlmm_pool_wake"
DLMM_BROKER_DB=Path(os.environ.get(
    "MM_SOLANA_EVIDENCE_BROKER_DB","solana-dlmm-evidence-broker.sqlite3"))

class _MeteoraPacer:
    def __init__(self):
        self.next=0.0
        self.lock=threading.Lock()
    def pace(self):
        with self.lock:
            now=time.monotonic()
            wait=max(0.0,self.next-now)
            if wait:
                time.sleep(wait)
                now=time.monotonic()
            self.next=max(now,self.next)+METEORA_MIN_INTERVAL_SECONDS

METEORA_PACER=_MeteoraPacer()



def assert_independence():
    bad_env=sorted(k for k in os.environ if k.startswith("MM_ROBINHOOD_"))
    if bad_env:
        raise RuntimeError("solana_dlmm_robinhood_config_forbidden:"+",".join(bad_env))
    forbidden=("robinhood","pons","ramses")
    imported=[
        name for name in sys.modules
        if any(part in forbidden for part in name.lower().split("."))
    ]
    if imported:
        raise RuntimeError("solana_dlmm_forbidden_strategy_import:"+",".join(sorted(imported)))


def load_policy():
    p=json.loads(POLICY_PATH.read_text())
    if p.get("kind")!="solana_dlmm_independent_v1":
        raise RuntimeError("solana_dlmm_policy_kind")
    if p.get("status")!="frozen_pre_prospective":
        raise RuntimeError("solana_dlmm_policy_not_frozen")
    independence=p.get("independence") or {}
    for key in (
        "wallet_signals","profitable_wallet_labels","prior_dlmm_candidate_outputs",
        "small_pool_study_outputs","capital_efficiency_v1_outputs",
        "robinhood_strategies","pons_strategies","ramses_strategies",
        "robinhood_data","robinhood_provider_config",
    ):
        if independence.get(key) is not False:
            raise RuntimeError("solana_dlmm_independence_drift:"+key)
    if p.get("authority",{}).get("allocation") is not False:
        raise RuntimeError("solana_dlmm_authority")
    if int(p["position"]["capital_lamports"])!=CAPITAL:
        raise RuntimeError("solana_dlmm_capital_drift")
    if int(p["costs"]["round_trip_network_cost_lamports"])!=ROUND_TRIP_NETWORK_COST:
        raise RuntimeError("solana_dlmm_cost_drift")
    return p


def _api(path,params=None):
    if not path.startswith("/"):
        raise ValueError("solana_dlmm_api_path")
    METEORA_PACER.pace()
    url=API_BASE+path
    if params:
        url+="?"+urllib.parse.urlencode(params)
    req=urllib.request.Request(url,headers={
        "Accept":"application/json",
        "User-Agent":"meme-machine-solana-dlmm-independent-v1/1",
    })
    with urllib.request.urlopen(req,timeout=20) as response:
        if response.status!=200:
            raise RuntimeError(f"solana_dlmm_api_http:{response.status}")
        raw=response.read(2_000_001)
    if len(raw)>2_000_000:
        raise RuntimeError("solana_dlmm_api_response_bound")
    return json.loads(raw)


def _num(value):
    try:
        x=float(value)
    except (TypeError,ValueError):
        return 0.0
    return x if math.isfinite(x) else 0.0


def _accel(short_value,long_value,long_multiple):
    short=max(0.0,_num(short_value));long=max(0.0,_num(long_value))
    baseline=long/float(long_multiple)
    if baseline<=0:
        return 99.0 if short>0 else 0.0
    return min(99.0,short/baseline)


def _sol_pair(row):
    x=(row.get("token_x") or {}).get("address")
    y=(row.get("token_y") or {}).get("address")
    return (x==dlmm.WSOL) ^ (y==dlmm.WSOL)


def _candidate(row):
    volume=row.get("volume") or {};fees=row.get("fees") or {}
    return dict(
        address=row.get("address"),name=row.get("name"),
        token_x=(row.get("token_x") or {}).get("address"),
        token_y=(row.get("token_y") or {}).get("address"),
        tvl_usd=_num(row.get("tvl")),
        volume_30m_snapshot_usd=_num(volume.get("30m")),
        fee_30m_snapshot_usd=_num(fees.get("30m")),
        dynamic_fee_pct=_num(row.get("dynamic_fee_pct")),
        volume_5m_usd=None,volume_30m_usd=None,
        fee_5m_usd=None,fee_30m_usd=None,
        fee_tvl_ratio_5m=None,
        volume_acceleration=None,fee_acceleration=None,
        event_score=None,
    )


def _history_acceleration(candidate,observed_at):
    payload=_api(
        f"/pools/{candidate['address']}/volume/history",
        dict(
            timeframe="5m",
            start_time=max(0,int(observed_at)-2100),
            end_time=int(observed_at),
        ),
    )
    rows=payload.get("data") if isinstance(payload,dict) else None
    if not isinstance(rows,list):
        raise RuntimeError("solana_dlmm_volume_history_shape")
    clean=[]
    for row in rows:
        if not isinstance(row,dict):
            continue
        ts=row.get("timestamp")
        # Meteora timestamps identify the START of each 5-minute bucket.
        # A bucket is admissible only after its full 300-second interval has ended.
        if not isinstance(ts,int) or ts+300>observed_at:
            continue
        clean.append(dict(
            timestamp=ts,
            volume=max(0.0,_num(row.get("volume"))),
            fees=max(0.0,_num(row.get("fees"))),
        ))
    clean.sort(key=lambda x:x["timestamp"])
    unique=[];seen=set()
    for row in clean:
        if row["timestamp"] in seen:
            raise RuntimeError("solana_dlmm_volume_history_duplicate_timestamp")
        seen.add(row["timestamp"]);unique.append(row)
    if len(unique)<6:
        raise RuntimeError("solana_dlmm_volume_history_insufficient_5m_buckets")
    window=unique[-6:]
    if any(b["timestamp"]-a["timestamp"]!=300
           for a,b in zip(window,window[1:])):
        raise RuntimeError("solana_dlmm_volume_history_nonconsecutive_5m_buckets")
    v5=window[-1]["volume"];f5=window[-1]["fees"]
    v30=sum(x["volume"] for x in window);f30=sum(x["fees"] for x in window)
    vacc=_accel(v5,v30,6);facc=_accel(f5,f30,6)
    tvl=max(0.0,float(candidate.get("tvl_usd") or 0.0))
    density=0.0 if tvl<=0 else f5/tvl
    out=dict(candidate)
    out.update(
        volume_5m_usd=v5,volume_30m_usd=v30,
        fee_5m_usd=f5,fee_30m_usd=f30,
        fee_tvl_ratio_5m=density,
        volume_acceleration=vacc,fee_acceleration=facc,
        event_score=(
            math.log1p(v5)*max(vacc,0.01)*max(facc,0.01)
            *max(density,1e-12)
        ),
        acceleration_window_start=window[0]["timestamp"],
        acceleration_window_end=window[-1]["timestamp"],
        acceleration_window_end_exclusive=window[-1]["timestamp"]+300,
        latest_completed_bucket_age_seconds=(
            int(observed_at)-(window[-1]["timestamp"]+300)),
        acceleration_bucket_count=len(window),
    )
    return out


def _iter_acceleration_candidates(policy,telemetry,deadline=None,checkpoint=None):
    """Yield each qualifying pool immediately after its history check.

    The order is deterministic: configured sort order, then page, then API row rank.
    A pool is evaluated only on first sighting so no later source can retroactively
    improve its priority. Most importantly, a qualifying signal is handed to the
    caller before the next pool history request is made.
    """
    telemetry.setdefault("rejections",[])
    telemetry.setdefault("errors",[])
    telemetry.setdefault("qualified",[])
    telemetry.setdefault("seen",0)
    telemetry.setdefault("history_reads",0)
    seen=set()
    regime=policy["regime"]
    for sort_by in DISCOVERY_SORTS:
        for page in range(1,DISCOVERY_PAGES_PER_SORT+1):
            if _runtime_expired(deadline):
                telemetry["runtime_deadline_reached"]=True
                return
            try:
                payload=_api("/pools",dict(
                    page=page,page_size=DISCOVERY_PAGE_SIZE,
                    sort_by=sort_by,filter_by="is_blacklisted=false",
                ))
            except Exception as exc:
                telemetry["errors"].append(dict(
                    sort=sort_by,page=page,reason=type(exc).__name__))
                break
            rows=payload.get("data") if isinstance(payload,dict) else None
            if not isinstance(rows,list):
                telemetry["errors"].append(dict(
                    sort=sort_by,page=page,reason="api_shape"))
                break
            for raw_rank,row in enumerate(rows,1):
                if _runtime_expired(deadline):
                    telemetry["runtime_deadline_reached"]=True
                    return
                if not isinstance(row,dict) or not _sol_pair(row):
                    continue
                address=row.get("address")
                if not isinstance(address,str) or not address or address in seen:
                    continue
                seen.add(address);telemetry["seen"]+=1
                raw=_candidate(row)
                raw["sources"]=[dict(
                    sort=sort_by,rank=(page-1)*DISCOVERY_PAGE_SIZE+raw_rank)]
                observed_at=int(time.time())
                try:
                    telemetry["history_reads"]+=1
                    item=_history_acceleration(raw,observed_at)
                except Exception as exc:
                    telemetry["rejections"].append(dict(
                        pool=address,
                        failed=["acceleration_history_unavailable"],
                        reason=type(exc).__name__,
                        candidate=raw,
                    ))
                    if checkpoint is not None:
                        checkpoint("discovery_history_unavailable")
                    continue
                failed=[]
                if item["volume_acceleration"]<float(
                        regime["min_volume_acceleration"]):
                    failed.append("volume_acceleration")
                if item["fee_acceleration"]<float(
                        regime["min_fee_acceleration"]):
                    failed.append("fee_acceleration")
                if failed:
                    telemetry["rejections"].append(dict(
                        pool=address,failed=failed,candidate=item))
                    if checkpoint is not None:
                        checkpoint("discovery_rejection")
                    continue
                item["signal_observed_at"]=observed_at
                item["discovery_sort"]=sort_by
                item["discovery_page"]=page
                item["discovery_raw_rank"]=raw_rank
                telemetry["qualified"].append(item)
                if checkpoint is not None:
                    checkpoint("discovery_signal")
                yield item
            if len(rows)<DISCOVERY_PAGE_SIZE:
                break


def discover(policy,scan_cap):
    """Compatibility collector used by unit tests; live execution streams instead."""
    telemetry={}
    accepted=[]
    for item in _iter_acceleration_candidates(policy,telemetry):
        accepted.append(item)
        if len(accepted)>=scan_cap:
            break
    return (
        accepted,
        telemetry.get("rejections",[]),
        telemetry.get("errors",[]),
    )


def _rpc_metrics(rpc):
    data=dict(
        calls=int(rpc.calls),http_requests=int(rpc.http_requests),
        failures=int(rpc.failures),retries=int(rpc.retries),
        failure_kinds=dict(getattr(rpc,"failure_kinds",{}) or {}),
        failure_methods=dict(getattr(rpc,"failure_methods",{}) or {}),
    )
    telemetry=getattr(rpc,"provider_telemetry",None)
    if callable(telemetry):
        try:
            data["provider"]=telemetry()
        except Exception:
            data["provider"]={"telemetry_unavailable":True}
    return data


def _sum_rpc_metrics(rpcs):
    failure_kinds=Counter()
    failure_methods=Counter()
    sessions=[]
    for rpc in rpcs:
        failure_kinds.update(getattr(rpc,"failure_kinds",{}) or {})
        failure_methods.update(getattr(rpc,"failure_methods",{}) or {})
        sessions.append(_rpc_metrics(rpc))
    return dict(
        calls=sum(int(r.calls) for r in rpcs),
        http_requests=sum(int(r.http_requests) for r in rpcs),
        failures=sum(int(r.failures) for r in rpcs),
        retries=sum(int(r.retries) for r in rpcs),
        failure_kinds=dict(sorted(failure_kinds.items())),
        failure_methods=dict(sorted(failure_methods.items())),
        session_count=len(rpcs),
        sessions=sessions,
    )


def _prove_network_identity(pacer,rpcs):
    attempts=[]
    for index in range(1,NETWORK_IDENTITY_MAX_ATTEMPTS+1):
        rpc=provider.new_rpc(limit=PER_RPC_LIMIT,pacer=pacer)
        rpcs.append(rpc)
        try:
            genesis=rpc.call(
                "getGenesisHash",priority=True,fresh=True)
            if genesis!=dlmm.pump.MAINNET:
                raise Unavailable("unsupported_network")
            attempts.append(dict(
                attempt=index,verified=True,rpc=_rpc_metrics(rpc)))
            return dict(
                verified=True,genesis_hash=genesis,
                attempts=attempts,verified_attempt=index)
        except (Unavailable,ValueError,KeyError,TypeError) as exc:
            attempts.append(dict(
                attempt=index,verified=False,reason=str(exc)[:120],
                rpc=_rpc_metrics(rpc)))
            if index<NETWORK_IDENTITY_MAX_ATTEMPTS:
                time.sleep(NETWORK_IDENTITY_RETRY_SECONDS*index)
    raise Unavailable("solana_network_identity_unavailable")


def _new_adapter(pacer,rpcs):
    # Network identity is proven once per research run. Rotated RPC sessions use
    # the same authenticated endpoint and do not repeat fragile getGenesisHash.
    rpc=provider.new_rpc(limit=PER_RPC_LIMIT,pacer=pacer)
    rpcs.append(rpc)
    return dlmm.Adapter(rpc,network_verified=True)


def _rotate(adapter,pacer,rpcs):
    return adapter if int(adapter.rpc.calls)<ROTATE_AT_CALLS else _new_adapter(pacer,rpcs)


def _atomic_checkpoint(report,stage,rpcs,pacer,**progress):
    report["checkpoint"]=dict(
        stage=stage,written_at=int(time.time()),**progress)
    report["rpc"]=_sum_rpc_metrics(rpcs)
    report["alchemy_pacer"]=pacer.telemetry()
    tmp=OUT.with_suffix(OUT.suffix+".tmp")
    tmp.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    os.replace(tmp,OUT)


def _runtime_expired(deadline):
    return deadline is not None and time.monotonic()>=deadline


def _runtime_remaining(deadline):
    return (float("inf") if deadline is None
            else max(0.0,deadline-time.monotonic()))


def _rate_limit_failures(rpcs):
    return sum(
        int((getattr(rpc,"failure_methods",{}) or {}).get(
            method,0))
        for rpc in rpcs
        for method in (
            "getSignaturesForAddress:http_429",
            "getTransaction:http_429",
            "getMultipleAccounts:http_429",
            "getBlockTime:http_429",
            "getGenesisHash:http_429",
        )
    )


def _is_new_rate_limit(rpcs,before):
    return _rate_limit_failures(rpcs)>int(before)


def _retry_rate_limited_operation(
    operation,adapter,pacer,rpcs,deadline=None
):
    consecutive=0
    while True:
        before=_rate_limit_failures(rpcs)
        try:
            return operation(adapter),adapter
        except Unavailable:
            if not _is_new_rate_limit(rpcs,before):
                raise
            consecutive+=1
            if consecutive>RATE_LIMIT_RECOVERY_MAX_CONSECUTIVE:
                raise Unavailable("solana_dlmm_rate_limit_recovery_exhausted")
            if _runtime_expired(deadline):
                raise Unavailable("experiment_runtime_deadline")
            adapter=_rotate(adapter,pacer,rpcs)
            # Shared pacer already owns the adaptive cooldown. Calling pace on the
            # next request is sufficient; no independent per-candidate backoff loop.
            continue


def _fresh_supported_start(adapter,candidate):
    snap=adapter.snapshot(candidate["address"],int(time.time()),True,fresh=True)
    state=dlmm.validate(snap,snap["available_time"],"real")
    dlmm.scout(snap,snap["available_time"],dict(
        pool=candidate["address"],x=candidate["token_x"],y=candidate["token_y"]))
    return state



def _complete_signature_census(rpc,pool,start_slot,end_slot,broker=None):
    """Prove finalized signature coverage with an incremental per-pool ledger.

    The first interval performs the bounded boundary proof. Later intervals fetch
    only signatures newer than the durable head, while the cached lower-bound
    witness preserves exact interval completeness. This never weakens the unchanged
    MAX_TRANSACTIONS bound.
    """
    scope="dlmm_interval"
    pages=0;rows_scanned=0

    def fetch_page(*,before=None,until=None):
        nonlocal pages,rows_scanned
        params=dict(limit=SIGNATURE_PAGE_LIMIT,commitment="finalized")
        if before is not None:
            params["before"]=before
        if until is not None:
            params["until"]=until
        page=rpc.call("getSignaturesForAddress",[pool,params],True)
        pages+=1
        if not isinstance(page,list) or len(page)>SIGNATURE_PAGE_LIMIT:
            raise Unavailable("solana_dlmm_signature_shape")
        for row in page:
            if not isinstance(row,dict):
                raise Unavailable("solana_dlmm_signature_shape")
            signature=row.get("signature");slot=row.get("slot")
            if not isinstance(signature,str) or not signature:
                raise Unavailable("solana_dlmm_signature_shape")
            if type(slot) is not int or slot<0:
                raise Unavailable("solana_dlmm_signature_shape")
            if row.get("confirmationStatus")!="finalized":
                raise Unavailable("solana_dlmm_signature_not_finalized")
        rows_scanned+=len(page)
        return page

    if broker is None:
        collected=[];seen=set();before=None;boundary=None
        for _ in range(MAX_SIGNATURE_CENSUS_PAGES):
            page=fetch_page(before=before)
            if not page:
                break
            for row in page:
                signature=row["signature"]
                if signature in seen:
                    raise Unavailable("solana_dlmm_signature_census_duplicate")
                seen.add(signature);collected.append(row)
                if row["slot"]<=start_slot and boundary is None:
                    boundary=row
            relevant=[
                row for row in collected
                if start_slot<row["slot"]<=end_slot and not row.get("err")
            ]
            if len(relevant)>MAX_TRANSACTIONS:
                raise Unavailable("solana_dlmm_transaction_pressure_overflow")
            if boundary is not None:
                break
            if len(page)<SIGNATURE_PAGE_LIMIT:
                break
            before=page[-1]["signature"]
    else:
        coverage=broker.signature_coverage(scope,pool)
        old_head=coverage.get("newest_signature")
        old_oldest=coverage.get("oldest_slot")

        # Extend the head only once per interval. The "until" cursor avoids
        # re-reading the already authenticated prefix.
        if int(coverage.get("covered_through_slot") or 0)<int(end_slot):
            before=None
            for _ in range(MAX_SIGNATURE_CENSUS_PAGES):
                page=fetch_page(before=before,until=old_head)
                if page:
                    broker.remember_signatures(scope,pool,page)
                if not page or len(page)<SIGNATURE_PAGE_LIMIT:
                    break
                before=page[-1]["signature"]

        coverage=broker.signature_coverage(scope,pool)
        # Establish or extend the lower-bound witness only when needed.
        oldest=coverage.get("oldest_slot")
        if oldest is None or int(oldest)>int(start_slot):
            before=None
            rows=broker.signature_rows(scope,pool)
            if rows:
                oldest_row=min(rows,key=lambda row:(row["slot"],row["signature"]))
                before=oldest_row["signature"]
            for _ in range(MAX_SIGNATURE_CENSUS_PAGES):
                page=fetch_page(before=before)
                if page:
                    broker.remember_signatures(scope,pool,page)
                if not page:
                    break
                if any(int(row["slot"])<=int(start_slot) for row in page):
                    break
                if len(page)<SIGNATURE_PAGE_LIMIT:
                    break
                before=page[-1]["signature"]

        # A successful finalized query proves the ledger current through this
        # authenticated interval end even when no new pool transaction occurred.
        broker.remember_signatures(
            scope,pool,[],covered_through_slot=int(end_slot))
        collected=broker.signature_rows(scope,pool,end_slot=end_slot)
        boundary_rows=[
            row for row in collected if int(row["slot"])<=int(start_slot)]
        boundary=(
            max(boundary_rows,key=lambda row:(row["slot"],row["signature"]))
            if boundary_rows else None
        )

    if boundary is None:
        raise Unavailable("solana_dlmm_signature_census_missing_start_boundary")
    relevant=[
        row for row in collected
        if start_slot<row["slot"]<=end_slot and not row.get("err")
    ]
    if len(relevant)>MAX_TRANSACTIONS:
        raise Unavailable("solana_dlmm_transaction_pressure_overflow")
    witness=dict(boundary)
    if type(witness.get("transactionIndex")) is not int:
        witness["transactionIndex"]=0
    selected=[]
    for row in relevant:
        item=dict(row)
        if type(item.get("transactionIndex")) is not int:
            raise Unavailable("solana_dlmm_transaction_index_unavailable")
        selected.append(item)
    selected.append(witness)
    selected.sort(
        key=lambda row:(row["slot"],row["transactionIndex"]),reverse=True)
    return selected,dict(
        pages=pages,rows_scanned=rows_scanned,
        relevant_successful=len(relevant),
        start_boundary_slot=boundary["slot"],
        cache_enabled=broker is not None,
        cached_prefix_reused=bool(
            broker is not None and old_head is not None),
        prior_oldest_slot=(
            None if broker is None else old_oldest),
    )

def _capture_chunk(
    adapter,start,cursor,wait_seconds,broker=None,hydration_kind="dlmm_fresh"
):
    if wait_seconds<=0:
        raise ValueError("solana_dlmm_chunk_wait")
    time.sleep(wait_seconds)
    end_snapshot=adapter.snapshot_from_state(
        start,int(time.time()),True,fresh=True)
    signatures,census=_complete_signature_census(
        adapter.rpc,start["pool"],start["slot"],end_snapshot["slot"],broker)
    relevant=[
        row for row in signatures
        if start["slot"]<row["slot"]<=end_snapshot["slot"] and not row.get("err")
    ]
    if broker is not None and relevant:
        signatures_to_hydrate=[s["signature"] for s in relevant]
        txmap,hydration=broker.hydrate_transactions(
            adapter.rpc,signatures_to_hydrate,kind=hydration_kind,
            deadline=time.time()+6.0,max_version=1,batch_size=8)
        if hydration["pending"]:
            raise Unavailable("solana_dlmm_transaction_hydration_incomplete")
        transactions={
            s["signature"]:txmap[s["signature"]]
            for s in relevant if txmap.get(s["signature"]) is not None
        }
        census["transaction_hydration"]=hydration
    else:
        params=[[
            s["signature"],dict(
                encoding="json",commitment="finalized",
                maxSupportedTransactionVersion=1)
        ] for s in relevant]
        values=(adapter.rpc.call_many(
            "getTransaction",params,True,batch_size=8) if params else [])
        transactions={s["signature"]:tx for s,tx in zip(relevant,values)}
    if len(encode(transactions))>2_000_000:
        raise Unavailable("solana_dlmm_interval_evidence_bound")
    tape=reconstruct(
        start,end_snapshot,signatures,transactions,int(time.time()),cursor)
    actions=ordered_tape_actions(tape)
    next_cursor=(list(actions[-1][1].get("cursor") or cursor)
                 if actions else list(cursor))
    return tape,next_cursor,census


def _observe_window(
    adapter,address,start,total_seconds,allow_reset,pacer,rpcs,deadline=None,
    broker=None,hydration_kind="dlmm_fresh"
):
    origin=start;current=start
    cursor=[start["slot"],2**31-1,2**31-1]
    chunks=[];elapsed=0;resets=0;meta=[];rate_limit_recoveries=0
    while elapsed<total_seconds:
        if _runtime_expired(deadline):
            return dict(
                verified=False,reason="experiment_runtime_deadline",
                elapsed_seconds=elapsed,resets=resets,chunks=meta,
                rate_limit_recoveries=rate_limit_recoveries,
            ),None,current,origin,adapter
        adapter=_rotate(adapter,pacer,rpcs)
        duration=min(CHUNK_SECONDS,total_seconds-elapsed)
        if _runtime_remaining(deadline)<duration:
            return dict(
                verified=False,reason="experiment_runtime_deadline",
                elapsed_seconds=elapsed,resets=resets,chunks=meta,
            ),None,current,origin,adapter
        rate_limit_before=_rate_limit_failures(rpcs)
        try:
            tape,cursor,census=_capture_chunk(
                adapter,current,cursor,duration,broker,hydration_kind)
        except (Unavailable,ValueError,KeyError,TypeError) as exc:
            reason=str(exc)
            if (reason=="provider_request_failed"
                    and _is_new_rate_limit(
                        rpcs,rate_limit_before)):
                rate_limit_recoveries+=1
                if rate_limit_recoveries>RATE_LIMIT_RECOVERY_MAX_CONSECUTIVE:
                    return dict(
                        verified=False,
                        reason="solana_dlmm_rate_limit_recovery_exhausted",
                        elapsed_seconds=elapsed,resets=resets,chunks=meta,
                        rate_limit_recoveries=rate_limit_recoveries,
                    ),None,current,origin,adapter
                adapter=_rotate(adapter,pacer,rpcs)
                continue
            if (allow_reset and reason.startswith("dlmm_snapshot_reset_required:")
                    and resets<MAX_WARMUP_RESETS):
                adapter=_rotate(adapter,pacer,rpcs)
                fresh=dlmm.validate(
                    adapter.snapshot(address,int(time.time()),True,fresh=True),
                    int(time.time()),"real")
                origin=fresh;current=fresh
                cursor=[fresh["slot"],2**31-1,2**31-1]
                chunks=[];meta=[];elapsed=0;resets+=1
                continue
            return dict(
                verified=False,reason=reason,elapsed_seconds=elapsed,
                resets=resets,chunks=meta,
                rate_limit_recoveries=rate_limit_recoveries,
            ),None,current,origin,adapter
        chunks.append(tape);current=tape.terminal;elapsed+=duration
        meta.append(dict(
            start_slot=tape.events[0]["previous_cursor"][0]
                if tape.events else None,
            end_slot=current["slot"],swaps=len(tape.events),
            adjustments=len(tape.terminal_adjustments),
            signature_census=census,
        ))
    combined=chain_verified_tapes(origin,chunks)
    return dict(
        verified=True,elapsed_seconds=elapsed,resets=resets,chunks=meta,
        rate_limit_recoveries=rate_limit_recoveries,
        swaps=len(combined.events),lineage=combined.lineage,
    ),combined,current,origin,adapter


def _to_sol(state,amount,token,bin_id):
    if amount<=0:return 0
    if token==dlmm.WSOL:return int(amount)
    p=dlmm.price(bin_id,state["step"])
    if state["y"]==dlmm.WSOL:
        return int(amount)*p//dlmm.Q
    return int(amount)*dlmm.Q//p


def _event_volume_sol(start,event):
    bid=event["observed"]["start"]
    token=start["x"] if event["for_y"] else start["y"]
    return _to_sol(start,event["amount"],token,bid)


def _event_fee_sol(start,event):
    bid=event["observed"]["start"]
    token=start["x"] if event["for_y"] else start["y"]
    return _to_sol(start,event["observed"]["fee"],token,bid)


def _base_fee_bps(state):
    s=state["parameters"]
    raw=s["base_factor"]*state["step"]*10*10**s["base_fee_power_factor"]
    return raw*10000/dlmm.FEE_PRECISION


def _current_fee_bps(state):
    return dlmm.total_fee(state)*10000/dlmm.FEE_PRECISION


def _fee_uplift(state):
    base=_base_fee_bps(state)
    return (99.0 if base<=0 and _current_fee_bps(state)>0
            else 0.0 if base<=0 else _current_fee_bps(state)/base)


def _movement_half_width(warm,entry,policy):
    r=policy["range"];center=int(entry["active"])
    observed=[]
    for e in warm.events:
        observed.extend([int(e["observed"]["start"]),int(e["observed"]["end"])])
    excursion=max([abs(x-center) for x in observed] or [1])
    scaled=excursion*math.sqrt(
        float(r["intended_holding_seconds"])/float(r["warmup_seconds"]))
    half=int(math.ceil(scaled*float(r["movement_safety_factor"])))
    return max(int(r["min_half_width_bins"]),
               min(int(r["max_half_width_bins"]),half))


def _centered_ids(state,half):
    active=int(state["active"])
    lower=list(range(active-half,active))
    upper=list(range(active+1,active+half+1))
    ids=lower+upper
    if any(str(bid) not in state["bins"] for bid in ids):
        raise Unavailable("solana_dlmm_missing_centered_range_bin")
    return lower,upper


def _range_liquidity_sol(state,ids):
    total=0
    for bid in ids:
        b=state["bins"][str(bid)]
        total+=_to_sol(state,b["x"],state["x"],bid)
        total+=_to_sol(state,b["y"],state["y"],bid)
    return total


def _range_flow_features(start,tape,lower,upper,liquidity_state=None):
    lower_edge=min(lower+upper);upper_edge=max(lower+upper)
    ids=lower+upper
    liquidity_state=start if liquidity_state is None else liquidity_state
    range_liquidity=_range_liquidity_sol(liquidity_state,ids)
    total_volume=total_fee=0
    direction={True:0,False:0}
    movement=[];travel=0
    start_bin=None;end_bin=None
    touches=0
    for event in tape.events:
        s=int(event["observed"]["start"]);e=int(event["observed"]["end"])
        lo,hi=sorted((s,e))
        if hi<lower_edge or lo>upper_edge:
            continue
        touches+=1
        volume=_event_volume_sol(start,event)
        fee=_event_fee_sol(start,event)
        total_volume+=volume;total_fee+=fee
        direction[bool(event["for_y"])]+=volume
        travel+=abs(e-s)
        if start_bin is None:start_bin=s
        end_bin=e
        if e!=s:movement.append(1 if e>s else -1)
    directional=sum(direction.values())
    balance=(0.0 if directional<=0 else
             2*min(direction.values())/directional)
    reversals=sum(a!=b for a,b in zip(movement,movement[1:]))
    drift=(0.0 if travel<=0 or start_bin is None or end_bin is None
           else abs(end_bin-start_bin)/travel)
    seconds=max(1,int(tape.terminal["time"])-int(start["time"]))
    return dict(
        touch_swaps=touches,range_liquidity_sol_lamports=range_liquidity,
        range_volume_sol_lamports=total_volume,
        range_fee_sol_lamports=total_fee,
        volume_rate_sol_lamports_per_second=total_volume/seconds,
        fee_rate_sol_lamports_per_second=total_fee/seconds,
        volume_to_active_liquidity=(
            0.0 if range_liquidity<=0 else total_volume/range_liquidity),
        fee_density=(
            0.0 if range_liquidity<=0 else total_fee/range_liquidity),
        two_way_balance=balance,reversal_count=reversals,
        travel_bins=travel,drift_ratio=drift,
        observed_seconds=seconds,
    )


def _stress_roundtrip(entry,fraction):
    sol_input=max(1,int(CAPITAL*float(fraction)))
    sol_is_x=entry["x"]==dlmm.WSOL
    post,quote=dlmm.swap(
        deepcopy(entry),sol_input,sol_is_x,int(entry["time"]))
    token=int(quote["output"])
    _,back=dlmm.swap(
        deepcopy(post),token,not sol_is_x,int(entry["time"]))
    output=int(back["output"])
    loss=max(0,sol_input-output)
    return dict(
        sol_input_lamports=sol_input,token_output_raw=token,
        executable_sol_back_lamports=output,
        loss_lamports=loss,loss_bps=loss*10000/sol_input,
    )


def pre_entry_features(warm_start,warm,entry,candidate,policy):
    half=_movement_half_width(warm,entry,policy)
    lower,upper=_centered_ids(entry,half)
    flow=_range_flow_features(
        warm_start,warm,lower,upper,liquidity_state=entry)
    q=policy["qualification"]
    liquidity=flow["range_liquidity_sol_lamports"]
    capture_share=(
        0.0 if liquidity<=0 else CAPITAL/(liquidity+CAPITAL))
    projected=(
        flow["range_fee_sol_lamports"]*capture_share
        *float(q["projected_fee_horizon_seconds"])
        /max(1,float(flow["observed_seconds"]))
    )
    stress=_stress_roundtrip(entry,q["stress_inventory_fraction_of_capital"])
    expected_net=projected-ROUND_TRIP_NETWORK_COST-stress["loss_lamports"]
    hours=float(policy["range"]["intended_holding_seconds"])/3600.0
    paired_info=(
        entry["token_y_mint_info"] if entry["x"]==dlmm.WSOL
        else entry["token_x_mint_info"])
    return dict(
        paired_token_program=paired_info["program"],
        paired_token_extensions=list(paired_info.get("extensions") or ()),
        issuer_mint_authority_present=bool(
            paired_info.get("mint_authority_present")),
        freeze_authority_present=bool(
            paired_info.get("freeze_authority_present")),
        half_width_bins=half,total_width_bins=half*2,
        lower=min(lower),upper=max(upper),
        range_lower_bins=lower,range_upper_bins=upper,
        capital_to_competing_liquidity_ratio=(
            None if liquidity<=0 else CAPITAL/liquidity),
        competing_liquidity_to_capital_multiple=liquidity/CAPITAL,
        estimated_fee_capture_share=capture_share,
        projected_fee_capture_lamports=projected,
        stress_inventory_roundtrip=stress,
        expected_net_lamports=expected_net,
        expected_after_cost_pnl_bps_per_capital_hour=(
            expected_net/CAPITAL*10000/hours),
        current_fee_bps=_current_fee_bps(entry),
        base_fee_bps=_base_fee_bps(entry),
        dynamic_fee_uplift=_fee_uplift(entry),
        volume_acceleration=candidate["volume_acceleration"],
        fee_acceleration=candidate["fee_acceleration"],
        **flow,
    )


def qualify(features,policy):
    r=policy["regime"];q=policy["qualification"]
    checks=dict(
        volume_acceleration=features["volume_acceleration"]>=float(
            r["min_volume_acceleration"]),
        fee_acceleration=features["fee_acceleration"]>=float(
            r["min_fee_acceleration"]),
        capacity=features["competing_liquidity_to_capital_multiple"]>=float(
            q["min_competing_range_liquidity_to_capital_multiple"]),
        two_way=features["two_way_balance"]>=float(q["min_two_way_balance"]),
        drift=features["drift_ratio"]<=float(q["max_drift_ratio"]),
        reversal=(not q["require_reversal"] or features["reversal_count"]>0),
        unwind=features["stress_inventory_roundtrip"]["loss_bps"]<=float(
            q["max_stress_unwind_loss_bps"]),
        expected_net=features["expected_net_lamports"]>=int(
            q["min_expected_net_lamports"]),
    )
    return dict(
        passes=all(checks.values()),checks=checks,
        failed=[k for k,v in checks.items() if not v],
        rule="solana_dlmm_independent_v1",fitted_thresholds=False,
    )


def _equal_split(total,count):
    if count<=0:raise ValueError("solana_dlmm_split_count")
    rows=[total//count]*count
    rows[-1]+=total-sum(rows)
    return rows


def _build_position(entry,features,policy):
    half=int(features["half_width_bins"])
    conversion=int(CAPITAL*float(policy["position"]["sol_share_before_conversion"]))
    remaining=CAPITAL-conversion
    sol_is_x=entry["x"]==dlmm.WSOL
    virtual,quote=dlmm.swap(
        deepcopy(entry),conversion,sol_is_x,int(entry["time"]))
    if int(virtual["active"])!=int(entry["active"]):
        raise Unavailable("solana_dlmm_entry_conversion_moves_active_bin")
    token=int(quote["output"])
    lower,upper=_centered_ids(virtual,half)
    sol_bins=(upper if sol_is_x else lower)
    token_bins=(lower if sol_is_x else upper)
    sol_amounts=_equal_split(remaining,len(sol_bins))
    token_amounts=_equal_split(token,len(token_bins))
    shares={};fee_start={}
    deposits=[]
    for bid,amount in zip(sol_bins,sol_amounts):
        b=virtual["bins"][str(bid)]
        x,y=(amount,0) if sol_is_x else (0,amount)
        if x and b["y"] or y and b["x"]:
            raise Unavailable("solana_dlmm_sol_side_bin_composition")
        share=dlmm.deposit_share(b,x,y)
        if share<=0:raise Unavailable("solana_dlmm_zero_sol_side_share")
        shares[str(bid)]=share;fee_start[str(bid)]={"x":b["fee_x"],"y":b["fee_y"]}
        b["x"]+=x;b["y"]+=y;b["supply"]+=share
        deposits.append(dict(bin=bid,x=x,y=y))
    for bid,amount in zip(token_bins,token_amounts):
        b=virtual["bins"][str(bid)]
        x,y=(0,amount) if sol_is_x else (amount,0)
        if x and b["y"] or y and b["x"]:
            raise Unavailable("solana_dlmm_token_side_bin_composition")
        share=dlmm.deposit_share(b,x,y)
        if share<=0:raise Unavailable("solana_dlmm_zero_token_side_share")
        shares[str(bid)]=share;fee_start[str(bid)]={"x":b["fee_x"],"y":b["fee_y"]}
        b["x"]+=x;b["y"]+=y;b["supply"]+=share
        deposits.append(dict(bin=bid,x=x,y=y))
    return dict(
        lower=min(lower+upper),upper=max(lower+upper),half_width=half,
        shares=shares,fee_start=fee_start,virtual=virtual,
        entry_active=virtual["active"],entry_slot=entry["slot"],
        entry_time=entry["time"],entry_conversion_sol_lamports=conversion,
        entry_conversion_token_raw=token,deposits=deposits,
    )


def _advance_position(position,tape):
    p=deepcopy(position);state=deepcopy(p["virtual"])
    for kind,item in ordered_tape_actions(tape):
        if kind=="swap":
            state,_=replay_swap_event(state,item)
        else:
            state=apply_external_adjustment(state,item,counterfactual=True)
        if isinstance(item.get("slot"),int):state["slot"]=max(state["slot"],item["slot"])
        if isinstance(item.get("time"),int):state["time"]=max(state["time"],item["time"])
    state["slot"]=tape.terminal["slot"];state["time"]=tape.terminal["time"]
    p["virtual"]=state
    return p


def _withdraw(position):
    state=deepcopy(position["virtual"])
    assets={"x":0,"y":0,"fee_x":0,"fee_y":0}
    for bid,share in position["shares"].items():
        b=state["bins"][bid]
        x=dlmm.withdraw_amount(share,b["x"],b["supply"])
        y=dlmm.withdraw_amount(share,b["y"],b["supply"])
        start=position["fee_start"][bid]
        fx=dlmm.claim_fee(share,b["fee_x"]-start["x"])
        fy=dlmm.claim_fee(share,b["fee_y"]-start["y"])
        for k,v in (("x",x),("y",y),("fee_x",fx),("fee_y",fy)):
            assets[k]+=v
        b["x"]-=x;b["y"]-=y;b["supply"]-=share
    return state,assets


def _mark(position):
    state,assets=_withdraw(position)
    sol_side="x" if state["x"]==dlmm.WSOL else "y"
    token_side="y" if sol_side=="x" else "x"
    sol=assets[sol_side]+assets["fee_"+sol_side]
    tokens=assets[token_side]+assets["fee_"+token_side]
    liquidation=0
    if tokens:
        _,quote=dlmm.swap(
            deepcopy(state),tokens,sol_side=="y",int(state["time"]))
        liquidation=int(quote["output"]);sol+=liquidation
    pnl=sol-CAPITAL-ROUND_TRIP_NETWORK_COST
    return dict(
        resolved=True,ending_sol_lamports=sol,pnl_lamports=pnl,
        pnl_bps=pnl*10000/CAPITAL,
        non_sol_inventory_raw=tokens,
        non_sol_inventory_liquidation_lamports=liquidation,
        non_sol_inventory_fraction_of_initial_capital=liquidation/CAPITAL,
        active_bin=state["active"],time=state["time"],slot=state["slot"],
    )


def _segment_exit(position,real_start,tape,real_terminal,entry_flow,policy):
    exit_policy=policy["exit"]
    lower=list(range(position["lower"],position["entry_active"]))
    upper=list(range(position["entry_active"]+1,position["upper"]+1))
    recent=_range_flow_features(real_start,tape,lower,upper)
    mark=_mark(position)
    active=int(real_terminal["active"])
    boundary=(active<=position["lower"]+2 or active>=position["upper"]-2)
    inventory=mark["non_sol_inventory_fraction_of_initial_capital"]>0.60
    directional=(
        recent["touch_swaps"]>=2
        and recent["two_way_balance"]<0.25
        and recent["drift_ratio"]>0.75
    )
    volume_collapse=(
        recent["touch_swaps"]>=2
        and recent["volume_rate_sol_lamports_per_second"]
            <0.50*entry_flow["volume_rate_sol_lamports_per_second"]
    )
    fee_collapse=(
        recent["touch_swaps"]>=2
        and recent["fee_density"]<0.50*entry_flow["fee_density"]
    )
    fee_uplift=_fee_uplift(real_terminal)
    dynamic_fee_collapse=(
        fee_uplift<1.05
        and recent["volume_rate_sol_lamports_per_second"]
            <entry_flow["volume_rate_sol_lamports_per_second"]
    )
    reasons=[]
    if boundary:reasons.append("range_boundary")
    if inventory:reasons.append("inventory_imbalance")
    if directional:reasons.append("one_way_flow")
    if volume_collapse:reasons.append("volume_collapse")
    if fee_collapse:reasons.append("fee_density_collapse")
    if dynamic_fee_collapse:reasons.append("dynamic_fee_collapse")
    return reasons,recent,mark,fee_uplift


def _lifecycle(
    adapter,address,entry,features,policy,pacer,rpcs,deadline=None,broker=None
):
    position=_build_position(entry,features,policy)
    current=entry;elapsed=0;segments=[];tapes=[]
    max_hold=int(policy["range"]["max_holding_seconds"])
    segment_seconds=int(policy["exit"]["observation_segment_seconds"])
    lower=list(range(features["lower"],entry["active"]))
    upper=list(range(entry["active"]+1,features["upper"]+1))
    entry_flow=dict(
        volume_rate_sol_lamports_per_second=features[
            "volume_rate_sol_lamports_per_second"],
        fee_density=features["fee_density"],
    )
    exit_reason="maximum_holding_time"
    while elapsed<max_hold:
        adapter=_rotate(adapter,pacer,rpcs)
        duration=min(segment_seconds,max_hold-elapsed)
        phase,tape,terminal,effective_start,adapter=_observe_window(
            adapter,address,current,duration,False,pacer,rpcs,deadline,
            broker,"position_monitor")
        if not phase["verified"]:
            return dict(
                complete=False,reason=phase["reason"],segments=segments,
                verified_hold_seconds=elapsed,
            ),adapter
        position=_advance_position(position,tape)
        reasons,recent,mark,uplift=_segment_exit(
            position,effective_start,tape,terminal,entry_flow,policy)
        elapsed+=duration;tapes.append(tape)
        segments.append(dict(
            elapsed_seconds=elapsed,lineage=tape.lineage,
            swaps=len(tape.events),recent=recent,mark=mark,
            dynamic_fee_uplift=uplift,exit_reasons=reasons,
        ))
        current=terminal
        if reasons:
            exit_reason=reasons[0];break
    combined=chain_verified_tapes(entry,tapes)
    final=_mark(position)
    hours=max(elapsed/3600.0,1/3600.0)
    final["pnl_bps_per_capital_hour"]=final["pnl_bps"]/hours
    return dict(
        complete=True,exit_reason=exit_reason,realized_hold_seconds=elapsed,
        segments=segments,lineage=combined.lineage,final=final,
    ),adapter




def _regime_pass(candidate,policy):
    regime=policy["regime"]
    return (
        candidate["volume_acceleration"]>=float(
            regime["min_volume_acceleration"])
        and candidate["fee_acceleration"]>=float(
            regime["min_fee_acceleration"])
    )


def _new_finalized_swaps(rpc,pool,after_slot,broker=None):
    before429=int((getattr(rpc,"failure_methods",{}) or {}).get(
        "getSignaturesForAddress:http_429",0))
    try:
        rows=rpc.call(
            "getSignaturesForAddress",
            [pool,dict(
                limit=FRESH_SWAP_TRIGGER_SIGNATURE_LIMIT,
                commitment="finalized")],
            True,
        )
    except Unavailable:
        after429=int((getattr(rpc,"failure_methods",{}) or {}).get(
            "getSignaturesForAddress:http_429",0))
        if after429>before429:
            return [],dict(
                rate_limited=True,stage="getSignaturesForAddress",
                head_slot=after_slot,head_signature=None,
                fresh_signature_count=0,
            )
        raise
    if not isinstance(rows,list):
        raise Unavailable("solana_dlmm_trigger_signature_shape")

    head_slot=after_slot
    head_signature=None
    valid=[]
    for row in rows:
        if not isinstance(row,dict):
            continue
        slot=row.get("slot");signature=row.get("signature")
        if type(slot) is not int or not isinstance(signature,str):
            continue
        if head_signature is None or slot>head_slot:
            head_slot=slot;head_signature=signature
        if (not row.get("err")
                and row.get("confirmationStatus")=="finalized"
                and slot>after_slot):
            valid.append(row)
    valid.sort(key=lambda row:(row["slot"],row["signature"]))
    if broker is not None and rows:
        broker.remember_signatures(
            "dlmm_fresh",pool,rows,
            covered_through_slot=max(after_slot,head_slot))
    if not valid:
        return [],dict(
            rate_limited=False,stage=None,
            head_slot=max(after_slot,head_slot),
            head_signature=head_signature,
            fresh_signature_count=0,
        )

    before429=int((getattr(rpc,"failure_methods",{}) or {}).get(
        "getTransaction:http_429",0))
    try:
        if broker is not None:
            sigs=[row["signature"] for row in valid]
            txmap,hydration=broker.hydrate_transactions(
                rpc,sigs,kind="dlmm_fresh",
                deadline=time.time()+5.0,max_version=1,batch_size=8)
            if hydration["pending"]:
                after429=int((getattr(rpc,"failure_methods",{}) or {}).get(
                    "getTransaction:http_429",0))
                return [],dict(
                    rate_limited=after429>before429,
                    stage="getTransaction",
                    head_slot=after_slot,head_signature=None,
                    fresh_signature_count=len(valid),
                    hydration=hydration,
                )
            values=[txmap.get(sig) for sig in sigs]
        else:
            params=[[
                row["signature"],dict(
                    encoding="json",commitment="finalized",
                    maxSupportedTransactionVersion=1)
            ] for row in valid]
            values=rpc.call_many(
                "getTransaction",params,True,batch_size=8)
            hydration=None
    except Unavailable:
        after429=int((getattr(rpc,"failure_methods",{}) or {}).get(
            "getTransaction:http_429",0))
        if after429>before429:
            # Do not advance the cursor; these exact signatures must be retried.
            return [],dict(
                rate_limited=True,stage="getTransaction",
                head_slot=after_slot,head_signature=None,
                fresh_signature_count=len(valid),
            )
        raise

    out=[]
    for row,tx in zip(valid,values):
        if not tx or (tx.get("meta") or {}).get("err"):
            continue
        swaps=transaction_swaps(tx,pool)
        if swaps:
            out.append(dict(
                signature=row["signature"],
                slot=row["slot"],
                block_time=tx.get("blockTime"),
                swap_count=len(swaps),
                swaps=swaps,
            ))
    return out,dict(
        rate_limited=False,stage=None,
        head_slot=max(after_slot,head_slot),
        head_signature=head_signature,
        fresh_signature_count=len(valid),
        hydration=(None if broker is None else hydration),
    )


def _await_fresh_swap_trigger_polling(
    adapter,candidate,baseline_state,policy,pacer,rpcs,deadline=None
):
    started=time.monotonic()
    baseline_slot=int(baseline_state["slot"])
    cursor_slot=baseline_slot
    polls=0
    refreshes=0
    current_candidate=dict(candidate)
    next_refresh=0.0
    while True:
        elapsed=max(0.0,time.monotonic()-started)
        if _runtime_expired(deadline):
            return dict(
                triggered=False,reason="experiment_runtime_deadline",
                waited_seconds=elapsed,polls=polls,
                acceleration_refreshes=refreshes,
                baseline_slot=baseline_slot,
            ),None,adapter,current_candidate
        if elapsed>=FRESH_SWAP_TRIGGER_MAX_SECONDS:
            return dict(
                triggered=False,reason="fresh_swap_trigger_timeout",
                waited_seconds=elapsed,polls=polls,
                acceleration_refreshes=refreshes,
                baseline_slot=baseline_slot,
            ),None,adapter,current_candidate
        if elapsed>=next_refresh:
            observed_at=int(time.time())
            try:
                current_candidate=_history_acceleration(
                    current_candidate,observed_at)
            except Exception as exc:
                return dict(
                    triggered=False,
                    reason="acceleration_refresh_unavailable",
                    detail=type(exc).__name__,
                    waited_seconds=elapsed,polls=polls,
                    acceleration_refreshes=refreshes,
                    baseline_slot=baseline_slot,
                ),None,adapter,current_candidate
            refreshes+=1
            if not _regime_pass(current_candidate,policy):
                return dict(
                    triggered=False,
                    reason="acceleration_regime_expired",
                    waited_seconds=elapsed,polls=polls,
                    acceleration_refreshes=refreshes,
                    baseline_slot=baseline_slot,
                    volume_acceleration=current_candidate[
                        "volume_acceleration"],
                    fee_acceleration=current_candidate[
                        "fee_acceleration"],
                ),None,adapter,current_candidate
            next_refresh=elapsed+FRESH_SWAP_TRIGGER_ACCEL_REFRESH_SECONDS

        adapter=_rotate(adapter,pacer,rpcs)
        swaps,poll_meta=_new_finalized_swaps(
            adapter.rpc,candidate["address"],cursor_slot)
        polls+=1
        if poll_meta.get("rate_limited"):
            remaining=min(
                FRESH_SWAP_TRIGGER_MAX_SECONDS-max(
                    0.0,time.monotonic()-started),
                _runtime_remaining(deadline))
            if remaining<=0:
                continue
            # The shared Alchemy pacer has already installed the adaptive cooldown.
            # Yield control without classifying the candidate as failed.
            time.sleep(min(
                FRESH_SWAP_TRIGGER_POLL_SECONDS,remaining))
            continue
        if swaps:
            trigger=swaps[0]
            trigger_slot=int(trigger["slot"])
            adapter=_rotate(adapter,pacer,rpcs)
            (post,adapter)=_retry_rate_limited_operation(
                lambda active:_fresh_supported_start(
                    active,current_candidate),
                adapter,pacer,rpcs,deadline)
            if int(post["slot"])<trigger_slot:
                # Finalized pool state must be at or beyond the authenticated swap.
                time.sleep(FRESH_SWAP_TRIGGER_POLL_SECONDS)
                continue
            trigger.update(
                triggered=True,
                reason="authenticated_fresh_swap",
                waited_seconds=max(0.0,time.monotonic()-started),
                polls=polls,
                acceleration_refreshes=refreshes,
                baseline_slot=baseline_slot,
                post_trigger_slot=int(post["slot"]),
            )
            return trigger,post,adapter,current_candidate
        # The same signature poll already supplied the finalized head. Advancing
        # from that response removes the prior duplicate head read per loop.
        cursor_slot=max(cursor_slot,int(poll_meta.get("head_slot") or cursor_slot))
        remaining=min(
            FRESH_SWAP_TRIGGER_MAX_SECONDS-max(
                0.0,time.monotonic()-started),
            _runtime_remaining(deadline))
        if remaining<=0:
            continue
        time.sleep(min(FRESH_SWAP_TRIGGER_POLL_SECONDS,remaining))


def _await_fresh_swap_trigger(
    adapter,candidate,baseline_state,policy,pacer,rpcs,deadline=None,broker=None
):
    """Wait on finalized DLMM pool-account wakeups, then authenticate one exact swap.

    HTTP signature polling is no longer the primary fresh-event detector. A finalized
    program-account stream wakes only the changed pool. A targeted signature/transaction
    read then proves that the wake was an actual swap. On a stream gap, one bounded
    recovery read covers the gap from the last authenticated cursor.
    """
    if broker is None:
        return _await_fresh_swap_trigger_polling(
            adapter,candidate,baseline_state,policy,pacer,rpcs,deadline)

    started=time.monotonic()
    baseline_slot=int(baseline_state["slot"])
    cursor_name="dlmm_fresh:"+str(candidate["address"])
    durable_cursor=broker.cursor(cursor_name)
    cursor_slot=max(baseline_slot,int(durable_cursor.get("slot") or 0))
    polls=0;wakeups=0;gap_recoveries=0;refreshes=0
    current_candidate=dict(candidate)
    next_refresh=0.0
    initial_status=broker.stream_status(
        DLMM_WAKE_STREAM_KEY,int(time.time()),0)
    last_gap_count=int(initial_status.get("gaps") or 0)

    while True:
        elapsed=max(0.0,time.monotonic()-started)
        if _runtime_expired(deadline):
            return dict(
                triggered=False,reason="experiment_runtime_deadline",
                waited_seconds=elapsed,polls=polls,wakeups=wakeups,
                gap_recoveries=gap_recoveries,
                acceleration_refreshes=refreshes,baseline_slot=baseline_slot,
            ),None,adapter,current_candidate
        if elapsed>=FRESH_SWAP_TRIGGER_MAX_SECONDS:
            return dict(
                triggered=False,reason="fresh_swap_trigger_timeout",
                waited_seconds=elapsed,polls=polls,wakeups=wakeups,
                gap_recoveries=gap_recoveries,
                acceleration_refreshes=refreshes,baseline_slot=baseline_slot,
            ),None,adapter,current_candidate

        if elapsed>=next_refresh:
            observed_at=int(time.time())
            try:
                current_candidate=_history_acceleration(
                    current_candidate,observed_at)
            except Exception as exc:
                return dict(
                    triggered=False,reason="acceleration_refresh_unavailable",
                    detail=type(exc).__name__,waited_seconds=elapsed,
                    polls=polls,wakeups=wakeups,gap_recoveries=gap_recoveries,
                    acceleration_refreshes=refreshes,baseline_slot=baseline_slot,
                ),None,adapter,current_candidate
            refreshes+=1
            if not _regime_pass(current_candidate,policy):
                return dict(
                    triggered=False,reason="acceleration_regime_expired",
                    waited_seconds=elapsed,polls=polls,wakeups=wakeups,
                    gap_recoveries=gap_recoveries,
                    acceleration_refreshes=refreshes,baseline_slot=baseline_slot,
                    volume_acceleration=current_candidate["volume_acceleration"],
                    fee_acceleration=current_candidate["fee_acceleration"],
                ),None,adapter,current_candidate
            next_refresh=elapsed+FRESH_SWAP_TRIGGER_ACCEL_REFRESH_SECONDS

        now=int(time.time())
        status=broker.stream_status(DLMM_WAKE_STREAM_KEY,now,0)
        gap_count=int(status.get("gaps") or 0)
        events=broker.recent_events(
            DLMM_WAKE_STREAM_KEY,after_slot=cursor_slot,
            address=candidate["address"])
        should_auth=bool(events)

        # A stream gap can hide a wakeup. Recover exactly once per observed gap
        # using the last authenticated per-pool cursor; normal operation does not poll.
        if gap_count>last_gap_count:
            should_auth=True
            gap_recoveries+=1
            last_gap_count=gap_count

        if should_auth:
            wakeups+=len(events)
            adapter=_rotate(adapter,pacer,rpcs)
            swaps,poll_meta=_new_finalized_swaps(
                adapter.rpc,candidate["address"],cursor_slot,broker)
            polls+=1
            if poll_meta.get("rate_limited"):
                remaining=min(
                    FRESH_SWAP_TRIGGER_MAX_SECONDS-max(
                        0.0,time.monotonic()-started),
                    _runtime_remaining(deadline))
                if remaining>0:
                    time.sleep(min(0.5,remaining))
                continue
            new_cursor=max(
                cursor_slot,int(poll_meta.get("head_slot") or cursor_slot))
            if new_cursor>cursor_slot:
                cursor_slot=new_cursor
                broker.advance_cursor(
                    cursor_name,cursor_slot,poll_meta.get("head_signature"))
            if swaps:
                trigger=swaps[0]
                trigger_slot=int(trigger["slot"])
                adapter=_rotate(adapter,pacer,rpcs)
                (post,adapter)=_retry_rate_limited_operation(
                    lambda active:_fresh_supported_start(
                        active,current_candidate),
                    adapter,pacer,rpcs,deadline)
                if int(post["slot"])<trigger_slot:
                    remaining=min(
                        FRESH_SWAP_TRIGGER_MAX_SECONDS-max(
                            0.0,time.monotonic()-started),
                        _runtime_remaining(deadline))
                    if remaining>0:
                        time.sleep(min(0.5,remaining))
                    continue
                trigger.update(
                    triggered=True,reason="authenticated_fresh_swap",
                    wake_source="finalized_program_account_stream",
                    waited_seconds=max(0.0,time.monotonic()-started),
                    polls=polls,wakeups=wakeups,gap_recoveries=gap_recoveries,
                    acceleration_refreshes=refreshes,baseline_slot=baseline_slot,
                    post_trigger_slot=int(post["slot"]),
                )
                return trigger,post,adapter,current_candidate

        remaining=min(
            FRESH_SWAP_TRIGGER_MAX_SECONDS-max(
                0.0,time.monotonic()-started),
            _runtime_remaining(deadline))
        if remaining<=0:
            continue
        time.sleep(min(0.25,remaining))


def _triggered_warmup(
    adapter,candidate,compatibility_state,policy,pacer,rpcs,deadline=None,broker=None
):
    trigger,post_trigger,adapter,current_candidate=(
        _await_fresh_swap_trigger(
            adapter,candidate,compatibility_state,policy,pacer,rpcs,deadline,broker))
    if not trigger.get("triggered"):
        return dict(
            aligned=False,reason=trigger["reason"],trigger=trigger,
        ),None,None,None,adapter,current_candidate
    warmup_seconds=int(policy["range"]["warmup_seconds"])
    phase,warm,entry,warm_origin,adapter=_observe_window(
        adapter,current_candidate["address"],post_trigger,
        warmup_seconds,True,pacer,rpcs,deadline,broker,"dlmm_fresh")
    result=dict(
        aligned=bool(phase.get("verified") and warm is not None and warm.events),
        reason=(
            "verified_nonzero_warmup"
            if phase.get("verified") and warm is not None and warm.events
            else "verified_zero_warmup_after_fresh_swap"
            if phase.get("verified")
            else "warmup_unverified"
        ),
        trigger=trigger,
        warmup=phase,
        qualifying_window_seconds=warmup_seconds,
        swaps=(None if warm is None else len(warm.events)),
    )
    return result,warm,entry,warm_origin,adapter,current_candidate


def _aligned_warmup(adapter,candidate,policy,pacer,rpcs):
    cfg=(policy.get("range") or {}).get("warmup_alignment") or {}
    windows=int(cfg.get("max_fresh_windows") or 1)
    warmup_seconds=int(cfg.get("qualifying_window_seconds")
                       or policy["range"]["warmup_seconds"])
    regime=policy["regime"]
    attempts=[]
    current_candidate=dict(candidate)
    for index in range(windows):
        observed_at=int(time.time())
        try:
            current_candidate=_history_acceleration(current_candidate,observed_at)
        except Exception as exc:
            return dict(
                aligned=False,reason="acceleration_refresh_unavailable",
                detail=type(exc).__name__,windows=attempts,
            ),None,None,None,None,adapter,current_candidate
        acceleration_pass=(
            current_candidate["volume_acceleration"]>=float(
                regime["min_volume_acceleration"])
            and current_candidate["fee_acceleration"]>=float(
                regime["min_fee_acceleration"])
        )
        attempt=dict(
            window=index+1,
            observed_at=observed_at,
            volume_acceleration=current_candidate["volume_acceleration"],
            fee_acceleration=current_candidate["fee_acceleration"],
            acceleration_pass=acceleration_pass,
        )
        if not acceleration_pass:
            attempts.append(attempt)
            return dict(
                aligned=False,reason="acceleration_regime_expired",
                windows=attempts,
            ),None,None,None,None,adapter,current_candidate

        adapter=_rotate(adapter,pacer,rpcs)
        try:
            start=_fresh_supported_start(adapter,current_candidate)
        except Exception as exc:
            attempt.update(
                verified=False,reason=str(exc)[:180],stage="fresh_start")
            attempts.append(attempt)
            raise

        phase,warm,entry,warm_origin,adapter=_observe_window(
            adapter,current_candidate["address"],start,warmup_seconds,
            True,pacer,rpcs)
        attempt.update(
            verified=bool(phase.get("verified")),
            warmup_reason=phase.get("reason"),
            swaps=(None if warm is None else len(warm.events)),
            warmup=phase,
        )
        attempts.append(attempt)
        if not phase.get("verified"):
            return dict(
                aligned=False,reason="warmup_unverified",
                windows=attempts,
            ),warm,entry,warm_origin,start,adapter,current_candidate
        if warm is not None and warm.events:
            return dict(
                aligned=True,reason="verified_nonzero_warmup",
                selected_window=index+1,windows=attempts,
            ),warm,entry,warm_origin,start,adapter,current_candidate
        # Only a verified zero-swap window is retryable. The next iteration
        # refreshes acceleration and takes a completely fresh prestate.
    return dict(
        aligned=False,reason="verified_zero_flow_after_alignment",
        windows=attempts,
    ),None,None,None,None,adapter,current_candidate


def run_live(target=None,max_attempted=None,max_runtime_seconds=None):
    assert_independence()
    policy=load_policy()
    target=int(target or policy["prospective_test"]["target_complete_lifecycles"])
    max_attempted=int(max_attempted or policy["prospective_test"]["max_attempted_pools"])
    if not 1<=target<=int(policy["prospective_test"]["target_complete_lifecycles"]):
        raise ValueError("solana_dlmm_target_bound")
    if not target<=max_attempted<=int(policy["prospective_test"]["max_attempted_pools"]):
        raise ValueError("solana_dlmm_attempt_bound")
    max_runtime_seconds=int(
        max_runtime_seconds or DEFAULT_MAX_RUNTIME_SECONDS)
    if not 60<=max_runtime_seconds<=7200:
        raise ValueError("solana_dlmm_runtime_bound")
    run_started_monotonic=time.monotonic()
    deadline=run_started_monotonic+max_runtime_seconds

    discovery_telemetry=dict(
        rejections=[],errors=[],qualified=[],seen=0,history_reads=0)
    compatibility_rejections=[];compatibility_screened=0
    pacer=provider.AlchemyPacer();rpcs=[]
    network_identity=_prove_network_identity(pacer,rpcs)
    broker=EvidenceBroker(DLMM_BROKER_DB)
    stream_stop=threading.Event();stream_ready=threading.Event()
    wake_stream=ProgramAccountWakeStream(
        DLMM_DISCOVERY_WS_URL,broker,DLMM_WAKE_STREAM_KEY,dlmm.PROGRAM,
        data_size=904,coverage_seconds=2)
    wake_thread=threading.Thread(
        target=wake_stream.run,args=(stream_stop,stream_ready),daemon=True)
    wake_thread.start()
    if not stream_ready.wait(15):
        broker.close()
        raise Unavailable("dlmm_wake_stream_start_timeout")
    report=dict(
        kind="solana_dlmm_independent_v1_prospective",
        policy_revision=policy.get("revision"),frozen_policy=policy,
        allocation_authority=False,signing=False,submission=False,live_money=False,
        independent_of_robinhood=True,independent_of_all_prior_dlmm_strategies=True,
        selector_uses_outcome_data=False,post_freeze_only=True,
        discovery_mode="streaming_immediate_handoff",
        discovery_candidates=discovery_telemetry["qualified"],
        discovery_api_rejections=discovery_telemetry["rejections"],
        discovery_errors=discovery_telemetry["errors"],
        target_complete_lifecycles=target,
        max_attempted_pools=max_attempted,started=int(time.time()),
        attempts=[],qualified_lifecycles=[],
        compatibility_rejections=compatibility_rejections,
        network_identity=network_identity,
        runtime_limit_seconds=max_runtime_seconds,
        evidence_acquisition_mode="program_account_wake_stream_plus_incremental_http_auth",
        wake_stream=broker.stream_status(
            DLMM_WAKE_STREAM_KEY,int(time.time()),0),
        evidence_broker=broker.telemetry(),
    )
    attempted=0;complete=0;failure_counts=Counter()
    def checkpoint(stage):
        report["wake_stream"]=broker.stream_status(
            DLMM_WAKE_STREAM_KEY,int(time.time()),0)
        report["evidence_broker"]=broker.telemetry()
        _atomic_checkpoint(
            report,stage,rpcs,pacer,
            attempted_pool_count=attempted,
            complete_lifecycle_count=complete,
            compatibility_screened_count=compatibility_screened,
            compatibility_rejection_count=len(compatibility_rejections),
            qualification_failure_counts=dict(sorted(failure_counts.items())),
            elapsed_seconds=max(
                0.0,time.monotonic()-run_started_monotonic),
        )
    checkpoint("run_initialized")
    candidate_stream=_iter_acceleration_candidates(
        policy,discovery_telemetry,deadline,checkpoint)
    for candidate in candidate_stream:
        if (_runtime_expired(deadline)
                or attempted>=max_attempted or complete>=target):
            break
        candidate_rpcs=[]
        adapter=_new_adapter(pacer,candidate_rpcs);rpcs.extend(candidate_rpcs)
        compatibility_screened+=1
        try:
            (compatibility_state,adapter)=_retry_rate_limited_operation(
                lambda active:_fresh_supported_start(
                    active,candidate),
                adapter,pacer,candidate_rpcs,deadline)
        except (Unavailable,ValueError,KeyError,TypeError,OverflowError) as exc:
            compatibility_rejections.append(dict(
                pool=candidate["address"],candidate=candidate,
                reason=str(exc)[:200],
                rpc=_sum_rpc_metrics(candidate_rpcs),
            ))
            checkpoint("compatibility_rejection")
            continue

        attempted+=1
        handoff_started_at=int(time.time())
        attempt=dict(
            attempt=attempted,pool=candidate["address"],candidate=candidate,
            signal_to_handoff_seconds=max(
                0,handoff_started_at-int(candidate["signal_observed_at"])),
            handoff_started_at=handoff_started_at,
            compatibility_passed=True,
        )
        try:
            alignment,warm,entry,warm_origin,adapter,aligned_candidate=(
                _triggered_warmup(
                    adapter,candidate,compatibility_state,
                    policy,pacer,candidate_rpcs,deadline,broker))
            # Any rotated RPCs created inside observation are not yet in global list.
            for rpc in candidate_rpcs:
                if rpc not in rpcs:rpcs.append(rpc)
            attempt["fresh_swap_trigger_and_warmup"]=alignment
            if not alignment["aligned"]:
                reason=alignment["reason"]
                attempt["terminal_classification"]=reason
                failure_counts[reason]+=1
                attempt["rpc"]=_sum_rpc_metrics(candidate_rpcs)
                report["attempts"].append(attempt)
                checkpoint("candidate_terminal")
                continue
            attempt["candidate_at_warmup"]=aligned_candidate
            features=pre_entry_features(
                warm_origin,warm,entry,aligned_candidate,policy)
            decision=qualify(features,policy)
            attempt["pre_entry_features"]=features
            attempt["qualification"]=decision
            for failed in decision["failed"]:failure_counts[failed]+=1
            if not decision["passes"]:
                attempt["terminal_classification"]="qualification_rejection"
                attempt["rpc"]=_sum_rpc_metrics(candidate_rpcs)
                report["attempts"].append(attempt)
                checkpoint("qualification_rejection")
                continue
            lifecycle,adapter=_lifecycle(
                adapter,candidate["address"],entry,features,policy,pacer,
                candidate_rpcs,deadline,broker)
            for rpc in candidate_rpcs:
                if rpc not in rpcs:rpcs.append(rpc)
            attempt["lifecycle"]=lifecycle
            attempt["terminal_classification"]=(
                "complete" if lifecycle["complete"] else "lifecycle_unverified")
            attempt["rpc"]=_sum_rpc_metrics(candidate_rpcs)
            report["attempts"].append(attempt)
            if lifecycle["complete"]:
                complete+=1
                report["qualified_lifecycles"].append(dict(
                    pool=candidate["address"],candidate=candidate,
                    pre_entry_features=features,qualification=decision,**lifecycle))
            else:
                failure_counts["lifecycle_unverified"]+=1
            checkpoint("lifecycle_terminal")
        except (Unavailable,ValueError,KeyError,TypeError,OverflowError) as exc:
            attempt["terminal_classification"]="exception"
            attempt["reason"]=str(exc)[:200]
            failure_counts["exception"]+=1
            attempt["rpc"]=_sum_rpc_metrics(candidate_rpcs)
            report["attempts"].append(attempt)
            checkpoint("candidate_exception")

    resolved=[x for x in report["qualified_lifecycles"]
              if (x.get("final") or {}).get("resolved")]
    pnl=[x["final"]["pnl_bps"] for x in resolved]
    capital_hour=[x["final"]["pnl_bps_per_capital_hour"] for x in resolved]
    exits=Counter(x["exit_reason"] for x in resolved)
    report.update(
        ended=int(time.time()),attempted_pool_count=attempted,
        discovery_unique_pool_count=int(discovery_telemetry["seen"]),
        discovery_history_read_count=int(discovery_telemetry["history_reads"]),
        discovery_qualified_count=len(discovery_telemetry["qualified"]),
        discovery_rejection_count=len(discovery_telemetry["rejections"]),
        compatibility_screened_count=compatibility_screened,
        compatibility_rejection_count=len(compatibility_rejections),
        complete_lifecycle_count=complete,target_met=complete>=target,
        qualification_failure_counts=dict(sorted(failure_counts.items())),
        profitable_lifecycle_count=sum(x["final"]["pnl_lamports"]>0 for x in resolved),
        profitable_rate=(None if not resolved else
                         sum(x["final"]["pnl_lamports"]>0 for x in resolved)/len(resolved)),
        median_pnl_bps=(None if not pnl else statistics.median(pnl)),
        mean_pnl_bps=(None if not pnl else statistics.fmean(pnl)),
        median_pnl_bps_per_capital_hour=(
            None if not capital_hour else statistics.median(capital_hour)),
        mean_pnl_bps_per_capital_hour=(
            None if not capital_hour else statistics.fmean(capital_hour)),
        exit_reason_counts=dict(sorted(exits.items())),
        rpc=_sum_rpc_metrics(rpcs),alchemy_pacer=pacer.telemetry(),
        wake_stream=broker.stream_status(
            DLMM_WAKE_STREAM_KEY,int(time.time()),0),
        evidence_broker=broker.telemetry(),
        runtime_limit_reached=_runtime_expired(deadline),
        elapsed_seconds=max(
            0.0,time.monotonic()-run_started_monotonic),
        conclusion=(
            "prospective_target_complete"
            if complete>=target else
            "prospective_20m_window_complete"
            if _runtime_expired(deadline) else
            "prospective_sample_incomplete_no_threshold_change"),
    )
    _atomic_checkpoint(
        report,"final",rpcs,pacer,
        attempted_pool_count=attempted,
        complete_lifecycle_count=complete,
        compatibility_screened_count=compatibility_screened,
        compatibility_rejection_count=len(compatibility_rejections),
        qualification_failure_counts=dict(sorted(failure_counts.items())),
        elapsed_seconds=report["elapsed_seconds"],
    )
    stream_stop.set();wake_thread.join(timeout=5)
    report["wake_stream"]=broker.stream_status(
        DLMM_WAKE_STREAM_KEY,int(time.time()),0)
    report["evidence_broker"]=broker.telemetry()
    broker.close()
    print(json.dumps(dict(
        conclusion=report["conclusion"],attempted=attempted,complete=complete,
        profitable_rate=report["profitable_rate"],
        median_pnl_bps=report["median_pnl_bps"],
        median_pnl_bps_per_capital_hour=report[
            "median_pnl_bps_per_capital_hour"],
        failures=report["qualification_failure_counts"],
        exits=report["exit_reason_counts"],
    ),sort_keys=True))
    return report


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--target-complete",type=int)
    p.add_argument("--max-attempted",type=int)
    p.add_argument("--max-runtime-seconds",type=int,default=DEFAULT_MAX_RUNTIME_SECONDS)
    args=p.parse_args()
    try:
        run_live(
            args.target_complete,args.max_attempted,args.max_runtime_seconds)
    except Exception as exc:
        existing={}
        try:
            existing=json.loads(OUT.read_text()) if OUT.exists() else {}
        except Exception:
            existing={}
        existing.update(
            terminal_failure=dict(
                error=str(exc)[:200],ended=int(time.time()),
                preserved_partial_evidence=bool(existing),
            ),
            conclusion="experiment_failed_partial_evidence_preserved"
                if existing else "experiment_failed_before_valid_terminal_result",
            allocation_authority=False,
        )
        tmp=OUT.with_suffix(OUT.suffix+".tmp")
        tmp.write_text(json.dumps(existing,indent=2,sort_keys=True)+"\n")
        os.replace(tmp,OUT)
        print(json.dumps(dict(
            conclusion=existing["conclusion"],
            error=str(exc)[:200],
            preserved_partial_evidence=bool(existing.get("checkpoint")),
        ),sort_keys=True))
        raise


if __name__=="__main__":
    main()
