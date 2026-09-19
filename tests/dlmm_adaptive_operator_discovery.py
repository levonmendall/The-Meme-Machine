"""DLMM operator discovery v2.

Prospective acquisition architecture:
1. census every observable eligible SOL-paired Meteora DLMM pool from the inventory API;
2. observe finalized DLMM program activity from the union of public Solana and
   authenticated OnFinality WebSockets;
3. deduplicate signatures before any transaction-body read;
4. reconstruct signatures through a deadline-aware queue using authenticated
   OnFinality HTTP at 5 RPS with Alchemy rescue;
5. extract all observable LP actors in the eligible pool census;
6. emit a pre-PnL candidate cohort only. No strategy/allocation authority.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import json
import os
from pathlib import Path
import time

from meme_machine import dlmm
from meme_machine.dlmm_acquisition import (
    AdaptiveReconstructionQueue,
    DEFAULT_RECONSTRUCTION_DEADLINE_SECONDS,
    ReconstructionTask,
    collect_program_union,
)
from tests import dlmm_alchemy_provider as provider
from tests import dlmm_wallet_strategy_discovery as study


OUT=Path("dlmm-adaptive-operator-discovery.json")
CHECKPOINT_OUT=Path("dlmm-adaptive-operator-checkpoint.json")
POOL_PAGE_SIZE=500
MAX_POOL_PAGES=20
MAX_ELIGIBLE_POOLS=5_000
STREAM_SECONDS=max(60,min(int(os.environ.get("MM_DLMM_DISCOVERY_STREAM_SECONDS","300")),900))
RECONSTRUCTION_SECONDS=max(
    60,min(int(os.environ.get("MM_DLMM_RECONSTRUCTION_SECONDS","900")),1800))
RECONSTRUCTION_DEADLINE_SECONDS=max(
    300,min(int(os.environ.get(
        "MM_DLMM_RECONSTRUCTION_DEADLINE_SECONDS",
        str(DEFAULT_RECONSTRUCTION_DEADLINE_SECONDS))),3600))
QUEUE_LIMIT=max(100,min(int(os.environ.get("MM_DLMM_RECONSTRUCTION_QUEUE_LIMIT","25000")),50000))
RPC_LIMIT=240
RPC_ROTATE_AT=200
TARGET_COHORT_WALLETS=80
MIN_COHORT_WALLETS=40


def _save(report):
    OUT.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")


def _atomic_json(path,body):
    path=Path(path)
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(body,indent=2,sort_keys=True)+"\n")
    tmp.replace(path)


def _pool_addresses(pool_rows):
    return [row["address"] for row in pool_rows]


def _load_checkpoint(pool_rows):
    if not CHECKPOINT_OUT.exists():
        return {},{}
    body=json.loads(CHECKPOINT_OUT.read_text())
    if body.get("kind")!="dlmm_adaptive_operator_checkpoint_v1":
        return {},{}
    if body.get("pool_addresses")!=_pool_addresses(pool_rows):
        return {},{}
    candidates=body.get("candidates") or {}
    processed=body.get("processed") or {}
    if not isinstance(candidates,dict) or not isinstance(processed,dict):
        return {},{}
    return candidates,processed


def _write_checkpoint(pool_rows,candidates,processed):
    _atomic_json(CHECKPOINT_OUT,dict(
        kind="dlmm_adaptive_operator_checkpoint_v1",
        pool_addresses=_pool_addresses(pool_rows),
        updated_at=int(time.time()),
        candidate_count=len(candidates),
        processed_count=len(processed),
        candidates=candidates,
        processed=processed,
    ))


def census_eligible_pools():
    """Census the complete API-visible eligible SOL-paired universe or fail closed."""
    rows=[];seen=set();complete=False;pages=0
    for page in range(1,MAX_POOL_PAGES+1):
        payload=study._json_get("/pools",dict(
            page=page,page_size=POOL_PAGE_SIZE,
            sort_by="fee_tvl_ratio_24h:desc",
            filter_by="is_blacklisted=false && tvl>=50000 && volume_24h>=25000",
        ))
        data=payload.get("data") if isinstance(payload,dict) else None
        if not isinstance(data,list):
            raise RuntimeError("dlmm_v2_pool_census_shape")
        pages=page
        for row in data:
            if not isinstance(row,dict) or not study._sol_paired(row):
                continue
            address=row.get("address")
            if not isinstance(address,str) or address in seen:
                continue
            seen.add(address)
            rows.append(dict(
                address=address,name=row.get("name"),
                tvl=row.get("tvl"),volume_24h=(row.get("volume") or {}).get("24h"),
                fee_tvl_ratio_24h=(row.get("fee_tvl_ratio") or {}).get("24h"),
                pool_created_at=row.get("created_at"),
                token_x=(row.get("token_x") or {}).get("symbol"),
                token_y=(row.get("token_y") or {}).get("symbol"),
            ))
            if len(rows)>MAX_ELIGIBLE_POOLS:
                raise RuntimeError("dlmm_v2_pool_census_capacity")
        if len(data)<POOL_PAGE_SIZE:
            complete=True
            break
    if not complete:
        raise RuntimeError("dlmm_v2_pool_census_truncated")
    rows.sort(key=lambda r:r["address"])
    return rows,dict(
        complete=True,pages=pages,eligible_sol_paired_pools=len(rows),
        page_size=POOL_PAGE_SIZE,max_pages=MAX_POOL_PAGES,
        filter="is_blacklisted=false && tvl>=50000 && volume_24h>=25000 && exactly_one_SOL_leg",
    )


def _actor_events_any_pool(tx,pool_rank,signature_row):
    """Extract supported LP actor mutations without iterating every pool."""
    meta=tx.get("meta") or {};message=(tx.get("transaction") or {}).get("message") or {}
    keys=study._keys(meta,message)
    required=int((message.get("header") or {}).get("numRequiredSignatures",0))
    events=[]
    for outer,inner,ix in study._ordered_instructions(meta,message):
        pi=ix.get("programIdIndex")
        if type(pi) is not int or not 0<=pi<len(keys) or keys[pi]!=dlmm.PROGRAM:
            continue
        raw=study._un58_data(ix.get("data") or "")
        action=study.LP_ACTOR_INSTRUCTIONS.get(raw[:8])
        if action is None:
            continue
        accounts=ix.get("accounts") or []
        if len(accounts)<=9:
            continue
        if any(type(accounts[i]) is not int or not 0<=accounts[i]<len(keys)
               for i in (0,1,9)):
            continue
        pool=keys[accounts[1]]
        rank=pool_rank.get(pool)
        if rank is None or accounts[9]>=required:
            continue
        events.append(dict(
            wallet=keys[accounts[9]],position=keys[accounts[0]],
            action=action,pool=pool,pool_rank=rank,
            slot=int(tx.get("slot") or signature_row.get("slot") or 0),
            signature=signature_row.get("signature"),
            execution_order=[outer,inner],
            discovery_providers=list(signature_row.get("providers") or []),
        ))
    return events


def _provider_session(rpc,started,reason):
    return dict(
        started=started,ended=int(time.time()),reason=reason,
        logical_requests=rpc.calls,transport_requests=rpc.http_requests,
        failures=rpc.failures,retries=rpc.retries,
        failure_kinds=dict(sorted(rpc.failure_kinds.items())),
        provider_topology=(rpc.provider_telemetry()
                           if hasattr(rpc,"provider_telemetry") else None),
    )


def reconstruct_union(signature_rows,pool_rows):
    pool_rank={row["address"]:i+1 for i,row in enumerate(pool_rows)}
    queue=AdaptiveReconstructionQueue(limit=QUEUE_LIMIT)
    now=time.time()
    for i,row in enumerate(signature_rows):
        queue.enqueue(ReconstructionTask(
            identity=row["signature"],kind="dlmm_program_transaction",
            deadline=max(now+1,float(row["first_observed_at"])+RECONSTRUCTION_DEADLINE_SECONDS),
            priority=(float(row["first_observed_at"]),int(row["slot"]),i),
            payload=dict(row),estimated_calls=1,
        ))

    pacer=provider.AlchemyPacer()
    rpc=provider.new_rpc(limit=RPC_LIMIT,pacer=pacer)
    session_started=int(time.time());sessions=[];failures=[];events=[]
    deadline=time.monotonic()+RECONSTRUCTION_SECONDS

    while len(queue) and time.monotonic()<deadline:
        now=time.time()
        task=queue.pop_ready(
            now,provider_calls=rpc.calls,rotation_threshold=RPC_ROTATE_AT,
            request_interval_seconds=provider.DLMM_MIN_REQUEST_INTERVAL_SECONDS)
        if task is None:
            if rpc.calls+1>RPC_ROTATE_AT:
                sessions.append(_provider_session(rpc,session_started,"bounded_http_rotation"))
                rpc=provider.new_rpc(limit=RPC_LIMIT,pacer=pacer)
                session_started=int(time.time())
                continue
            # pop_ready may have expired/dropped one task. Avoid a busy loop if only
            # provider timing changed.
            time.sleep(0.01)
            continue
        row=task.payload
        before=dict(rpc.failure_kinds)
        try:
            tx=rpc.call("getTransaction",[
                row["signature"],dict(
                    encoding="json",commitment="finalized",
                    maxSupportedTransactionVersion=study.MAX_SUPPORTED_TRANSACTION_VERSION,
                )
            ],False)
            if not isinstance(tx,dict):
                raise RuntimeError("dlmm_v2_transaction_unavailable")
            events.extend(_actor_events_any_pool(tx,pool_rank,row))
        except Exception as exc:
            after=dict(rpc.failure_kinds)
            delta={k:int(after.get(k,0))-int(before.get(k,0))
                   for k in set(before)|set(after)
                   if int(after.get(k,0))-int(before.get(k,0))}
            failures.append(dict(
                signature=row["signature"],slot=row["slot"],
                error=type(exc).__name__,failure_kind_delta=dict(sorted(delta.items())),
            ))

    sessions.append(_provider_session(
        rpc,session_started,"queue_complete" if not len(queue) else "wall_clock_end"))
    return dict(
        events=events,failures=failures,queue=queue.status(time.time()),
        remaining_queue_depth=len(queue),provider_sessions=sessions,
        shared_pacer=pacer.telemetry(),
        complete=(not len(queue) and not failures),
    )


def _wallet_rows(events):
    action_counts=defaultdict(Counter);pool_sets=defaultdict(set);latest={}
    for e in events:
        action_counts[e["wallet"]][e["action"]]+=1
        pool_sets[e["wallet"]].add(e["pool"])
        prior=latest.get(e["wallet"])
        if prior is None or (e["slot"],e["signature"] or "")>(prior["slot"],prior["signature"] or ""):
            latest[e["wallet"]]=e
    rows=[]
    for wallet in action_counts:
        last=latest[wallet]
        rows.append(dict(
            wallet=wallet,
            observed_lp_actions=dict(sorted(action_counts[wallet].items())),
            observed_lp_action_count=sum(action_counts[wallet].values()),
            observed_distinct_pools=len(pool_sets[wallet]),
            latest_pool=last["pool"],latest_slot=last["slot"],
            latest_signature=last["signature"],latest_action=last["action"],
        ))
    rows.sort(key=lambda r:(
        -r["observed_distinct_pools"],-r["observed_lp_action_count"],
        -r["latest_slot"],r["wallet"]))
    return rows


def main():
    started=int(time.time())
    report=dict(
        kind="dlmm_adaptive_operator_discovery_v2",started=started,
        pnl_data_read=False,strategy_freeze_permitted=False,
        allocation_authority=False,signing_authority=False,submission_authority=False,
        provider_roles=dict(
            discovery="union(public_solana_ws,authenticated_onfinality_ws)",
            reconstruction_primary="authenticated_onfinality_http_5rps",
            reconstruction_rescue="alchemy_http_rescue_only",
        ),
        status="started",
    )
    _save(report)

    pools,pool_census=census_eligible_pools()
    report.update(pool_census=pool_census,pools=pools);_save(report)

    union=collect_program_union(STREAM_SECONDS)
    report.update(stream_union=union);_save(report)

    reconstruction=reconstruct_union(union["signatures"],pools)
    events=reconstruction.pop("events")
    wallets=_wallet_rows(events)
    cohort=wallets[:TARGET_COHORT_WALLETS]

    status=(
        "candidate_cohort_ready"
        if reconstruction["complete"] and len(cohort)>=MIN_COHORT_WALLETS
        else "incomplete_reconstruction"
        if not reconstruction["complete"]
        else "insufficient_observed_wallets"
    )
    report.update(
        ended=int(time.time()),status=status,
        reconstruction=reconstruction,
        lp_actor_event_count=len(events),
        observed_wallet_count=len(wallets),
        all_observed_wallets=wallets,
        candidate_wallet_count=len(cohort),
        candidate_wallets=cohort,
        candidate_selection=dict(
            pnl_blind=True,
            order="distinct_observed_pools_desc_then_lp_actions_desc_then_latest_slot_desc",
            target_wallets=TARGET_COHORT_WALLETS,
            minimum_wallets=MIN_COHORT_WALLETS,
        ),
    )
    _save(report)
    print(json.dumps(dict(
        status=status,pools=len(pools),
        stream_signatures=union["union"]["unique_signatures"],
        reconstructed=reconstruction["queue"]["processed"],
        remaining=reconstruction["remaining_queue_depth"],
        events=len(events),wallets=len(wallets),
    ),sort_keys=True))
    if not reconstruction["complete"]:
        raise RuntimeError("dlmm_v2_reconstruction_incomplete")
    return report


if __name__=="__main__":
    main()
