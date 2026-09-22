"""Analyze whether public prior LP skill improves quiet Ramses USDG entries.

Uses only derivation+validation rows from the corrected fee decomposition artifact.
For each entry, an owner's prior record includes only lifecycles that had fully
closed before the current entry timestamp.
"""
from __future__ import annotations
from collections import defaultdict
import json, math
from pathlib import Path

SRC=Path("ramses-historical-fee-decomposition.json")
OUT=Path("ramses-public-lp-skill-analysis.json")

def qtile(values,q):
    xs=sorted(float(x) for x in values if x is not None and math.isfinite(float(x)))
    if not xs:return None
    if len(xs)==1:return xs[0]
    p=(len(xs)-1)*q;lo=int(math.floor(p));hi=int(math.ceil(p))
    if lo==hi:return xs[lo]
    return xs[lo]+(xs[hi]-xs[lo])*(p-lo)

def summarize(rows):
    if not rows:return {}
    return dict(
        n=len(rows),pools=len({r["pool"] for r in rows}),owners=len({r["owner"] for r in rows}),
        median_gross_return=qtile([r["gross_return"] for r in rows],.5),
        mean_gross_return=sum(float(r["gross_return"]) for r in rows)/len(rows),
        win_rate=sum(float(r["gross_return"])>0 for r in rows)/len(rows),
        p10_gross_return=qtile([r["gross_return"] for r in rows],.1),
        median_fee_return=qtile([r["fee_return"] for r in rows],.5),
        mean_fee_return=sum(float(r["fee_return"]) for r in rows)/len(rows),
        median_inventory_return=qtile([r["inventory_return"] for r in rows],.5),
        mean_inventory_return=sum(float(r["inventory_return"]) for r in rows)/len(rows),
        median_hold_hours=qtile([float(r["hold_seconds"])/3600 for r in rows],.5),
    )

def main():
    body=json.loads(SRC.read_text())
    rows=body.get("rows") or []
    if any(r.get("split")=="holdout" for r in rows):
        raise RuntimeError("lp_skill_holdout_exposed")
    rows=sorted(rows,key=lambda r:(int(r["entry_timestamp"]),str(r["owner"]),str(r["pool"])))
    closed_by_owner=defaultdict(list)
    enriched=[]
    for r in rows:
        entry=int(r["entry_timestamp"]);owner=str(r["owner"]).lower()
        prior=[p for p in closed_by_owner[owner] if int(p["exit_timestamp"])<entry]
        prior_returns=[float(p["gross_return"]) for p in prior]
        prior_fees=[float(p["fee_return"]) for p in prior]
        q=dict(r)
        q["prior_closed_count"]=len(prior)
        q["prior_win_rate"]=(sum(x>0 for x in prior_returns)/len(prior_returns) if prior_returns else None)
        q["prior_median_gross_return"]=qtile(prior_returns,.5)
        q["prior_mean_gross_return"]=(sum(prior_returns)/len(prior_returns) if prior_returns else None)
        q["prior_median_fee_return"]=qtile(prior_fees,.5)
        q["prior_positive_record"]=bool(
            len(prior)>=1 and q["prior_median_gross_return"] is not None and q["prior_median_gross_return"]>0
        )
        q["prior_positive_fee_record"]=bool(
            len(prior)>=1 and q["prior_median_fee_return"] is not None and q["prior_median_fee_return"]>0
        )
        enriched.append(q)
        closed_by_owner[owner].append(r)

    quiet=[
        r for r in enriched
        if str(r.get("symbol") or "").endswith("/USDG")
        and int((r.get("pre_1800s") or {}).get("swap_count",999))<=2
    ]
    out=dict(
        kind="ramses_public_lp_skill_analysis_v1",research_only=True,
        holdout_outcomes_read=False,
        signal="quiet USDG entry; owner skill computed only from lifecycles closed before current entry",
        splits={}
    )
    for split in ("derivation","validation"):
        sr=[r for r in quiet if r.get("split")==split]
        groups={
            "all":sr,
            "no_prior":[r for r in sr if r["prior_closed_count"]==0],
            "prior_any":[r for r in sr if r["prior_closed_count"]>=1],
            "prior_2plus":[r for r in sr if r["prior_closed_count"]>=2],
            "prior_3plus":[r for r in sr if r["prior_closed_count"]>=3],
            "prior_positive":[r for r in sr if r["prior_positive_record"]],
            "prior_positive_fee":[r for r in sr if r["prior_positive_fee_record"]],
            "prior_2plus_positive":[r for r in sr if r["prior_closed_count"]>=2 and r["prior_positive_record"]],
            "prior_2plus_positive_fee":[r for r in sr if r["prior_closed_count"]>=2 and r["prior_positive_fee_record"]],
        }
        out["splits"][split]={name:summarize(g) for name,g in groups.items()}
    out["rows"]=enriched
    OUT.write_text(json.dumps(out,indent=2,sort_keys=True))
    print(json.dumps({
        "status":"complete",
        "derivation":out["splits"]["derivation"],
        "validation":out["splits"]["validation"],
    },sort_keys=True))

if __name__=="__main__":main()
