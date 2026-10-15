"""Fold only replayed, preserved Ramses terminals; active command history stays."""
from copy import deepcopy
import hashlib
import json,time
from pathlib import Path
import sqlite3
from meme_machine.runtime.journal import canonical,digest
from meme_machine.runtime.journal_proof import extend
from meme_machine.runtime.lifecycle_identity import parsed,archived_scope


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
            (issued:=parsed(i)) is not None and issued['epoch']==scope['epoch'] and issued['index']<=scope['through']}
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
            from meme_machine.runtime.learning import lifecycle
            lifecycle(book.db,identity,'ramses',time.time(),retired[identity],
                (dict(action=action,position=json.loads(raw)) for action,raw in
                 book.db.execute('SELECT action,body FROM ramses_strategy_journal WHERE id=? ORDER BY seq',(identity,))))
            book.db.execute('DELETE FROM ramses_strategy_journal WHERE id=?',(identity,))
            book.db.execute('DELETE FROM ramses_strategy_position WHERE id=?',(identity,))
        book.db.execute("CREATE TRIGGER ramses_journal_no_delete BEFORE DELETE ON ramses_strategy_journal BEGIN SELECT RAISE(ABORT,'append_only'); END")
        if book.reconcile()!=before:raise ValueError('ramses_terminal_accounting_changed')
        book.db.execute('COMMIT')
    except BaseException:book.db.execute('ROLLBACK');raise
    return True
