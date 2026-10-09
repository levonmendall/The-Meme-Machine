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
    def __init__(self,rpc,key,side,amount,*,fresh_head=None):
        self.rpc=rpc;self.key=key;self.side=side;self.amount=amount;self.header=None;self.cache=None
        self.identity_snapshot=None
        self.fresh_head=fresh_head
        self.used_shared_head=False
        self.shared_head_at=None

    def _identity_key(self):
        # Identical state at ONE authenticated canonical block is immutable.
        # No deployment/manager fact is inferred for a later block, credential,
        # chain or process. This uses the original before/after numeric fence;
        # verified EIP-1898 reuse may already eliminate these same reads.
        fingerprint=getattr(self.rpc,'provider_fingerprint',None)
        if not fingerprint or getattr(self.rpc,'chain_verified',False) is not True:return None
        return (fingerprint,self.header['number'],self.header['hash'],V4_QUOTER)

    def call(self,method,params,*,scope):
        if method=='eth_getBlockByNumber' and params[0]=='latest':
            # A Current monitoring turn already purchased this authoritative
            # head. Reuse only within the original five-second quote window;
            # canonical numeric membership is still checked after the quote.
            candidate=self.fresh_head
            valid=False
            if (isinstance(candidate,tuple) and len(candidate)==2
                    and isinstance(candidate[0],dict)):
                head,at=candidate
                try:
                    age=time.monotonic()-float(at)
                    valid=(0<=age<=3 and isinstance(head.get('number'),str)
                        and isinstance(head.get('hash'),str)
                        and isinstance(head.get('timestamp'),str)
                        and isinstance(head.get('parentHash'),str))
                except (TypeError,ValueError,OverflowError):valid=False
            if valid:
                self.header=dict(candidate[0])
                self.used_shared_head=True
                self.shared_head_at=float(candidate[1])
            else:
                self.header=self.rpc.call(method,params,scope=scope)
            return self.header
        if self.header is None:raise BoundaryError('pons_v4_quote_header_missing')
        if self.cache is None:
            block=self.header['number'];zero_for_one=self.key.currency0!=ZERO if self.side=='sell' else self.key.currency0==ZERO
            calls=[('eth_getCode',[V4_QUOTER,block]),
                ('eth_call',[dict(to=V4_QUOTER,data=calldata('poolManager()')),block]),
                ('eth_call',[dict(to=V4_QUOTER,data=_v4_quoter_calldata(self.key,zero_for_one,self.amount)),block]),
                ('eth_gasPrice',[])]
            identity=self._identity_key()
            prior=getattr(self.rpc,'v4_identity_snapshot',None)
            same=(identity is not None and isinstance(prior,dict) and prior.get('identity')==identity)
            requested=calls[2:] if same else calls
            wire=[]
            for m,p in requested:
                wire.append((m,[*p[:-1],pinned_block(self.rpc,m,self.header)] if m in ('eth_call','eth_getCode') else p))
            wire.append(('eth_getBlockByNumber',[block,False]))
            previous=getattr(self.rpc,'evidence_pins',{});self.rpc.evidence_pins={}
            try:values=self.rpc.batch(wire,scope=scope)
            finally:self.rpc.evidence_pins=previous
            if not isinstance(values,list) or len(values)!=len(wire):raise BoundaryError('pons_v4_quote_batch_incomplete')
            if values[-1]['number']!=block or values[-1]['hash']!=self.header['hash']:
                raise BoundaryError('pons_quote_canonical_membership_disagreement')
            resolved=([prior['code'],prior['manager']]+values[:-1]) if same else values[:-1]
            self.cache={canonical([m,p]):v for (m,p),v in zip(calls,resolved)}
            if (identity is not None and all(isinstance(v,str) for v in resolved[:2])
                    and sum(len(v.encode()) for v in resolved[:2])<=getattr(self.rpc,'max_response',2_000_000)):
                self.identity_snapshot=dict(identity=identity,code=resolved[0],manager=resolved[1])
        identity=canonical([method,params])
        if identity not in self.cache:raise BoundaryError('pons_v4_quote_read_not_pinned')
        return self.cache.pop(identity)


def v4_quote(rpc,key,pool_id,amount,gas_units,store,label,*,side='sell',
             local_freshness=False,fresh_head=None):
    started=time.monotonic()
    reads=PinnedV4Reads(rpc,key,side,amount,fresh_head=fresh_head)
    try:
        # If a previous authenticated head is selected, it does NOT gain
        # another five seconds of freshness just because the quote began now.
        effective=started
        if (isinstance(fresh_head,tuple) and len(fresh_head)==2
                and isinstance(fresh_head[1],(int,float))
                and 0<=started-fresh_head[1]<=3):
            effective=min(started,float(fresh_head[1]))
        with quote_deadline(rpc,effective):
            result=native_v4_quote(reads,key,pool_id,amount,gas_units,store,label,
                side=side,local_freshness=local_freshness)
        if (reads.used_shared_head and
                (reads.shared_head_at is None or
                 not 0<=time.monotonic()-reads.shared_head_at<=5)):
            raise BoundaryError('pons_v4_shared_head_quote_stale')
        # Publish only after native code, manager, output and freshness checks.
        # One bounded pair on the existing RPC owner; no quote, gas, economic
        # state, new database or cross-block identity is retained here.
        if reads.identity_snapshot is not None:rpc.v4_identity_snapshot=reads.identity_snapshot
        return result
    except BoundaryError:
        rpc.v4_identity_snapshot=None
        raise
