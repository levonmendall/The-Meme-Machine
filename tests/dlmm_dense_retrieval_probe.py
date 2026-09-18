"""Targeted historical proof of the formerly failing 14-body STONK interval."""
from __future__ import annotations
import json, os
from pathlib import Path

from meme_machine import dlmm,pump
from meme_machine.dlmm_tape import _keys
from meme_machine.postgrad import PoolScanRPC
from tests import dlmm_alchemy_provider as alchemy_provider
from meme_machine.provider import Unavailable
from meme_machine.store import encode
from tests import dlmm_boundary_acquisition as boundary

POOL='zxTpi4BtaWX3mgdAPoezkMD1hxx8CdeCfrqXMWvSCLX'
START_SLOT=447932477
END_SLOT=447932489
EXPECTED=14
OUT=Path('dlmm-dense-retrieval-proof.json')


class HistoricalDenseRPC(PoolScanRPC):
    ALLOWED=PoolScanRPC.ALLOWED|{'getBlock'}


def _account_keys(row):
    tx=(row or {}).get('transaction') or {}
    result=[]
    for item in tx.get('accountKeys') or []:
        key=item.get('pubkey') if isinstance(item,dict) else item
        if isinstance(key,str): result.append(key)
    return result


def run():
    rpc=HistoricalDenseRPC(alchemy_provider.rpc_url(),limit=100)
    if rpc.call('getGenesisHash',priority=True)!=pump.MAINNET:
        raise Unavailable('dense_retrieval_wrong_network')

    selected=[];blocks=[]
    for slot in range(START_SLOT+1,END_SLOT+1):
        if slot>START_SLOT+1: rpc.sleep(1.0)
        block=rpc.call('getBlock',[slot,dict(
            commitment='finalized',encoding='json',transactionDetails='accounts',
            maxSupportedTransactionVersion=0,rewards=False)],True)
        if block is None: raise Unavailable('dense_retrieval_missing_block')
        matched=0
        for transaction_index,row in enumerate(block.get('transactions') or []):
            if (row.get('meta') or {}).get('err') or POOL not in _account_keys(row):
                continue
            signatures=((row.get('transaction') or {}).get('signatures') or [])
            if not signatures or not isinstance(signatures[0],str):
                raise Unavailable('dense_retrieval_signature_shape')
            selected.append(dict(signature=signatures[0],slot=slot,
                                 transactionIndex=transaction_index,err=None,
                                 confirmationStatus='finalized'))
            matched+=1
        blocks.append(dict(slot=slot,matching_successful_transactions=matched,
                           transaction_rows=len(block.get('transactions') or [])))
    if len(selected)!=EXPECTED:
        raise Unavailable(f'dense_retrieval_expected_{EXPECTED}_got_{len(selected)}')

    telemetry={}
    values=boundary._fetch_transaction_bodies(rpc,selected,telemetry)
    if len(values)!=EXPECTED or any(value is None for value in values):
        raise Unavailable('dense_retrieval_incomplete_bodies')
    transactions={}
    for sig,tx in zip(selected,values):
        if (not tx or tx.get('slot')!=sig['slot'] or
            ((tx.get('transaction') or {}).get('signatures') or [None])[0]!=sig['signature'] or
            not tx.get('meta') or tx['meta'].get('err')):
            raise Unavailable('dense_retrieval_body_identity')
        message=(tx.get('transaction') or {}).get('message') or {}
        if POOL not in _keys(tx['meta'],message):
            raise Unavailable('dense_retrieval_pool_identity')
        transactions[sig['signature']]=tx
    size=len(encode(transactions))
    if size>2_000_000: raise Unavailable('dlmm_interval_evidence_bound')

    report=dict(
        kind='dlmm_dense_14_transaction_retrieval_proof_v1',
        allocation_authority=False,pool=POOL,start_slot=START_SLOT,end_slot=END_SLOT,
        expected_transactions=EXPECTED,recovered_transactions=len(selected),
        retrieval=telemetry,blocks=blocks,evidence_bytes=size,
        rpc_calls=rpc.calls,rpc_http_requests=rpc.http_requests,
        rpc_failures=rpc.failures,rpc_retries=rpc.retries,
        provider_failure_kinds=rpc.failure_kinds,
        provider_failure_methods=rpc.failure_methods,
        rpc_batch_fallbacks=rpc.batch_fallbacks,
        rpc_batch_fallback_items=rpc.batch_fallback_items,
    )
    OUT.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps(dict(
        recovered_transactions=len(selected),
        retrieval_mode=telemetry.get('transaction_retrieval_mode'),
        rpc_calls=rpc.calls,rpc_http_requests=rpc.http_requests,
        rpc_failures=rpc.failures,rpc_retries=rpc.retries,evidence_bytes=size),
        sort_keys=True))
    return report

if __name__=='__main__': run()
