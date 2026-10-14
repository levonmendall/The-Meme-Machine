"""One explicit PAPER decision transition, independent of financial identities.

This is recovery compatibility on the existing owners' checkpoints. It never
changes a genesis, balance, journal event, portfolio epoch, or holding policy.
"""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3

from meme_machine.runtime.journal import canonical, digest
from meme_machine.paper_policy_revision import ACTIVE_REVISION, previous_hash

SELECTION_KEY = 'paper_decision_policy_selection'
SELECTION_NAMESPACE = '__paper_decision_policy__'


def regime_for(strategy):
    if 'survivor' in strategy:
        return 'pump_survivor' if 'pump' in strategy else 'pons_survivor'
    if 'pump' in strategy:return 'pump_current'
    if 'pons' in strategy:return 'pons_current'
    raise ValueError('paper_policy_transition_unknown_strategy')


def active_hash(regime):
    if regime=='pump_current':
        from meme_machine.lanes.pump.pump_acceleration_strategy import policy_hash
        return policy_hash()
    if regime=='pump_survivor':
        from meme_machine.lanes.pump.pumpswap_survivor import POLICY_HASH
    elif regime=='pons_current':
        from meme_machine.lanes.pons.pons_selective_continuation import POLICY_HASH
    elif regime=='pons_survivor':
        from meme_machine.lanes.pons.pons_postgrad_survivor import POLICY_HASH
    else:raise ValueError('paper_policy_transition_unknown_regime')
    return POLICY_HASH


def known_hash(regime,value):
    """Historical joins may use either exact source policy, never an arbitrary hash."""
    return value in (previous_hash(regime),active_hash(regime))


def compatible_identity(stored,requested,*,regime,field='policy_hash'):
    old=dict(stored);new=dict(requested)
    old_hash=old.pop(field,None);new_hash=new.pop(field,None)
    return (old==new and old_hash==previous_hash(regime)
        and new_hash==active_hash(regime) and old_hash!=new_hash)


def selection(financial_identity,decision_identity):
    return dict(schema='paper-decision-policy-selection-v1',revision=ACTIVE_REVISION,
        financial_identity=financial_identity,decision_identity=decision_identity,
        financial_identity_hash=digest(financial_identity),
        decision_identity_hash=digest(decision_identity))


def require_flat_rows(rows,*,kind):
    """Only explicit terminal zero quantities establish a transition boundary."""
    for row in rows:
        if kind=='sleeve':
            terminal=row.get('status')=='settled' and row.get('held')==0 and bool(row.get('terminal_hash'))
            pending=(row.get('scale_reservation') or {}).get('status')=='reserved'
        elif kind=='capital':
            native=row.get('native_position') or row.get('shared_terminal_position')
            terminal=(row.get('status')=='settled' and row.get('reserved')==0
                and isinstance(native,dict) and row.get('native_settlement_hash')==digest(native)
                and row.get('native_accounting',{}).get('replay_verified') is True)
            pending=False
            if terminal:require_flat_rows([native],kind='pons')
        elif kind=='pons':
            terminal=(row.get('status')=='settled' and row.get('tokens')==0
                and row.get('reserved')==0 and row.get('remaining_cost')==0)
            pending=bool(row.get('pending_exit_tokens') or row.get('controller_state',{}).get('pending_action'))
        else:
            terminal=(row.get('status') in ('settled','cancelled') and row.get('tokens')==0
                and row.get('reserved')==0 and row.get('basis')==0)
            pending=bool(row.get('pending_action'))
        if not terminal or pending:
            raise ValueError('paper_policy_transition_unresolved_'+kind+':'+str(row.get('id','unavailable')))


def require_flat_portfolio(state):
    """Pure check reused by supervisor preflight and the native transition boundary."""
    if (not isinstance(state,dict) or not isinstance(state.get('positions'),dict)
            or not isinstance(state.get('reservations'),dict)):
        raise ValueError('paper_policy_transition_portfolio_evidence_unavailable')
    for key in ('positions','reservations','commitments','obligations','runtime_pending','runtime_inbox',
                'pending_deliveries','pending_backing'):
        if key in state and not isinstance(state[key],list if key=='pending_deliveries' else dict):
            raise ValueError('paper_policy_transition_portfolio_evidence_unavailable:'+key)
        if state.get(key):raise ValueError('paper_policy_transition_unresolved_'+key)


def assert_shared_transition(root,state):
    """Permit revised restart only after the original flat/ACKed selection.

    Supervisor calls this before admission or children. An existing revised
    sleeve checkpoint proves that its selection happened while every old
    obligation was clear; new positions keep their own effective policy facts.
    """
    if (not isinstance(state,dict) or not isinstance(state.get('positions'),dict)
            or not isinstance(state.get('reservations'),dict)):
        raise ValueError('paper_policy_transition_portfolio_evidence_unavailable')
    try:
        require_flat_portfolio(state)
        return
    except ValueError as error:
        if str(error).startswith('paper_policy_transition_portfolio_evidence_unavailable'):raise
    from meme_machine.runtime.directional_sleeve import policies
    for lane in ('pump','pons'):
        path=Path(root)/lane/'directional-sleeve.sqlite'
        if not path.is_file():raise ValueError('paper_policy_transition_unresolved_portfolio:'+lane)
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
            db.execute('BEGIN')
            raw=db.execute('SELECT body FROM sleeve_genesis WHERE id=1').fetchone()
            if raw is None:raise ValueError('paper_policy_transition_sleeve_identity_unavailable:'+lane)
            identity=json.loads(raw[0]);requested=dict(identity,policies=policies(lane))
            if identity.get('lane')!=lane:raise ValueError('paper_policy_transition_sleeve_identity_unavailable:'+lane)
            if identity!=requested:
                if (set(identity['policies'])!=set(requested['policies']) or not all(
                        compatible_identity(dict(policy_hash=identity['policies'][strategy]),
                            dict(policy_hash=value),regime=regime_for(strategy))
                        for strategy,value in requested['policies'].items())):
                    raise ValueError('paper_policy_transition_unrecognized_financial_policy:'+lane)
                row=db.execute('SELECT value FROM opportunity_meta_v1 WHERE key=?',(SELECTION_KEY,)).fetchone()
                if row is None:raise ValueError('paper_policy_transition_unresolved_old_policy:'+lane)
                saved=json.loads(row[0]);checksum=saved.pop('checksum',None)
                if checksum!=digest(saved) or saved!=selection(identity,requested):
                    raise ValueError('paper_policy_selection_checkpoint_conflict')
            for raw, in db.execute('SELECT body FROM sleeve_positions'):
                held=json.loads(raw)
                if held.get('status')!='settled' and held.get('decision_policy_hash')!=requested['policies'].get(held.get('strategy')):
                    raise ValueError('paper_policy_transition_unresolved_old_policy:'+held['id'])


def require_external_flat():
    """Check existing selected authority and delivery ACKs without becoming its writer."""
    database=os.environ.get('MM_PORTFOLIO_ACCOUNTING_DB')
    if database:
        from meme_machine.shared_capital.runtime import selected
        shared=selected(database)
        if shared is None:
            raise ValueError('paper_policy_transition_legacy_portfolio_requires_reconciliation')
        with closing(sqlite3.connect(Path(shared).resolve().as_uri()+'?mode=ro',uri=True)) as db:
            db.execute('BEGIN')
            row=db.execute('SELECT body,hash FROM shared_capital_projection WHERE id=1').fetchone()
            if row is None:raise ValueError('paper_policy_transition_portfolio_evidence_unavailable')
            value=json.loads(row[0])
            if digest(value)!=row[1]:raise ValueError('paper_policy_transition_portfolio_identity')
            # A sibling owner may already have selected the revision while
            # flat, then opened a revised position before this lazy book opens.
            # Its existing selection proof permits that staggered restart;
            # this book still separately proves all its own old rows terminal.
            assert_shared_transition(Path(database).parent,value)
    sleeve=os.environ.get('MM_DIRECTIONAL_SLEEVE_DB')
    if sleeve and not Path(sleeve).is_file():raise ValueError('paper_policy_transition_sleeve_evidence_unavailable')
    if sleeve:
        with closing(sqlite3.connect(Path(sleeve).resolve().as_uri()+'?mode=ro',uri=True)) as db:
            rows=[json.loads(raw) for raw, in db.execute('SELECT body FROM sleeve_positions')]
            try:require_flat_rows(rows,kind='sleeve')
            except ValueError:
                raw=db.execute('SELECT body FROM sleeve_genesis WHERE id=1').fetchone()
                identity=json.loads(raw[0]) if raw else None
                if identity is None:raise ValueError('paper_policy_transition_sleeve_identity_unavailable')
                from meme_machine.runtime.directional_sleeve import policies
                requested=dict(identity,policies=policies(identity['lane']))
                if requested!=identity:
                    if (set(identity['policies'])!=set(requested['policies']) or not all(
                            compatible_identity(dict(policy_hash=identity['policies'][strategy]),
                                dict(policy_hash=value),regime=regime_for(strategy))
                            for strategy,value in requested['policies'].items())):
                        raise ValueError('paper_policy_transition_unrecognized_financial_policy')
                    row=db.execute('SELECT value FROM opportunity_meta_v1 WHERE key=?',(SELECTION_KEY,)).fetchone()
                    saved=json.loads(row[0]) if row else {}
                    checksum=saved.pop('checksum',None)
                    if checksum!=digest(saved) or saved!=selection(identity,requested):
                        raise ValueError('paper_policy_transition_unresolved_old_sleeve')
                if any(r.get('status')!='settled' and r.get('decision_policy_hash')!=requested['policies'].get(r.get('strategy')) for r in rows):
                    raise ValueError('paper_policy_transition_unresolved_old_sleeve')


def runtime_selection(db,expected):
    row=db.execute('SELECT body,hash FROM runtime_state WHERE identity=? AND key=?',
        (SELECTION_NAMESPACE,SELECTION_KEY)).fetchone()
    if row is None:return False
    value=json.loads(row[0])
    if digest(value)!=row[1] or value!=expected:
        raise ValueError('paper_policy_selection_checkpoint_conflict')
    return True


def save_runtime_selection(db,value):
    db.execute('INSERT INTO runtime_state VALUES(?,?,?,?)',
        (SELECTION_NAMESPACE,SELECTION_KEY,canonical(value),digest(value)))
