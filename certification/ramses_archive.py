"""Fold only replayed, preserved Ramses terminals; active command history stays."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
from certification.journal import canonical,digest
from certification.journal_proof import extend
from certification.lifecycle_identity import parsed,archived_scope


def anchor(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='ramses_terminal_archive'").fetchone():return None
    row=db.execute('SELECT body,hash FROM ramses_terminal_archive WHERE id=1').fetchone()
    if row is None:return None
    value=json.loads(row[0])
    genesis=db.execute("SELECT body,hash FROM ramses_strategy_meta WHERE id='genesis'").fetchone()
    if digest(value)!=row[1] or value['genesis']!=json.loads(genesis[0]) or digest(value['genesis'])!=genesis[1]:
        raise ValueError('ramses_terminal_archive_integrity')
    return value


def compact(book,path,authority):
    with Path(path).open('rb') as stream:
        if hashlib.file_digest(stream,'sha256').hexdigest()!=authority['snapshot_sha256']:
            raise ValueError('ramses_terminal_snapshot_identity')
    source=object.__new__(type(book));source.__dict__.update(book.__dict__)
    source.db=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)
    try:
        before=source.reconcile();old=anchor(source.db);scope=archived_scope(authority)
        genesis=json.loads(source.db.execute("SELECT body FROM ramses_strategy_meta WHERE id='genesis'").fetchone()[0])
        positions={i:source.position(i) for i, in source.db.execute('SELECT id FROM ramses_strategy_position')}
        retired={i:p for i,p in positions.items() if p['status']=='settled' and
            (issued:=parsed(i)) is not None and issued['campaign']==scope['campaign'] and issued['index']<=scope['through']}
        folded=deepcopy((old or {}).get('folded',dict(positions=0,realized=0,metrics={})))
        summaries={}
        for identity,action,raw in source.db.execute('SELECT id,action,body FROM ramses_strategy_journal ORDER BY seq'):
            if identity in retired:
                summaries[identity]=extend([dict(action=action,position=json.loads(raw))],summaries.get(identity))
        for identity,position in retired.items():
            counts=summaries[identity]['actions'];entered=bool(counts.get('open'));monitored=bool(counts.get('monitor'))
            values=dict(natural_entries=int(entered),natural_settlements=int(entered),
                natural_monitoring=int(entered and monitored),natural_partial_realizations=0,
                natural_exits=counts.get('segment_close',0),complete_natural_lifecycles=int(entered and monitored))
            for key,value in values.items():folded['metrics'][key]=folded['metrics'].get(key,0)+value
            folded['positions']+=1;folded['realized']+=position['realized']
        proof=dict(schema='ramses-terminal-prefix-v1',genesis=genesis,folded=folded,
            archived_entry_scope=scope,authority=authority,retired_count=len(retired),
            retired_hash=digest(retired),journal_summary_hash=digest(summaries),
            previous_archive_hash=digest(old) if old else None)
    finally:source.db.close()
    book.db.execute('BEGIN IMMEDIATE')
    try:
        current=anchor(book.db)
        if current and current['authority']['state_hash']==authority['state_hash']:
            book.db.execute('ROLLBACK');return False
        if book.reconcile()!=before or {i:book.position(i) for i, in book.db.execute('SELECT id FROM ramses_strategy_position')}!=positions:
            raise ValueError('ramses_terminal_source_changed')
        book.db.execute('INSERT OR REPLACE INTO ramses_terminal_archive VALUES(1,?,?)',(canonical(proof),digest(proof)))
        book.db.execute('DROP TRIGGER ramses_journal_no_delete')
        for identity in retired:
            book.db.execute('DELETE FROM ramses_strategy_journal WHERE id=?',(identity,))
            book.db.execute('DELETE FROM ramses_strategy_position WHERE id=?',(identity,))
        book.db.execute("CREATE TRIGGER ramses_journal_no_delete BEFORE DELETE ON ramses_strategy_journal BEGIN SELECT RAISE(ABORT,'append_only'); END")
        if book.reconcile()!=before:raise ValueError('ramses_terminal_accounting_changed')
        book.db.execute('COMMIT')
    except BaseException:book.db.execute('ROLLBACK');raise
    return True


def externalize(destination,artifact,window):
    """Campaign audit JSONL is not an input to native position recovery."""
    from certification.autonomous_window import verify_snapshot,checksum
    folder=Path(destination)/'files/ramses/robinhood-ramses-extended-market.sqlite.campaign'
    path=folder/'lifecycles.jsonl'
    if not path.exists() or not path.stat().st_size:return None
    snapshot=verify_snapshot(artifact)
    target='certification-native/'+snapshot['phase']+'/ramses/'+folder.name+'/'+path.name
    saved=next((row for row in snapshot['files'] if row.get('target')==target),None)
    if not saved or saved['sha256']!=checksum(path) or saved['bytes']!=path.stat().st_size:
        raise ValueError('ramses_campaign_log_not_preserved')
    prior_path=folder/'lifecycle-archive.json'
    old=json.loads(prior_path.read_text()) if prior_path.exists() else None
    if old:
        saved_prior=next((row for row in snapshot['files'] if row.get('target')==
            str(Path(target).with_name(prior_path.name))),None)
        if not saved_prior or saved_prior['sha256']!=checksum(prior_path):
            raise ValueError('ramses_campaign_prefix_not_preserved')
    if old and digest({k:v for k,v in old.items() if k!='hash'})!=old['hash']:
        raise ValueError('ramses_campaign_log_prefix_corruption')
    counts=dict((old or {}).get('counts',{}));records=0
    with path.open() as stream:
        for line in stream:
            row=json.loads(line);counts[row['kind']]=counts.get(row['kind'],0)+1;records+=1
    proof=dict(schema='ramses-campaign-log-prefix-v1',window=window,counts=counts,
        records=records,preserved_snapshot_hash=digest(snapshot),file_sha256=saved['sha256'],
        previous=old['hash'] if old else None)
    proof['hash']=digest(proof)
    # This is an unsealed copy. Any failure leaves it ineligible for restore.
    prior_path.write_text(canonical(proof));path.unlink()
    return proof
