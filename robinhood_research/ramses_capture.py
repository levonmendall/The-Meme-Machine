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
from .provider_topology import configured_dlmm_rpc
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
        session=configured_dlmm_rpc(self.endpoint,limit=200,per_scope=200,retries=0)
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