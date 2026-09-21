"""Collect Ramses DLMM fee events with exact block/log identity.

This is a compact supplement for historical LP fee attribution. It does not read
LP outcomes or strategy policy.
"""
from __future__ import annotations
import gzip,json,time
from pathlib import Path
from .ramses_historical_index_collect import START,DAY,FEE_FIELDS,fetch_day

OUT=Path("ramses-historical-fees-with-identity.json.gz")
SUMMARY=Path("ramses-historical-fees-with-identity-summary.json")

def main():
    cutoff=int(time.time())+1
    fees=[];cursor=START
    while cursor<cutoff:
        end=min(cutoff,cursor+DAY)
        rows=fetch_day("DLMMFeeEvent",FEE_FIELDS,cursor,end)
        fees.extend(rows)
        print(json.dumps(dict(day=cursor,fees=len(rows),cumulative=len(fees))),flush=True)
        cursor=end
    missing=sum(1 for r in fees if r.get("blockNumber") is None or (r.get("logIndexNumber") is None and r.get("logIndex") is None))
    summary=dict(kind="ramses_dlmm_fee_identity_supplement_v1",research_only=True,
                 fee_events=len(fees),missing_log_identity=missing,start_timestamp=START,cutoff_timestamp=cutoff)
    SUMMARY.write_text(json.dumps(summary,indent=2,sort_keys=True))
    with gzip.open(OUT,"wt",encoding="utf-8") as fh:
        json.dump(dict(fee_events=fees),fh,separators=(",",":"))
    print(json.dumps(dict(status="complete",**summary),sort_keys=True))
if __name__=="__main__":main()
