"""Frozen bridge and one-add contracts for existing directional lifecycles."""
BRIDGE_SECONDS=129600
BRIDGE_GATES=('current_after_cost_return_positive','fresh_generation_state',
    'fresh_executable_exit_quote','canonical_lineage_and_venue',
    'creator_distribution_safe','hard_concentration_safe','executable_exit_liquidity',
    'no_persistent_confirmed_demand_failure','no_irreversible_exit_intent')


def reference_return(net,quantity,original_basis,original_quantity):
    """Original-entry unit price; neither a harvest nor an add rebases risk."""
    if min(quantity,original_basis,original_quantity)<=0:raise ValueError('directional_reference')
    return (int(net)*original_quantity*10000//(quantity*original_basis))-10000


def bridge_state(state,facts,*,now,ordinary_expired):
    updated=dict(state)
    if now<state['opened_at']:raise ValueError('bridge_time_regression')
    if state.get('bridged'):
        return updated,now-state['opened_at']>=BRIDGE_SECONDS
    if not ordinary_expired:return updated,False
    eligible=(state.get('realization_taken') is True and state.get('high_water_bps',0)>=5000
        and now-state['opened_at']<BRIDGE_SECONDS
        and all(facts.get(gate) is True for gate in BRIDGE_GATES))
    if eligible:
        updated.update(bridged=True,bridged_at=now,bridge_deadline=state['opened_at']+BRIDGE_SECONDS)
        return updated,False
    return updated,True


def scale_budget(state,facts,*,now,sleeve,execution_allowance):
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


def native_sync(book,sleeve,identity):
    if sleeve is None:return
    from .journal import digest
    p=book._load(identity);proof=book.replay()
    held=sleeve.get(identity)
    reservation=(held or {}).get('scale_reservation') or {}
    if reservation.get('status')=='reserved':
        sleeve.recover_scale(identity,request=reservation['request'],
            committed=p.get('scale_request')==reservation['request'],native_verified=proof['verified'])
    if p['status']=='open':
        sleeve.acknowledge_native(identity,basis=p['basis'],pnl=p['realized'],at=p['last_at'],
            native_hash=digest(p),native_verified=proof['verified'])
