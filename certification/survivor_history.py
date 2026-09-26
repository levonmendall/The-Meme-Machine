"""Bounded incremental, authenticated Survivor observations and lifecycle state.

No provider client, backfill, inferred gaps, or portfolio authority. Graduation
identity is immutable. Missing continuity is a sticky entry block until a new
authenticated graduation identity, rather than a manufactured historical value.
"""
import json
import sqlite3
from contextlib import contextmanager
from certification.journal import canonical,digest


class History:
    def __init__(self,path,*,policy,maximum_candidates=64,maximum_points=100000):
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
        self.set_meta('policy',policy)

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

    def append(self,identity,*,through,events,points,complete):
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
            for at,price in points:
                if at>through:raise ValueError('survivor_future_price')
                # Native adapter deterministically chooses the final chain-ordered
                # state in a second; a later watermark may complete that second.
                body=[identity,int(at),str(price)]
                self.db.execute('INSERT OR REPLACE INTO points VALUES(?,?,?,?)',(*body,digest(body)))
            if self.db.execute('SELECT count(*) FROM points WHERE candidate=?',(identity,)).fetchone()[0]>self.maximum_points:
                raise ValueError('survivor_history_point_capacity')
            self.db.execute('DELETE FROM events WHERE candidate=? AND at<?',(identity,through-3600))
            row['through']=through;self.save(row)
            return row

    def facts(self,identity,now):
        events=[self._verified(r) for r in self.db.execute('SELECT body,hash FROM events WHERE candidate=? AND at<=? ORDER BY at,id',(identity,now))]
        points=[]
        for at,price,h in self.db.execute('SELECT at,price,hash FROM points WHERE candidate=? AND at<=? ORDER BY at',(identity,now)):
            if digest([identity,at,price])!=h:raise ValueError('survivor_price_corruption')
            points.append(dict(at=at,price=price))
        return points,events

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


class Worker:
    """One bounded task at a time; never blocks fast native decision scheduling."""
    def __init__(self,factory):
        from concurrent.futures import ThreadPoolExecutor
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='survivor')
        self.factory=factory;self.service=None;self.future=None;self.last=0;self.status={}

    def _step(self,admit):
        if self.service is None:self.service=self.factory()
        return self.service.step(admit=admit)

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
