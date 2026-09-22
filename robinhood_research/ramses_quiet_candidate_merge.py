"""Merge isolated Ramses quiet-entry exact replay candidates.

All six partial artifacts must come from the same frozen protocol and deterministic
selection. No strategy parameters are changed here.
"""
from __future__ import annotations
import json, os
from pathlib import Path

ROOT=Path(os.environ.get("RAMSES_PARTIAL_ROOT","/tmp/ramses-partials"))
OUT=Path("ramses-quiet-mint-counterfactual.json")
EXPECTED=6

def main():
    parts=[]
    for idx in range(EXPECTED):
        matches=list(ROOT.glob(f"candidate-{idx}/**/ramses-quiet-mint-counterfactual.json"))
        if len(matches)!=1:
            raise RuntimeError(f"quiet_merge_candidate_artifact:{idx}:{len(matches)}")
        body=json.loads(matches[0].read_text())
        rows=body.get("candidates") or []
        if len(rows)!=1:
            raise RuntimeError(f"quiet_merge_candidate_count:{idx}")
        if int((body.get("selection") or {}).get("candidate_index",-1))!=idx:
            raise RuntimeError(f"quiet_merge_candidate_index:{idx}")
        if not (body.get("checkpoint") or {}).get("complete"):
            raise RuntimeError(f"quiet_merge_incomplete:{idx}")
        parts.append(body)

    protocol=json.dumps(parts[0]["protocol"],sort_keys=True,separators=(",",":"))
    bounds={k:v for k,v in (parts[0].get("selection") or {}).items() if k not in ("candidate_index","selected")}
    rows=[]
    seen=set()
    for idx,body in enumerate(parts):
        if json.dumps(body["protocol"],sort_keys=True,separators=(",",":"))!=protocol:
            raise RuntimeError("quiet_merge_protocol_mismatch")
        here={k:v for k,v in (body.get("selection") or {}).items() if k not in ("candidate_index","selected")}
        if here!=bounds:
            raise RuntimeError("quiet_merge_selection_mismatch")
        row=body["candidates"][0]
        key=(row.get("candidate") or {}).get("selection_hash")
        if not key or key in seen:
            raise RuntimeError("quiet_merge_duplicate_candidate")
        seen.add(key);rows.append(row)

    resolved=[
        v for r in rows if "holds" in r
        for h in r["holds"] for v in h.get("variants",[])
        if v.get("gross_return_bps") is not None
    ]
    selection=dict(parts[0]["selection"])
    selection.pop("candidate_index",None)
    selection["selected"]=EXPECTED
    selection["full_selected"]=EXPECTED
    out=dict(
        kind="ramses_dlmm_quiet_mint_counterfactual_v1",
        research_only=True,existing_strategy_policy_used=False,
        holdout_outcomes_read=False,
        protocol=parts[0]["protocol"],selection=selection,candidates=rows,
        checkpoint=dict(completed_candidates=EXPECTED,target_candidates=EXPECTED,complete=True),
        summary=dict(
            selected_candidates=EXPECTED,
            resolved_variants=len(resolved),
            positive_variants=sum(v["gross_return_bps"]>0 for v in resolved),
            median_gross_return_bps=(None if not resolved else
              sorted(v["gross_return_bps"] for v in resolved)[len(resolved)//2]),
        ),
        merge=dict(source="six isolated exact candidate jobs",candidate_indices=list(range(EXPECTED))),
    )
    OUT.write_text(json.dumps(out,indent=2,sort_keys=True))
    print(json.dumps(dict(status="complete",summary=out["summary"]),sort_keys=True))

if __name__=="__main__":
    main()
