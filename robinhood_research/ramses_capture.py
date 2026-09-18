"""Prospective bounded Ramses proof: freeze range first, then observe finalized mainnet."""
import base64
from collections import Counter
import hashlib
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
                     paper_fee_capture, paper_position, paper_removal, price, quote_value, replay, state, unpack, values)

DISCOVERY_BLOCKS=3000
ACTIVITY_WAIT_SECONDS=120
ACTIVITY_POLL_SECONDS=10
LOG_BLOCK_CHUNK=50
MAX_FACTORY_POOLS=400
FORWARD_SECONDS=60
PAPER_NATIVE_CAPITAL=10**16
INVENTORY_BASELINE=Path(__file__).with_name('ramses_native_inventory_baseline.json')
INVENTORY_NATIVE_SHA='1e6beebd82ae3b87d1f2149374a5efdf6acc089c9cb4f792ae9b32e42b97aee5'


class BoundedMultiRpc:
    """Ramses-only bounded multi-session reader for complete factory inventory.

    Each underlying Rpc keeps the existing 200-logical-request hard boundary.
    This wrapper may open at most four sessions and aggregates all provider
    telemetry, so complete inventory is possible without changing shared/Pons
    provider behavior or making the budget unbounded.
    """
    def __init__(self,endpoint,*,max_sessions=4,batch_size=20,batch_pause=0.75):
        self.endpoint=endpoint;self.max_sessions=max_sessions;self.batch_size=batch_size;self.batch_pause=batch_pause
        self.sessions=[];self.wrapper_retries=0
        self._new()

    def _new(self):
        if len(self.sessions)>=self.max_sessions:
            raise BoundaryError('ramses_provider_program_budget_exhausted')
        session=Rpc(self.endpoint,limit=200,per_scope=200,retries=0)
        self.sessions.append(session)
        return session

    def _session(self,needed=1):
        current=self.sessions[-1]
        if current.used+needed>current.limit:
            current=self._new()
        return current

    def call(self,method,params,*,scope='connectivity'):
        for attempt in range(2):
            try:
                return self._session(1).call(method,params,scope=scope)
            except BoundaryError as exc:
                if str(exc)!='provider_rpc_429' or attempt:
                    raise
                self.wrapper_retries+=1;time.sleep(3)
        raise BoundaryError('provider_rpc_429')

    def batch(self,calls,*,scope='connectivity'):
        if not isinstance(calls,list) or not calls:
            raise BoundaryError('provider_batch_shape')
        out=[]
        chunks=[calls[i:i+self.batch_size] for i in range(0,len(calls),self.batch_size)]
        for index,chunk in enumerate(chunks):
            if index:time.sleep(self.batch_pause)
            for attempt in range(2):
                try:
                    out.extend(self._session(len(chunk)).batch(chunk,scope=scope))
                    break
                except BoundaryError as exc:
                    if str(exc)!='provider_rpc_429' or attempt:
                        raise
                    self.wrapper_retries+=1;time.sleep(3)
        return out

    def receipt(self,tx_hash,block_hash,*,scope):
        result=self.call('eth_getTransactionReceipt',[tx_hash],scope=scope)
        if result['transactionHash']!=tx_hash or result['blockHash']!=block_hash:
            raise BoundaryError('receipt_block_disagreement')
        return result

    def verify_chain(self):
        result=self.call('eth_chainId',[])
        if int(result,16)!=4663:
            raise BoundaryError('wrong_chain')
        return 4663

    def telemetry(self):
        requests=transport=logical=retries=0
        methods=Counter();logical_methods=Counter();scopes=Counter();failures=Counter()
        for session in self.sessions:
            row=session.telemetry()
            requests+=row['requests'];transport+=row['transport_requests'];logical+=row['logical_requests'];retries+=row['retries']
            methods.update(row['methods']);logical_methods.update(row['logical_methods']);scopes.update(row['scopes']);failures.update(row['failures'])
        retries+=self.wrapper_retries
        return dict(requests=requests,transport_requests=transport,logical_requests=logical,retries=retries,
                    methods=dict(methods),logical_methods=dict(logical_methods),scopes=dict(scopes),
                    failures=dict(failures),sessions=len(self.sessions),max_sessions=self.max_sessions,
                    program_logical_limit=self.max_sessions*200,batch_size=self.batch_size,batch_pause_seconds=self.batch_pause)


def run(endpoint):
    rpc=BoundedMultiRpc(endpoint,max_sessions=4)
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
        for first in range(start,end+1,LOG_BLOCK_CHUNK):
            q=dict(fromBlock=hex(first),toBlock=hex(min(end,first+LOG_BLOCK_CHUNK-1)))
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
        router=load('ramses_router')['address']
        discovery_wnative='0x'+read(router,'getWNATIVE()',block=discovery_end,scope='discovery')[-40:]
        result['wnative']=discovery_wnative
        # Use the previously authenticated complete inventory as an immutable
        # baseline. Verified DLMMFactory source is append-only: createLBPair is
        # the only _allLBPairs mutation and calls _allLBPairs.push(pair).
        try:
            baseline=json.loads(INVENTORY_BASELINE.read_text())
        except (OSError,ValueError):
            raise BoundaryError('ramses_inventory_baseline_unreadable') from None
        if (baseline.get('kind')!='ramses_native_factory_inventory_baseline_v1'
            or baseline.get('chain_id')!=4663
            or baseline.get('factory')!=result['identities']['ramses_factory']['address']
            or baseline.get('factory_runtime_sha256')!=result['identities']['ramses_factory']['runtime_sha256']
            or baseline.get('pool_implementation')!=result['identities']['ramses_pool_implementation']['address']
            or baseline.get('pool_implementation_runtime_sha256')!=result['identities']['ramses_pool_implementation']['runtime_sha256']
            or baseline.get('wnative')!=discovery_wnative.lower()
            or baseline.get('evidence_artifact_sha256')!='50a8ea15a474822d41b85674ca968227d857dcce8440caef40e252cd45ee3afc'):
            raise BoundaryError('ramses_inventory_baseline_identity')
        cached=baseline.get('native_pools')
        if not isinstance(cached,list) or len(cached)!=baseline.get('native_pool_count'):
            raise BoundaryError('ramses_inventory_baseline_shape')
        compact=json.dumps(cached,sort_keys=True,separators=(',',':')).encode()
        if hashlib.sha256(compact).hexdigest()!=INVENTORY_NATIVE_SHA or baseline.get('native_entries_sha256')!=INVENTORY_NATIVE_SHA:
            raise BoundaryError('ramses_inventory_baseline_digest')
        seen_addresses=set();seen_indices=set();native_pools=[]
        for row in cached:
            if (set(row)!=set(('a','i','n','s','x','y')) or row['n'] not in ('x','y')
                or row['i'] in seen_indices or row['a'] in seen_addresses
                or not 0<=row['i']<baseline['factory_pool_count']):
                raise BoundaryError('ramses_inventory_baseline_entry')
            if (row['x']==discovery_wnative.lower())!=(row['n']=='x') or (row['y']==discovery_wnative.lower())!=(row['n']=='y'):
                raise BoundaryError('ramses_inventory_baseline_native_side')
            seen_indices.add(row['i']);seen_addresses.add(row['a']);native_pools.append(row['a'])

        pool_count=values(read(factory,'getNumberOfLBPairs()',block=discovery_end,scope='discovery'))[0]
        result['factory_pool_count']=pool_count
        result['inventory_baseline_count']=baseline['factory_pool_count']
        result['inventory_baseline_artifact']=baseline['evidence_artifact_id']
        result['inventory_baseline_digest']=baseline['native_entries_sha256']
        if pool_count<baseline['factory_pool_count']:
            raise BoundaryError('factory_pool_inventory_regressed')
        if pool_count>MAX_FACTORY_POOLS:
            raise BoundaryError('factory_pool_inventory_capacity:'+str(pool_count))

        # Only authenticate pools appended after the proven baseline. Existing
        # native entries are immutable by the verified factory source. The
        # ultimately selected pool is independently revalidated below.
        result['new_factory_pools']=[]
        for first in range(baseline['factory_pool_count'],pool_count,20):
            indices=list(range(first,min(pool_count,first+20)))
            rows=rpc.batch([('eth_call',[dict(to=factory,data=calldata('getLBPairAtIndex(uint256)',i)),hex(discovery_end)])
                            for i in indices],scope='discovery')
            addresses=['0x'+row[-40:] for row in rows]
            if any(int(a,16)==0 for a in addresses) or len(set(addresses))!=len(addresses):
                raise BoundaryError('invalid_factory_pool_inventory')
            codes=rpc.batch([('eth_getCode',[a,hex(discovery_end)]) for a in addresses],scope='discovery')
            for index,address_i,code in zip(indices,addresses,codes):
                try:
                    auth=authenticate_pool(code,factory_member=True)
                except BoundaryError as exc:
                    raise BoundaryError('factory_registered_pool_authentication:'+str(exc)) from None
                native_side=('x' if auth['token_x'].lower()==discovery_wnative.lower()
                             else ('y' if auth['token_y'].lower()==discovery_wnative.lower() else None))
                row=dict(index=index,address=address_i,token_x=auth['token_x'],token_y=auth['token_y'],
                         bin_step=auth['bin_step'],native_side=native_side)
                result['new_factory_pools'].append(row)
                if native_side is not None:native_pools.append(address_i)
        result['native_factory_pools']=native_pools
        result['native_factory_pool_count']=len(native_pools)
        if not native_pools:
            raise BoundaryError('no_factory_registered_native_ramses_pool')

        active_names=frozenset(('Swap','DepositedToBins','WithdrawnFromBins','FlashLoan'))
        def economically_active(rows):
            eligible=[]
            for event in rows:
                try:
                    decoded=decode_ramses_event(abi,event)
                except BoundaryError:
                    continue
                if decoded['name'] in active_names:
                    eligible.append((event,decoded))
            return eligible

        # Search only the complete native-pool inventory. Liquidity deposits/removals
        # and flash loans are genuine Ramses pool-state activity too; requiring a swap
        # here unnecessarily censored otherwise valid prospective observations.
        activity=batched_logs(max(0,discovery_end-DISCOVERY_BLOCKS+1),discovery_end,
                              address=native_pools,scope='discovery')
        result['discovery_blocks']=DISCOVERY_BLOCKS
        result['discovery_logs']=activity
        result['discovery_event_names']={}
        for event,decoded in economically_active(activity):
            result['discovery_event_names'][decoded['name']]=result['discovery_event_names'].get(decoded['name'],0)+1
        selection=None;selection_decoded=None
        recent=economically_active(activity)
        if recent:
            selection,selection_decoded=sorted(recent,key=lambda row:(int(row[0]['blockNumber'],16),
                int(row[0]['transactionIndex'],16),int(row[0]['logIndex'],16),row[0]['address'].lower()))[-1]
            result['selection_rule']='most_recent_native_economic_mutation_before_freeze'
        else:
            watch_started=time.monotonic();cursor=discovery_end
            result['selection_rule']='first_native_economic_mutation_after_watch_start'
            while time.monotonic()-watch_started<ACTIVITY_WAIT_SECONDS and selection is None:
                time.sleep(ACTIVITY_POLL_SECONDS)
                frontier=rpc.call('eth_getBlockByNumber',['finalized',False],scope='discovery')
                height=int(frontier['number'],16)
                if height<=cursor:continue
                new_rows=batched_logs(cursor+1,height,address=native_pools,scope='discovery')
                activity.extend(new_rows);cursor=height
                eligible=economically_active(new_rows)
                if eligible:
                    selection,selection_decoded=sorted(eligible,key=lambda row:(int(row[0]['blockNumber'],16),
                        int(row[0]['transactionIndex'],16),int(row[0]['logIndex'],16),row[0]['address'].lower()))[0]
                    break
            result['activity_watch_seconds']=time.monotonic()-watch_started
        if selection is None:
            raise BoundaryError('no_natural_native_ramses_activity_during_bounded_watch')
        result['selection_event_name']=selection_decoded['name']
        address=selection['address']
        result['selection_event']=selection
        result['factory_checks']={}
        explicit=read(factory,'isPool(address)',(address,),discovery_end,scope='discovery')
        result['factory_checks'][address]=explicit
        if int(explicit,16)!=1:
            raise BoundaryError('selected_pool_lost_factory_membership')
        result['pool']=address
        start_frontier=rpc.call('eth_getBlockByNumber',['finalized',False],scope='connectivity')
        start=int(start_frontier['number'],16);start_ts=int(start_frontier['timestamp'],16)
        result['start_frontier']={k:start_frontier[k] for k in ('hash','number','timestamp','parentHash')}
        result['pool_code']=rpc.call('eth_getCode',[address,hex(start)],scope='pool')
        clone=authenticate_pool(result['pool_code'],factory_member=int(result['factory_checks'][address],16)==1)
        wnative='0x'+read(router,'getWNATIVE()',block=start)[-40:]
        if wnative.lower()!=discovery_wnative.lower():raise BoundaryError('router_native_asset_changed')
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
            captured_fees=paper_fee_capture(position,result['replay'])
            outcome=paper_outcome(position,terminal_state,unwind=unwind,costs=None,lp_fees_captured=captured_fees)
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
