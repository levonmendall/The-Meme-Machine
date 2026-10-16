"""Cross-process physical-request governor used only by meme_machine.runtime.

The hybrid Solana ceiling supports concurrent evidence work; lane-local pacers
and other providers retain their limits. Priority-zero position work outranks
discovery. Backoff is shared by endpoint.
"""
from contextlib import closing
from pathlib import Path
import hashlib
import json
import sqlite3
import os
import time
import uuid
from urllib.parse import quote
from .provider_clock import (ProviderClockError,bind_clock_domain,
                             inspect_clock_domain,validate_timer)
from .sqlite_failure import connect as diagnostic_connect,preserving_cleanup

class Governor:
    def __init__(self,path,*,interval=.5):
        if interval<.5:raise ValueError('operational_rate_increase_forbidden')
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        self.path=str(path);self.interval=interval
        # The authenticated hybrid plane shares one physical Solana clock across
        # candidates, continuation and positions. Other providers retain their
        # accepted conservative ceiling. This is observation capacity only.
        self.solana_interval=(.05 if os.environ.get('MM_SOLANA_EVIDENCE_PLANE_DB') else interval)
        # Explicit operational profiles override the old hybrid engineering
        # default. The bounded dispatch envelope promised two RPC starts/s.
        # Throughput advertised by the account is not a higher-rate proof.
        from meme_machine.operational.position_continuation import provider_interval
        operating_interval=provider_interval('solana')
        if operating_interval is not None:self.solana_interval=operating_interval
        with closing(diagnostic_connect(self.path,diagnostic_role='source_governor.initialize',timeout=30,isolation_level=None)) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('BEGIN IMMEDIATE')
            try:
                self._schema(db)
                self._clock(db)
                db.execute('COMMIT')
            except BaseException:
                if db.in_transaction:db.execute('ROLLBACK')
                raise

    @staticmethod
    def _schema(db):
        statements='''CREATE TABLE IF NOT EXISTS pressure(
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
                '''
        for statement in statements.split(';'):
            if statement.strip():db.execute(statement)
        for operation in ('delete','update'):
            db.execute('CREATE TRIGGER IF NOT EXISTS grants_no_'+operation+' BEFORE '+
                operation.upper()+" ON grants BEGIN SELECT RAISE(ABORT,'append_only'); END")
        if 'deadline' not in {r[1] for r in db.execute('PRAGMA table_info(queue)')}:
            db.execute('ALTER TABLE queue ADD COLUMN deadline REAL')

    @staticmethod
    def _validate_clock_state(db):
        for next_at,cooldown in db.execute('SELECT next_at,cooldown FROM pressure'):
            validate_timer(next_at);validate_timer(cooldown)
        for row in db.execute('SELECT cooldown FROM method_pressure'):
            validate_timer(row[0])
        for created,deadline in db.execute('SELECT created,deadline FROM queue'):
            validate_timer(created)
            if deadline is not None:
                if validate_timer(deadline)<created:
                    raise ProviderClockError('provider_clock_queue_invalid')

    @classmethod
    def _clock_snapshot(cls,db):
        cls._validate_clock_state(db)
        archive={}
        for table,bound in (('pressure',256),('method_pressure',1024),('queue',16384)):
            cursor=db.execute('SELECT * FROM '+table+' ORDER BY rowid LIMIT ?',(bound+1,))
            rows=cursor.fetchall()
            if len(rows)>bound:raise ProviderClockError('provider_clock_snapshot_bound')
            archive[table]=dict(columns=[column[0] for column in cursor.description],rows=rows)
        # Historical grants are retained in place. Hash the existing append-only
        # audit as a framed stream instead of bounding recovery by its population.
        cursor=db.execute('SELECT * FROM grants ORDER BY id')
        columns=[column[0] for column in cursor.description]
        digest=hashlib.sha256();count=0;first=last=None
        for row in cursor:
            encoded=json.dumps(row,separators=(',',':'),allow_nan=False).encode()
            digest.update(len(encoded).to_bytes(8,'big'));digest.update(encoded)
            count+=1
            if first is None:first=row[0]
            last=row[0]
        has_state=any(value['rows'] for value in archive.values()) or count>0
        archive['grants']=dict(columns=columns,row_count=count,first_id=first,last_id=last,
                               sha256=digest.hexdigest(),retained_in_place=True)
        return has_state,archive

    def _transition_quiet(self,db):
        delays=[self.solana_interval if provider=='solana' else self.interval
                for provider, in db.execute('SELECT provider FROM pressure')]
        if db.execute('SELECT 1 FROM pressure WHERE cooldown>0 LIMIT 1').fetchone():delays.append(8.0)
        delays.extend(self._method_backoff(method,100)
                      for method, in db.execute('SELECT method FROM method_pressure WHERE cooldown>0'))
        return max(delays,default=0.0)

    def _rebase_clock(self,db,now,quiet_until):
        # A zero backoff is an explicit absence of recorded policy debt. Keep
        # signature-only backoff local to that method, including across boots.
        for provider,cooldown in db.execute('SELECT provider,cooldown FROM pressure').fetchall():
            spacing=self.solana_interval if provider=='solana' else self.interval
            db.execute('UPDATE pressure SET next_at=?,cooldown=? WHERE provider=?',
                (now+spacing,now+8.0 if cooldown>0 else 0.0,provider))
        for provider,method,cooldown in db.execute(
                'SELECT provider,method,cooldown FROM method_pressure').fetchall():
            db.execute('UPDATE method_pressure SET cooldown=? WHERE provider=? AND method=?',
                (now+self._method_backoff(method,100) if cooldown>0 else 0.0,provider,method))
        # The old boot cannot deliver these tickets. The complete rows remain in
        # the append-only transition archive; historical grants are untouched.
        db.execute('DELETE FROM queue')

    def _clock(self,db,*,adoption_identity=None,clock=None):
        self._validate_clock_state(db)
        return bind_clock_domain(db,component='source_governor',
            clock=clock or time.monotonic,quiet_seconds=self._transition_quiet,
            snapshot=self._clock_snapshot,rebase=self._rebase_clock,
            adoption_identity=adoption_identity)

    @classmethod
    def adopt_legacy_clock(cls,path,*,audit_identity,clock=time.monotonic):
        """Adopt existing timers only under external stopped/no-inflight fences."""
        if audit_identity is None:
            raise ProviderClockError('provider_clock_adoption_identity_invalid')
        # Construction is intentionally bypassed: it must reject legacy state.
        obj=object.__new__(cls);obj.path=str(path);obj.interval=.5
        from meme_machine.operational.position_continuation import provider_interval
        configured=provider_interval('solana')
        obj.solana_interval=(configured if configured is not None else
            .05 if os.environ.get('MM_SOLANA_EVIDENCE_PLANE_DB') else .5)
        uri='file:'+quote(str(Path(path).absolute()),safe='/')+'?mode=rw'
        with closing(diagnostic_connect(uri,uri=True,diagnostic_role='source_governor.clock_adoption',
                timeout=30,isolation_level=None)) as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if not {'pressure','method_pressure','queue','grants'}<=tables:
                    raise ProviderClockError('provider_clock_schema_invalid')
                result=obj._clock(db,adoption_identity=audit_identity,clock=clock)
                db.execute('COMMIT');return result
            except BaseException:
                if db.in_transaction:db.execute('ROLLBACK')
                raise

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
        from .operating_families import require_active,active_scope_sql
        require_active(lane)
        live=active_scope_sql('lane')
        if not 0<deadline_seconds<=30:raise ValueError('provider_deadline_bound')
        methods=self._methods(methods)
        identity=str(uuid.uuid4());started=time.monotonic()
        db=diagnostic_connect(self.path,diagnostic_role='source_governor.acquire',timeout=30,isolation_level=None)
        granted=False;reason='queue_deadline'
        try:
            db.execute('BEGIN IMMEDIATE')
            self._clock(db)
            db.execute('INSERT OR IGNORE INTO pressure VALUES(?,0,0,0,0)',(provider,))
            for method in methods:
                db.execute('INSERT OR IGNORE INTO method_pressure VALUES(?,?,0,0,0,0)',
                           (provider,method))
            db.execute('DELETE FROM queue WHERE '+live+' AND created<=?',(started-30,))
            if db.execute('SELECT COUNT(*) FROM queue WHERE '+live+' AND provider=?',(provider,)).fetchone()[0]>=256:
                victim=(db.execute('SELECT id FROM queue WHERE '+live+' AND provider=? AND priority>=50 ORDER BY priority DESC,created DESC LIMIT 1',(provider,)).fetchone()
                        if provider=='solana' and priority in (0,1) else None)
                if victim:
                    db.execute('DELETE FROM queue WHERE id=?',victim)
                else:
                    reason='queue_capacity';db.execute('ROLLBACK');raise TimeoutError('operational_provider_queue_capacity')
            db.execute('INSERT INTO queue(id,provider,lane,priority,created,deadline) VALUES(?,?,?,?,?,?)',(identity,provider,lane,priority,started,started+deadline_seconds))
            db.execute('COMMIT')
            while True:
                now=time.monotonic()
                if now-started>deadline_seconds:raise TimeoutError('operational_provider_queue_deadline')
                db.execute('BEGIN IMMEDIATE')
                try:
                    now=self._clock(db)['now']
                    if now-started>deadline_seconds:
                        reason='queue_deadline'
                        raise TimeoutError('operational_provider_queue_deadline')
                    db.execute('DELETE FROM queue WHERE '+live+' AND created<=?',(now-30,))
                    if not db.execute('SELECT 1 FROM queue WHERE id=?',(identity,)).fetchone():
                        reason='background_preempted';db.execute('COMMIT')
                        raise TimeoutError('operational_background_preempted')
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
                        raise TimeoutError('operational_provider_method_cooldown')
                    ready=max(float(next_at),float(cooldown),method_cooldown)
                    reason=('shared_cooldown_backpressure' if max(float(cooldown),method_cooldown)>now
                            else 'physical_governor_wait')
                    if head and head[0]==identity and now>=ready:
                        db.execute('UPDATE pressure SET next_at=?,grants=grants+1 WHERE provider=?',(now+(self.solana_interval if provider=='solana' else self.interval),provider))
                        db.execute('DELETE FROM queue WHERE id=?',(identity,));db.execute('COMMIT')
                        granted=True;reason='granted'
                        return now-started
                    db.execute('COMMIT')
                except BaseException:
                    with preserving_cleanup():
                        if db.in_transaction:db.execute('ROLLBACK')
                    raise
                _stop_sleep(min(.05,max(.005,ready-now)))
        finally:
            try:
                with preserving_cleanup():
                    if db.in_transaction:db.execute('ROLLBACK')
                    ended=time.monotonic()
                    db.execute('INSERT INTO grants(provider,lane,priority,requested,ended,wait,granted,reason) VALUES(?,?,?,?,?,?,?,?)',(provider,lane,priority,started,ended,ended-started,int(granted),reason))
                    db.execute('DELETE FROM queue WHERE id=?',(identity,))
                    db.execute('DROP TRIGGER IF EXISTS grants_no_delete')
                    db.execute('DELETE FROM grants WHERE id < (SELECT COALESCE(MAX(id),0)-4096 FROM grants)')
            finally:db.close()

    @staticmethod
    def _head(db,provider,now):
        from .operating_families import active_scope_sql
        # Positions always first. Foreground Pump/DLMM use one urgency class,
        # with a bounded aged grant so a continuous short-deadline lane cannot
        # suppress the other. Speculative work is never promoted over foreground.
        return db.execute("""SELECT id FROM queue WHERE """+active_scope_sql('lane')+""" AND provider=?
            ORDER BY CASE WHEN priority=0 THEN 0
                     WHEN priority BETWEEN 10 AND 30 AND created<=? THEN 5
                     WHEN priority BETWEEN 10 AND 30 THEN 10 ELSE priority END,
            CASE WHEN priority BETWEEN 10 AND 30 AND created<=? THEN created ELSE COALESCE(deadline,created+30) END,
            created,id LIMIT 1""",(provider,now-2,now-2)).fetchone()

    def rate_limited(self,provider,methods=()):
        methods=self._methods(methods)
        with closing(diagnostic_connect(self.path,diagnostic_role='source_governor.rate_limited',timeout=30,isolation_level=None)) as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                now=self._clock(db)['now']
                self._rate_limited(db,provider,methods,now)
                db.execute('COMMIT')
            except BaseException:
                if db.in_transaction:db.execute('ROLLBACK')
                raise

    def _rate_limited(self,db,provider,methods,now):
            db.execute('INSERT OR IGNORE INTO pressure VALUES(?,0,0,0,0)',(provider,))
            # The accepted v10 hour showed all Solana rate errors isolated to
            # getSignaturesForAddress while unrelated methods remained healthy.
            # Preserve the physical request ceiling and the existing 15/30/60s
            # method backoff, but do not globally stall unrelated foreground reads
            # for a demonstrably method-scoped signature-history throttle.
            method_scoped_signature_limit=(methods==('getSignaturesForAddress',))
            if method_scoped_signature_limit:
                db.execute('UPDATE pressure SET rate_errors=rate_errors+1 WHERE provider=?',(provider,))
            else:
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
        with closing(diagnostic_connect(self.path,diagnostic_role='source_governor.succeeded',timeout=30,isolation_level=None)) as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                self._clock(db)
                self._succeeded(db,provider,methods)
                db.execute('COMMIT')
            except BaseException:
                if db.in_transaction:db.execute('ROLLBACK')
                raise

    @staticmethod
    def _succeeded(db,provider,methods):
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
        with closing(diagnostic_connect(self.path,diagnostic_role='source_governor.status',timeout=30,isolation_level=None)) as db:
            self._validate_clock_state(db)
            clock_domain=inspect_clock_domain(db,component='source_governor',clock=time.monotonic)
            now=clock_domain['now']
            return dict(clock_domain=clock_domain,
                        providers=[dict(provider=p,next_at=n,cooldown=c,grants=g,rate_errors=r) for p,n,c,g,r in db.execute('SELECT * FROM pressure')],
                        method_pressure=[dict(provider=p,method=m,cooldown_remaining_seconds=max(0,float(c)-now),
                            rate_errors=int(e),rate_streak=int(s),success_streak=int(ok))
                            for p,m,c,e,s,ok in db.execute('SELECT * FROM method_pressure')],
                        lane_grants=[dict(lane=l,requested=n,granted=g,deadline_misses=n-g,queue_wait_seconds=w,max_wait_seconds=m) for l,n,g,w,m in db.execute('SELECT lane,count(*),sum(granted),sum(wait),max(wait) FROM grants GROUP BY lane')],
                        queues=[dict(lane=l,priority=p,depth=n) for l,p,n in db.execute('SELECT lane,priority,count(*) FROM queue GROUP BY lane,priority')])


def _stop_sleep(seconds):
    from meme_machine.runtime.stop import sleep
    return sleep(seconds,sleeper=time.sleep)
