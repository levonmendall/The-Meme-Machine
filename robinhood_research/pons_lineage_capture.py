"""Bounded finalized Pons launch/graduation capture, independently of Ramses."""
import base64
import json
import os
from pathlib import Path
import time
import zlib
from . import BoundaryError
from .abi import calldata, decode_event, topic, signature
from .identity import authenticate, load
from .pons import factory_record, raw_event, prove_v4_lineage
from .provider import Rpc


def run(endpoint):
    rpc=Rpc(endpoint,limit=200,per_scope=180,retries=0)
    r=dict(kind='captured_finalized_pons_lineage',started_at=time.time(),identities={},logs=[],receipts=[],headers={},records={},lineages=[],reads=[])
    roles=['pons_v2_factory','pons_v2_hook','pons_deployer','pons_executor','uniswap_v4_manager','pons_v1_factory','uniswap_v3_factory']
    addresses={role:load(role)['address'].lower() for role in roles}
    try:
        rpc.verify_chain()
        header=rpc.call('eth_getBlockByNumber',['finalized',False]);end=int(header['number'],16)
        r['frontier']={k:header[k] for k in ('hash','number','timestamp','parentHash')}
        for role,address in addresses.items():
            r['identities'][role]=authenticate(role,address,rpc.call('eth_getCode',[address,hex(end)],scope='pons'))
        wanted=[]
        for role in ('pons_v2_factory','pons_v2_hook','pons_v1_factory'):
            for a in load(role)['abi']:
                if a['type']=='event' and a['name'] in ('TokenLaunched','PoolGraduated','PoolRegistered'):
                    wanted.append(topic(signature(a)))
        for first in range(end-999,end+1,10):
            r['logs']+=rpc.call('eth_getLogs',[dict(fromBlock=hex(first),toBlock=hex(first+9),
                address=[addresses[x] for x in ('pons_v2_factory','pons_v2_hook','pons_v1_factory')],topics=[wanted])],scope='pons')
            if len(r['logs'])>100:
                raise BoundaryError('lineage_log_capacity')
        txs=list(dict.fromkeys(e['transactionHash'] for e in r['logs']))
        if len(txs)>20:
            raise BoundaryError('lineage_receipt_capacity')
        role_for={v:k for k,v in addresses.items()}
        events=[]
        for tx in txs:
            sample=next(e for e in r['logs'] if e['transactionHash']==tx)
            receipt=rpc.receipt(tx,sample['blockHash'],scope='pons');r['receipts'].append(receipt)
            bh=sample['blockHash']
            if bh not in r['headers']:
                b=rpc.call('eth_getBlockByHash',[bh,False],scope='pons')
                r['headers'][bh]={k:b[k] for k in ('hash','number','timestamp','parentHash')}
            for event in receipt['logs']:
                role=role_for.get(event['address'].lower())
                if role:
                    try:
                        e=raw_event(load(role)['abi'],event,address=event['address'],receipt=receipt,
                            header=r['headers'][bh],observed_at=time.time(),confirmation='finalized')
                        e['role']=role;events.append(e)
                    except BoundaryError as exc:
                        if str(exc) not in ('unsupported_event_signature','unsupported_dynamic_event'):
                            raise
        r['events']=events
        for event in events:
            if event['decoded']['name'] not in ('PoolGraduated','TokenLaunched'):
                continue
            role=event['role'];token=event['decoded']['args']['token']
            if token not in r['records']:
                raw=rpc.call('eth_call',[dict(to=addresses[role],data=calldata('getLaunchedToken(address)',token)),hex(end)],scope='pons')
                r['reads'].append(dict(address=addresses[role],token=token,block=end,value=raw,observed_at=time.time()))
                r['records'][token]=factory_record(raw,role)
            if event['decoded']['name']=='PoolGraduated':
                siblings=[e for e in events if e['transaction_hash']==event['transaction_hash']]
                reg=next((e for e in siblings if e['decoded']['name']=='PoolRegistered' and e['decoded']['args']['memecoin']==token),None)
                init=next((e for e in siblings if e['decoded']['name']=='Initialize' and reg and e['decoded']['args']['id']==reg['decoded']['args']['poolId']),None)
                if reg and init:
                    r['lineages'].append(prove_v4_lineage(record=r['records'][token],registration=reg,initialization=init,
                        graduation=event,hook=addresses['pons_v2_hook'],manager=addresses['uniswap_v4_manager']))
    except BoundaryError as exc:
        r['boundary']=str(exc)
    r['provider']=rpc.telemetry();r['ended_at']=time.time()
    return r


if __name__=='__main__':
    r=run(os.environ.get('MM_ROBINHOOD_READ_RPC_URL',''))
    raw=json.dumps(r,sort_keys=True,separators=(',',':')).encode()
    if len(raw)>2_000_000:
        raise BoundaryError('report_capacity')
    Path('robinhood-pons-lineage-report.json').write_bytes(raw)
    print(json.dumps(dict(boundary=r.get('boundary'),lineages=r['lineages'],provider=r['provider'])))
    data=base64.b64encode(zlib.compress(raw,9)).decode()
    for i in range(0,len(data),6000):print('PUBLIC_EVIDENCE_CHUNK '+str(i//6000)+' '+data[i:i+6000])
