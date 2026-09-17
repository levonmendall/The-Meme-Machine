"""Run the unchanged high-activity DLMM research experiment through PublicNode.

This changes only the read-only RPC transport. Candidate ranking, finalized on-chain
validation, warmup/outcome separation, strategy selector, simulator, evidence gates,
and allocation-disabled authority all remain exactly those in
`tests.dlmm_strategy_high_activity`.
"""
from __future__ import annotations

import argparse
import json

from meme_machine.postgrad import PoolScanRPC as _PoolScanRPC
from tests import dlmm_strategy_high_activity as research

PUBLICNODE_SOLANA = "https://solana-rpc.publicnode.com"


class PublicNodePoolScanRPC(_PoolScanRPC):
    def __init__(self, _url, limit=240, **kwargs):
        super().__init__(PUBLICNODE_SOLANA, limit=limit, **kwargs)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cycles", type=int, default=research.MAX_CYCLES)
    parser.add_argument("--window-seconds", type=int, default=6)
    args = parser.parse_args()

    original = research.PoolScanRPC
    research.PoolScanRPC = PublicNodePoolScanRPC
    try:
        report = research.run_live(args.cycles, args.window_seconds)
    finally:
        research.PoolScanRPC = original

    report["research_rpc_provider"] = "publicnode_free_keyless"
    report["research_rpc_endpoint_public"] = PUBLICNODE_SOLANA
    research.REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "provider": report["research_rpc_provider"],
        "conclusion": report["conclusion"],
        "pools": report["distinct_pools"],
        "opportunities": report["opportunity_count"],
        "nonempty_warmups": report["nonempty_warmup_count"],
        "nonempty_outcomes": report["nonempty_outcome_count"],
        "selected_trades": report["selected_trade_count"],
        "selected_median_pnl_bps": report["selected_median_pnl_bps"],
        "rpc_failures": report["rpc_failures"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
