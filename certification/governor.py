"""Cross-process physical-request governor used only by certification.

A conservative shared ceiling; it never increases a lane's existing local rate.
Priority-zero position work outranks discovery. Backoff is shared by endpoint.
"""
from contextlib import closing
from pathlib import Path
import sqlite3
import time
import uuid

class Governor:
    def __init__(self,path,*,interval=.5):
        if interval<.5:raise ValueError('certification_rate_increase_forbidden')
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        self.path=str(path);self.interval=interval
        with closing(sqlite3.connect(self.path,timeout=30,isolation_level=None)) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''CREATE TABLE IF NOT EXISTS pressure(
                provider TEXT PRIMARY KEY,next_at REAL NOT NULL,cooldown REAL NOT NULL,grants INTEGER NOT NULL,rate_errors INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS queue(
                id TEXT PRIMARY KEY,provider TEXT NOT NULL,lane TEXT NOT NULL,priority INTEGER NOT NULL,created REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS priority_queue ON queue(provider,priority,created);
                CREATE TABLE IF NOT EXISTS grants(id INTEGER PRIMARY KEY,provider TEXT,lane TEXT,priority INTEGER,
                    requested REAL,ended REAL,wait REAL,granted INTEGER,reason TEXT);
                CREATE TABLE IF NOT EXISTS method_pressure(
                    provider TEXT NOT NULL,method TEXT NOT NULL,cooldown REAL NOT NULL,
                    rate_errors INTEGER NOT NULL,rate_streak INTEGER NOT NULL,
                    success_streak INTEGER NOT NULL,PRIMARY KEY(provider,method));
                CREATE TRIGGER IF NOT EXISTS grants_no_delete BEFORE DELETE ON grants BEGIN SELECT RAISE(ABORT,'append_only'); END;
                CREATE TRIGGER IF NOT EXISTS grants_no_update BEFORE UPDATE ON grants BEGIN SELECT RAISE(ABORT,'append_only'); END;''')
            if 'deadline' not in {r[1] for r in db.execute('PRAGMA table_info(queue)')}:
                db.execute('ALTER TABLE queue ADD COLUMN deadline REAL')

    @staticmethod
    def _methods(methods):
        return tuple(dict.fromkeys(str(x) for x in (methods or ()) if x))

    @staticmethod
    def _method_backoff(method,streak):
        streak=max(1,int(streak))
        if method=='getProgramAccounts':
            return min(60.0,30.0*(2**min(streak-1,1)))
        if method=='getSignaturesForAddress':
            return min(60.0,15.0*(2**min(streak-1,2)))
        return min(30.0,8.0*(2**min(streak-1,2)))

    def acquire(self,provider,lane,priority=50,*,deadline_seconds=30,methods=()):
        if not 0<deadline_seconds<=30:raise ValueError('provider_deadline_bound')
        methods=self._methods(methods)
        identity=str(uuid.uuid4());started=time.monotonic()
        db=sqlite3.connect(self.path,timeout=30,isolation_level=None)
        granted=False;reason='queue_deadline'
        try:
            db.execute('INSERT OR IGNORE INTO pressure VALUES(?,0,0,0,0)',(provider,))
            for method in methods:
                db.execute('INSERT OR IGNORE INTO method_pressure VALUES(?,?,0,0,0,0)',
                           (provider,method))
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM queue WHERE created<=?',(started-30,))
            if db.execute('SELECT COUNT(*) FROM queue WHERE provider=?',(provider,)).fetchone()[0]>=256:
                db.execute('ROLLBACK');raise TimeoutError('certification_provider_queue_capacity')
            db.execute('INSERT INTO queue(id,provider,lane,priority,created,deadline) VALUES(?,?,?,?,?,?)',(identity,provider,lane,priority,started,started+deadline_seconds))
            db.execute('COMMIT')
            while True:
                now=time.monotonic()
                if now-started>deadline_seconds:raise TimeoutError('certification_provider_queue_deadline')
                db.execute('BEGIN IMMEDIATE')
                try:
                    db.execute('DELETE FROM queue WHERE created<=?',(now-30,))
                    head=self._head(db,provider,now)
                    next_at,cooldown=db.execute('SELECT next_at,cooldown FROM pressure WHERE provider=?',(provider,)).fetchone()
                    method_rows=(db.execute(
                        'SELECT method,cooldown FROM method_pressure WHERE provider=? AND method IN ('+
                        ','.join('?' for _ in methods)+')',
                        (provider,*methods)).fetchall() if methods else [])
                    method_cooldown=max((float(row[1]) for row in method_rows),default=0.0)
                    # Compact account scans have an unchanged fallback path.  Once
                    # this exact method proves rate-limited, do not hold a candidate
                    # behind a long cooldown or retry the same expensive request.
                    if (priority!=0 and any(m=='getProgramAccounts' and float(cd)>now
                                            for m,cd in method_rows)):
                        reason='method_cooldown'
                        db.execute('DELETE FROM queue WHERE id=?',(identity,))
                        db.execute('COMMIT')
                        raise TimeoutError('certification_provider_method_cooldown')
                    ready=max(float(next_at),float(cooldown),method_cooldown)
                    if head and head[0]==identity and now>=ready:
                        db.execute('UPDATE pressure SET next_at=?,grants=grants+1 WHERE provider=?',(now+self.interval,provider))
                        db.execute('DELETE FROM queue WHERE id=?',(identity,));db.execute('COMMIT')
                        granted=True;reason='granted'
                        return now-started
                    db.execute('COMMIT')
                except BaseException:
                    if db.in_transaction:db.execute('ROLLBACK')
                    raise
                time.sleep(min(.05,max(.005,ready-now)))
        finally:
            if db.in_transaction:db.execute('ROLLBACK')
            ended=time.monotonic()
            db.execute('INSERT INTO grants(provider,lane,priority,requested,ended,wait,granted,reason) VALUES(?,?,?,?,?,?,?,?)',(provider,lane,priority,started,ended,ended-started,int(granted),reason))
            db.execute('DELETE FROM queue WHERE id=?',(identity,));db.close()

    @staticmethod
    def _head(db,provider,now):
        # Positions always first. Foreground Pump/DLMM use one urgency class,
        # with a bounded aged grant so a continuous short-deadline lane cannot
        # suppress the other. Speculative work is never promoted over foreground.
        return db.execute("""SELECT id FROM queue WHERE provider=?
            ORDER BY CASE WHEN priority=0 THEN 0
                     WHEN priority BETWEEN 10 AND 30 AND created<=? THEN 5
                     WHEN priority BETWEEN 10 AND 30 THEN 10 ELSE priority END,
            CASE WHEN priority BETWEEN 10 AND 30 AND created<=? THEN created ELSE COALESCE(deadline,created+30) END,
            created,id LIMIT 1""",(provider,now-2,now-2)).fetchone()

    def rate_limited(self,provider,methods=()):
        methods=self._methods(methods);now=time.monotonic()
        with closing(sqlite3.connect(self.path,timeout=30,isolation_level=None)) as db:
            db.execute('INSERT OR IGNORE INTO pressure VALUES(?,0,0,0,0)',(provider,))
            db.execute('UPDATE pressure SET cooldown=MAX(cooldown,?),rate_errors=rate_errors+1 WHERE provider=?',(now+8,provider))
            for method in methods:
                row=db.execute('SELECT cooldown,rate_errors,rate_streak FROM method_pressure WHERE provider=? AND method=?',
                               (provider,method)).fetchone()
                old_cooldown,events,streak=(row if row else (0,0,0))
                streak=int(streak)+1
                delay=self._method_backoff(method,streak)
                db.execute('INSERT OR REPLACE INTO method_pressure VALUES(?,?,?,?,?,0)',
                           (provider,method,max(float(old_cooldown),now+delay),
                            int(events)+1,streak))

    def succeeded(self,provider,methods=()):
        methods=self._methods(methods)
        if not methods:return
        with closing(sqlite3.connect(self.path,timeout=30,isolation_level=None)) as db:
            for method in methods:
                row=db.execute('SELECT cooldown,rate_errors,rate_streak,success_streak FROM method_pressure WHERE provider=? AND method=?',
                               (provider,method)).fetchone()
                if not row or int(row[2])<=0:continue
                success=int(row[3])+1;streak=int(row[2])
                if success>=4:
                    streak=max(0,streak-1);success=0
                db.execute('UPDATE method_pressure SET rate_streak=?,success_streak=? WHERE provider=? AND method=?',
                           (streak,success,provider,method))

    def status(self):
        with closing(sqlite3.connect(self.path,timeout=30,isolation_level=None)) as db:
            now=time.monotonic()
            return dict(providers=[dict(provider=p,next_at=n,cooldown=c,grants=g,rate_errors=r) for p,n,c,g,r in db.execute('SELECT * FROM pressure')],
                        method_pressure=[dict(provider=p,method=m,cooldown_remaining_seconds=max(0,float(c)-now),
                            rate_errors=int(e),rate_streak=int(s),success_streak=int(ok))
                            for p,m,c,e,s,ok in db.execute('SELECT * FROM method_pressure')],
                        lane_grants=[dict(lane=l,requested=n,granted=g,deadline_misses=n-g,queue_wait_seconds=w,max_wait_seconds=m) for l,n,g,w,m in db.execute('SELECT lane,count(*),sum(granted),sum(wait),max(wait) FROM grants GROUP BY lane')],
                        queues=[dict(lane=l,priority=p,depth=n) for l,p,n in db.execute('SELECT lane,priority,count(*) FROM queue GROUP BY lane,priority')])
