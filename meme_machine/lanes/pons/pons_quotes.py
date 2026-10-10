"""Pons-native quote transport; exact arithmetic stays in the existing adapter."""
from contextlib import contextmanager
import time
import sqlite3

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
    completed_canonical_read(rpc,header)
    return current


def completed_canonical_read(rpc,header):
    """Publish a target proof only after an ordered membership response."""
    from meme_machine.runtime.source_artifacts import REGISTRY
    raw=getattr(rpc,'_current',rpc)
    fingerprint=getattr(raw,'provider_fingerprint',None);sequence=getattr(raw,'used',None)
    admission=getattr(raw,'shared_admission',None)
    try:activity=admission.activity_marker() if admission is not None else None
    except (OSError,ValueError,sqlite3.Error):activity=None
    rpc.last_canonical_read=(dict(number=header['number'],hash=header['hash'],session=id(raw),
        sequence=sequence,completed=time.monotonic(),provider_fingerprint=fingerprint,source_generation=REGISTRY.generation,
        provider_activity=activity)
        if isinstance(fingerprint,str) and getattr(raw,'chain_verified',False) is True
            and type(sequence) is int and (admission is None or activity is not None) else None)


def unchanged_canonical_read(rpc,check,header):
    """One ordered read, reused only before any further provider operation."""
    from meme_machine.runtime.source_artifacts import REGISTRY
    raw=getattr(rpc,'_current',rpc)
    valid=(isinstance(check,dict) and check is getattr(rpc,'last_canonical_read',None)
        and check['session']==id(raw) and check['sequence']==getattr(raw,'used',None)
        and check['provider_fingerprint']==getattr(raw,'provider_fingerprint',None)
        and getattr(raw,'chain_verified',False) is True and check['source_generation']==REGISTRY.generation
        and check['number']==header['number'] and check['hash']==header['hash']
        and 0<=time.monotonic()-check['completed']<=5)
    if not valid:return False
    admission=getattr(raw,'shared_admission',None)
    if admission is None:return check.get('provider_activity') is None
    try:return check.get('provider_activity') is not None and admission.activity_marker()==check['provider_activity']
    except (OSError,ValueError,sqlite3.Error):return False


class PinnedV4Reads:
    """One current header, bounded state batch, then ordered membership fence."""
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
            previous=getattr(self.rpc,'evidence_pins',{});self.rpc.evidence_pins={}
            try:values=self.rpc.batch(wire,scope=scope)
            finally:self.rpc.evidence_pins=previous
            if not isinstance(values,list) or len(values)!=len(wire):raise BoundaryError('pons_v4_quote_batch_incomplete')
            # JSON-RPC batch ordering says nothing about execution ordering.
            # This uncached read starts AFTER every dependent state response.
            canonical_boundary(self.rpc,self.header,scope)
            resolved=([prior['code'],prior['manager']]+values) if same else values
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


class _SharedV4Reads:
    """One already-authenticated acquisition, consumed by native quote parsing."""
    def __init__(self,header,values,*,started,wall,observed):
        self.header=header;self.values=values
        self.original_acquisition_monotonic=started
        self.original_acquisition_wall=wall;self.original_observed_at=observed
    def call(self,method,params,*,scope):
        if method=='eth_getBlockByNumber' and params==['latest',False]:return self.header
        try:return self.values[canonical([method,params])]
        except KeyError:raise BoundaryError('pons_shared_quote_evidence_missing') from None


def shared_v4_quotes(rpc,requests,*,deadline_seconds=3,prepare_history=None,deadline_at=None):
    """Acquire already-due exact simulations once, with the original deadlines.

    Unknown endpoint resources keep this path inactive before any purchase.
    Every caller still runs the native adapter and its own quantity/finality
    checks. This does not wait for another position or retain market state.
    """
    resources=getattr(rpc,'shared_quote_resources',None)
    single=len(requests)==1
    if not single and (not isinstance(resources,dict) or resources.get('validated') is not True
            or resources.get('provider_fingerprint')!=getattr(rpc,'provider_fingerprint',None)
            or getattr(rpc,'chain_verified',False) is not True
            or not {'eth_call','eth_getCode'}<=set(getattr(rpc,'hash_state_supported',()))):
        raise BoundaryError('pons_shared_quote_resources_unproved')
    # One owner uses exactly its existing four-element native quote batch. It
    # needs no new endpoint capability, larger payload or cross-owner proof.
    resources=resources or {}
    max_bytes=rpc.max_response if single else resources.get('max_response_bytes')
    max_latency=resources.get('max_latency_seconds')
    elements=len(requests)+3
    if (not 1<=len(requests)<=47 or deadline_seconds not in (3,5)
            or not isinstance(max_bytes,int) or not 0<max_bytes<=rpc.max_response
            or not single and (not isinstance(max_latency,(int,float)) or not 0<=max_latency<=1
            or elements>resources.get('max_logical_elements',0)
            or 1+3*max_latency>=deadline_seconds
            or 80+26*(len(requests)+1)>resources.get('max_throughput_cu',0))):
        raise BoundaryError('pons_shared_quote_resource_or_deadline_bound')
    from meme_machine.runtime.source_artifacts import REGISTRY
    source_generation=REGISTRY.generation
    started=time.monotonic();wall=time.time()
    effective=started-5+deadline_seconds
    if deadline_at is not None:effective=min(effective,deadline_at-5)
    with quote_deadline(rpc,effective):
        header=rpc.call('eth_getBlockByNumber',['latest',False],scope='pons_survivor')
        if any(r.get('block_hash') not in (None,header['hash']) for r in requests):
            raise BoundaryError('pons_shared_quote_canonical_targets_differ')
        logical=[('eth_getCode',[V4_QUOTER,header['number']]),
            ('eth_call',[dict(to=V4_QUOTER,data=calldata('poolManager()')),header['number']]),
            ('eth_gasPrice',[])]
        for r in requests:
            side=r.get('side','sell');amount=r['amount'];key=r['key']
            if side not in ('buy','sell') or not isinstance(amount,int) or amount<=0:
                raise BoundaryError('pons_shared_quote_request_identity')
            direction=key.currency0!=ZERO if side=='sell' else key.currency0==ZERO
            logical.append(('eth_call',[dict(to=V4_QUOTER,data=_v4_quoter_calldata(key,direction,amount)),header['number']]))
        unique=list({canonical([m,p]):(m,p) for m,p in logical}.values())
        wire=[(m,[*p[:-1],pinned_block(rpc,m,header)] if m in ('eth_call','eth_getCode') else p) for m,p in unique]
        if prepare_history is None:
            values=rpc.batch(wire,scope='pons_survivor')
            if not isinstance(values,list) or len(values)!=len(wire):raise BoundaryError('pons_shared_quote_incomplete')
            canonical_boundary(rpc,header,'pons_survivor')
        else:
            # Native held-history acquisition fences target, all event blocks
            # and prior checkpoints AFTER state, logs and receipt enrichment.
            # It returns only authenticated evidence; no quote is exposed yet.
            authenticated,values=prepare_history(header,wire)
            boundary=authenticated.get(int(header['number'],16))
            if not boundary or boundary.get('hash')!=header['hash']:
                raise BoundaryError('pons_shared_quote_history_boundary_missing')
            # The history callback's numeric fence completed AFTER state,
            # logs, receipts and sender fallback. Reuse this actual ordered
            # proof; a same-batch membership read would not establish it.
            completed_canonical_read(rpc,header)
        if not isinstance(values,list) or len(values)!=len(wire):raise BoundaryError('pons_shared_quote_incomplete')
        if len(canonical(values).encode())>max_bytes:raise BoundaryError('pons_shared_quote_payload_bound')
    observed=time.time()
    prepared=_SharedV4Reads(header,{canonical([m,p]):v for (m,p),v in zip(unique,values)},
        started=started,wall=wall,observed=observed)
    from .evidence import Store
    result=[]
    for r in requests:
        store=Store(':memory:')
        try:
            q,meta,ledger=native_v4_quote(prepared,r['key'],r['pool_id'],r['amount'],r['gas_units'],store,
                'shared-held-exact',side=r.get('side','sell'),local_freshness=True)
            q.check(int(time.time()),r['pool_id'],r.get('side','sell'),r['amount'],q.stamp.kind,finality_ledger=ledger)
            result.append(dict(quote=q,meta=meta,acquired=started,header=header,reads=prepared,
                source_generation=source_generation))
        finally:store.close()
    if REGISTRY.generation!=source_generation:
        rpc.last_canonical_read=None
        raise BoundaryError('pons_shared_quote_source_changed')
    if (not 0<=time.monotonic()-started<=deadline_seconds or
            deadline_at is not None and time.monotonic()>deadline_at):
        raise BoundaryError('pons_shared_quote_original_deadline')
    # Preserve the original exact-block identity reuse for subsequent native
    # partial-exit simulations. Never retain gas, price or a number alias.
    if isinstance(getattr(rpc,'provider_fingerprint',None),str) and rpc.chain_verified is True:
        identity=(rpc.provider_fingerprint,header['number'],header['hash'],V4_QUOTER)
        pair=[prepared.values[canonical([m,p])] for m,p in logical[:2]]
        if all(isinstance(v,str) for v in pair) and sum(len(v.encode()) for v in pair)<=rpc.max_response:
            rpc.v4_identity_snapshot=dict(identity=identity,code=pair[0],manager=pair[1])
    return result


def shared_exit_quotes(rpc,requests):
    """Refresh execution facts for already-due exits at one original head.

    Each request carries a previously parsed native full-position quotation.
    Partial quantities receive independent exact simulations. The fresh head
    and gas are common; membership is read AFTER every dependent response.
    A changed head, incomplete batch or unproved resource envelope refuses
    reuse, leaving the caller's original native exit path authoritative.
    """
    resources=getattr(rpc,'shared_quote_resources',None)
    if (not isinstance(resources,dict) or resources.get('validated') is not True
            or resources.get('provider_fingerprint')!=getattr(rpc,'provider_fingerprint',None)
            or getattr(rpc,'chain_verified',False) is not True
            or not {'eth_call','eth_getCode'}<=set(getattr(rpc,'hash_state_supported',()))):
        raise BoundaryError('pons_shared_quote_resources_unproved')
    if not 2<=len(requests)<=47:raise BoundaryError('pons_shared_exit_count')
    from meme_machine.runtime.source_artifacts import REGISTRY
    generation=REGISTRY.generation
    first=requests[0]['prepared'];header=first['header'];started=first['acquired']
    if (any(r['prepared']['header']!=header or r['prepared']['acquired']!=started
            or r['prepared'].get('source_generation')!=generation for r in requests)
            or not 0<=time.monotonic()-started<=3):
        raise BoundaryError('pons_shared_exit_original_head_stale')
    logical=[('eth_getBlockByNumber',['latest',False]),('eth_gasPrice',[])]
    for r in requests:
        q=r['prepared']['quote'];amount=r['amount']
        if type(amount) is not int or not 0<amount<=q.amount_in or q.market!=r['pool_id']:
            raise BoundaryError('pons_shared_exit_quantity_identity')
        if amount!=q.amount_in:
            direction=r['key'].currency0!=ZERO
            logical.append(('eth_call',[dict(to=V4_QUOTER,
                data=_v4_quoter_calldata(r['key'],direction,amount)),header['number']]))
    unique=list({canonical([m,p]):(m,p) for m,p in logical}.values())
    max_bytes=resources.get('max_response_bytes');latency=resources.get('max_latency_seconds')
    if (not isinstance(max_bytes,int) or not 0<max_bytes<=rpc.max_response
            or not isinstance(latency,(int,float)) or not 0<=latency<=1
            or len(unique)>resources.get('max_logical_elements',0)
            or 60+26*(len(unique)-2)>resources.get('max_throughput_cu',0)):
        raise BoundaryError('pons_shared_quote_resource_or_deadline_bound')
    wire=[(m,[*p[:-1],pinned_block(rpc,m,header)] if m=='eth_call' else p) for m,p in unique]
    with quote_deadline(rpc,started):
        values=rpc.batch(wire,scope='pons_survivor')
        if (not isinstance(values,list) or len(values)!=len(unique) or any(v is None for v in values)
                or len(canonical(values).encode())>max_bytes):
            raise BoundaryError('pons_shared_quote_incomplete')
        if values[0].get('number')!=header['number'] or values[0].get('hash')!=header['hash']:
            raise BoundaryError('pons_shared_exit_head_changed')
        canonical_boundary(rpc,header,'pons_survivor')
    purchased={canonical([m,p]):v for (m,p),v in zip(unique,values)}
    from .evidence import Store
    results=[]
    for r in requests:
        old=r['prepared'];amount=r['amount'];direction=r['key'].currency0!=ZERO
        call=('eth_call',[dict(to=V4_QUOTER,data=_v4_quoter_calldata(r['key'],direction,amount)),header['number']])
        retained=dict(old['reads'].values)
        retained[canonical(['eth_gasPrice',[]])]=purchased[canonical(['eth_gasPrice',[]])]
        if amount!=old['quote'].amount_in:retained[canonical(list(call))]=purchased[canonical(list(call))]
        reads=_SharedV4Reads(header,retained,started=started,
            wall=old['reads'].original_acquisition_wall,observed=time.time())
        store=Store(':memory:')
        try:
            q,meta,ledger=native_v4_quote(reads,r['key'],r['pool_id'],amount,r['gas_units'],store,
                'shared-exit-exact',side='sell',local_freshness=True)
            q.check(int(time.time()),r['pool_id'],'sell',amount,q.stamp.kind,finality_ledger=ledger)
            results.append(dict(quote=q,meta=meta,acquired=started,header=header,
                canonical_read=getattr(rpc,'last_canonical_read',None)))
        finally:store.close()
    if REGISTRY.generation!=generation:
        rpc.last_canonical_read=None
        raise BoundaryError('pons_shared_quote_source_changed')
    if not 0<=time.monotonic()-started<=5:raise BoundaryError('pons_shared_exit_original_quote_stale')
    return results
