"""Bounded finalized Pons V2->V4 and Pons V1->V3 lineage capture.

This is a certification probe, not discovery authority.  It deliberately targets one
recent V2 graduation and one historical V1 launch, then authenticates every relevant
event through its receipt/header and the pinned deployed contract compilations.
"""
import base64
import json
import os
from pathlib import Path
import time
import zlib

from . import BoundaryError
from .abi import calldata, topic, signature
from .identity import authenticate, load
from .pons import (
    factory_record, raw_event, prove_v4_lineage, prove_v1_v3_lineage,
)
from .provider import Rpc

WINDOW=2000
V2_WINDOWS=40
V1_WINDOWS=80


def _event_topic(role,name):
    rows=[a for a in load(role)['abi'] if a.get('type')=='event' and a.get('name')==name]
    if len(rows)!=1:
        raise BoundaryError('lineage_event_abi_missing')
    return topic(signature(rows[0]))


def _scan_backward(rpc,address,event_topic,end):
    scans=[]
    for index in range(V2_WINDOWS):
        hi=end-index*WINDOW
        lo=max(0,hi-WINDOW+1)
        rows=rpc.call('eth_getLogs',[dict(
            fromBlock=hex(lo),toBlock=hex(hi),address=address,topics=[event_topic]
        )],scope='pons')
        scans.append(dict(direction='backward',from_block=lo,to_block=hi,count=len(rows)))
        if rows:
            return rows[-1],scans
        if lo==0:
            break
    return None,scans


def _scan_forward(rpc,address,event_topic,start,end):
    scans=[]
    for index in range(V1_WINDOWS):
        lo=start+index*WINDOW
        if lo>end:
            break
        hi=min(end,lo+WINDOW-1)
        rows=rpc.call('eth_getLogs',[dict(
            fromBlock=hex(lo),toBlock=hex(hi),address=address,topics=[event_topic]
        )],scope='pons')
        scans.append(dict(direction='forward',from_block=lo,to_block=hi,count=len(rows)))
        if rows:
            return rows[0],scans
    return None,scans


def _decode_receipt_events(rpc,raw_log,addresses,role_for,report):
    receipt=rpc.receipt(raw_log['transactionHash'],raw_log['blockHash'],scope='pons')
    report['receipts'].append(receipt)
    bh=raw_log['blockHash']
    if bh not in report['headers']:
        block=rpc.call('eth_getBlockByHash',[bh,False],scope='pons')
        report['headers'][bh]={k:block[k] for k in ('hash','number','timestamp','parentHash')}
    header=report['headers'][bh]
    decoded=[]
    for event in receipt['logs']:
        role=role_for.get(event['address'].lower())
        if not role:
            continue
        try:
            row=raw_event(
                load(role)['abi'],event,address=event['address'],receipt=receipt,
                header=header,observed_at=time.time(),confirmation='finalized',
            )
            row['role']=role
            decoded.append(row)
        except BoundaryError as exc:
            if str(exc) not in ('unsupported_event_signature','unsupported_dynamic_event'):
                raise
    report['events'].extend(decoded)
    return decoded


def _record(rpc,role,address,token,end,report):
    raw=rpc.call(
        'eth_call',
        [dict(to=address,data=calldata('getLaunchedToken(address)',token)),hex(end)],
        scope='pons',
    )
    report['reads'].append(dict(
        role=role,address=address,token=token,block=end,value=raw,observed_at=time.time(),
    ))
    return factory_record(raw,role)


def run(endpoint):
    rpc=Rpc(endpoint,limit=200,per_scope=190,retries=0)
    report=dict(
        kind='captured_finalized_pons_lineage_v2',
        started_at=time.time(),identities={},headers={},receipts=[],events=[],reads=[],
        scans=[],v2_lineages=[],v1_lineages=[],provider=None,
    )
    roles=[
        'pons_v2_factory','pons_v2_hook','pons_deployer','pons_executor',
        'uniswap_v4_manager','pons_v1_factory','uniswap_v3_factory',
    ]
    addresses={role:load(role)['address'].lower() for role in roles}
    role_for={address:role for role,address in addresses.items()}
    try:
        rpc.verify_chain()
        frontier=rpc.call('eth_getBlockByNumber',['finalized',False],scope='pons')
        end=int(frontier['number'],16)
        report['frontier']={k:frontier[k] for k in ('hash','number','timestamp','parentHash')}

        for role,address in addresses.items():
            code=rpc.call('eth_getCode',[address,hex(end)],scope='pons')
            report['identities'][role]=authenticate(role,address,code)

        # V2: a completed graduation must bind factory PoolGraduated, hook
        # PoolRegistered and V4 PoolManager Initialize in one authenticated receipt.
        v2_log,v2_scans=_scan_backward(
            rpc,addresses['pons_v2_factory'],_event_topic('pons_v2_factory','PoolGraduated'),end,
        )
        report['scans'].extend(v2_scans)
        if v2_log is None:
            raise BoundaryError('no_v2_graduation_in_bounded_scan')
        siblings=_decode_receipt_events(rpc,v2_log,addresses,role_for,report)
        graduation=next((e for e in siblings
                         if e['role']=='pons_v2_factory' and e['decoded']['name']=='PoolGraduated'),None)
        if graduation is None:
            raise BoundaryError('v2_graduation_receipt_missing')
        token=graduation['decoded']['args']['token']
        record=_record(rpc,'pons_v2_factory',addresses['pons_v2_factory'],token,end,report)
        registration=next((e for e in siblings
                           if e['role']=='pons_v2_hook'
                           and e['decoded']['name']=='PoolRegistered'
                           and e['decoded']['args']['memecoin']==token),None)
        initialization=next((e for e in siblings
                             if e['role']=='uniswap_v4_manager'
                             and e['decoded']['name']=='Initialize'
                             and registration
                             and e['decoded']['args']['id']==registration['decoded']['args']['poolId']),None)
        if registration is None or initialization is None:
            raise BoundaryError('v2_graduation_lineage_event_missing')
        report['v2_lineages'].append(prove_v4_lineage(
            record=record,registration=registration,initialization=initialization,
            graduation=graduation,hook=addresses['pons_v2_hook'],
            manager=addresses['uniswap_v4_manager'],
        ))

        # V1: use the exact Sourcify deployment block, then require the Pons
        # TokenLaunched and Uniswap V3 PoolCreated to occur in the same receipt.
        v1_start=int(load('pons_v1_factory')['deployment']['blockNumber'])
        v1_log,v1_scans=_scan_forward(
            rpc,addresses['pons_v1_factory'],_event_topic('pons_v1_factory','TokenLaunched'),
            v1_start,end,
        )
        report['scans'].extend(v1_scans)
        if v1_log is None:
            raise BoundaryError('no_v1_launch_in_bounded_scan')
        siblings=_decode_receipt_events(rpc,v1_log,addresses,role_for,report)
        launch=next((e for e in siblings
                     if e['role']=='pons_v1_factory' and e['decoded']['name']=='TokenLaunched'),None)
        if launch is None:
            raise BoundaryError('v1_launch_receipt_missing')
        token=launch['decoded']['args']['token']
        record=_record(rpc,'pons_v1_factory',addresses['pons_v1_factory'],token,end,report)
        pool_created=next((e for e in siblings
                           if e['role']=='uniswap_v3_factory'
                           and e['decoded']['name']=='PoolCreated'
                           and e['decoded']['args']['pool']==launch['decoded']['args']['pool']),None)
        if pool_created is None:
            raise BoundaryError('v1_v3_poolcreated_missing')
        report['v1_lineages'].append(prove_v1_v3_lineage(
            record=record,launch=launch,pool_created=pool_created,
            factory=addresses['pons_v1_factory'],v3_factory=addresses['uniswap_v3_factory'],
        ))
    except BoundaryError as exc:
        report['boundary']=str(exc)
    report['provider']=rpc.telemetry()
    report['ended_at']=time.time()
    return report


if __name__=='__main__':
    result=run(os.environ.get('MM_ROBINHOOD_READ_RPC_URL',''))
    raw=json.dumps(result,sort_keys=True,separators=(',',':')).encode()
    if len(raw)>2_000_000:
        raise BoundaryError('report_capacity')
    Path('robinhood-pons-lineage-report.json').write_bytes(raw)
    print(json.dumps(dict(
        boundary=result.get('boundary'),
        v2_lineages=result.get('v2_lineages',[]),
        v1_lineages=result.get('v1_lineages',[]),
        provider=result['provider'],
    )))
    data=base64.b64encode(zlib.compress(raw,9)).decode()
    for i in range(0,len(data),6000):
        print('PUBLIC_EVIDENCE_CHUNK '+str(i//6000)+' '+data[i:i+6000])
