"""Fold only preserved, acknowledged terminals whose native candidate retired.

The existing prefix anchors retain balances and hash chains. A bounded pending
receipt joins the two native databases across crashes; raw rows remain in the
same digest-bound predecessor artifacts used for their journal checkpoints.
"""
import json
from certification.journal import canonical,digest
from certification.lifecycle_identity import parsed,archived_scope


def metrics(summary,position):
    counts=summary['actions'];entered=bool(counts.get('filled'))
    terminal=bool(counts.get('settled'));monitored=bool(counts.get('mark'))
    return dict(natural_entries=int(entered),natural_settlements=int(entered and terminal),
        natural_monitoring=int(entered and monitored),natural_partial_realizations=counts.get('partial_harvest',0),
        natural_exits=counts.get('settled',0),complete_natural_lifecycles=int(entered and terminal and monitored))


def _save(book,anchor):
    table='journal_archive' if 'run_id' in book.identity else 'sleeve_archive'
    book.db.execute('UPDATE '+table+' SET body=?,hash=? WHERE id=1',(canonical(anchor),digest(anchor)))


def _eligible(history,candidate):
    if not candidate or history.get_meta('graduation_floor') is None:return False
    row=history.get(candidate)
    return row is None or (row['state']=='retired' and not row.get('position')
        and row['graduation']['at']<history.get_meta('graduation_floor'))


def _touched(sleeve):
    # The current strategy may already have appended unrelated startup events.
    return {json.loads(raw)['row']['id'] for raw, in sleeve.db.execute('SELECT body FROM sleeve_journal')}


def _book_commit(book,plan):
    with book.transaction():
        anchor=book._archive()
        if anchor.get('retirement_receipt')==plan['hash']:return
        before=book.reconcile();proof=book.replay()
        if book.db.execute('SELECT COUNT(*) FROM journal').fetchone()[0]:raise ValueError('retirement_new_native_events')
        totals=anchor.setdefault('folded',{})
        aggregate=totals.setdefault('metrics',{})
        for identity,expected in plan['positions'].items():
            if book._load(identity)!=expected or anchor['positions'].get(identity)!=expected:
                raise ValueError('retirement_native_changed')
            for key,value in metrics(anchor['journal_proofs'][identity],expected).items():
                aggregate[key]=aggregate.get(key,0)+value
            for key in ('realized','capital_unit_seconds'):
                totals[key]=totals.get(key,0)+expected[key]
            totals['settled']=totals.get('settled',0)+int(expected['status']=='settled')
            anchor['positions'].pop(identity);anchor['risk_states'].pop(identity,None)
            anchor['journal_proofs'].pop(identity)
            book.db.execute('DELETE FROM positions WHERE id=?',(identity,))
            book.db.execute('DELETE FROM runtime_state WHERE identity=?',(identity,))
        anchor['archived_entry_scope']=plan['scope'];anchor['retirement_receipt']=plan['hash']
        anchor['retirement_pending']=plan
        _save(book,anchor)
        if book.reconcile()!=before or book.replay()!=proof:raise ValueError('retirement_native_accounting_changed')


def _sleeve_commit(sleeve,plan):
    with sleeve.transaction():
        anchor=sleeve._archive()
        if anchor.get('retirement_receipt')==plan['hash']:return
        before=sleeve.reconcile()
        if _touched(sleeve)&(set(plan['sleeve_positions'])|set(plan['candidates'])):
            raise ValueError('retirement_new_sleeve_events')
        totals=anchor.setdefault('folded',{})
        for identity,expected in plan['sleeve_positions'].items():
            if sleeve.get(identity)!=expected or anchor['positions'].get(identity)!=expected:
                raise ValueError('retirement_sleeve_changed')
            totals['positions']=totals.get('positions',0)+1;totals['realized']=totals.get('realized',0)+expected['pnl']
            anchor['positions'].pop(identity);sleeve.db.execute('DELETE FROM sleeve_positions WHERE id=?',(identity,))
        for candidate,expected in plan['candidates'].items():
            if sleeve.candidate(candidate)!=expected or anchor['candidates'].get(candidate)!=expected:
                raise ValueError('retirement_candidate_changed')
            if any(json.loads(raw).get('candidate')==candidate for raw, in sleeve.db.execute('SELECT body FROM sleeve_positions')):
                raise ValueError('retirement_candidate_referenced')
            anchor['candidates'].pop(candidate);sleeve.db.execute('DELETE FROM sleeve_candidates WHERE id=?',(candidate,))
        anchor.setdefault('archived_entry_scopes',{})[plan['strategy']]=plan['scope']
        anchor['retirement_receipt']=plan['hash'];_save(sleeve,anchor)
        if sleeve.reconcile()!=before:raise ValueError('retirement_sleeve_accounting_changed')


def compact(book,sleeve,history):
    """Called before resumed work; no new authority is created by this receipt."""
    native=book._archive();shared=sleeve._archive()
    if native is None or shared is None:return False
    pending=native.get('retirement_pending')
    if pending:
        if digest({k:v for k,v in pending.items() if k!='hash'})!=pending['hash']:
            raise ValueError('retirement_pending_corruption')
        plan=pending
    else:
        authority=native['authority'];other=shared['authority'];state=authority['state_hash']
        if ('authorization_hash' not in authority or other.get('state_hash')!=state
                or authority.get('artifact')!=other.get('artifact')
                or history.get_meta('compacted_from_state')!=state):return False
        if book.db.execute('SELECT COUNT(*) FROM journal').fetchone()[0]:return False
        touched=_touched(sleeve)
        scope=archived_scope(authority);positions={};sleeve_positions={};candidates={}
        for identity,position in native['positions'].items():
            issued=parsed(identity)
            if (issued is None or issued['campaign']!=scope['campaign'] or issued['index']>scope['through']
                    or position['status'] not in ('cancelled','settled')
                    or identity in touched or position.get('candidate') in touched
                    or not _eligible(history,position.get('candidate'))):continue
            held=shared['positions'].get(identity)
            if (not held or held['status']!='settled' or held['held']!=0 or held['pnl']!=position['realized']
                    or held.get('terminal_hash')!=digest(position)):
                raise ValueError('retirement_native_sleeve_acknowledgement')
            positions[identity]=position;sleeve_positions[identity]=held
        strategy=book.identity['lane']
        for candidate,row in shared['candidates'].items():
            if row['strategy']!=strategy or candidate in touched or not _eligible(history,candidate):continue
            if any(p.get('candidate')==candidate and identity not in sleeve_positions
                   for identity,p in shared['positions'].items()):continue
            candidates[candidate]=row
        if not positions and not candidates:return False
        plan=dict(schema='survivor-terminal-retirement-v1',scope=scope,strategy=strategy,
            state_hash=state,artifact=authority['artifact'],positions=positions,
            sleeve_positions=sleeve_positions,candidates=candidates)
        plan['hash']=digest(plan)
        with book.transaction():
            anchor=book._archive();anchor['retirement_pending']=plan;_save(book,anchor)
    _book_commit(book,plan)
    _sleeve_commit(sleeve,plan)
    with book.transaction():
        anchor=book._archive();anchor.pop('retirement_pending',None);_save(book,anchor)
    return True
