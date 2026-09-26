"""Shared staged realization mechanics; risk constants remain strategy-owned."""


def mark(state, observation, policy):
    """Pure transition. The native ledger must atomically persist returned state.

    A repeated observation cannot supply the second deterioration confirmation.
    Unavailable liquidity creates an exit intent, never fabricated proceeds.
    """
    repeated=observation['id'] == state.get('last_observation')
    if repeated and observation['at']==state.get('last_at'):
        return dict(state), dict(state['last_action'])
    now = observation['at']
    if now < state.get('last_at',state['opened_at']):
        raise ValueError('survivor_mark_time_regression')
    updated = dict(state)
    current = observation.get('after_cost_return_bps')
    high = updated.get('high_water_bps',0)
    if current is not None:
        if type(current) is not int:
            raise ValueError('survivor_return_integer')
        if current > high:
            updated['high_at'] = now
        high = max(high,current)
    updated['high_water_bps'] = high
    updated['tightened'] = updated.get('tightened',False) or high >= policy['tight_arm_bps']
    soft = None if repeated else observation.get('soft_deterioration')
    if soft is not None:
        updated['deterioration_streak'] = updated.get('deterioration_streak',0)+1 if soft is True else 0
    else:updated.setdefault('deterioration_streak',0)
    reason = None
    if observation.get('creator_distribution') is True:
        reason = 'creator_distribution'
    elif observation.get('severe_persistent_deterioration') is True:
        reason = 'severe_persistent_deterioration'
    elif observation.get('exit_liquidity_valid') is False:
        reason = 'invalid_exit_liquidity'
    elif now-state['opened_at'] >= policy['maximum_hold_seconds']:
        reason = 'maximum_hold'
    elif current is not None and current <= policy['hard_stop_bps']:
        reason = 'hard_stop'
    elif current is not None and high >= policy['first_profit_bps']:
        trail = policy['tight_trail_bps'] if updated['tightened'] else policy['trail_bps']
        if (high-current)*10000 >= (10000+high)*trail:
            reason = 'runner_trail'
    if reason is None and updated['deterioration_streak'] >= policy['soft_confirmations']:
        reason = 'persistent_demand_deterioration'
    if (reason is None and policy.get('stale_seconds') is not None and current is not None
            and now-state['opened_at'] >= policy['stale_seconds']
            and now-updated.get('high_at',state['opened_at']) >= policy['stale_seconds']
            and current < policy['stale_return_ceiling_bps']):
        reason = 'stale_thesis'
    # A full-exit intent is irreversible even if the next quote is unavailable.
    # Recovery cannot turn a stopped position back into a fresh hold.
    pending=state.get('last_action',{})
    if pending.get('action')=='full_exit':
        action=dict(pending)
    elif reason is not None:
        action = dict(action='full_exit',reason=reason)
    elif pending.get('action')=='partial_exit' and not state.get('realization_taken'):
        action=dict(pending)
    elif (current is not None and current >= policy['first_profit_bps']
          and not state.get('realization_taken')):
        quantity = state['original_quantity']*policy['first_sell_bps']//10000
        action = (dict(action='partial_exit',quantity=quantity,reason='first_realization')
                  if 0 < quantity < state['remaining_quantity'] else dict(action='hold',reason='partial_dust'))
    else:
        action = dict(action='hold',reason=None)
    updated.update(last_observation=observation['id'],last_at=now,last_action=action)
    return updated, action


def new_regime(previous, current, *, minimum_seconds=3600, minimum_changes=2):
    if current['at']-previous['at'] < minimum_seconds:
        return False
    dimensions = ('high_reset_cycle','base_id','buyer_population','independent_demand','flow_regime')
    return sum(previous.get(k) is not None and current.get(k) is not None
               and previous[k] != current[k] for k in dimensions) >= minimum_changes
