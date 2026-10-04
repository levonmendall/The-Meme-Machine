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
from meme_machine.runtime.journal import canonical,digest


class History:
    def __init__(self,path,*,policy,maximum_candidates=64,maximum_points=100000):
        self.path=Path(path)
        self.initial_file_sha256=None
        if self.path.is_file():
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
        self.initial_changes=self.db.total_changes
        self.initial_data_version=self.db.execute('PRAGMA data_version').fetchone()[0]

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
        if self.expired(evidence):raise ValueError('survivor_graduation_expired')
        if len(self.rows())>=self.maximum_candidates:
            raise ValueError('survivor_candidate_capacity')
        row=dict(id=identity,graduation=evidence,state='graduated',through=evidence['at'],
                 complete=True,last_checked=0,position=None)
        self.save(row);return row

    def expired(self,evidence):
        floor=self.get_meta('graduation_floor')
        return floor is not None and evidence['at']<floor

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
        # The operational caller owns this history connection. Every removed
        # point is verified and folded under the same transaction below.
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
            floor=self.get_meta('graduation_floor')
            if floor is not None:
                removed=hashlib.sha256();count=0
                for body,checksum in self.db.execute("""SELECT body,hash FROM candidates
                        WHERE json_extract(body,'$.state')='retired'
                        AND json_extract(body,'$.graduation.at')<? ORDER BY id""",(floor,)):
                    row=self._verified((body,checksum));identity=row['id']
                    if row.get('position'):raise ValueError('survivor_open_position_retirement')
                    prefix=self.get_meta('archive_prefix:'+identity)
                    removed.update((canonical(dict(candidate=row,prefix=prefix))+'\n').encode())
                    count+=1
                    self.db.execute('DELETE FROM candidates WHERE id=?',(identity,))
                    self.db.execute('DELETE FROM meta WHERE key=?',('archive_prefix:'+identity,))
                if count:
                    previous=self.get_meta('retired_archive')
                    self.set_meta('retired_archive',dict(schema='survivor-retired-prefix-v1',
                        graduation_floor=floor,removed_count=count,removed_hash=removed.hexdigest(),
                        total_count=count+(previous['total_count'] if previous else 0),
                        previous_prefix_hash=digest(previous) if previous else None,authority=authority))
        self.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        return True

    def rows(self,*,include_retired=False):
        # Tombstones preserve identity but never enter the monitoring hot set.
        sql='SELECT body,hash FROM candidates'
        if not include_retired:sql+=" WHERE json_extract(body,'$.state')!='retired'"
        rows=[self._verified(row) for row in self.db.execute(sql)]
        return sorted(rows,key=lambda r:(r['last_checked'],r['id']))

    def retire(self,row,*,expired_before=None):
        if row.get('position'):raise ValueError('survivor_open_position_retirement')
        if expired_before is not None and row['graduation']['at']>=expired_before:
            raise ValueError('survivor_retirement_age')
        with self.transaction():
            if expired_before is not None:
                previous=self.get_meta('graduation_floor')
                self.set_meta('graduation_floor',max(expired_before,previous) if previous is not None else expired_before)
            row=dict(id=row['id'],graduation=row['graduation'],state='retired',last_checked=row['last_checked'],position=None)
            self.save(row)
            self.db.execute('DELETE FROM points WHERE candidate=?',(row['id'],))
            self.db.execute('DELETE FROM events WHERE candidate=?',(row['id'],))

    def close(self):self.db.close()


def compact_restored_history(history,*,lane,reducer=None):
    from meme_machine.runtime.preserved_checkpoint import history_authority
    return history.compact_archived(history_authority(history,lane),reducer=reducer)


class Worker:
    """One bounded task at a time; never blocks fast native decision scheduling."""
    def __init__(self,factory):
        from concurrent.futures import ThreadPoolExecutor
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='survivor')
        self.factory=factory;self.service=None;self.future=None;self.last=0;self.status={}
        self.completed_steps=0;self.successful_steps=0;self.admission_enabled_steps=0
        self.closed=False;self.close_future=None

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

    def prime(self,*,timeout=30):
        """Initialize and reconcile on the owned executor, with a bounded wait."""
        if self.closed:raise RuntimeError('survivor_worker_closed')
        if self.future is None:self.future=self.pool.submit(self._step,False)
        self.status=self.future.result(timeout=timeout)
        self.future=None
        return self.status

    def tick(self,now,*,admit=True):
        if self.closed:raise RuntimeError('survivor_worker_closed')
        if self.future is not None:
            if not self.future.done():return self.status
            self.status=self.future.result();self.future=None
        if now-self.last>=5:
            self.last=now;self.future=self.pool.submit(self._step,admit)
        return self.status

    def _close_owned_service(self):
        # Queued behind the accepted step on the same executor. SQLite is never
        # closed from the supervisor thread, including after a timed-out prime.
        try:
            if self.future is not None:self.status=self.future.result()
        finally:
            if self.service is not None:self.service.close()
        return self.status

    def close(self,*,timeout=5):
        """Bound caller drain; the supervisor owns process termination deadlines.

        A timed-out transport may still finish on its owner thread. Do not close
        its connection concurrently or report a durable step as cancelled. The
        one queued close runs after it; native journals remain restart authority.
        """
        if timeout<0:raise ValueError('survivor_close_timeout')
        if self.close_future is None:
            self.closed=True
            self.close_future=self.pool.submit(self._close_owned_service)
            self.pool.shutdown(wait=False)
        return self.close_future.result(timeout=timeout)
