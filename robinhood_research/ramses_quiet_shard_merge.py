"""Merge six exact Ramses quiet-entry candidate shards into the frozen artifact shape."""
from __future__ import annotations
import json, os
from pathlib import Path

ROOT=Path(os.environ.get("RAMSES_SHARD_ROOT","/tmp/ramses-shards"))
OUT=Path("ramses-quiet-mint-counterfactual.json")
EXPECTED=6

def main():
    files=sorted(ROOT.glob("**/ramses-quiet-mint-counterfactual.json"))
    if len(files)!=EXPECTED:
        raise RuntimeError(f"ramses_quiet_shard_count:{len(files)}")
    rows=[]
    protocol=None
    selection_base=None
    providers=[]
    seen=set()
    for path in files:
        body=json.loads(path.read_text())
        if body.get("kind")!="ramses_dlmm_quiet_mint_counterfactual_v1":
            raise RuntimeError("ramses_quiet_shard_kind")
        cand=body.get("candidates") or []
        if len(cand)!=1:
            raise RuntimeError("ramses_quiet_shard_candidate_count")
        sel=body.get("selection") or {}
        idx=sel.get("shard_candidate_index")
        h=sel.get("shard_selection_hash")
        if type(idx) is not int or idx<0 or idx>=EXPECTED or not h:
            raise RuntimeError("ramses_quiet_shard_identity")
        if idx in seen:
            raise RuntimeError("ramses_quiet_shard_duplicate")
        seen.add(idx)
        actual=(cand[0].get("candidate") or {}).get("selection_hash")
        if actual!=h:
            raise RuntimeError("ramses_quiet_shard_hash_mismatch")
        if protocol is None:
            protocol=body.get("protocol")
            selection_base={k:v for k,v in sel.items() if not k.startswith("shard_")}
        else:
            if body.get("protocol")!=protocol:
                raise RuntimeError("ramses_quiet_shard_protocol_mismatch")
            base={k:v for k,v in sel.items() if not k.startswith("shard_")}
            if base!=selection_base:
                raise RuntimeError("ramses_quiet_shard_selection_mismatch")
        rows.append((idx,cand[0]))
        providers.append(body.get("provider"))
    if seen!=set(range(EXPECTED)):
        raise RuntimeError("ramses_quiet_shard_missing_index")
    rows=[r for _,r in sorted(rows)]
    resolved=[
        v for r in rows if "holds" in r
        for h in r.get("holds",[]) for v in h.get("variants",[])
        if v.get("gross_return_bps") is not None
    ]
    vals=sorted(v["gross_return_bps"] for v in resolved)
    out=dict(
        kind="ramses_dlmm_quiet_mint_counterfactual_v1",
        research_only=True,existing_strategy_policy_used=False,
        holdout_outcomes_read=False,protocol=protocol,
        selection=selection_base,candidates=rows,
        checkpoint=dict(completed_candidates=EXPECTED,target_candidates=EXPECTED,complete=True),
        summary=dict(
            selected_candidates=EXPECTED,
            resolved_variants=len(resolved),
            positive_variants=sum(v["gross_return_bps"]>0 for v in resolved),
            median_gross_return_bps=(vals[len(vals)//2] if vals else None),
        ),
        shard_providers=providers,
    )
    OUT.write_text(json.dumps(out,indent=2,sort_keys=True))
    print(json.dumps({"status":"complete","summary":out["summary"]},sort_keys=True))

if __name__=="__main__":main()
