"""One-shot read-only mainnet proof for post-graduation adapters.

No Store is opened, no paper reservation is created, and no transaction can be built,
signed or submitted. The output capture is source evidence for decoder regression only.
"""
from dataclasses import asdict
import json
import os
import time
from pathlib import Path

from meme_machine.postgrad import (
    PostGraduationAdapter, buy_quote, graduation_handoff, pumpswap_pool, sell_quote,
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
            report['samples'][surface] = dict(
                success=False, mint=mint, surface=surface,
                blocker=str(exc) if str(exc) else type(exc).__name__,
            )
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
