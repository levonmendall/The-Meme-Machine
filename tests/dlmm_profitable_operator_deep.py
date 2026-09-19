"""Execute authenticated deep reconstruction for every eligible DLMM operator.

Input is the provisional ranking produced from the frozen all-pool cohort. The deep
stage does not trust the provisional top lists as a filter: every eligible wallet is
processed. Wallet-level checkpoints make the expensive Solana transaction recovery
restart-safe. Unsupported histories remain explicitly unavailable.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import argparse
import json
import math
from pathlib import Path
import statistics
import time

from meme_machine import pump
from meme_machine.dlmm_tape import _keys, _ordered_instructions, _un58_data
from tests import dlmm_alchemy_provider as provider
from tests import dlmm_profitable_operator_discovery as op
from tests import dlmm_profitable_operator_reconstruction as rec

DEFAULT_RANKING=Path("dlmm-profitable-operator-ranking.json")
CHECKPOINT=Path("dlmm-profitable-operator-deep-checkpoint.json")
OUT=Path("dlmm-profitable-operator-deep-reconstruction.json")
DERIVATION_PROTOCOL=Path("DLMM_PROFITABLE_OPERATOR_RULE_DERIVATION_V1.json")
RPC_OBJECT_LOGICAL_LIMIT=200


def _atomic(path,body):
    path=Path(path);tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(body,indent=2,sort_keys=True)+"\n")
    tmp.replace(path)


def _signature(ranking):
    return dict(
        protocol_sha256=ranking.get("protocol_sha256"),
        cohort_hash=ranking.get("cohort_hash"),
        wallets=list(ranking.get("deep_reconstruction_wallets") or []),
        transaction_version=1,
        network_cost_policy="unique_wallet_transaction_fee_once",
        entry_context="meteora_5m_hour_before_entry",
    )


def _load_checkpoint(signature):
    if not CHECKPOINT.exists(): return {},{}
    body=json.loads(CHECKPOINT.read_text())
    if body.get("kind")!="dlmm_profitable_operator_deep_checkpoint_v1" or body.get("signature")!=signature:
        raise RuntimeError("dlmm_operator_deep_checkpoint_mismatch")
    rows=body.get("rows") or {};failures=body.get("failures") or {}
    if not isinstance(rows,dict) or not isinstance(failures,dict):
        raise RuntimeError("dlmm_operator_deep_checkpoint_shape")
    return rows,failures


def _write_checkpoint(signature,rows,failures,started):
    _atomic(CHECKPOINT,dict(
        kind="dlmm_profitable_operator_deep_checkpoint_v1",
        status=("complete" if len(rows)==len(signature["wallets"]) and not failures
                else "partial"),
        signature=signature,started_at=started,updated_at=int(time.time()),
        completed_wallets=len(rows),failed_wallets=len(failures),
        rows=rows,failures=failures,
    ))


def _fetch_transactions(signatures):
    signatures=sorted(set(signatures))
    pacer=provider.AlchemyPacer();out={}
    for start in range(0,len(signatures),RPC_OBJECT_LOGICAL_LIMIT):
        group=signatures[start:start+RPC_OBJECT_LOGICAL_LIMIT]
        rpc=provider.new_rpc(limit=240,pacer=pacer)
        params=[[sig,dict(
            encoding="json",commitment="finalized",
            maxSupportedTransactionVersion=1,
        )] for sig in group]
        values=rpc.call_many("getTransaction",params,True,batch_size=8)
        for sig,tx in zip(group,values):
            if not tx:
                raise RuntimeError("dlmm_operator_finalized_transaction_unavailable")
            out[sig]=tx
    return out,pacer.telemetry()


def _history_signature_map(wallet_row):
    mapping=defaultdict(list)
    for position,events in (wallet_row.get("histories") or {}).items():
        for event in events:
            sig=event.get("signature")
            if isinstance(sig,str) and sig:
                mapping[sig].append((position,event))
    return mapping


def _features_for_wallet(wallet_row,transactions):
    signature_map=_history_signature_map(wallet_row)
    by_position=defaultdict(dict);tx_meta={}
    for sig,items in signature_map.items():
        tx=transactions.get(sig)
        if tx is None:
            raise RuntimeError("dlmm_operator_missing_transaction")
        tx_meta[sig]=dict(
            fee_lamports=int((tx.get("meta") or {}).get("fee") or 0),
            block_time=tx.get("blockTime"),
        )
        seen=set()
        for position,event in items:
            pool=event.get("pool")
            key=(position,pool)
            if key in seen: continue
            seen.add(key)
            if not isinstance(pool,str):
                raise RuntimeError("dlmm_operator_history_pool_missing")
            by_position[position][sig]=rec.transaction_features(tx,pool,position)
            tx_meta[sig]["fee_payer"]=by_position[position][sig].get("fee_payer")
    return by_position,tx_meta


def _direct_sol_prices(wallet_row):
    prices=defaultdict(list)
    for events in (wallet_row.get("histories") or {}).values():
        for event in events:
            sig=event.get("signature")
            price=rec.infer_event_sol_price(event)
            if isinstance(sig,str) and price is not None:
                prices[sig].append(float(price))
    resolved={}
    for sig,values in prices.items():
        # A transaction may contain multiple position events. Require all directly
        # inferred SOL prices to agree within 1%; otherwise do not price its fee.
        median=statistics.median(values)
        if median>0 and all(abs(v/median-1.0)<=0.01 for v in values):
            resolved[sig]=median
    return resolved


def _network_costs(wallet_row,tx_meta):
    prices=_direct_sol_prices(wallet_row)
    total_lamports=0;total_usd=0.0;unpriced=[]
    position_sigs=defaultdict(set)
    signature_positions=defaultdict(set)
    for position,events in (wallet_row.get("histories") or {}).items():
        for event in events:
            sig=event.get("signature")
            if isinstance(sig,str) and sig:
                position_sigs[position].add(sig)
                signature_positions[sig].add(position)
    fee_usd_by_sig={}
    for sig,meta in tx_meta.items():
        lamports=int(meta.get("fee_lamports") or 0);total_lamports+=lamports
        price=prices.get(sig)
        if price is None:
            unpriced.append(sig);continue
        usd=lamports/1_000_000_000.0*price
        fee_usd_by_sig[sig]=usd;total_usd+=usd

    position_cost={}
    ambiguous=[]
    for position,sigs in position_sigs.items():
        if any(sig not in fee_usd_by_sig for sig in sigs):
            position_cost[position]=None;continue
        # A single Solana transaction can manage several positions. Wallet-level
        # cost is exact, but position-level allocation would be arbitrary; TWR then
        # remains unavailable rather than splitting the fee.
        if any(len(signature_positions[sig])!=1 for sig in sigs):
            position_cost[position]=None
            ambiguous.extend(sig for sig in sigs if len(signature_positions[sig])!=1)
            continue
        position_cost[position]=sum(fee_usd_by_sig[sig] for sig in sigs)
    return dict(
        total_fee_lamports=total_lamports,
        total_fee_sol=total_lamports/1_000_000_000.0,
        total_fee_usd=(None if unpriced else total_usd),
        fee_usd_complete=not unpriced,
        unpriced_signatures=sorted(unpriced),
        position_cost_usd=position_cost,
        position_cost_ambiguous_signatures=sorted(set(ambiguous)),
        fee_usd_by_signature=fee_usd_by_sig,
    )


def _after_cost_path(wallet_row,network):
    if not network["fee_usd_complete"]:
        return dict(
            max_after_cost_realized_drawdown_usd=None,
            profitable_after_cost_active_week_rate=None,
            after_cost_active_weeks=None,
        )
    timeline=[]
    for p in wallet_row.get("positions") or []:
        closed=p.get("closed_at")
        if isinstance(closed,int):
            timeline.append((closed,1,float(p.get("pnl_usd") or 0.0)))
    sig_events=_history_signature_map(wallet_row)
    for sig,usd in network["fee_usd_by_signature"].items():
        items=sig_events.get(sig) or []
        times=[e.get("block_time") for _pos,e in items if isinstance(e.get("block_time"),int)]
        if not times:
            return dict(
                max_after_cost_realized_drawdown_usd=None,
                profitable_after_cost_active_week_rate=None,
                after_cost_active_weeks=None,
            )
        timeline.append((min(times),0,-float(usd)))
    timeline.sort()
    equity=0.0;peak=0.0;drawdown=0.0;weeks=defaultdict(float)
    for ts,_order,value in timeline:
        equity+=value;peak=max(peak,equity);drawdown=max(drawdown,peak-equity)
        weeks[int(ts)//604800]+=value
    values=list(weeks.values())
    return dict(
        max_after_cost_realized_drawdown_usd=drawdown,
        profitable_after_cost_active_week_rate=(
            None if not values else sum(v>0 for v in values)/len(values)),
        after_cost_active_weeks=len(values),
    )


def _mint_initialized_in_transaction(tx,mint):
    if not tx or not isinstance(tx.get("meta"),dict) or tx["meta"].get("err"):
        return False
    message=(tx.get("transaction") or {}).get("message") or {}
    try:
        keys=_keys(tx["meta"],message)
    except (KeyError,TypeError):
        return False
    for _outer,_inner,ix in _ordered_instructions(tx["meta"],message):
        pi=ix.get("programIdIndex")
        if type(pi) is not int or not 0<=pi<len(keys) or keys[pi]!=pump.TOKEN_PROGRAM:
            continue
        accounts=ix.get("accounts") or []
        if not accounts or type(accounts[0]) is not int or not 0<=accounts[0]<len(keys):
            continue
        if keys[accounts[0]]!=mint:
            continue
        raw=_un58_data(ix.get("data") or "")
        if raw and raw[0] in (0,20):  # InitializeMint / InitializeMint2
            return True
    return False


class TokenAgeResolver:
    def __init__(self,policy=None):
        if policy is None:
            body=json.loads(DERIVATION_PROTOCOL.read_text())
            policy=(body.get("context_resolution") or {}).get("token_age") or {}
        self.max_pages=int(policy.get("max_signature_pages") or 0)
        self.page_size=int(policy.get("signatures_per_page") or 0)
        if not 1<=self.max_pages<=5 or self.page_size!=1000:
            raise RuntimeError("dlmm_operator_token_age_policy_drift")
        self.cache={}
        self.pacer=provider.AlchemyPacer()

    def resolve(self,mint):
        if mint in self.cache:
            return self.cache[mint]
        rpc=provider.new_rpc(limit=240,pacer=self.pacer)
        rows=[];before=None;exhausted=False
        for page in range(1,self.max_pages+1):
            cfg=dict(limit=self.page_size,commitment="finalized")
            if before is not None:
                cfg["before"]=before
            batch=rpc.call("getSignaturesForAddress",[mint,cfg],True)
            if not isinstance(batch,list):
                raise RuntimeError("dlmm_operator_token_age_signature_shape")
            rows.extend(batch)
            if len(batch)<self.page_size:
                exhausted=True
                break
            last=batch[-1] if batch else None
            cursor=(last or {}).get("signature") if isinstance(last,dict) else None
            if not isinstance(cursor,str) or not cursor or cursor==before:
                raise RuntimeError("dlmm_operator_token_age_cursor")
            before=cursor
        if not exhausted:
            result=dict(
                exact=False,creation_time=None,creation_signature=None,
                reason="mint_signature_history_exceeds_preregistered_bound",
                signatures_scanned=len(rows))
            self.cache[mint]=result
            return result
        successful=[
            row for row in rows if isinstance(row,dict) and not row.get("err")
            and isinstance(row.get("signature"),str)
        ]
        if not successful:
            result=dict(
                exact=False,creation_time=None,creation_signature=None,
                reason="no_successful_mint_history",signatures_scanned=len(rows))
            self.cache[mint]=result
            return result
        earliest=successful[-1]
        tx=rpc.call("getTransaction",[
            earliest["signature"],dict(
                encoding="json",commitment="finalized",
                maxSupportedTransactionVersion=1,
            )
        ],True)
        if not tx or not _mint_initialized_in_transaction(tx,mint):
            result=dict(
                exact=False,creation_time=None,
                creation_signature=earliest["signature"],
                reason="earliest_successful_transaction_not_mint_initialization",
                signatures_scanned=len(rows))
            self.cache[mint]=result
            return result
        created=tx.get("blockTime")
        if not isinstance(created,int) or created<=0:
            result=dict(
                exact=False,creation_time=None,
                creation_signature=earliest["signature"],
                reason="mint_initialization_block_time_unavailable",
                signatures_scanned=len(rows))
            self.cache[mint]=result
            return result
        result=dict(
            exact=True,creation_time=created,
            creation_signature=earliest["signature"],
            reason=None,signatures_scanned=len(rows),
            initialization="classic_spl_initialize_mint")
        self.cache[mint]=result
        return result


def _market_context(pool,entry_time,pool_cache,context_cache,token_age_resolver=None):
    if not isinstance(entry_time,int) or entry_time<=0:
        return dict(status="unavailable",reason="missing_entry_time")
    key=(pool,entry_time//300)
    if key in context_cache:
        return context_cache[key]
    if pool not in pool_cache:
        pool_cache[pool]=op._api(f"/pools/{pool}")
    info=pool_cache[pool]
    created=info.get("created_at") if isinstance(info,dict) else None
    start=max(0,entry_time-3600)
    ohlcv_error=None;volume_error=None
    try:
        ohlcv=op._api(f"/pools/{pool}/ohlcv",dict(
            timeframe="5m",start_time=start,end_time=entry_time))
        candles=ohlcv.get("data") if isinstance(ohlcv,dict) else None
        if not isinstance(candles,list):
            raise RuntimeError("dlmm_operator_ohlcv_shape")
    except Exception as exc:
        candles=None;ohlcv_error=type(exc).__name__
    try:
        vol=op._api(f"/pools/{pool}/volume/history",dict(
            timeframe="5m",start_time=start,end_time=entry_time))
        volumes=vol.get("data") if isinstance(vol,dict) else None
        if not isinstance(volumes,list):
            raise RuntimeError("dlmm_operator_volume_shape")
    except Exception as exc:
        volumes=None;volume_error=type(exc).__name__
    closes=[] if candles is None else [
        float(x["close"]) for x in candles
        if isinstance(x,dict) and float(x.get("close") or 0)>0]
    returns=[math.log(b/a) for a,b in zip(closes,closes[1:]) if a>0 and b>0]
    token_x=(info.get("token_x") or {}).get("address") if isinstance(info,dict) else None
    token_y=(info.get("token_y") or {}).get("address") if isinstance(info,dict) else None
    non_sol_mint=(token_y if token_x==rec.dlmm.WSOL else
                  token_x if token_y==rec.dlmm.WSOL else None)
    token_creation=None
    if token_age_resolver is not None and isinstance(non_sol_mint,str):
        token_creation=token_age_resolver.resolve(non_sol_mint)
    token_age=None;token_age_reason="exact_token_creation_time_not_proven"
    if token_creation is not None:
        if token_creation.get("exact") and token_creation.get("creation_time")<=entry_time:
            token_age=entry_time-int(token_creation["creation_time"])
            token_age_reason=None
        else:
            token_age_reason=token_creation.get("reason") or "token_creation_after_entry"
    result=dict(
        status=("available" if ohlcv_error is None and volume_error is None else "partial"),
        pool_created_at=created,
        pool_age_seconds=(None if not isinstance(created,int)
                          else max(0,entry_time-created)),
        pre_entry_60m_volume_usd=(
            None if volumes is None else
            sum(float(x.get("volume") or 0.0) for x in volumes if isinstance(x,dict))),
        pre_entry_60m_fees_usd=(
            None if volumes is None else
            sum(float(x.get("fees") or 0.0) for x in volumes if isinstance(x,dict))),
        pre_entry_5m_log_return_volatility=(
            None if candles is None or len(returns)<2 else statistics.pstdev(returns)),
        ohlcv_candles=(None if candles is None else len(candles)),
        volume_buckets=(None if volumes is None else len(volumes)),
        ohlcv_unavailable_reason=ohlcv_error,
        volume_unavailable_reason=volume_error,
        fee_tvl_at_entry=None,
        fee_tvl_at_entry_reason="historical_tvl_not_exposed_by_meteora_data_api",
        non_sol_token_mint=non_sol_mint,
        token_age_seconds=token_age,
        token_age_reason=token_age_reason,
        token_creation=token_creation,
    )
    context_cache[key]=result
    return result


def _entry_exit_profiles(wallet_row,by_position,pool_cache=None,context_cache=None,
                         token_age_resolver=None):
    pool_cache={} if pool_cache is None else pool_cache
    context_cache={} if context_cache is None else context_cache
    profiles=[]
    positions={p.get("position"):p for p in wallet_row.get("positions") or []}
    for position,events in (wallet_row.get("histories") or {}).items():
        events=sorted(events,key=lambda e:(int(e.get("block_time") or 0),
                                           int(e.get("slot") or 0),
                                           int(e.get("ix_index") or 0)))
        adds=[e for e in events if e.get("event_type")=="add"]
        removes=[e for e in events if e.get("event_type")=="remove"]
        entry_event=adds[0] if adds else None
        exit_event=removes[-1] if removes else None
        entry_feature=None
        if entry_event is not None:
            feature=(by_position.get(position) or {}).get(entry_event.get("signature")) or {}
            entry_feature=feature.get("entry")
        entry_time=(entry_event or {}).get("block_time")
        pool=(entry_event or {}).get("pool") or (exit_event or {}).get("pool")
        context=(_market_context(
            pool,entry_time,pool_cache,context_cache,
            token_age_resolver=token_age_resolver)
                 if isinstance(pool,str) else
                 dict(status="unavailable",reason="missing_pool"))
        if entry_feature:
            entry_feature=dict(entry_feature)
            swap_fees=(by_position.get(position) or {}).get(
                entry_event.get("signature"),{}).get(
                    "swap_fee_bps_observed_in_transaction") or []
            entry_feature["entry_dynamic_fee_bps_observed"]=(
                None if not swap_fees else max(swap_fees))
            entry_feature["entry_dynamic_fee_reason"]=(
                None if swap_fees else
                "no_authenticated_same_transaction_swap_fee_observation")
        rebalances=[]
        for feature in (by_position.get(position) or {}).values():
            rebalances.extend(feature.get("rebalances") or [])
        p=positions.get(position) or {}
        exit_feature=(
            {} if exit_event is None else
            ((by_position.get(position) or {}).get(exit_event.get("signature")) or {})
        )
        remove_events=exit_feature.get("remove_events") or []
        exit_active=(remove_events[-1].get("active") if remove_events else None)
        lower=p.get("lower_bin_id");upper=p.get("upper_bin_id")
        exit_relation=None
        if isinstance(exit_active,int) and isinstance(lower,int) and isinstance(upper,int):
            exit_relation=dict(
                active_bin=exit_active,
                lower_active_offset_bins=lower-exit_active,
                upper_active_offset_bins=upper-exit_active,
                center_active_offset_bins=(lower+upper)/2.0-exit_active,
                active_inside_range=lower<=exit_active<=upper,
                range_source="meteora_closed_position_lower_upper",
            )
        profiles.append(dict(
            position=position,pool=pool,
            entry_time=entry_time,exit_time=(exit_event or {}).get("block_time"),
            hold_seconds=p.get("hold_seconds"),
            entry=entry_feature,market_context=context,
            rebalances=sorted(rebalances,key=lambda x:(
                x.get("active_bin",0),x.get("old_min_bin",0),x.get("new_min_bin",0))),
            rebalance_count=len(rebalances),
            exit_action=exit_feature.get("actions"),
            exit_active_bin=exit_active,
            exit_active_bin_relation=exit_relation,
            exit_active_bin_reason=(
                None if exit_active is not None
                else "authenticated_remove_liquidity_event_unavailable"),
        ))
    return profiles


def _deep_wallet(wallet_row,pool_cache=None,context_cache=None,
                 token_age_resolver=None):
    sigmap=_history_signature_map(wallet_row)
    transactions,pacer=_fetch_transactions(sigmap)
    by_position,tx_meta=_features_for_wallet(wallet_row,transactions)
    network=_network_costs(wallet_row,tx_meta)

    exact_rows=[];capital_exact=True;capital_hours=0.0
    for p in wallet_row.get("positions") or []:
        position=p.get("position")
        result=rec.exact_position_capital(
            p,wallet_row.get("histories",{}).get(position) or [],
            by_position.get(position) or {})
        exact_rows.append(dict(position=position,**result))
        if not result.get("exact"):
            capital_exact=False
        else:
            capital_hours+=float(result.get("capital_hours_usd") or 0.0)

    gross=float(wallet_row.get("api_realized_pnl_usd") or 0.0)
    after=(None if network["total_fee_usd"] is None
           else gross-network["total_fee_usd"])
    twr=rec.exact_simple_twr(
        wallet_row.get("positions") or [],
        wallet_row.get("histories") or {},
        network["position_cost_usd"])
    path=_after_cost_path(wallet_row,network)
    profiles=_entry_exit_profiles(
        wallet_row,by_position,pool_cache=pool_cache,context_cache=context_cache,
        token_age_resolver=token_age_resolver)
    fee_payers=sorted({
        meta.get("fee_payer") for meta in tx_meta.values()
        if isinstance(meta.get("fee_payer"),str)
    })
    return dict(
        wallet=wallet_row["wallet"],
        measured_closed_positions=wallet_row.get("measured_closed_positions"),
        distinct_pools=wallet_row.get("distinct_pools"),
        gross_realized_pnl_usd=gross,
        fee_income_usd=float(wallet_row.get("fee_income_usd") or 0.0),
        inventory_token_price_pnl_usd=float(
            wallet_row.get("inventory_token_price_pnl_usd") or 0.0),
        network_execution_cost=network,
        after_network_cost_pnl_usd=after,
        capital_at_risk_exact=capital_exact,
        capital_hours_usd=(capital_hours if capital_exact else None),
        after_cost_pnl_per_capital_hour=(
            None if after is None or not capital_exact or capital_hours<=0
            else after/capital_hours),
        exact_position_capital=exact_rows,
        exact_time_weighted_return=twr,
        profitable_position_rate=wallet_row.get("profitable_position_rate"),
        **path,
        gross_max_realized_drawdown_usd=wallet_row.get("max_realized_drawdown_usd"),
        gross_profitable_active_week_rate=wallet_row.get("profitable_active_week_rate"),
        fee_payers=fee_payers,
        entry_exit_profiles=profiles,
        rpc_pacing=pacer,
    )


def _rank(rows):
    def sorted_metric(key,descending=True,eligible=lambda r:True):
        valid=[r for r in rows if r.get(key) is not None and eligible(r)]
        return sorted(valid,key=lambda r:(
            -float(r[key]) if descending else float(r[key]),r["wallet"]))
    return dict(
        absolute_after_network_cost_pnl_usd=sorted_metric(
            "after_network_cost_pnl_usd"),
        after_cost_pnl_per_capital_hour=sorted_metric(
            "after_cost_pnl_per_capital_hour"),
        exact_time_weighted_return=sorted(
            [r for r in rows if (r.get("exact_time_weighted_return") or {}).get("available")],
            key=lambda r:(-float(r["exact_time_weighted_return"]["twr"]),r["wallet"])),
        profitable_position_rate=sorted_metric("profitable_position_rate"),
        max_after_cost_realized_drawdown_usd=sorted_metric(
            "max_after_cost_realized_drawdown_usd",descending=False),
        profitable_after_cost_active_week_rate=sorted_metric(
            "profitable_after_cost_active_week_rate"),
    )


def run(path=DEFAULT_RANKING):
    ranking=json.loads(Path(path).read_text())
    if ranking.get("kind")!="dlmm_profitable_operator_ranking_v1":
        raise RuntimeError("dlmm_operator_deep_ranking_kind")
    wallets=ranking.get("deep_reconstruction_wallets") or []
    by_wallet={r.get("wallet"):r for r in ranking.get("all_wallets") or []}
    if any(w not in by_wallet for w in wallets):
        raise RuntimeError("dlmm_operator_deep_wallet_rows_missing")
    signature=_signature(ranking);rows,failures=_load_checkpoint(signature)
    started=int(time.time())
    _write_checkpoint(signature,rows,failures,started)
    pool_cache={};context_cache={}
    token_age_resolver=TokenAgeResolver()
    for index,wallet in enumerate(wallets,1):
        if wallet in rows:
            continue
        try:
            rows[wallet]=_deep_wallet(
                by_wallet[wallet],pool_cache=pool_cache,context_cache=context_cache,
                token_age_resolver=token_age_resolver)
            failures.pop(wallet,None);state="completed"
        except Exception as exc:
            failures[wallet]=dict(error=type(exc).__name__,message=str(exc)[:160])
            state="failed"
        _write_checkpoint(signature,rows,failures,started)
        print(json.dumps(dict(
            phase="deep_wallet",wallet=wallet,index=index,total=len(wallets),
            state=state,completed=len(rows),failed=len(failures)),
            sort_keys=True),flush=True)
    if failures:
        raise RuntimeError(f"dlmm_operator_deep_incomplete:{len(failures)}")
    data=[rows[w] for w in wallets]
    rankings=_rank(data)
    clusters=rec.cluster_fleets(data)
    report=dict(
        kind="dlmm_profitable_operator_deep_reconstruction_v1",
        status="deep_reconstruction_complete_rule_derivation_not_yet_frozen",
        protocol_sha256=ranking.get("protocol_sha256"),
        cohort_hash=ranking.get("cohort_hash"),
        wallet_count=len(data),
        capital_exact_wallet_count=sum(bool(r.get("capital_at_risk_exact")) for r in data),
        network_cost_usd_complete_wallet_count=sum(
            (r.get("network_execution_cost") or {}).get("fee_usd_complete",False)
            for r in data),
        exact_twr_wallet_count=sum(
            (r.get("exact_time_weighted_return") or {}).get("available",False)
            for r in data),
        rankings={
            name:[
                dict(
                    wallet=r["wallet"],
                    value=(r["exact_time_weighted_return"]["twr"]
                           if name=="exact_time_weighted_return" else r.get(name)),
                    positions=r.get("measured_closed_positions"),
                    pools=r.get("distinct_pools"),
                )
                for r in values
            ]
            for name,values in rankings.items()
        },
        operator_clusters=clusters,
        wallets=data,
    )
    _atomic(OUT,report)
    print(json.dumps(dict(
        wallets=len(data),clusters=len(clusters),
        exact_capital=report["capital_exact_wallet_count"],
        exact_twr=report["exact_twr_wallet_count"]),
        sort_keys=True))
    return report


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--ranking",default=str(DEFAULT_RANKING))
    args=p.parse_args();run(Path(args.ranking))


if __name__=="__main__":
    main()
