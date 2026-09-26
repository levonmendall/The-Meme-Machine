"""Fresh commit and durable runner for the two strategy-owned Survivor policies.

The integer PaperBook is reused from the certified Pump accounting primitive.
Each regime has its own native book and shares only sleeve reservation authority.
"""
from contextlib import nullcontext

from certification.execution_capacity import resize, breadth_retained
from certification.journal import digest
from certification.survivor_risk import mark


def handoff_ready(book, rows):
    """A controller written before native reservation is still pending work."""
    for row in rows:
        if row.get('position'):
            try:position=book._load(row['position'])
            except ValueError:return False
            if position['status']=='reserved':return False
    return True


def commit(*,book,sleeve,identity,candidate,generation,strategy,policy_hash,
           decision,regime,at,target,minimum,retention_bps,ordinary_limit,
           stress_limit,adapter,qualify):
    """Provider work is outside the commit lock; quotes are never reused on restart.

    Adapter functions use the native authenticated provider/plane and enforce
    completeness. A callable loss probe uses one pinned fresh state. Final quote
    validation is repeated under the generation fence immediately before fill.
    """
    try:
        existing=book._load(identity)
    except ValueError:
        existing=None
    if existing and existing['status'] in ('open','settled'):
        # Idempotent recovery of a native commit, not a second fill.
        book.replay()
        return dict(status='already_committed',position=existing)
    breadth=decision['features']['independent_buyers']
    if not decision['candidate'] or decision['policy_hash']!=policy_hash or breadth<=0:
        raise ValueError('survivor_qualified_decision_required')
    held=sleeve.get(identity)
    budget=held['amount'] if held is not None else min(target,sleeve.reconcile()['available'])
    if budget<minimum:raise ValueError('survivor_minimum_capital')
    sleeve.reserve(identity,strategy=strategy,amount=budget,at=at,candidate=candidate,
                   generation=generation,regime=regime)
    if existing is None:
        book.reserve(identity,budget,at,dict(decision=decision,generation=generation,regime=regime))
    try:
        state=adapter.fresh_state(candidate)
        quote_context=adapter.fresh_quotes(state,budget)
        facts=adapter.reconstruct(state,quote_context)
        fresh=qualify(facts)
        if not fresh['candidate']:
            raise ValueError('survivor_fill_qualification:'+','.join(fresh['all_rejections']))
        fill_breadth=fresh['features']['independent_buyers']
        if not breadth_retained(breadth,fill_breadth,retention_bps):
            raise ValueError('survivor_breadth_retention')
        cap=min(budget,adapter.turnover_cap(facts,fresh))
        capacity=resize(cap,minimum,quote_context.loss,
                        ordinary_limit=ordinary_limit,stress_limit=stress_limit)
        if capacity.final_size<=0:raise ValueError('survivor_execution_capacity')
        execution=quote_context.entry(capacity.final_size)
        now=adapter.now()
        telemetry=dict(decision=decision,fill=fresh,execution=execution,
                       capacity=dict(capacity.telemetry(),decision_size=target,capital_cap=budget,
                           turnover_cap=adapter.turnover_cap(facts,fresh),final_size=capacity.final_size,
                           binding_cap=capacity.binding_reason if capacity.final_size<cap else
                               'turnover' if cap<budget else 'capital'),generation=generation)
        # Both locks forbid supersession while the native fill transaction commits.
        with adapter.generation_fence(candidate,generation), sleeve.commit_fence(identity):
            adapter.validate_current(state,execution,now)
            book.transition(identity,'filled',now,amount=execution['cost'],
                            tokens=execution['quantity'],evidence=telemetry)
        return dict(status='filled',position=book._load(identity),telemetry=telemetry)
    except BaseException:
        # Only a provably unfilled native reservation may be released.
        book.replay();position=book._load(identity)
        if position['status']=='reserved':
            now=max(at,adapter.now())
            book.transition(identity,'cancelled',now,evidence=dict(reason='commit_failed'))
            position=book._load(identity)
            sleeve.release(identity,pnl=0,at=now,terminal_hash=digest(position),native_verified=True,cancelled=True)
        raise


def restore_risk(book,identity):
    """Rebuild runner state from the same immutable economic journal as fills."""
    book.replay()
    state=None
    import json
    for raw, in book.db.execute('SELECT body FROM journal ORDER BY seq'):
        row=json.loads(raw)
        if row['position']['id']!=identity:continue
        p=row['position'];action=row['action'];e=row['evidence']
        if action=='filled':
            state=dict(opened_at=row['at'],original_quantity=p['tokens'],remaining_quantity=p['tokens'],
                       original_basis=p['basis'],high_water_bps=0,high_at=row['at'],
                       realization_taken=False,tightened=False,deterioration_streak=0)
        elif action=='mark' and state is not None:
            state=dict(e['risk_state'])
        elif action=='partial_harvest' and state is not None:
            state.update(realization_taken=True,remaining_quantity=p['tokens'])
        elif action=='settled' and state is not None:
            state.update(settled=True,remaining_quantity=0)
    if state is None:raise ValueError('survivor_fill_missing')
    return state


def monitor(*,book,sleeve,identity,observation,policy,adapter):
    state=restore_risk(book,identity)
    if state.get('settled'):return dict(action='settled')
    position=book._load(identity)
    next_state,action=mark(state,observation,policy)
    if observation['id']!=state.get('last_observation'):
        # Return uses the remaining cost basis and full executable remaining exit.
        book.transition(identity,'mark',observation['at'],
                        amount=observation.get('net_exit_proceeds',position['mark']),
                        evidence=dict(risk_state=next_state,observation=observation))
    if action['action']=='hold':return action
    qty=position['tokens'] if action['action']=='full_exit' else action['quantity']
    if action['action']=='partial_exit' and state.get('realization_taken'):
        return dict(action='hold',reason='realization_already_committed')
    execution=adapter.exit_quote(qty)
    if execution is None:
        return dict(action='exit_pending',reason=action['reason'])
    now=adapter.now()
    adapter.validate_exit(execution,qty,now)
    native_action='settled' if action['action']=='full_exit' else 'partial_harvest'
    book.transition(identity,native_action,now,amount=execution['net_proceeds'],tokens=qty,
                    evidence=dict(exit_reason=action['reason'],execution=execution))
    book.replay()
    if native_action=='settled':
        final=book._load(identity)
        sleeve.release(identity,pnl=final['realized'],at=now,terminal_hash=digest(final),native_verified=True)
    return action
