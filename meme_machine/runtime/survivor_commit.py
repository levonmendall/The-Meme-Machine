"""Fresh commit and durable runner for the two strategy-owned Survivor policies.

The integer PaperBook is reused from the certified Pump accounting primitive.
Each regime has its own native book and shares only sleeve reservation authority.
"""
from meme_machine.runtime.provider_purchases import attributed_work
from contextlib import nullcontext

from meme_machine.runtime.execution_capacity import resize, breadth_retained
from meme_machine.runtime.journal import digest
from meme_machine.runtime.survivor_risk import mark


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
    available=target if hasattr(sleeve,'authority') else sleeve.reconcile()['available']
    budget=held['amount'] if held is not None else min(target,available)
    if budget<minimum:raise ValueError('survivor_minimum_capital')
    sleeve.reserve(identity,strategy=strategy,amount=budget,at=at,candidate=candidate,
                   generation=generation,regime=regime)
    if existing is None:
        book.reserve(identity,budget,at,dict(candidate=candidate,decision=decision,generation=generation,regime=regime))
    try:
        # A slow first incremental reconstruction can exhaust the native five-
        # second freshness budget. One bounded complete refresh uses the now-
        # caught-up history; it never reuses a stale quote or loosens freshness.
        for attempt in range(2):
            state=adapter.fresh_state(candidate)
            quote_context=adapter.fresh_quotes(state,budget)
            facts=adapter.reconstruct(state,quote_context)
            expired=getattr(adapter,'commit_context_expired',lambda state:False)(state)
            if not expired:break
            if attempt==1:raise ValueError('survivor_stale_commit')
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
        from .directional_continuation import native_sync
        native_sync(book,sleeve,identity)
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
    """Reuse only the risk fold of an unchanged, freshly verified native journal.

    Monetary replay is deliberately retained: shared grant/recovery dependencies
    can change outside this connection. This cache never supplies that proof.
    A read transaction makes verification and the risk view one SQLite snapshot.
    """
    from copy import deepcopy
    from meme_machine.runtime.source_artifacts import REGISTRY
    with book.lock:
        own_snapshot=not book.db.in_transaction
        if own_snapshot:book.db.execute('BEGIN')
        try:
            proof=book.replay()
            marker=(tuple(sorted(book.identity.items())),id(book.db),book.db.total_changes,
                book.db.execute('PRAGMA data_version').fetchone()[0],
                book.db.execute('PRAGMA schema_version').fetchone()[0],
                book.db.execute('SELECT hash FROM journal_archive WHERE id=1').fetchone(),
                proof['events'],proof['final_hash'],proof['cash'],REGISTRY.generation,
                risk_record,getattr(book,'recovery_generation',None),id(getattr(book,'portfolio',None)))
            cached=getattr(book,'_risk_replay_cache',None)
            if cached and cached[:2]==(marker,identity):return deepcopy(cached[2])
            state=_fold_risk(book,identity)
            book._risk_replay_cache=(marker,identity,deepcopy(state))
            return state
        except BaseException:
            book._risk_replay_cache=None
            raise
        finally:
            if own_snapshot:book.db.execute('ROLLBACK')


def _fold_risk(book,identity):
    prefix=book._archive()
    state=prefix['risk_states'].get(identity) if prefix else None
    import json
    for raw, in book.db.execute('SELECT body FROM journal ORDER BY seq'):
        row=json.loads(raw)
        if row['position']['id']!=identity:continue
        state=risk_record(state,row)
    if state is None:raise ValueError('survivor_fill_missing')
    return state


def restore_risks(book,identities):
    """One verified native snapshot for bounded, noncommitting preparation.

    The final monitor still performs its original reconciliation and replay.
    No monetary proof or prepared risk view is retained across mutations.
    """
    from copy import deepcopy
    import json
    wanted=set(identities)
    with book.lock:
        own_snapshot=not book.db.in_transaction
        if own_snapshot:book.db.execute('BEGIN')
        try:
            book.replay()
            prefix=book._archive()
            states={key:deepcopy(prefix['risk_states'].get(key)) if prefix else None for key in wanted}
            for raw, in book.db.execute('SELECT body FROM journal ORDER BY seq'):
                row=json.loads(raw);key=row['position']['id']
                if key in states:states[key]=risk_record(states[key],row)
            if any(value is None for value in states.values()):raise ValueError('survivor_fill_missing')
            return states
        finally:
            if own_snapshot:book.db.execute('ROLLBACK')


def risk_record(state,row):
    """One unchanged native replay step, also used to seal a durable prefix."""
    p=row['position'];action=row['action'];e=row['evidence']
    if action=='filled':
        state=dict(opened_at=row['at'],original_quantity=p['tokens'],remaining_quantity=p['tokens'],
                   original_basis=p['basis'],high_water_bps=0,high_at=row['at'],
                   realization_taken=False,tightened=False,deterioration_streak=0)
    elif action=='mark' and state is not None:state=dict(e['risk_state'])
    elif action=='partial_harvest' and state is not None:
        state.update(realization_taken=True,remaining_quantity=p['tokens'])
    elif action=='scale_add' and state is not None:
        state.update(scale_committed=True,scale_request=e['request'],remaining_quantity=p['tokens'])
    elif action=='settled' and state is not None:state.update(settled=True,remaining_quantity=0)
    return state


def monitor(*,book,sleeve,identity,observation,policy,adapter,exceptional_context=None):
    from .directional_continuation import native_sync,reference_return
    native_sync(book,sleeve,identity)
    state=restore_risk(book,identity)
    if state.get('settled'):return dict(action='settled')
    position=book._load(identity)
    if state.get('scale_committed') and observation.get('after_cost_return_bps') is not None:
        observation=dict(observation,after_cost_return_bps=reference_return(
            observation['net_exit_proceeds'],position['tokens'],state['original_basis'],state['original_quantity']))
    if exceptional_context is not None or state.get('exceptional'):
        from .exceptional_winner import survivor_mark
        lane=book.identity['lane']
        family={'pumpswap-survivor-momentum-v1':'pump_survivor',
                'pons-postgrad-survivor-momentum-v1':'pons_survivor'}[lane]
        state=dict(state,realized_profit=position['realized'])
        next_state,action=survivor_mark(state,observation,policy,family=family,context=exceptional_context)
    else:next_state,action=mark(state,observation,policy)
    if next_state!=state:
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
    if native_action=='partial_harvest':native_sync(book,sleeve,identity)
    if native_action=='settled':
        final=book._load(identity)
        sleeve.release(identity,pnl=final['realized'],at=now,terminal_hash=digest(final),native_verified=True)
    return action


def exceptional_evidence_failure(runtime,*,family,blocker,rows=None):
    """Provider failure before monitoring: durable intent, zero acquisition.

    Use the same Book/risk journal and existing worker. A prior quote remains
    explicitly unavailable; no execution or successful settlement is inferred.
    Normal policies have no exceptional state and this is a no-op for them.
    """
    from .exceptional_winner import CHECKPOINTS,VERSION
    enabled=getattr(runtime,'exceptional_context',None) is not None
    now=runtime.now()
    for row in runtime.history.rows() if rows is None else rows:
        identity=row.get('position')
        if not identity:continue
        try:position=runtime.book._load(identity)
        except ValueError:
            if not enabled:continue
            raise
        if position['status']!='open':continue
        state=restore_risk(runtime.book,identity);previous=state.get('exceptional')
        if not enabled and not previous:continue
        if now-state['opened_at']<CHECKPOINTS[family]:continue
        action=state.get('last_action',{})
        if action.get('action')!='full_exit':
            action=dict(action='full_exit',reason='exceptional_authenticated_evidence_unavailable')
        if not previous or previous.get('status')!='EXIT_REQUIRED':
            state=dict(state,last_action=action,last_at=now,last_observation='unavailable:'+str(now),
                exceptional=dict(previous or {},version=VERSION,family=family,opened_at=state['opened_at'],
                    until=(previous or {}).get('until',state['opened_at']+CHECKPOINTS[family]),
                    status='EXIT_REQUIRED',reason=action['reason'],protected=False,exit_required_at=now,blocker=blocker))
            runtime.book.transition(identity,'mark',now,amount=position['mark'],
                evidence=dict(risk_state=state,observation=dict(at=now,after_cost_return_bps=None,blocker=blocker)))
        row['position_safety']=dict(at=now,evidence_current=False,exit_quote_available=False,
            pending_exit=True,protected=False,blocker=blocker)
        runtime.history.save(row)


@attributed_work('scaling_requalification')
def scale(*,book,sleeve,identity,candidate,generation,adapter,qualify,ordinary_limit,stress_limit,minimum):
    """Fresh native requalification and one incremental economic event."""
    from .directional_continuation import scale_budget,native_sync,BRIDGE_GATES
    from .scaling_necessary_conditions import scale_necessary_budget
    native_sync(book,sleeve,identity)
    from meme_machine.operational.position_continuation import position_only,addition_rejection
    if position_only():
        addition_rejection(book,identity,'funding_authorization_closed',adapter.now());return None
    risk=restore_risk(book,identity);p=book._load(identity);now=adapter.now()
    if (p['status']!='open' or risk.get('scale_committed') or not risk.get('realization_taken')
            or risk.get('first_tail_crossed_at') is None or now-risk['first_tail_crossed_at']<900
            or risk.get('last_action',{}).get('action')!='hold'):return None
    sizing=sleeve.sizing_basis(250)
    target=min(sizing['allocatable_target'],risk['original_basis']//2)
    if target<minimum:return None
    if scale_necessary_budget(risk,now=now,sizing=sizing)<minimum:return None
    state=adapter.fresh_state(candidate)
    # Only an adapter's exact local calculation on this fresh native snapshot
    # may reject on price. No old mark, quote, fee or observation is consulted.
    local_return=getattr(adapter,'necessary_scale_return',lambda *args:None)(state,p,risk)
    if local_return is not None and scale_necessary_budget(risk,now=adapter.now(),
            sizing=sleeve.sizing_basis(250),after_cost_return_bps=local_return)<minimum:return None
    quotes=adapter.fresh_quotes(state,target)
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
    from .directional_continuation import reference_return
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
