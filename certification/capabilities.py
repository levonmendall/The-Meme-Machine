"""Bounded, read-only capability probes. Never infer support from another chain.

Run after the existing contention guard and deterministic gate, before lane launch.
No throughput increase: use the configured existing role and pacing unchanged.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

def probe(rpc):
    rpc.verify_chain()
    frontier=rpc.call('eth_getBlockByNumber',['finalized',False],scope='capability_probe')
    report=dict(frontier={k:frontier[k] for k in ('number','hash','timestamp')},methods={},started_at=time.time())
    # Fixed zero-value empty-code simulation. No signing/submission, no authority.
    call=dict(to='0x0000000000000000000000000000000000000000',data='0x')
    cases=[('eip1898_eth_getCode',[call['to'],{'blockHash':frontier['hash']}]),
           ('eip1898_eth_call',[call,{'blockHash':frontier['hash']}]),('eth_callMany',[[{'transactions':[dict(to=call['to'],input='0x')]}],
                          {'blockNumber':frontier['number'],'transactionIndex':-1},{},1000])]
    transactions=frontier.get('transactions')
    if isinstance(transactions,list) and len(transactions)<=128:
        cases.append(('eth_getBlockReceipts',[frontier['hash']]))
    else:report['methods']['eth_getBlockReceipts']=dict(supported=None,reason='probe_response_size_guard')
    for method,params in cases:
        started=time.monotonic()
        try:
            value=rpc.call(method.removeprefix('eip1898_'),params,scope='capability_probe')
            if method.startswith('eip1898_'):
                row=dict(supported=value=='0x',reason='empty_code_exact_hash_probe')
            elif method=='eth_callMany':
                valid=(isinstance(value,list) and len(value)==1 and isinstance(value[0],list)
                    and len(value[0])==1 and value[0][0].get('value')=='0x')
                row=dict(supported=valid,semantic_equivalence_for_strategy_calls=False,
                    reason='empty_code_probe_only; sequential simulations not automatically interchangeable with independent calls')
            else:
                valid=isinstance(value,list) and len(value)==len(transactions) and all(isinstance(r,dict) and r.get('blockHash')==frontier['hash'] for r in value)
                valid=valid and {r.get('transactionHash') for r in value}==set(transactions)
                row=dict(supported=valid,reason='validated_block_and_transaction_census' if valid else 'response_identity_mismatch')
            row['response']=value
            row['request']=dict(method=method,params=params)
            row['response_sha256']=hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()
        except Exception as exc:
            # Stable boundary codes only; never stringify arbitrary exception/URL.
            from robinhood_research import BoundaryError
            code=str(exc) if isinstance(exc,BoundaryError) else type(exc).__name__
            row=dict(supported=False if code in ('provider_rpc_-32601','provider_rpc_-32602') else None,reason=code)
        row['latency_seconds']=time.monotonic()-started;report['methods'][method]=row
    report.update(ended_at=time.time(),provider=rpc.telemetry())
    return report

def main():
    p=argparse.ArgumentParser();p.add_argument('--worktrees',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    sys.path.insert(0,str(Path(a.worktrees)/'pons'))
    from robinhood_research.provider_topology import configured_rpc
    from robinhood_research import CHAIN_ID
    endpoints={os.environ.get(k) for k in ('MM_ROBINHOOD_READ_RPC_URL','MM_ROBINHOOD_DLMM_RPC_URL') if os.environ.get(k)}
    results={}
    for endpoint in endpoints:
        identity=hashlib.sha256((str(CHAIN_ID)+':'+endpoint).encode()).hexdigest()
        results[identity]=probe(configured_rpc(endpoint,limit=12,per_scope=12,retries=0,timeout=3))
    Path(a.output).write_text(json.dumps(dict(observed_at=time.time(),endpoints=results),sort_keys=True,indent=2)+'\n')
if __name__=='__main__':main()
