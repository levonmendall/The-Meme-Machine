"""Pons-native quote transport; exact arithmetic stays in the existing adapter."""
from contextlib import contextmanager
import time

from . import BoundaryError
from .abi import calldata
from .evidence import canonical
from .pons_natural_paper import V4_QUOTER,ZERO,_v4_quoter_calldata,_v4_quote as native_v4_quote


def pinned_block(rpc,method,header):
    # Use proved EIP-1898 support. Otherwise the fresh, uncached numeric boundary
    # below fences the same canonical block; no numeric state is durably reused.
    if method in getattr(rpc,'hash_state_supported',()):
        return dict(blockHash=header['hash'],requireCanonical=True)
    return header['number']


@contextmanager
def quote_deadline(rpc,started):
    previous=getattr(rpc,'evidence_deadline',None)
    rpc.evidence_deadline=started+5
    try:yield
    finally:rpc.evidence_deadline=previous


def canonical_boundary(rpc,header,scope):
    # Do not let a caller's immutable number alias answer membership.
    previous=getattr(rpc,'evidence_pins',{})
    rpc.evidence_pins={}
    try:current=rpc.call('eth_getBlockByNumber',[header['number'],False],scope=scope)
    finally:rpc.evidence_pins=previous
    if current['number']!=header['number'] or current['hash']!=header['hash']:
        raise BoundaryError('pons_quote_canonical_membership_disagreement')


class PinnedV4Reads:
    """One current header and one bounded state/cost/membership batch."""
    def __init__(self,rpc,key,side,amount):
        self.rpc=rpc;self.key=key;self.side=side;self.amount=amount;self.header=None;self.cache=None

    def call(self,method,params,*,scope):
        if method=='eth_getBlockByNumber' and params[0]=='latest':
            self.header=self.rpc.call(method,params,scope=scope)
            return self.header
        if self.header is None:raise BoundaryError('pons_v4_quote_header_missing')
        if self.cache is None:
            block=self.header['number'];zero_for_one=self.key.currency0!=ZERO if self.side=='sell' else self.key.currency0==ZERO
            calls=[('eth_getCode',[V4_QUOTER,block]),
                ('eth_call',[dict(to=V4_QUOTER,data=calldata('poolManager()')),block]),
                ('eth_call',[dict(to=V4_QUOTER,data=_v4_quoter_calldata(self.key,zero_for_one,self.amount)),block]),
                ('eth_gasPrice',[])]
            wire=[]
            for m,p in calls:
                wire.append((m,[*p[:-1],pinned_block(self.rpc,m,self.header)] if m in ('eth_call','eth_getCode') else p))
            wire.append(('eth_getBlockByNumber',[block,False]))
            previous=getattr(self.rpc,'evidence_pins',{});self.rpc.evidence_pins={}
            try:values=self.rpc.batch(wire,scope=scope)
            finally:self.rpc.evidence_pins=previous
            if not isinstance(values,list) or len(values)!=len(wire):raise BoundaryError('pons_v4_quote_batch_incomplete')
            if values[-1]['number']!=block or values[-1]['hash']!=self.header['hash']:
                raise BoundaryError('pons_quote_canonical_membership_disagreement')
            self.cache={canonical([m,p]):v for (m,p),v in zip(calls,values)}
        identity=canonical([method,params])
        if identity not in self.cache:raise BoundaryError('pons_v4_quote_read_not_pinned')
        return self.cache.pop(identity)


def v4_quote(rpc,key,pool_id,amount,gas_units,store,label,*,side='sell',local_freshness=False):
    started=time.monotonic()
    with quote_deadline(rpc,started):
        return native_v4_quote(PinnedV4Reads(rpc,key,side,amount),key,pool_id,amount,gas_units,store,label,
            side=side,local_freshness=local_freshness)
