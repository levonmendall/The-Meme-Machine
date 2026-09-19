"""TVL-stratified DLMM profitability study for the frozen 200-wallet cohort.

Consumes the completed profitable-operator ranking/deep artifacts. It does not select
new wallets or change any strategy threshold. Point-in-time entry TVL is reconstructed
from authenticated reserve pre-balances; missing history is reported unavailable.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import threading
import time

from meme_machine import dlmm, pump
from meme_machine.dlmm_tape import _keys
from tests import dlmm_alchemy_provider as provider
from tests import dlmm_profitable_operator_discovery as op

PROTOCOL=Path("DLMM_SMALL_POOL_PROFITABILITY_STUDY_V1.json")
DEFAULT_RANKING=Path("dlmm-profitable-operator-ranking.json")
DEFAULT_DEEP=Path("dlmm-profitable-operator-deep-reconstruction.json")
CHECKPOINT=Path("dlmm-small-pool-profitability-checkpoint.json")
OUT=Path("dlmm-small-pool-profitability.json")

MAX_PRIOR_SIGNATURES=32
MAX_PRIOR_SECONDS=120
DEFAULT_WORKERS=4
MAX_WORKERS=4
WHOLE_WALLET_ATTEMPTS=2

TVL_BUCKETS=(
    ("<10k",0.0,10000.0),
    ("10-25k",10000.0,25000.0),
    ("25-50k",25000.0,50000.0),
    (">=50k",50000.0,None),
)
AGE_BUCKETS=(
    ("<1h",0.0,3600.0),
    ("1-6h",3600.0,21600.0),
    ("6-24h",21600.0,86400.0),
    ("1-7d",86400.0,604800.0),
    (">=7d",604800.0,None),
)
VOL_BUCKETS=(
    ("<1pct",0.0,0.01),
    ("1-3pct",0.01,0.03),
    ("3-10pct",0.03,0.10),
    (">=10pct",0.10,None),
)


def _atomic(path,body):
    path=Path(path);tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(body,indent=2,sort_keys=True)+"\n")
    tmp.replace(path)


def _protocol_hash():
    return hashlib.sha256(PROTOCOL.read_bytes()).hexdigest()


def _bucket(value,rules):
    if value is None:return None
    x=float(value)
    for label,lo,hi in rules:
        if x>=lo and (hi is None or x<hi):
            return label
    return None


def _finite(value):
    try:
        x=float(value)
    except (TypeError,ValueError):
        return None
    return x if math.isfinite(x) else None


class SafePacer(provider.AlchemyPacer):
    def __init__(self):
        super().__init__();self._guard=threading.Lock()
    def pace(self,rpc,requested_interval=0.5):
        with self._guard:
            return super().pace(rpc,requested_interval)


class EntryTVLResolver:
    def __init__(self):
        self.pacer=SafePacer()
        self.local=threading.local()
        self.cache_lock=threading.Lock()
        self.identity_cache={}
        self.detail_cache={}
        self.ohlcv_cache={}

    def _rpc(self):
        rpc=getattr(self.local,"rpc",None)
        if rpc is None or int(getattr(rpc,"calls",0))>=180:
            rpc=provider.new_rpc(limit=220,pacer=self.pacer)
            self.local.rpc=rpc
        return rpc

    def pool_identity(self,pool):
        with self.cache_lock:
            prior=self.identity_cache.get(pool)
        if prior is not None:return prior
        result=self._rpc().call("getAccountInfo",[
            pool,dict(encoding="base64",commitment="finalized")
        ],True,True)
        account=result.get("value") if isinstance(result,dict) else None
        raw=pump.raw_account(account,dlmm.PROGRAM,"LbPair")
        if len(raw)!=904:
            raise RuntimeError("dlmm_small_pool_lbpair_layout")
        identity=dict(
            x=pump.b58(raw[88:120]),y=pump.b58(raw[120:152]),
            vault_x=pump.b58(raw[152:184]),vault_y=pump.b58(raw[184:216]),
        )
        with self.cache_lock:self.identity_cache[pool]=identity
        return identity

    def pool_detail(self,pool):
        with self.cache_lock:
            prior=self.detail_cache.get(pool)
        if prior is not None:return prior
        payload=op._api(f"/pools/{pool}")
        detail=(payload.get("data") if isinstance(payload,dict)
                and isinstance(payload.get("data"),dict) else payload)
        if not isinstance(detail,dict):
            raise RuntimeError("dlmm_small_pool_detail_shape")
        if detail.get("address") not in (None,pool):
            raise RuntimeError("dlmm_small_pool_detail_identity")
        with self.cache_lock:self.detail_cache[pool]=detail
        return detail

    @staticmethod
    def _display_balance(row):
        token=(row or {}).get("uiTokenAmount") or {}
        amount=token.get("amount");decimals=token.get("decimals")
        if not isinstance(amount,str) or not amount.isdigit() or not isinstance(decimals,int):
            return None
        return int(amount)/(10**decimals),decimals

    def reserve_balances(self,tx,identity):
        if not isinstance(tx,dict) or not isinstance(tx.get("meta"),dict):
            return None
        meta=tx["meta"];message=(tx.get("transaction") or {}).get("message") or {}
        try: keys=_keys(meta,message)
        except Exception:return None
        try:
            ix=keys.index(identity["vault_x"]);iy=keys.index(identity["vault_y"])
        except ValueError:
            return None
        pre=meta.get("preTokenBalances") or []
        xr=[r for r in pre if r.get("accountIndex")==ix and r.get("mint")==identity["x"]]
        yr=[r for r in pre if r.get("accountIndex")==iy and r.get("mint")==identity["y"]]
        if len(xr)!=1 or len(yr)!=1:return None
        x=self._display_balance(xr[0]);y=self._display_balance(yr[0])
        if x is None or y is None:return None
        return dict(
            x_amount=x[0],y_amount=y[0],x_decimals=x[1],y_decimals=y[1],
            block_time=tx.get("blockTime"),slot=tx.get("slot"),
        )

    def transaction(self,signature):
        return self._rpc().call("getTransaction",[
            signature,dict(
                encoding="json",commitment="finalized",
                maxSupportedTransactionVersion=1,
            )
        ],True,True)

    def immediately_prior_success(self,pool,entry_signature,entry_time,identity):
        rows=self._rpc().call("getSignaturesForAddress",[
            pool,dict(
                before=entry_signature,limit=MAX_PRIOR_SIGNATURES,
                commitment="finalized")
        ],True,True)
        if not isinstance(rows,list):
            return None,"prior_signature_shape"
        first=None
        for row in rows:
            if not isinstance(row,dict) or row.get("err") is not None:
                continue
            first=row;break
        if first is None:
            return None,"no_prior_successful_pool_transaction"
        block_time=first.get("blockTime")
        if not isinstance(block_time,int) or entry_time-block_time<0 or entry_time-block_time>MAX_PRIOR_SECONDS:
            return None,"prior_successful_pool_transaction_too_old"
        tx=self.transaction(first.get("signature"))
        balances=self.reserve_balances(tx,identity)
        if balances is None:
            return None,"immediate_prior_success_does_not_expose_both_reserves"
        return balances,None

    def ohlcv_close(self,pool,entry_time):
        key=(pool,int(entry_time)//300)
        with self.cache_lock:
            if key in self.ohlcv_cache:return self.ohlcv_cache[key]
        payload=op._api(f"/pools/{pool}/ohlcv",dict(
            timeframe="5m",start_time=max(0,int(entry_time)-3600),
            end_time=max(0,int(entry_time)-1)))
        data=payload.get("data") if isinstance(payload,dict) else None
        closes=[]
        if isinstance(data,list):
            for row in data:
                if not isinstance(row,dict):continue
                ts=row.get("timestamp");close=_finite(row.get("close"))
                if isinstance(ts,int) and ts<entry_time and close is not None and close>0:
                    closes.append((ts,close))
        result=None if not closes else max(closes)[1]
        with self.cache_lock:self.ohlcv_cache[key]=result
        return result

    @staticmethod
    def _price_candidates(amount,usd,decimals):
        amount=_finite(amount);usd=_finite(usd)
        if amount is None or usd is None or amount<=0 or usd<=0:return []
        values=[usd/amount]
        if isinstance(decimals,int) and decimals>=0:
            display=amount/(10**decimals)
            if display>0:values.append(usd/display)
        out=[]
        for value in values:
            if value>0 and math.isfinite(value) and all(
                    abs(value/x-1)>1e-10 for x in out):
                out.append(value)
        return out

    def prices(self,event,detail,balances,pool,entry_time):
        tx=(detail.get("token_x") or {}) if isinstance(detail,dict) else {}
        ty=(detail.get("token_y") or {}) if isinstance(detail,dict) else {}
        x_mint=tx.get("address") or event.get("token_x")
        y_mint=ty.get("address") or event.get("token_y")
        x_dec=tx.get("decimals")
        y_dec=ty.get("decimals")
        if not isinstance(x_dec,int):x_dec=balances.get("x_decimals")
        if not isinstance(y_dec,int):y_dec=balances.get("y_decimals")
        xc=self._price_candidates(event.get("amount_x"),event.get("amount_x_usd"),x_dec)
        yc=self._price_candidates(event.get("amount_y"),event.get("amount_y_usd"),y_dec)
        close=self.ohlcv_close(pool,entry_time)
        pairs=[]
        if xc and yc:
            pairs=[(x,y,"event_both") for x in xc for y in yc]
        elif xc and close:
            pairs=[(x,x/close,"event_x_plus_ohlcv") for x in xc]
        elif yc and close:
            pairs=[(close*y,y,"event_y_plus_ohlcv") for y in yc]
        else:
            return None,"point_in_time_token_prices_unavailable"
        valid=[]
        for px,py,source in pairs:
            if min(px,py)<=0:continue
            sol=(px if x_mint==dlmm.WSOL else py if y_mint==dlmm.WSOL else None)
            if sol is None or not 1.0<=sol<=10000.0:
                continue
            if close is not None and abs((px/py)/close-1.0)>0.20:
                continue
            valid.append((px,py,source))
        # collapse numerically equivalent alternatives caused by duplicate unit candidates
        unique=[]
        for row in valid:
            if not any(abs(row[0]/x[0]-1)<1e-8 and abs(row[1]/x[1]-1)<1e-8 for x in unique):
                unique.append(row)
        if len(unique)!=1:
            return None,"ambiguous_point_in_time_token_prices"
        px,py,source=unique[0]
        return dict(x_usd=px,y_usd=py,ohlcv_close=close,source=source),None

    def resolve(self,pool,event,entry_time):
        if not isinstance(pool,str) or not isinstance(entry_time,int):
            return dict(available=False,reason="missing_pool_or_entry_time")
        signature=event.get("signature")
        if not isinstance(signature,str) or not signature:
            return dict(available=False,reason="missing_entry_signature")
        try:
            identity=self.pool_identity(pool)
            detail=self.pool_detail(pool)
            tx=self.transaction(signature)
            balances=self.reserve_balances(tx,identity)
            source="entry_transaction_pre_balances"
            if balances is None:
                balances,reason=self.immediately_prior_success(
                    pool,signature,entry_time,identity)
                if balances is None:
                    return dict(available=False,reason=reason)
                source="immediately_prior_successful_pool_transaction_pre_balances"
            prices,reason=self.prices(event,detail,balances,pool,entry_time)
            if prices is None:
                return dict(available=False,reason=reason)
            tvl=balances["x_amount"]*prices["x_usd"]+balances["y_amount"]*prices["y_usd"]
            if not math.isfinite(tvl) or tvl<0:
                return dict(available=False,reason="invalid_reconstructed_tvl")
            return dict(
                available=True,entry_tvl_usd=tvl,tvl_bucket=_bucket(tvl,TVL_BUCKETS),
                balance_source=source,balance_slot=balances.get("slot"),
                balance_block_time=balances.get("block_time"),
                price_source=prices["source"],ohlcv_close=prices.get("ohlcv_close"),
            )
        except Exception as exc:
            return dict(available=False,reason=type(exc).__name__)


def _signature(ranking,deep,profitable):
    return dict(
        protocol_sha256=_protocol_hash(),
        cohort_hash=ranking.get("cohort_hash"),
        deep_cohort_hash=deep.get("cohort_hash"),
        profitable_wallets=sorted(profitable),
        tvl_buckets=[x[0] for x in TVL_BUCKETS],
        max_prior_seconds=MAX_PRIOR_SECONDS,
        max_prior_signatures=MAX_PRIOR_SIGNATURES,
    )


def _load_checkpoint(signature):
    if not CHECKPOINT.exists():return {}
    body=json.loads(CHECKPOINT.read_text())
    if body.get("kind")!="dlmm_small_pool_profitability_checkpoint_v1" or body.get("signature")!=signature:
        raise RuntimeError("dlmm_small_pool_checkpoint_mismatch")
    rows=body.get("wallets") or {}
    if not isinstance(rows,dict):raise RuntimeError("dlmm_small_pool_checkpoint_shape")
    return rows


def _write_checkpoint(signature,rows,started):
    _atomic(CHECKPOINT,dict(
        kind="dlmm_small_pool_profitability_checkpoint_v1",
        status=("complete" if len(rows)==len(signature["profitable_wallets"]) else "partial"),
        signature=signature,started_at=started,updated_at=int(time.time()),
        completed_wallets=len(rows),wallets=rows,
    ))


def _entry_event(history):
    rows=sorted(history,key=lambda e:(
        int(e.get("block_time") or 0),int(e.get("slot") or 0),int(e.get("ix_index") or 0)))
    for event in rows:
        if event.get("event_type")=="add":
            return event
    return None


def _wallet_rows(rank_wallet,deep_wallet,resolver):
    positions={p.get("position"):p for p in rank_wallet.get("positions") or []}
    histories=rank_wallet.get("histories") or {}
    profiles={p.get("position"):p for p in deep_wallet.get("entry_exit_profiles") or []}
    position_cost=(deep_wallet.get("network_execution_cost") or {}).get("position_cost_usd") or {}
    rows=[]
    for position,p in positions.items():
        if not isinstance(position,str):continue
        profile=profiles.get(position) or {}
        history=histories.get(position) or []
        event=_entry_event(history)
        pool=profile.get("pool") or (event or {}).get("pool") or p.get("pool")
        entry_time=profile.get("entry_time") or (event or {}).get("block_time")
        tvl=(resolver.resolve(pool,event,entry_time)
             if event is not None else dict(available=False,reason="missing_entry_add_event"))
        market=profile.get("market_context") or {}
        age=market.get("pool_age_seconds")
        vol=market.get("pre_entry_5m_log_return_volatility")
        cost=position_cost.get(position)
        gross=float(p.get("pnl_usd") or 0.0)
        after=(gross-float(cost) if isinstance(cost,(int,float)) else None)
        rows.append(dict(
            position=position,pool=pool,entry_time=entry_time,
            entry_tvl=tvl,tvl_bucket=tvl.get("tvl_bucket"),
            pool_age_seconds=age,pool_age_bucket=_bucket(age,AGE_BUCKETS),
            pre_entry_volatility=vol,volatility_bucket=_bucket(vol,VOL_BUCKETS),
            deposit_usd=float(p.get("deposit_usd") or 0.0),
            realized_pnl_usd=gross,
            network_cost_usd=(float(cost) if isinstance(cost,(int,float)) else None),
            after_network_cost_position_pnl_usd=after,
            fee_income_usd=float(p.get("fee_usd") or 0.0),
            inventory_token_price_pnl_usd=gross-float(p.get("fee_usd") or 0.0),
            pnl_pct=float(p.get("pnl_pct") or 0.0),
        ))
    return dict(
        wallet=rank_wallet["wallet"],
        after_network_cost_pnl_usd=deep_wallet.get("after_network_cost_pnl_usd"),
        position_count=len(rows),positions=rows,
    )


def _wallet_with_retry(rank_wallet,deep_wallet,resolver):
    last=None
    for attempt in range(WHOLE_WALLET_ATTEMPTS):
        try:return _wallet_rows(rank_wallet,deep_wallet,resolver)
        except Exception as exc:
            last=exc
            if attempt+1<WHOLE_WALLET_ATTEMPTS:time.sleep(1)
    raise last


def _aggregate(rows):
    bucket_rows=defaultdict(list);missing=Counter()
    operator_bucket=defaultdict(lambda:defaultdict(float))
    cross=defaultdict(lambda:dict(
        positions=0,operators=set(),pnl=0.0,deposit=0.0,fees=0.0))
    for wallet_row in rows:
        wallet=wallet_row["wallet"]
        for p in wallet_row["positions"]:
            bucket=p.get("tvl_bucket")
            if bucket is None:
                missing[(p.get("entry_tvl") or {}).get("reason") or "unknown"]+=1
                continue
            bucket_rows[bucket].append((wallet,p))
            operator_bucket[wallet][bucket]+=p["realized_pnl_usd"]
            key=(bucket,p.get("pool_age_bucket"),p.get("volatility_bucket"))
            c=cross[key];c["positions"]+=1;c["operators"].add(wallet)
            c["pnl"]+=p["realized_pnl_usd"];c["deposit"]+=p["deposit_usd"]
            c["fees"]+=p["fee_income_usd"]
    by_tvl={}
    for label,_,_ in TVL_BUCKETS:
        data=bucket_rows.get(label,[])
        positions=[p for _w,p in data]
        operators=sorted({w for w,_p in data})
        pnl=sum(p["realized_pnl_usd"] for p in positions)
        dep=sum(p["deposit_usd"] for p in positions)
        exact_after=[p for p in positions if p["after_network_cost_position_pnl_usd"] is not None]
        after=sum(p["after_network_cost_position_pnl_usd"] for p in exact_after)
        wins=sum(p["realized_pnl_usd"]>0 for p in positions)
        op_positive=sum(operator_bucket[w][label]>0 for w in operators)
        by_tvl[label]=dict(
            position_count=len(positions),distinct_operator_count=len(operators),
            deployed_deposit_usd=dep,realized_pnl_usd=pnl,
            after_network_cost_attributable_pnl_usd=after,
            after_network_cost_attributable_position_count=len(exact_after),
            fee_income_usd=sum(p["fee_income_usd"] for p in positions),
            inventory_token_price_pnl_usd=sum(
                p["inventory_token_price_pnl_usd"] for p in positions),
            profitable_position_rate=(None if not positions else wins/len(positions)),
            median_position_pnl_pct=(None if not positions else statistics.median(
                p["pnl_pct"] for p in positions)),
            pnl_per_deployed_dollar=(None if dep<=0 else pnl/dep),
            operator_share_with_positive_stratum_pnl=(
                None if not operators else op_positive/len(operators)),
        )
    cross_rows=[]
    for (tvl,age,vol),c in sorted(cross.items(),key=lambda x:tuple(str(v) for v in x[0])):
        cross_rows.append(dict(
            tvl_bucket=tvl,pool_age_bucket=age,volatility_bucket=vol,
            position_count=c["positions"],distinct_operator_count=len(c["operators"]),
            realized_pnl_usd=c["pnl"],deployed_deposit_usd=c["deposit"],
            fee_income_usd=c["fees"],
            pnl_per_deployed_dollar=(None if c["deposit"]<=0 else c["pnl"]/c["deposit"]),
        ))
    return by_tvl,cross_rows,dict(sorted(missing.items()))


def run(ranking_path=DEFAULT_RANKING,deep_path=DEFAULT_DEEP):
    ranking=json.loads(Path(ranking_path).read_text())
    deep=json.loads(Path(deep_path).read_text())
    if ranking.get("kind")!="dlmm_profitable_operator_ranking_v1":
        raise RuntimeError("dlmm_small_pool_ranking_kind")
    if deep.get("kind")!="dlmm_profitable_operator_deep_reconstruction_v1":
        raise RuntimeError("dlmm_small_pool_deep_kind")
    if ranking.get("cohort_hash")!=deep.get("cohort_hash"):
        raise RuntimeError("dlmm_small_pool_cohort_mismatch")
    protocol=json.loads(PROTOCOL.read_text())
    if ranking.get("cohort_hash")!=protocol["source_cohort"]["cohort_hash"]:
        raise RuntimeError("dlmm_small_pool_frozen_cohort_mismatch")
    rank_by={r.get("wallet"):r for r in ranking.get("all_wallets") or []}
    deep_by={r.get("wallet"):r for r in deep.get("wallets") or []}
    profitable=sorted(
        w for w,row in deep_by.items()
        if isinstance(w,str)
        and int(row.get("measured_closed_positions") or 0)>=20
        and int(row.get("distinct_pools") or 0)>=3
        and isinstance(row.get("after_network_cost_pnl_usd"),(int,float))
        and float(row["after_network_cost_pnl_usd"])>0
        and w in rank_by
    )
    if not profitable:
        raise RuntimeError("dlmm_small_pool_no_final_profitable_operators")
    signature=_signature(ranking,deep,profitable)
    rows=_load_checkpoint(signature);started=int(time.time())
    _write_checkpoint(signature,rows,started)
    resolver=EntryTVLResolver()
    pending=[w for w in profitable if w not in rows]
    workers=int(os.environ.get("DLMM_SMALL_POOL_WORKERS",DEFAULT_WORKERS))
    if not 1<=workers<=MAX_WORKERS:raise RuntimeError("dlmm_small_pool_worker_bound")
    with ThreadPoolExecutor(max_workers=min(workers,max(1,len(pending))),
                            thread_name_prefix="dlmm-small-pool") as executor:
        future_map={
            executor.submit(_wallet_with_retry,rank_by[w],deep_by[w],resolver):w
            for w in pending
        }
        for future in as_completed(future_map):
            wallet=future_map[future]
            rows[wallet]=future.result()
            _write_checkpoint(signature,rows,started)
            resolved=sum(
                bool(p.get("entry_tvl",{}).get("available"))
                for p in rows[wallet]["positions"])
            print(json.dumps(dict(
                phase="small_pool_wallet",wallet=wallet,
                completed_wallets=len(rows),total_wallets=len(profitable),
                positions=rows[wallet]["position_count"],resolved_tvl=resolved,
            ),sort_keys=True),flush=True)
    ordered=[rows[w] for w in profitable]
    by_tvl,cross,missing=_aggregate(ordered)
    all_positions=[p for r in ordered for p in r["positions"]]
    resolved=sum(bool(p.get("entry_tvl",{}).get("available")) for p in all_positions)
    report=dict(
        kind="dlmm_small_pool_profitability_study_v1",
        status="descriptive_complete_no_strategy_threshold_changed",
        protocol_sha256=signature["protocol_sha256"],
        cohort_hash=ranking.get("cohort_hash"),
        final_profitable_operator_count=len(profitable),
        final_profitable_operators=profitable,
        measured_position_count=len(all_positions),
        entry_tvl_resolved_position_count=resolved,
        entry_tvl_resolution_rate=(None if not all_positions else resolved/len(all_positions)),
        entry_tvl_unavailable_reasons=missing,
        by_tvl_stratum=by_tvl,
        tvl_age_volatility_cross_classification=cross,
        wallets=ordered,
        provider=dict(
            topology="public_solana_ws_not_used_in_historical_study__direct_alchemy_http",
            alchemy_pacing=resolver.pacer.telemetry(),
        ),
        interpretation_guardrails=dict(
            current_50000_tvl_execution_gate_changed=False,
            descriptive_only=True,
            no_best_bucket_strategy_selection=True,
            current_tvl_never_substituted_for_entry_tvl=True,
        ),
    )
    _atomic(OUT,report)
    print(json.dumps(dict(
        operators=len(profitable),positions=len(all_positions),resolved_tvl=resolved,
        by_tvl={k:dict(
            positions=v["position_count"],pnl=v["realized_pnl_usd"],
            deposit=v["deployed_deposit_usd"])
            for k,v in by_tvl.items()},
    ),sort_keys=True))
    return report


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--ranking",default=str(DEFAULT_RANKING))
    p.add_argument("--deep",default=str(DEFAULT_DEEP))
    args=p.parse_args();run(Path(args.ranking),Path(args.deep))


if __name__=="__main__":
    main()
