"""Bounded local telemetry and verified native journal prefix maintenance."""
import json
import os
from pathlib import Path


def audit_ring(db, table, trigger, *, limit=4096, key='seq', where='1=1'):
    """Ordinary audit rows have no scheduling or capital authority."""
    count=db.execute('SELECT COUNT(*) FROM '+table+' WHERE '+where).fetchone()[0]
    if count<=limit:return
    if table=='progress' and key=='sequence':
        # Four native pipelines share this existing maintenance hook. Keep all
        # strategy code unchanged; derive learning before its debug ring folds.
        from meme_machine.runtime.learning import pipeline,install
        if not db.in_transaction:db.execute('BEGIN')
        install(db)
        for row in db.execute('SELECT * FROM progress WHERE sequence NOT IN (SELECT sequence FROM progress ORDER BY sequence DESC LIMIT ?) ORDER BY sequence',(limit,)).fetchall():
            pipeline(db,row)
    sql=db.execute('SELECT sql FROM sqlite_master WHERE name=?',(trigger,)).fetchone()
    if sql:db.execute('DROP TRIGGER '+trigger)
    db.execute('DELETE FROM '+table+' WHERE ('+where+') AND '+key+' NOT IN (SELECT '+key+' FROM '+table+' WHERE '+where+' ORDER BY '+key+' DESC LIMIT ?)',(limit,))
    if sql:db.execute(sql[0])


def solana_cache_retention(db,now):
    """Keep a day of authenticated evidence and all live consumer interests.

    Hot strategy windows retain their original evidence. Expired observations
    grant no permanent execution authority and do not need a second RPC archive.
    Caller owns the transaction and broker lock.
    """
    cutoff=now-86400
    trigger=db.execute("SELECT sql FROM sqlite_master WHERE name='immutable_transactions_no_delete'").fetchone()
    if trigger:db.execute('DROP TRIGGER immutable_transactions_no_delete')
    db.execute("DELETE FROM immutable_transactions WHERE cached_at<? AND NOT EXISTS(SELECT 1 FROM evidence_consumers c WHERE c.signature=immutable_transactions.signature AND c.state='waiting' AND c.deadline>=?)",(cutoff,now))
    if trigger:db.execute(trigger[0])
    # tx_cache is only a legacy compatibility cache in the operational epoch.
    db.execute('DELETE FROM tx_cache WHERE cached_at<?',(cutoff,))
    db.execute('DELETE FROM signature_interests WHERE NOT EXISTS(SELECT 1 FROM immutable_transactions t WHERE t.signature=signature_interests.signature) AND NOT EXISTS(SELECT 1 FROM evidence_consumers c WHERE c.signature=signature_interests.signature)')
    db.execute('DELETE FROM speculative_permits WHERE epoch<?',(int(now//10)-2,))
    db.execute('DELETE FROM evidence_consumers WHERE deadline<? AND state<>\'waiting\'',(cutoff,))
    terminal=db.execute("SELECT sql FROM sqlite_master WHERE name='evidence_terminals_no_delete'").fetchone()
    if terminal:db.execute('DROP TRIGGER evidence_terminals_no_delete')
    db.execute('DELETE FROM evidence_terminals WHERE deadline<? AND NOT EXISTS(SELECT 1 FROM evidence_consumers c WHERE c.owner=evidence_terminals.owner AND c.signature=evidence_terminals.signature)',(cutoff,))
    if terminal:db.execute(terminal[0])
    audit_ring(db,'acquisition_phases','acquisition_phases_no_delete')
    audit_ring(db,'hydration_attempt_failures','hydration_attempt_no_delete')


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
                saved=life.snapshot()
                from meme_machine.runtime.learning import lifecycle
                import time
                with book.transaction():
                    lifecycle(book.db,identity,'pump-current',time.time(),
                              dict(position=saved['position'],reservation=saved['reservation'],entry_features=life.entry_evidence),saved['history'])
                saved['history']=saved['history'][:1]+saved['history'][-64:]
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


def _pons_checkpoint(paper):
    from meme_machine.lanes.pons.evidence import canonical,digest
    row=paper.store.db.execute("SELECT body,hash FROM pons_journal_checkpoint WHERE id=1").fetchone()
    if row is None:return {}
    value=json.loads(row[0])
    if digest(value)!=row[1] or value['experiment']!=paper.experiment:raise ValueError('pons_checkpoint_integrity')
    return value


def pons_prefix(paper):
    return _pons_checkpoint(paper).get('positions',{})


def compact_pons_observations(paper,now):
    """Expire Current quote snapshots, never economic or history authority.

    Executable quotes expire after five seconds. Keep 120 seconds, the native
    Stamp default, before folding their observation-only scopes. The durable
    economic journal/checkpoint already contains exact booked quotes and complete
    controller state. Contiguous history, graduation and writeoff proofs are not
    eligible. The existing checkpoint retains counts and a checksum chain.
    """
    from meme_machine.lanes.pons.evidence import canonical,digest
    db=paper.store.db
    if db.in_transaction:raise ValueError('pons_retention_inside_native_transaction')
    if now<getattr(paper,'_observation_maintenance_due',float('-inf')):return
    db.execute('BEGIN IMMEDIATE')
    try:
        expired=db.execute("""SELECT id FROM records WHERE category='confirmed_block'
            AND id GLOB 'paper-selective-*' AND id NOT GLOB 'paper-selective-writeoff-*'
            AND CAST(json_extract(body,'$.stamp.observed_at') AS INTEGER)<?""",(now-120,)).fetchall()
        retiring=[]
        for identity, in expired:
            scope=identity.rsplit(':',1)[0]
            block=paper.store.get('confirmed_block',identity)
            # Only the new exact snapshot scopes are disposable. Legacy stream
            # scopes and graduation/history authority retain their old rules.
            if scope.rsplit(':',1)[-1]!=digest(block['stamp']):continue
            # A dependency would need its own explicit history retention proof.
            if db.execute("SELECT 1 FROM records WHERE category='confirmed_dependency' AND id LIKE ?",(scope+':%',)).fetchone():continue
            for category,key in db.execute('SELECT category,id FROM records WHERE id=? AND category IN (\'confirmed_block\',\'displaced_block\',\'finalized_block\')',(identity,)):
                retiring.append((category,key,paper.store.get(category,key)))
        # These rows are diagnostics. Native recovery streak, pending intent and
        # original clock are in the atomic controller, not the diagnostic ring.
        for category in ('selective_provider_session_rotation','selective_provider_recovery'):
            for key, in db.execute('SELECT id FROM records WHERE category=? ORDER BY rowid DESC LIMIT -1 OFFSET 512',(category,)):
                retiring.append((category,key,paper.store.get(category,key)))
        if retiring:
            value=_pons_checkpoint(paper) or dict(experiment=paper.experiment,positions={})
            previous=value.get('observation_retention',dict(counts={},hash=None))
            counts=dict(previous['counts'])
            for category,key,body in retiring:counts[category]=counts.get(category,0)+1
            value['observation_retention']=dict(counts=counts,
                hash=digest([previous['hash'],retiring]),through=now,
                authority='expired_quote_snapshots_and_bounded_diagnostics_only')
            for category,key,body in retiring:
                db.execute('DELETE FROM records WHERE category=? AND id=?',(category,key))
                if category=='confirmed_block':db.execute('DELETE FROM cursors WHERE scope=?',('finality:'+key.rsplit(':',1)[0],))
            db.execute('INSERT OR REPLACE INTO pons_journal_checkpoint VALUES(1,?,?)',(canonical(value),digest(value)))
        db.commit()
    except BaseException:
        db.rollback();raise
    paper._observation_maintenance_due=now+60


def compact_pons(paper,*,limit=64):
    """Preserve native flow replay, controller state and event-time integrals."""
    from meme_machine.lanes.pons.pons_selective_ledger import JOURNAL_CATEGORY
    from meme_machine.lanes.pons.evidence import canonical,digest
    db=paper.store.db
    if db.in_transaction:raise ValueError('pons_compaction_inside_native_transaction')
    latest=db.execute("SELECT MAX(CAST(json_extract(body,'$.last_at') AS INTEGER)) FROM pons_selective_paper").fetchone()[0]
    if latest is not None:compact_pons_observations(paper,latest)
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
        value=_pons_checkpoint(paper) or dict(experiment=paper.experiment)
        value['positions']=prefix
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
