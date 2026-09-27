"""Checkpoint replayed Meteora history already bound to a native artifact.

Retired scoped positions fold into conserved totals. Live lifecycle entry/tapes
remain exact so the existing strategy restore replays its original exit state.
"""
from contextlib import closing
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
from certification.journal import canonical,digest
from certification.journal_proof import extend
from certification.lifecycle_identity import parsed,archived_scope


def anchor(db,genesis):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='events_archive'").fetchone():return None
    saved=db.execute('SELECT body,hash FROM events_archive WHERE id=1').fetchone()
    if saved is None:return None
    value=json.loads(saved[0])
    if digest(value)!=saved[1] or value['genesis']!=genesis:raise ValueError('meteora_archive_integrity')
    return value


def events(db,genesis):
    saved=anchor(db,genesis)
    if saved:
        yield json.loads(db.execute('SELECT body FROM events WHERE seq=1').fetchone()[0])
        yield from saved['lifecycle_events']
    for raw, in db.execute('SELECT body FROM events WHERE seq>? ORDER BY seq',
            (saved['state']['events'] if saved else 0,)):
        yield json.loads(raw)


def compact(book,path,authority,callbacks):
    with Path(path).open('rb') as stream:
        if hashlib.file_digest(stream,'sha256').hexdigest()!=authority['snapshot_sha256']:
            raise ValueError('meteora_archive_snapshot_identity')
    source=object.__new__(type(book));source.__dict__.update(book.__dict__)
    source.connect=lambda:sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)
    economic=source.replay_economics(*callbacks);before=source.reconcile()
    if economic.get('verified') is not True:raise ValueError('meteora_archive_unverified_economics')
    with closing(source.connect()) as db:
        db.execute('BEGIN');state=source._replay(db);original_state=deepcopy(state);prior=anchor(db,book.genesis)
        logical=list(events(db,book.genesis));scope=archived_scope(authority)
        proofs=deepcopy(prior['journal_proofs']) if prior else {}
        for raw, in db.execute('SELECT body FROM events WHERE seq>? ORDER BY seq',
                (prior['state']['events'] if prior else 0,)):
            event=json.loads(raw);identity=event['identity']
            if identity:proofs[identity]=extend([event],proofs.get(identity))
    retired=[];folded=deepcopy((prior or {}).get('folded',{}))
    metrics=folded.setdefault('metrics',{})
    for identity,position in list(state['positions'].items()):
        issued=parsed(identity)
        if (issued is None or issued['campaign']!=scope['campaign'] or issued['index']>scope['through']
                or position['status'] not in ('settled','cancelled','written_off')):continue
        counts=proofs[identity]['actions'];entered=bool(counts.get('entry'));settled=bool(counts.get('settle'))
        monitored=bool(counts.get('mark'))
        values=dict(natural_entries=int(entered),natural_settlements=int(entered and settled),
            natural_monitoring=int(entered and monitored),natural_partial_realizations=0,natural_exits=0,
            complete_natural_lifecycles=int(entered and settled and monitored))
        for key,value in values.items():metrics[key]=metrics.get(key,0)+value
        key={'settled':'settled','written_off':'writeoffs','cancelled':'cancelled'}[position['status']]
        folded[key]=folded.get(key,0)+1
        folded['economic_events']=folded.get('economic_events',0)+sum(counts.get(k,0) for k in ('entry','mark','settle'))
        retired.append(identity);del state['positions'][identity];del proofs[identity]
    # Repeated unavailable-evidence receipts do not alter strategy state. Their
    # full bytes remain in the predecessor, with the last status retained here.
    kept=[];unresolved={}
    for event in logical:
        identity=event['identity']
        if identity not in state['positions']:continue
        if event['action']=='unresolved':unresolved[identity]=event;continue
        unresolved.pop(identity,None);kept.append(event)
    kept.extend(unresolved.values());kept.sort(key=lambda e:e['at_ns'])
    last={event['identity']:event for event in kept}
    projections={identity:dict(id=identity,
        status='settled' if position['status'] in ('settled','cancelled','written_off') else
               'open' if proofs[identity]['actions'].get('entry') else 'reserved',
        version=proofs[identity]['events']-1,at=last[identity].get('at'),last_action=last[identity]['action'])
        for identity,position in state['positions'].items()}
    value=dict(schema='meteora-preserved-prefix-v1',genesis=book.genesis,state=state,
        lifecycle_events=kept,journal_proofs=proofs,position_projections=projections,
        folded=folded,archived_entry_scope=scope,preserved_economic_replay=economic,
        authority=authority,previous_archive_hash=digest(prior) if prior else None,
        retired_count=len(retired),retired_hash=digest(retired))
    with closing(book.connect()) as db:
        db.execute('BEGIN IMMEDIATE')
        try:
            current=book._replay(db);old=anchor(db,book.genesis)
            if old and old['authority']['state_hash']==authority['state_hash']:
                db.rollback();return False
            if current['events']!=state['events'] or current['hash']!=state['hash']:
                raise ValueError('meteora_archive_new_events')
            if current!=original_state:
                raise ValueError('meteora_archive_source_changed')
            db.execute('INSERT OR REPLACE INTO events_archive VALUES(1,?,?)',(canonical(value),digest(value)))
            db.execute('DROP TRIGGER no_delete')
            db.execute('DELETE FROM events WHERE seq>1 AND seq<=?',(state['events'],))
            db.execute("CREATE TRIGGER no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'append_only'); END")
            if book.reconcile(db=db)!=before or book.replay_economics(*callbacks,db=db)!=economic:
                raise ValueError('meteora_archive_accounting_changed')
            db.commit()
        except BaseException:db.rollback();raise
    return True
