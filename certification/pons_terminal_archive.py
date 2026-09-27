"""Retire verified Pons terminal trials only inside an unsealed successor copy.

The immutable predecessor retains every native trial and allocation receipt.
Live trials and all re-entry vectors remain exact. No provider or entry authority.
"""
from contextlib import chdir,closing
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import threading

from certification.journal import canonical,digest
from certification.lifecycle_identity import scope,parsed

FOLDER='pons-selective-continuation-v1-cohort'
CAPITAL=FOLDER+'/pons-selective-cohort-capital.sqlite'


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
    from certification.journal_proof import extend
    counts=extend(events)['actions'];entered=bool(counts.get('entry'));monitored=bool(counts.get('mark'))
    terminal=position['status']=='settled' and bool(counts.get('exit'))
    return dict(natural_entries=int(entered),natural_settlements=int(entered and terminal),
        natural_monitoring=int(entered and monitored),natural_partial_realizations=0,
        natural_exits=counts.get('exit',0)+counts.get('exit_intent',0),
        complete_natural_lifecycles=int(entered and terminal and monitored))


def _controller_prefix(files,source_root,snapshot,rows):
    """Expire only settled pre-graduation re-entry state past frozen token age."""
    from certification.autonomous_window import checksum
    from robinhood_research.pons_selective_continuation import ENTRY_THRESHOLDS
    path=files/'shared/shared-robinhood-evidence.candidates.sqlite'
    with closing(sqlite3.connect(path)) as db:
        raw=db.execute("SELECT body FROM runtime WHERE key='pons_cohort'").fetchone()
    if raw is None:return None
    saved=json.loads(raw[0]);result=saved['result'];logs={};values={}
    inventory={r['target']:r for r in snapshot['files'] if 'target' in r}
    for kind in ('qualifiers','lifecycles'):
        name=result.get('native_archive_paths',{}).get(kind)
        if name:
            relative=Path(name)
            if relative.is_absolute() or relative.parent!=Path(FOLDER):raise ValueError('pons_terminal_controller_path')
            path=files/'pons'/relative
            item=inventory.get('certification-native/'+snapshot['phase']+'/pons/'+name)
            if path.exists():
                if not item or checksum(path)!=item['sha256']:raise ValueError('pons_terminal_controller_not_preserved')
                values[kind]=[json.loads(line) for line in path.read_text().splitlines() if line]
                logs[kind]=path
            elif saved.get('archive_counts',{}).get(kind,0):raise ValueError('pons_terminal_controller_missing')
            else:values[kind]=[]
        else:values[kind]=list(result.get(kind,[]))
    qualifiers=values['qualifiers'];lifecycles=values['lifecycles']
    from certification.robinhood.pons import coalesce_lifecycle_rows
    lifecycles=coalesce_lifecycle_rows(lifecycles);values['lifecycles']=lifecycles
    by_index={x.get('index'):x for x in lifecycles}
    now=max([float(result.get('ended_at',0) or 0)]+[float(q.get('vector',{}).get('asof',0)) for q in qualifiers])
    drop=set();protected=set();old=controller_anchor(result);folded=deepcopy(old)
    for q in qualifiers:
        life=by_index.get(q['index']) or {};position=life.get('final_position') or {}
        native=rows.get(position.get('id'));vector=q.get('vector') or {}
        at=vector.get('asof');age=vector.get('token_age_seconds')
        expired=(type(at) in (int,float) and type(age) in (int,float) and age>=0
                 and now>at-age+ENTRY_THRESHOLDS['max_token_age_seconds'])
        if (expired and native and native['status']=='settled' and native.get('native_position')==position
                and life.get('status') in ('settled','entry_failed')
                and not int((life.get('reconciliation') or {}).get('open_exposure',0))):
            drop.add(q['index'])
            folded['qualifiers']=folded.get('qualifiers',0)+1
            folded['wallet_converged']=folded.get('wallet_converged',0)+int(bool(q.get('wallet_convergence',{}).get('converged')))
            status=life['status'];counts=folded.setdefault('lifecycle_status_counts',{})
            counts[status]=counts.get(status,0)+1
            folded['realized_pnl_quote']=folded.get('realized_pnl_quote',0)+int(life.get('realized_pnl_quote') or 0)
            folded['graduated_lifecycles']=folded.get('graduated_lifecycles',0)+int(bool(life.get('carried_through_graduation')))
        elif position.get('id'):protected.add(position['id'])
    folded['next_index']=max([old.get('next_index',0)]+[q['index']+1 for q in qualifiers])
    return dict(saved=saved,values=values,logs=logs,drop=drop,protected=protected,folded=folded)


def _publish_controller(files,plan,proof,retired):
    if plan is None:return
    # Every removed controller has an independently replayed native retirement.
    for life in plan['values']['lifecycles']:
        if life.get('index') in plan['drop'] and life['final_position']['id'] not in retired:
            raise ValueError('pons_terminal_controller_without_native_retirement')
    saved=plan['saved'];result=saved['result'];folded=plan['folded']
    folded.update(preserved_snapshot_hash=proof['preserved_snapshot_hash'],previous= digest(result.get('archived_trials',{})))
    folded['hash']=digest({k:v for k,v in folded.items() if k!='hash'})
    result['archived_trials']=folded
    for kind in ('qualifiers','lifecycles'):
        keep=[r for r in plan['values'][kind] if r.get('index') not in plan['drop']]
        if kind in plan['logs']:
            plan['logs'][kind].write_text(''.join(canonical(r)+'\n' for r in keep))
            result[kind]=[];saved.setdefault('archive_counts',{})[kind]=len(keep)
        else:result[kind]=keep
    path=files/'shared/shared-robinhood-evidence.candidates.sqlite'
    with closing(sqlite3.connect(path)) as db:
        with db:db.execute("UPDATE runtime SET body=? WHERE key='pons_cohort'",(canonical(saved),))


def _compact(destination,artifact,window):
    from certification.autonomous_window import verify_snapshot,checksum
    from certification.robinhood.window_archive import _preserved
    from certification.sleeve_reservations import SleeveReservations
    from certification.market_assurance import native_positions
    from robinhood_research.evidence import Store
    from robinhood_research.pons_selective_capital import CohortCapital
    from robinhood_research.pons_selective_ledger import SelectivePaper,STRATEGY_NAMESPACE,JOURNAL_CATEGORY
    from robinhood_research.pons_selective_continuation import POLICY_HASH
    files=Path(destination).resolve()/'files';artifact=Path(artifact).resolve()
    root=files/'pons';path=root/CAPITAL
    snapshot=verify_snapshot(artifact);phase=snapshot['phase']
    source_root=artifact/('certification-native/'+phase+'/pons')
    inventory={artifact/r['target'] for r in snapshot['files'] if 'target' in r}
    _preserved(path,source_root/CAPITAL,inventory)
    campaign=scope(window);entry_scope=dict(campaign=campaign['campaign'],through=campaign['index'])
    book=object.__new__(CohortCapital);book.path=str(path)
    with closing(book._connect()) as db:
        genesis=json.loads(db.execute('SELECT body FROM capital_genesis WHERE id=1').fetchone()[0])
        if genesis['policy_hash']!=POLICY_HASH:raise ValueError('pons_terminal_policy')
        book.capital=genesis['capital'];old=anchor(db)
        rows={i:json.loads(b) for i,b in db.execute('SELECT * FROM capital_positions')}
        sequence=max((old or {}).get('sequence',0),db.execute('SELECT COALESCE(MAX(seq),0) FROM capital_journal').fetchone()[0])
    with chdir(root):before=book.reconcile()
    if not before['cash_basis_conservation'] or not before['native_observation_complete']:
        raise ValueError('pons_terminal_native_unreconciled')
    controller=_controller_prefix(files,source_root,snapshot,rows)
    report=native_positions(root,'pons');retired={};trials={};folded=deepcopy((old or {}).get('folded',{}))
    for identity,row in rows.items():
        issued=parsed(identity)
        if (controller and identity in controller['protected']):continue
        if (row['status']!='settled' or issued is None or issued['campaign']!=entry_scope['campaign']
                or issued['index']>entry_scope['through']):continue
        relative=Path(row['trial_path'])
        if relative.is_absolute() or relative.parent!=Path(FOLDER) or not re.fullmatch(r'trial-\d+\.sqlite',relative.name):
            raise ValueError('pons_terminal_trial_path')
        trial=root/relative;original=source_root/relative
        _preserved(trial,original,inventory)
        with closing(sqlite3.connect(trial.resolve().as_uri()+'?mode=ro',uri=True)) as native:
            store=object.__new__(Store);store.db=native
            paper=object.__new__(SelectivePaper);paper.store=store;paper.experiment=STRATEGY_NAMESPACE
            positions=paper.positions()
            if positions!=[row.get('native_position')]:raise ValueError('pons_terminal_trial_ownership')
            position=positions[0];accounting=paper.accounting(identity)
            if (position['status']!='settled' or any(position[k] for k in ('tokens','reserved','remaining_cost'))
                    or position['pnl']!=row['pnl'] or position['realized_pnl']!=row['pnl']
                    or digest(position)!=row.get('native_settlement_hash')
                    or accounting!=row.get('native_accounting') or not accounting['integral_complete']):
                raise ValueError('pons_terminal_trial_accounting')
            events=[store.get(JOURNAL_CATEGORY,key) for key, in native.execute('SELECT id FROM records WHERE category=?',(JOURNAL_CATEGORY,))]
            events.sort(key=lambda e:e['position']['version'])
        retired[identity]=row;trials[identity]=relative
        for key,value in dict(positions=1,realized=row['pnl'],native_execution_cost=accounting['native_execution_cost'],
                capital_at_risk_unit_nanoseconds=accounting['capital_at_risk_unit_nanoseconds']).items():
            folded[key]=folded.get(key,0)+value
        metrics=folded.setdefault('metrics',{})
        for key,value in _metrics(events,position).items():metrics[key]=metrics.get(key,0)+value
    if not retired:return None
    sleeve_path=root/'directional-sleeve.sqlite';sleeve=None
    if sleeve_path.exists():
        _preserved(sleeve_path,source_root/'directional-sleeve.sqlite',inventory)
        sleeve=object.__new__(SleeveReservations);sleeve.lock=threading.RLock()
        sleeve.db=sqlite3.connect(sleeve_path,isolation_level=None)
        sleeve.identity=json.loads(sleeve.db.execute('SELECT body FROM sleeve_genesis WHERE id=1').fetchone()[0])
        ceiling=sleeve.reconcile()
        for identity,row in retired.items():
            held=sleeve.get(identity)
            if (not held or held['held'] or held['status']!='settled' or held['pnl']!=row['pnl']
                    or held['strategy']!=STRATEGY_NAMESPACE or held.get('terminal_hash')!=row['native_settlement_hash']):
                sleeve.close();raise ValueError('pons_terminal_sleeve_acknowledgement')
    proof=dict(schema='pons-terminal-prefix-v1',genesis=genesis,folded=folded,sequence=sequence,
        archived_entry_scope=entry_scope,preserved_snapshot_hash=digest(snapshot),window=window,
        retired_count=len(retired),retired_hash=digest(retired),previous=digest(old) if old else None)
    try:
        with closing(book._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                db.execute('CREATE TABLE IF NOT EXISTS capital_archive(id INTEGER PRIMARY KEY CHECK(id=1),body TEXT NOT NULL,hash TEXT NOT NULL)')
                db.execute('INSERT OR REPLACE INTO capital_archive VALUES(1,?,?)',(canonical(proof),digest(proof)))
                db.execute('DROP TRIGGER journal_no_delete')
                for identity in retired:
                    db.execute('DELETE FROM capital_positions WHERE id=?',(identity,))
                    db.execute('DELETE FROM capital_journal WHERE id=?',(identity,))
                db.execute("CREATE TRIGGER journal_no_delete BEFORE DELETE ON capital_journal BEGIN SELECT RAISE(ABORT,'append_only'); END")
                if book._reconcile(db)!={k:v for k,v in before.items() if k!='unobserved_native_positions'}:
                    raise ValueError('pons_terminal_accounting_changed')
                db.execute('COMMIT')
            except BaseException:db.execute('ROLLBACK');raise
        if sleeve:
            source=source_root/'directional-sleeve.sqlite'
            sleeve._compact_preserved(source,dict(state_hash=digest(snapshot),snapshot_sha256=checksum(source),
                artifact={'digest':'sha256:'+digest(snapshot)},campaign_id=window['campaign_id'],
                authorization_hash=window['authorization_hash'],window_index=window['index']))
            with sleeve.transaction():
                saved=sleeve._archive();totals=saved.setdefault('folded',{})
                for identity,row in retired.items():
                    saved['positions'].pop(identity);sleeve.db.execute('DELETE FROM sleeve_positions WHERE id=?',(identity,))
                    totals['positions']=totals.get('positions',0)+1;totals['realized']=totals.get('realized',0)+row['pnl']
                saved.setdefault('archived_entry_scopes',{})[STRATEGY_NAMESPACE]=entry_scope
                sleeve.db.execute('UPDATE sleeve_archive SET body=?,hash=? WHERE id=1',(canonical(saved),digest(saved)))
                if sleeve.reconcile()!=ceiling:raise ValueError('pons_terminal_sleeve_changed')
        _publish_controller(files,controller,proof,retired)
        # This copy cannot be restored until every deletion and check completes.
        for relative in trials.values():
            (root/relative).unlink()
            lock=root/(str(relative)+'.controller.lock')
            if lock.exists():
                original=source_root/(str(relative)+'.controller.lock')
                if original not in inventory or checksum(lock)!=checksum(original):raise ValueError('pons_terminal_lock_not_preserved')
                lock.unlink()
        with chdir(root):
            if book.reconcile()!=before:raise ValueError('pons_terminal_replay_changed')
        after=native_positions(root,'pons')
        for key in folded['metrics']:
            if after[key]!=report[key]:raise ValueError('pons_terminal_review_changed:'+key)
        if after['violations']:raise ValueError('pons_terminal_review_violation')
        return proof
    finally:
        if sleeve:sleeve.close()


def externalize(destination,artifact,window,source_root):
    if not (Path(destination)/'files/pons'/CAPITAL).exists():return None
    env={k:v for k,v in os.environ.items() if not k.startswith('MM_')}
    env['PYTHONPATH']=str(Path(__file__).resolve().parents[1])
    result=subprocess.run([sys.executable,'-m','certification.pons_terminal_archive',
        str(Path(destination).resolve()),str(Path(artifact).resolve()),canonical(window)],
        cwd=source_root,env=env,capture_output=True,text=True,timeout=60)
    if result.returncode:raise ValueError('pons_terminal_archive_failed:'+result.stderr[-2000:])
    return json.loads(result.stdout)


if __name__=='__main__':
    sys.path.insert(0,os.getcwd())
    from certification.offline_tests import install_network_guard
    install_network_guard()
    print(canonical(_compact(sys.argv[1],sys.argv[2],json.loads(sys.argv[3]))))
