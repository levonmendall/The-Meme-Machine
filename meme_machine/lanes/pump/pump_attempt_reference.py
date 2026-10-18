"""Verified Current terminal-attempt facts in the existing native checkpoint.

Derive only at cancellation/recovery boundaries. A nomination reads the compact
proof and original canonical generation; it never scans historical attempts.
This supplies no accounting, reset policy, quote or retry-loop authority.
"""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import threading
import time

from meme_machine.runtime.journal import digest

KEY='verified-current-terminal-attempt-v1'
FRONTIERS='current_attempt_frontiers'


def reference_key(mint,mode):
    from meme_machine.runtime.journal import canonical
    return canonical([mint,mode])


def terminal_attempt_evidence(life):
    """Tag the existing native event before automatic journal compaction.

    An absent original qualifying vector stays unavailable. Reservation or
    publication time cannot replace its original canonical observation time.
    """
    try:
        snapshot=life.entry_evidence;signal=snapshot['_runtime_recovery']['signal']
        if (signal['observed_at']!=snapshot['market_time'] or signal['mint']!=
                (life.position.mint if life.position else life.reservation['mint'])
                or signal['phase']!=(life.position.mode if life.position else life.reservation['mode'])):return None
        state=snapshot['_runtime_recovery'].get('state') or {}
        graduated=state.get('graduation_time')
        if graduated is None and life.book is not None:
            context=life.book.runtime_state(life.lifecycle_id,'postgrad_context') or {}
            if context.get('mint')==signal['mint']:graduated=context.get('graduation_time')
        from .pump_acceleration_strategy import POLICY
        expires=None if type(graduated) is not int else graduated+max(POLICY.max_postgrad_entry_age_s,600)
        if life.position is not None:
            quantity=life.position.original_quantity;cost=life.position.original_basis
            if type(quantity) is not int or quantity<=0 or type(cost) is not int or cost<=0:return None
        elif life.reservation is not None:
            # The native action proof below must independently confirm that
            # this reservation never filled. These are reservation facts,
            # rather than missing position fields interpreted as zero.
            quantity=cost=0
        else:return None
        return dict(mint=signal['mint'],mode=signal['phase'],
            decision_observed_at=signal['observed_at'],decision_slot=snapshot['slot'],
            decision_vector_hash=digest(signal),entry_universe_expires_at=expires,
            original_entry_quantity=quantity,paid_entry_cost=cost)
    except (KeyError,TypeError,ValueError):return None


def fold_terminal_attempt(frontiers,event,event_hash,summary,components,financial_identity):
    """Fold exact native original facts, independent of analytical reporting.

    The existing prefix owner calls this on an already verified event. The
    components argument remains compatible with that caller but supplies no
    permission: missing or retired reporting detail cannot become an entry gate.
    """
    if event['action'] not in ('cancelled','settled'):return
    attempt=event['evidence'].get('attempt')
    if not attempt:return
    key=reference_key(attempt['mint'],attempt['mode'])
    expiry=attempt.get('entry_universe_expires_at')
    if expiry is not None and time.time()>expiry:
        frontiers.pop(key,None);return
    position=event['position'];actions=summary['actions'];cancelled=event['action']=='cancelled'
    if (summary['events']!=sum(actions.values()) or actions.get('reserved')!=1
            or any(position[key]!=0 for key in ('tokens','basis','reserved','capital_at_risk'))):return
    qty,cost=attempt.get('original_entry_quantity'),attempt.get('paid_entry_cost')
    if type(qty) is not int or type(cost) is not int:return
    if cancelled:
        if actions!={'reserved':1,'cancelled':1} or qty!=0 or cost!=0:return
        frontier=dict(market_time=attempt['decision_observed_at'],slot=attempt['decision_slot'])
    else:
        if (actions.get('filled')!=1 or actions.get('settled')!=1 or actions.get('cancelled',0)
                or qty<=0 or cost<=0):return
        execution=event['evidence'].get('execution') or {}
        frontier=execution.get('snapshot')
        if not frontier:return
    if (frontier['market_time']<attempt['decision_observed_at'] or frontier['slot']<attempt['decision_slot']):return
    proof=dict(attempt,schema=KEY,lifecycle_id=position['id'],original_entry_quantity=qty,
        paid_entry_cost=cost,outcome='verified_never_filled' if cancelled else 'filled_and_closed',
        last_observed_at=frontier['market_time'],last_slot=frontier['slot'],
        terminal_hash=digest(position),terminal_event_hash=event_hash,
        terminal_at=position['last_at'],native_history_complete=True,native_history_actions=dict(actions),
        native_financial_identity=dict(financial_identity),authority='derived_native_history_only',release_authority=False)
    old=frontiers.get(key)
    if old is None or (proof['terminal_at'],proof['last_slot'])>=(old['terminal_at'],old['last_slot']):frontiers[key]=proof


def retain_retirement_frontiers(book,anchor,plan):
    """Keep a latest reference only after the existing exact release receipts.

    This function emits no capital command or delivery. A pending portfolio ACK
    defers this candidate's normal retirement rather than pretending it resolved.
    """
    from .pump_acceleration_strategy import STRATEGY_ID
    if book.identity['lane']!=STRATEGY_ID:return True
    from meme_machine.lanes.pons.pons_reentry import _portfolio_ack
    wanted=set(plan['positions'])
    for proof in anchor.get(FRONTIERS,{}).values():
        identity=proof['lifecycle_id']
        if identity not in wanted:continue
        position=plan['positions'][identity];sleeve=plan['sleeve_positions'][identity]
        if (digest(position)!=proof['terminal_hash'] or sleeve['terminal_hash']!=proof['terminal_hash']
                or sleeve['status']!='settled' or sleeve['held']!=0 or sleeve['pnl']!=position['realized']):
            raise ValueError('pump_attempt_retirement_join')
        if not _portfolio_ack(position,proof['terminal_event_hash'],lane='pump',
                cancelled=proof['outcome']=='verified_never_filled'):return False
        proof['retirement']=dict(receipt_hash=plan['hash'],scope=plan['scope'],
            terminal_position=dict(position),sleeve_release=dict(sleeve),portfolio_release_acknowledged=True,
            native_financial_identity=dict(book.identity))
    return True


def _retired_position(book,proof):
    from meme_machine.runtime.lifecycle_identity import parsed
    if book.db.execute('SELECT 1 FROM positions WHERE id=?',(proof['lifecycle_id'],)).fetchone():return None
    anchor=book._archive();saved=anchor.get(FRONTIERS,{}).get(reference_key(proof['mint'],proof['mode'])) if anchor else None
    retirement=proof.get('retirement');issued=parsed(proof['lifecycle_id'])
    if (saved!=proof or not retirement or not issued or retirement['native_financial_identity']!=book.identity
            or proof['native_financial_identity']!=book.identity or retirement['portfolio_release_acknowledged'] is not True):return None
    for scope in (retirement['scope'],anchor.get('archived_entry_scope') or {}):
        if scope.get('epoch')!=issued['epoch'] or issued['index']>scope.get('through',-1):return None
    position=retirement['terminal_position'];release=retirement['sleeve_release']
    if (position['id']!=proof['lifecycle_id'] or digest(position)!=proof['terminal_hash']
            or release['id']!=position['id'] or release['terminal_hash']!=proof['terminal_hash']
            or release['status']!='settled' or release['held']!=0 or release['pnl']!=position['realized']
            or release.get('cancelled') is not (position['status']=='cancelled')
            or (release.get('scale_reservation') or {}).get('status')=='reserved'):return None
    return position


def _sleeve_ack(book,position,*,read_context=None):
    if read_context is not None:
        from meme_machine.runtime.native_restore_context import require_read_context
        read_context=require_read_context(read_context)
    path=(read_context.sleeve_path('pump') if read_context is not None
        else os.environ.get('MM_DIRECTIONAL_SLEEVE_DB'))
    if not path:return os.environ.get('MM_DIRECTIONAL_COMPOSITE_REQUIRED')!='1'
    from meme_machine.runtime.sleeve_reservations import SleeveReservations
    from meme_machine.lanes.pons.pons_reentry import _shared_reader,_readonly_snapshot
    from meme_machine.shared_capital.native_sleeve import SharedSleeve
    authority=_shared_reader(read_context)
    with _readonly_snapshot(path,read_context) as db:
        sleeve=object.__new__(SharedSleeve if authority else SleeveReservations)
        sleeve.db=db;sleeve.lock=threading.RLock()
        sleeve.identity=json.loads(db.execute('SELECT body FROM sleeve_genesis WHERE id=1').fetchone()[0])
        if sleeve.identity['lane']!='pump' or sleeve.identity['capital']!=book.identity['initial']:
            return False
        if authority:sleeve.authority=authority
        sleeve.reconcile();held=sleeve.get(position['id'])
        return bool(held and held['status']=='settled' and held['held']==0
            and held.get('cancelled') is (position['status']=='cancelled') and held['pnl']==position['realized']
            and held.get('terminal_hash')==digest(position)
            and (held.get('scale_reservation') or {}).get('status')!='reserved')


def release_acknowledged(book,proof,*,read_context=None):
    """Recheck delayed external acknowledgements without changing them."""
    if read_context is not None:
        from meme_machine.runtime.native_restore_context import require_read_context
        require_read_context(read_context).require_database(book.db)
    try:
        retired=False
        try:position=book._load(proof['lifecycle_id'])
        except ValueError:
            position=_retired_position(book,proof);retired=True
            if position is None:return False
        cancelled=proof['outcome']=='verified_never_filled'
        actions=proof['native_history_actions']
        if (proof['schema']!=KEY or proof['native_history_complete'] is not True
                or proof['native_financial_identity']!=book.identity
                or cancelled and (actions!={'reserved':1,'cancelled':1} or
                    proof['original_entry_quantity']!=0 or proof['paid_entry_cost']!=0)
                or not cancelled and (proof['outcome']!='filled_and_closed' or
                    actions.get('reserved')!=1 or actions.get('filled')!=1 or actions.get('settled')!=1 or
                    actions.get('cancelled',0)!=0 or
                    proof['original_entry_quantity']<=0 or proof['paid_entry_cost']<=0)
                or digest(position)!=proof['terminal_hash'] or
                    position['status']!=('cancelled' if cancelled else 'settled')
                or any(position[key]!=0 for key in ('tokens','basis','reserved','capital_at_risk'))
                or cancelled and position.get('scale_request') is not None):return False
        if retired:return True
        from meme_machine.lanes.pons.pons_reentry import _portfolio_ack
        return _sleeve_ack(book,position,read_context=read_context) and _portfolio_ack(position,proof['terminal_event_hash'],
            lane='pump',cancelled=cancelled,read_context=read_context)
    except (KeyError,ValueError,TypeError,sqlite3.Error):return False


def _terminal_attempt(book,identity,signal,snapshot,*,save,read_context=None):
    """Verify complete exact-lifecycle history at terminal/recovery boundaries.

    A retained reservation prefix is usable only with its complete native action
    summary and explicit zero quantity/basis. An old terminal prefix without this
    checkpoint is unavailable rather than inferred to have never filled.
    """
    if book is None:return None
    try:
        saved=book.runtime_state(identity,KEY)
        if saved is not None:return saved if release_acknowledged(book,saved,read_context=read_context) else None
        anchor=book._archive()
        folded=(anchor or {}).get(FRONTIERS,{}).get(reference_key(signal.mint,signal.phase))
        if folded and folded['lifecycle_id']==identity:
            return folded if release_acknowledged(book,folded,read_context=read_context) else None
        replay=book.replay();position=book._load(identity)
        prefix=(anchor or {}).get('positions',{}).get(identity)
        actions={};original=None;entry_quantity=entry_cost=None
        if prefix is not None:
            summary=(anchor or {}).get('journal_proofs',{}).get(identity)
            if (not summary or summary['actions'].get('reserved')!=1
                    or summary['events']!=sum(summary['actions'].values())):return None
            actions=dict(summary['actions']);original=prefix
            if actions.get('filled')==1:
                controller=(anchor.get('controller_snapshots',{}).get(identity) or {}).get('state',{}).get('position')
                if not controller:return None
                entry_quantity=controller.get('original_quantity');entry_cost=controller.get('original_basis')
        terminal_hash=None;terminal_snapshot=None
        for raw,event_hash in book.db.execute(
                "SELECT body,hash FROM journal WHERE json_extract(body,'$.position.id')=? ORDER BY seq",(identity,)):
            event=json.loads(raw);action=event['action'];actions[action]=actions.get(action,0)+1
            if original is None:original=event['position']
            if action=='filled':
                entry_quantity=event['position']['tokens'];entry_cost=event['position']['basis']
            if action=='settled':
                execution=event['evidence'].get('execution') or {}
                terminal_snapshot=execution.get('snapshot') or event['evidence'].get('snapshot')
            terminal_hash=event_hash
        cancelled=position['status']=='cancelled'
        if (replay['verified'] is not True or original is None
                or position['status'] not in ('cancelled','settled') or position['tokens']!=0 or position['basis']!=0
                or position['reserved']!=0 or position['capital_at_risk']!=0
                or not terminal_hash):return None
        if cancelled:
            if (actions!={'reserved':1,'cancelled':1} or original['status']!='reserved'
                    or original['tokens']!=0 or original['basis']!=0 or position.get('scale_request') is not None):return None
            entry_quantity=entry_cost=0
        elif (actions.get('reserved')!=1 or actions.get('filled')!=1 or actions.get('settled')!=1
                or actions.get('cancelled',0)!=0 or actions.get('scale_add',0)>1
                or type(entry_quantity) is not int or entry_quantity<=0
                or type(entry_cost) is not int or entry_cost<=0 or not terminal_snapshot):return None
        observed=int(signal.observed_at);slot=int(snapshot['slot'])
        if observed!=snapshot['market_time']:return None
        frontier=snapshot if cancelled else terminal_snapshot
        last_observed=int(frontier['market_time']);last_slot=int(frontier['slot'])
        if last_observed<observed or last_slot<slot:return None
        proof=dict(schema=KEY,lifecycle_id=identity,mint=signal.mint,mode=signal.phase,
            decision_observed_at=observed,decision_slot=slot,
            decision_vector_hash=digest(signal.__dict__),original_entry_quantity=entry_quantity,paid_entry_cost=entry_cost,
            outcome='verified_never_filled' if cancelled else 'filled_and_closed',
            last_observed_at=last_observed,last_slot=last_slot,
            terminal_hash=digest(position),terminal_event_hash=terminal_hash,
            terminal_at=position['last_at'],native_history_complete=True,
            native_history_actions=actions,native_replay_head=replay['final_hash'],
            native_financial_identity=dict(book.identity),
            authority='derived_native_history_only',release_authority=False)
        # A delayed release is not a missing native history. Save the proven
        # attempt once; later nominations still recheck all release ACKs.
        if save:book.checkpoint_runtime(identity,KEY,proof,claim=True)
        return proof if release_acknowledged(book,proof,read_context=read_context) else None
    except (KeyError,ValueError,TypeError,sqlite3.Error):return None


def checkpoint_terminal_attempt(book,identity,signal,snapshot):
    return _terminal_attempt(book,identity,signal,snapshot,save=True)


def derive_terminal_attempt(book,identity,signal,snapshot,*,read_context):
    """Identical terminal fold and real ACK checks without installing a proof."""
    from meme_machine.runtime.native_restore_context import require_read_context
    require_read_context(read_context).require_database(book.db)
    return _terminal_attempt(book,identity,signal,snapshot,save=False,read_context=read_context)


def checkpoint_cancelled_attempt(book,identity,signal,snapshot):
    return checkpoint_terminal_attempt(book,identity,signal,snapshot)


def prior_attempt_blocks(book,qualifiers,signal,snapshot):
    """Pending or unresolved exposure blocks; a completed trade is not a count cap.

    Pump Current has no post-trade reset predicate. Other strategies' independent
    reset references and predicates are not consumed or changed by this adapter.
    """
    rows=[row for row in qualifiers if row['mint']==signal.mint and row['mode']==signal.phase]
    if book is None:return bool(rows)
    try:
        anchor=book._archive()
        latest=(anchor or {}).get(FRONTIERS,{}).get(reference_key(signal.mint,signal.phase))
        if latest and (not release_acknowledged(book,latest) or
                signal.observed_at<=latest['last_observed_at'] or
                snapshot['market_time']!=signal.observed_at or snapshot['slot']<=latest['last_slot']):return True
    except (KeyError,ValueError,TypeError,sqlite3.Error):return True
    for row in rows:
        try:
            proof=book.runtime_state(row['lifecycle_id'],KEY)
            if latest and row['lifecycle_id']==latest['lifecycle_id']:proof=latest
            if not proof and latest and latest.get('retirement'):
                from meme_machine.runtime.lifecycle_identity import parsed
                issued=parsed(row['lifecycle_id']);scope=anchor.get('archived_entry_scope') or {}
                present=book.db.execute('SELECT 1 FROM positions WHERE id=?',(row['lifecycle_id'],)).fetchone()
                if (not present and issued and issued['epoch']==scope.get('epoch')
                        and issued['index']<=scope.get('through',-1)):continue
        except (KeyError,ValueError,TypeError,sqlite3.Error):return True
        if (not proof or proof['mint']!=signal.mint or proof['mode']!=signal.phase
                or proof['lifecycle_id']!=row['lifecycle_id'] or not release_acknowledged(book,proof)
                or signal.observed_at<=proof['last_observed_at']
                or snapshot['market_time']!=signal.observed_at or snapshot['slot']<=proof['last_slot']):return True
    return False


def retire_entry_universe(book,mint,graduation_at,now):
    """Prune only at the existing, independently proven Current age retirement."""
    if book is None:return
    from .pump_acceleration_strategy import POLICY
    if now-graduation_at<=max(POLICY.max_postgrad_entry_age_s,600):return
    anchor=book._archive()
    if not anchor:return
    frontiers=anchor.get(FRONTIERS,{})
    keys=[key for key,proof in frontiers.items() if proof['mint']==mint]
    if not keys:return
    with book.transaction():
        for key in keys:frontiers.pop(key)
        from meme_machine.runtime.survivor_terminal_archive import _save
        _save(book,anchor)
