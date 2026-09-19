"""Cross-process physical-request governor used only by certification.

A conservative shared ceiling; it never increases a lane's existing local rate.
Priority-zero position work outranks discovery. Backoff is shared by endpoint.
"""
import os
from pathlib import Path
import sqlite3
import time
import uuid

class Governor:
    def __init__(self,path,*,interval=.5):
        if interval<.5:raise ValueError('certification_rate_increase_forbidden')
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        self.path=str(path);self.interval=interval
        with sqlite3.connect(self.path,timeout=30) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''CREATE TABLE IF NOT EXISTS pressure(
                provider TEXT PRIMARY KEY,next_at REAL NOT NULL,cooldown REAL NOT NULL,grants INTEGER NOT NULL,rate_errors INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS queue(
                id TEXT PRIMARY KEY,provider TEXT NOT NULL,lane TEXT NOT NULL,priority INTEGER NOT NULL,created REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS priority_queue ON queue(provider,priority,created);''')

    def acquire(self,provider,lane,priority=50,*,deadline_seconds=30):
        identity=str(uuid.uuid4());started=time.monotonic()
        db=sqlite3.connect(self.path,timeout=30,isolation_level=None)
        try:
            db.execute('INSERT OR IGNORE INTO pressure VALUES(?,0,0,0,0)',(provider,))
            db.execute('INSERT INTO queue VALUES(?,?,?,?,?)',(identity,provider,lane,priority,time.monotonic()))
            while True:
                now=time.monotonic()
                if now-started>deadline_seconds:raise TimeoutError('certification_provider_queue_deadline')
                db.execute('BEGIN IMMEDIATE')
                try:
                    head=db.execute('SELECT id FROM queue WHERE provider=? ORDER BY priority,created,id LIMIT 1',(provider,)).fetchone()
                    next_at,cooldown=db.execute('SELECT next_at,cooldown FROM pressure WHERE provider=?',(provider,)).fetchone()
                    if head[0]==identity and now>=max(next_at,cooldown):
                        db.execute('UPDATE pressure SET next_at=?,grants=grants+1 WHERE provider=?',(now+self.interval,provider))
                        db.execute('DELETE FROM queue WHERE id=?',(identity,));db.execute('COMMIT')
                        return now-started
                    db.execute('COMMIT')
                except BaseException:
                    db.execute('ROLLBACK');raise
                time.sleep(min(.05,max(.005,max(next_at,cooldown)-now)))
        finally:
            db.execute('DELETE FROM queue WHERE id=?',(identity,));db.close()

    def rate_limited(self,provider):
        with sqlite3.connect(self.path,timeout=30) as db:
            db.execute('UPDATE pressure SET cooldown=MAX(cooldown,?),rate_errors=rate_errors+1 WHERE provider=?',(time.monotonic()+8,provider))

    def status(self):
        with sqlite3.connect(self.path,timeout=30) as db:
            return dict(providers=[dict(provider=p,next_at=n,cooldown=c,grants=g,rate_errors=r) for p,n,c,g,r in db.execute('SELECT * FROM pressure')],
                        queues=[dict(lane=l,priority=p,depth=n) for l,p,n in db.execute('SELECT lane,priority,count(*) FROM queue GROUP BY lane,priority')])
