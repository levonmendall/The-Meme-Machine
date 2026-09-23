"""Bounded, read-only capability probes. Never infer support from another chain.

Run after the existing contention guard and deterministic gate, before lane launch.
Transient transport/5xx failures get one bounded retry against the same endpoint.
The probe remains fail-closed and persists every hashed endpoint result before exit.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

TRANSIENT_PROBE_BOUNDARIES=frozenset({
    'provider_transport_failure',
    'provider_http_500',
    'provider_http_502',
    'provider_http_503',
    'provider_http_504',
})


def _boundary_code(exc):
    """Return only a stable boundary/type code; never stringify arbitrary URLs."""
    try:
        from robinhood_research import BoundaryError
    except ImportError:
        BoundaryError=()
    return str(exc) if BoundaryError and isinstance(exc,BoundaryError) else type(exc).__name__


def _same_endpoint_retry(operation,retries):
    """Retry once only for approved transient transport/5xx boundaries."""
    try:
        return operation()
    except Exception as exc:
        code=_boundary_code(exc)
        if code not in TRANSIENT_PROBE_BOUNDARIES:
            raise
        retries.append(dict(reason=code,attempt=1,delay_seconds=0.1))
        time.sleep(0.1)
        return operation()


def probe(rpc, *, require_public_observation=False):
    retries=[]
    _same_endpoint_retry(rpc.verify_chain,retries)
    frontier=_same_endpoint_retry(
        lambda:rpc.call('eth_getBlockByNumber',['finalized',False],scope='capability_probe'),
        retries)
    report=dict(
        frontier={k:frontier[k] for k in ('number','hash','timestamp')},
        methods={},
        started_at=time.time(),
    )
    if require_public_observation:
        logs=_same_endpoint_retry(
            lambda:rpc.call('eth_getLogs',[{
                'fromBlock':frontier['number'],
                'toBlock':frontier['number'],
                'address':'0x0000000000000000000000000000000000000000',
            }],scope='public_observation_probe'),
            retries)
        if not isinstance(logs,list):
            raise RuntimeError('public_observation_logs_shape')
        report['public_observation']=dict(
            chain_authenticated=True,
            finalized_block=frontier['number'],
            bounded_log_read=True,
            log_rows=len(logs),
        )
    # Fixed zero-value empty-code simulation. No signing/submission, no authority.
    call=dict(to='0x0000000000000000000000000000000000000000',data='0x')
    cases=[
        ('eip1898_eth_getCode',[call['to'],{'blockHash':frontier['hash']}]),
        ('eip1898_eth_call',[call,{'blockHash':frontier['hash']}]),
        ('eth_callMany',[[{'transactions':[dict(to=call['to'],input='0x')]}],
                         {'blockNumber':frontier['number'],'transactionIndex':-1},{},1000]),
    ]
    transactions=frontier.get('transactions')
    if isinstance(transactions,list) and len(transactions)<=128:
        cases.append(('eth_getBlockReceipts',[frontier['hash']]))
    else:
        report['methods']['eth_getBlockReceipts']=dict(
            supported=None,reason='probe_response_size_guard')
    for method,params in cases:
        started=time.monotonic()
        try:
            value=_same_endpoint_retry(
                lambda m=method,p=params:rpc.call(
                    m.removeprefix('eip1898_'),p,scope='capability_probe'),
                retries)
            if method.startswith('eip1898_'):
                row=dict(supported=value=='0x',reason='empty_code_exact_hash_probe')
            elif method=='eth_callMany':
                valid=(isinstance(value,list) and len(value)==1 and isinstance(value[0],list)
                    and len(value[0])==1 and value[0][0].get('value')=='0x')
                row=dict(
                    supported=valid,
                    semantic_equivalence_for_strategy_calls=False,
                    reason='empty_code_probe_only; sequential simulations not automatically interchangeable with independent calls',
                )
            else:
                valid=(isinstance(value,list) and len(value)==len(transactions)
                    and all(isinstance(r,dict) and r.get('blockHash')==frontier['hash']
                            for r in value))
                valid=valid and {r.get('transactionHash') for r in value}==set(transactions)
                row=dict(
                    supported=valid,
                    reason='validated_block_and_transaction_census'
                           if valid else 'response_identity_mismatch',
                )
            row['response']=value
            row['request']=dict(method=method,params=params)
            row['response_sha256']=hashlib.sha256(
                json.dumps(value,sort_keys=True).encode()).hexdigest()
        except Exception as exc:
            code=_boundary_code(exc)
            row=dict(
                supported=False if code in ('provider_rpc_-32601','provider_rpc_-32602') else None,
                reason=code,
            )
        row['latency_seconds']=time.monotonic()-started
        report['methods'][method]=row
    report.update(
        ended_at=time.time(),
        provider=rpc.telemetry(),
        transient_retries=retries,
        passed=True,
    )
    return report


def required_probe(factory, *, roles, require_public_observation=False):
    """Return a complete row even when a required endpoint cannot be proven."""
    started=time.time();rpc=None
    try:
        rpc=factory()
        row=probe(rpc,require_public_observation=require_public_observation)
        row.update(required=True,roles=sorted(roles),passed=True)
        return row
    except Exception as exc:
        row=dict(
            required=True,
            roles=sorted(roles),
            passed=False,
            failure=_boundary_code(exc),
            started_at=started,
            ended_at=time.time(),
        )
        if rpc is not None:
            try:
                row['provider']=rpc.telemetry()
            except Exception as telemetry_exc:
                row['provider_telemetry_error']=type(telemetry_exc).__name__
        return row


def persist_results(output,results):
    """Persist every endpoint identity before returning aggregate gate status."""
    failures=sorted(identity for identity,row in results.items()
                    if row.get('required') is True and row.get('passed') is not True)
    payload=dict(
        observed_at=time.time(),
        passed=not failures,
        failed_endpoint_identities=failures,
        endpoints=results,
    )
    path=Path(output);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(payload,sort_keys=True,indent=2)+'\n')
    return payload


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--worktrees',required=True)
    p.add_argument('--output',required=True)
    a=p.parse_args()

    sys.path.insert(0,str(Path(a.worktrees)/'pons'))
    from robinhood_research.provider_topology import (
        configured_rpc,public_diagnostic_rpc,PUBLIC_DIAGNOSTIC_RPC_URL)
    from robinhood_research import CHAIN_ID

    configured={}
    for variable,role in (
        ('MM_ROBINHOOD_READ_RPC_URL','configured_read'),
        ('MM_ROBINHOOD_DLMM_RPC_URL','configured_dlmm'),
    ):
        endpoint=os.environ.get(variable)
        if endpoint:
            configured.setdefault(endpoint,set()).add(role)

    results={}
    # Stable ordering makes the persisted report reproducible while identities
    # remain secret-safe hashes of chain id + endpoint.
    for endpoint in sorted(configured):
        identity=hashlib.sha256((str(CHAIN_ID)+':'+endpoint).encode()).hexdigest()
        results[identity]=required_probe(
            lambda endpoint=endpoint:configured_rpc(
                endpoint,limit=12,per_scope=12,retries=0,timeout=3),
            roles=configured[endpoint],
        )

    public_identity=hashlib.sha256(
        (str(CHAIN_ID)+':'+PUBLIC_DIAGNOSTIC_RPC_URL).encode()).hexdigest()
    results[public_identity]=required_probe(
        lambda:public_diagnostic_rpc(limit=12,per_scope=12,retries=0),
        roles={'public_observation_diagnostic'},
        require_public_observation=True,
    )

    payload=persist_results(a.output,results)
    if not payload['passed']:
        raise SystemExit(1)


if __name__=='__main__':
    main()
