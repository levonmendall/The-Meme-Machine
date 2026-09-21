"""Nominate historical Ramses DLMM windows for exact blank-slate replay.

This stage uses signal-window information only. It never looks at future P&L.
Existing Ramses strategy thresholds are not imported.
"""
from __future__ import annotations
from collections import defaultdict
import gzip, hashlib, json, math, os
from pathlib import Path

RAW=Path(os.environ.get("RAMSES_INDEX_DATA","ramses-historical-index-data.json.gz"))
PROTOCOL=Path("RAMSES_DLMM_BLANK_SLATE_HISTORICAL_PROTOCOL_V1.json")
OUT=Path("ramses-historical-strategy-nominations.json")
MAX_PER_POOL=10
PER_COHORT=120

def f(x):
    try:return float(x)
    except (TypeError,ValueError):return 0.0

def i(x):
    try:return int(x)
    except (TypeError,ValueError):return 0

def _pool(value):
    return str(value or "").split(":")[-1].lower()

def _event_index(row):
    raw=str(row.get("id") or "")
    try:return int(raw.rsplit(":",1)[-1])
    except (ValueError,IndexError):return None

def _percentile_rank(value, values):
    xs=[f(x) for x in values if x is not None and math.isfinite(f(x))]
    if not xs:return 0.0
    return sum(x<=f(value) for x in xs)/len(xs)

def enrich_swap_blocks(swaps,fees):
    by={}
    for row in fees:
        idx=_event_index(row)
        key=(str(row.get("transaction") or ""),idx)
        if not key[0] or idx is None:continue
        block=i(row.get("blockNumber"))
        if block<=0:continue
        prior=by.get(key)
        if prior is not None and prior!=block:
            raise RuntimeError("ramses_nomination_fee_block_conflict")
        by[key]=block
    out=[];missing=0
    for row in swaps:
        q=dict(row);key=(str(row.get("transaction") or ""),_event_index(row))
        block=by.get(key)
        if block is None:
            missing+=1
            continue
        q["blockNumber"]=block;q["poolAddress"]=_pool(q.get("pool"));out.append(q)
    return out,missing

def rank_windows(rows):
    by_start=defaultdict(list)
    for row in rows:
        if i(row.get("swap_count"))>=2:
            by_start[i(row.get("start"))].append(row)
    out=[]
    for start,group in by_start.items():
        fees=[f(x.get("lp_fees_usd")) for x in group]
        vols=[f(x.get("volume_usd")) for x in group]
        for row in group:
            q=dict(row)
            q["fee_percentile"]=_percentile_rank(q.get("lp_fees_usd"),fees)
            q["volume_percentile"]=_percentile_rank(q.get("volume_usd"),vols)
            out.append(q)
    return out

def split_bounds(rows):
    starts=sorted(i(r.get("start")) for r in rows if i(r.get("start"))>0)
    if not starts:raise RuntimeError("ramses_nomination_no_windows")
    lo,hi=starts[0],starts[-1]+1
    span=max(1,hi-lo)
    return dict(start=lo,derivation_end=lo+int(span*.60),
                validation_end=lo+int(span*.80),end=hi)

def split_name(ts,b):
    if ts<b["derivation_end"]:return "derivation"
    if ts<b["validation_end"]:return "validation"
    return "holdout"

def _stable(row,label):
    raw="|".join([label,str(row.get("pool")),str(row.get("start")),
                  str(row.get("swap_count")),str(row.get("volume_usd"))])
    return hashlib.sha256(raw.encode()).hexdigest()

def _bounded(rows,key,label):
    counts=defaultdict(int);out=[]
    for row in sorted(rows,key=key,reverse=True):
        p=_pool(row.get("pool"))
        if counts[p]>=MAX_PER_POOL:continue
        counts[p]+=1;out.append(row)
        if len(out)>=PER_COHORT:break
    return out

def _controls(rows,label):
    counts=defaultdict(int);out=[]
    for row in sorted(rows,key=lambda r:_stable(r,label)):
        p=_pool(row.get("pool"))
        if counts[p]>=MAX_PER_POOL:continue
        counts[p]+=1;out.append(row)
        if len(out)>=PER_COHORT:break
    return out

def event_map(swaps,seconds):
    by=defaultdict(list)
    for s in swaps:
        ts=i(s.get("timestamp"))
        by[(s["poolAddress"],ts//seconds)].append(s)
    for k in by:
        by[k].sort(key=lambda r:(i(r.get("timestamp")),i(r.get("blockNumber")),_event_index(r) or -1))
    return by

def candidate(row,events,kind,split,seconds,bounds):
    p=_pool(row.get("pool"));bucket=i(row.get("start"))//seconds
    tape=events.get((p,bucket),[])
    if not tape:raise RuntimeError("ramses_nomination_missing_signal_events")
    last=tape[-1]
    split_end={"derivation":bounds["derivation_end"],
               "validation":bounds["validation_end"],
               "holdout":bounds["end"]}[split]
    return dict(
        cohort=kind,split=split,signal_seconds=seconds,
        pool=p,symbol=row.get("symbol"),signal_start=i(row.get("start")),
        signal_end=i(row.get("end")),entry_timestamp=i(last.get("timestamp")),
        entry_block=i(last.get("blockNumber")),bin_step_bps=i(row.get("bin_step_bps")),
        swap_count=i(row.get("swap_count")),transaction_count=i(row.get("transaction_count")),
        volume_usd=f(row.get("volume_usd")),lp_fees_usd=f(row.get("lp_fees_usd")),
        lp_fee_bps=(None if row.get("lp_fee_bps") is None else f(row.get("lp_fee_bps"))),
        two_way_share=f(row.get("two_way_share")),flow_imbalance=f(row.get("flow_imbalance")),
        gross_bin_travel=i(row.get("gross_bin_travel")),net_bin_displacement=i(row.get("net_bin_displacement")),
        chop_ratio=f(row.get("chop_ratio")),fee_percentile=f(row.get("fee_percentile")),
        volume_percentile=f(row.get("volume_percentile")),split_end_timestamp=split_end,
        eligible_hold_seconds=[h for h in json.loads(PROTOCOL.read_text())["search_grid"]["hold_seconds"]
                               if i(last.get("timestamp"))+int(h)<split_end],
        selection_uses_future_outcome=False,
    )

def main():
    protocol=json.loads(PROTOCOL.read_text())
    if protocol.get("status")!="preregistered_before_full_index_results":
        raise RuntimeError("ramses_nomination_protocol_state")
    with gzip.open(RAW,"rt",encoding="utf-8") as fh:data=json.load(fh)
    swaps,missing=enrich_swap_blocks(data.get("swaps") or [],data.get("fee_events") or [])
    all_ranked=[]
    source={}
    for seconds,key in [(300,"windows_5m"),(900,"windows_15m"),(1800,"windows_30m")]:
        rows=rank_windows(data.get(key) or [])
        source[seconds]=rows;all_ranked.extend(rows)
    bounds=split_bounds(all_ranked)
    nominations=[]
    coverage={}
    for seconds,rows in source.items():
        events=event_map(swaps,seconds)
        for split in ("derivation","validation","holdout"):
            group=[r for r in rows if split_name(i(r.get("start")),bounds)==split]
            two=[r for r in group if i(r.get("swap_count"))>=3 and f(r.get("two_way_share"))>0]
            one=[r for r in group if i(r.get("swap_count"))>=2 and f(r.get("flow_imbalance"))>=.90]
            two_pick=_bounded(two,lambda r:(f(r.get("fee_percentile")),f(r.get("volume_percentile")),
                                             f(r.get("two_way_share")),min(20.0,f(r.get("chop_ratio"))),
                                             -i(r.get("net_bin_displacement")),i(r.get("swap_count"))),
                              "two_way_opportunity")
            one_pick=_bounded(one,lambda r:(f(r.get("fee_percentile")),f(r.get("volume_percentile")),
                                             i(r.get("swap_count")),i(r.get("net_bin_displacement"))),
                              "directional_control")
            ctl=_controls(group,f"{seconds}:{split}:activity_control")
            for kind,pick in [("two_way_opportunity",two_pick),("directional_control",one_pick),("activity_control",ctl)]:
                for row in pick:
                    c=candidate(row,events,kind,split,seconds,bounds)
                    if c["entry_block"]>0 and c["eligible_hold_seconds"]:
                        nominations.append(c)
            coverage[f"{seconds}:{split}"]=dict(active=len(group),two_way=len(two),directional=len(one),
                                                  nominated_two_way=len(two_pick),nominated_directional=len(one_pick),
                                                  nominated_control=len(ctl))
    out=dict(
        kind="ramses_dlmm_historical_strategy_nominations_v1",
        research_only=True,existing_strategy_policy_used=False,
        protocol_sha256=hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
        source_index_kind="ramses_dlmm_indexed_history_v1",
        swap_rows_with_block=len(swaps),swap_rows_missing_block=missing,
        split_bounds=bounds,coverage=coverage,nominations=nominations,
        note="Nominations use signal-window information only; exact future LP replay decides profitability."
    )
    OUT.write_text(json.dumps(out,indent=2,sort_keys=True))
    print(json.dumps(dict(status="complete",nominations=len(nominations),
                         swaps=len(swaps),missing_blocks=missing,bounds=bounds),sort_keys=True))

if __name__=="__main__":main()
