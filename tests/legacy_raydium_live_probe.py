"""Read-only explicit legacy Raydium-v4 current-pair proof.

The legacy Pump->Raydium migration transaction itself is not reconstructed here.  The
pool comes from the checked research registry, is revalidated fully on chain, and stays
allocation-ineligible.  No transaction creation, signing or submission exists.
"""
from dataclasses import asdict
import json
import os
import time
from pathlib import Path

from meme_machine.legacy_raydium import LegacyRaydiumProvenance, read_explicit_pool
from meme_machine.postgrad import PostGraduationAdapter, buy_quote, graduation_handoff, sell_quote
from meme_machine.solana_read_rpc import new_rpc, new_pool_scan_rpc

REGISTRY = Path('evidence/legacy_raydium_pool_registry.json')
CAPTURE = Path('legacy-raydium-live-capture.json')
REPORT = Path('legacy-raydium-live-report.json')
QUOTE_BUDGET_LAMPORTS = 100_000_000


def main():
    doc = json.loads(REGISTRY.read_text())
    if doc.get('authority') != 'read-only research only; never selects or authorizes a trade':
        raise ValueError('legacy_registry_authority')
    records = doc.get('records') or []
    if len(records) != 1:
        raise ValueError('bounded_legacy_registry_required')
    record = records[0]
    provenance = LegacyRaydiumProvenance(
        mint=record['mint'],
        pool=record['pool'],
        current_pair_identity_verified=bool(record['current_pair_identity_verified']),
        direct_pump_withdraw_lineage_verified=bool(record['direct_pump_withdraw_lineage_verified']),
        source_label='legacy-raydium-pool-provenance-v1',
    )
    if record.get('allocation_eligible') or provenance.allocation_eligible:
        raise ValueError('legacy_registry_cannot_authorize_allocation')

    rpc = new_rpc(limit=120)
    scan_rpc = new_pool_scan_rpc(limit=40, pacer=rpc.read_pacer)
    adapter = PostGraduationAdapter(rpc, scan_rpc=scan_rpc)
    started = int(time.time())
    graduation = adapter.graduation_snapshot(provenance.mint, started, priority=True)
    handoff = graduation_handoff(graduation, int(time.time()))
    snapshot = read_explicit_pool(adapter, handoff, provenance, int(time.time()), priority=True)
    buy = buy_quote(snapshot, QUOTE_BUDGET_LAMPORTS)
    sell = sell_quote(snapshot, buy.output_amount)

    report = dict(
        kind='legacy_raydium_explicit_read_only_probe',
        success=True,
        mint=provenance.mint,
        pool=provenance.pool,
        surface=snapshot['surface'],
        model=snapshot['model'],
        graduation_slot=handoff.source_slot,
        snapshot_slot=snapshot['slot'],
        quote_age_seconds=max(0, int(time.time())-snapshot['market_time']),
        token_reserve=snapshot['state']['base_reserve'],
        sol_reserve_lamports=snapshot['state']['quote_reserve'],
        swap_fee_numerator=snapshot['state']['fee_numerator'],
        swap_fee_denominator=snapshot['state']['fee_denominator'],
        buy_budget_lamports=QUOTE_BUDGET_LAMPORTS,
        buy_token_units=buy.output_amount,
        buy_fee_input_units=buy.fee_amount,
        immediate_roundtrip_lamports=sell.output_amount,
        immediate_roundtrip_loss_lamports=buy.input_amount-sell.output_amount,
        current_pair_identity_verified=snapshot['source']['current_pair_identity_verified'],
        direct_pump_withdraw_lineage_verified=snapshot['source']['direct_pump_withdraw_lineage_verified'],
        allocation_eligible=False,
        order_authority=False,
        signing_authority=False,
        transaction_submission_authority=False,
        live_money_authority=False,
        profitability_evidence=False,
        provider_spend_usd=0 if (rpc.failover_count + scan_rpc.failover_count)==0 else None,
        infrastructure_spend_usd=0,
        rpc_requests=rpc.calls,
        rpc_failures=rpc.failures,
        rpc_retries=rpc.retries,
        provider_topology=rpc.provider_telemetry(),
        scan_provider_topology=scan_rpc.provider_telemetry(),
        started=started,
        ended=int(time.time()),
        limitation=record['verification']['limitation'],
    )
    capture = dict(
        kind='captured_mainnet_legacy_raydium_read',
        captured_at=int(time.time()),
        registry_record=record,
        graduation=graduation,
        handoff=asdict(handoff),
        snapshot=snapshot,
        quote=dict(buy=asdict(buy), sell=asdict(sell)),
    )
    REPORT.write_text(json.dumps(report, sort_keys=True))
    CAPTURE.write_text(json.dumps(capture, sort_keys=True))
    print(json.dumps(report, sort_keys=True))


if __name__ == '__main__':
    main()