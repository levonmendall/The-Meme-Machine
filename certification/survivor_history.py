"""Bounded incremental, authenticated Survivor observations and lifecycle state.

No provider client, backfill, inferred gaps, or portfolio authority. Graduation
identity is immutable. Missing continuity is a sticky entry block until a new
authenticated graduation identity, rather than a manufactured historical value.
"""
import json
import hashlib
import os
from pathlib import Path
import time
import sqlite3
from fractions import Fraction
from contextlib import contextmanager
from certification.journal import canonical,digest


class History:
    def __init__(self,path,*,policy,maximum_candidates=64,maximum_points=100000):
        self.path=Path(path)
        self.initial_file_sha256=None
        if (os.environ.get('MM_AUTONOMOUS_STATE_RECEIPT') or os.environ.get('MM_AUTONOMOUS_POSITION_STATE')) and self.path.is_file():
            with self.path.open('rb') as source:self.initial_file_sha256=hashlib.file_digest(source,'sha256').hexdigest()
        self.db=sqlite3.connect(path,isolation_level=None)
        self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,body TEXT NOT NULL,hash TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS candidates(id TEXT PRIMARY KEY,body TEXT NOT NULL,hash TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events(candidate TEXT,id TEXT,at INTEGER,body TEXT,hash TEXT,PRIMARY KEY(candidate,id));
        CREATE INDEX IF NOT EXISTS recent_events ON events(candidate,at);
        CREATE TABLE IF NOT EXISTS points(candidate TEXT,at INTEGER,price TEXT,hash TEXT,PRIMARY KEY(candidate,at));
        ''')
        self.maximum_candidates=maximum_candidates;self.maximum_points=maximum_points
        old=self.get_meta('policy')
        if old is not None and old!=policy:raise ValueError('survivor_history_policy_drift')
        if old is None:self.set_meta('policy',policy)

    @contextmanager
    def transaction(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK');raise

    def get_meta(self,key):
        row=self.db.execute('SELECT body,hash FROM meta WHERE key=?',(key,)).fetchone()
        return self._verified(row)

    def set_meta(self,key,value):
        self.db.execute('INSERT OR REPLACE INTO meta VALUES(?,?,?)',(key,canonical(value),digest(value)))

    def _verified(self,row):
        if row is None:return None
        value=json.loads(row[0])
        if digest(value)!=row[1]:raise ValueError('survivor_history_corruption')
        return value

    def get(self,identity):
        return self._verified(self.db.execute('SELECT body,hash FROM candidates WHERE id=?',(identity,)).fetchone())

    def save(self,row):
        self.db.execute('INSERT OR REPLACE INTO candidates VALUES(?,?,?)',(row['id'],canonical(row),digest(row)))

    def graduate(self,identity,evidence):
        old=self.get(identity)
        if old:
            if old['graduation']!=evidence:raise ValueError('conflicting_survivor_graduation')
            return old
        if len(self.rows())>=self.maximum_candidates:
            raise ValueError('survivor_candidate_capacity')
        row=dict(id=identity,graduation=evidence,state='graduated',through=evidence['at'],
                 complete=True,last_checked=0,position=None)
        self.save(row);return row

    def append(self,identity,*,through,events,points,complete,evidence_checkpoint=None):
        with self.transaction():
            row=self.get(identity)
            if row is None or through<row['through']:raise ValueError('survivor_history_watermark')
            if not complete:
                row['complete']=False;self.save(row);return row
            for event in events:
                if event.get('authenticated') is not True or event['at']>through:
                    raise ValueError('survivor_history_event_authority')
                old=self.db.execute('SELECT body,hash FROM events WHERE candidate=? AND id=?',(identity,event['id'])).fetchone()
                if old and self._verified(old)!=event:raise ValueError('survivor_history_event_conflict')
                self.db.execute('INSERT OR IGNORE INTO events VALUES(?,?,?,?,?)',
                    (identity,event['id'],event['at'],canonical(event),digest(event)))
            prefix=self.get_meta('archive_prefix:'+identity)
            for at,price in points:
                if at>through:raise ValueError('survivor_future_price')
                bar=dict(price) if isinstance(price,dict) else dict(price=str(price),low=str(price),high=str(price))
                old=self.db.execute('SELECT price,hash FROM points WHERE candidate=? AND at=?',(identity,int(at))).fetchone()
                if prefix and int(at)<=prefix['through']:
                    if not old or old[0]!=canonical(bar):raise ValueError('survivor_archived_price_rewrite')
                if old:
                    if digest([identity,int(at),old[0]])!=old[1]:raise ValueError('survivor_price_corruption')
                    prior=json.loads(old[0])
                    bar['low']=str(min(Fraction(bar['low']),Fraction(prior['low'])))
                    bar['high']=str(max(Fraction(bar['high']),Fraction(prior['high'])))
                if not 0<Fraction(bar['low'])<=Fraction(bar['price'])<=Fraction(bar['high']):
                    raise ValueError('survivor_price_range')
                body=[identity,int(at),canonical(bar)]
                self.db.execute('INSERT OR REPLACE INTO points VALUES(?,?,?,?)',(*body,digest(body)))
            if self.db.execute('SELECT count(*) FROM points WHERE candidate=?',(identity,)).fetchone()[0]>self.maximum_points:
                raise ValueError('survivor_history_point_capacity')
            self.db.execute('DELETE FROM events WHERE candidate=? AND at<?',(identity,through-3600))
            row['through']=through
            if evidence_checkpoint is not None:
                # Stored in the same FULL-sync transaction as the consumed rows.
                # An interrupted append can never authorize pin advancement.
                row['evidence_checkpoint']=evidence_checkpoint
            self.save(row)
            return row

    def facts(self,identity,now):
        prefix=self.get_meta('archive_prefix:'+identity)
        if prefix and now<prefix['through']:raise ValueError('survivor_archived_history_query')
        events=[self._verified(r) for r in self.db.execute('SELECT body,hash FROM events WHERE candidate=? AND at<=? ORDER BY at,id',(identity,now))]
        points=[]
        for at,price,h in self.db.execute('SELECT at,price,hash FROM points WHERE candidate=? AND at<=? ORDER BY at',(identity,now)):
            if digest([identity,at,price])!=h:raise ValueError('survivor_price_corruption')
            points.append(dict(at=at,**json.loads(price)))
        return points,events

    def prefix(self,identity):
        value=self.get_meta('archive_prefix:'+identity)
        return None if value is None else value['reducer_state']

    def compact_archived(self,authority,*,reducer=None):
        """Replace already-preserved old observations with exact sufficient state.

        All removed bytes remain in the verified predecessor artifact. One original
        graduation anchor and the boundary witness remain alongside the exact last
        24 hours; the unchanged 100,000-point guard still applies to new ingestion.
        """
        prior=authority['state_hash']
        if self.get_meta('compacted_from_state')==prior:return False
        if self.initial_file_sha256!=authority['history_sha256']:
            raise ValueError('survivor_history_archive_source_changed')
        with self.transaction():
            for row in self.rows():
                identity=row['id'];cut=row['through']-86400
                older=[]
                for at,price,checksum in self.db.execute(
                        'SELECT at,price,hash FROM points WHERE candidate=? AND at<=? ORDER BY at',(identity,cut)):
                    if digest([identity,at,price])!=checksum:raise ValueError('survivor_price_corruption')
                    older.append(dict(at=at,**json.loads(price)))
                if len(older)<3:continue
                previous=self.get_meta('archive_prefix:'+identity)
                before=None if previous is None else previous['reducer_state']
                folded=[p for p in older if previous is None or p['at']>previous['through']]
                state=None if reducer is None else reducer(folded,before)
                removed=older[1:-1]
                record=dict(schema='survivor-archived-prefix-v1',through=older[-1]['at'],
                    reducer_state=state,authority=authority,removed_count=len(removed),
                    removed_hash=digest(removed),previous_prefix_hash=None if previous is None else digest(previous))
                self.set_meta('archive_prefix:'+identity,record)
                self.db.execute('DELETE FROM points WHERE candidate=? AND at>? AND at<?',
                    (identity,older[0]['at'],older[-1]['at']))
            self.set_meta('compacted_from_state',prior)
        self.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        return True

    def rows(self,*,include_retired=False):
        # Tombstones preserve identity but never enter the monitoring hot set.
        sql='SELECT body,hash FROM candidates'
        if not include_retired:sql+=" WHERE json_extract(body,'$.state')!='retired'"
        rows=[self._verified(row) for row in self.db.execute(sql)]
        return sorted(rows,key=lambda r:(r['last_checked'],r['id']))

    def retire(self,row):
        if row.get('position'):raise ValueError('survivor_open_position_retirement')
        with self.transaction():
            row=dict(id=row['id'],graduation=row['graduation'],state='retired',last_checked=row['last_checked'],position=None)
            self.save(row)
            self.db.execute('DELETE FROM points WHERE candidate=?',(row['id'],))
            self.db.execute('DELETE FROM events WHERE candidate=?',(row['id'],))

    def close(self):self.db.close()


def compact_restored_history(history,*,lane,reducer=None):
    from certification.campaign_state import restored_window
    position=os.environ.get('MM_AUTONOMOUS_POSITION_STATE')
    if position:
        from certification.position_continuation import _runtime_identity
        _runtime_identity(position,lane)  # Exact no-entry claim and installed capsule.
        claim=json.loads((Path(position)/'autonomous-position-authority.json').read_text())
        receipt=json.loads((Path(position)/'certification-position/restored-campaign-state.json').read_text())
    else:
        claim=restored_window()
        if claim is None:return False
        receipt=json.loads(Path(os.environ['MM_AUTONOMOUS_STATE_RECEIPT']).read_text())
    name={'pump':'pump/pump-survivor/history.sqlite',
          'pons':'pons/pons-selective-continuation-v1-cohort/pons-survivor/history.sqlite'}[lane]
    expected=receipt.get('history_snapshots',{}).get(name)
    previous=claim['previous'];artifact=previous.get('artifact') or {}
    if (not expected or not isinstance(artifact.get('digest'),str)
            or not artifact['digest'].startswith('sha256:')):
        raise ValueError('survivor_history_archive_authority_missing')
    authority=dict(state_hash=receipt['state_hash'],history_sha256=expected,
        artifact=artifact,campaign_id=claim['campaign_id'],window_index=previous['index'])
    return history.compact_archived(authority,reducer=reducer)


class Worker:
    """One bounded task at a time; never blocks fast native decision scheduling."""
    def __init__(self,factory):
        from concurrent.futures import ThreadPoolExecutor
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='survivor')
        self.factory=factory;self.service=None;self.future=None;self.last=0;self.status={}
        self.completed_steps=0;self.successful_steps=0;self.admission_enabled_steps=0

    def _step(self,admit):
        if self.service is None:self.service=self.factory()
        status=self.service.step(admit=admit)
        self.completed_steps+=1
        if admit:self.admission_enabled_steps+=1
        if not status.get('last_boundary'):self.successful_steps+=1
        return dict(status,machinery=dict(completed_steps=self.completed_steps,
            successful_steps=self.successful_steps,allocation_authority=bool(admit),
            admission_enabled_steps=self.admission_enabled_steps,
            last_step_completed_at=time.time()))

    def tick(self,now,*,admit=True):
        if self.future is not None:
            if not self.future.done():return self.status
            self.status=self.future.result();self.future=None
        if now-self.last>=5:
            self.last=now;self.future=self.pool.submit(self._step,admit)
        return self.status

    def close(self):
        try:
            if self.future is not None:self.status=self.future.result()
        finally:
            try:
                if self.service is not None:self.pool.submit(self.service.close).result()
            finally:self.pool.shutdown(wait=True)
        return self.status
