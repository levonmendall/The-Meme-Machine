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
from meme_machine.lanes.pons.identity import authenticate

LIMITS = dict(wall_seconds=45, logical_rpc_elements=64, physical_http_attempts=32,
              estimated_cu=6400, maximum_range_blocks=40, maximum_response_bytes=2000000,
              temporary_bytes=128*1024*1024,provider_workers=1,application_retries=0)


@decision_work(5)
def compare(history, provider, first, *, clock=time.monotonic, required_transaction=None):
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
    source=bounded([('eth_chainId',[]),('eth_getBlockByNumber',['0x0',False]),
                    ('eth_getCode',[query['address'],hex(first)])])
    if int(source[0],16)!=CHAIN_ID or number(source[1])!=0:
        raise BoundaryError('capability_chain_identity')
    deployment=authenticate('pons_v2_factory',query['address'],source[2])
    before=bounded([('eth_getBlockByNumber',[hex(first-1),False]),
                    ('eth_getBlockByNumber',[hex(first),False]),
                    ('eth_getBlockByNumber',[hex(last),False])])
    if (number(before[0])!=first-1 or number(before[1])!=first or number(before[2])!=last
            or before[1]['parentHash']!=before[0]['hash']):
        raise BoundaryError('capability_boundary_identity')
    spans=[(b,min(last,b+9)) for b in range(first,last+1,10)]
    baseline=bounded([('eth_getLogs',[dict(query,fromBlock=hex(a),toBlock=hex(b))]) for a,b in spans])
    # Retain partial comparison evidence even when the larger request is rejected.
    # Each small response must obey its own interval, not merely the union.
    for rows,(a,b) in zip(baseline,spans):
        p._validated(rows,query,a,b)
        if rows!=sorted(rows,key=order):
            raise BoundaryError('capability_event_order_disagreement')
    reference=[e for rows in baseline for e in rows]
    history.set_meta('pons_capability_baseline',dict(spans=spans,event_count=len(reference),
        digest=digest(reference),identities=[event_id(e) for e in reference],
        order=[order(e) for e in reference],boundaries=before,genesis_hash=source[1]['hash'],
        deployment=deployment,authenticated=False))
    if not reference:
        raise BoundaryError('capability_nonempty_sample_required')
    if required_transaction is not None and not any(e['transactionHash']==required_transaction for e in reference):
        raise BoundaryError('capability_reference_sample_unavailable')
    witness=p._witness(reference,query,first,last)
    baseline_evidence=history.get_meta('pons_capability_baseline')
    baseline_evidence.update(authenticated=True,headers_digest=digest(witness['headers']),
                             receipts_digest=digest({str(k):v for k,v in witness['receipts'].items()}))
    history.set_meta('pons_capability_baseline',baseline_evidence)
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
    p._validated(enlarged,query,first,last)
    if enlarged!=sorted(enlarged,key=order):
        raise BoundaryError('capability_event_order_disagreement')
    history.set_meta('pons_capability_candidate',dict(event_count=len(enlarged),digest=digest(enlarged),
        identities=[event_id(e) for e in enlarged],order=[order(e) for e in enlarged]))
    if reference!=candidate:
        raise BoundaryError('capability_range_population_disagreement')
    if [e for rows in baseline for e in rows]!=enlarged:
        raise BoundaryError('capability_event_order_or_duplicate_disagreement')
    after=bounded([('eth_getBlockByNumber',[hex(first-1),False]),
                   ('eth_getBlockByNumber',[hex(first),False]),
                   ('eth_getBlockByNumber',[hex(last),False]),
                   ('eth_getBlockByNumber',['0x0',False])])
    if after[:3]!=before or after[3]!=source[1]:
        raise BoundaryError('capability_range_reorg')
    if clock()-started>=LIMITS['wall_seconds']:
        raise BoundaryError('capability_wall_exhausted')
    return dict(schema='pons-log-range-comparison-v1',chain_id=CHAIN_ID,
        genesis_hash=source[1]['hash'],provider_fingerprint=p.fingerprint,filter=query,
        first=first,last=last,range_blocks=40,equal=True,baseline_digest=digest(reference),
        candidate_digest=digest(candidate),canonical_end_hash=after[2]['hash'],
        canonical_beginning_hash=after[1]['hash'],canonical_boundaries=after[:3],
        event_identities=[event_id(e) for e in reference],event_order=[order(e) for e in reference],
        deployment=deployment,event_count=len(reference),
        limits=LIMITS,logical_comparison_elements=elements,logical_rpc_elements=elements,
        comparison_dispatch_groups=attempts,
        elapsed_seconds=clock()-started,provider_certified=False,
        limitation='one nonempty forty-block sample; no larger range or seven-day parity established')
