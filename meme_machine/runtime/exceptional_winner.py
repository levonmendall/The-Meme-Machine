"""Inactive proposed renewal rules. No provider, admission or execution owner.

Native callers supply fresh authenticated evidence and the existing usage
ledger's finite operating window. No live caller supplies this context by
default. A renewal changes only a holding checkpoint, never entry or exposure.
"""
from copy import deepcopy
from decimal import Decimal, InvalidOperation

VERSION='exceptional-winner-candidate-v1'
RENEWAL_SECONDS=3600
CHECKPOINTS={'pump_current':129600,'pons_current':129600,
             'pump_survivor':259200,'pons_survivor':259200}
HEALTH=('native_managers','native_recovery','exit_paths','authenticated_evidence',
        'reconciliation','provider_governors')
SAFETY=('fresh_generation_state','fresh_executable_exit_quote','canonical_lineage_and_venue',
        'creator_distribution_safe','hard_concentration_safe','executable_exit_liquidity',
        'no_persistent_confirmed_demand_failure','no_irreversible_exit_intent',
        'authenticated','history_complete','authenticated_economic_valuation')
COUNTERS=('rpc_cu','rpc_elements','http_attempts','http_bytes','native_bytes')


def _resources(resources,previous,*,now,next_boundary):
    if not isinstance(resources,dict):return 'finite_resources_missing',None
    try:
        numbers=('observed_at','queue_depth','queue_wait_seconds','rss_bytes','cpu_cores',
                 'safety_latency_seconds','cadence_seconds','maintenance_until','recovery_until','service_until')
        if any(not Decimal(str(resources[k])).is_finite() or Decimal(str(resources[k]))<0 for k in numbers):
            return 'finite_resource_shape',None
        if not 0<=now-resources['observed_at']<=5:return 'resource_evidence_stale',None
        if resources['capacity_verified'] is not True:return 'protective_capacity_unverified',None
        if not isinstance(resources['readiness'],dict) or not all(resources['readiness'].get(k) is True for k in HEALTH):
            return 'native_safety_readiness_missing',None
        if type(resources['position_owner_count']) is not int or resources['position_owner_count']!=1:
            return 'native_owner_not_unique',None
        if resources['cadence_seconds']!=(3 if resources['family']=='pons_survivor' else 5):
            return 'original_safety_cadence_required',None
        if (resources['queue_depth']>64 or resources['queue_wait_seconds']>5
                or resources['rss_bytes']>=6*1024**3 or Decimal(str(resources['cpu_cores']))>Decimal('1.8')
                or resources['safety_latency_seconds']>resources['cadence_seconds']):
            return 'protective_resource_or_latency_pressure',None
        if resources['recovery_available'] is not True:return 'bounded_exit_recovery_unavailable',None
        if any(type(resources[k]) is not int for k in ('maintenance_until','recovery_until','service_until')):
            return 'finite_resource_shape',None
        if next_boundary>resources['maintenance_until']:return 'finite_operating_window_exhausted',None
        if (resources['recovery_until']<resources['maintenance_until']+3600
                or resources['service_until']<resources['recovery_until']+65):
            return 'exit_recovery_and_shutdown_reserve_missing',None
        used=resources['used'];limits=resources['limits'];need=resources['next_window_demand']
        if resources['next_window_demand_verified'] is not True:return 'next_window_demand_unverified',None
        for k in COUNTERS:
            if any(type(row[k]) is not int or row[k]<0 for row in (used,limits,need)):
                return 'finite_resource_shape',None
            if limits[k]<=0 or used[k]+need[k]>limits[k]:return 'remaining_'+k+'_insufficient',None
        if min(need[k] for k in ('rpc_cu','rpc_elements','http_attempts','http_bytes'))<=0:
            return 'protective_work_cannot_be_free',None
        usd={k:Decimal(str(resources[k])) for k in ('spend_used','spend_limit','next_window_spend')}
        if (not all(v.is_finite() and v>=0 for v in usd.values()) or usd['spend_limit']<=0
                or usd['spend_used']+usd['next_window_spend']>usd['spend_limit']):
            return 'remaining_modeled_spend_insufficient',None
        identity=dict(run_id=resources['run_id'],started_at=resources['started_at'],
            maintenance_until=resources['maintenance_until'],recovery_until=resources['recovery_until'],
            service_until=resources['service_until'],limits=limits,spend_limit=str(usd['spend_limit']))
        if not identity['run_id'] or type(identity['started_at']) is not int:return 'original_run_identity_missing',None
        if previous:
            if previous['resource_identity']!=identity:return 'original_operating_envelope_changed',None
            if any(used[k]<previous['used'][k] for k in COUNTERS):return 'cumulative_usage_regressed',None
            if usd['spend_used']<Decimal(previous['spend_used']):return 'cumulative_spend_regressed',None
        return None,dict(resource_identity=deepcopy(identity),used=dict(used),spend_used=str(usd['spend_used']))
    except (KeyError,TypeError,ValueError,InvalidOperation):return 'finite_resources_incomplete',None


def checkpoint(state,facts,*,family,now,current_return,context):
    """Fresh check on every extended safety turn; renewal grid stays entry-bound.

Returns native state plus expired/reason. Qualification never executes an exit,
opens a position, buys evidence, creates funding or replenishes a budget.
"""
    updated=dict(state);previous=state.get('exceptional')
    first=state['opened_at']+CHECKPOINTS[family]
    if now<state['opened_at']:raise ValueError('exceptional_time_regression')
    if now<first:return updated,False,None
    if context is None and not previous:return updated,True,None
    due=previous['until'] if previous else first
    reason=None;balances=None
    try:
        if (previous and (previous.get('version')!=VERSION or previous.get('family')!=family
                or previous.get('opened_at')!=state['opened_at'])):reason='native_extension_identity_disagreement'
        elif previous and previous.get('status')=='EXIT_REQUIRED':reason=previous['reason']
        elif (not isinstance(context,dict) or context.get('version')!=VERSION
                or context.get('family')!=family):reason='candidate_context_missing'
        elif family.endswith('current') and state.get('bridged') is not True:reason='original_current_bridge_required'
        elif state.get('realization_taken') is not True or state.get('realized_profit',0)<=0:reason='initial_realized_profit_required'
        elif type(current_return) is not int or current_return<10000:reason='current_after_cost_two_times_required'
        elif not isinstance(facts,dict) or not all(facts.get(k) is True for k in SAFETY):reason='authenticated_complete_native_safety_evidence_required'
        elif not 0<=now-facts['observed_at']<=5:reason='exceptional_evidence_stale'
        elif type(facts['quantity']) is not int or facts['quantity']!=state['remaining_quantity']:reason='native_remaining_quantity_disagreement'
        elif (type(facts['entry_buyers']) is not int or facts['entry_buyers']<=0
                or type(facts['minimum_buyers']) is not int or facts['minimum_buyers']<=0
                or type(facts['independent_buyers']) is not int
                or facts['independent_buyers']<facts['minimum_buyers']
                or facts['independent_buyers']*10000<facts['entry_buyers']*5000):reason='independent_demand_breadth_not_retained'
        elif (any(type(facts[k]) is not int or facts[k]<0 for k in ('buy_flow','sell_flow','new_buyers'))
                or facts['buy_flow']<=facts['sell_flow'] or facts['new_buyers']<=0):reason='fresh_organic_demand_not_sustained'
        elif now>=due and now-due>(3 if family=='pons_survivor' else 5):reason='fresh_renewal_checkpoint_missed'
        else:
            next_boundary=due+RENEWAL_SECONDS if now>=due else due
            resources=context.get('resources')
            if not isinstance(resources,dict) or resources.get('family')!=family:
                reason='original_resource_family_required'
            else:
                reason,balances=_resources(resources,previous,now=now,next_boundary=next_boundary)
                if reason is None:
                    profit=Decimal(str(facts['native_net_profit_usd']))
                    costs=Decimal(str(resources['spend_used']))+Decimal(str(resources['next_window_spend']))
                    # Existing authenticated native valuation includes realized
                    # P&L and the executable remaining exit, after execution costs.
                    # Conservatively charge the entire existing continuation
                    # ledger; no new attribution ledger or anticipated gains.
                    if not profit.is_finite() or profit<=costs:
                        reason='positive_profit_after_continuation_costs_required'
    except (KeyError,TypeError,ValueError,InvalidOperation):reason='exceptional_native_evidence_incomplete'
    if reason:
        updated['exceptional']=dict(previous or {},version=VERSION,family=family,
            opened_at=state['opened_at'],until=due,status='EXIT_REQUIRED',reason=reason,
            protected=False,exit_required_at=(previous or {}).get('exit_required_at',now))
        return updated,True,'exceptional_'+reason
    renew=now>=due
    updated['exceptional']=dict(previous or {},**balances,version=VERSION,family=family,
        opened_at=state['opened_at'],until=due+RENEWAL_SECONDS if renew else due,
        renewals=(previous or {}).get('renewals',0)+int(renew),status='ACTIVE',reason=None,
        last_evidence_at=facts['observed_at'])
    return updated,False,None


def survivor_mark(state,observation,policy,*,family,context):
    from .survivor_risk import mark
    if observation['at']-state['opened_at']<CHECKPOINTS[family]:return mark(state,observation,policy)
    if context is None and not state.get('exceptional'):return mark(state,observation,policy)
    # Only the original fixed hold is deferred for this evaluation. All other
    # native exits, partials, timers and irreversible pending intents still run.
    shadow=dict(policy,maximum_hold_seconds=max(policy['maximum_hold_seconds'],
        observation['at']-state['opened_at']+1))
    native,action=mark(state,observation,shadow)
    if action['action']=='full_exit':
        if native.get('exceptional'):
            native['exceptional']=dict(native['exceptional'],status='EXIT_REQUIRED',reason=action['reason'],
                protected=False,exit_required_at=native['exceptional'].get('exit_required_at',observation['at']))
        return native,action
    evidence=(context or {}).get('evidence',{})
    native,expired,reason=checkpoint(native,evidence,family=family,now=observation['at'],
        current_return=observation.get('after_cost_return_bps'),context=context)
    if expired:
        action=dict(action='full_exit',reason=reason or 'maximum_hold')
        native['last_action']=action
    return native,action


def current_bridge(state,facts,*,now,ordinary_expired,context):
    from .directional_continuation import bridge_state
    native,expired=bridge_state(state,facts,now=now,ordinary_expired=ordinary_expired)
    if now-state['opened_at']<129600:return native,expired,None
    if context is None and not state.get('exceptional'):return native,expired,None
    family=(context or {}).get('family') or (state.get('exceptional') or {}).get('family')
    if family not in ('pump_current','pons_current'):return native,True,'exceptional_current_family_missing'
    return checkpoint(native,(context or {}).get('evidence',{}),family=family,now=now,
        current_return=facts.get('after_cost_return_bps'),context=context)
