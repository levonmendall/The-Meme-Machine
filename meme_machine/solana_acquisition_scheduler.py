"""Bounded durable dispatch scheduling on the existing canonical owner.

The acquisition job remains the obligation. This additive queue carries no
coverage, completeness, financial, provider or lease authority. A caller must
still perform its original fresh dispatch checks and mark its in-flight claim
on the same owner. No job bounds, cursor, priority or deadline are rewritten.

Backfill and wake cursors are committed in the supplied writer transaction;
there is no volatile progress to advance before COMMIT. New pending jobs and
material job changes enter the ready queue through exact-id triggers, including
changes below a backfill cursor. A restart retains both unfinished backfill and
finite retry times. There is no global deferred-state reset.
"""
import math
import re

from .solana_evidence_plane import EvidenceUnavailable


DEFERRED = 'DEFERRED'
IDLE = 'IDLE'
STEP = 16
EXCLUSIONS = 8
FAMILIES = ('pump', 'pumpswap', 'meteora')
QUEUE = 'acquisition_schedule_ready_v1'
STATE = 'acquisition_schedule_state_v1'
URGENT_STATE = 'acquisition_schedule_urgent_v1'
FANOUT = 'acquisition_schedule_fanout_v1'
SIGNALS = 'acquisition_schedule_signals_v1'
URGENT_COUNT = 'acquisition_schedule_urgent_count_v1'
JOB_FIELDS = ('id', 'family', 'address', 'lo', 'hi', 'priority', 'deadline',
              'token', 'pages', 'last_slot', 'last_index', 'lineage', 'created',
              'updated', 'error')
MATERIAL_FIELDS = ('family', 'address', 'lo', 'hi', 'priority', 'deadline',
                   'token', 'pages', 'last_slot', 'last_index', 'lineage',
                   'created', 'error')


def _require(condition, code):
    if not condition:
        raise EvidenceUnavailable(code)


def _number(value):
    return type(value) in (int, float) and 0 <= value < 10**18 and math.isfinite(value)


def _step(limit):
    _require(type(limit) is int and 1 <= limit <= STEP,
             'acquisition_schedule_step')
    return limit


def _excluded(values):
    _require(not isinstance(values, (str, bytes, dict)),
             'acquisition_schedule_exclusions')
    result = set()
    for index, value in enumerate(values):
        _require(index < EXCLUSIONS and type(value) is str and
                 re.fullmatch('[0-9a-f]{64}', value) is not None,
                 'acquisition_schedule_exclusions')
        result.add(value)
    return result


class AcquisitionScheduler:
    """One canonical writer; finite indexed work for each scheduling step."""

    def __init__(self, history):
        self.history = history
        self.db = history.db
        self.writer = history.writer
        active = history.active_families
        _require(type(active) in (tuple, list, set, frozenset) and
                 len(active) <= len(FAMILIES) and all(f in FAMILIES for f in active),
                 'acquisition_schedule_families')
        self.families = tuple(f for f in FAMILIES if f in active)
        self._install()

    def _install(self):
        # execute(), rather than executescript(), preserves an enclosing owner
        # transaction. Index construction is installation work, never a poll.
        with self.writer.transaction():
            self._ddl(f'''CREATE TABLE IF NOT EXISTS {QUEUE}(
                id TEXT PRIMARY KEY,family TEXT NOT NULL,rank INTEGER NOT NULL,
                priority INTEGER NOT NULL,deadline REAL NOT NULL,created REAL NOT NULL,
                ready INTEGER NOT NULL CHECK(ready IN (0,1)),retry_at REAL NOT NULL,
                version INTEGER NOT NULL CHECK(version>0),dependency TEXT)''', 'table', QUEUE)
            self._ddl(f'''CREATE TABLE IF NOT EXISTS {STATE}(
                id INTEGER PRIMARY KEY CHECK(id=1),after_id TEXT NOT NULL,
                complete INTEGER NOT NULL CHECK(complete IN (0,1)),
                revision INTEGER NOT NULL CHECK(revision BETWEEN 0 AND 9223372036854775807),
                pending_count INTEGER NOT NULL CHECK(pending_count>=0))''',
                'table', STATE)
            if self.db.execute(f'SELECT 1 FROM {STATE} WHERE id=1').fetchone() is None:
                # One pre-live installation snapshot, including inactive
                # families. Polls and process restarts never recount the table.
                pending = self.db.execute(
                    "SELECT COUNT(*) FROM acquisition_jobs WHERE status='pending'").fetchone()[0]
                self.db.execute(f"INSERT INTO {STATE} VALUES(1,'',?,0,?)", (int(pending==0),pending))
            self._ddl(f'''CREATE TABLE IF NOT EXISTS {URGENT_STATE}(
                family TEXT NOT NULL,priority INTEGER NOT NULL,
                after_deadline REAL NOT NULL,after_created REAL NOT NULL,after_id TEXT NOT NULL,
                complete INTEGER NOT NULL CHECK(complete IN (0,1)),PRIMARY KEY(family,priority))''',
                'table', URGENT_STATE)
            empty=self.db.execute("SELECT 1 FROM acquisition_jobs WHERE status='pending' LIMIT 1").fetchone() is None
            for family in self.families:
                for priority in range(3):
                    self.db.execute(f"INSERT OR IGNORE INTO {URGENT_STATE} VALUES(?,?,-1,-1,'',?)",
                                    (family, priority,int(empty)))
            self._ddl('''CREATE INDEX IF NOT EXISTS acquisition_schedule_source_cursor_v1
                ON acquisition_jobs(status,id)''', 'index', 'acquisition_schedule_source_cursor_v1')
            self._ddl('''CREATE INDEX IF NOT EXISTS acquisition_schedule_source_urgent_v1
                ON acquisition_jobs(family,status,priority,deadline,created,id)''',
                'index', 'acquisition_schedule_source_urgent_v1')
            self._ddl(f'''CREATE INDEX IF NOT EXISTS acquisition_schedule_head_v1
                ON {QUEUE}(family,ready,rank,deadline,priority,created,id)''',
                'index', 'acquisition_schedule_head_v1')
            self._ddl(f'''CREATE INDEX IF NOT EXISTS acquisition_schedule_retry_v1
                ON {QUEUE}(ready,retry_at,id)''', 'index', 'acquisition_schedule_retry_v1')
            for suffix, predicate in (('urgent', 'rank<3'), ('optional', 'rank=3')):
                index = 'acquisition_schedule_retry_'+suffix+'_v1'
                self._ddl(f'''CREATE INDEX IF NOT EXISTS {index}
                    ON {QUEUE}(retry_at,id) WHERE ready=0 AND {predicate}''', 'index', index)
            for rank in range(4):
                index = 'acquisition_schedule_retry_rank'+str(rank)+'_v1'
                self._ddl(f'''CREATE INDEX IF NOT EXISTS {index}
                    ON {QUEUE}(retry_at,id) WHERE ready=0 AND rank={rank}''', 'index', index)
            self._install_urgent_count()
            self._install_fanout()
            insert = f'''UPDATE {STATE} SET revision=revision+1 WHERE id=1;
                INSERT INTO {QUEUE}
                (id,family,rank,priority,deadline,created,ready,retry_at,version,dependency)
                VALUES(NEW.id,NEW.family,CASE WHEN NEW.priority<=2 THEN NEW.priority ELSE 3 END,
                    NEW.priority,NEW.deadline,NEW.created,1,0,
                    (SELECT revision FROM {STATE} WHERE id=1),NULL)
                ON CONFLICT(id) DO UPDATE SET family=excluded.family,rank=excluded.rank,
                    priority=excluded.priority,deadline=excluded.deadline,created=excluded.created,
                    ready=1,retry_at=0,version=excluded.version,dependency=NULL;'''
            self._ddl(f'''CREATE TRIGGER IF NOT EXISTS acquisition_schedule_insert_v1
                AFTER INSERT ON acquisition_jobs WHEN NEW.status='pending'
                BEGIN {insert} END''', 'trigger', 'acquisition_schedule_insert_v1')
            changed = ' OR '.join('NEW.'+field+' IS NOT OLD.'+field
                                  for field in MATERIAL_FIELDS)
            self._ddl(f'''CREATE TRIGGER IF NOT EXISTS acquisition_schedule_update_v1
                AFTER UPDATE OF status,{','.join(MATERIAL_FIELDS)} ON acquisition_jobs
                WHEN NEW.status='pending' AND (OLD.status IS NOT NEW.status OR {changed})
                BEGIN {insert} END''', 'trigger', 'acquisition_schedule_update_v1')
            self._ddl(f'''CREATE TRIGGER IF NOT EXISTS acquisition_schedule_nonpending_v1
                AFTER UPDATE OF status ON acquisition_jobs WHEN NEW.status!='pending'
                BEGIN DELETE FROM {QUEUE} WHERE id=NEW.id; END''',
                'trigger', 'acquisition_schedule_nonpending_v1')
            self._ddl(f'''CREATE TRIGGER IF NOT EXISTS acquisition_schedule_delete_v1
                AFTER DELETE ON acquisition_jobs
                BEGIN DELETE FROM {QUEUE} WHERE id=OLD.id; END''',
                'trigger', 'acquisition_schedule_delete_v1')
            self._ddl(f'''CREATE TRIGGER IF NOT EXISTS acquisition_schedule_count_insert_v1
                AFTER INSERT ON acquisition_jobs WHEN NEW.status='pending'
                BEGIN UPDATE {STATE} SET pending_count=pending_count+1 WHERE id=1; END''',
                'trigger', 'acquisition_schedule_count_insert_v1')
            self._ddl(f'''CREATE TRIGGER IF NOT EXISTS acquisition_schedule_count_delete_v1
                AFTER DELETE ON acquisition_jobs WHEN OLD.status='pending'
                BEGIN UPDATE {STATE} SET pending_count=pending_count-1 WHERE id=1; END''',
                'trigger', 'acquisition_schedule_count_delete_v1')
            self._ddl(f'''CREATE TRIGGER IF NOT EXISTS acquisition_schedule_count_status_v1
                AFTER UPDATE OF status ON acquisition_jobs
                WHEN NEW.status IS NOT OLD.status AND (NEW.status='pending' OR OLD.status='pending')
                BEGIN UPDATE {STATE} SET pending_count=pending_count
                    +CASE WHEN NEW.status='pending' THEN 1 ELSE 0 END
                    -CASE WHEN OLD.status='pending' THEN 1 ELSE 0 END WHERE id=1; END''',
                'trigger', 'acquisition_schedule_count_status_v1')

    def _install_urgent_count(self):
        # This additive singleton has scheduling authority only: zero avoids
        # repeated empty urgent scans, never proves history or completion.
        # Only a genuinely new table may reconcile. An existing missing or
        # malformed row is a refusal, never an invented zero or silent repair.
        existed=self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (URGENT_COUNT,)).fetchone() is not None
        trigger_names=tuple('acquisition_schedule_urgent_count_'+kind+'_v1'
            for kind in ('insert','delete','update'))
        present=tuple(self.db.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND name=?",
            (name,)).fetchone() is not None for name in trigger_names)
        # A partial retained counter could have missed old-source writes while
        # one trigger was absent. Recreating that trigger cannot authenticate
        # its old zero. First install and all three triggers commit atomically.
        _require(all(present) if existed else not any(present),
            'acquisition_schedule_urgent_count_schema')
        self._ddl(f'''CREATE TABLE IF NOT EXISTS {URGENT_COUNT}(
            id INTEGER PRIMARY KEY CHECK(id=1),pending_urgent INTEGER NOT NULL
            CHECK(typeof(pending_urgent)='integer' AND pending_urgent>=0))''','table',URGENT_COUNT)
        if not existed:
            pending=self.db.execute("SELECT COUNT(*) FROM acquisition_jobs WHERE status='pending' AND priority<=2").fetchone()[0]
            self.db.execute(f'INSERT INTO {URGENT_COUNT} VALUES(1,?)',(pending,))
        self.urgent_pending_count()
        self._ddl(f'''CREATE TRIGGER IF NOT EXISTS acquisition_schedule_urgent_count_insert_v1
            AFTER INSERT ON acquisition_jobs WHEN NEW.status='pending' AND NEW.priority<=2
            BEGIN UPDATE {URGENT_COUNT} SET pending_urgent=pending_urgent+1 WHERE id=1; END''',
            'trigger','acquisition_schedule_urgent_count_insert_v1')
        self._ddl(f'''CREATE TRIGGER IF NOT EXISTS acquisition_schedule_urgent_count_delete_v1
            AFTER DELETE ON acquisition_jobs WHEN OLD.status='pending' AND OLD.priority<=2
            BEGIN UPDATE {URGENT_COUNT} SET pending_urgent=pending_urgent-1 WHERE id=1; END''',
            'trigger','acquisition_schedule_urgent_count_delete_v1')
        old="(OLD.status='pending' AND OLD.priority<=2)"
        new="(NEW.status='pending' AND NEW.priority<=2)"
        self._ddl(f'''CREATE TRIGGER IF NOT EXISTS acquisition_schedule_urgent_count_update_v1
            AFTER UPDATE OF status,priority ON acquisition_jobs WHEN {old} IS NOT {new}
            BEGIN UPDATE {URGENT_COUNT} SET pending_urgent=pending_urgent
                +CASE WHEN {new} THEN 1 ELSE 0 END-CASE WHEN {old} THEN 1 ELSE 0 END WHERE id=1; END''',
            'trigger','acquisition_schedule_urgent_count_update_v1')

    def urgent_pending_count(self):
        # All families and all pending deadlines count, including expired jobs
        # until their honest retirement. Inactive families are conservative:
        # they can retain the full urgent path, never manufacture empty work.
        row=self.db.execute(f'SELECT pending_urgent FROM {URGENT_COUNT} WHERE id=1').fetchone()
        _require(row is not None and len(row)==1 and type(row[0]) is int and row[0]>=0,
            'acquisition_schedule_urgent_count_unavailable')
        return row[0]

    def _install_fanout(self):
        # These are resumable scheduling dependencies, never coverage. Signals
        # touch one candidate key; waking its retained parents is indexed and
        # bounded below, rather than an unbounded trigger-side fanout update.
        self._ddl(f'''CREATE TABLE IF NOT EXISTS {FANOUT}(
            job_id TEXT PRIMARY KEY,job_version INTEGER NOT NULL,
            family TEXT NOT NULL,scope TEXT NOT NULL,after_slot INTEGER,
            waiting INTEGER NOT NULL CHECK(waiting IN (0,1)),observed_revision INTEGER NOT NULL)''',
            'table', FANOUT)
        self._ddl(f'''CREATE INDEX IF NOT EXISTS acquisition_schedule_fanout_wait_v1
            ON {FANOUT}(family,scope,waiting,job_id)''', 'index', 'acquisition_schedule_fanout_wait_v1')
        self._ddl(f'''CREATE TABLE IF NOT EXISTS {SIGNALS}(
            sequence INTEGER PRIMARY KEY,family TEXT NOT NULL,scope TEXT NOT NULL,
            revision INTEGER NOT NULL CHECK(revision>=0),dirty INTEGER NOT NULL CHECK(dirty IN (0,1)),
            scan_revision INTEGER NOT NULL,after_parent TEXT NOT NULL,UNIQUE(family,scope))''', 'table', SIGNALS)
        self._ddl(f'''CREATE INDEX IF NOT EXISTS acquisition_schedule_signals_dirty_v1
            ON {SIGNALS}(dirty,sequence)''', 'index', 'acquisition_schedule_signals_dirty_v1')
        self._ddl('''CREATE TABLE IF NOT EXISTS acquisition_schedule_signal_cursor_v1(
            id INTEGER PRIMARY KEY CHECK(id=1),after_sequence INTEGER NOT NULL)''',
            'table','acquisition_schedule_signal_cursor_v1')
        self.db.execute('INSERT OR IGNORE INTO acquisition_schedule_signal_cursor_v1 VALUES(1,0)')
        self._binding_signals = self.db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='evidence_bindings'").fetchone() is not None
        def notify(side, *, binding=False, fallback=False):
            scope=(side+'.coverage_scope' if binding else
                ("COALESCE((SELECT coverage_scope FROM evidence_bindings WHERE family="+side+".family AND address="+side+".address),"+
                 "'candidate:'||"+side+".family||':'||"+side+".address)" if self._binding_signals and not fallback else
                 "'candidate:'||"+side+".family||':'||"+side+".address"))
            return f'''INSERT INTO {SIGNALS}(family,scope,revision,dirty,scan_revision,after_parent)
                VALUES({side}.family,{scope},1,1,-1,'') ON CONFLICT(family,scope)
                DO UPDATE SET revision=revision+1,dirty=1;'''
        changed=' OR '.join('NEW.'+field+' IS NOT OLD.'+field for field in MATERIAL_FIELDS)
        for action in ('INSERT','UPDATE','DELETE'):
            sides=('OLD','NEW') if action=='UPDATE' else (('OLD',) if action=='DELETE' else ('NEW',))
            when=' WHEN OLD.status IS NOT NEW.status OR '+changed if action=='UPDATE' else ''
            event='UPDATE OF status,'+','.join(MATERIAL_FIELDS) if action=='UPDATE' else action
            # A move can signal the old and new key; duplicate notification of
            # an unchanged key is conservative and still fixed work.
            body=' '.join(notify(side) for side in sides)
            name='acquisition_schedule_signal_'+action.lower()+'_v1'
            self._ddl(f'''CREATE TRIGGER IF NOT EXISTS {name} AFTER {event} ON acquisition_jobs{when}
                BEGIN {body} END''','trigger',name)
        if self._binding_signals:
            for action in ('INSERT','UPDATE','DELETE'):
                sides=('OLD','NEW') if action=='UPDATE' else (('OLD',) if action=='DELETE' else ('NEW',))
                body=' '.join(notify(side,binding=canonical_scope,fallback=not canonical_scope)
                    for side in sides for canonical_scope in (True,False))
                name='acquisition_schedule_binding_signal_'+action.lower()+'_v1'
                self._ddl(f'''CREATE TRIGGER IF NOT EXISTS {name} AFTER {action} ON evidence_bindings
                    BEGIN {body} END''','trigger',name)
        self._ddl(f'''CREATE TRIGGER IF NOT EXISTS acquisition_schedule_fanout_nonpending_v1
            AFTER UPDATE OF status ON acquisition_jobs WHEN NEW.status!='pending'
            BEGIN DELETE FROM {FANOUT} WHERE job_id=NEW.id; END''',
            'trigger','acquisition_schedule_fanout_nonpending_v1')
        self._ddl(f'''CREATE TRIGGER IF NOT EXISTS acquisition_schedule_fanout_delete_v1
            AFTER DELETE ON acquisition_jobs BEGIN DELETE FROM {FANOUT} WHERE job_id=OLD.id; END''',
            'trigger','acquisition_schedule_fanout_delete_v1')

    def _scope(self, job):
        row=(self.db.execute('SELECT coverage_scope FROM evidence_bindings WHERE family=? AND address=?',
            (job['family'],job['address'])).fetchone() if self._binding_signals else None)
        return row[0] if row is not None else 'candidate:'+job['family']+':'+job['address']

    def _fanout_job(self, job):
        row=self.db.execute(f'''SELECT q.version FROM {QUEUE} q JOIN acquisition_jobs j ON j.id=q.id
            WHERE q.id=? AND j.status='pending' ''',(job['id'],)).fetchone()
        _require(row==(job.get('_scheduler_version'),), 'acquisition_schedule_fanout_stale')

    def fanout_after(self, job):
        with self.writer.transaction():
            return self._fanout_after(job)

    def _fanout_after(self, job):
        self._fanout_job(job)
        scope=self._scope(job)
        row=self.db.execute(f'SELECT job_version,after_slot,waiting,scope FROM {FANOUT} WHERE job_id=?',
            (job['id'],)).fetchone()
        if row is None or row[0]!=job['_scheduler_version'] or row[3]!=scope:
            self.db.execute(f'''INSERT INTO {FANOUT} VALUES(?,?,?,?,NULL,0,0)
                ON CONFLICT(job_id) DO UPDATE SET job_version=excluded.job_version,
                family=excluded.family,scope=excluded.scope,after_slot=NULL,waiting=0,observed_revision=0''',
                (job['id'],job['_scheduler_version'],job['family'],scope))
            return None
        return row[1]

    def fanout_advance(self, job, through):
        with self.writer.transaction():
            _require(type(through) is int and job['lo']<=through<=job['hi'], 'acquisition_schedule_fanout')
            after=self._fanout_after(job)
            _require(after is None or through>=after, 'acquisition_schedule_fanout_backwards')
            self.db.execute(f'''UPDATE {FANOUT} SET after_slot=?,waiting=0 WHERE job_id=? AND job_version=?''',
                (through,job['id'],job['_scheduler_version']))

    def fanout_wait(self, job):
        with self.writer.transaction():
            self._fanout_wait(job)

    def _fanout_wait(self, job):
        # Called AFTER this parent's child insertions in the same transaction.
        # Its own work therefore cannot wake it ahead of its new children.
        self._fanout_after(job)
        self.db.execute(f'''INSERT OR IGNORE INTO {SIGNALS}
            (family,scope,revision,dirty,scan_revision,after_parent) VALUES(?,?,0,0,-1,'')''',
            (job['family'],self._scope(job)))
        revision=self.db.execute(f'SELECT revision FROM {SIGNALS} WHERE family=? AND scope=?',
            (job['family'],self._scope(job))).fetchone()[0]
        self.db.execute(f'''UPDATE {FANOUT} SET after_slot=NULL,waiting=1,observed_revision=?
            WHERE job_id=? AND job_version=?''',(revision,job['id'],job['_scheduler_version']))
        self.defer(job,job['deadline'])

    def wake_fanout(self):
        with self.writer.transaction():
            self._wake_fanout()

    def _wake_fanout(self):
        after=self.db.execute('SELECT after_sequence FROM acquisition_schedule_signal_cursor_v1 WHERE id=1').fetchone()[0]
        row=self.db.execute(f'''SELECT sequence,family,scope,revision,scan_revision,after_parent
            FROM {SIGNALS} WHERE dirty=1 AND sequence>? ORDER BY sequence LIMIT 1''',(after,)).fetchone()
        if row is None:
            row=self.db.execute(f'''SELECT sequence,family,scope,revision,scan_revision,after_parent
                FROM {SIGNALS} WHERE dirty=1 ORDER BY sequence LIMIT 1''').fetchone()
        if row is None:return
        sequence,family,scope,revision,target,after_parent=row
        if target<0:target=revision
        rows=self.db.execute(f'''SELECT job_id,job_version,observed_revision FROM {FANOUT}
            INDEXED BY acquisition_schedule_fanout_wait_v1 WHERE family=? AND scope=?
            AND waiting=1 AND job_id>? ORDER BY job_id LIMIT ?''',
            (family,scope,after_parent,STEP)).fetchall()
        for identity,version,observed in rows:
            if observed<target:
                self.db.execute(f'''UPDATE {QUEUE} SET ready=1,retry_at=0,dependency=NULL
                    WHERE id=? AND version=?''',(identity,version))
                self.db.execute(f'''UPDATE {FANOUT} SET waiting=0,after_slot=NULL
                    WHERE job_id=? AND job_version=?''',(identity,version))
        if len(rows)<STEP:
            dirty=int(revision!=target)
            self.db.execute(f'''UPDATE {SIGNALS} SET dirty=?,scan_revision=-1,after_parent='' WHERE sequence=?''',
                (dirty,sequence))
        else:
            self.db.execute(f'''UPDATE {SIGNALS} SET scan_revision=?,after_parent=? WHERE sequence=?''',
                (target,rows[-1][0],sequence))
        self.db.execute('UPDATE acquisition_schedule_signal_cursor_v1 SET after_sequence=? WHERE id=1',(sequence,))

    def _ddl(self, statement, object_kind, name):
        self.db.execute(statement)
        # A pre-existing weaker trigger/index is not a resumable projection.
        # SQLite removes IF NOT EXISTS from the stored CREATE text.
        expected = statement.replace(' IF NOT EXISTS ', ' ', 1).strip()
        actual = self.db.execute('SELECT sql FROM sqlite_master WHERE type=? AND name=?',
                                 (object_kind, name)).fetchone()
        _require(actual == (expected,), 'acquisition_schedule_schema_mismatch')

    def _now(self):
        value = self.history.clock()
        _require(_number(value), 'acquisition_schedule_clock')
        return value

    def pending_count(self):
        """Exact all-family pending obligations, not a capped queue estimate."""
        row = self.db.execute(f'SELECT pending_count FROM {STATE} WHERE id=1').fetchone()
        _require(row is not None and type(row[0]) is int and row[0] >= 0,
                 'acquisition_schedule_pending_count')
        return row[0]

    def _ensure(self, job):
        # Preserve an existing deferral/version. Source triggers own refreshes.
        if self.db.execute(f'SELECT 1 FROM {QUEUE} WHERE id=?', (job['id'],)).fetchone():
            return
        self.db.execute(f'UPDATE {STATE} SET revision=revision+1 WHERE id=1')
        self.db.execute(f'''INSERT INTO {QUEUE}
            (id,family,rank,priority,deadline,created,ready,retry_at,version,dependency)
            VALUES(?,?,?,?,?,?,1,0,(SELECT revision FROM {STATE} WHERE id=1),NULL)''',
            (job['id'], job['family'], min(job['priority'], 3), job['priority'],
             job['deadline'], job['created']))

    def backfill(self, *, limit=STEP):
        """Seek at most sixteen retained pending ids; new writes use triggers."""
        limit = _step(limit)
        with self.writer.transaction():
            after, complete = self.db.execute(
                f'SELECT after_id,complete FROM {STATE} WHERE id=1').fetchone()
            if complete:
                return dict(complete=True, processed=0)
            rows = self.db.execute('''SELECT id,family,priority,deadline,created
                FROM acquisition_jobs INDEXED BY acquisition_schedule_source_cursor_v1
                WHERE status='pending' AND id>? ORDER BY id LIMIT ?''',
                (after, limit)).fetchall()
            for identity, family, priority, deadline, created in rows:
                self._ensure(dict(id=identity, family=family, priority=priority,
                                  deadline=deadline, created=created))
            complete = len(rows) < limit
            self.db.execute(f'UPDATE {STATE} SET after_id=?,complete=? WHERE id=1',
                            (rows[-1][0] if rows else after, int(complete)))
        return dict(complete=complete, processed=len(rows))

    def wake(self, *, limit=STEP, urgent=None):
        """Wake only a bounded indexed prefix of due deferrals, never all jobs."""
        limit = _step(limit)
        _require(urgent is None or type(urgent) is bool, 'acquisition_schedule_urgent')
        now = self._now()
        suffix = '' if urgent is None else ('_urgent' if urgent else '_optional')
        predicate = '' if urgent is None else (' AND rank<3' if urgent else ' AND rank=3')
        with self.writer.transaction():
            rows = self.db.execute(f'''SELECT id,version FROM {QUEUE}
                INDEXED BY acquisition_schedule_retry{suffix}_v1
                WHERE ready=0{predicate} AND retry_at<=? ORDER BY retry_at,id LIMIT ?''',
                (now, limit)).fetchall()
            for identity, version in rows:
                self.db.execute(f'''UPDATE {QUEUE} SET ready=1,retry_at=0,dependency=NULL
                    WHERE id=? AND version=? AND ready=0''', (identity, version))
            more = self.db.execute(f'''SELECT 1 FROM {QUEUE}
                INDEXED BY acquisition_schedule_retry{suffix}_v1
                WHERE ready=0{predicate} AND retry_at<=? ORDER BY retry_at,id LIMIT 1''',
                (now,)).fetchone() is not None
        return dict(processed=len(rows), more=more)

    def _wake_rank(self, rank, *, limit=STEP):
        """A fixed rank's retry bookkeeping cannot block a higher rank."""
        _require(type(rank) is int and 0 <= rank <= 3, 'acquisition_schedule_rank')
        limit = _step(limit)
        now = self._now()
        # rank is one of four internal literals, never external SQL.
        index = 'acquisition_schedule_retry_rank'+str(rank)+'_v1'
        with self.writer.transaction():
            rows = self.db.execute(f'''SELECT id,version FROM {QUEUE} INDEXED BY {index}
                WHERE ready=0 AND rank={rank} AND retry_at<=?
                ORDER BY retry_at,id LIMIT ?''', (now, limit)).fetchall()
            for identity, version in rows:
                self.db.execute(f'''UPDATE {QUEUE} SET ready=1,retry_at=0,dependency=NULL
                    WHERE id=? AND version=? AND ready=0''', (identity, version))
            more = self.db.execute(f'''SELECT 1 FROM {QUEUE} INDEXED BY {index}
                WHERE ready=0 AND rank={rank} AND retry_at<=?
                ORDER BY retry_at,id LIMIT 1''', (now,)).fetchone() is not None
        return dict(processed=len(rows), more=more)

    @staticmethod
    def _order(job):
        return (min(job['priority'], 3), job['deadline'], job['priority'],
                job['created'], job['id'])

    def _seed_urgent(self, *, limit=STEP):
        """Merge bounded ordered old urgent prefixes with trigger-fed heads.

        The returned frontier is the first unvisited old urgent key. A ready
        candidate preceding that frontier is globally ordered even while other
        old jobs remain unseeded. Deferred old rows are visited only once;
        subsequent selection honors their queue readiness rather than returning
        the same unready raw source head forever.
        """
        limit = _step(limit)
        now = self._now()
        with self.writer.transaction():
            heads = {}

            def advance(family, priority, after):
                row = self.db.execute('''SELECT id,family,priority,deadline,created
                    FROM acquisition_jobs INDEXED BY acquisition_schedule_source_urgent_v1
                    WHERE family=? AND status='pending' AND priority=? AND deadline>?
                        AND (deadline,created,id)>(?,?,?)
                    ORDER BY deadline,created,id LIMIT 1''',
                    (family, priority, now, *after)).fetchone()
                if row is None:
                    self.db.execute(f'''UPDATE {URGENT_STATE} SET complete=1
                        WHERE family=? AND priority=?''', (family, priority))
                    heads.pop((family, priority), None)
                else:
                    heads[family, priority] = dict(zip(
                        ('id', 'family', 'priority', 'deadline', 'created'), row))

            for family in self.families:
                for priority in range(3):
                    after_deadline, after_created, after_id, complete = self.db.execute(
                        f'''SELECT after_deadline,after_created,after_id,complete
                            FROM {URGENT_STATE} WHERE family=? AND priority=?''',
                        (family, priority)).fetchone()
                    if not complete:
                        advance(family, priority, (after_deadline, after_created, after_id))
            processed = 0
            while heads and processed < limit:
                selected = min(heads.values(), key=self._order)
                self._ensure(selected)
                after = (selected['deadline'], selected['created'], selected['id'])
                self.db.execute(f'''UPDATE {URGENT_STATE}
                    SET after_deadline=?,after_created=?,after_id=? WHERE family=? AND priority=?''',
                    (*after, selected['family'], selected['priority']))
                processed += 1
                advance(selected['family'], selected['priority'], after)
            frontier = min(heads.values(), key=self._order) if heads else None
        return dict(processed=processed, complete=frontier is None, frontier=frontier)

    def _queue_job(self, metadata, family, rank):
        identity, version, priority, deadline, created = metadata
        columns = ','.join(JOB_FIELDS)
        row = self.db.execute(f'''SELECT {columns},status
            FROM acquisition_jobs WHERE id=?''', (identity,)).fetchone()
        _require(row is not None, 'acquisition_schedule_projection_mismatch')
        job = dict(zip(JOB_FIELDS, row[:-1]))
        _require(row[-1] == 'pending' and job['family'] == family and
            (job['priority'], job['deadline'], job['created']) ==
            (priority, deadline, created) and min(job['priority'], 3) == rank,
            'acquisition_schedule_projection_mismatch')
        job['_scheduler_version'] = version
        return job

    def _ready_head(self, now, excluded, *, urgent, rank=None):
        found = []
        _require(rank is None or type(rank) is int and 0 <= rank <= 3,
                 'acquisition_schedule_rank')
        ranks = (rank,) if rank is not None else (range(3) if urgent else (3,))
        for rank in ranks:
            for family in self.families:
                rows = self.db.execute(f'''SELECT id,version,priority,deadline,created FROM {QUEUE}
                    INDEXED BY acquisition_schedule_head_v1
                    WHERE family=? AND ready=1 AND rank=? AND deadline>?
                    ORDER BY deadline,priority,created,id LIMIT ?''',
                    (family, rank, now, EXCLUSIONS+1)).fetchall()
                for metadata in rows:
                    # Bound the queue prefix before validating its authoritative
                    # source. A broken projection cannot make a filtering JOIN
                    # silently scan an unbounded stale prefix.
                    job = self._queue_job(metadata, family, rank)
                    if job['id'] not in excluded:
                        found.append(job)
                        break
            if urgent and found:
                break
        return min(found, key=self._order) if found else None

    def _optional_head(self, now, excluded):
        return self._ready_head(now, excluded, urgent=False)

    def _blocked_frontier(self, now, rank):
        """Conservative minimum remaining blocked key, without retry filtering.

        Looking at all blocked keys is intentionally conservative: no unbounded
        future-retry prefix is filtered while proving a ready head precedes the
        remaining due work. Each family contributes one indexed exact key.
        """
        found = []
        for family in self.families:
            metadata = self.db.execute(f'''SELECT id,version,priority,deadline,created
                FROM {QUEUE} INDEXED BY acquisition_schedule_head_v1
                WHERE family=? AND ready=0 AND rank=? AND deadline>?
                ORDER BY deadline,priority,created,id LIMIT 1''',
                (family, rank, now)).fetchone()
            if metadata is not None:
                found.append(self._queue_job(metadata, family, rank))
        return min(found, key=self._order) if found else None

    def _proved_head(self, head, now, rank, *, more_due, seed_frontier=None):
        if head is None:
            return False
        if seed_frontier is not None and self._order(head) > self._order(seed_frontier):
            return False
        if more_due:
            blocked = self._blocked_frontier(now, rank)
            if blocked is not None and self._order(head) >= self._order(blocked):
                return False
        return True

    def validate_clock(self):
        # Empty work still obeys the original finite/nonnegative owner clock
        # contract; absence of urgent jobs is not configuration authority.
        return self._now()

    def validate_selection(self, *, excluding=(), urgent=False):
        # Shared with the history zero shortcut so proven empty work cannot
        # turn malformed original controls into a successful IDLE result.
        _require(type(urgent) is bool, 'acquisition_schedule_urgent')
        return _excluded(excluding)

    def next(self, *, excluding=(), urgent=False):
        """Return one original fresh job, DEFERRED, or IDLE; never a proof.

        Urgent native obligations remain independently selectable during the
        bounded optional backfill. Optional work starts only after every old
        pending job has joined the same globally ordered ready population.
        """
        excluded=self.validate_selection(excluding=excluding,urgent=urgent)
        urgent_count=self.urgent_pending_count()
        if urgent and urgent_count==0:
            self.validate_clock()
            return IDLE
        if urgent_count:
            progress = self._seed_urgent()
            self.wake_fanout()
            remaining = STEP
            for rank in range(3):
                due = self._wake_rank(rank, limit=remaining)
                remaining -= due['processed']
                now = self._now()
                head = self._ready_head(now, excluded, urgent=True, rank=rank)
                frontier = progress['frontier']
                if self._proved_head(head, now, rank, more_due=due['more'], seed_frontier=frontier):
                    return head if head['deadline'] > self._now() else DEFERRED
                # An unfinished same/higher rank must make bounded progress before
                # any lower rank can be selected. Higher proved ready heads already
                # returned without touching lower-rank retry bookkeeping.
                if due['more'] or (frontier is not None and frontier['priority'] <= rank):
                    return DEFERRED
                if remaining == 0 and rank < 2:
                    return DEFERRED
            if urgent:
                return IDLE
        else:
            self.validate_clock()
            # Optional dependency wakes and dispatch remain active even when
            # the exact urgent population is empty.
            self.wake_fanout()
        progress = self.backfill()
        if not progress['complete']:
            return DEFERRED
        due = self._wake_rank(3)
        now = self._now()
        head = self._optional_head(now, excluded)
        if not self._proved_head(head, now, 3, more_due=due['more']):
            return DEFERRED if due['more'] else IDLE
        return (head if head['deadline'] > self._now() else DEFERRED) if head else IDLE

    def defer(self, job, retry_at, dependency=None):
        """Temporarily remove exactly this job version from dispatch readiness.

        The retry clock is scheduling metadata and cannot exceed the original
        obligation deadline. A new/tightened request resets readiness via its
        trigger. Dependency is an optional digest, never a provider body.
        """
        _require(type(job) is dict and type(job.get('id')) is str and
                 type(job.get('_scheduler_version')) is int and
                 job['_scheduler_version'] > 0, 'acquisition_schedule_job')
        _require(_number(retry_at), 'acquisition_schedule_retry')
        _require(dependency is None or type(dependency) is str and
                 re.fullmatch('[0-9a-f]{64}', dependency) is not None,
                 'acquisition_schedule_dependency')
        with self.writer.transaction():
            row = self.db.execute(f'''SELECT q.version,j.deadline FROM {QUEUE} q
                JOIN acquisition_jobs j ON j.id=q.id
                WHERE q.id=? AND j.status='pending' ''', (job['id'],)).fetchone()
            if row is None or row[0] != job['_scheduler_version']:
                return False
            self.db.execute(f'''UPDATE {QUEUE} SET ready=0,retry_at=?,dependency=?
                WHERE id=? AND version=?''',
                (min(retry_at, row[1]), dependency, job['id'], row[0]))
        return True
