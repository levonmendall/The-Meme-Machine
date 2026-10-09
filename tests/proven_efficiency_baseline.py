"""Frozen comparison functions from cbfcb4137f10474ffc7fe0e19f0b8772f25c1563; offline only."""

from meme_machine.runtime.execution_capacity import resize,breadth_retained

from meme_machine.runtime.survivor_commit import restore_risk

from meme_machine.runtime.directional_continuation import BRIDGE_GATES

def original_scale_budget(state,facts,*,now,sleeve,execution_allowance):
    if (state.get('scale_committed') or state.get('realization_taken') is not True
            or state.get('high_water_bps',0)<10000 or state.get('first_tail_crossed_at') is None
            or now-state['first_tail_crossed_at']<900 or state.get('pending_exit')
            or state.get('last_action',{}).get('action') in ('full_exit','partial_exit')
            or not all(facts.get(gate) is True for gate in BRIDGE_GATES)
            or facts.get('fresh_strategy_requalified') is not True
            or facts.get('fresh_execution_requalified') is not True):return 0
    current=facts.get('after_cost_return_bps')
    high=state['high_water_bps']
    if current is None or current<=0 or (high-current)*10000>(10000+high)*1500:return 0
    sizing=sleeve.sizing_basis(250)
    original=state['original_basis']
    ceiling=max(0,sizing['realized_equity'])*750//10000-original
    return max(0,min(sizing['target'],original//2,sizing['available'],int(execution_allowance),ceiling))

def original_scale(*,book,sleeve,identity,candidate,generation,adapter,qualify,ordinary_limit,stress_limit,minimum):
    """Fresh native requalification and one incremental economic event."""
    from meme_machine.runtime.directional_continuation import native_sync,BRIDGE_GATES
    scale_budget=original_scale_budget
    native_sync(book,sleeve,identity)
    from meme_machine.operational.position_continuation import position_only,addition_rejection
    if position_only():
        addition_rejection(book,identity,'funding_authorization_closed',adapter.now());return None
    risk=restore_risk(book,identity);p=book._load(identity);now=adapter.now()
    if (p['status']!='open' or risk.get('scale_committed') or not risk.get('realization_taken')
            or risk.get('first_tail_crossed_at') is None or now-risk['first_tail_crossed_at']<900
            or risk.get('last_action',{}).get('action')!='hold'):return None
    target=min(sleeve.sizing_basis(250)['allocatable_target'],risk['original_basis']//2)
    if target<minimum:return None
    state=adapter.fresh_state(candidate);quotes=adapter.fresh_quotes(state,target)
    facts=adapter.reconstruct(state,quotes);decision=qualify(facts)
    if decision.get('candidate') is not True:return None
    if not breadth_retained(adapter.current['decision']['features']['independent_buyers'],
            decision['features']['independent_buyers'],5000):return None
    allowance=min(target,adapter.turnover_cap(facts,decision))
    capacity=resize(allowance,minimum,quotes.loss,ordinary_limit=ordinary_limit,stress_limit=stress_limit)
    risk_facts={gate:True for gate in BRIDGE_GATES}
    risk_facts.update(fresh_strategy_requalified=True,fresh_execution_requalified=capacity.final_size>0,
        after_cost_return_bps=risk['high_water_bps'])
    # Current executable price, never the peak, supplies drawdown authority.
    exit_quote=adapter.exit_quote(p['tokens'])
    if exit_quote is None:return None
    from meme_machine.runtime.directional_continuation import reference_return
    risk_facts['after_cost_return_bps']=reference_return(exit_quote['net_proceeds'],p['tokens'],risk['original_basis'],risk['original_quantity'])
    size=scale_budget(risk,risk_facts,now=adapter.now(),sleeve=sleeve,execution_allowance=capacity.final_size)
    if size<minimum:return None
    execution=quotes.entry(size);cost=execution['cost'];request=identity+':scale:1'
    if cost>size:raise ValueError('scale_execution_overdraw')
    sleeve.reserve_scale(identity,amount=cost,original_basis=risk['original_basis'],at=now,request=request,
        scale_state=risk,scale_facts=risk_facts)
    try:
        with adapter.generation_fence(candidate,generation),sleeve.scale_fence(identity,request):
            adapter.validate_current(state,execution,adapter.now())
            book.transition(identity,'scale_add',adapter.now(),amount=cost,tokens=execution['quantity'],
                evidence=dict(request=request,execution=execution,decision=decision,capacity=capacity.telemetry(),generation=generation))
    except BaseException:
        proof=book.replay();native=book._load(identity)
        sleeve.recover_scale(identity,request=request,committed=native.get('scale_request')==request,native_verified=proof['verified'])
        raise
    native_sync(book,sleeve,identity)
    return book._load(identity)


from meme_machine.runtime.survivor_commit import risk_record

def original_restore_risk(book,identity):
    """Rebuild runner state from the same immutable economic journal as fills."""
    book.replay()
    prefix=book._archive()
    state=prefix['risk_states'].get(identity) if prefix else None
    import json
    for raw, in book.db.execute('SELECT body FROM journal ORDER BY seq'):
        row=json.loads(raw)
        if row['position']['id']!=identity:continue
        state=risk_record(state,row)
    if state is None:raise ValueError('survivor_fill_missing')
    return state


from collections import Counter

def original_provider_usage_record(db, row, *, wire=True):
    """Update the shared materialized counters in the transport audit transaction."""
    counts=Counter()
    n=row.get('physical_requests',0) if wire else 0
    if not wire:counts['completed_transport_attempts']=row.get('physical_requests',0)
    purpose=row.get('category','unclassified')
    if not wire:
        counts['response_bytes']=row.get('response_bytes',0)
        counts['category:'+purpose+':response_bytes']=row.get('response_bytes',0)
    counts['physical_http_requests']=n
    if n:
        counts['request_bytes']=row.get('request_bytes',0)
        counts['category:'+purpose+':request_bytes']=row.get('request_bytes',0)
        counts['category:'+purpose+':physical_http_requests']=n
        counts['category:'+purpose+':logical_rpc_calls']=len(row['methods'])
        counts.update({'category:'+purpose+':method:'+m:v for m,v in Counter(row['methods']).items()})
        counts['logical_rpc_calls']=len(row['methods'])
        counts.update({'method:'+m:v for m,v in Counter(row['methods']).items()})
        counts['retries']=int(row.get('retry_attempt',0)>0)
        if row.get('batch'):
            counts['batch_transports']=n;counts['batch_members']=len(row['methods'])
        for label,words in [('repair',('repair','gap')),('execution_current_state',('paper','exit','unwind','confirm','current','execution'))]:
            if any(w in row.get('scope','') for w in words):
                counts[label+'_transports']=n;counts[label+'_logical_calls']=len(row['methods'])
    counts['responses_429']=int(row.get('http_status')==429 or row.get('rpc_error_code')==429)
    counts['provider_queue_wait_seconds']=row.get('wait_seconds',0)
    counts['transport_latency_seconds']=row.get('latency_seconds',0)
    counts['category:'+purpose+':scheduling_wait_seconds']=row.get('wait_seconds',0)
    counts['category:'+purpose+':latency_seconds']=row.get('latency_seconds',0)
    if row.get('boundary'):counts['failure:'+row['boundary']]=1
    db.executemany('INSERT INTO provider_usage VALUES(?,?,?,?) ON CONFLICT(endpoint,lane,metric) DO UPDATE SET value=value+excluded.value',
        [(row['endpoint_fingerprint'],row['lane'],key,value) for key,value in counts.items()])
