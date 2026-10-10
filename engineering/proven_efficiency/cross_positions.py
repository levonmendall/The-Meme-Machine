"""Native quote parity and governor measurements; offline preparation only.

No production module imports this file. Batch only already-ready requests at one
authenticated block, with proved EIP-1898 support. No timer enlarges a batch.
History, capital, admission and protection-loop integration remain independent
release requirements; this is not a whole-loop capacity certificate.
"""
from collections import Counter
from contextlib import ExitStack
from dataclasses import asdict
import argparse
import io
import hashlib
import json
import os
from pathlib import Path
import time
from unittest.mock import patch

from operational.tests import network_guard
from meme_machine.operational.artifact_storage import Scratch
from meme_machine.lanes.pons import BoundaryError,CHAIN_ID
from meme_machine.lanes.pons.abi import calldata
from meme_machine.lanes.pons.evidence import Store,canonical
from meme_machine.lanes.pons.pons_quotes import v4_quote
from meme_machine.lanes.pons.pons_natural_paper import V4_QUOTER,_v4_quoter_calldata,ZERO
from meme_machine.lanes.pons.pons_postgrad_survivor import exit_action
from meme_machine.lanes.pons.pons_selective_continuation import runner_action
from meme_machine.lanes.pons.provider_topology import PacedRpc,ProviderPacer
from meme_machine.lanes.pons.protocols import PoolKey
from tests.lanes.pons.test_pons_finalization import ExactQuoteRPC,address,block_header
from operational.provider_cost_attribution import join_native_decisions

ENDPOINT='https://robinhood-mainnet.g.alchemy.com/v2/OFFLINE_CROSS_POSITION'


class Clock:
    def __init__(self):self.at=100.
    def time(self):return self.at
    def sleep(self,seconds):self.at+=seconds


def quote_request(index,*,block_hash=None):
    key=PoolKey(ZERO,address(index+1),3000,60,address(999))
    return dict(key=key,pool_id=key.pool_id(),amount=10**18+index*10000,side='sell',block_hash=block_hash)


def native_quote(rpc,request,*,head=None):
    store=Store(':memory:')
    try:
        q,meta,ledger=v4_quote(rpc,request['key'],request['pool_id'],request['amount'],200000,
            store,'offline-position-protection',side=request['side'],local_freshness=True,fresh_head=head)
        q.check(int(time.time()),q.market,request['side'],request['amount'],q.stamp.kind,finality_ledger=ledger)
        return quote_decision(q,meta,request)
    finally:store.close()


def quote_decision(q,meta,request):
    basis=request['amount']//100
    rbps=(q.amount_out-q.gas_quote-basis)*10000//basis
    action=exit_action(after_cost_return_bps=rbps,high_water_return_bps=5000,
        hold_seconds=100,seconds_since_high=0,buy_quote_30m=300,sell_quote_30m=100,new_buyers_30m=4)
    if request.get('consumer')=='current':
        action=runner_action(tokens=request['amount'],partial_taken=True,after_cost_return_bps=rbps,
            high_water_return_bps=5000,seconds_since_high=0,new_buyer_growth=4,buy_quote=300,sell_quote=100)
    return dict(native_economic=dict(side=q.side,quantity=q.amount_in,amount_out=q.amount_out,
        gas_quote=q.gas_quote,market=q.market,block=meta['block'],block_hash=meta['block_hash']),
        native_exit_decision=action,stamp=asdict(q.stamp))


def ready_quote_union(rpc,requests,*,now=time.monotonic):
    from meme_machine.lanes.pons.pons_quotes import shared_v4_quotes
    if len(requests)==1:return [native_quote(rpc,requests[0])]
    # The deterministic fixture proves these bounds only for injected HTTP.
    # The operational endpoint has no such proof and remains disabled.
    rpc.shared_quote_resources=dict(validated=True,provider_fingerprint=rpc.provider_fingerprint,
        max_response_bytes=rpc.max_response,max_latency_seconds=.001,
        max_logical_elements=50,max_throughput_cu=2000)
    values=shared_v4_quotes(rpc,[dict(r,gas_units=200000) for r in requests])
    return [quote_decision(v['quote'],v['meta'],r) for r,v in zip(requests,values)]


def scenario(root,count,*,timing='coincident',mode='native',cadence=3,latency=.001):
    if count not in range(1,21) or timing not in ('coincident','staggered') or mode not in ('native','prepared_union'):
        raise ValueError('offline_cross_position_scenario')
    clock=Clock();provider=ExactQuoteRPC();wire=[];decisions=[];current=[0];links=[]
    cpu_started=time.process_time()
    def value(method,params):
        if method=='eth_chainId':return hex(CHAIN_ID)
        if method=='eth_getBlockByNumber':
            n=100+current[0] if params[0]=='latest' else int(params[0],16)
            return dict(block_header(n),parentHash=block_header(n-1)['hash'],timestamp=hex(100))
        return provider.value(method,params)
    def response(request,**kwargs):
        body=json.loads(request.data);calls=body if isinstance(body,list) else [body]
        row=dict(purchase_id=f'mock-{count}-{cadence}-{timing}-{mode}-'+str(len(wire)),started=clock.at,
            completed=True,failed=False,
            methods=[c['method'] for c in calls],logical_elements=len(calls),request_bytes=len(request.data),
            independent_simulations=sum(c['method']=='eth_call' and
                c['params'][0]['data']!=calldata('poolManager()') for c in calls),
            identity_blocks=[c['params'][1]['blockHash'] for c in calls
                if c['method']=='eth_getCode' and isinstance(c['params'][1],dict)])
        answers=[dict(jsonrpc='2.0',id=c['id'],result=value(c['method'],c['params'])) for c in calls]
        encoded=json.dumps(answers if isinstance(body,list) else answers[0]).encode()
        row['payload_bytes']=len(encoded);wire.append(row);clock.at+=latency
        return io.BytesIO(encoded)
    env=dict(MM_ROBINHOOD_READ_RPC_URL=ENDPOINT,MM_PROVIDER_DB=str(root/'provider.sqlite'),
        MM_RPC_CACHE_DB=str(root/'reuse.sqlite'),MM_RUNTIME_LANE='pons',MM_ROBINHOOD_STATE_DIR=str(root))
    with ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ,env,clear=True))
        stack.enter_context(patch('time.monotonic',side_effect=clock.time))
        stack.enter_context(patch('time.time',side_effect=clock.time))
        stack.enter_context(patch('meme_machine.lanes.pons.provider.urlopen',side_effect=response))
        pacer=ProviderPacer(2,clock=clock.time,sleeper=clock.sleep)
        rpc=PacedRpc(ENDPOINT,role='directional_evidence_primary',requests_per_second=2,
            pacer=pacer,limit=200,per_scope=190,retries=0)
        rpc.shared_admission.clock=clock.time;rpc.shared_admission.sleep=clock.sleep
        rpc.hash_state_supported={'eth_call','eth_getCode'} # Explicitly proved offline fixture capability.
        rpc.evidence_timing={};rpc.verify_chain()
        releases=[100+(i*(cadence-.01)/(count or 1) if timing=='staggered' else 0) for i in range(count)]
        # Survivor currently dispatches its held controllers serially. Current
        # has eight workers; these measurements do not certify that parallel loop.
        for i in range(count):
            clock.at=max(clock.at,releases[i]);dispatch=clock.at
            first_purchase=len(wire)
            current[0]=i if timing=='staggered' else 0
            req=quote_request(i);req['consumer']='current' if cadence==5 else 'survivor'
            if mode=='prepared_union' and timing=='coincident':
                if i==0:
                    ready_requests=[dict(quote_request(j),consumer=req['consumer']) for j in range(count)]
                    ready=ready_quote_union(rpc,ready_requests,now=clock.time)
                    union_dispatch=dispatch;union_purchases=list(range(len(wire)))
                decision=ready[i]
                dispatch=union_dispatch;acquired=union_purchases
            else:
                # Adversarial states cannot form one union. Keep original work.
                decision=native_quote(rpc,req);acquired=list(range(first_purchase,len(wire)))
            reused=[0]+[j for j,r in enumerate(wire) if
                decision['native_economic']['block_hash'] in r['identity_blocks'] and j<first_purchase]
            links.extend(dict(purchase_id=wire[j]['purchase_id'],consumer=i,consumer_family=req['consumer'],
                acquisition='acquired' if j in acquired else 'authenticated_identity_reuse',
                deadline=releases[i]+cadence,native_decision=decision['native_exit_decision'],
                canonical_block=decision['native_economic']['block'],
                canonical_hash=decision['native_economic']['block_hash']) for j in sorted(set(acquired+reused)))
            decisions.append(dict(consumer=i,released=releases[i],dispatch=dispatch,completed=clock.at,
                queue_age_seconds=dispatch-releases[i],native_decision_latency_seconds=clock.at-releases[i],
                deadline=releases[i]+cadence,deadline_met=clock.at<=releases[i]+cadence,**decision))
        telemetry=rpc.telemetry()
    purchased=Counter(m for r in wire for m in r['methods'])
    independent=[r['native_economic'] for r in decisions]
    assert len({r['market'] for r in independent})==count
    assert all(r['native_exit_decision']['action']=='full_exit' for r in decisions)
    assert all(b['started']-a['started']>=.5-1e-7 for a,b in zip(wire,wire[1:]))
    facts=[];consumers=[]
    for d in decisions:
        identity=hashlib.sha256(canonical(d['native_economic']).encode()).hexdigest()
        facts.append(dict(evidence_id=identity,canonical_hash=d['native_economic']['block_hash'],
            authenticated_by_native_validator=True,purchase_ids=[r['purchase_id'] for r in links if r['consumer']==d['consumer']]))
        consumers.append(dict(decision_id=f'decision-{d["consumer"]}',consumer='current' if cadence==5 else 'survivor',
            evidence_ids=[identity],canonical_hash=d['native_economic']['block_hash'],
            original_deadline=d['deadline'],decided_at=d['completed'],native_decision=d['native_exit_decision']))
    joined=join_native_decisions(wire,facts,consumers)
    return dict(classification='OFFLINE_NATIVE_QUOTE_COMPONENT; virtual governor clock and mock HTTP latency',
        held_positions=count,timing=timing,mode=mode,original_cadence_seconds=cadence,
        methods=dict(purchased),physical_requests=len(wire),logical_elements=sum(purchased.values()),
        physical_provider_calls=0,simulations=sum(r['independent_simulations'] for r in wire),
        native_decisions=count,canonical_checks=purchased['eth_getBlockByNumber'],
        payload_bytes=sum(r['payload_bytes'] for r in wire),provider_timing=rpc.evidence_timing,
        decisions=decisions,purchase_to_decision_links=links,native_decision_join=joined,
        local_cpu_seconds=time.process_time()-cpu_started,
        acquisition_reuse=telemetry['provider_purchases']['totals'],
        original_deadline_misses=sum(not d['deadline_met'] for d in decisions),
        caveat='No history/entry/exit settlement latency is included. Current thread scheduling and real provider RTT remain unproved.')


def build(root):
    rows=[]
    for count in range(1,21):
        for cadence in (3,5):
            for timing in ('coincident','staggered'):
                results=[]
                for mode in ('native','prepared_union'):
                    folder=root/f'{count}-{cadence}-{timing}-{mode}';folder.mkdir()
                    results.append(scenario(folder,count,timing=timing,mode=mode,cadence=cadence))
                before,prepared=results
                assert [d['native_economic'] for d in before['decisions']]==[d['native_economic'] for d in prepared['decisions']]
                assert [d['native_exit_decision'] for d in before['decisions']]==[d['native_exit_decision'] for d in prepared['decisions']]
                rows.append(dict(positions=count,cadence=cadence,timing=timing,original=before,offline_preparation=prepared,
                    economic_and_exit_parity=True,production_activation=False))
    return dict(schema='cross-position-native-component-v1',rows=rows,actual_provider_calls=0,
        governor_rps=2,no_batch_wait_introduced=True,full_protection_loop_capacity_proved=False,
        current_more_than_eight_controllers_proved=False,
        interpretation='80 position/timing/cadence pairs, both native and inactive prepared paths. Do not extrapolate fixture latency into a provider guarantee.')


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();network_guard()
    with Scratch() as scratch:
        result=build(scratch.path);scratch.check();a.output.write_text(json.dumps(result,separators=(',',':'))+'\n');scratch.success=True
    print(json.dumps(dict(scenarios=len(result['rows']),actual_provider_calls=0)))


if __name__=='__main__':main()
