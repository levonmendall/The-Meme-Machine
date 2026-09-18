"""Bounded finalized Pons V2->V4 and Pons V1->V3 lineage capture.

External indexes are used only as locators.  Every accepted fact is re-authenticated
against the configured Robinhood RPC, pinned deployed bytecode, block headers,
receipts, factory state and protocol-native pool-creation events.
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
from .pons import factory_record, raw_event, prove_v4_lineage, prove_v1_v3_lineage
from .provider import Rpc

# Locator-only anchors.  They do not enter the proof without full RPC authentication.
V2_GRADUATION_BLOCK=56882711
V2_GRADUATION_TX='0x1d49a28a0e27ecdd952094c4aaa9de2105253a2d62924ec36e761c13e43493c9'
V1_ANCHOR_TOKEN='0xc4cb8a0167c77e36194f6affb6b71d931fab62c0'


def _event_topic(role,name):
    rows=[a for a in load(role)['abi'] if a.get('type')=='event' and a.get('name')==name]
    if len(rows)!=1:
        raise BoundaryError('lineage_event_abi_missing')
    return topic(signature(rows[0]))


def _topic_address(address):
    return '0x'+'0'*24+address.lower()[2:]


def _decode_receipt_events(rpc,receipt,header,addresses,role_for,report):
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


def _first_code_block(rpc,address,low,high,report):
    """Binary-search deployment height using historical eth_getCode."""
    if low<0 or low>=high:
        raise BoundaryError('invalid_code_search_range')
    before=rpc.call('eth_getCode',[address,hex(low)],scope='pons')
    if before!='0x':
        raise BoundaryError('v1_anchor_predates_search_floor')
    probes=0
    left,right=low+1,high
    while left<right:
        mid=(left+right)//2
        code=rpc.call('eth_getCode',[address,hex(mid)],scope='pons')
        probes+=1
        if code=='0x':
            left=mid+1
        else:
            right=mid
    code=rpc.call('eth_getCode',[address,hex(left)],scope='pons')
    probes+=1
    if code=='0x':
        raise BoundaryError('v1_anchor_code_not_found')
    report['code_search']=dict(token=address,low=low,high=high,creation_block=left,probes=probes)
    return left


def run(endpoint):
    rpc=Rpc(endpoint,limit=120,per_scope=110,retries=0)
    report=dict(
        kind='captured_finalized_pons_lineage_v3',
        started_at=time.time(),identities={},headers={},receipts=[],events=[],reads=[],
        v2_lineages=[],v1_lineages=[],provider=None,
        locator_sources=dict(
            v2='public_index_locator_reauthenticated_onchain',
            v1='published_pons_v1_token_locator_reauthenticated_onchain',
        ),
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

        # V2 graduation: the locator supplies only block/tx identity.  The receipt
        # must independently contain the authenticated Pons factory graduation,
        # Pons hook registration and V4 PoolManager initialization.
        v2_block=rpc.call('eth_getBlockByNumber',[hex(V2_GRADUATION_BLOCK),False],scope='pons')
        if int(v2_block['number'],16)!=V2_GRADUATION_BLOCK:
            raise BoundaryError('v2_locator_block_disagreement')
        v2_header={k:v2_block[k] for k in ('hash','number','timestamp','parentHash')}
        report['headers'][v2_header['hash']]=v2_header
        v2_receipt=rpc.receipt(V2_GRADUATION_TX,v2_header['hash'],scope='pons')
        if int(v2_receipt['blockNumber'],16)!=V2_GRADUATION_BLOCK:
            raise BoundaryError('v2_locator_receipt_disagreement')
        report['receipts'].append(v2_receipt)
        siblings=_decode_receipt_events(rpc,v2_receipt,v2_header,addresses,role_for,report)
        graduation=next((e for e in siblings
                         if e['role']=='pons_v2_factory' and e['decoded']['name']=='PoolGraduated'),None)
        if graduation is None:
            raise BoundaryError('v2_graduation_receipt_missing')
        token=graduation['decoded']['args']['token']
        record=_record(rpc,'pons_v2_factory',addresses['pons_v2_factory'],token,end,report)
        registration=next((e for e in siblings
                           if e['role']=='pons_v2_hook' and e['decoded']['name']=='PoolRegistered'
                           and e['decoded']['args']['memecoin']==token),None)
        initialization=next((e for e in siblings
                             if e['role']=='uniswap_v4_manager' and e['decoded']['name']=='Initialize'
                             and registration
                             and e['decoded']['args']['id']==registration['decoded']['args']['poolId']),None)
        if registration is None or initialization is None:
            raise BoundaryError('v2_graduation_lineage_event_missing')
        report['v2_lineages'].append(prove_v4_lineage(
            record=record,registration=registration,initialization=initialization,
            graduation=graduation,hook=addresses['pons_v2_hook'],manager=addresses['uniswap_v4_manager'],
        ))

        # V1: authenticate the public token locator as an actual record in the pinned
        # V1 factory, discover its deployment block by historical bytecode, then
        # require Pons TokenLaunched + Uniswap V3 PoolCreated in the same receipt.
        v1_record=_record(rpc,'pons_v1_factory',addresses['pons_v1_factory'],V1_ANCHOR_TOKEN,end,report)
        if not v1_record.get('exists') or v1_record.get('token')!=V1_ANCHOR_TOKEN:
            raise BoundaryError('v1_anchor_factory_record_missing')
        factory_deploy=int(load('pons_v1_factory')['deployment']['blockNumber'])
        creation=_first_code_block(rpc,V1_ANCHOR_TOKEN,factory_deploy,end,report)
        launch_rows=rpc.call('eth_getLogs',[dict(
            fromBlock=hex(creation),toBlock=hex(creation),
            address=addresses['pons_v1_factory'],
            topics=[_event_topic('pons_v1_factory','TokenLaunched'),_topic_address(V1_ANCHOR_TOKEN)],
        )],scope='pons')
        if len(launch_rows)!=1:
            raise BoundaryError('v1_anchor_launch_log_count')
        raw_launch=launch_rows[0]
        v1_block=rpc.call('eth_getBlockByNumber',[hex(creation),False],scope='pons')
        v1_header={k:v1_block[k] for k in ('hash','number','timestamp','parentHash')}
        if raw_launch['blockHash']!=v1_header['hash']:
            raise BoundaryError('v1_anchor_block_disagreement')
        report['headers'][v1_header['hash']]=v1_header
        v1_receipt=rpc.receipt(raw_launch['transactionHash'],v1_header['hash'],scope='pons')
        report['receipts'].append(v1_receipt)
        siblings=_decode_receipt_events(rpc,v1_receipt,v1_header,addresses,role_for,report)
        launch=next((e for e in siblings
                     if e['role']=='pons_v1_factory' and e['decoded']['name']=='TokenLaunched'
                     and e['decoded']['args']['token']==V1_ANCHOR_TOKEN),None)
        if launch is None:
            raise BoundaryError('v1_launch_receipt_missing')
        pool_created=next((e for e in siblings
                           if e['role']=='uniswap_v3_factory' and e['decoded']['name']=='PoolCreated'
                           and e['decoded']['args']['pool']==launch['decoded']['args']['pool']),None)
        if pool_created is None:
            raise BoundaryError('v1_v3_poolcreated_missing')
        report['v1_lineages'].append(prove_v1_v3_lineage(
            record=v1_record,launch=launch,pool_created=pool_created,
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
