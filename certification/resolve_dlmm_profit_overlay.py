"""Deterministic resolver for reviewed DLMM profitability overlay conflicts.

Only the explicitly reviewed Meteora campaign-runtime conflict is supported here.
Any other unresolved path or conflict shape fails closed for manual inspection.
"""
from __future__ import annotations
from pathlib import Path
import sys

def resolve_meteora(path: Path) -> None:
    text=path.read_text()
    old='''<<<<<<< ours
    if not 60<=max_runtime_seconds<=90000:
=======
    if type(campaign) is not bool:raise ValueError("solana_dlmm_campaign_flag")
    if not 60<=max_runtime_seconds<=(21600 if campaign else 7200):
>>>>>>> theirs
'''
    new='''    if type(campaign) is not bool:raise ValueError("solana_dlmm_campaign_flag")
    if not 60<=max_runtime_seconds<=(90000 if campaign else 7200):
'''
    if text.count(old)!=1:
        raise SystemExit("unexpected_meteora_campaign_conflict")
    resolved=text.replace(old,new,1)
    if "<<<<<<<" in resolved or "=======" in resolved or ">>>>>>>" in resolved:
        raise SystemExit("unresolved_meteora_overlay_conflict")
    path.write_text(resolved)

def main() -> None:
    if len(sys.argv)!=3:
        raise SystemExit("usage: resolve_dlmm_profit_overlay.py <lane> <path>")
    lane,path=sys.argv[1],Path(sys.argv[2])
    if lane!="meteora" or path.name!="solana_dlmm_independent_v1.py":
        raise SystemExit("unreviewed_dlmm_overlay_conflict")
    resolve_meteora(path)

if __name__=="__main__":
    main()
