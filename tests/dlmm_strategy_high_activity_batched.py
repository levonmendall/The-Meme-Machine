"""Retry high-activity DLMM research with cheap mint prefilter and bounded batching.

Meteora's API remains discovery-only. Candidate token mints are screened in one
finalized batch before expensive pool snapshots, then every survivor still passes
PR #4's complete finalized pool/bin validation. Only physical RPC pressure is reduced;
evidence, ordering, simulator, warmup/outcome separation, selector and disabled
allocation authority remain unchanged.
"""
from __future__ import annotations

import argparse
import json
import time

from meme_machine import dlmm, pump
from meme_machine.dlmm_tape import MAX_TRANSACTIONS, reconstruct
from meme_machine.provider import Unavailable
from meme_machine.store import digest, encode
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


def efficient_discover_and_revalidate(adapter, now):
    candidates, api_error = research.discovery_candidates()
    rpc = adapter.rpc
    rejections = []

    # Discovery metadata is not trusted. This finalized mint batch is merely a
    # cheap rejection pass; accepted pools are still fully re-read atomically by
    # Adapter.snapshot below.
    mint_by_candidate = []
    unique_mints = []
    for candidate in candidates:
        x, y = candidate.get('token_x'), candidate.get('token_y')
        token = y if x == dlmm.WSOL else x if y == dlmm.WSOL else None
        mint_by_candidate.append(token)
        if token and token not in unique_mints:
            unique_mints.append(token)
    valid_mints = set()
    if unique_mints:
        response = rpc.call(
            'getMultipleAccounts',
            [unique_mints, dict(encoding='base64', commitment='finalized')],
            True,
        )
        values = response.get('value') if isinstance(response, dict) else None
        if not isinstance(values, list) or len(values) != len(unique_mints):
            raise Unavailable('dlmm_research_mint_prefilter_shape')
        for mint, account in zip(unique_mints, values):
            try:
                if not account or account.get('owner') != pump.TOKEN_PROGRAM:
                    raise ValueError('dlmm_unsupported_token_program_or_version')
                pump.mint_info(account)
                valid_mints.add(mint)
            except (ValueError, KeyError, TypeError) as exc:
                rejections.append(dict(pool=None, mint=mint, reason=str(exc)[:140], stage='mint_prefilter'))

    states, accepted = {}, []
    for candidate, token in zip(candidates, mint_by_candidate):
        address = candidate['address']
        if token and token not in valid_mints:
            rejections.append(dict(
                pool=address, name=candidate.get('name'), reason='mint_prefilter_rejected', stage='mint_prefilter'))
            continue
        try:
            snap = adapter.snapshot(address, int(time.time()), True)
            state = dlmm.validate(snap, snap['available_time'], 'real')
            if candidate.get('token_x') and candidate.get('token_y'):
                dlmm.scout(snap, snap['available_time'], dict(
                    pool=address, x=candidate['token_x'], y=candidate['token_y']))
            states[address] = state
            accepted.append(dict(
                **candidate,
                finalized_slot=state['slot'],
                active_bin=state['active'],
                onchain_bin_step=state['step'],
                evidence_hash=digest(snap),
            ))
        except (Unavailable, ValueError, KeyError, TypeError) as exc:
            rejections.append(dict(pool=address, name=candidate.get('name'), reason=str(exc)[:140], stage='pool_revalidation'))
        if len(states) >= TARGET_SUPPORTED_POOLS:
            break
    return states, accepted, rejections, api_error


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cycles', type=int, default=1)
    parser.add_argument('--window-seconds', type=int, default=6)
    args = parser.parse_args()

    original_advance = research._advance
    original_fetch = research.fetch_high_activity
    original_discover = research.discover_and_revalidate
    original_max_pools = research.MAX_POOLS

    def deep_fetch(_limit=24):
        research.MAX_POOLS = DEEP_DISCOVERY_POOL_MULTIPLIER
        try:
            return original_fetch(DEEP_DISCOVERY_PAGE)
        finally:
            research.MAX_POOLS = TARGET_SUPPORTED_POOLS

    research.MAX_POOLS = TARGET_SUPPORTED_POOLS
    research._advance = batched_advance
    research.fetch_high_activity = deep_fetch
    research.discover_and_revalidate = efficient_discover_and_revalidate
    try:
        report = research.run_live(args.cycles, args.window_seconds)
    finally:
        research._advance = original_advance
        research.fetch_high_activity = original_fetch
        research.discover_and_revalidate = original_discover
        research.MAX_POOLS = original_max_pools

    report['research_rpc_provider'] = 'solana_labs_public_mainnet'
    report['transaction_retrieval'] = 'bounded_call_many_batch_size_4'
    report['candidate_prefilter'] = 'single_finalized_getMultipleAccounts_classic_spl_mints'
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
        'rpc_calls': report['rpc_calls'],
        'rpc_failures': report['rpc_failures'],
    }, sort_keys=True))


if __name__ == '__main__':
    main()
