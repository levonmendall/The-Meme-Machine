"""Execute one forced, paper-only Ramses LP lifecycle on real finalized mainnet state."""
import base64
import json
import os
from pathlib import Path
import zlib

from . import BoundaryError
from .ramses_capture import run

REPORT=Path(os.environ.get("MM_ROBINHOOD_RAMSES_FORCED_REPORT","robinhood-ramses-forced-paper-report.json"))
DB=Path(os.environ.get("MM_ROBINHOOD_RAMSES_FORCED_DB","robinhood-ramses-forced-paper.sqlite"))


def main():
    if DB.exists():
        raise BoundaryError("forced_ramses_paper_db_already_exists")
    result=run(
        os.environ.get("MM_ROBINHOOD_READ_RPC_URL",""),
        forced_paper=True,
        forced_db_path=str(DB),
    )
    result["artifact_kind"]="forced_ramses_paper_mechanics_v1"
    result["paper_only"]=True
    result["natural_proof"]=False
    result["allocation_authority"]=False
    result["strategy_evidence_eligible"]=False
    raw=json.dumps(result,sort_keys=True,separators=(",",":")).encode()
    if len(raw)>2_000_000:
        raise BoundaryError("forced_ramses_report_capacity")
    REPORT.write_bytes(raw)
    print(json.dumps(dict(
        boundary=result.get("boundary"),
        mechanics_complete=result.get("mechanics_complete",False),
        pool=result.get("pool"),
        proposal_hash=result.get("proposal_hash"),
        observation_seconds=result.get("observation_seconds"),
        final_status=(result.get("forced_paper_final") or {}).get("position",{}).get("status"),
        provider=result.get("provider"),
    )))
    data=base64.b64encode(zlib.compress(raw,9)).decode()
    for i in range(0,len(data),6000):
        print("PUBLIC_EVIDENCE_CHUNK "+str(i//6000)+" "+data[i:i+6000])


if __name__=="__main__":
    main()
