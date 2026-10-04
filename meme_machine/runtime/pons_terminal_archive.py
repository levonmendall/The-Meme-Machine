"""Pons native terminal prefix verification."""
import json
from meme_machine.runtime.journal import canonical,digest
from contextlib import closing
from pathlib import Path
import os,time
def controller_anchor(result):
    value=result.get('archived_trials',{})
    if value and value.get('hash')!=digest({k:v for k,v in value.items() if k!='hash'}):
        raise ValueError('pons_terminal_controller_anchor_corruption')
    return value


def anchor(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='capital_archive'").fetchone():return None
    row=db.execute('SELECT body,hash FROM capital_archive WHERE id=1').fetchone()
    if row is None:return None
    value=json.loads(row[0])
    genesis=json.loads(db.execute('SELECT body FROM capital_genesis WHERE id=1').fetchone()[0])
    if digest(value)!=row[1] or value['genesis']!=genesis:raise ValueError('pons_terminal_archive_integrity')
    return value


def _metrics(events,position):
    from meme_machine.runtime.journal_proof import extend
    counts=extend(events)['actions'];entered=bool(counts.get('entry'));monitored=bool(counts.get('mark'))
    terminal=position['status']=='settled' and bool(counts.get('exit'))
    return dict(natural_entries=int(entered),natural_settlements=int(entered and terminal),
        natural_monitoring=int(entered and monitored),natural_partial_realizations=0,
        natural_exits=counts.get('exit',0)+counts.get('exit_intent',0),
        complete_natural_lifecycles=int(entered and terminal and monitored))


def checkpoint_capital(book):
    """Exact native projection replaces a verified completed journal prefix."""
    with closing(book._connect()) as db:
        db.execute('BEGIN IMMEDIATE')
        try:
            if db.execute('SELECT COUNT(*) FROM capital_journal').fetchone()[0]<512:
                db.commit();return
            before=book._reconcile(db);old=anchor(db) or {}
            value=dict(old,genesis=json.loads(db.execute('SELECT body FROM capital_genesis WHERE id=1').fetchone()[0]),
                sequence=db.execute('SELECT MAX(seq) FROM capital_journal').fetchone()[0],
                positions={i:json.loads(b) for i,b in db.execute('SELECT id,body FROM capital_positions')})
            db.execute('CREATE TABLE IF NOT EXISTS capital_archive(id INTEGER PRIMARY KEY CHECK(id=1),body TEXT NOT NULL,hash TEXT NOT NULL)')
            db.execute('INSERT OR REPLACE INTO capital_archive VALUES(1,?,?)',(canonical(value),digest(value)))
            sql=db.execute("SELECT sql FROM sqlite_master WHERE name='journal_no_delete'").fetchone()[0]
            db.execute('DROP TRIGGER journal_no_delete');db.execute('DELETE FROM capital_journal');db.execute(sql)
            if book._reconcile(db)!=before:raise ValueError('pons_capital_checkpoint_changed')
            db.commit()
        except BaseException:db.rollback();raise


def retire_controller(result):
    """Port the frozen maximum-token-age retirement and native join checks.

    Keep every active controller and eligible re-entry vector. Closed trials
    become aggregate native balances only after cohort/sleeve/portfolio delivery.
    The pending local receipt makes file removal restartable, with no artifact.
    """
    from meme_machine.lanes.pons.pons_selective_continuation import ENTRY_THRESHOLDS
    from meme_machine.lanes.pons.pons_selective_capital import CohortCapital
    from meme_machine.lanes.pons import pons_selective_cohort as module
    from meme_machine.runtime.directional_sleeve import open_sleeve
    from meme_machine.runtime.preserved_checkpoint import snapshot
    from meme_machine.runtime.survivor_terminal_archive import _sleeve_commit
    from meme_machine.runtime.lifecycle_identity import archived_scope
    if not os.environ.get('MM_PAPER_EPOCH'):return
    book=CohortCapital(module.ROOT/'pons-selective-cohort-capital.sqlite',module.STRATEGY_CAPITAL_QUOTE)
    checkpoint_capital(book)
    by_index={r.get('index'):r for r in result['lifecycles']}
    with closing(book._connect()) as db:
        rows={i:json.loads(b) for i,b in db.execute('SELECT id,body FROM capital_positions')}
        old=anchor(db) or {}
    pending=old.get('retirement_pending')
    if pending:plan=pending
    else:
        retired={};drop=[];folded=json.loads(canonical(old.get('folded',{})))
        controller=json.loads(canonical(controller_anchor(result)));now=time.time()
        for q in result['qualifiers']:
            life=by_index.get(q['index']) or {};p=life.get('final_position') or {};row=rows.get(p.get('id'))
            vector=q.get('vector') or {};at=vector.get('asof');age=vector.get('token_age_seconds')
            expired=type(at) in (int,float) and type(age) in (int,float) and age>=0 and now>at-age+ENTRY_THRESHOLDS['max_token_age_seconds']
            if not expired or not row or row['status']!='settled' or row.get('native_position')!=p:continue
            if life.get('status') not in ('settled','entry_failed') or int((life.get('reconciliation') or {}).get('open_exposure',0)):continue
            if any(p.get(k,0) for k in ('tokens','reserved','remaining_cost')) or digest(p)!=row.get('native_settlement_hash'):raise ValueError('pons_terminal_native_identity')
            if not row['native_accounting']['integral_complete']:raise ValueError('pons_terminal_native_integral')
            if os.environ.get('MM_PORTFOLIO_ACCOUNTING_DB'):
                from meme_machine.runtime.portfolio import NativePortfolio
                if any(n==p['id'] for n,_ in NativePortfolio(os.environ['MM_PORTFOLIO_ACCOUNTING_DB'],'pons').pending()):continue
            retired[p['id']]=row;drop.append(q['index'])
            for key,value in dict(positions=1,realized=row['pnl'],native_execution_cost=row['native_accounting']['native_execution_cost'],capital_at_risk_unit_nanoseconds=row['native_accounting']['capital_at_risk_unit_nanoseconds']).items():folded[key]=folded.get(key,0)+value
            controller['qualifiers']=controller.get('qualifiers',0)+1
            controller['wallet_converged']=controller.get('wallet_converged',0)+int(bool(q.get('wallet_convergence',{}).get('converged')))
            counts=controller.setdefault('lifecycle_status_counts',{});counts[life['status']]=counts.get(life['status'],0)+1
            controller['realized_pnl_quote']=controller.get('realized_pnl_quote',0)+int(life.get('realized_pnl_quote') or 0)
            controller['graduated_lifecycles']=controller.get('graduated_lifecycles',0)+int(bool(life.get('carried_through_graduation')))
        if not retired:return
        controller['next_index']=max([controller.get('next_index',0)]+[q['index']+1 for q in result['qualifiers']])
        plan=dict(retired=retired,drop=drop,folded=folded,controller=controller,scope=dict(epoch=os.environ['MM_PAPER_EPOCH'],through=time.time_ns()))
        plan['hash']=digest(plan)
    if plan['hash']!=digest({k:v for k,v in plan.items() if k!='hash'}):raise ValueError('pons_retirement_pending_corruption')
    sleeve=open_sleeve('pons',book.capital)
    try:
        shared={}
        if sleeve:
            for identity,row in plan['retired'].items():
                held=sleeve.get(identity)
                if held is None and sleeve._archive().get('retirement_receipt')==plan['hash']:continue
                if not held or held['held'] or held['status']!='settled' or held['pnl']!=row['pnl'] or held.get('terminal_hash')!=row['native_settlement_hash']:raise ValueError('pons_retirement_sleeve_acknowledgement')
                shared[identity]=held
        with closing(book._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                current=anchor(db) or {};before=book._reconcile(db)
                if not current.get('retirement_pending'):
                    current.update(genesis=json.loads(db.execute('SELECT body FROM capital_genesis WHERE id=1').fetchone()[0]),folded=plan['folded'],retirement_pending=plan,archived_entry_scope=plan['scope'])
                    for identity in plan['retired']:
                        current.get('positions',{}).pop(identity,None)
                        db.execute('DELETE FROM capital_positions WHERE id=?',(identity,))
                    sql=db.execute("SELECT sql FROM sqlite_master WHERE name='journal_no_delete'").fetchone()[0]
                    db.execute('DROP TRIGGER journal_no_delete')
                    for identity in plan['retired']:db.execute('DELETE FROM capital_journal WHERE id=?',(identity,))
                    db.execute(sql)
                    db.execute('CREATE TABLE IF NOT EXISTS capital_archive(id INTEGER PRIMARY KEY CHECK(id=1),body TEXT NOT NULL,hash TEXT NOT NULL)')
                    db.execute('INSERT OR REPLACE INTO capital_archive VALUES(1,?,?)',(canonical(current),digest(current)))
                    if book._reconcile(db)!=before:raise ValueError('pons_terminal_capital_changed')
                db.commit()
            except BaseException:db.rollback();raise
        if sleeve and shared:
            path=sleeve.db.execute('PRAGMA database_list').fetchone()[2]
            with snapshot(path,name='pons/sleeve.sqlite',lane='pons') as source:sleeve._compact_preserved(*source)
            joined=dict(plan,positions={},sleeve_positions=shared,candidates={},strategy=module.STRATEGY_NAMESPACE)
            _sleeve_commit(sleeve,joined)
        controller=plan['controller'];controller['hash']=digest({k:v for k,v in controller.items() if k!='hash'})
        result['archived_trials']=controller
        for kind in ('qualifiers','lifecycles'):result[kind]=[r for r in result[kind] if r.get('index') not in plan['drop']]
        # A checkpoint of the new controller precedes removing native files.
        from meme_machine.runtime.robinhood.plane import Plane
        plane=Plane(result['candidate_plane_path'])
        try:
            saved=plane.checkpoint_read('pons_cohort')
            if saved:saved['result']=result;plane.checkpoint('pons_cohort',saved)
        finally:plane.close()
        for row in plan['retired'].values():
            path=Path(row['trial_path'])
            if path.resolve().parent!=module.ROOT.resolve() or not path.name.startswith('trial-'):raise ValueError('pons_retirement_path')
            for suffix in ('','-wal','-shm','.controller.lock'):Path(str(path)+suffix).unlink(missing_ok=True)
        with closing(book._connect()) as db:
            with db:
                current=anchor(db);current.pop('retirement_pending',None)
                db.execute('UPDATE capital_archive SET body=?,hash=? WHERE id=1',(canonical(current),digest(current)))
    finally:
        if sleeve:sleeve.close()

