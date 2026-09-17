"""Retry high-activity DLMM research with deeper discovery and bounded batching.

Only pre-entry candidate breadth and physical `getTransaction` transport change.
Logical request budgets, finalized evidence requirements, complete ordering,
terminal-state equality, warmup/outcome separation, fixed strategy selection and
disabled allocation authority are unchanged.
"""
from __future__ import annotations

import argparse
import json
import time

from meme_machine.dlmm_tape import MAX_TRANSACTIONS, reconstruct
from meme_machine.provider import Unavailable
from meme_machine.store import encode
from tests import dlmm_strategy_high_activity as research

TARGET_SUPPORTED_POOLS = 3
DEEP_DISCOVERY_POOL_MULTIPLIER = 12  # returns at most 36 pre-entry addresses
DEEP_DISCOVERY_PAGE = 80


def batched_advance(adapter, states, wait_seconds):
    time.sleep(wait_seconds)
    advanced, tapes, errors = {}, {}, []
    rpc = adapter.rpc
    for address, start in list(states.items()):
        try:
            end_snapshot = adapter.snapshot(address, int(time.time()), True)
            signatures = rpc.call(
                'getSignaturesForAddress',
                [start['pool'], dict(limit=64, commitment='finalized')],
                True,
            )
            relevant = [
                sig for sig in signatures
                if start['slot'] < sig['slot'] <= end_snapshot['slot'] and not sig.get('err')
            ]
            if len(relevant) > MAX_TRANSACTIONS:
                raise Unavailable('dlmm_transaction_bound')
            params = [
                [sig['signature'], dict(
                    encoding='json', commitment='finalized', maxSupportedTransactionVersion=0)]
                for sig in relevant
            ]
            values = rpc.call_many('getTransaction', params, True, batch_size=4)
            transactions = {sig['signature']: tx for sig, tx in zip(relevant, values)}
            if len(encode(transactions)) > 2_000_000:
                raise Unavailable('dlmm_interval_evidence_bound')
            now = int(time.time())
            tape = reconstruct(
                start,
                end_snapshot,
                signatures,
                transactions,
                now,
                [start['slot'], 2**31 - 1, 2**31 - 1],
            )
            advanced[address] = tape.terminal
            tapes[address] = tape
        except (Unavailable, ValueError, KeyError, TypeError) as exc:
            errors.append(dict(pool=address, reason=str(exc)))
    return advanced, tapes, errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cycles', type=int, default=1)
    parser.add_argument('--window-seconds', type=int, default=6)
    args = parser.parse_args()

    original_advance = research._advance
    original_fetch = research.fetch_high_activity
    original_max_pools = research.MAX_POOLS

    def deep_fetch(_limit=24):
        # Reuse the exact current API parser/filter, but inspect farther down the
        # same volume_30m ranking before on-chain eligibility filtering.
        research.MAX_POOLS = DEEP_DISCOVERY_POOL_MULTIPLIER
        try:
            return original_fetch(DEEP_DISCOVERY_PAGE)
        finally:
            research.MAX_POOLS = TARGET_SUPPORTED_POOLS

    research.MAX_POOLS = TARGET_SUPPORTED_POOLS
    research._advance = batched_advance
    research.fetch_high_activity = deep_fetch
    try:
        report = research.run_live(args.cycles, args.window_seconds)
    finally:
        research._advance = original_advance
        research.fetch_high_activity = original_fetch
        research.MAX_POOLS = original_max_pools

    report['research_rpc_provider'] = 'solana_labs_public_mainnet'
    report['transaction_retrieval'] = 'bounded_call_many_batch_size_4'
    report['activity_rank_rows_examined_max'] = DEEP_DISCOVERY_PAGE
    report['supported_pool_target'] = TARGET_SUPPORTED_POOLS
    research.REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps({
        'provider': report['research_rpc_provider'],
        'transaction_retrieval': report['transaction_retrieval'],
        'conclusion': report['conclusion'],
        'pools': report['distinct_pools'],
        'initial_pools': len(report['initial_pools']),
        'opportunities': report['opportunity_count'],
        'nonempty_warmups': report['nonempty_warmup_count'],
        'nonempty_outcomes': report['nonempty_outcome_count'],
        'selected_trades': report['selected_trade_count'],
        'selected_median_pnl_bps': report['selected_median_pnl_bps'],
        'rpc_failures': report['rpc_failures'],
    }, sort_keys=True))


if __name__ == '__main__':
    main()
