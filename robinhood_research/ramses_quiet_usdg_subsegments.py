"""Analyze quiet-USDG Ramses realized LP subsegments on unsealed history only.

Consumes the derivation+validation fee decomposition artifact. The holdout is absent
by construction and is never queried.
"""
from __future__ import annotations
from collections import defaultdict
import json, math
from pathlib import Path

SRC=Path("ramses-historical-fee-decomposition.json")
OUT=Path("ramses-quiet-usdg-subsegments.json")

def f(v):
    try:return float(v)
    except (TypeError,ValueError):return None

def qtile(xs,q):
    vals=sorted(float(x) for x in xs if x is not None and math.isfinite(float(x)))
    if not vals:return None
    if len(vals)==1:return vals[0]
    p=(len(vals)-1)*q;lo=int(math.floor(p));hi=int(math.ceil(p))
    if lo==hi:return vals[lo]
    return vals[lo]+(vals[hi]-vals[lo])*(p-lo)

def summarize(rows):
    if not rows:return {}
    dep=sum(float(r.get("deposit_usd") or 0) for r in rows)
    pnl=sum(float(r.get("gross_pnl_usd") or 0) for r in rows)
    fee=sum(float(r.get("fee_income_usd") or 0) for r in rows)
    inv=sum(float(r.get("inventory_pnl_usd") or 0) for r in rows)
    pool_pnl=defaultdict(float)
    owner_pnl=defaultdict(float)
    for r in rows:
        pool_pnl[str(r.get("pool"))]+=float(r.get("gross_pnl_usd") or 0)
        owner_pnl[str(r.get("owner"))]+=float(r.get("gross_pnl_usd") or 0)
    pos_total=sum(v for v in pool_pnl.values() if v>0)
    max_pool_pos=max([v for v in pool_pnl.values() if v>0] or [0])
    max_owner_pos=max([v for v in owner_pnl.values() if v>0] or [0])
    return dict(
        n=len(rows),pools=len(pool_pnl),owners=len(owner_pnl),
        median_gross_return=qtile([r.get("gross_return") for r in rows],.5),
        mean_gross_return=sum(float(r.get("gross_return") or 0) for r in rows)/len(rows),
        win_rate=sum(float(r.get("gross_return") or 0)>0 for r in rows)/len(rows),
        p10_gross_return=qtile([r.get("gross_return") for r in rows],.1),
        median_fee_return=qtile([r.get("fee_return") for r in rows],.5),
        mean_fee_return=sum(float(r.get("fee_return") or 0) for r in rows)/len(rows),
        median_inventory_return=qtile([r.get("inventory_return") for r in rows],.5),
        mean_inventory_return=sum(float(r.get("inventory_return") or 0) for r in rows)/len(rows),
        median_hold_hours=qtile([float(r.get("hold_seconds") or 0)/3600 for r in rows],.5),
        median_width_bins=qtile([r.get("width_bins") for r in rows],.5),
        deployed_usd=dep,gross_pnl_usd=pnl,fee_income_usd=fee,inventory_pnl_usd=inv,
        max_positive_pool_pnl_share=(max_pool_pos/pos_total if pos_total>0 else None),
        max_positive_owner_pnl_share=(max_owner_pos/pos_total if pos_total>0 else None),
    )

def bucket(v,bounds):
    for name,lo,hi in bounds:
        if lo<=v<hi:return name
    return None

def main():
    data=json.loads(SRC.read_text())
    rows=data.get("rows") or []
    if any(r.get("split")=="holdout" for r in rows):
        raise RuntimeError("quiet_subsegments_holdout_exposed")
    quiet=[
        r for r in rows
        if str(r.get("symbol") or "").endswith("/USDG")
        and int((r.get("pre_1800s") or {}).get("swap_count",999))<=2
    ]
    width_bounds=[("<=8",0,9),("9-16",9,17),("17-32",17,33),("33-64",33,65),("65+",65,10**9)]
    hold_bounds=[("<6h",0,6),("6-24h",6,24),("24-72h",24,72),("72h+",72,10**9)]
    out=dict(
      kind="ramses_quiet_usdg_realized_subsegments_v1",
      research_only=True,holdout_outcomes_read=False,
      selection="symbol ends /USDG and strictly pre-entry 30m swap_count <= 2",
      splits={},interactions={}
    )
    for split in ("derivation","validation"):
        sr=[r for r in quiet if r.get("split")==split]
        out["splits"][split]=dict(overall=summarize(sr),by_width={},by_hold={},by_sidedness={},by_pool={})
        for name,lo,hi in width_bounds:
            out["splits"][split]["by_width"][name]=summarize([r for r in sr if lo<=int(r.get("width_bins") or 0)<hi])
        for name,lo,hi in hold_bounds:
            out["splits"][split]["by_hold"][name]=summarize([r for r in sr if lo<=float(r.get("hold_seconds") or 0)/3600<hi])
        for side in ("x_only","y_only","two_sided","unknown"):
            out["splits"][split]["by_sidedness"][side]=summarize([r for r in sr if r.get("sidedness")==side])
        for p in sorted({r.get("pool") for r in sr}):
            pr=[r for r in sr if r.get("pool")==p]
            out["splits"][split]["by_pool"][str(p)]=dict(symbol=pr[0].get("symbol"),summary=summarize(pr))
    for split in ("derivation","validation"):
        sr=[r for r in quiet if r.get("split")==split]
        combos={}
        for wname,wlo,whi in width_bounds:
            for hname,hlo,hhi in hold_bounds:
                rr=[r for r in sr if wlo<=int(r.get("width_bins") or 0)<whi and hlo<=float(r.get("hold_seconds") or 0)/3600<hhi]
                combos[f"{wname}__{hname}"]=summarize(rr)
        out["interactions"][split]=combos
    OUT.write_text(json.dumps(out,indent=2,sort_keys=True))
    print(json.dumps({
        "status":"complete",
        "derivation":out["splits"]["derivation"]["overall"],
        "validation":out["splits"]["validation"]["overall"],
    },sort_keys=True))

if __name__=="__main__":main()
