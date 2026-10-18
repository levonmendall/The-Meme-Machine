"""Derived Current re-entry references, joined to verified native lifecycles.

This is a checkpoint projection, never a capital or accounting authority. Native
reads happen at recovery/receipt boundaries; nomination only reads this map.
"""
from contextlib import closing, contextmanager
import json
import os
from pathlib import Path
import sqlite3
import threading

from . import BoundaryError
from .evidence import Store, canonical, digest
from .pons_selective_continuation import POLICY_HASH, REENTRY_POLICY, reentry_regime_reset
from .pons_selective_ledger import SelectivePaper, STRATEGY_NAMESPACE, DECISION_CATEGORY


def native_history(paper, identity, *, events=None, prefix=None):
    """Compact action facts from the already-verified journal and retained prefix."""
    from meme_machine.runtime.storage import pons_prefix
    if prefix is None:prefix=pons_prefix(paper).get(identity) or {}
    prior=prefix.get('lifecycle_evidence')
    previous=prefix.get('event')
    facts=json.loads(canonical(prior)) if prior else dict(
        identity=identity,complete=not bool(prefix),actions={},entry=None)
    if facts.get('identity')!=identity:
        raise BoundaryError('selective_reentry_prefix_identity')
    if prior and 'entry' not in facts:
        facts['entry']=prefix.get('entry')
        if facts.get('entry_hash')!=(digest(facts['entry']) if facts['entry'] else None):
            raise BoundaryError('selective_reentry_prefix_entry_identity')
    for event in paper.events(identity) if events is None else events:
        if previous and event['position']['version']<=previous['position']['version']:continue
        version=event['position']['version']
        facts['complete']=facts['complete'] and 'quote' in event and 'recorded_at_ns' in event
        if previous is None: facts['complete']=facts['complete'] and version==0 and event['action']=='reserve'
        actions=facts['actions'];actions[event['action']]=actions.get(event['action'],0)+1
        if event['action']=='entry':
            if facts['entry'] is not None:raise BoundaryError('selective_reentry_multiple_entries')
            facts['entry']=event
        previous=event
    # Old native prefixes explicitly retain entry execution even if they did
    # not retain negative evidence sufficient to prove a cancellation.
    if facts['entry'] is None: facts['entry']=prefix.get('entry')
    facts['through_version']=previous['position']['version'] if previous else None
    return facts


def _readonly(path):
    return sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True,isolation_level=None)


@contextmanager
def _readonly_snapshot(path, read_context=None):
    if read_context is not None:
        from meme_machine.runtime.native_restore_context import require_read_context
        with require_read_context(read_context).database(path) as db:
            yield db
    else:
        with closing(_readonly(path)) as db:
            db.execute('BEGIN')
            yield db


def _shared_reader(read_context=None):
    if read_context is not None:
        from meme_machine.runtime.native_restore_context import require_read_context
        return require_read_context(read_context)
    from meme_machine.shared_capital.runtime import selected,RuntimeCapital
    from types import SimpleNamespace
    database=os.environ.get('MM_PORTFOLIO_ACCOUNTING_DB')
    path=selected(database) if database else None
    if not path:return None
    with closing(_readonly(path)) as ledger:
        ledger.execute('BEGIN')
        reader=object.__new__(RuntimeCapital);reader.db=ledger
        state=reader._read()
    return SimpleNamespace(ledger=lambda:state)


def _sleeve_ack(position, capital, *, read_context=None):
    if read_context is not None:
        from meme_machine.runtime.native_restore_context import require_read_context
        read_context=require_read_context(read_context)
    path=(read_context.sleeve_path('pons') if read_context is not None
        else os.environ.get('MM_DIRECTIONAL_SLEEVE_DB'))
    if not path:
        return os.environ.get('MM_DIRECTIONAL_COMPOSITE_REQUIRED')!='1'
    from meme_machine.runtime.directional_sleeve import policies
    from meme_machine.runtime.sleeve_reservations import SleeveReservations
    from meme_machine.shared_capital.native_sleeve import SharedSleeve
    authority=_shared_reader(read_context)
    with _readonly_snapshot(path,read_context) as db:
        sleeve=object.__new__(SharedSleeve if authority else SleeveReservations)
        sleeve.db=db;sleeve.lock=threading.RLock()
        sleeve.identity=json.loads(db.execute('SELECT body FROM sleeve_genesis WHERE id=1').fetchone()[0])
        expected=dict(lane='pons',capital=capital,policies=policies('pons'),
            cohort=(read_context.cohort_id if read_context is not None else
                os.environ.get('MM_DIRECTIONAL_COHORT_ID')),paper_only=True)
        from meme_machine.runtime.policy_compatibility import known_hash,regime_for
        if (dict(sleeve.identity,policies=expected['policies'])!=expected
                or set(sleeve.identity['policies'])!=set(expected['policies'])
                or not all(known_hash(regime_for(k),v) for k,v in sleeve.identity['policies'].items())):
            raise BoundaryError('selective_reentry_sleeve_genesis')
        if authority:sleeve.authority=authority
        sleeve.reconcile();held=sleeve.get(position['id'])
        return bool(held and held['status']=='settled' and held['held']==0
            and held.get('terminal_hash')==digest(position) and held['pnl']==position['pnl']
            and (held.get('scale_reservation') or {}).get('status')!='reserved')


def _portfolio_ack(position, event_hash, *, lane='pons', cancelled=None, read_context=None):
    """Existing exact release receipts, shared by native directional adapters."""
    if read_context is not None:
        from meme_machine.runtime.native_restore_context import require_read_context
        read_context=require_read_context(read_context)
    path=(read_context.portfolio_path if read_context is not None
        else os.environ.get('MM_PORTFOLIO_ACCOUNTING_DB'))
    if not path:return True
    from meme_machine.shared_capital.runtime import selected, RuntimeCapital
    if read_context is not None:
        from meme_machine.runtime.native_restore_context import require_read_context
        require_read_context(read_context).ledger()
        shared=read_context.shared_path
    else:shared=selected(path)
    if shared:
        with _readonly_snapshot(shared,read_context) as db:
            reader=object.__new__(RuntimeCapital);reader.db=db
            state=reader._read();key=lane+':'+position['id']
            if not state or key in state.get('runtime_pending',{}):return False
            life=state.get('native_aliases',{}).get(key)
            request_id=state.get('runtime_native_requests',{}).get(key)
            request_ids={request_id,state.get('runtime_native_requests',{}).get(key+':scale')}-{None}
            request=state.get('requests',{}).get(request_id) or {}
            regime=(request.get('value') or {}).get('regime',lane+'_current')
            cursor=state.get('native_cursors',{}).get(regime+':'+str(life))
            native=dict(epoch_id=state['epoch_id'],regime=regime,lifecycle_id=life,
                event_id='native:'+event_hash,sequence=cursor,journal_sha256=event_hash)
            delivered=state.get('native_deliveries',{}).get(regime+':'+str(life)+':native:'+event_hash)
            held=(state.get('positions',{}).get(life) or {})
            return bool(cursor and delivered==digest(native)
                and not any(identity in request_ids or r.get('request_id') in request_ids or r.get('lifecycle_id')==life
                    for category in ('reservations','commitments','runtime_inbox','obligations')
                    for identity,r in state.get(category,{}).items())
                and not any(r.get('lifecycle_id')==life or r.get('native_id')==position['id']
                    for r in state.get('runtime_pending',{}).values())
                and not any(r.get('lane')==lane and r.get('native') in (position['id'],str(life).split(':',1)[-1])
                    for r in state.get('pending_deliveries',[]))
                and (not held or held.get('status')!='OPEN'))
    # Legacy accounting retains exact delivery receipts in its normal prefix.
    from meme_machine.portfolio_accounting import PortfolioAccounting
    from meme_machine.portfolio_lane_integration import PortfolioLaneProducer
    with closing(_readonly(path)) as db:
        db.execute('BEGIN')
        account=object.__new__(PortfolioAccounting);account.db=db
        state=account._replay()
        if state is None:return False
        if db.execute('SELECT 1 FROM portfolio_native_pending WHERE lane=? AND native=?',
                (lane,position['id'])).fetchone():return False
        alias=db.execute('SELECT id FROM portfolio_native_ids WHERE lane=? AND native=?',
            (lane,position['id'])).fetchone()
        if not alias:return False
        native_alias='n'+str(alias[0]);kind='release' if (cancelled is True or cancelled is None and position['entry_tokens']==0) else 'settle'
        if any(json.loads(raw).get('native_lifecycle_id')==native_alias
                for raw, in db.execute('SELECT body FROM portfolio_native_pending WHERE lane=?',(lane,))):return False
        event_id='portfolio:'+lane+':'+digest([state['receipt']['epoch_id'],lane,native_alias,'native:'+event_hash,kind])
        receipt=account.canonical_event(event_id)
        provenance=((receipt or {}).get('body',{}).get('data') or {}).get('provenance') or {}
        producer=object.__new__(PortfolioLaneProducer);producer.epoch_id=state['receipt']['epoch_id']
        reservation=producer._reservation_id(lane,native_alias)
        # Receipt and terminal position are both products of native accountant
        # replay. A pending delivery or surviving reservation is never flat.
        held=state['positions'].get(lane+':'+native_alias)
        return bool(provenance.get('native_lifecycle_id')==native_alias
            and provenance.get('native_journal_hash')==event_hash
            and provenance.get('source_event_id')=='native:'+event_hash
            and reservation not in state['reservations']
            and not any(r.get('lane')==lane and r.get('lifecycle_id')==lane+':'+native_alias
                for r in state['reservations'].values())
            and (not held or held.get('state')!='OPEN'))


def verify_lifecycle(root, qualifier, life, *, read_context=None):
    """Read exact native replay and release acknowledgements; absence is unresolved."""
    if read_context is not None:
        from meme_machine.runtime.native_restore_context import require_read_context
        read_context=require_read_context(read_context)
    from .pons_selective_capital import CohortCapital
    root=Path(root);capital_path=root/'pons-selective-cohort-capital.sqlite'
    with _readonly_snapshot(capital_path,read_context) as db:
        genesis=json.loads(db.execute('SELECT body FROM capital_genesis WHERE id=1').fetchone()[0])
        guard=object.__new__(CohortCapital);guard.path=str(capital_path);guard.capital=genesis['capital']
        guard._reconcile(db,readonly=True,readonly_authority=_shared_reader(read_context))
        rows=[json.loads(raw) for raw, in db.execute('SELECT body FROM capital_positions')]
    # qindex is the immutable controller/native path join, not a summary status.
    original_path=(lambda value:read_context.identity(value,base=read_context.root/'pons')) if read_context is not None else (lambda value:Path(value).resolve())
    rows=[r for r in rows if original_path(r['trial_path']).parent==original_path(root)
        and Path(r['trial_path']).name in ('trial-%03d.sqlite'%qualifier['index'],'trial-%d.sqlite'%qualifier['index'])]
    if len(rows)!=1:raise BoundaryError('selective_reentry_capital_lifecycle_join')
    row=rows[0];identity=row['id'];path=Path(row['trial_path'])
    if life.get('lifecycle_id') and life['lifecycle_id']!=identity:raise BoundaryError('selective_reentry_receipt_identity')
    if read_context is not None:path=original_path(path)
    with _readonly_snapshot(path,read_context) as native:
        store=object.__new__(Store);store.db=native
        paper=object.__new__(SelectivePaper);paper.store=store;paper.experiment=STRATEGY_NAMESPACE
        position=paper._get(identity);history=native_history(paper,identity)
        decision=store.get(DECISION_CATEGORY,identity)
        if digest(decision)!=row['decision_hash']:raise BoundaryError('selective_reentry_decision_identity')
        vector=qualifier.get('vector') or {}
        from meme_machine.runtime.policy_compatibility import known_hash
        if (not known_hash('pons_current',vector.get('policy_hash'))
                or vector.get('policy_hash')!=decision.get('policy_hash') or not vector.get('current_threshold_pass')
                or qualifier.get('curve')!=decision.get('market')
                or qualifier.get('token')!=decision.get('token')
                or qualifier.get('source_transaction')!=decision.get('source_transaction')
                or vector.get('evidence_available_at')!=decision.get('asof')
                or type(vector.get('asof')) is not int):
            raise BoundaryError('selective_reentry_qualifier_join')
        if decision.get('qualifying_vector_id') is not None:
            if decision['qualifying_vector_id']!=digest(vector) or decision.get('qualifying_vector_asof')!=vector['asof']:
                raise BoundaryError('selective_reentry_vector_conflict')
        else:
            # A legacy base's reduced metrics alone do not authenticate the
            # original nomination clock. Missing exact time/identity stays open.
            from .pons_selective_recovery import BASE
            base_row=native.execute('SELECT 1 FROM records WHERE category=? AND id=?',(BASE,identity)).fetchone()
            if base_row:
                base=store.get(BASE,identity);saved=base.get('evaluation') or {};saved_vector=saved.get('vector') or {}
                if (base.get('identity')!=identity or saved.get('source_transaction')!=qualifier['source_transaction']
                        or saved.get('token')!=qualifier['token'] or saved.get('curve')!=qualifier['curve']
                        or saved.get('qualifying_vector_id')!=digest(vector)
                        or saved_vector.get('asof')!=vector['asof']
                        or any(saved_vector.get(k)!=vector.get(k) for k in ('current_threshold_pass','policy_hash','trajectory','demand'))):
                    raise BoundaryError('selective_reentry_original_vector_join')
            elif history['entry'] is not None:
                raise BoundaryError('selective_reentry_original_vector_missing')
        entry=history['entry'];filled=bool(entry and entry.get('quote')
            and entry['position']['entry_tokens']>0 and entry['position']['cost']>0)
        if entry and not filled:raise BoundaryError('selective_reentry_entry_execution_unresolved')
        flat=position['status']=='settled' and all(position.get(k)==0 for k in
            ('tokens','entry_tokens','cost','remaining_cost','reserved')) and position.get('pending_exit_tokens') is None
        zero_cancel=bool(history['complete'] and history['actions'].get('reserve')==1
            and history['actions'].get('cancel')==1 and not history['actions'].get('entry')
            and not history['actions'].get('scale_add') and flat)
        terminal=position['status']=='settled' and position['tokens']==0 and position['reserved']==0 and position['remaining_cost']==0 and position.get('pending_exit_tokens') is None
        from meme_machine.runtime.storage import pons_prefix
        event_hash=digest((pons_prefix(paper).get(identity) or {}).get('event'))
        events=paper.events(identity)
        if events:event_hash=digest(events[-1])
    acknowledged=bool(terminal and row['status']=='settled' and row['reserved']==0
        and row.get('native_position')==position and row.get('native_settlement_hash')==digest(position)
        and row.get('native_journal_hash')==event_hash and row.get('native_accounting',{}).get('integral_complete')
        and _sleeve_ack(position,genesis['capital'],read_context=read_context)
        and _portfolio_ack(position,event_hash,read_context=read_context))
    return dict(index=qualifier['index'],lifecycle_id=identity,
        outcome='filled_trade' if filled else 'never_filled_cancellation' if zero_cancel else 'active_or_unresolved',
        native_terminal=terminal,terminal_ready=acknowledged and (filled or zero_cancel),native_position_hash=digest(position),
        vector_id=digest(vector),vector=json.loads(canonical(vector)),original_at=vector['asof'])


def validate_references(result):
    value=result.get('reentry_references') or {}
    for state in value.values():
        if state.get('hash')!=digest({k:v for k,v in state.items() if k!='hash'}):
            raise BoundaryError('selective_reentry_checkpoint_integrity')
    return value


def refresh_reference(root, result, qualifier, life, *, read_context=None):
    references=result.setdefault('reentry_references',{})
    curve=qualifier['curve'];state=references.setdefault(curve,{})
    try:fact=verify_lifecycle(root,qualifier,life,read_context=read_context)
    except (BoundaryError,ValueError,KeyError,TypeError,OSError,sqlite3.Error) as error:
        fact=dict(index=qualifier['index'],lifecycle_id=life.get('lifecycle_id'),
            outcome='active_or_unresolved',terminal_ready=False,unavailable=str(error))
    unresolved=state.setdefault('unresolved_lifecycles',{})
    if fact.get('unavailable'):unresolved[str(qualifier['index'])]=fact
    else:unresolved.pop(str(qualifier['index']),None)
    if qualifier['index']>=(state.get('last_attempt') or {}).get('index',-1):
        state['last_attempt']={k:v for k,v in fact.items() if k!='vector'}
    if fact['outcome']=='filled_trade' and qualifier['index']>=(state.get('last_filled_trade') or {}).get('index',-1):
        state['last_filled_trade']=fact
    state['hash']=digest({k:v for k,v in state.items() if k!='hash'})
    return state


def recover_references(root,result,*,read_context=None):
    validate_references(result)
    by_index={r.get('index'):r for r in result.get('lifecycles',[])}
    # Once at the existing recovery boundary. Retired exact references remain in
    # the same atomic cohort checkpoint, even when their native trial is retired.
    for qualifier in sorted(result.get('qualifiers',[]),key=lambda q:q['index']):
        refresh_reference(root,result,qualifier,by_index.get(qualifier['index']) or {},read_context=read_context)
    return result.setdefault('reentry_references',{})


def retire_expired_references(result,retired_indices,*,now):
    """Forget only references outside Current's unchanged entry lifetime.

    The retirement writer preserves exact reference facts in its existing
    completed-lifecycle store first. Missing joins and eligible history survive.
    Survivor does not consume this map and keeps its own eligibility lifetime.
    """
    from .pons_selective_continuation import ENTRY_THRESHOLDS
    remaining={q['curve'] for q in result.get('qualifiers',[])}
    references=result.get('reentry_references',{})
    for curve,state in list(references.items()):
        if curve in remaining or state.get('unresolved_lifecycles'):continue
        attempt=state.get('last_attempt') or {}
        if attempt.get('index') not in retired_indices or not attempt.get('terminal_ready'):continue
        reference=state.get('last_filled_trade')
        if reference:
            if not reference.get('terminal_ready'):continue
            vector=reference.get('vector') or {};at=vector.get('asof');age=vector.get('token_age_seconds')
            if not (type(at) in (int,float) and type(age) in (int,float) and age>=0
                and now>at-age+ENTRY_THRESHOLDS['max_token_age_seconds']):continue
        del references[curve]


def refresh_pending_ack(root,result):
    """Refresh only known native terminals awaiting their existing release ACK."""
    pending={state['last_attempt']['index'] for state in result.get('reentry_references',{}).values()
        if state.get('last_attempt',{}).get('outcome') in ('filled_trade','never_filled_cancellation')
        and state['last_attempt'].get('native_terminal') is True
        and not state['last_attempt'].get('terminal_ready') and not state['last_attempt'].get('unavailable')}
    if not pending:return
    qualifiers={q['index']:q for q in result.get('qualifiers',[]) if q['index'] in pending}
    lifecycles={life['index']:life for life in result.get('lifecycles',[]) if life.get('index') in pending}
    for index in pending:
        if index in qualifiers:refresh_reference(root,result,qualifiers[index],lifecycles.get(index) or {})


def note_attempt(result,qualifier):
    state=result.setdefault('reentry_references',{}).setdefault(qualifier['curve'],{})
    state['last_attempt']=dict(index=qualifier['index'],lifecycle_id=None,outcome='active_or_unresolved',
        terminal_ready=False,vector_id=digest(qualifier['vector']),original_at=qualifier['vector'].get('asof'))
    state['hash']=digest({k:v for k,v in state.items() if k!='hash'})


def reset_explanation(reference,current):
    previous=(reference or {}).get('vector');policy=REENTRY_POLICY
    result=dict(reference_lifecycle_id=(reference or {}).get('lifecycle_id'),
        reference_vector_id=(reference or {}).get('vector_id'),reference_asof=(reference or {}).get('original_at'),
        elapsed_seconds=None,elapsed_time_pass=None,changed_dimensions=[],eta_change_seconds=None,
        progress_15s_change_bps=None,top3_concentration_change_bps=None,new_buyer_group_count=None,
        reset_required=bool(reference),reset_result=None,qualification_result=current.get('qualification'),
        current_threshold_pass=current.get('current_threshold_pass'),unavailable=[])
    if not previous:
        result['unavailable']=['reference_lifecycle_id','reference_vector_id','reference_asof',
            'elapsed_seconds','elapsed_time_pass','eta_change_seconds','progress_15s_change_bps',
            'top3_concentration_change_bps','new_buyer_group_count','reset_result'];return result
    before=previous.get('trajectory') or {};after=current.get('trajectory') or {}
    old=previous.get('demand') or {};new=current.get('demand') or {}
    if type(previous.get('asof')) is int and type(current.get('asof')) is int:
        result['elapsed_seconds']=current['asof']-previous['asof']
        result['elapsed_time_pass']=result['elapsed_seconds']>=policy['min_seconds']
    else:result['unavailable'].append('elapsed_seconds')
    for target,key,threshold,label,a,b in (
        ('eta_change_seconds','graduation_eta_seconds','min_eta_change_seconds','eta',before,after),
        ('progress_15s_change_bps','progress_15s_bps','min_progress_15s_change_bps','progress',before,after),
        ('top3_concentration_change_bps','top3_buyer_flow_bps','min_top3_concentration_change_bps','concentration',old,new)):
        if a.get(key) is None or b.get(key) is None:result['unavailable'].append(target);continue
        result[target]=int(b[key])-int(a[key])
        if abs(result[target])>=policy[threshold]:result['changed_dimensions'].append(label)
    if 'recent_buy_groups' in old and 'recent_buy_groups' in new:
        result['new_buyer_group_count']=len(set(new['recent_buy_groups'] or ())-set(old['recent_buy_groups'] or ()))
        if result['new_buyer_group_count']>=policy['min_new_buyer_groups']:result['changed_dimensions'].append('new_buyer_groups')
    else:result['unavailable'].append('new_buyer_group_count')
    # The existing predicate remains the sole policy authority, including its
    # historical default semantics. Signed deltas are explanations only.
    result['reset_result']=reentry_regime_reset(previous,current)
    return result


def reentry_decision(state,current,*,active=False):
    state=state or {};reference=state.get('last_filled_trade')
    explanation=reset_explanation(reference,current)
    attempt=state.get('last_attempt')
    explanation['last_attempt']=attempt
    if state.get('unresolved_lifecycles'):
        explanation['unresolved_lifecycles']=state['unresolved_lifecycles']
        if not reference:explanation['reset_required']=None
    reason=None
    if active:reason='same_curve_lifecycle_active'
    elif state.get('unresolved_lifecycles'):reason='prior_curve_reset_reference_unresolved'
    elif attempt and not attempt.get('terminal_ready'):reason='prior_curve_lifecycle_not_flat'
    elif reference and not explanation['reset_result']:reason='reentry_regime_not_reset'
    explanation['authorization_rejection']=reason
    return reason,explanation
