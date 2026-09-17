"""Bounded read-only probe for the authentic USELESS-SOL `last_update` mutation.

This diagnostic has no Store/allocation authority. It captures one finalized start/end
pair, the complete bounded pool transaction set between them, and only the Meteora
instruction discriminators/order/account positions needed to identify a mutation.
No economics are inferred from an unverified interval.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

from meme_machine import dlmm
from meme_machine.dlmm_tape import _instruction_pool_positions,_keys,_ordered_instructions,_un58_data
from meme_machine.postgrad import PoolScanRPC
from meme_machine.provider import Unavailable

POOL='8ztFxjFPfVUtEf4SLSapcFj8GW2dxyUA9no2bLPq7H7V'  # USELESS-SOL
OUT=Path('dlmm-mutation-probe.json')
MAX_TX=16


def _idl_names():
    raw=json.loads(Path('tests/fixtures/dlmm_idl_subset.json').read_text())
    result={}
    for item in raw.get('instructions',[]):
        disc=item.get('discriminator')
        if isinstance(disc,list) and len(disc)==8:
            result[bytes(disc).hex()]=item.get('name')
    return result


def _scalar_delta(start,end):
    ignored={'bins','time','slot'}
    result={}
    for key in sorted((set(start)|set(end))-ignored):
        if start.get(key)!=end.get(key):
            a=start.get(key);b=end.get(key)
            if isinstance(a,(str,int,float,bool,type(None))) and isinstance(b,(str,int,float,bool,type(None))):
                result[key]=dict(start=a,end=b)
            elif key=='parameters':
                result[key]=dict(start=a,end=b)
    return result


def run(wait_seconds=20):
    if not 5<=wait_seconds<=30:raise ValueError('dlmm_mutation_probe_wait_bound')
    rpc=PoolScanRPC('https://api.mainnet-beta.solana.com',limit=160)
    adapter=dlmm.Adapter(rpc)
    start_snap=adapter.snapshot(POOL,int(time.time()),True)
    start=dlmm.validate(start_snap,start_snap['available_time'],'real')
    time.sleep(wait_seconds)
    end_snap=adapter.snapshot(POOL,int(time.time()),True)
    end=dlmm.validate(end_snap,end_snap['available_time'],'real')
    sigs=rpc.call('getSignaturesForAddress',[POOL,dict(limit=64,commitment='finalized')],True)
    selected=[s for s in sigs if start['slot']<s['slot']<=end['slot'] and not s.get('err')]
    if len(selected)>MAX_TX:raise Unavailable('dlmm_mutation_probe_transaction_bound')
    params=[[s['signature'],dict(encoding='json',commitment='finalized',maxSupportedTransactionVersion=0)] for s in selected]
    txs=rpc.call_many('getTransaction',params,True,batch_size=4)
    names=_idl_names();transactions=[]
    for sig,tx in zip(selected,txs):
        if not tx or not tx.get('meta') or tx['meta'].get('err'):raise Unavailable('dlmm_mutation_probe_missing_tx')
        meta=tx['meta'];message=tx['transaction']['message'];keys=_keys(meta,message);items=[]
        for outer,inner,ix in _ordered_instructions(meta,message):
            if keys[ix['programIdIndex']]!=dlmm.PROGRAM:continue
            data=_un58_data(ix['data']);disc=data[:8].hex() if len(data)>=8 else data.hex()
            positions=_instruction_pool_positions(ix,keys,POOL)
            accounts=ix.get('accounts') or []
            items.append(dict(
                outer=outer,inner=inner,discriminator=disc,name=names.get(disc),
                pool_positions=positions,
                account0=(keys[accounts[0]] if accounts and isinstance(accounts[0],int) and 0<=accounts[0]<len(keys) else None),
                account_count=len(accounts),
            ))
        transactions.append(dict(
            signature=sig['signature'],slot=sig['slot'],transactionIndex=sig.get('transactionIndex'),
            blockTime=tx.get('blockTime'),meteora_instructions=items,
        ))
    report=dict(
        kind='dlmm_useless_last_update_mutation_probe_v1',allocation_authority=False,
        pool=POOL,wait_seconds=wait_seconds,start_slot=start['slot'],end_slot=end['slot'],
        start_time=start['time'],end_time=end['time'],scalar_delta=_scalar_delta(start,end),
        relevant_transactions=len(selected),transactions=transactions,
        rpc_calls=rpc.calls,rpc_http_requests=rpc.http_requests,rpc_failures=rpc.failures,
        rpc_retries=rpc.retries,provider_failure_kinds=rpc.failure_kinds,
    )
    OUT.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps(dict(pool=POOL,start_slot=start['slot'],end_slot=end['slot'],
                          relevant_transactions=len(selected),scalar_delta=report['scalar_delta'],
                          rpc_failures=rpc.failures),sort_keys=True))
    return report


def main():
    p=argparse.ArgumentParser();p.add_argument('--wait-seconds',type=int,default=20);a=p.parse_args();run(a.wait_seconds)

if __name__=='__main__':main()
