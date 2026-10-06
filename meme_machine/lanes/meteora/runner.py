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
from dataclasses import asdict
import uuid
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

from meme_machine.lanes.meteora import dlmm
from meme_machine.lanes.meteora.dlmm_tape import (
    MAX_TRANSACTIONS,
    apply_external_adjustment,
    chain_verified_tapes,
    ordered_tape_actions,
    reconstruct,
    replay_swap_event,
    transaction_swaps,
)
from meme_machine.lanes.meteora.provider import Unavailable
from meme_machine.lanes.meteora.solana_evidence_runtime import RuntimeEvidence,METEORA_SCOPE

EVIDENCE_PLANE=None
CANDIDATE_HISTORY=None

def _evidence_plane():
    global EVIDENCE_PLANE
    if EVIDENCE_PLANE is None:EVIDENCE_PLANE=RuntimeEvidence(owner="meteora")
    return EVIDENCE_PLANE
from meme_machine.lanes.meteora.solana_evidence_broker import (
    DEFAULT_BROKER_DB,EvidenceBroker,ProgramAccountWakeStream,
)
from meme_machine.lanes.meteora.store import encode,digest
from meme_machine.lanes.meteora.dlmm_independent_accounting import PaperBook
from meme_machine.lanes.meteora import dlmm_alchemy_provider as provider

POLICY_PATH=Path(__file__).with_name("SOLANA_DLMM_INDEPENDENT_V1.json")
OUT=Path("solana-dlmm-independent-v1-live.json")
API_BASE="https://dlmm.datapi.meteora.ag"

CAPITAL=100_000_000
ENTRY_NETWORK_COST=200_000
EXIT_NETWORK_COST=200_000
ROUND_TRIP_NETWORK_COST=ENTRY_NETWORK_COST+EXIT_NETWORK_COST

DISCOVERY_PAGE_SIZE=250
DISCOVERY_PAGES_PER_SORT=2
DISCOVERY_SORTS=("fee_tvl_ratio_5m:desc","volume_5m:desc","volume_30m:desc")
PER_RPC_LIMIT=240
ROTATE_AT_CALLS=190
# One-second verification segments retain the exact 12-second warmup and
# unchanged 16-transaction verifier bound while reducing density censoring.
CHUNK_SECONDS=1
MAX_WARMUP_RESETS=2
SIGNATURE_PAGE_LIMIT=256
MAX_SIGNATURE_CENSUS_PAGES=4
SIGNATURE_CENSUS_MAX_ROWS=SIGNATURE_PAGE_LIMIT*MAX_SIGNATURE_CENSUS_PAGES
FRESH_SWAP_TRIGGER_POLL_SECONDS=2
FRESH_SWAP_TRIGGER_MAX_SECONDS=120
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
    "MM_SOLANA_EVIDENCE_BROKER_DB",DEFAULT_BROKER_DB))

class _MeteoraPacer:
    def __init__(self):
        self.next=0.0
        self.lock=threading.Lock()
    def pace(self):
        with self.lock:
            now=time.monotonic()
            wait=max(0.0,self.next-now)
            if wait:
                _stop_sleep(wait)
                now=time.monotonic()
            self.next=max(now,self.next)+METEORA_MIN_INTERVAL_SECONDS

METEORA_PACER=_MeteoraPacer()



PROGRESS_HOOK=None

def _stage(pool,stage,reason=None,**details):
    if PROGRESS_HOOK is not None:PROGRESS_HOOK(pool,stage,reason,**details)

def _record_progress(pipeline,active_triggers,pool,stage,reason=None,
                     classification=None,**details):
    """Keep candidate and trigger identities separate in the append-only funnel."""
    from meme_machine.lanes.meteora.pipeline import censor_class
    if stage=="trigger_authenticated":
        trigger_id=str(pool)+":"+str(details.get("slot"))
        previous=active_triggers.get(pool)
        if previous and previous!=trigger_id:
            pipeline.record(previous,"trigger_terminal","superseded_before_fresh_state",
                pool=pool)
            pipeline.record(pool,"evidence_superseded","superseded_before_fresh_state",
                "superseded_candidate_state",observation_id=previous)
        active_triggers[pool]=trigger_id
        pipeline.record(trigger_id,"trigger_started",pool=pool,slot=details.get("slot"))
        pipeline.record(pool,"evidence_required",observation_id=trigger_id,
            scope="fresh_state_and_verified_warmup_before_full_vector")
    if pool in active_triggers:
        details.setdefault("observation_id",active_triggers[pool])
    if stage=="warmup_started":
        pipeline.record(pool,"evidence_requested",scope="verified_warmup_reconstruction",
            observation_id=details.get("observation_id"))
    if stage in ("terminal","settled") and pool in active_triggers:
        pipeline.record(active_triggers.pop(pool),"trigger_terminal",reason or "settled",pool=pool)
    if classification is None and reason:
        if reason=="paper_capital_occupied":
            classification="capital_occupied"
        elif reason=="durable_position_continuation_active":
            classification="open_continuing"
        elif reason=="qualification_rejection":
            classification="strategy_rejection"
        elif reason=="campaign_window_insufficient_preentry_time":
            classification="pending_at_observation_close"
        elif reason=="stream_gap_unresolved_at_trigger_timeout":
            classification="stream_gap"
        elif (stage=="terminal" and details.get("stage_failed")=="compatibility"
                and (reason=="dlmm_missing_active_or_liquidity"
                    or any(x in str(reason) for x in ("unsupported","authority","extension")))):
            classification="structural_ineligible"
        else:classification=censor_class(reason)
    pipeline.record(pool,stage,reason,classification,**details)


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
    """Build public ranking context from the pool-list response only.

    These fields never authorize entry. The prior per-pool 35-minute history read
    duplicated public context for every candidate even though acceleration is not
    a profitability-v1 gate.
    """
    volume=row.get("volume") or {};fees=row.get("fees") or {}
    missing=[name for name,values in (("volume",volume),("fees",fees))
             if "5m" not in values or values["5m"] is None]
    tvl=_num(row.get("tvl"));v5=_num(volume.get("5m"));v30=_num(volume.get("30m"))
    f5=_num(fees.get("5m"));f30=_num(fees.get("30m"))
    vacc=_accel(v5,v30,6);facc=_accel(f5,f30,6)
    density=0.0 if tvl<=0 else f5/tvl
    return dict(
        address=row.get("address"),name=row.get("name"),
        token_x=(row.get("token_x") or {}).get("address"),
        token_y=(row.get("token_y") or {}).get("address"),
        tvl_usd=tvl,volume_30m_snapshot_usd=v30,fee_30m_snapshot_usd=f30,
        dynamic_fee_pct=_num(row.get("dynamic_fee_pct")),
        volume_5m_usd=v5,volume_30m_usd=v30,fee_5m_usd=f5,fee_30m_usd=f30,
        fee_tvl_ratio_5m=density,volume_acceleration=vacc,fee_acceleration=facc,
        event_score=(math.log1p(v5)*max(vacc,0.01)*max(facc,0.01)*max(density,1e-12)),
        public_context_source="pool_list_snapshot",
        missing_5m_context=missing,
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
        public_context_source="completed_5m_history_buckets",
        missing_5m_context=[],
    )
    return out


def _iter_acceleration_candidates(policy,telemetry,deadline=None,checkpoint=None,seen=None):
    """Yield SOL-paired candidates from cheap public ranking snapshots.

    The order is deterministic: configured sort order, then page, then API row rank.
    A history read supplies the existing five-minute context only when the list
    API omits it. Missing data is never a zero-fee economic rejection. Authenticated
    local fee density, depth, flow and after-cost economics remain entry authority.
    """
    telemetry.setdefault("rejections",[])
    telemetry.setdefault("errors",[])
    telemetry.setdefault("qualified",[])
    telemetry.setdefault("seen",0)
    telemetry.setdefault("history_reads",0)
    telemetry.setdefault("snapshot_context_candidates",0)
    seen=set() if seen is None else seen
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
                _stage(address,"discovered")
                raw=_candidate(row)
                raw["sources"]=[dict(
                    sort=sort_by,rank=(page-1)*DISCOVERY_PAGE_SIZE+raw_rank)]
                observed_at=int(time.time())
                item=raw
                telemetry["snapshot_context_candidates"]+=1
                if item.get("missing_5m_context") and item["tvl_usd"]>0:
                    telemetry["history_reads"]+=1
                    try:
                        item=_history_acceleration(item,observed_at)
                    except Exception as exc:
                        reason=str(exc)
                        if not reason.startswith("solana_dlmm_volume_history_"):
                            reason=type(exc).__name__
                        telemetry["errors"].append(dict(pool=address,
                            reason=reason,failure_domain="incomplete_evidence",
                            missing_fields=item["missing_5m_context"],
                            qualification_inferred=False))
                        _stage(address,"rejected","public_fee_context_incomplete",
                               classification="reconstruction_incomplete")
                        if checkpoint is not None:checkpoint("discovery_incomplete_evidence")
                        continue
                failed=[]
                # Public Meteora API data only orders discovery. Entry authority
                # is reserved for authenticated finalized on-chain range fees.
                if item["fee_5m_usd"]<=0:
                    failed.append("public_fee_context_zero")
                if item["tvl_usd"]<=0:
                    failed.append("public_liquidity_context_zero")
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


def _campaign_candidates(policy,telemetry,deadline,checkpoint,source=None):
    """Retain every cheap candidate; schedule only bounded expensive warming.

    The public discovery producer owns an unlimited-by-count on-disk spool.  After
    cheap public-context screening, candidates enter the shared EDF queue.  A busy
    worker never converts a candidate into a rejection: the work remains durable
    and the earliest decision deadline is always claimed first.
    """
    from meme_machine.lanes.meteora.dlmm_discovery import CampaignDiscovery
    from meme_machine.runtime.candidate_history import CandidateDeadlineMissed
    source=source or CampaignDiscovery(OUT.with_suffix('.discovery.sqlite'),
        api=_api,candidate=_candidate,eligible=_sol_pair,sorts=DISCOVERY_SORTS,
        pages=DISCOVERY_PAGES_PER_SORT,page_size=DISCOVERY_PAGE_SIZE,deadline=deadline)
    for key in ('rejections','errors','qualified'):telemetry.setdefault(key,[])
    for key in ('seen','history_reads','snapshot_context_candidates'):telemetry.setdefault(key,0)
    source.start();source_done=False
    worker='meteora-warmup:'+str(os.getpid())
    history=CANDIDATE_HISTORY
    try:
        while not _runtime_expired(deadline):
            if history is not None:
                try:claimed=history.claim(worker,lane='meteora')
                except CandidateDeadlineMissed as exc:
                    raise Unavailable('candidate_decision_deadline_missed') from exc
                if claimed is not None:
                    item=dict(claimed['payload']['candidate'])
                    item['_candidate_work_id']=claimed['id']
                    yield item
                    continue
                if source_done:
                    if history.pending(lane='meteora')<=0:break
                    _stop_sleep(min(.05,_runtime_remaining(deadline)))
                    continue
            if source_done:break
            item=source.next_candidate()
            stats=source.snapshot();telemetry['seen']=stats['first_seen']
            telemetry['census_cycles']=stats['census_cycles']
            telemetry['source_acquisition']=stats
            if item is None:
                source_done=True
                continue
            address=item['address'];observed_at=item['signal_observed_at']
            if source.on_discovered is None:_stage(address,'discovered')
            telemetry['snapshot_context_candidates']+=1
            if item.get('missing_5m_context') and item['tvl_usd']>0:
                telemetry['history_reads']+=1
                try:item=_history_acceleration(item,observed_at)
                except Exception as exc:
                    reason=str(exc)
                    if not reason.startswith('solana_dlmm_volume_history_'):reason=type(exc).__name__
                    telemetry['errors'].append(dict(pool=address,reason=reason,
                        failure_domain='incomplete_evidence',qualification_inferred=False))
                    _stage(address,'rejected','public_fee_context_incomplete')
                    checkpoint('discovery_incomplete_evidence');continue
            failed=[]
            if item['fee_5m_usd']<=0:failed.append('public_fee_context_zero')
            if item['tvl_usd']<=0:failed.append('public_liquidity_context_zero')
            if failed:
                telemetry['rejections'].append(dict(pool=address,failed=failed,candidate=item))
                checkpoint('discovery_rejection');continue
            telemetry['qualified'].append(item)
            checkpoint('discovery_signal')
            if history is None:
                yield item
                continue
            decision_deadline=int(getattr(source,'deadline_wall',
                time.time()+_runtime_remaining(deadline)))
            history.observe('meteora',address,surface='meteora-dlmm',
                observed_at=int(observed_at),decision_deadline=decision_deadline,
                metadata=dict(source='meteora_public_ranking',
                    discovery_sort=item.get('discovery_sort'),
                    discovery_page=item.get('discovery_page'),
                    discovery_raw_rank=item.get('discovery_raw_rank')))
            history.enqueue('meteora',address,kind='warmup',
                ready_at=time.time(),deadline=decision_deadline,
                estimate_seconds=FRESH_SWAP_TRIGGER_MAX_SECONDS+
                    int(policy['range']['warmup_seconds'])+15,
                priority=30,payload=dict(candidate=item),
                identity='meteora:warmup:'+address+':'+str(int(observed_at)))
            checkpoint('candidate_retained')
    finally:
        try:source.close()
        finally:
            if hasattr(source,'final_snapshot'):
                stats=source.final_snapshot;telemetry['source_acquisition']=stats
                telemetry['seen']=stats['first_seen'];telemetry['census_cycles']=stats['census_cycles']



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
                _stop_sleep(NETWORK_IDENTITY_RETRY_SECONDS*index)
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
    report.update(progress)
    report["checkpoint"]=dict(
        stage=stage,written_at=int(time.time()),**progress)
    report["rpc"]=_sum_rpc_metrics(rpcs)
    report["alchemy_pacer"]=pacer.telemetry()
    from meme_machine.lanes.meteora.durable_publication import publish_report
    report['publication']=publish_report(OUT,report,asynchronous=bool(os.environ.get('MM_SOLANA_EVIDENCE_PLANE_DB')))


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



def _complete_signature_census(rpc,pool,start_slot,end_slot,broker=None,*,gap_repair=False):
    """Prove finalized signature coverage with an incremental per-pool ledger.

    The first interval performs the bounded boundary proof. Later intervals fetch
    only signatures newer than the durable head, while the cached lower-bound
    witness preserves exact interval completeness. This never weakens the unchanged
    MAX_TRANSACTIONS bound.
    """
    if gap_repair is not True:raise Unavailable('legacy_census_requires_explicit_gap_repair')
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
        old_oldest=coverage.get("oldest_slot")
        cached=broker.signature_rows(scope,pool)
        # Only a previously completed census can supply an incremental cursor.
        reuse=bool(coverage.get("covered_through_slot") and old_oldest is not None
                   and int(old_oldest)<=int(start_slot))
        old_head=coverage.get("newest_signature") if reuse else None
        pending=[];seen=set();before=None
        if not reuse or int(coverage["covered_through_slot"])<int(end_slot):
            for _ in range(MAX_SIGNATURE_CENSUS_PAGES):
                page=fetch_page(before=before,until=old_head)
                for row in page:
                    if row["signature"] in seen:
                        raise Unavailable("solana_dlmm_signature_census_duplicate")
                    seen.add(row["signature"]);pending.append(row)
                relevant=[row for row in pending
                          if start_slot<row["slot"]<=end_slot and not row.get("err")]
                if len(relevant)>MAX_TRANSACTIONS:
                    raise Unavailable("solana_dlmm_transaction_pressure_overflow")
                # Cold start needs only the exact lower witness, not the pool's
                # entire history. A warm query must finish its bridge to old_head.
                if (not old_head and any(row["slot"]<=start_slot for row in page)):
                    break
                if len(page)<SIGNATURE_PAGE_LIMIT:
                    break
                before=page[-1]["signature"]
            else:
                raise Unavailable("solana_dlmm_signature_census_head_incomplete")
        # Stage new rows until coverage, boundary, cardinality and transaction
        # ordering fields have all been checked. Failure must not poison the next
        # request's durable head or claim a missing chain range was authenticated.
        merged={row["signature"]:row for row in (cached if reuse else [])}
        merged.update({row["signature"]:row for row in pending})
        collected=[row for row in merged.values() if row["slot"]<=end_slot]
        boundary_rows=[row for row in collected if row["slot"]<=start_slot]
        boundary=max(boundary_rows,key=lambda row:(row["slot"],row["signature"])) if boundary_rows else None

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
    if broker is not None:
        broker.remember_signatures(scope,pool,pending,covered_through_slot=int(end_slot))
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
    _stage(start["pool"],"forward_observation",duration_seconds=wait_seconds)
    _stop_sleep(wait_seconds)
    _stage(start["pool"],"reconstruction_started")
    end_snapshot=adapter.snapshot_from_state(
        start,int(time.time()),True,fresh=True)
    plane=_evidence_plane()
    signatures,transactions,census=plane.meteora_interval(start['pool'],start['slot'],end_snapshot['slot'])
    plane.count('meteora.local_warmup_intervals')
    if len(encode(transactions))>2_000_000:
        raise Unavailable("solana_dlmm_interval_evidence_bound")
    tape=reconstruct(
        start,end_snapshot,signatures,transactions,int(time.time()),cursor)
    _stage(start["pool"],"reconstruction_complete",lineage=tape.lineage)
    actions=ordered_tape_actions(tape)
    if CANDIDATE_HISTORY is not None:
        # Persist only the normalized economics required by later promotion.
        # Raw transaction bodies remain evidence-plane material, not candidate history.
        for kind,item,_order in actions:
            order=list(item.get('cursor') or [item.get('slot',0),0,0])
            if len(order)!=3:raise Unavailable('candidate_history_meteora_order')
            identity=str(item.get('signature') or digest(
                [start['pool'],kind,order,item]))
            CANDIDATE_HISTORY.append_event(
                'meteora',start['pool'],identity=identity+':'+str(order[2]),
                slot=int(order[0]),transaction_index=int(order[1]),
                event_index=int(order[2]),
                market_time=int(item.get('time') or tape.terminal['time']),
                kind='meteora_'+str(kind),payload=dict(item))
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
    density=(0.0 if range_liquidity<=0 else total_fee/range_liquidity)
    volume_density=(0.0 if range_liquidity<=0 else total_volume/range_liquidity)
    return dict(
        touch_swaps=touches,range_liquidity_sol_lamports=range_liquidity,
        range_volume_sol_lamports=total_volume,
        range_fee_sol_lamports=total_fee,
        volume_rate_sol_lamports_per_second=total_volume/seconds,
        fee_rate_sol_lamports_per_second=total_fee/seconds,
        volume_to_active_liquidity=volume_density,
        fee_density=density,
        authenticated_fee_density_24h_pct=(
            100.0*density*86400.0/float(seconds)),
        authenticated_volume_to_liquidity_24h=(
            volume_density*86400.0/float(seconds)),
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
    q=policy["qualification"]
    checks=dict(
        authenticated_fee_density=(
            features["authenticated_fee_density_24h_pct"]
            >=float(q["min_authenticated_fee_density_24h_pct"])
        ),
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
        rule="solana_dlmm_authenticated_fee_density_v1",
        fitted_thresholds=False,
        public_api_entry_authority=False,
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
        entry_conversion_quote=quote,
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
    liquidation=0;quote=None
    if tokens:
        _,quote=dlmm.swap(
            deepcopy(state),tokens,sol_side=="y",int(state["time"]))
        liquidation=int(quote["output"]);sol+=liquidation
    # Allocate the one executable unwind proportionally. A separate dust-size
    # hypothetical swap must never censor an otherwise executable real unwind.
    inventory_liquidation=liquidation*assets[token_side]//tokens if tokens else 0
    inventory_sol=assets[sol_side]+inventory_liquidation
    fee_value=sol-inventory_sol
    inventory_spot=assets[sol_side]+_to_sol(state,assets[token_side],state[token_side],state['active'])
    fee_spot=assets['fee_'+sol_side]+_to_sol(state,assets['fee_'+token_side],state[token_side],state['active'])
    unwind_cost=inventory_spot+fee_spot-sol
    pnl=sol-CAPITAL-ROUND_TRIP_NETWORK_COST
    return dict(
        resolved=True,ending_sol_lamports=sol,pnl_lamports=pnl,
        withdrawn_assets_raw=assets,unwind_quote=quote,
        fee_pnl_lamports=fee_value,inventory_pnl_lamports=inventory_sol-CAPITAL,
        fee_income_mark_lamports=fee_spot,inventory_mark_pnl_lamports=inventory_spot-CAPITAL,
        unwind_cost_lamports=unwind_cost,
        network_cost_lamports=ROUND_TRIP_NETWORK_COST,
        fee_valuation_method='pro_rata_combined_executable_unwind_output',
        execution_cost_accounting='swap_and_protocol_fees_embedded_in_executable_quotes_network_cost_separate',
        unwind_input_token=state[token_side],
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
        and recent["two_way_balance"]<0.18
        and recent["drift_ratio"]>0.82
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
    reasons=[]
    if boundary:reasons.append("range_boundary")
    if inventory:reasons.append("inventory_imbalance")
    if directional:reasons.append("one_way_flow")
    if volume_collapse:reasons.append("volume_collapse")
    if fee_collapse:reasons.append("fee_density_collapse")
    return reasons,recent,mark,fee_uplift


def _eligible_exit_reasons(reasons, *, elapsed_seconds, collapse_streaks, policy):
    """Separate immediate capital-risk exits from ordinary economic deterioration."""
    hard_risk=("range_boundary","inventory_imbalance","one_way_flow")
    eligible=[reason for reason in reasons if reason in hard_risk]
    core_hold=int(policy["prospective_test"]["minimum_hold_seconds_for_nonrisk_exit"])
    confirmations=int(policy["exit"].get("economic_collapse_confirmation_segments",2))
    if int(elapsed_seconds) >= core_hold:
        for reason in ("volume_collapse","fee_density_collapse"):
            if (
                reason in reasons
                and int(collapse_streaks.get(reason,0)) >= confirmations
                and reason not in eligible
            ):
                eligible.append(reason)
    return eligible


def _lifecycle(adapter,address,entry,features,policy,pacer,rpcs,deadline=None,broker=None,book=None,decision_id=None):
    identity=book.identity() if book is not None else None
    if EVIDENCE_PLANE is not None:
        EVIDENCE_PLANE.interest(METEORA_SCOPE,lower_slot=entry['slot'],addresses=[address],
            owner='meteora:position:'+str(identity),lifecycle='open',priority=0)
    if book is not None:
        book.append(identity,'reserve',dict(amount=CAPITAL+ROUND_TRIP_NETWORK_COST,
            pool=address,policy_hash=digest(policy),strategy_evidence_hash=digest(dict(entry=entry,features=features))))
        if CANDIDATE_HISTORY is not None and decision_id is not None:
            CANDIDATE_HISTORY.record_funding(decision_id,'meteora',address,
                status='funded',at=int(time.time()),details=dict(
                    lifecycle_id=identity,amount=CAPITAL+ROUND_TRIP_NETWORK_COST))
    _stage(address,'entry_reserved',lifecycle_id=identity)
    try:
        return _position_lifecycle(adapter,address,entry,features,policy,pacer,rpcs,deadline,broker,book,identity)
    except BaseException as exc:
        if book is not None:
            book.fail(identity,type(exc).__name__+':'+str(exc)[:200])
            _release_position_evidence(book,identity)
        raise


POSITION_EVIDENCE_RECOVERY_MAX=3
POSITION_EVIDENCE_RECOVERABLE=frozenset((
    "provider_request_failed",
    "solana_dlmm_rate_limit_recovery_exhausted",
    "solana_dlmm_signature_census_missing_start_boundary",
    "solana_dlmm_transaction_hydration_incomplete",
    "solana_dlmm_transaction_index_unavailable",
))


def _recover_position_observation(
    adapter,address,current,duration,pacer,rpcs,deadline,broker
):
    recoveries=[]
    while True:
        phase,tape,terminal,effective_start,adapter=_observe_window(
            adapter,address,current,duration,False,pacer,rpcs,deadline,
            broker,"position_monitor")
        if phase["verified"]:
            return phase,tape,terminal,effective_start,adapter,recoveries
        reason=str(phase.get("reason") or "")
        if (
            reason not in POSITION_EVIDENCE_RECOVERABLE
            or len(recoveries)>=POSITION_EVIDENCE_RECOVERY_MAX
            or _runtime_expired(deadline)
        ):
            return phase,tape,terminal,effective_start,adapter,recoveries
        recoveries.append(dict(attempt=len(recoveries)+1,reason=reason))
        _stage(address,"forward_observation",recovery=True,
            recovery_attempt=len(recoveries),reason=reason)
        adapter=_rotate(adapter,pacer,rpcs)


def _checkpoint_position_evidence(book,identity,current):
    """The native committed tape already holds this consumed prefix for replay."""
    if book is None or EVIDENCE_PLANE is None:return
    owner='meteora:position:'+str(identity);slot=current['slot']
    EVIDENCE_PLANE.interest(METEORA_SCOPE,lower_slot=slot,addresses=[current['pool']],
        owner=owner,lifecycle='open',priority=0)
    EVIDENCE_PLANE.advance_interest(METEORA_SCOPE,lower_slot=slot,consumed_slot=slot,
        checkpoint_hash=digest(dict(identity=identity,genesis=book.genesis,current=current)),owner=owner)


def _release_position_evidence(book,identity):
    """An evidence pin resolves only after this native lifecycle is terminal."""
    if book is None or EVIDENCE_PLANE is None:return
    from contextlib import closing
    with closing(book.connect()) as db:
        db.execute('BEGIN');row=book._replay(db)['positions'].get(identity)
    if row and row['status'] in ('cancelled','settled','written_off'):
        EVIDENCE_PLANE.command(op='release',owner='meteora:position:'+str(identity),scope=METEORA_SCOPE,resolved=True)


def _recover_position_evidence(book):
    """Repair a crash between native terminal commit and pin release."""
    if EVIDENCE_PLANE is None or EVIDENCE_PLANE.reader is None:return
    from contextlib import closing
    with closing(book.connect()) as db:
        db.execute('BEGIN');positions=book._replay(db)['positions']
    prefix='meteora:position:'+book.genesis['namespace']+':'+book.run_id+':'
    owners=EVIDENCE_PLANE.reader.db.execute('SELECT owner FROM interests WHERE scope=? AND active=1',
                                           (METEORA_SCOPE,)).fetchall()
    for (owner,) in owners:
        if not owner.startswith(prefix):continue
        row=positions.get(owner[len('meteora:position:'):])
        # Missing native intent proves the crash preceded reservation/fill.
        if row is None or row['status'] in ('cancelled','settled','written_off'):
            EVIDENCE_PLANE.command(op='release',owner=owner,scope=METEORA_SCOPE,resolved=True)


def _position_lifecycle(
    adapter,address,entry,features,policy,pacer,rpcs,deadline=None,broker=None,book=None,identity=None,*,recovered=None
):
    position=recovered['position'] if recovered else _build_position(entry,features,policy)
    if book is not None and recovered is None:
        book.append(identity,'entry',dict(capital=CAPITAL,entry_cost=ENTRY_NETWORK_COST,
            exit_cost=EXIT_NETWORK_COST,entry_state=entry,position=position,features=features,
            policy=policy,mark=_mark(position)))
    _stage(address,'deployed',lifecycle_id=identity)
    _stage(address,'entry_filled',lifecycle_id=identity)
    current=recovered['current'] if recovered else entry
    if recovered:_checkpoint_position_evidence(book,identity,current)
    elapsed=recovered['elapsed'] if recovered else 0
    segments=[];tapes=list(recovered['tapes']) if recovered else []
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
    collapse_streaks={"volume_collapse":0,"fee_density_collapse":0}
    if recovered:
        collapse_streaks=dict(recovered['collapse_streaks'])
        exit_reason=recovered['restored_exit'] or exit_reason
    while elapsed<max_hold and not (recovered and recovered['restored_exit']):
        adapter=_rotate(adapter,pacer,rpcs)
        duration=min(segment_seconds,max_hold-elapsed)
        phase,tape,terminal,effective_start,adapter,recoveries=(
            _recover_position_observation(
                adapter,address,current,duration,pacer,rpcs,deadline,broker))
        if not phase["verified"]:
            reason=str(phase.get("reason") or "")
            terminal_writeoff=(reason in ("dlmm_multiple_liquidity_removals_in_interval","dlmm_add_liquidity_by_strategy2_mixed_with_swap_interval") or reason.startswith("dlmm_rebalance_liquidity_requires_position_state:"))
            if book is not None:(book.append(identity,'writeoff',dict(reason=reason,recovery_attempts=recoveries)) if terminal_writeoff else book.fail(identity,reason))
            _release_position_evidence(book,identity)
            return dict(lifecycle_id=identity,
                complete=False,reason=phase["reason"],segments=segments,
                verified_hold_seconds=elapsed,recovery_attempts=recoveries,terminal_writeoff=terminal_writeoff,
                **(dict(writeoff_proceeds_lamports=0) if terminal_writeoff else dict(unresolved_position=True)),
            ),adapter
        position=_advance_position(position,tape)
        raw_reasons,recent,mark,uplift=_segment_exit(
            position,effective_start,tape,terminal,entry_flow,policy)
        observed_seconds=max(
            duration,
            max(0,int(terminal.get("time",0))-int(current.get("time",0))))
        elapsed+=observed_seconds;tapes.append(tape)
        for reason in collapse_streaks:
            collapse_streaks[reason]=(
                collapse_streaks[reason]+1 if reason in raw_reasons else 0
            )
        eligible_reasons=_eligible_exit_reasons(
            raw_reasons,elapsed_seconds=elapsed,
            collapse_streaks=collapse_streaks,policy=policy,
        )
        if book is not None:
            book.append(identity,'mark',dict(
                tape=asdict(tape),position_hash=digest(position),mark=mark,
                strategy_progress=dict(observed_seconds=observed_seconds,
                    elapsed_seconds=elapsed,collapse_streaks=dict(collapse_streaks),
                    raw_exit_reasons=raw_reasons,eligible_exit_reasons=eligible_reasons,
                    effective_start_hash=digest(effective_start),
                    effective_start=(effective_start if effective_start!=current else None))))
            _checkpoint_position_evidence(book,identity,terminal)
        segments.append(dict(
            elapsed_seconds=elapsed,lineage=tape.lineage,
            swaps=len(tape.events),recent=recent,mark=mark,
            dynamic_fee_uplift=uplift,
            raw_exit_reasons=raw_reasons,
            collapse_streaks=dict(collapse_streaks),
            exit_reasons=eligible_reasons,
            evidence_recovery_attempts=recoveries,
        ))
        current=terminal
        if eligible_reasons:
            exit_reason=eligible_reasons[0];break
    _stage(address,"unwind",lifecycle_id=identity)
    combined=chain_verified_tapes(entry,tapes)
    final=_mark(position)
    if book is not None:
        book.append(identity,'settle',dict(
            mark=final,exit_reason=exit_reason,lineage=combined.lineage))
    if EVIDENCE_PLANE is not None:
        _release_position_evidence(book,identity)
        EVIDENCE_PLANE.count('meteora.positions_settled')
    hours=max(elapsed/3600.0,1/3600.0)
    final["pnl_bps_per_capital_hour"]=final["pnl_bps"]/hours
    return dict(
        complete=True,lifecycle_id=identity,exit_reason=exit_reason,
        realized_hold_seconds=elapsed,segments=segments,
        lineage=combined.lineage,final=final,
    ),adapter




def _regime_pass(candidate,policy):
    # Public history remains a bounded freshness/activity context only.
    # It cannot authorize the trade or impose the profitability threshold.
    return (
        float(candidate.get("fee_5m_usd") or 0.0)>0.0
        and float(candidate.get("tvl_usd") or 0.0)>0.0
    )


def _new_finalized_swaps(rpc,pool,after_slot,broker=None):
    plane=_evidence_plane();scope=plane.meteora_scope(pool);frontier=plane.frontier(scope)
    if frontier<=after_slot:return [],dict(rate_limited=False,stage=None,head_slot=after_slot,head_signature=None,fresh_signature_count=0)
    rows=plane.reader.window(scope,after_slot+1,frontier,as_of=plane.clock(),
        address=pool,kind='transaction',limit=FRESH_SWAP_TRIGGER_SIGNATURE_LIMIT)
    out=[]
    for row in rows:
        tx=row['payload']
        if (tx.get('meta') or {}).get('err'):continue
        swaps=transaction_swaps(tx,pool,trigger_only=True)
        if swaps:out.append(dict(signature=row['signature'],slot=row['slot'],block_time=tx.get('blockTime'),swap_count=len(swaps),swaps=swaps))
    plane.count('meteora.local_triggers')
    return out,dict(rate_limited=False,stage=None,head_slot=frontier,
        head_signature=rows[-1]['signature'] if rows else None,fresh_signature_count=len(rows),
        hydration=None,historical_provider_calls=0,source='local_finalized_evidence_plane')


def _await_fresh_swap_trigger_polling(
    adapter,candidate,baseline_state,policy,pacer,rpcs,deadline=None
):
    started=time.monotonic()
    baseline_slot=int(baseline_state["slot"])
    cursor_slot=baseline_slot
    polls=0
    refreshes=0
    current_candidate=dict(candidate)
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
            _stop_sleep(min(
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
                _stop_sleep(FRESH_SWAP_TRIGGER_POLL_SECONDS)
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
        _stop_sleep(min(FRESH_SWAP_TRIGGER_POLL_SECONDS,remaining))


def _await_fresh_swap_trigger(
    adapter,candidate,baseline_state,policy,pacer,rpcs,deadline=None,broker=None
):
    """Wait on finalized pool wakeups and authenticate only when needed.

    One bounded authentication read closes the handoff interval between the
    finalized compatibility snapshot and the moment this candidate begins
    consuming the shared wake stream. After that, HTTP authentication is
    wake-driven. Each observed stream gap schedules exactly one additional
    bounded recovery read from the last authenticated per-pool cursor.
    """
    if broker is None:
        return _await_fresh_swap_trigger_polling(
            adapter,candidate,baseline_state,policy,pacer,rpcs,deadline)

    started=time.monotonic()
    baseline_slot=int(baseline_state["slot"])
    cursor_name="dlmm_fresh:"+str(candidate["address"])
    durable_cursor=broker.cursor(cursor_name)
    cursor_slot=max(baseline_slot,int(durable_cursor.get("slot") or 0))
    polls=0;wakeups=0;gap_recoveries=0;bootstrap_auth_reads=0;refreshes=0
    current_candidate=dict(candidate)
    initial_status=broker.stream_status(
        DLMM_WAKE_STREAM_KEY,int(time.time()),0)
    last_gap_count=int(initial_status.get("gaps") or 0)
    # A read while disconnected cannot close an outage that is still growing.
    # Retain the recovery obligation until a post-reconnect read completes.
    gap_recovery_pending=not bool(initial_status.get("covered",False))
    bootstrap_recovery_pending=True
    pending_trigger=None
    pending_trigger_source=None

    def terminal(reason,elapsed,**extra):
        if reason=="fresh_swap_trigger_timeout":
            if pending_trigger is not None:
                reason="fresh_state_unavailable_after_authenticated_trigger"
            elif gap_recovery_pending:
                reason="stream_gap_unresolved_at_trigger_timeout"
        row=dict(
            triggered=False,reason=reason,waited_seconds=elapsed,
            polls=polls,wakeups=wakeups,gap_recoveries=gap_recoveries,
            bootstrap_auth_reads=bootstrap_auth_reads,
            gap_recovery_pending=gap_recovery_pending,
            gap_recovery_scope="bounded_candidate_trigger_authentication_not_stream_backfill",
            authenticated_trigger_pending_fresh_state=pending_trigger is not None,
            acceleration_refreshes=refreshes,baseline_slot=baseline_slot,
        )
        row.update(extra)
        return row,None,adapter,current_candidate

    while True:
        elapsed=max(0.0,time.monotonic()-started)
        if _runtime_expired(deadline):
            return terminal("experiment_runtime_deadline",elapsed)
        if elapsed>=FRESH_SWAP_TRIGGER_MAX_SECONDS:
            return terminal("fresh_swap_trigger_timeout",elapsed)


        now=int(time.time())
        status=broker.stream_status(DLMM_WAKE_STREAM_KEY,now,0)
        gap_count=int(status.get("gaps") or 0)
        events=broker.recent_events(
            DLMM_WAKE_STREAM_KEY,after_slot=cursor_slot,
            address=candidate["address"])
        should_auth=bool(events) or bootstrap_recovery_pending

        # A gap can hide wakeups after the first disconnect notification. Only
        # acknowledge its bounded recovery read after reconnection and hydration.
        if gap_count>last_gap_count:
            gap_recovery_pending=True
            last_gap_count=gap_count
        recovering_gap=gap_recovery_pending and bool(status.get("covered",False))
        should_auth=should_auth or recovering_gap

        if should_auth and pending_trigger is None:
            wakeups+=len(events)
            was_bootstrap=bootstrap_recovery_pending
            adapter=_rotate(adapter,pacer,rpcs)
            swaps,poll_meta=_new_finalized_swaps(
                adapter.rpc,candidate["address"],cursor_slot,broker)
            polls+=1
            if (poll_meta.get("rate_limited")
                    or (poll_meta.get("hydration") or {}).get("pending")):
                remaining=min(
                    FRESH_SWAP_TRIGGER_MAX_SECONDS-max(
                        0.0,time.monotonic()-started),
                    _runtime_remaining(deadline))
                if remaining>0:
                    _stop_sleep(min(0.5,remaining))
                continue

            if recovering_gap:
                gap_recoveries+=1
                gap_recovery_pending=False
            if was_bootstrap:
                bootstrap_auth_reads+=1
                bootstrap_recovery_pending=False

            new_cursor=max(
                cursor_slot,int(poll_meta.get("head_slot") or cursor_slot))
            if new_cursor>cursor_slot:
                cursor_slot=new_cursor
                broker.advance_cursor(
                    cursor_name,cursor_slot,poll_meta.get("head_signature"))

            if swaps:
                pending_trigger=dict(swaps[0])
                pending_trigger_source=("handoff_gap_auth" if was_bootstrap
                    else "stream_gap_auth" if recovering_gap
                    else "finalized_program_account_stream")
                trigger_slot=int(pending_trigger["slot"])
                _stage(candidate["address"],"trigger_observed",slot=trigger_slot)
                _stage(candidate["address"],"trigger_authenticated",slot=trigger_slot)

        if pending_trigger is not None:
            # The finalized account endpoint may lag the authenticated swap.
            # Keep that same trigger while obtaining its required fresh prestate;
            # advancing the signature cursor must not silently discard it.
            trigger_slot=int(pending_trigger["slot"])
            adapter=_rotate(adapter,pacer,rpcs)
            (post,adapter)=_retry_rate_limited_operation(
                lambda active:_fresh_supported_start(active,current_candidate),
                adapter,pacer,rpcs,deadline)
            elapsed=max(0.0,time.monotonic()-started)
            if _runtime_expired(deadline):
                return terminal("experiment_runtime_deadline",elapsed)
            if elapsed>=FRESH_SWAP_TRIGGER_MAX_SECONDS:
                return terminal("fresh_swap_trigger_timeout",elapsed)
            if int(post["slot"])<trigger_slot:
                remaining=min(
                    FRESH_SWAP_TRIGGER_MAX_SECONDS-max(
                        0.0,time.monotonic()-started),
                    _runtime_remaining(deadline))
                if remaining>0:_stop_sleep(min(0.5,remaining))
                continue
            pending_trigger.update(
                triggered=True,reason="authenticated_fresh_swap",
                wake_source=pending_trigger_source,
                waited_seconds=max(0.0,time.monotonic()-started),
                polls=polls,wakeups=wakeups,gap_recoveries=gap_recoveries,
                bootstrap_auth_reads=bootstrap_auth_reads,
                gap_recovery_pending=gap_recovery_pending,
                gap_recovery_scope="bounded_candidate_trigger_authentication_not_stream_backfill",
                acceleration_refreshes=refreshes,baseline_slot=baseline_slot,
                post_trigger_slot=int(post["slot"]),
            )
            return pending_trigger,post,adapter,current_candidate

        remaining=min(
            FRESH_SWAP_TRIGGER_MAX_SECONDS-max(
                0.0,time.monotonic()-started),
            _runtime_remaining(deadline))
        if remaining<=0:
            continue
        _stop_sleep(min(0.25,remaining))

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
    _stage(candidate["address"],"fresh_state",slot=post_trigger["slot"])
    _stage(candidate["address"],"warmup_started")
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
    if phase.get("verified"):
        _stage(candidate["address"],"warmup_complete")
        if not result["aligned"]:
            _stage(candidate["address"],"evidence_not_required",
                "verified_zero_warmup_after_fresh_swap",scope="full_economic_vector",
                authoritative_warmup_complete=True)
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
        acceleration_pass=_regime_pass(current_candidate,policy)
        attempt=dict(
            window=index+1,observed_at=observed_at,
            volume_acceleration=current_candidate["volume_acceleration"],
            fee_acceleration=current_candidate["fee_acceleration"],
            acceleration_pass=acceleration_pass,public_context_refreshed=False,
        )
        if not acceleration_pass:
            attempts.append(attempt)
            return dict(
                aligned=False,reason="public_fee_context_expired",
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


def run_live(target=None,max_attempted=None,max_runtime_seconds=None,*,campaign=False):
    global PROGRESS_HOOK,CANDIDATE_HISTORY
    from meme_machine.lanes.meteora.pipeline import Pipeline,censor_class
    assert_independence()
    policy=load_policy()
    from meme_machine.runtime.candidate_history import open_candidate_history
    CANDIDATE_HISTORY=open_candidate_history()
    target=int(target or policy["prospective_test"]["target_complete_lifecycles"])
    max_attempted=int(max_attempted or policy["prospective_test"]["max_attempted_pools"])
    if not 1<=target<=int(policy["prospective_test"]["target_complete_lifecycles"]):
        raise ValueError("solana_dlmm_target_bound")
    if not target<=max_attempted<=int(policy["prospective_test"]["max_attempted_pools"]):
        raise ValueError("solana_dlmm_attempt_bound")
    max_runtime_seconds=int(
        max_runtime_seconds or DEFAULT_MAX_RUNTIME_SECONDS)
    if type(campaign) is not bool:raise ValueError("solana_dlmm_campaign_flag")
    if not 60<=max_runtime_seconds<=90000:
        raise ValueError("solana_dlmm_runtime_bound")
    run_started_monotonic=time.monotonic()
    deadline=run_started_monotonic+max_runtime_seconds

    book_path=OUT.with_suffix('.accounting.sqlite3')
    run_id=os.environ.get('MM_PAPER_EPOCH') or str(uuid.uuid4())
    if book_path.exists():
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(book_path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
            genesis=json.loads(db.execute('SELECT body FROM events ORDER BY seq LIMIT 1').fetchone()[0])['data']
        if os.environ.get('MM_PAPER_EPOCH') not in (None,genesis['run_id']):raise ValueError('runtime_run_identity_mismatch')
        run_id=genesis['run_id']
    book=PaperBook(book_path,run_id=run_id,policy_hash=digest(policy),capital=globals().get('NATIVE_GENESIS_CAPITAL',1_000_000_000),
                   economic_replay=(_build_position,_advance_position,_mark))
    # No providers or lifecycle workers exist yet. Only the native journal can
    # establish whether a crashed reservation ever became PAPER inventory.
    book.recover_unfilled_reservations()
    recovered=None
    if book.reconcile()['unsettled']:
        from meme_machine.runtime.position_continuation import restore_meteora_strategy
        recovered=restore_meteora_strategy(book,sys.modules[__name__])
    discovery_telemetry=dict(
        rejections=[],errors=[],qualified=[],seen=0,history_reads=0)
    compatibility_rejections=[];compatibility_screened=0
    pacer=provider.AlchemyPacer();rpcs=[]
    network_identity=_prove_network_identity(pacer,rpcs)
    plane=_evidence_plane()
    _recover_position_evidence(book)
    from meme_machine.runtime.status import update
    update('MANAGING' if recovered else 'DISCOVERING',reconciled=True,restored_positions=book.reconcile()['unsettled'])
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
        kind="solana_dlmm_authenticated_fee_density_v1_prospective",
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
    report['policy_hash']=digest(policy)
    report["continuous_campaign"]=campaign
    report["attempt_budget_window_seconds"]=None
    report['operational_configuration']=dict(campaign=campaign,census_interval_seconds=60 if campaign else None,
        attempt_limit=None if campaign else max_attempted,attempt_window_seconds=None,
        first_sighting_scope='entire_process',paper_starting_capital_lamports=1_000_000_000,
        runtime_seconds=max_runtime_seconds,position_drain_seconds=int(policy['range']['max_holding_seconds'])+300 if campaign else 0)
    report['operational_configuration_hash']=digest(report['operational_configuration'])
    pipeline=Pipeline(OUT.with_suffix(".pipeline.sqlite"),"meteora",digest(policy))
    from meme_machine.lanes.meteora.dlmm_discovery import CampaignDiscovery
    discovery_source=CampaignDiscovery(OUT.with_suffix('.discovery.sqlite'),
        api=_api,candidate=_candidate,eligible=_sol_pair,sorts=DISCOVERY_SORTS,
        pages=DISCOVERY_PAGES_PER_SORT,page_size=DISCOVERY_PAGE_SIZE,deadline=deadline,
        repeat=campaign,
        on_discovered=lambda pool,at,sort,page,rank:pipeline.record(pool,'discovered',
            source_observed_at=at,sort=sort,page=page,rank=rank))
    def checkpoint(stage):
        if discovery_source is not None:
            stats=(discovery_source.final_snapshot if discovery_source.closed else discovery_source.snapshot())
            discovery_telemetry['seen']=stats['first_seen']
            report['discovery_acquisition']=stats
        report["opportunity_coverage"]=pipeline.snapshot()
        report["discovery_unique_pool_count"]=int(discovery_telemetry["seen"])
        report["accounting"]=book.reconcile()
        report["wake_stream"]=broker.stream_status(
            DLMM_WAKE_STREAM_KEY,int(time.time()),0)
        report["evidence_broker"]=broker.telemetry()
        report["evidence_plane"]=_evidence_plane().telemetry()
        if CANDIDATE_HISTORY is not None:
            report["candidate_history"]=CANDIDATE_HISTORY.telemetry()
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
    active_triggers={}
    def progress(pool,stage,reason=None,**details):
        _record_progress(pipeline,active_triggers,pool,stage,reason,**details)
        checkpoint(stage)
    PROGRESS_HOOK=progress
    checkpoint("run_initialized")
    candidate_stream=_campaign_candidates(policy,discovery_telemetry,deadline,checkpoint,discovery_source)
    try:
        if recovered:
            address=recovered['entry']['pool']
            plane.interest(METEORA_SCOPE,lower_slot=recovered['current']['slot'],addresses=[address],
                owner='meteora:position:'+recovered['identity'],lifecycle='open',priority=0)
            plane.count('meteora.position_recoveries')
            adapter=_new_adapter(pacer,rpcs)
            lifecycle,adapter=_position_lifecycle(adapter,address,recovered['entry'],recovered['features'],
                recovered['policy'],pacer,rpcs,deadline,broker,book,recovered['identity'],recovered=recovered)
            report['recovered_lifecycle']=lifecycle;checkpoint('position_recovered')
        for candidate in candidate_stream:
            if (_runtime_expired(deadline)
                    or (not campaign and (attempted>=max_attempted or complete>=target))):
                break
            plane=_evidence_plane()
            admission=plane.admit_candidate(METEORA_SCOPE,
                addresses=[candidate['address']],owner='meteora:candidate:'+candidate['address'])
            if not admission['accepted']:
                failure_counts[admission['terminal_classification']]+=1
                report['attempts'].append(dict(pool=candidate['address'],candidate=candidate,**admission))
                _stage(candidate['address'],'terminal',admission['reason'],stage_failed='evidence_admission')
                checkpoint('evidence_admission_unavailable')
                continue
            try:
                candidate_rpcs=[]
                adapter=_new_adapter(pacer,candidate_rpcs);rpcs.extend(candidate_rpcs)
                compatibility_screened+=1
                _stage(candidate["address"],"screened")
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
                    _stage(candidate["address"],"terminal",str(exc),stage_failed="compatibility")
                    checkpoint("compatibility_rejection")
                    continue

                attempted+=1
                _stage(candidate["address"],"admitted")
                _stage(candidate["address"],"trigger_evidence_requested")
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
                        if reason=="campaign_window_insufficient_preentry_time":
                            _stage(candidate["address"],"evidence_pending",reason,
                                scope="preentry_admission_at_observation_close",
                                cross_block_transfer_authorized=False)
                        attempt["terminal_classification"]=reason
                        failure_counts[reason]+=1
                        attempt["rpc"]=_sum_rpc_metrics(candidate_rpcs)
                        report["attempts"].append(attempt)
                        _stage(candidate["address"],"terminal",(alignment.get("warmup") or {}).get("reason",reason),stage_failed=reason)
                        checkpoint("candidate_terminal")
                        continue
                    attempt["candidate_at_warmup"]=aligned_candidate
                    features=pre_entry_features(
                        warm_origin,warm,entry,aligned_candidate,policy)
                    _stage(candidate["address"],"prospective_range",lower=features.get("lower"),upper=features.get("upper"))
                    _stage(candidate["address"],"economic_vector")
                    _stage(candidate["address"],"evidence_complete")
                    decision=qualify(features,policy)
                    decision_id=None
                    if CANDIDATE_HISTORY is not None:
                        decision_id=CANDIDATE_HISTORY.record_decision(
                            'meteora',candidate["address"],mode='dlmm',
                            observed_at=int(entry.get('available_time') or time.time()),
                            qualified=bool(decision["passes"]),decision=dict(
                                features=features,qualification=decision,
                                policy_hash=digest(policy)))
                    _stage(candidate["address"],"evaluated")
                    _stage(candidate["address"],"qualified" if decision["passes"] else "rejected")
                    attempt["pre_entry_features"]=features
                    attempt["qualification"]=decision
                    attempt["decision_id"]=decision_id
                    for failed in decision["failed"]:failure_counts[failed]+=1
                    if not decision["passes"]:
                        attempt["terminal_classification"]="qualification_rejection"
                        attempt["rpc"]=_sum_rpc_metrics(candidate_rpcs)
                        report["attempts"].append(attempt)
                        _stage(candidate["address"],"terminal","qualification_rejection",failed=decision["failed"])
                        checkpoint("qualification_rejection")
                        continue
                    capital_state=book.reconcile()
                    if capital_state['unsettled']:
                        reason='paper_capital_occupied'
                        if CANDIDATE_HISTORY is not None and decision_id is not None:
                            CANDIDATE_HISTORY.record_funding(
                                decision_id,'meteora',candidate["address"],
                                status='denied',at=int(time.time()),reason=reason,
                                details=capital_state)
                        attempt["funding"]=dict(status='denied',reason=reason,capital=capital_state)
                        attempt["terminal_classification"]="funding_denied"
                        attempt["economic_rejection"]=False
                        attempt["rpc"]=_sum_rpc_metrics(candidate_rpcs)
                        report["attempts"].append(attempt)
                        failure_counts['funding_denied']+=1
                        _stage(candidate["address"],"funding_denied",reason,
                            qualification_preserved=True,decision_id=decision_id)
                        _stage(candidate["address"],"terminal",reason,
                            qualification_preserved=True,decision_id=decision_id)
                        checkpoint("funding_denied")
                        continue
                    lifecycle,adapter=_lifecycle(
                        adapter,candidate["address"],entry,features,policy,pacer,
                        candidate_rpcs,(deadline+int(policy['range']['max_holding_seconds'])+300
                            if campaign else deadline),broker,book,decision_id=decision_id)
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
                    _stage(candidate["address"],"settled" if lifecycle["complete"] else "terminal",
                        None if lifecycle["complete"] else lifecycle.get("reason","lifecycle_unverified"))
                    checkpoint("lifecycle_terminal")
                except (Unavailable,ValueError,KeyError,TypeError,OverflowError) as exc:
                    classification='paper_capital_capacity' if str(exc)=='dlmm_accounting_capital_exhausted' else 'exception'
                    if (classification=='paper_capital_capacity'
                            and CANDIDATE_HISTORY is not None
                            and attempt.get('decision_id') is not None):
                        CANDIDATE_HISTORY.record_funding(
                            attempt['decision_id'],'meteora',candidate["address"],
                            status='denied',at=int(time.time()),
                            reason='dlmm_accounting_capital_exhausted',
                            details=book.reconcile())
                        attempt['funding']=dict(status='denied',
                            reason='dlmm_accounting_capital_exhausted',
                            capital=book.reconcile())
                    attempt["terminal_classification"]=classification
                    attempt["reason"]=str(exc)[:200]
                    failure_counts[classification]+=1
                    attempt["rpc"]=_sum_rpc_metrics(candidate_rpcs)
                    report["attempts"].append(attempt)
                    _stage(candidate["address"],"terminal",str(exc),stage_failed=(pipeline.last or {}).get("stage"))
                    checkpoint("candidate_exception")
            finally:
                # A terminal candidate no longer owns a retention lease. Position
                # leases use a separate identity and remain pinned until settlement.
                plane.command(op='release',owner='meteora:candidate:'+candidate['address'],
                    scope=METEORA_SCOPE,resolved=False)
                plane.count('meteora.candidate_interests_released')
                work_id=candidate.get('_candidate_work_id')
                if CANDIDATE_HISTORY is not None and work_id is not None:
                    CANDIDATE_HISTORY.complete(work_id,status='complete')

    finally:
        try:
            try:candidate_stream.close()
            finally:
                if discovery_source is not None:
                    try:discovery_source.close()
                    finally:
                        if hasattr(discovery_source,'final_snapshot'):
                            report['discovery_acquisition']=discovery_source.final_snapshot
                            checkpoint('discovery_source_stopped')
        finally:
            if sys.exc_info()[0] is not None:
                # An exceptional native run must not leave a callback or worker
                # attached to its closed candidate/report databases.
                PROGRESS_HOOK=None
                stream_stop.set();wake_thread.join(timeout=5)
                try:pipeline.close()
                finally:
                    broker.close()
                    if CANDIDATE_HISTORY is not None:
                        CANDIDATE_HISTORY.close();CANDIDATE_HISTORY=None



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
            "continuous_campaign_window_complete" if campaign and _runtime_expired(deadline) else
            "prospective_target_complete"
            if complete>=target else
            "prospective_20m_window_complete"
            if _runtime_expired(deadline) else
            "prospective_sample_incomplete_no_threshold_change"),
    )
    report["accounting"]=book.reconcile()
    report["accounting_replay"]=book.replay_economics(_build_position,_advance_position,_mark)
    for pool,trigger_id in active_triggers.items():
        pipeline.record(trigger_id,"trigger_terminal","campaign_shutdown_unresolved_trigger",
            "reconstruction_incomplete",pool=pool)
    report["opportunity_coverage"]=pipeline.snapshot()
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
    if CANDIDATE_HISTORY is not None:
        CANDIDATE_HISTORY.close();CANDIDATE_HISTORY=None
    PROGRESS_HOOK=None;pipeline.close()
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
        from meme_machine.lanes.meteora.durable_publication import publish_report
        existing['publication']=publish_report(OUT,existing)
        print(json.dumps(dict(
            conclusion=existing["conclusion"],
            error=str(exc)[:200],
            preserved_partial_evidence=bool(existing.get("checkpoint")),
        ),sort_keys=True))
        raise


if __name__=="__main__":
    main()


def _stop_sleep(seconds):
    from meme_machine.runtime.stop import sleep
    return sleep(seconds,sleeper=time.sleep)
