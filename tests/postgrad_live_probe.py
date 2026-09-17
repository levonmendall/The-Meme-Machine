"""One-shot read-only mainnet proof for post-graduation adapters.

No Store is opened, no paper reservation is created, and no transaction can be built,
signed or submitted. The output capture is source evidence for decoder regression only.
"""
import base64
from dataclasses import asdict
import json
import os
import struct
import time
from pathlib import Path

from meme_machine import pump
from meme_machine.postgrad import (
    PUMPSWAP_DOCUMENTED_POOL if False else PUMPSWAP_PROGRAM,
)
from meme_machine.postgrad import (
    RAYDIUM_AMM_V4, RAYDIUM_LAYOUT_SIZE, WSOL,
    PostGraduationAdapter, _decode_raydium_pool, buy_quote, graduation_handoff,
    pumpswap_pool, sell_quote,
)
from meme_machine.provider import RPC

PUMPSWAP_SAMPLE_MINT = '7LSsEoJGhLeZzGvDofTdNg7M3JttxQqGWNLo6vWMpump'
PUMPSWAP_DOCUMENTED_POOL = 'GseMAnNDvntR5uFePZ51yZBXzNSn7GdFPkfHwfr6d77J'
LEGACY_RAYDIUM_SAMPLE_MINT = '9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump'
QUOTE_BUDGET_LAMPORTS = 100_000_000
CAPTURE = Path('postgrad-live-capture.json')


def _surface(adapter, mint, surface):
    observed = int(time.time())
    graduation = adapter.graduation_snapshot(mint, observed, priority=True)
    handoff = graduation_handoff(graduation, int(time.time()))
    if surface == 'pumpswap':
        snapshot = adapter.pumpswap_snapshot(handoff, int(time.time()), priority=True)
    elif surface == 'raydium-v4':
        snapshot = adapter.raydium_snapshot(handoff, int(time.time()), priority=True)
    else:
        raise ValueError('unsupported_probe_surface')
    buy = buy_quote(snapshot, QUOTE_BUDGET_LAMPORTS)
    sell = sell_quote(snapshot, buy.output_amount)
    result = dict(
        success=True,
        mint=mint,
        surface=surface,
        pool=snapshot['pool'],
        graduation_slot=handoff.source_slot,
        snapshot_slot=snapshot['slot'],
        quote_age_seconds=max(0, int(time.time())-snapshot['market_time']),
        base_reserve=snapshot['state']['base_reserve'],
        quote_reserve=snapshot['state']['quote_reserve'],
        buy_budget_lamports=QUOTE_BUDGET_LAMPORTS,
        buy_cost_lamports=buy.input_amount,
        buy_token_units=buy.output_amount,
        buy_fee_amount=buy.fee_amount,
        buy_fee_asset=buy.fee_asset,
        immediate_roundtrip_lamports=sell.output_amount,
        immediate_roundtrip_loss_lamports=buy.input_amount-sell.output_amount,
        model=snapshot['model'],
    )
    capture = dict(
        kind='captured_mainnet_postgrad_read',
        captured_at=int(time.time()),
        graduation=graduation,
        handoff=asdict(handoff),
        snapshot=snapshot,
        quote=dict(buy=asdict(buy), sell=asdict(sell)),
    )
    return result, capture


def _legacy_raydium_lineage(adapter, mint):
    """Collect bounded lineage evidence without selecting among ambiguous pools."""
    adapter._verify_scan()
    candidates = {}
    for offset in (400, 432):
        result = adapter.scan_rpc.call(
            'getProgramAccounts',
            [RAYDIUM_AMM_V4, {
                'commitment':'finalized', 'withContext':True, 'encoding':'base64',
                'filters':[
                    {'dataSize':RAYDIUM_LAYOUT_SIZE},
                    {'memcmp':{'offset':offset, 'bytes':mint}},
                ],
            }],
            True,
        )
        for row in result.get('value') or []:
            try:
                key = row['pubkey']
                state = _decode_raydium_pool(key, row['account'], mint)
                raw = base64.b64decode(row['account']['data'][0], validate=True)
                candidates[key] = dict(
                    pool=key,
                    pool_open_time=struct.unpack_from('<Q', raw, 224)[0],
                    owner=pump.b58(raw[688:720]),
                    lp_reserve=struct.unpack_from('<Q', raw, 720)[0],
                    market_id=state['market_id'],
                    open_orders=state['open_orders'],
                    base_mint=state['base_mint'],
                    quote_mint=state['quote_mint'],
                    base_vault=state['base_vault'],
                    quote_vault=state['quote_vault'],
                    swap_fee_numerator=state['swap_fee_numerator'],
                    swap_fee_denominator=state['swap_fee_denominator'],
                )
            except (ValueError, KeyError, TypeError, struct.error):
                continue

    curve = pump.pda([b'bonding-curve', pump.un58(mint)])
    signatures = adapter.rpc.call(
        'getSignaturesForAddress',
        [curve, {'limit':20, 'commitment':'finalized'}],
        True,
    )
    successful = [row for row in signatures if not row.get('err')]
    params = [[row['signature'], {
        'encoding':'json', 'commitment':'finalized',
        'maxSupportedTransactionVersion':0,
    }] for row in successful]
    txs = adapter.rpc.call_many('getTransaction', params, True, batch_size=8) if params else []
    terminal = []
    withdraw = []
    for sig, tx in zip(successful, txs):
        if not tx:
            continue
        logs = (tx.get('meta') or {}).get('logMessages') or []
        text = '\n'.join(logs)
        row = dict(
            signature=sig['signature'],
            slot=int(tx.get('slot') or sig.get('slot') or 0),
            block_time=tx.get('blockTime', sig.get('blockTime')),
            pump_withdraw=('Instruction: Withdraw' in text),
            pump_program_invoked=any(pump.PROGRAM in line for line in logs),
        )
        terminal.append(row)
        if row['pump_withdraw']:
            withdraw.append(row)
    withdraw_times = [int(row['block_time']) for row in withdraw if row.get('block_time') is not None]
    if withdraw_times:
        reference = max(withdraw_times)
        for row in candidates.values():
            row['seconds_from_withdraw'] = int(row['pool_open_time'])-reference
    return dict(
        authority='read_only_diagnostic',
        selection_performed=False,
        bonding_curve=curve,
        candidates=sorted(candidates.values(), key=lambda x:(x['pool_open_time'], x['pool'])),
        recent_terminal_transactions=terminal,
        withdraw_matches=withdraw,
    )


def main():
    url = os.environ.get('MM_SOLANA_RPC_URL', 'https://api.mainnet-beta.solana.com')
    rpc = RPC(url, limit=200)
    adapter = PostGraduationAdapter(rpc)
    report = dict(
        kind='postgrad_read_only_live_probe',
        network='solana-mainnet',
        order_authority=False,
        allocation_enabled=False,
        signing_authority=False,
        transaction_submission_authority=False,
        live_money_authority=False,
        profitability_evidence=False,
        provider_spend_usd=0 if url == 'https://api.mainnet-beta.solana.com' else None,
        infrastructure_spend_usd=0,
        samples={},
        limitations=[],
        started=int(time.time()),
    )
    captures = {}
    checks = [
        ('pumpswap', PUMPSWAP_SAMPLE_MINT),
        ('raydium-v4', LEGACY_RAYDIUM_SAMPLE_MINT),
    ]
    for surface, mint in checks:
        try:
            result, capture = _surface(adapter, mint, surface)
            if surface == 'pumpswap':
                matches = bool(
                    result['pool'] and
                    pumpswap_pool(mint) == PUMPSWAP_DOCUMENTED_POOL == result['pool'])
                result['documented_pool_matches'] = matches
                if not matches:
                    raise ValueError('documented_pumpswap_pool_identity_mismatch')
            report['samples'][surface] = result
            captures[surface] = capture
        except Exception as exc:
            row = dict(
                success=False, mint=mint, surface=surface,
                blocker=str(exc) if str(exc) else type(exc).__name__,
            )
            if surface == 'raydium-v4' and str(exc) == 'ambiguous_legacy_raydium_pools':
                try:
                    row['lineage_diagnostic'] = _legacy_raydium_lineage(adapter, mint)
                except Exception as lineage_exc:
                    row['lineage_diagnostic_error'] = (
                        f'{type(lineage_exc).__name__}:{str(lineage_exc)}')
            report['samples'][surface] = row
            report['limitations'].append(f'{surface}:{type(exc).__name__}:{str(exc)}')
    report.update(
        success=all(report['samples'].get(surface, {}).get('success') for surface, _ in checks),
        ended=int(time.time()),
        http_logical_requests=rpc.calls,
        http_transport_requests=rpc.http_requests,
        http_failures=rpc.failures,
        http_retries=rpc.retries,
        http_failure_kinds=rpc.failure_kinds,
        scan_status=dict(
            configured=adapter.scan_rpc is not None,
            verified=adapter.scan_verified,
            logical_requests=getattr(adapter.scan_rpc, 'calls', 0),
            transport_requests=getattr(adapter.scan_rpc, 'http_requests', 0),
            failures=getattr(adapter.scan_rpc, 'failures', 0),
            retries=getattr(adapter.scan_rpc, 'retries', 0),
            failure_kinds=dict(getattr(adapter.scan_rpc, 'failure_kinds', {})),
        ),
    )
    CAPTURE.write_text(json.dumps(dict(report=report, captures=captures), sort_keys=True))
    print(json.dumps(report, sort_keys=True))
    if not report['success']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
