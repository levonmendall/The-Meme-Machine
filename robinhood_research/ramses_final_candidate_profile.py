"""Profile frozen quiet-entry candidates from indexed history only.

No future outcome metrics, no strategy changes, no archive RPC.
"""
from __future__ import annotations
import gzip,json
from collections import defaultdict
from pathlib import Path
from .ramses_historical_quiet_mint_counterfactual import (
    INDEX,MINT_FIELDS,POOL_FIELDS,page,swap_times,select_candidates,i,addr
)
OUT=Path("ramses-final-candidate-profile.json")

def main():
    with gzip.open(INDEX,"rt",encoding="utf-8") as fh:index=json.load(fh)
    by,start,end=swap_times(index)
    candidates,selection=select_candidates(page("DLMMMint",MINT_FIELDS),page("DLMMPool",POOL_FIELDS),by,start,end)
    rows=[]
    for idx,c in enumerate(candidates):
        ts=i(c["timestamp"]);swaps=by.get(addr(c["pool"]),[])
        rows.append(dict(
            candidate_index=idx,selection_hash=c["selection_hash"],pool=c["pool"],symbol=c.get("symbol"),
            timestamp=ts,prior_30m_swaps=c.get("prior_30m_swaps"),prior_24h_swaps=c.get("prior_24h_swaps"),
            next_1h_swaps=sum(ts < x <= ts+3600 for x in swaps),
            next_4h_swaps=sum(ts < x <= ts+14400 for x in swaps),
            mint_bin_count=len(c.get("mint_bin_ids") or []),
            mint_amount_usd=c.get("mint_amount_usd"),
        ))
    OUT.write_text(json.dumps(dict(kind="ramses_final_candidate_profile_v1",selection=selection,candidates=rows),indent=2,sort_keys=True))
    print(json.dumps(rows,sort_keys=True))

if __name__=="__main__":main()
