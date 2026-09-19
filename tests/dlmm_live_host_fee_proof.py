"""Bounded current finalized live occurrence proof for Meteora host fees.

Full host-fee arithmetic/reconstruction is already covered by captured/offline
terminal-equality tests. This proof closes only the remaining live-occurrence gap:
observe a current finalized exact-input swap with nonzero host_fee and authenticate
the input-token host account delta through transaction_swaps().
"""
from __future__ import annotations
import json, os
from pathlib import Path

from meme_machine.dlmm_tape import transaction_swaps
from tests import dlmm_alchemy_provider as alchemy_provider
from meme_machine.provider import Unavailable

OUT=Path('dlmm-live-host-fee-proof.json')
POOLS=(
    ('JUP-SOL','C8Gr6AUuq9hEdSYJzoEpNcdjpojPZwqG5MtQbeouNNwg'),
    ('STONK-SOL','zxTpi4BtaWX3mgdAPoezkMD1hxx8CdeCfrqXMWvSCLX'),
    ('USELESS-SOL','8ztFxjFPfVUtEf4SLSapcFj8GW2dxyUA9no2bLPq7H7V'),
)
SIGNATURES_PER_POOL=12
MAX_BODY_READS=36
BODY_PACE_SECONDS=1.5


def run():
    rpc=alchemy_provider.new_rpc(limit=120)
    scanned=[];found=None;body_reads=0
    for name,pool in POOLS:
        try:
            signatures=rpc.call('getSignaturesForAddress',[
                pool,dict(limit=SIGNATURES_PER_POOL,commitment='finalized')],True)
        except Unavailable as exc:
            scanned.append(dict(name=name,pool=pool,signature_rows=0,successful_rows=0,
                                bodies=[],rejections=[dict(reason=str(exc)[:120],
                                stage='signature_census')]))
            continue
        successful=[row for row in signatures
                    if isinstance(row,dict) and not row.get('err')
                    and isinstance(row.get('signature'),str)]
        pool_row=dict(name=name,pool=pool,signature_rows=len(signatures),
                      successful_rows=len(successful),bodies=[],rejections=[])
        scanned.append(pool_row)
        for row in successful:
            if body_reads>=MAX_BODY_READS: break
            if body_reads:
                rpc.sleep(BODY_PACE_SECONDS)
            body_reads+=1
            try:
                tx=rpc.call('getTransaction',[row['signature'],dict(
                    encoding='json',commitment='finalized',
                    maxSupportedTransactionVersion=0)],True)
            except Unavailable as exc:
                pool_row['rejections'].append(dict(
                    signature=row['signature'],reason=str(exc)[:120],
                    stage='transaction_body'))
                continue
            if not tx or not tx.get('meta') or tx['meta'].get('err'):
                pool_row['rejections'].append(dict(
                    signature=row['signature'],reason='missing_or_failed_transaction'))
                continue
            try:
                swaps=transaction_swaps(tx,pool)
            except (Unavailable,ValueError,KeyError,TypeError) as exc:
                pool_row['rejections'].append(dict(
                    signature=row['signature'],reason=str(exc)[:120]))
                continue
            summary=dict(signature=row['signature'],slot=tx.get('slot'),
                         swaps=len(swaps),host_fee_swaps=0)
            for event in swaps:
                host=int((event.get('observed') or {}).get('host_fee',0))
                if host<=0: continue
                summary['host_fee_swaps']+=1
                found=dict(
                    pool=pool,pool_name=name,signature=row['signature'],
                    slot=tx.get('slot'),block_time=tx.get('blockTime'),
                    instruction=event.get('instruction'),
                    amount=event.get('amount'),for_y=event.get('for_y'),
                    host_fee=host,
                    protocol_fee=(event.get('observed') or {}).get('protocol_fee'),
                    total_fee=(event.get('observed') or {}).get('fee'),
                    start_bin=(event.get('observed') or {}).get('start'),
                    end_bin=(event.get('observed') or {}).get('end'),
                    commitment='finalized',
                    host_account_delta_authenticated=True,
                )
                break
            pool_row['bodies'].append(summary)
            if found: break
        if found: break
    report=dict(
        kind='dlmm_live_host_fee_occurrence_proof_v1',
        allocation_authority=False,prospective_allocation_enabled=False,
        current_finalized_host_fee_event=found,
        host_fee_occurrence_proven=found is not None,
        scanned_pools=scanned,body_reads=body_reads,
        signatures_per_pool=SIGNATURES_PER_POOL,max_body_reads=MAX_BODY_READS,
        body_pace_seconds=BODY_PACE_SECONDS,
        rpc_calls=rpc.calls,rpc_http_requests=rpc.http_requests,
        rpc_failures=rpc.failures,rpc_retries=rpc.retries,
        provider_failure_kinds=rpc.failure_kinds,
        provider_failure_methods=rpc.failure_methods,
        provider_topology=rpc.provider_telemetry(),
    )
    OUT.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps(dict(
        host_fee_occurrence_proven=found is not None,
        pool=None if found is None else found['pool_name'],
        body_reads=body_reads,rpc_calls=rpc.calls,
        rpc_failures=rpc.failures,rpc_retries=rpc.retries),sort_keys=True))
    if found is None:
        raise SystemExit('DLMM_LIVE_HOST_FEE_OCCURRENCE_NOT_OBSERVED')
    print('DLMM_LIVE_HOST_FEE_OCCURRENCE_PROOF_PASSED')
    return report

if __name__=='__main__':
    run()