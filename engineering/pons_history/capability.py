"""Small separately authorized range comparison; importing this makes no calls.

The canonical, already-governed provider and disposable PonsHistory are supplied
by the caller. There is no new endpoint, provider connection, approval token or
rate. A comparison receipt proves only this endpoint/filter/range sample. It is
not historical completeness or provider-capacity acceptance.
"""
import time
from meme_machine.lanes.pons import BoundaryError, CHAIN_ID
from meme_machine.lanes.pons.pons_historical import Preparation, number, order, event_id
from meme_machine.lanes.pons.provider_admission import decision_work
from meme_machine.runtime.journal import digest

LIMITS = dict(wall_seconds=45, logical_rpc_elements=64, physical_http_attempts=32,
              estimated_cu=6400, maximum_range_blocks=40, maximum_response_bytes=2000000)


@decision_work(5)
def compare(history, provider, first, *, clock=time.monotonic):
    """Compare one forty-block query to four preserved ten-block queries.

    Choose a historical range with at least one known authentic factory event.
    An empty comparison alone is INSUFFICIENT_SAMPLE, not a capability PASS.
    All errors and exhausted bounds leave no successful support receipt.
    """
    if type(first) is not int or first < 1:
        raise ValueError('capability_range_identity')
    started=clock()
    elements=attempts=0
    p=Preparation(history,provider)
    original=p.calls
    def bounded(calls,**kwargs):
        nonlocal elements,attempts
        if (clock()-started>=LIMITS['wall_seconds'] or elements+len(calls)>LIMITS['logical_rpc_elements']
                or attempts+1>LIMITS['physical_http_attempts']):
            raise BoundaryError('capability_budget_exhausted')
        rpc=p.rpc(len(calls))
        if getattr(rpc,'retries',0)!=0 or getattr(rpc,'max_response',2000000)>2000000:
            raise BoundaryError('capability_transport_bounds')
        elements+=len(calls);attempts+=1
        previous=getattr(rpc,'evidence_deadline',None)
        deadline=started+LIMITS['wall_seconds']
        rpc.evidence_deadline=deadline if previous is None else min(previous,deadline)
        try:return original(calls,**kwargs)
        finally:rpc.evidence_deadline=previous
    p.calls=bounded
    query=p.population_filter();last=first+39
    source=bounded([('eth_chainId',[]),('eth_getBlockByNumber',['0x0',False])])
    if int(source[0],16)!=CHAIN_ID or number(source[1])!=0:
        raise BoundaryError('capability_chain_identity')
    before=bounded([('eth_getBlockByNumber',[hex(first-1),False]),
                    ('eth_getBlockByNumber',[hex(last),False])])
    if number(before[0])!=first-1 or number(before[1])!=last:
        raise BoundaryError('capability_boundary_identity')
    spans=[(b,min(last,b+9)) for b in range(first,last+1,10)]
    baseline=bounded([('eth_getLogs',[dict(query,fromBlock=hex(a),toBlock=hex(b))]) for a,b in spans])
    enlarged=bounded([('eth_getLogs',[dict(query,fromBlock=hex(first),toBlock=hex(last))])])[0]
    if (not isinstance(enlarged,list) or any(not isinstance(x,list) for x in baseline)
            or len(enlarged)>=p.log_limit or any(len(x)>=p.log_limit for x in baseline)):
        raise BoundaryError('capability_incomplete_response')
    def exact(events):
        out={}
        for e in events:
            ident=event_id(e)
            if ident in out and out[ident]!=e:
                raise BoundaryError('capability_conflicting_duplicate')
            out[ident]=e
        return sorted(out.values(),key=order)
    reference=exact([e for batch in baseline for e in batch]);candidate=exact(enlarged)
    if reference!=candidate:
        raise BoundaryError('capability_range_population_disagreement')
    if not reference:
        raise BoundaryError('capability_nonempty_sample_required')
    p._witness(reference,query,first,last)
    after=bounded([('eth_getBlockByNumber',[hex(first-1),False]),
                   ('eth_getBlockByNumber',[hex(last),False])])
    if after!=before:
        raise BoundaryError('capability_range_reorg')
    if clock()-started>=LIMITS['wall_seconds']:
        raise BoundaryError('capability_wall_exhausted')
    return dict(schema='pons-log-range-comparison-v1',chain_id=CHAIN_ID,
        genesis_hash=source[1]['hash'],provider_fingerprint=p.fingerprint,filter=query,
        first=first,last=last,range_blocks=40,equal=True,baseline_digest=digest(reference),
        canonical_end_hash=after[1]['hash'],event_count=len(reference),
        limits=LIMITS,logical_rpc_elements=elements,physical_attempt_upper_bound=attempts,
        elapsed_seconds=clock()-started,provider_certified=False,
        limitation='one nonempty forty-block sample; no larger range or seven-day parity established')
