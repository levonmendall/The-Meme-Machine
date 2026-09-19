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
from .provider_topology import configured_rpc
from .ramses import (authenticate_pool, decode_ramses_event, freeze_proposals, paper_outcome,
                     paper_fee_capture, paper_position, paper_removal, price, quote_value, replay, state, unpack, values)

ACTIVITY_POLL_SECONDS=15
RANK_POOL_COUNT=96
WATCH_POOL_COUNT=8
WATCH_COHORT_COUNT=1
WATCH_SLOT_SECONDS=300
ACTIVITY_WAIT_SECONDS=WATCH_SLOT_SECONDS
FINALITY_WAIT_SECONDS=180
FORWARD_HEAD_WAIT_SECONDS=180
FORWARD_FINALITY_WAIT_SECONDS=240
FORCED_FORWARD_FINALITY_WAIT_SECONDS=600
LOG_BLOCK_CHUNK=10
MAX_FACTORY_POOLS=400
FORWARD_SECONDS=60
PAPER_NATIVE_CAPITAL=10**16
FORCED_PAPER_POOL='0xbc2f7c6ec69341393fd7965dd0bb4d9f42881c63'
INVENTORY_BASELINE=Path(__file__).with_name('ramses_native_inventory_baseline.json')
INVENTORY_NATIVE_SHA='1e6beebd82ae3b87d1f2149374a5efdf6acc089c9cb4f792ae9b32e42b97aee5'


class BoundedMultiRpc:
    """Ramses-only bounded multi-session reader for complete factory inventory.

    Each underlying Rpc keeps the existing 200-logical-request hard boundary.
    This wrapper may open at most four sessions and aggregates all provider
    telemetry, so complete inventory is possible without changing shared/Pons
    provider behavior or making the budget unbounded.
    """
    def __init__(self,endpoint,*,max_sessions=4,batch_size=20,batch_pause=0.75,rate_retries=1):
        self.endpoint=endpoint;self.max_sessions=max_sessions;self.batch_size=batch_size;self.batch_pause=batch_pause
        self.rate_retries=rate_retries
        self.sessions=[];self.wrapper_retries=0
        self._new()

    def _new(self):
        if len(self.sessions)>=self.max_sessions:
            raise BoundaryError('ramses_provider_program_budget_exhausted')
        session=configured_rpc(self.endpoint,limit=200,per_scope=200,retries=0)
        self.sessions.append(session)
        return session

    def _session(self,needed=1):
        current=self.sessions[-1]
        if current.used+needed>current.limit:
            current=self._new()
        return current

    def call(self,method,params,*,scope='connectivity'):
        for attempt in range(self.rate_retries+1):
            try:
                return self._session(1).call(method,params,scope=scope)
            except BoundaryError as exc:
                if str(exc) not in ('provider_rpc_429','provider_http_429') or attempt>=self.rate_retries:
                    raise
                self.wrapper_retries+=1;time.sleep(3*(attempt+1))
        raise BoundaryError('provider_rate_limit')

    def batch(self,calls,*,scope='connectivity'):
        if not isinstance(calls,list) or not calls:
            raise BoundaryError('provider_batch_shape')
        out=[]
        chunks=[calls[i:i+self.batch_size] for i in range(0,len(calls),self.batch_size)]
        for index,chunk in enumerate(chunks):
            if index:time.sleep(self.batch_pause)
            for attempt in range(self.rate_retries+1):
                try:
                    out.extend(self._session(len(chunk)).batch(chunk,scope=scope))
                    break
                except BoundaryError as exc:
                    if str(exc) not in ('provider_rpc_429','provider_http_429') or attempt>=self.rate_retries:
                        raise
                    self.wrapper_retries+=1;time.sleep(3*(attempt+1))
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


def _first_finalized_block_at_or_after(rpc,start_block,finalized_frontier,target_timestamp):
    """Return the earliest already-finalized block at/after the target time.

    The finalized frontier can lag the head by minutes. Using the frontier
    itself therefore stretches a +60s experiment into the finality lag. Block
    timestamps are strictly increasing on this EVM chain, so a bounded binary
    search recovers the first finalized block crossing the frozen horizon.
    """
    high=int(finalized_frontier['number'],16)
    if high<=start_block or int(finalized_frontier['timestamp'],16)<target_timestamp:
        raise BoundaryError('forced_finalized_target_not_reached')
    low=start_block+1;reads=0
    while low<high:
        mid=(low+high)//2
        row=rpc.call('eth_getBlockByNumber',[hex(mid),False],scope='forward');reads+=1
        if int(row['timestamp'],16)>=target_timestamp:
            high=mid
        else:
            low=mid+1
    selected=rpc.call('eth_getBlockByNumber',[hex(low),False],scope='forward');reads+=1
    previous=rpc.call('eth_getBlockByNumber',[hex(low-1),False],scope='forward');reads+=1
    if (int(selected['timestamp'],16)<target_timestamp
        or int(previous['timestamp'],16)>=target_timestamp
        or int(selected['number'],16)!=low
        or int(previous['number'],16)!=low-1):
        raise BoundaryError('forced_finalized_horizon_selection_disagreement')
    return selected,previous,reads


def run(endpoint, *, forced_paper=False, forced_db_path=None):
    rpc=BoundedMultiRpc(endpoint,max_sessions=4,rate_retries=(3 if forced_paper else 1))
    lifecycle=None;forced_identity=None
    result=dict(kind=('forced_ramses_paper_mechanics' if forced_paper else 'prospective_finalized_ramses'),
                started_at=time.time(),reads=[],allocation_authority=False,
                prospective_range=False,research_only=True,forced_paper=bool(forced_paper),
                strategy_evidence_eligible=(False if forced_paper else None))
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
        seen_addresses=set();seen_indices=set();native_pools=[];native_meta={}
        for row in cached:
            if (set(row)!=set(('a','i','n','s','x','y')) or row['n'] not in ('x','y')
                or row['i'] in seen_indices or row['a'] in seen_addresses
                or not 0<=row['i']<baseline['factory_pool_count']):
                raise BoundaryError('ramses_inventory_baseline_entry')
            if (row['x']==discovery_wnative.lower())!=(row['n']=='x') or (row['y']==discovery_wnative.lower())!=(row['n']=='y'):
                raise BoundaryError('ramses_inventory_baseline_native_side')
            seen_indices.add(row['i']);seen_addresses.add(row['a']);native_pools.append(row['a'])
            native_meta[row['a']]=dict(native_side=row['n'],token_x=row['x'],token_y=row['y'],bin_step=row['s'],index=row['i'])

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
                if native_side is not None:
                    native_pools.append(address_i)
                    native_meta[address_i]=dict(native_side=native_side,token_x=auth['token_x'],token_y=auth['token_y'],bin_step=auth['bin_step'],index=index)
        result['native_factory_pools']=native_pools
        result['native_factory_pool_count']=len(native_pools)
        if not native_pools:
            raise BoundaryError('no_factory_registered_native_ramses_pool')

        active_names=frozenset(('Swap','DepositedToBins','WithdrawnFromBins','FlashLoan'))
        economic_topics=[[topic('Swap(address,address,uint24,bytes32,bytes32,uint24,bytes32,bytes32)'),
                          topic('DepositedToBins(address,address,uint256[],bytes32[])'),
                          topic('WithdrawnFromBins(address,address,uint256[],bytes32[])'),
                          topic('FlashLoan(address,address,uint24,bytes32,bytes32,bytes32)')]]
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

        if forced_paper:
            if FORCED_PAPER_POOL not in native_pools:
                raise BoundaryError('forced_ramses_pool_not_in_authenticated_native_inventory')
            raw=rpc.batch([
                ('eth_call',[dict(to=FORCED_PAPER_POOL,data=calldata('getReserves()')),hex(discovery_end)]),
                ('eth_call',[dict(to=FORCED_PAPER_POOL,data=calldata('getLBHooksParameters()')),hex(discovery_end)]),
                ('eth_call',[dict(to=FORCED_PAPER_POOL,data=calldata('getVariableFeeParameters()')),hex(discovery_end)]),
            ],scope='discovery')
            forced_reserves=values(raw[0]);forced_hooks=int(raw[1],16);forced_variable=values(raw[2])
            if forced_hooks!=0 or not any(forced_reserves) or len(forced_variable)!=4:
                raise BoundaryError('forced_ramses_pool_not_currently_watchable')
            meta=native_meta[FORCED_PAPER_POOL]
            native_reserve=forced_reserves[0 if meta['native_side']=='x' else 1]
            scheduled=[dict(address=FORCED_PAPER_POOL,last_update=forced_variable[3],
                            native_reserve=native_reserve,native_side=meta['native_side'],
                            bin_step=meta['bin_step'])]
            cohorts=[scheduled]
            schedule_public=[dict(slot=0,pools=[{k:scheduled[0][k] for k in
                ('address','last_update','native_reserve','native_side','bin_step')}])]
            schedule_hash=hashlib.sha256(json.dumps(schedule_public,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            result['watchable_native_pool_count']=1
            result['watch_schedule']=schedule_public;result['watch_schedule_hash']=schedule_hash
            result['forced_pool_source']='previously_authenticated_forced_mechanics_pool'
            result['selection_rule']='forced_paper_fixed_authenticated_native_pool'
        else:
            # Freeze a deterministic multi-cohort watch schedule using only
            # point-in-time state available before any future observation. The
            # entire schedule is hashed before slot 1; pools are never reranked,
            # promoted or substituted using outcomes observed during the watch.
            variable_rows=rpc.batch([
                ('eth_call',[dict(to=a,data=calldata('getVariableFeeParameters()')),hex(discovery_end)])
                for a in native_pools],scope='discovery')
            ranked=[]
            for a,raw in zip(native_pools,variable_rows):
                variable=values(raw)
                if len(variable)!=4:raise BoundaryError('native_pool_variable_shape')
                ranked.append(dict(address=a,last_update=variable[3],variable=variable))
            ranked.sort(key=lambda row:(row['last_update'],row['address']),reverse=True)
            rank_candidates=ranked[:RANK_POOL_COUNT]
            state_calls=[]
            for row in rank_candidates:
                state_calls.extend([
                    ('eth_call',[dict(to=row['address'],data=calldata('getReserves()')),hex(discovery_end)]),
                    ('eth_call',[dict(to=row['address'],data=calldata('getLBHooksParameters()')),hex(discovery_end)]),
                ])
            state_rows=rpc.batch(state_calls,scope='discovery') if state_calls else []
            watchable=[]
            for i,row in enumerate(rank_candidates):
                reserves=values(state_rows[2*i]);hooks=int(state_rows[2*i+1],16)
                side=native_meta[row['address']]['native_side']
                native_reserve=reserves[0 if side=='x' else 1]
                if hooks==0:
                    watchable.append(dict(address=row['address'],last_update=row['last_update'],
                                          native_reserve=native_reserve,native_side=side,
                                          bin_step=native_meta[row['address']]['bin_step']))
            watchable.sort(key=lambda row:(row['last_update'],row['native_reserve'],row['address']),reverse=True)
            result['watchable_native_pool_count']=len(watchable)
            scheduled=watchable[:WATCH_POOL_COUNT*WATCH_COHORT_COUNT]
            if len(scheduled)!=WATCH_POOL_COUNT:
                raise BoundaryError('insufficient_watchable_native_ramses_pools:'+str(len(scheduled)))
            cohorts=[scheduled[i:i+WATCH_POOL_COUNT] for i in range(0,len(scheduled),WATCH_POOL_COUNT)]
            if len(cohorts)>WATCH_COHORT_COUNT:raise BoundaryError('watch_schedule_capacity')
            schedule_public=[]
            for slot,cohort in enumerate(cohorts):
                schedule_public.append(dict(slot=slot,pools=[
                    {k:row[k] for k in ('address','last_update','native_reserve','native_side','bin_step')}
                    for row in cohort]))
            schedule_hash=hashlib.sha256(json.dumps(schedule_public,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            result['watch_schedule']=schedule_public;result['watch_schedule_hash']=schedule_hash
            result['selection_rule']='first_authenticated_economic_mutation_on_frozen_preentry_watch_schedule'

        if forced_paper:
            result['selection_rule']='forced_paper_first_authenticated_pool_from_frozen_preentry_schedule'
            address=scheduled[0]['address']
            activity=[]
            result['watch_slots']=[]
            result['activity_watch_seconds']=0
            result['discovery_logs']=[]
            result['selection_event_name']='forced_paper_admission'
            result['selection_event']=None
            result['selection_finality']=dict(finalized=True,source='finalized_preentry_state')
            result['forced_admission']=dict(
                authority='forced_ramses_machinery_test',natural_proof=False,
                strategy_evidence_eligible=False,outcome_used_for_selection=False,
                selected_from_schedule_hash=schedule_hash,pool=address)
            result['pool']=address
        else:
            # Observe each precommitted cohort only during its fixed slot. Reserves
            # detect swaps/mints/burns; protocol fees additionally detect flash loans.
            # Exact logs are fetched only after a state change.
            selection=None;selection_decoded=None;activity=[];watch_started=time.monotonic()
            result['watch_slots']=[]
            for slot,cohort in enumerate(cohorts):
                if selection is not None:break
                slot_frontier=rpc.call('eth_getBlockByNumber',['latest',False],scope='discovery')
                cursor=int(slot_frontier['number'],16)
                initial_calls=[]
                for row in cohort:
                    initial_calls.extend([
                        ('eth_call',[dict(to=row['address'],data=calldata('getReserves()')),hex(cursor)]),
                        ('eth_call',[dict(to=row['address'],data=calldata('getProtocolFees()')),hex(cursor)]),
                    ])
                initial=rpc.batch(initial_calls,scope='discovery')
                last_state={}
                for i,row in enumerate(cohort):
                    last_state[row['address']]=(tuple(values(initial[2*i])),tuple(values(initial[2*i+1])))
                slot_started=time.monotonic();slot_end=cursor;polls=0
                while time.monotonic()-slot_started<WATCH_SLOT_SECONDS and selection is None:
                    time.sleep(ACTIVITY_POLL_SECONDS)
                    frontier=rpc.call('eth_getBlockByNumber',['latest',False],scope='discovery')
                    height=int(frontier['number'],16)
                    if height<=cursor:continue
                    calls=[]
                    for row in cohort:
                        calls.extend([
                            ('eth_call',[dict(to=row['address'],data=calldata('getReserves()')),hex(height)]),
                            ('eth_call',[dict(to=row['address'],data=calldata('getProtocolFees()')),hex(height)]),
                        ])
                    current=rpc.batch(calls,scope='discovery');polls+=1
                    changed=[];current_state={}
                    for i,row in enumerate(cohort):
                        state_now=(tuple(values(current[2*i])),tuple(values(current[2*i+1])))
                        current_state[row['address']]=state_now
                        if state_now!=last_state[row['address']]:changed.append(row['address'])
                    if changed:
                        interval=batched_logs(cursor+1,height,address=changed,topics=economic_topics,scope='discovery')
                        activity.extend(interval)
                        eligible=economically_active(interval)
                        if eligible:
                            selection,selection_decoded=sorted(eligible,key=lambda row:(int(row[0]['blockNumber'],16),
                                int(row[0]['transactionIndex'],16),int(row[0]['logIndex'],16),row[0]['address'].lower()))[0]
                    last_state=current_state;cursor=height;slot_end=height
                result['watch_slots'].append(dict(slot=slot,start_block=int(slot_frontier['number'],16),
                                                   end_block=slot_end,polls=polls,
                                                   seconds=time.monotonic()-slot_started,
                                                   selected=selection is not None))
            result['activity_watch_seconds']=time.monotonic()-watch_started
            result['discovery_logs']=activity
            if selection is None:raise BoundaryError('no_natural_native_ramses_activity_on_frozen_watch_schedule')
            result['selection_event_name']=selection_decoded['name']
            address=selection['address'];result['selection_event']=selection
            selection_block=int(selection['blockNumber'],16)
            finality_started=time.monotonic()
            selection_finalized=rpc.call('eth_getBlockByNumber',['finalized',False],scope='discovery')
            while int(selection_finalized['number'],16)<selection_block:
                if time.monotonic()-finality_started>=FINALITY_WAIT_SECONDS:
                    raise BoundaryError('selection_finality_timeout')
                time.sleep(10)
                selection_finalized=rpc.call('eth_getBlockByNumber',['finalized',False],scope='discovery')
            selection_header=rpc.call('eth_getBlockByNumber',[hex(selection_block),False],scope='discovery')
            if selection_header['hash']!=selection['blockHash']:
                raise BoundaryError('selection_reorg_before_freeze')
            selection_receipt=rpc.receipt(selection['transactionHash'],selection['blockHash'],scope='discovery')
            if (int(selection_receipt['status'],16)!=1
                or selection_receipt['transactionIndex']!=selection['transactionIndex']
                or selection not in selection_receipt['logs']):
                raise BoundaryError('selection_receipt_identity_disagreement')
            result['selection_finality']=dict(finalized=True,block=selection_block,block_hash=selection['blockHash'],
                                              waited_seconds=time.monotonic()-finality_started)
        result['factory_checks']={}
        result['pool']=address
        start_frontier=rpc.call('eth_getBlockByNumber',['finalized',False],scope='connectivity')
        start=int(start_frontier['number'],16);start_ts=int(start_frontier['timestamp'],16)
        result['start_frontier']={k:start_frontier[k] for k in ('hash','number','timestamp','parentHash')}
        explicit=read(factory,'isPool(address)',(address,),start,scope='pool')
        result['factory_checks'][address]=explicit
        if int(explicit,16)!=1:raise BoundaryError('selected_pool_lost_factory_membership')
        result['pool_code']=rpc.call('eth_getCode',[address,hex(start)],scope='pool')
        clone=authenticate_pool(result['pool_code'],factory_member=True)
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
        if forced_paper:
            if not forced_db_path: raise BoundaryError('forced_ramses_paper_db_required')
            from .ramses_paper import RamsesPaper
            forced_capital=max(PAPER_NATIVE_CAPITAL,paper_position(freeze,0)['initial_cost_basis'])
            lifecycle=RamsesPaper(forced_db_path,forced_capital)
            forced_identity='forced:'+address.lower()+':'+str(start)+':'+freeze['proposal_hash']
            reserved=lifecycle.reserve(
                forced_identity,pool=address,freeze=freeze,proposal_index=0,
                block=start,block_hash=start_frontier['hash'],at=start_ts)
            opened=lifecycle.enter(forced_identity,at=start_ts)
            before_restart=lifecycle.reconcile()
            lifecycle.close()
            lifecycle=RamsesPaper(forced_db_path,forced_capital)
            after_restart=lifecycle.reconcile()
            if before_restart!=after_restart or lifecycle.position(forced_identity)['status']!='open':
                raise BoundaryError('forced_ramses_entry_restart_reconciliation')
            result['forced_paper_entry']=dict(
                identity=forced_identity,reservation=reserved,opened=opened,
                reconciliation=after_restart,restart_proven=True)
        # Nothing after this point can alter the frozen proposal definitions.
        target=start_ts+FORWARD_SECONDS
        if forced_paper:
            # Forced machinery proof has no need to anchor an unfinalized head.
            # Wait directly for finalized chain time to cross the frozen +60s horizon.
            finality_deadline=time.monotonic()+FORCED_FORWARD_FINALITY_WAIT_SECONDS
            end_frontier=rpc.call('eth_getBlockByNumber',['finalized',False],scope='forward')
            while int(end_frontier['timestamp'],16)<target:
                if time.monotonic()>=finality_deadline:raise BoundaryError('forced_terminal_finality_timeout')
                time.sleep(10)
                end_frontier=rpc.call('eth_getBlockByNumber',['finalized',False],scope='forward')
            finalized_frontier=end_frontier
            end_frontier,previous_frontier,search_reads=_first_finalized_block_at_or_after(
                rpc,start,finalized_frontier,target)
            end=int(end_frontier['number'],16);end_ts=int(end_frontier['timestamp'],16)
            result['forced_finalized_horizon']=dict(
                target_timestamp=target,
                finalized_frontier_block=int(finalized_frontier['number'],16),
                finalized_frontier_timestamp=int(finalized_frontier['timestamp'],16),
                selected_block=end,selected_timestamp=end_ts,
                previous_block=int(previous_frontier['number'],16),
                previous_timestamp=int(previous_frontier['timestamp'],16),
                search_reads=search_reads,
                overshoot_seconds=end_ts-target)
        else:
            head_deadline=time.monotonic()+FORWARD_HEAD_WAIT_SECONDS
            end_candidate=rpc.call('eth_getBlockByNumber',['latest',False],scope='forward')
            while int(end_candidate['timestamp'],16)<target:
                if time.monotonic()>=head_deadline:raise BoundaryError('insufficient_forward_head_window')
                time.sleep(5)
                end_candidate=rpc.call('eth_getBlockByNumber',['latest',False],scope='forward')
            end=int(end_candidate['number'],16);end_ts=int(end_candidate['timestamp'],16)
            finality_deadline=time.monotonic()+FORWARD_FINALITY_WAIT_SECONDS
            finalized_frontier=rpc.call('eth_getBlockByNumber',['finalized',False],scope='forward')
            while int(finalized_frontier['number'],16)<end:
                if time.monotonic()>=finality_deadline:raise BoundaryError('terminal_finality_timeout')
                time.sleep(10)
                finalized_frontier=rpc.call('eth_getBlockByNumber',['finalized',False],scope='forward')
            end_frontier=rpc.call('eth_getBlockByNumber',[hex(end),False],scope='forward')
            if end_frontier['hash']!=end_candidate['hash']:
                raise BoundaryError('terminal_reorg_before_finality')
        result['frontier']={k:end_frontier[k] for k in ('hash','number','timestamp','parentHash')}
        if forced_paper:
            # The provider only proved 10-block log ranges on this chain. Keep
            # that exact range bound but pace batches so the ~60s fast-chain
            # interval does not trip endpoint rate limits.
            rpc.batch_size=min(rpc.batch_size,10)
            rpc.batch_pause=max(rpc.batch_pause,1.5)
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
        if not events and not forced_paper:raise BoundaryError('insufficient_forward_activity')
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
        if forced_paper:
            chosen=observations[0]
            lifecycle.exit_intent(forced_identity,at=end_ts,reason='forced_test_horizon')
            final_position=lifecycle.finish(forced_identity,outcome=chosen['outcome'],at=end_ts)
            before_final_restart=lifecycle.reconcile()
            lifecycle.close()
            from .ramses_paper import RamsesPaper
            lifecycle=RamsesPaper(forced_db_path,forced_capital)
            after_final_restart=lifecycle.reconcile()
            if before_final_restart!=after_final_restart:
                raise BoundaryError('forced_ramses_final_restart_reconciliation')
            final_position=lifecycle.position(forced_identity)
            result['forced_paper_final']=dict(
                position=final_position,reconciliation=after_final_restart,
                restart_proven=True,terminal_equality=result['replay']['terminal_equality'],
                paper_only=True,allocation_authority=False,natural_proof=False,
                strategy_evidence_eligible=False)
            result['mechanics_complete']=final_position['status']=='settled'
            if not result['mechanics_complete']:
                raise BoundaryError('forced_ramses_unwind_unavailable')
        else:
            if any(o['outcome']['unresolved_inventory'] for o in observations):
                raise BoundaryError('unwind_liquidity_unavailable')
            # Exact hypothetical add/remove/claim/unwind gas is not inferable from unrelated receipts.
            # Do not manufacture it; after-cost return stays null until executable cost evidence exists.
            raise BoundaryError('cost_evidence_unavailable')
    except BoundaryError as exc:
        result['boundary']=str(exc)
    if lifecycle is not None:
        try: lifecycle.close()
        except Exception: pass
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