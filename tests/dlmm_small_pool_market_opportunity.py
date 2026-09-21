"""Wallet-independent DLMM small-pool market opportunity study.

This test never reads wallet PnL or profitable-operator labels. It compares current
gross LP opportunity density across fixed TVL strata and freezes that result for later
comparison with the separately completed 200-wallet operator study.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import statistics
import threading
import time
from datetime import datetime, timezone
import urllib.parse
import urllib.request

from meme_machine import dlmm
from tests import dlmm_wallet_strategy_discovery as api

PROTOCOL=Path("DLMM_SMALL_POOL_MARKET_OPPORTUNITY_V1.json")
CHECKPOINT=Path("dlmm-small-pool-market-volatility-checkpoint.json")
OUT=Path("dlmm-small-pool-market-opportunity.json")

API_BASE=api.API_BASE
PAGE_SIZE=1000
MAX_PAGES=512  # Safety ceiling; low-TVL Meteora strata can exceed 100 API pages.
VOL_SAMPLE_PER_BUCKET=60
API_RPS=12

BUCKETS=(
    ("<10k",0.0,10000.0),
    ("10-25k",10000.0,25000.0),
    ("25-50k",25000.0,50000.0),
    (">=50k",50000.0,None),
)


class Pacer:
    def __init__(self,rps=API_RPS):
        self.interval=1.0/float(rps);self.next=0.0;self.lock=threading.Lock()
    def pace(self):
        with self.lock:
            now=time.monotonic();wait=max(0.0,self.next-now)
            if wait:time.sleep(wait);now=time.monotonic()
            self.next=max(now,self.next)+self.interval


PACER=Pacer()


def _get(path,params=None):
    PACER.pace()
    url=API_BASE+path
    if params:url+="?"+urllib.parse.urlencode(params)
    req=urllib.request.Request(url,headers={
        "Accept":"application/json",
        "User-Agent":"meme-machine-dlmm-small-pool-market-study/1",
    })
    with urllib.request.urlopen(req,timeout=30) as response:
        if response.status!=200:
            raise RuntimeError(f"dlmm_small_pool_market_http:{response.status}")
        return json.loads(response.read())


def _num(value):
    try:x=float(value)
    except (TypeError,ValueError):return None
    return x if math.isfinite(x) else None



def _timestamp(value):
    if isinstance(value,bool):
        return None
    if isinstance(value,(int,float)):
        x=int(value)
        # Millisecond timestamps are accepted only after explicit normalization.
        if x>10_000_000_000:
            x//=1000
        return x if x>=0 else None
    if isinstance(value,str):
        raw=value.strip()
        if not raw:
            return None
        try:
            x=float(raw)
        except ValueError:
            x=None
        if x is not None and math.isfinite(x):
            out=int(x)
            if out>10_000_000_000:
                out//=1000
            return out if out>=0 else None
        try:
            parsed=datetime.fromisoformat(raw.replace("Z","+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed=parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp())
    return None


def _exact_sol_pair(row):
    x=(row.get("token_x") or {}).get("address")
    y=(row.get("token_y") or {}).get("address")
    return (x==dlmm.WSOL) ^ (y==dlmm.WSOL)


def _filter(label):
    if label=="<10k":return "is_blacklisted=false && tvl<10000"
    if label=="10-25k":return "is_blacklisted=false && tvl>=10000 && tvl<25000"
    if label=="25-50k":return "is_blacklisted=false && tvl>=25000 && tvl<50000"
    if label==">=50k":return "is_blacklisted=false && tvl>=50000"
    raise ValueError(label)


def census_bucket(label):
    out=[];seen=set();api_total=None;api_pages=None
    for page in range(1,MAX_PAGES+1):
        payload=_get("/pools",dict(
            page=page,page_size=PAGE_SIZE,sort_by="tvl:desc",
            filter_by=_filter(label),
        ))
        rows=payload.get("data") if isinstance(payload,dict) else None
        if not isinstance(rows,list):
            raise RuntimeError("dlmm_small_pool_market_pool_shape")
        if api_total is None:
            api_total=payload.get("total")
            api_pages=payload.get("pages")
        for row in rows:
            if not isinstance(row,dict) or not _exact_sol_pair(row):continue
            address=row.get("address")
            if not isinstance(address,str) or address in seen:continue
            seen.add(address)
            tvl=_num(row.get("tvl"))
            volume=_num((row.get("volume") or {}).get("24h"))
            fees=_num((row.get("fees") or {}).get("24h"))
            dynamic=_num(row.get("dynamic_fee_pct"))
            created=_timestamp(row.get("created_at"))
            out.append(dict(
                address=address,name=row.get("name"),tvl_usd=tvl,
                volume_24h_usd=volume,fees_24h_usd=fees,
                dynamic_fee_pct=dynamic,created_at=created,
                token_x=(row.get("token_x") or {}).get("symbol"),
                token_y=(row.get("token_y") or {}).get("symbol"),
            ))
        final=(isinstance(api_pages,int) and page>=api_pages) or len(rows)<PAGE_SIZE
        if final:
            return out,dict(
                complete=True,pages_read=page,api_pages=api_pages,
                api_total_before_sol_filter=api_total,
            )
    return out,dict(
        complete=False,pages_read=MAX_PAGES,api_pages=api_pages,
        api_total_before_sol_filter=api_total,
    )


def _quantile(values,q):
    xs=sorted(float(x) for x in values if x is not None and math.isfinite(float(x)))
    if not xs:return None
    if len(xs)==1:return xs[0]
    p=(len(xs)-1)*float(q);lo=int(math.floor(p));hi=int(math.ceil(p))
    if lo==hi:return xs[lo]
    return xs[lo]+(xs[hi]-xs[lo])*(p-lo)


def _age_bucket(seconds):
    if seconds is None:return None
    if seconds<3600:return "<1h"
    if seconds<21600:return "1-6h"
    if seconds<86400:return "6-24h"
    if seconds<604800:return "1-7d"
    return ">=7d"


def summarize_bucket(rows,observed_at):
    fee_density=[];volume_density=[];dynamic=[];ages=[];age_counts=Counter()
    active=0;total_tvl=0.0;total_volume=0.0;total_fees=0.0
    for r in rows:
        tvl=r["tvl_usd"];vol=r["volume_24h_usd"];fees=r["fees_24h_usd"]
        if tvl is not None:total_tvl+=tvl
        if vol is not None:
            total_volume+=vol
            if vol>0:active+=1
        if fees is not None:total_fees+=fees
        if tvl is not None and tvl>0:
            if vol is not None:volume_density.append(vol/tvl)
            if fees is not None:fee_density.append(fees/tvl)
        if r["dynamic_fee_pct"] is not None:dynamic.append(r["dynamic_fee_pct"])
        created=r.get("created_at")
        age=(observed_at-created if isinstance(created,int) and created<=observed_at else None)
        if age is not None:
            ages.append(age);age_counts[_age_bucket(age)]+=1
    n_age=len(ages)
    return dict(
        pool_count=len(rows),active_volume_pool_count=active,
        total_tvl_usd=total_tvl,total_volume_24h_usd=total_volume,
        total_fees_24h_usd=total_fees,
        median_volume_to_tvl_24h=_quantile(volume_density,0.50),
        median_fee_to_tvl_24h=_quantile(fee_density,0.50),
        p75_fee_to_tvl_24h=_quantile(fee_density,0.75),
        p90_fee_to_tvl_24h=_quantile(fee_density,0.90),
        p95_fee_to_tvl_24h=_quantile(fee_density,0.95),
        profitable_capacity_proxy_fees_per_1000_tvl_24h=(
            None if total_tvl<=0 else total_fees/total_tvl*1000.0),
        median_dynamic_fee_pct=_quantile(dynamic,0.50),
        median_pool_age_seconds=_quantile(ages,0.50),
        pool_age_distribution=dict(sorted(age_counts.items())),
        share_age_lt_1h=(None if not n_age else sum(x<3600 for x in ages)/n_age),
        share_age_lt_6h=(None if not n_age else sum(x<21600 for x in ages)/n_age),
        share_age_lt_24h=(None if not n_age else sum(x<86400 for x in ages)/n_age),
    )


def _sample(rows):
    eligible=[r for r in rows if (r.get("volume_24h_usd") or 0)>0]
    eligible.sort(key=lambda r:hashlib.sha256(r["address"].encode()).hexdigest())
    return eligible[:VOL_SAMPLE_PER_BUCKET]


def _checkpoint_signature(snapshot_hash):
    return dict(
        protocol_sha256=hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
        snapshot_hash=snapshot_hash,sample_size=VOL_SAMPLE_PER_BUCKET,
        timeframe="5m",lookback_seconds=3600,
    )


def _load_checkpoint(signature):
    if not CHECKPOINT.exists():return {}
    body=json.loads(CHECKPOINT.read_text())
    if body.get("kind")!="dlmm_small_pool_market_volatility_checkpoint_v1":
        raise RuntimeError("dlmm_small_pool_market_checkpoint_kind")
    if body.get("signature")!=signature:
        raise RuntimeError("dlmm_small_pool_market_checkpoint_mismatch")
    rows=body.get("pools") or {}
    if not isinstance(rows,dict):
        raise RuntimeError("dlmm_small_pool_market_checkpoint_shape")
    return rows


def _save_checkpoint(signature,rows):
    body=dict(
        kind="dlmm_small_pool_market_volatility_checkpoint_v1",
        signature=signature,updated_at=int(time.time()),pools=rows,
    )
    tmp=CHECKPOINT.with_suffix(".tmp")
    tmp.write_text(json.dumps(body,indent=2,sort_keys=True)+"\n");tmp.replace(CHECKPOINT)


def volatility(pool,observed_at):
    payload=_get(f"/pools/{pool}/ohlcv",dict(
        timeframe="5m",start_time=max(0,observed_at-3600),end_time=observed_at))
    data=payload.get("data") if isinstance(payload,dict) else None
    if not isinstance(data,list):
        return dict(available=False,reason="ohlcv_shape")
    closes=[]
    for row in data:
        if not isinstance(row,dict):continue
        ts=row.get("timestamp");close=_num(row.get("close"))
        if isinstance(ts,int) and ts<=observed_at and close is not None and close>0:
            closes.append((ts,close))
    closes.sort()
    returns=[math.log(b/a) for (_ta,a),(_tb,b) in zip(closes,closes[1:]) if a>0 and b>0]
    if len(returns)<2:
        return dict(available=False,reason="insufficient_returns",candles=len(closes))
    return dict(
        available=True,candles=len(closes),return_count=len(returns),
        log_return_volatility=statistics.pstdev(returns),
    )


def main():
    observed_at=int(time.time())
    by_bucket={};meta={}
    for label,_lo,_hi in BUCKETS:
        rows,status=census_bucket(label)
        if not status["complete"]:
            raise RuntimeError(f"dlmm_small_pool_market_incomplete_stratum:{label}")
        by_bucket[label]=rows;meta[label]=status
        print(json.dumps(dict(
            phase="pool_census",bucket=label,pools=len(rows),
            pages=status["pages_read"],complete=True),sort_keys=True),flush=True)

    canonical=[
        [label,r["address"],r["tvl_usd"],r["volume_24h_usd"],r["fees_24h_usd"],r["created_at"]]
        for label,_lo,_hi in BUCKETS for r in by_bucket[label]
    ]
    snapshot_hash=hashlib.sha256(json.dumps(
        canonical,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    signature=_checkpoint_signature(snapshot_hash)
    vol_rows=_load_checkpoint(signature)

    for label,_lo,_hi in BUCKETS:
        for row in _sample(by_bucket[label]):
            address=row["address"]
            if address in vol_rows:continue
            try:result=volatility(address,observed_at)
            except Exception as exc:result=dict(available=False,reason=type(exc).__name__)
            vol_rows[address]=dict(bucket=label,**result)
            _save_checkpoint(signature,vol_rows)

    summaries={}
    vol_summary={}
    cross=[]
    for label,_lo,_hi in BUCKETS:
        summaries[label]=summarize_bucket(by_bucket[label],observed_at)
        sampled=[v for v in vol_rows.values() if v.get("bucket")==label]
        values=[v["log_return_volatility"] for v in sampled if v.get("available")]
        vol_summary[label]=dict(
            sampled_pool_count=len(sampled),available_volatility_count=len(values),
            median_volatility=_quantile(values,0.50),p75_volatility=_quantile(values,0.75),
            p90_volatility=_quantile(values,0.90),
            share_volatility_ge_3pct=(None if not values else
                                     sum(v>=0.03 for v in values)/len(values)),
            share_volatility_ge_10pct=(None if not values else
                                      sum(v>=0.10 for v in values)/len(values)),
        )
        sample_addresses={a for a,v in vol_rows.items()
                          if v.get("bucket")==label and v.get("available")}
        sample_map={r["address"]:r for r in by_bucket[label]
                    if r["address"] in sample_addresses}
        grouped=defaultdict(list)
        for address in sample_addresses:
            row=sample_map.get(address)
            if row is None:continue
            created=row.get("created_at")
            age=(observed_at-created if isinstance(created,int) and created<=observed_at else None)
            grouped[_age_bucket(age)].append(address)
        for age_bucket,addresses in sorted(grouped.items(),key=lambda x:str(x[0])):
            vals=[vol_rows[a]["log_return_volatility"] for a in addresses]
            fee_density=[]
            for a in addresses:
                r=sample_map[a];tvl=r.get("tvl_usd");fees=r.get("fees_24h_usd")
                if tvl and tvl>0 and fees is not None:fee_density.append(fees/tvl)
            cross.append(dict(
                tvl_bucket=label,pool_age_bucket=age_bucket,
                sampled_pool_count=len(addresses),
                median_volatility=_quantile(vals,0.50),
                median_fee_to_tvl_24h=_quantile(fee_density,0.50),
            ))

    report=dict(
        kind="dlmm_small_pool_market_opportunity_v1",
        status="pool_first_descriptive_complete_no_wallet_inputs",
        protocol_sha256=signature["protocol_sha256"],observed_at=observed_at,
        snapshot_hash=snapshot_hash,consumes_wallet_review=False,
        consumes_wallet_pnl=False,current_50000_tvl_execution_gate_changed=False,
        census=meta,by_tvl_stratum=summaries,
        volatility_sample_by_tvl_stratum=vol_summary,
        tvl_age_volatility_sample_cross_classification=cross,
        volatility_checkpoint=str(CHECKPOINT),
        interpretation_guardrails=dict(
            gross_opportunity_not_net_profit=True,
            fee_density_is_not_profit_after_inventory_loss=True,
            compare_to_independent_200_wallet_review_later=True,
            no_best_bucket_strategy_selection=True,
        ),
    )
    OUT.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps(dict(
        status=report["status"],
        by_tvl={k:dict(
            pools=v["pool_count"],median_fee_tvl=v["median_fee_to_tvl_24h"],
            median_volume_tvl=v["median_volume_to_tvl_24h"],
            share_lt24h=v["share_age_lt_24h"])
            for k,v in summaries.items()},
        volatility={k:dict(
            median=v["median_volatility"],share_ge_3pct=v["share_volatility_ge_3pct"])
            for k,v in vol_summary.items()},
    ),sort_keys=True))


if __name__=="__main__":
    main()
