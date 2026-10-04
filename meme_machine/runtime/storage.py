"""Bounded local telemetry and verified native journal prefix maintenance."""
import json
import os
from pathlib import Path


def audit_ring(db, table, trigger, *, limit=4096, key='seq'):
    """Ordinary audit rows have no scheduling or capital authority."""
    count=db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
    if count<=limit:return
    sql=db.execute('SELECT sql FROM sqlite_master WHERE name=?',(trigger,)).fetchone()
    if sql:db.execute('DROP TRIGGER '+trigger)
    db.execute('DELETE FROM '+table+' WHERE '+key+' NOT IN (SELECT '+key+' FROM '+table+' ORDER BY '+key+' DESC LIMIT ?)',(limit,))
    if sql:db.execute(sql[0])


def jsonl_ring(path,row,*,limit=256):
    """Debug projection only. Recovery uses the native SQLite checkpoints."""
    path=Path(path)
    try:
        prior=path.read_text().splitlines()[-limit+1:] if path.exists() else []
        prior.append(json.dumps(row,sort_keys=True,separators=(',',':')))
        temporary=path.with_suffix(path.suffix+'.tmp')
        temporary.write_text('\n'.join(prior)+'\n')
        os.replace(temporary,path)
    except OSError as error:
        print('debug publication failed:',type(error).__name__,flush=True)


def compact_pump(book):
    from meme_machine.runtime.preserved_checkpoint import snapshot
    from meme_machine.runtime.survivor_terminal_archive import _save,_book_commit,_sleeve_commit
    from meme_machine.runtime.directional_sleeve import open_sleeve
    from meme_machine.runtime.lifecycle_identity import archived_scope,parsed
    from meme_machine.runtime.journal import digest
    from meme_machine.lanes.pump.pump_acceleration_paper import PumpAccelerationPaperLifecycle
    if not os.environ.get('MM_PAPER_EPOCH'):return
    if getattr(book,'_maintenance_running',False):return
    if book.db.execute('SELECT COUNT(*) FROM journal').fetchone()[0]<512:return
    path=book.db.execute('PRAGMA database_list').fetchone()[2]
    book._maintenance_running=True
    try:
        with book.lock,snapshot(path,name='pump/paper.sqlite',lane='pump') as preserved:
            if not preserved:return
            snapshots={}
            for identity, in book.db.execute('SELECT id FROM positions'):
                life=PumpAccelerationPaperLifecycle.restore(book,identity)
                saved=life.snapshot();saved['history']=saved['history'][:1]+saved['history'][-64:]
                snapshots[identity]=dict(state=saved,entry_evidence=life.entry_evidence)
            book._compact_preserved(*preserved,cost_reader=lambda _:None,risk_reader=lambda *_:None)
            with book.transaction():
                anchor=book._archive();anchor['controller_snapshots']=snapshots;anchor.pop('controller_events',None);_save(book,anchor)
            sleeve=open_sleeve('pump',book.identity['initial'])
            if sleeve is None:return
            try:
                pending=book._archive().get('retirement_pending')
                if pending:plan=pending
                else:
                    positions={};shared={}
                    for identity,p in book._archive()['positions'].items():
                        held=sleeve.get(identity)
                        if not parsed(identity) or p['status'] not in ('settled','cancelled') or not held:continue
                        if held['held'] or held['status']!='settled':continue
                        if held['pnl']!=p['realized'] or held.get('terminal_hash')!=digest(p):raise ValueError('pump_retirement_acknowledgement')
                        positions[identity]=p;shared[identity]=held
                    if not positions:return
                    sleeve_path=sleeve.db.execute('PRAGMA database_list').fetchone()[2]
                    with snapshot(sleeve_path,name='pump/sleeve.sqlite',lane='pump') as source:
                        sleeve._compact_preserved(*source)
                    plan=dict(schema='current-sleeve-terminal-retirement-v1',scope=archived_scope(preserved[1]),
                        strategy=book.identity['lane'],positions=positions,sleeve_positions=shared,candidates={})
                    plan['hash']=digest(plan)
                _book_commit(book,plan);_sleeve_commit(sleeve,plan)
                with book.transaction():
                    anchor=book._archive();anchor.pop('retirement_pending',None)
                    for identity in plan['positions']:anchor['controller_snapshots'].pop(identity,None)
                    _save(book,anchor)
            finally:sleeve.close()
    finally:book._maintenance_running=False


def pons_prefix(paper):
    from meme_machine.lanes.pons.evidence import canonical,digest
    row=paper.store.db.execute("SELECT body,hash FROM pons_journal_checkpoint WHERE id=1").fetchone()
    if row is None:return {}
    value=json.loads(row[0])
    if digest(value)!=row[1] or value['experiment']!=paper.experiment:raise ValueError('pons_checkpoint_integrity')
    return value['positions']


def compact_pons(paper,*,limit=512):
    """Preserve native flow replay, controller state and event-time integrals."""
    from meme_machine.lanes.pons.pons_selective_ledger import JOURNAL_CATEGORY
    from meme_machine.lanes.pons.evidence import canonical,digest
    db=paper.store.db
    if db.in_transaction:raise ValueError('pons_compaction_inside_native_transaction')
    if db.execute('SELECT COUNT(*) FROM records WHERE category=?',(JOURNAL_CATEGORY,)).fetchone()[0]<=limit:return False
    if getattr(paper,'portfolio',None):paper.portfolio.recover()
    db.execute('BEGIN IMMEDIATE')
    try:
        before=paper.reconcile();rows=paper.positions();prefix=pons_prefix(paper)
        for position in rows:
            events=paper.events(position['id']);last=events[-1] if events else prefix[position['id']]['event']
            accounting=paper.accounting(position['id'])
            entry=next((e for e in events if e['action']=='entry'),prefix.get(position['id'],{}).get('entry'))
            prefix[position['id']]=dict(event=last,accounting=accounting,entry=entry)
        value=dict(experiment=paper.experiment,positions=prefix)
        db.execute('INSERT OR REPLACE INTO pons_journal_checkpoint VALUES(1,?,?)',(canonical(value),digest(value)))
        guard=db.execute("SELECT sql FROM sqlite_master WHERE name='pons_selective_records_no_delete'").fetchone()[0]
        db.execute('DROP TRIGGER pons_selective_records_no_delete')
        keep={p['id']+':'+str(p['version']) for p in rows}
        for key, in db.execute('SELECT id FROM records WHERE category=?',(JOURNAL_CATEGORY,)).fetchall():
            if key not in keep:db.execute('DELETE FROM records WHERE category=? AND id=?',(JOURNAL_CATEGORY,key))
        db.execute(guard)
        if paper.reconcile()!=before:raise ValueError('pons_checkpoint_accounting_changed')
        db.commit()
    except BaseException:
        db.rollback();raise
    return True


def compact_survivor(service,lane):
    """Same-thread maintenance of the existing Current/Survivor primitives."""
    import time
    if not os.environ.get('MM_PAPER_EPOCH') or time.monotonic()<getattr(service,'_next_maintenance',0):return
    from meme_machine.runtime.survivor_history import compact_restored_history
    from meme_machine.runtime.preserved_checkpoint import snapshot
    from meme_machine.runtime.survivor_terminal_archive import compact
    if lane=='pump':
        from meme_machine.lanes.pump.pumpswap_survivor import reduce_reset_history
    else:reduce_reset_history=None
    compact_restored_history(service.history,lane=lane,reducer=reduce_reset_history)
    for book,name in ((service.book,'paper'),(service.sleeve,'sleeve')):
        if getattr(book,'portfolio',None):book.portfolio.recover()
        path=book.db.execute('PRAGMA database_list').fetchone()[2]
        with snapshot(path,name=lane+'/'+name+'.sqlite',lane=lane) as source:
            if source:book._compact_preserved(*source)
    compact(service.book,service.sleeve,service.history)
    service._next_maintenance=time.monotonic()+60
