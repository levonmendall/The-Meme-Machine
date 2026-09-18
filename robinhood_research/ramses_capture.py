"""Prospective bounded Ramses proof: freeze range first, then observe finalized mainnet."""
import base64
import json
import os
from pathlib import Path
import time
import zlib

from . import BoundaryError
from .abi import calldata, topic
from .identity import authenticate, load
from .provider import Rpc
from .ramses import (authenticate_pool, decode_ramses_event, freeze_proposals, paper_outcome,
                     paper_position, paper_removal, price, quote_value, replay, state, unpack, values)

DISCOVERY_BLOCKS=300
FORWARD_SECONDS=60
PAPER_NATIVE_CAPITAL=10**16


def run(endpoint):
    rpc=Rpc(endpoint,limit=200,per_scope=160,retries=0)
    result=dict(kind='prospective_finalized_ramses',started_at=time.time(),reads=[],
                allocation_authority=False,prospective_range=False,research_only=True)
    factory=load('ramses_factory')['address'];abi=load('ramses_pool_implementation')['abi']

    def read(address,sig,args=(),block=None,scope='pool'):
        value=rpc.call('eth_call',[dict(to=address,data=calldata(sig,*args)),hex(block)],scope=scope)
        result['reads'].append(dict(address=address,signature=sig,args=list(args),block=block,
                                    value=value,observed_at=time.time()))
        return value

    def read_many(address,specs,block,scope='pool'):
        calls=[('eth_call',[dict(to=address,data=calldata(sig,*args)),hex(block)]) for sig,args in specs]
        vals=rpc.batch(calls,scope=scope)
        out={}
        for (sig,args),value in zip(specs,vals):
            out[sig]=value
            result['reads'].append(dict(address=address,signature=sig,args=list(args),block=block,
                                        value=value,observed_at=time.time()))
        return out

    def batched_logs(start,end,*,address=None,topics=None,scope):
        if start>end:return []
        requests=[]
        for first in range(start,end+1,10):
            q=dict(fromBlock=hex(first),toBlock=hex(min(end,first+9)))
            if address:q['address']=address
            if topics:q['topics']=topics
            requests.append(('eth_getLogs',[q]))
        found=[]
        for i in range(0,len(requests),50):
            for page in rpc.batch(requests[i:i+50],scope=scope):
                found.extend(page)
                if len(found)>400:raise BoundaryError('capture_log_capacity')
        return found

    def base_snapshot(address,block,*,initial):
        sigs=['getBinStep()','getActiveId()','getReserves()','getProtocolFees()','getStaticFeeParameters()',
              'getVariableFeeParameters()','getLBHooksParameters()']
        if initial:sigs+=['getTokenX()','getTokenY()','implementation()','getFactory()']
        return dict(values=read_many(address,[(s,()) for s in sigs],block),bins={})

    def add_bins(snapshot,address,block,bins,*,price_anchor=None):
        # Duplicate ABI signatures are batched directly and assigned positionally.
        # This avoids the old redundant read/re-read path.
        if bins:
            calls=[]
            for bid in bins:
                calls.extend([('eth_call',[dict(to=address,data=calldata('getBin(uint24)',bid)),hex(block)]),
                              ('eth_call',[dict(to=address,data=calldata('totalSupply(uint256)',bid)),hex(block)])])
            raw=rpc.batch(calls,scope='pool')
            for i,bid in enumerate(bins):
                snapshot['bins'][str(bid)]={
                    'getBin(uint24)':raw[2*i],
                    'totalSupply(uint256)':raw[2*i+1],
                }
                result['reads'].extend([
                    dict(address=address,signature='getBin(uint24)',args=[bid],block=block,value=raw[2*i],observed_at=time.time()),
                    dict(address=address,signature='totalSupply(uint256)',args=[bid],block=block,value=raw[2*i+1],observed_at=time.time()),
                ])
        if price_anchor is not None and str(price_anchor) in snapshot['bins']:
            snapshot['bins'][str(price_anchor)]['getPriceFromId(uint24)']=read(address,'getPriceFromId(uint24)',(price_anchor,),block)
        return snapshot

    try:
        rpc.verify_chain()
        discovery_frontier=rpc.call('eth_getBlockByNumber',['finalized',False],scope='connectivity')
        discovery_end=int(discovery_frontier['number'],16)
        result['identities']={}
        for role in ('ramses_factory','ramses_pool_implementation','ramses_router'):
            pin=load(role);code=rpc.call('eth_getCode',[pin['address'],hex(discovery_end)],scope='discovery')
            result['identities'][role]=authenticate(role,pin['address'],code)
        swap_topic=topic('Swap(address,address,uint24,bytes32,bytes32,uint24,bytes32,bytes32)')
        activity=batched_logs(max(0,discovery_end-DISCOVERY_BLOCKS+1),discovery_end,topics=[swap_topic],scope='discovery')
        result['discovery_blocks']=DISCOVERY_BLOCKS
        result['discovery_logs']=activity
        ordered=[]
        for event in sorted(activity,key=lambda e:(int(e['blockNumber'],16),int(e['logIndex'],16)),reverse=True):
            if event['address'] not in ordered:ordered.append(event['address'])
        result['factory_checks']={};address=None
        checks=ordered[:5]
        if checks:
            vals=rpc.batch([('eth_call',[dict(to=factory,data=calldata('isPool(address)',candidate)),hex(discovery_end)]) for candidate in checks],
                           scope='discovery')
            for candidate,value in zip(checks,vals):
                result['factory_checks'][candidate]=value
                if address is None and int(value,16)==1:address=candidate
        if address is None:
            raise BoundaryError('no_factory_validated_activity_in_300_block_window')
        result['pool']=address
        start_frontier=rpc.call('eth_getBlockByNumber',['finalized',False],scope='connectivity')
        start=int(start_frontier['number'],16);start_ts=int(start_frontier['timestamp'],16)
        result['start_frontier']={k:start_frontier[k] for k in ('hash','number','timestamp','parentHash')}
        result['pool_code']=rpc.call('eth_getCode',[address,hex(start)],scope='pool')
        clone=authenticate_pool(result['pool_code'],factory_member=int(result['factory_checks'][address],16)==1)
        router=load('ramses_router')['address']
        wnative='0x'+read(router,'getWNATIVE()',block=start)[-40:]
        result['wnative']=wnative

        pre=base_snapshot(address,start,initial=True)
        token_x='0x'+pre['values']['getTokenX()'][-40:];token_y='0x'+pre['values']['getTokenY()'][-40:]
        if token_y.lower()==wnative.lower():quote_side='y'
        elif token_x.lower()==wnative.lower():quote_side='x'
        else:raise BoundaryError('native_quote_pair_unavailable')
        active=values(pre['values']['getActiveId()'])[0]
        proposal_bins=list(range(active-3,active+4))
        add_bins(pre,address,start,proposal_bins,price_anchor=active)
        pre_state=state(pre)
        prehistory=[]
        for event in sorted([e for e in activity if e['address'].lower()==address.lower()],
                            key=lambda e:(int(e['blockNumber'],16),int(e['logIndex'],16))):
            d=decode_ramses_event(abi,event)
            if d['name']=='Swap':prehistory.append(dict(block=int(event['blockNumber'],16),transaction_hash=event['transactionHash'],args=d['args']))
        freeze=freeze_proposals(pre_state,PAPER_NATIVE_CAPITAL,quote_side=quote_side,entry_timestamp=start_ts,prehistory=prehistory)
        freeze.update(pre_entry_block=start,pre_entry_hash=start_frontier['hash'],pre_entry_time=start_ts,
                      quote_asset=wnative,source='finalized_prestate')
        result['range_freeze']=freeze;result['prospective_range']=True;result['quote_side']=quote_side
        result['proposal_hash']=freeze['proposal_hash'];result['prehistory']=prehistory
        # Nothing after this point can alter the frozen proposal definitions.
        target=start_ts+FORWARD_SECONDS;deadline=time.monotonic()+100
        end_frontier=start_frontier
        while int(end_frontier['timestamp'],16)<target:
            if time.monotonic()>=deadline:raise BoundaryError('insufficient_finalized_forward_window')
            time.sleep(10)
            end_frontier=rpc.call('eth_getBlockByNumber',['finalized',False],scope='forward')
        end=int(end_frontier['number'],16);end_ts=int(end_frontier['timestamp'],16)
        result['frontier']={k:end_frontier[k] for k in ('hash','number','timestamp','parentHash')}
        events=batched_logs(start+1,end,address=address,scope='pool')
        result['logs']=events
        decoded=[]
        mutation_bins=set(proposal_bins)
        for event in events:
            d=decode_ramses_event(abi,event);decoded.append(d);a=d['args']
            if d['name'] in ('Swap','CompositionFees'):mutation_bins.add(a['id'])
            elif d['name'] in ('DepositedToBins','WithdrawnFromBins'):mutation_bins.update(a['ids'])
            elif d['name']=='TransferBatch' and (a['from'].lower()=='0x'+'00'*20 or a['to'].lower()=='0x'+'00'*20):
                mutation_bins.update(a['ids'])
        result['decoded']=decoded
        if len(mutation_bins)>9:raise BoundaryError('capture_bin_capacity')
        missing=sorted(mutation_bins-set(proposal_bins))
        if missing:add_bins(pre,address,start,missing)

        terminal=base_snapshot(address,end,initial=False)
        add_bins(terminal,address,end,sorted(mutation_bins))
        result['states']={str(start):pre,str(end):terminal}
        txs=[]
        for event in events:
            if event['transactionHash'] not in txs:txs.append(event['transactionHash'])
        if len(txs)>10:raise BoundaryError('capture_receipt_capacity')
        if txs:
            result['receipts']=rpc.batch([('eth_getTransactionReceipt',[tx]) for tx in txs],scope='pool')
        else:result['receipts']=[]
        block_numbers=sorted(set(int(e['blockNumber'],16) for e in events))
        if len(block_numbers)>10:raise BoundaryError('capture_header_capacity')
        result['headers']={
            str(start):{k:start_frontier[k] for k in ('number','hash','timestamp','parentHash')},
            str(end):{k:end_frontier[k] for k in ('number','hash','timestamp','parentHash')},
        }
        needed=[h for h in block_numbers if h not in (start,end)]
        if needed:
            rows=rpc.batch([('eth_getBlockByNumber',[hex(h),False]) for h in needed],scope='pool')
            for h,row in zip(needed,rows):
                result['headers'][str(h)]={k:row[k] for k in ('number','hash','timestamp','parentHash')}
        check=rpc.call('eth_getBlockByNumber',[hex(end),False],scope='pool')
        if check['hash']!=end_frontier['hash']:raise BoundaryError('finalized_chain_disagreement')

        result['replay']=replay(result)
        result['observation_seconds']=end_ts-start_ts
        if not events:raise BoundaryError('insufficient_forward_activity')
        observations=[]
        terminal_state=result['replay']['terminal_state']
        for index,_proposal in enumerate(freeze['proposals']):
            position=paper_position(freeze,index);removal=paper_removal(position,terminal_state)['amounts']
            nonquote=0 if quote_side=='y' else 1;amount=removal[nonquote];unwind=None
            if amount:
                if amount>=2**128:raise BoundaryError('unwind_amount_capacity')
                for_y=1 if quote_side=='y' else 0
                raw=read(address,'getSwapOut(uint128,bool)',(amount,for_y),end)
                q=values(raw)
                spot=price(terminal_state['active'],terminal_state['step'])
                expected=quote_value([amount,0] if nonquote==0 else [0,amount],spot,quote_side)
                unwind=dict(input_side='x' if nonquote==0 else 'y',amount_in=amount,amount_in_left=q[0],
                            amount_out=q[1],fee=q[2],slippage=max(0,expected-q[1]),block=end)
            outcome=paper_outcome(position,terminal_state,unwind=unwind,costs=None,lp_fees_captured=None)
            observations.append(dict(proposal_index=index,name=position['proposal']['name'],position=position,outcome=outcome))
        result['observations']=observations
        if any(o['outcome']['unresolved_inventory'] for o in observations):
            raise BoundaryError('unwind_liquidity_unavailable')
        # Exact hypothetical add/remove/claim/unwind gas is not inferable from unrelated receipts.
        # Do not manufacture it; after-cost return stays null until executable cost evidence exists.
        raise BoundaryError('cost_evidence_unavailable')
    except BoundaryError as exc:
        result['boundary']=str(exc)
    result['provider']=rpc.telemetry();result['ended_at']=time.time()
    return result


if __name__=='__main__':
    result=run(os.environ.get('MM_ROBINHOOD_READ_RPC_URL',''))
    raw=json.dumps(result,sort_keys=True,separators=(',',':')).encode()
    if len(raw)>2_000_000:raise BoundaryError('report_capacity')
    Path('robinhood-ramses-report.json').write_bytes(raw)
    print(json.dumps(dict(boundary=result.get('boundary'),pool=result.get('pool'),proposal_hash=result.get('proposal_hash'),
                          observation_seconds=result.get('observation_seconds'),provider=result['provider'])))
    data=base64.b64encode(zlib.compress(raw,9)).decode()
    for i in range(0,len(data),6000):
        print('PUBLIC_EVIDENCE_CHUNK '+str(i//6000)+' '+data[i:i+6000])
