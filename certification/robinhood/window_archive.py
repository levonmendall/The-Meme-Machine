"""Move completed-window observations to their verified native predecessor.

Only a copied, unsealed capsule changes. Candidate/position authority stays hot;
raw audit rows stay in immutable artifacts. Reports cover the current window,
with explicit receipts for earlier windows rather than relabelled old decisions.
"""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3

from certification.journal import canonical,digest
from certification.robinhood.accounting import consistency

# Native Pons ImmutableEvidenceCache limits; these are unchanged storage bounds.
CACHE_LIMITS=dict(header_hash=4096,header_number=4096,receipt=8192,launch=4096,
                  real_quote=4096,compiled_create2_curve=4096)


def logical_hash(db):
    checksum=hashlib.sha256()
    for line in db.iterdump():checksum.update((line+'\n').encode())
    return checksum.hexdigest()


def _preserved(path,original,inventory):
    if original not in inventory or not original.is_file():raise ValueError('robinhood_history_not_preserved')
    with closing(sqlite3.connect(original.resolve().as_uri()+'?mode=ro',uri=True)) as source:
        with closing(sqlite3.connect(path)) as copied:
            if logical_hash(source)!=logical_hash(copied):raise ValueError('robinhood_history_source_changed')


def _erase(db,table,trigger,where='',args=()):
    sql=db.execute('SELECT sql FROM sqlite_master WHERE name=?',(trigger,)).fetchone()
    if sql is None:raise ValueError('robinhood_history_guard_missing')
    db.execute('DROP TRIGGER '+trigger)
    db.execute('DELETE FROM '+table+where,args)
    db.execute(sql[0])


def _retire_identities(db,files,artifact,snapshot,window,inventory,old):
    """Retire acknowledged predecessors; retained controllers always win.

    The latest source frontier for each lane remains hot. A bounded lane fence
    replaces retired per-candidate fences, so historical source replay cannot
    become a fresh nomination after a campaign handoff.
    """
    from certification.lifecycle_identity import parsed,scope
    protected=set();retired_positions=[];terminal_candidates=set()
    campaign=scope(window);position_scope=dict(campaign=campaign['campaign'],through=campaign['index'])
    for key,raw in db.execute('SELECT key,body FROM runtime').fetchall():
        value=json.loads(raw)
        if key=='pons_cohort':
            # Re-entry and recovery references are removed only by the native
            # current-Pons archival proof, never guessed by this shared owner.
            result=value.get('result',{})
            protected.update(r['curve'].lower() for kind in ('qualifiers','lifecycles')
                for r in result.get(kind,[]) if r.get('curve'))
            for kind in ('qualifiers','lifecycles'):
                name=result.get('native_archive_paths',{}).get(kind)
                if name:
                    path=files/'pons'/name
                    if Path(name).is_absolute() or '..' in Path(name).parts:
                        raise ValueError('robinhood_controller_path')
                    if path.exists():
                        for line in path.read_text().splitlines():
                            row=json.loads(line)
                            if row.get('curve'):protected.add(row['curve'].lower())
        if not key.startswith('native_position:'):continue
        p=value['position'];issued=parsed(p['id']);lane=value['provenance']['lane']
        eligible=(p['status']=='settled' and issued and issued['campaign']==position_scope['campaign']
                  and issued['index']<=position_scope['through'])
        locator=Path(value['provenance']['native_ledger'])
        if eligible and not locator.is_absolute() and '..' not in locator.parts:
            source=artifact/('certification-native/'+snapshot['phase'])/lane/locator
            if source not in inventory:raise ValueError('robinhood_terminal_projection_not_preserved')
            table={'pons':'pons_selective_paper','ramses':'ramses_strategy_position'}[lane]
            with closing(sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True)) as native:
                row=native.execute('SELECT body FROM '+table+' WHERE id=?',(p['id'],)).fetchone()
            if row is None or json.loads(row[0])!=p:raise ValueError('robinhood_terminal_projection_changed')
            # Native controllers are authoritative. An unresolved controller
            # sidecar or safety intent keeps the projection hot.
            safety=db.execute('SELECT body FROM runtime WHERE key=?',('position_safety:'+p['id'],)).fetchone()
            if safety:protected.add(value['candidate']);continue
            retired_positions.append(key)
            terminal_candidates.add(value['candidate'])
        else:protected.add(value['candidate'])
    rows=[dict(r) for r in db.execute('SELECT * FROM candidates')]
    frontier={lane:max(tuple(json.loads(r['ordering'])) for r in rows if r['lane']==lane)
              for lane in {r['lane'] for r in rows}}
    floors=dict(old.get('retired_ordering',{}));retired=[]
    for row in rows:
        key=row['id'];order=tuple(json.loads(row['ordering']))
        if (key in protected or key.rsplit(':',1)[-1].lower() in protected or row['pending']
                or row['claim'] or order>=frontier[row['lane']]):continue
        if row['state'] not in ('canonical_evidence_complete','strategy_rejected','structural_excluded','settled','entry_cancelled') and key not in terminal_candidates:continue
        if not db.execute('SELECT 1 FROM result_consumption WHERE candidate=? AND generation=?',
                          (key,row['generation'])).fetchone() and row['state'] not in ('strategy_rejected','structural_excluded'):continue
        retired.append(key)
        floors[row['lane']]=list(max(tuple(floors.get(row['lane'],[])),order))
    for key in retired_positions:db.execute('DELETE FROM runtime WHERE key=?',(key,))
    for key in retired:
        db.execute('DELETE FROM candidates WHERE id=?',(key,))
        db.execute('DELETE FROM observation_archive WHERE candidate=?',(key,))
    return dict(retired_ordering=floors,retired_position_scope=position_scope,
                retired_candidates=len(retired),retired_candidate_hash=digest(retired),
                retired_positions=len(retired_positions),retired_projection_hash=digest(retired_positions))


def externalize(destination,artifact,window):
    from certification.autonomous_window import verify_snapshot
    files=Path(destination)/'files';path=files/'shared/shared-robinhood-evidence.candidates.sqlite'
    with closing(sqlite3.connect(path)) as probe:
        if not probe.execute("SELECT 1 FROM sqlite_master WHERE name='candidates'").fetchone():return None
    snapshot=verify_snapshot(artifact);artifact=Path(artifact)
    phase=snapshot['phase'];shared=artifact/('certification-'+phase)/path.name
    inventory={artifact/r['target'] for r in snapshot['files'] if 'target' in r}
    _preserved(path,shared,inventory)
    with closing(sqlite3.connect(path)) as db:
        db.row_factory=sqlite3.Row
        raw=db.execute("SELECT body FROM runtime WHERE key='window_history_archive'").fetchone()
        old=json.loads(raw[0]) if raw else {}
        if old and (old.get('schema')!='robinhood-window-history-v1'
                or old.get('chain_hash')!=digest({k:v for k,v in old.items() if k!='chain_hash'})):
            raise ValueError('robinhood_history_archive_corruption')
        sources=dict(old.get('projection_sources',{}));pipelines=[]
        high=max(old.get('transition_high_water',0),db.execute('SELECT COALESCE(MAX(seq),0) FROM transitions').fetchone()[0])
        for lane in ('pons','ramses'):
            first=db.execute('SELECT t.* FROM transitions t JOIN candidates c ON c.id=t.candidate WHERE c.lane=? ORDER BY t.seq LIMIT 1',(lane,)).fetchone()
            if first and lane not in sources:
                sources[lane]='candidate-plane:'+hashlib.sha256(json.dumps(dict(first),sort_keys=True).encode()).hexdigest()
            matches=sorted(set((files/lane).rglob('*.pipeline.sqlite')) | set((files/lane).rglob('opportunity-pipeline.sqlite')))
            if len(matches)>1 or (first and not matches):raise ValueError('robinhood_history_pipeline_missing')
            if not matches:continue
            pipeline=matches[0]
            _preserved(pipeline,artifact/('certification-native/'+phase)/pipeline.relative_to(files),inventory)
            if lane=='pons':
                proof=consistency(path,pipeline,lane)
                if proof['status']!='pass':raise ValueError('robinhood_history_accounting_unreconciled')
            with closing(sqlite3.connect(pipeline)) as p:
                rows=[dict(candidate=c,stage=s,classification=k,details=json.loads(d))
                      for c,s,k,d in p.execute('SELECT candidate,stage,classification,details FROM progress ORDER BY sequence')]
                from certification.evidence_obligations import summarize
                obligations=summarize(rows)
                if obligations.get('pending_at_observation_close'):raise ValueError('robinhood_history_unresolved_obligation')
                source=sources.get(lane) if lane=='pons' else None
                last=db.execute('SELECT COALESCE(MAX(t.seq),0) FROM transitions t JOIN candidates c ON c.id=t.candidate WHERE c.lane=?',(lane,)).fetchone()[0]
                if last and lane=='pons':
                    acknowledged=p.execute('SELECT COALESCE(MAX(sequence),0) FROM progress_sources WHERE source=?',(source,)).fetchone()[0]
                    if acknowledged<last:
                        unprojected=list(db.execute('SELECT t.kind,t.details FROM transitions t JOIN candidates c ON c.id=t.candidate WHERE c.lane=? AND t.seq>?',(lane,acknowledged)))
                        if phase!='position' or any(kind not in ('position_safety','settled')
                                or json.loads(details).get('authority')!='native_paper_ledger'
                                or not json.loads(details).get('position_digest') for kind,details in unprojected):
                            raise ValueError('robinhood_history_projection_incomplete')
                summary=dict(lane=lane,raw_records=len(rows),obligations=obligations,
                    classes={k:n for k,n in p.execute('SELECT classification,COUNT(DISTINCT candidate) FROM progress WHERE classification IS NOT NULL GROUP BY classification')})
                pipelines.append((pipeline,source,last,summary))
        counts={table:db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
                for table in ('observations','transitions','evidence','result_consumption','rolling')}
        proof=dict(schema='robinhood-window-history-v1',window=window,preserved_snapshot_hash=digest(snapshot),
            previous=old.get('chain_hash'),windows=old.get('windows',0)+1,
            reporting_scope='current_window; exact prior decisions remain in verified native artifacts',
            projection_sources=sources,transition_high_water=high,pipelines=[p[3] for p in pipelines],
            before=counts)
        with db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS observation_archive(candidate TEXT PRIMARY KEY,ordering TEXT NOT NULL)')
            db.execute('INSERT OR REPLACE INTO observation_archive SELECT id,ordering FROM candidates')
            proof.update(_retire_identities(db,files,artifact,snapshot,window,inventory,old))
            _erase(db,'observations','observations_no_delete',
                ' WHERE NOT EXISTS(SELECT 1 FROM candidates c WHERE c.id=observations.candidate AND c.latest_id=observations.observation)')
            _erase(db,'transitions','history_no_delete')
            db.execute('DELETE FROM result_consumption WHERE NOT EXISTS(SELECT 1 FROM candidates c WHERE c.id=result_consumption.candidate AND c.generation=result_consumption.generation)')
            # Per-candidate rolling eviction cannot retire keys for candidates
            # that never update again. Their exact normalized rows are already
            # in the verified immutable predecessor. This is a cache, never a
            # cursor, position or continuity authority: misses use the same
            # receipt/header-authenticated builder, with unchanged limits.
            db.execute('DELETE FROM rolling')
            # Cache misses still require the original authenticated provider path.
            for namespace, in db.execute('SELECT DISTINCT namespace FROM evidence').fetchall():
                limit=CACHE_LIMITS.get(namespace.rsplit(':',1)[-1])
                if namespace.startswith('ramses_pool_metadata:'):limit=CACHE_LIMITS['launch']
                if limit is not None:
                    db.execute('DELETE FROM evidence WHERE namespace=? AND key NOT IN (SELECT key FROM evidence WHERE namespace=? ORDER BY created DESC,key DESC LIMIT ?)',(namespace,namespace,limit))
                elif namespace=='ramses_route_v1':
                    # Exact-frontier route quotes are reauthenticated each window.
                    db.execute('DELETE FROM evidence WHERE namespace=?',(namespace,))
            proof['after']={table:db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for table in counts}
            proof['chain_hash']=digest(proof)
            db.execute('INSERT OR REPLACE INTO runtime VALUES(?,?)',('window_history_archive',canonical(proof)))
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('robinhood_history_integrity')
    for path,source,last,summary in pipelines:
        with closing(sqlite3.connect(path)) as db:
            with db:
                db.execute('BEGIN IMMEDIATE')
                _erase(db,'progress','progress_no_delete')
                # One high-water receipt retains the existing projection source.
                if db.execute("SELECT 1 FROM sqlite_master WHERE name='progress_sources'").fetchone():
                    db.execute('DELETE FROM progress_sources')
                if source and last:db.execute('INSERT INTO progress_sources VALUES(?,?)',(source,last))
                db.execute('CREATE TABLE IF NOT EXISTS window_history_archive(id INTEGER PRIMARY KEY CHECK(id=1),body TEXT NOT NULL)')
                db.execute('INSERT OR REPLACE INTO window_history_archive VALUES(1,?)',(canonical(dict(chain_hash=proof['chain_hash'],summary=summary)),))
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('robinhood_pipeline_archive_integrity')
    return proof
