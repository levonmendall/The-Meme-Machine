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

def resolve_ramses(path: Path) -> None:
    text=path.read_text()
    old='''<<<<<<< ours
    start = _window_start_block(
        rpc,end,int(frontier["timestamp"],16),LOOKBACK_SECONDS,lookback_blocks
    )
=======
    start = max(0, end - lookback_blocks + 1)
    checkpoint('factory_authentication',frontier_block=end,frontier_hash=frontier['hash'],
        frontier_timestamp=int(frontier['timestamp'],16))
>>>>>>> theirs
'''
    new='''    start = _window_start_block(
        rpc,end,int(frontier["timestamp"],16),LOOKBACK_SECONDS,lookback_blocks
    )
    checkpoint('factory_authentication',frontier_block=end,frontier_hash=frontier['hash'],
        frontier_timestamp=int(frontier['timestamp'],16))
'''
    if text.count(old)!=1:
        raise SystemExit("unexpected_ramses_window_checkpoint_conflict")
    resolved=text.replace(old,new,1)
    if "<<<<<<<" in resolved or "=======" in resolved or ">>>>>>>" in resolved:
        raise SystemExit("unresolved_ramses_overlay_conflict")
    path.write_text(resolved)

def main() -> None:
    if len(sys.argv)!=3:
        raise SystemExit("usage: resolve_dlmm_profit_overlay.py <lane> <path>")
    lane,path=sys.argv[1],Path(sys.argv[2])
    if lane=="meteora" and path.name=="solana_dlmm_independent_v1.py":
        resolve_meteora(path)
    elif lane=="ramses" and path.name=="ramses_universe.py":
        resolve_ramses(path)
    else:
        raise SystemExit("unreviewed_dlmm_overlay_conflict")

if __name__=="__main__":
    main()
