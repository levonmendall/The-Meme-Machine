"""DLMM operator discovery v2.

Prospective acquisition architecture:
1. census every observable eligible SOL-paired Meteora DLMM pool from the inventory API;
2. observe finalized DLMM program activity from the public Solana WebSocket;
3. classify notification logs and deduplicate signatures before any body read;
4. queue only likely/uncertain LP mutations, then reconstruct directly through
   authenticated Alchemy HTTP at a 5 RPS ceiling;
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
    valid_solana_signature,
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

LP_MUTATIONS={
    bytes([181,157,89,67,143,182,52,72]):("add_liquidity",1,0,11),
    bytes([228,162,78,28,70,219,116,115]):("add_liquidity2",1,0,9),
    bytes([7,3,150,127,148,40,61,200]):("add_liquidity_by_strategy",1,0,11),
    bytes([3,221,149,218,111,141,118,213]):("add_liquidity_by_strategy2",1,0,9),
    bytes([41,5,238,175,100,225,6,205]):("add_liquidity_by_strategy_one_side",1,0,8),
    bytes([28,140,238,99,231,162,21,149]):("add_liquidity_by_weight",1,0,11),
    bytes([209,59,63,91,111,200,153,228]):("add_liquidity_by_weight2",1,0,9),
    bytes([94,155,103,151,70,95,220,165]):("add_liquidity_one_side",1,0,8),
    bytes([161,194,103,84,171,71,250,154]):("add_liquidity_one_side_precise",1,0,8),
    bytes([33,51,163,201,117,98,125,231]):("add_liquidity_one_side_precise2",1,0,6),
    bytes([92,4,176,193,119,185,83,9]):("rebalance_liquidity",1,0,9),
    bytes([10,51,61,35,112,105,24,85]):("remove_all_liquidity",1,0,11),
    bytes([80,85,209,72,24,206,177,108]):("remove_liquidity",1,0,11),
    bytes([230,215,82,127,241,101,227,146]):("remove_liquidity2",1,0,9),
    bytes([26,82,102,152,240,74,105,26]):("remove_liquidity_by_range",1,0,11),
    bytes([204,2,195,145,53,145,145,205]):("remove_liquidity_by_range2",1,0,9),
    bytes([169,32,79,137,136,232,70,137]):("claim_fee",0,1,4),
    bytes([112,191,101,171,28,144,127,187]):("claim_fee2",0,1,2),
}


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
    candidates={
        signature:row for signature,row in candidates.items()
        if valid_solana_signature(signature)
    }
    processed={
        signature:row for signature,row in processed.items()
        if signature in candidates
    }
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


def _number(value):
    try:
        return float(value)
    except (TypeError,ValueError):
        return None


def diagnose_pool_universe():
    """Audit the unfiltered API-visible pool inventory without changing eligibility."""
    primary=Counter();overlap=Counter();examples=defaultdict(list)
    total=0;sol_pairs=0;complete=False;pages=0;eligible=0
    seen=set()
    for page in range(1,MAX_POOL_PAGES+1):
        payload=study._json_get("/pools",dict(
            page=page,page_size=POOL_PAGE_SIZE,sort_by="tvl:desc",
        ))
        data=payload.get("data") if isinstance(payload,dict) else None
        if not isinstance(data,list):
            raise RuntimeError("dlmm_v2_pool_diagnostic_shape")
        pages=page
        for row in data:
            total+=1
            if not isinstance(row,dict):
                primary["malformed_row"]+=1;overlap["malformed_row"]+=1
                continue
            address=row.get("address")
            if not isinstance(address,str) or not address:
                primary["malformed_address"]+=1;overlap["malformed_address"]+=1
                continue
            if address in seen:
                overlap["duplicate_address"]+=1
                continue
            seen.add(address)

            reasons=[]
            if row.get("is_blacklisted") is True:
                reasons.append("blacklisted")
            x=(row.get("token_x") or {}).get("address")
            y=(row.get("token_y") or {}).get("address")
            sol_pair=(x==dlmm.WSOL) ^ (y==dlmm.WSOL)
            if sol_pair:
                sol_pairs+=1
            else:
                reasons.append("not_exactly_one_sol_leg")
            tvl=_number(row.get("tvl"))
            volume=_number((row.get("volume") or {}).get("24h"))
            if tvl is None:
                reasons.append("missing_tvl")
            elif tvl<50000:
                reasons.append("tvl_below_50000")
            if volume is None:
                reasons.append("missing_volume_24h")
            elif volume<25000:
                reasons.append("volume_24h_below_25000")

            if not reasons:
                eligible+=1
                primary["eligible"]+=1
                continue
            for reason in reasons:
                overlap[reason]+=1
                if len(examples[reason])<10:
                    examples[reason].append(dict(
                        address=address,name=row.get("name"),
                        tvl=row.get("tvl"),
                        volume_24h=(row.get("volume") or {}).get("24h"),
                        token_x=(row.get("token_x") or {}).get("symbol"),
                        token_y=(row.get("token_y") or {}).get("symbol"),
                    ))
            precedence=(
                "blacklisted","not_exactly_one_sol_leg","missing_tvl",
                "tvl_below_50000","missing_volume_24h","volume_24h_below_25000"
            )
            primary[next(reason for reason in precedence if reason in reasons)]+=1
        if len(data)<POOL_PAGE_SIZE:
            complete=True
            break
    return dict(
        complete=complete,pages=pages,page_size=POOL_PAGE_SIZE,
        observable_unique_pools=len(seen),raw_rows_seen=total,
        exact_one_sol_leg_pools=sol_pairs,
        eligible_under_current_rules=eligible,
        primary_classification=dict(sorted(primary.items())),
        overlapping_rejection_reasons=dict(sorted(overlap.items())),
        rejection_examples={k:v for k,v in sorted(examples.items())},
        rules=dict(
            exactly_one_sol_leg=True,is_blacklisted=False,
            min_tvl_usd=50000,min_volume_24h_usd=25000,
        ),
    )


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
        spec=LP_MUTATIONS.get(raw[:8])
        if spec is None:
            continue
        action,pool_i,position_i,signer_i=spec
        accounts=ix.get("accounts") or []
        needed=max(pool_i,position_i,signer_i)
        if len(accounts)<=needed:
            continue
        selected=[accounts[pool_i],accounts[position_i],accounts[signer_i]]
        if any(type(i) is not int or not 0<=i<len(keys) for i in selected):
            continue
        pool=keys[accounts[pool_i]]
        rank=pool_rank.get(pool)
        if rank is None or accounts[signer_i]>=required:
            continue
        events.append(dict(
            wallet=keys[accounts[signer_i]],position=keys[accounts[position_i]],
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
    prior_candidates,processed=_load_checkpoint(pool_rows)
    candidates={str(k):dict(v) for k,v in prior_candidates.items()}
    for row in signature_rows:
        candidates[row["signature"]]=dict(row)
    _write_checkpoint(pool_rows,candidates,processed)

    queue=AdaptiveReconstructionQueue(limit=QUEUE_LIMIT)
    now=time.time();reused_events=[]
    ordered=sorted(candidates.values(),key=lambda r:(
        float(r["first_observed_at"]),int(r["slot"]),r["signature"]))
    for i,row in enumerate(ordered):
        prior=processed.get(row["signature"])
        if isinstance(prior,dict) and prior.get("status")=="success":
            reused_events.extend(prior.get("events") or [])
            continue
        queue.enqueue(ReconstructionTask(
            identity=row["signature"],kind="dlmm_program_transaction",
            deadline=max(now+1,float(row["first_observed_at"])+RECONSTRUCTION_DEADLINE_SECONDS),
            priority=(float(row["first_observed_at"]),int(row["slot"]),i),
            payload=dict(row),estimated_calls=1,
        ))

    pacer=provider.AlchemyPacer()
    rpc=provider.new_rpc(limit=RPC_LIMIT,pacer=pacer)
    session_started=int(time.time());sessions=[];failures=[];events=list(reused_events)
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
            extracted=_actor_events_any_pool(tx,pool_rank,row)
            events.extend(extracted)
            processed[row["signature"]]=dict(
                status="success",slot=row["slot"],
                relevance_actions=row.get("relevance_actions") or [],
                events=extracted,
            )
            _write_checkpoint(pool_rows,candidates,processed)
        except Exception as exc:
            after=dict(rpc.failure_kinds)
            delta={k:int(after.get(k,0))-int(before.get(k,0))
                   for k in set(before)|set(after)
                   if int(after.get(k,0))-int(before.get(k,0))}
            failure=dict(
                signature=row["signature"],slot=row["slot"],
                error=type(exc).__name__,failure_kind_delta=dict(sorted(delta.items())),
            )
            failures.append(failure)
            processed[row["signature"]]=dict(status="failed",**failure)
            _write_checkpoint(pool_rows,candidates,processed)

    sessions.append(_provider_session(
        rpc,session_started,"queue_complete" if not len(queue) else "wall_clock_end"))
    unresolved=[
        signature for signature in candidates
        if not isinstance(processed.get(signature),dict)
        or processed[signature].get("status")!="success"
    ]
    return dict(
        events=events,failures=failures,queue=queue.status(time.time()),
        remaining_queue_depth=len(queue),provider_sessions=sessions,
        shared_pacer=pacer.telemetry(),
        checkpoint_path=str(CHECKPOINT_OUT),
        checkpoint_reused_event_count=len(reused_events),
        checkpoint_processed_signatures=len(processed),
        unresolved_candidate_count=len(unresolved),
        complete=(not len(queue) and not failures and not unresolved),
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
            discovery="public_solana_ws_full_stream_then_log_relevance_filter",
            reconstruction_primary="authenticated_alchemy_http_5rps",
            reconstruction_rescue=None,
        ),
        status="started",
    )
    _save(report)

    pool_rejection_diagnostic=diagnose_pool_universe()
    report.update(pool_rejection_diagnostic=pool_rejection_diagnostic);_save(report)

    pools,pool_census=census_eligible_pools()
    report.update(pool_census=pool_census,pools=pools);_save(report)

    union=collect_program_union(STREAM_SECONDS)
    report.update(stream_union=union);_save(report)

    reconstruction=reconstruct_union(union["lp_candidates"],pools)
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
        reconstruction_candidates=union["union"]["reconstruction_candidates"],
        filtered_without_http=union["union"]["filtered_without_http"],
        reconstructed=reconstruction["queue"]["processed"],
        remaining=reconstruction["remaining_queue_depth"],
        events=len(events),wallets=len(wallets),
    ),sort_keys=True))
    if not reconstruction["complete"]:
        raise RuntimeError("dlmm_v2_reconstruction_incomplete")
    return report


if __name__=="__main__":
    main()
