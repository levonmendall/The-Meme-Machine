"""Resumable optional dispatch checks on the one canonical owner.

Only an authenticated complete local preparation may supply missing intervals.
Each turn reads at most one 16-KiB metric chunk or one sixteen-row indexed page.
No blob, SQLite read transaction, provider request or decoded result body survives
a turn. The acquisition job remains the durable obligation for every other gap.
"""
from dataclasses import dataclass
import copy
import hashlib
import json
import math
import re
import zlib

from .solana_evidence_plane import EvidenceUnavailable, canonical, digest


DEFERRED = 'DEFERRED'
READY = 'READY'
COMPLETE = 'COMPLETE'
CHUNK = 16 * 1024
PAGE = 16
BODY_LIMIT = 4096
GUARD = 'acquisition_dispatch_probe_v1'
JOB_FIELDS = ('id', 'family', 'address', 'lo', 'hi', 'priority', 'deadline',
              'token', 'pages', 'last_slot', 'last_index', 'lineage')


@dataclass(frozen=True)
class DispatchStep:
    state: str
    interval: tuple | None = None
    job_id: str | None = None
    dependency: str | None = None
    reason: str | None = None
    continuation: bool = False
    scanned_through: int | None = None
    missing_any: bool = False


def _require(condition, code):
    if not condition:
        raise EvidenceUnavailable(code)


def _hash(value):
    return type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None


def _prefix_append(old, old_hash, new, new_hash, old_lo, new_lo, old_hi, new_hi, requested_hi):
    """Bounded proof of an unchanged prefix with new points only above the job.

    Larger or rewritten fragments require a fresh preparation. These checks do
    not create coverage; the canonical publication still authenticates it.
    """
    try:
        if (type(old) is not bytes or type(new) is not bytes or len(old)>CHUNK or len(new)>CHUNK
                or not _hash(old_hash) or not _hash(new_hash) or old_lo!=new_lo
                or not all(type(n) is int for n in (old_hi,new_hi,requested_hi))
                or not requested_hi<=old_hi<new_hi):return 0
        if hashlib.sha256(old).hexdigest()!=old_hash or hashlib.sha256(new).hexdigest()!=new_hash:return 0
        def points(packed):
            decoder=zlib.decompressobj();raw=decoder.decompress(packed,CHUNK+1)
            if len(raw)>CHUNK or not decoder.eof or decoder.unused_data:return None
            value=json.loads(raw)
            if type(value) is not list or not 1<=len(value)<=512:return None
            for row in value:
                if (type(row) is not list or len(row)!=3 or type(row[0]) is not int
                        or type(row[1]) is not int or not 0<=row[0]<=row[1]<2**63
                        or type(row[2]) not in (int,float) or not 0<=row[2]<10**18
                        or not math.isfinite(row[2])):return None
            return value
        before,after=points(old),points(new)
        return int(before is not None and after is not None and len(before)<=256
            and len(after)>len(before) and after[:len(before)]==before
            and all(row[0]>requested_hi for row in after[len(before):]))
    except (ValueError,TypeError,UnicodeError,zlib.error,OverflowError,RecursionError):return 0


class _Metric:
    """Small streaming JSON recognizer for the canonical preparation metric.

    Strings not used as object keys are validated and discarded byte by byte.
    Numbers and keys have fixed token bounds; depth is fixed. No missing-interval
    list is ever accumulated. A completed intersecting interval pauses parsing
    until its bounded pending-publication check finishes.
    """
    def __init__(self, lo, hi):
        self.lo = lo
        self.hi = hi
        self.stack = []
        self.root = False
        self.finished = False
        self.lower = self.upper = None
        self.gaps_seen = False
        self.gaps_null = False
        self.last_gap = -1
        self.first_gap = None
        self.gap = None
        self.mode = None
        self.token = bytearray()
        self.capture = False
        self.escape = False
        self.hex_left = 0
        self.buffer = b''
        self.offset = 0

    def _done(self):
        if not self.stack:
            self.finished = True
            return
        parent = self.stack[-1]
        _require(parent['phase'] == 'value', 'dispatch_metric_json')
        parent['phase'] = 'comma'
        if parent['kind'] == 'array':
            parent['index'] += 1

    def _accept(self, kind, value=None):
        frame = self.stack[-1] if self.stack else None
        if frame and frame['kind'] == 'object' and frame['phase'] in ('key', 'key_or_end'):
            if kind == '}' and frame['phase'] == 'key_or_end':
                self.stack.pop(); self._done(); return
            _require(kind == 'string' and type(value) is str, 'dispatch_metric_json')
            _require(frame['last'] is None or frame['last'] < value, 'dispatch_metric_json')
            frame['key'] = frame['last'] = value
            frame['phase'] = 'colon'
            return
        if frame and frame['phase'] == 'colon':
            _require(kind == ':', 'dispatch_metric_json')
            frame['phase'] = 'value'
            return
        if frame and frame['phase'] == 'comma':
            end = '}' if frame['kind'] == 'object' else ']'
            if kind == end:
                self.stack.pop()
                if frame['role'] == 'interval':
                    _require(frame['index'] == 2, 'dispatch_metric_intervals')
                    a, b = frame['values']
                    _require(0 <= a <= b < 2**63 and a > self.last_gap,
                             'dispatch_metric_intervals')
                    self.last_gap = b
                    if self.first_gap is None: self.first_gap = a
                    if a <= self.hi and b >= self.lo:
                        self.gap = (max(a, self.lo), min(b, self.hi))
                self._done()
                return
            _require(kind == ',', 'dispatch_metric_json')
            frame['phase'] = 'key' if frame['kind'] == 'object' else 'value'
            return
        if frame and frame['kind'] == 'array' and frame['phase'] == 'value_or_end':
            if kind == ']':
                _require(frame['role'] != 'interval', 'dispatch_metric_intervals')
                self.stack.pop(); self._done(); return
            frame['phase'] = 'value'
        _require(not self.finished and (frame is None or frame['phase'] == 'value'),
                 'dispatch_metric_json')
        role = 'other'
        if frame is None:
            _require(not self.root and kind == '{', 'dispatch_metric_json')
            self.root = True; role = 'root'
        elif frame['role'] == 'root' and frame['key'] == 'missing_intervals':
            self.gaps_seen = True
            _require(kind in ('[', 'null'), 'dispatch_metric_intervals')
            self.gaps_null = kind == 'null'
            role = 'gaps'
        elif frame['role'] == 'gaps':
            _require(kind == '[', 'dispatch_metric_intervals')
            role = 'interval'
        elif frame['role'] == 'interval':
            _require(kind == 'number' and type(value) is int and frame['index'] < 2,
                     'dispatch_metric_intervals')
            frame['values'].append(value)
        elif frame['role'] == 'root' and frame['key'] in ('lower_slot', 'upper_slot'):
            _require(kind == 'number' and type(value) is int and 0 <= value < 2**63,
                     'dispatch_metric_bounds')
            if frame['key'] == 'lower_slot': self.lower = value
            else: self.upper = value
        if kind in ('{', '['):
            _require(len(self.stack) < 16, 'dispatch_metric_depth')
            self.stack.append(dict(kind='object' if kind == '{' else 'array', role=role,
                phase='key_or_end' if kind == '{' else 'value_or_end',
                key=None, last=None, index=0, values=[]))
        else:
            _require(kind in ('number', 'string', 'null', 'true', 'false'), 'dispatch_metric_json')
            self._done()

    def feed(self, data):
        _require(self.offset == len(self.buffer) and len(data) <= CHUNK, 'dispatch_metric_chunk')
        self.buffer = data
        self.offset = 0

    def scan(self):
        while self.offset < len(self.buffer) and self.gap is None:
            byte = self.buffer[self.offset]
            if self.mode == 'string':
                self.offset += 1
                if self.capture:
                    self.token.append(byte)
                    _require(len(self.token) <= 128, 'dispatch_metric_token')
                if self.hex_left:
                    _require(byte in b'0123456789abcdefABCDEF', 'dispatch_metric_json')
                    self.hex_left -= 1
                elif self.escape:
                    _require(byte in b'"\\/bfnrtu', 'dispatch_metric_json')
                    self.escape = False
                    if byte == 117: self.hex_left = 4
                elif byte == 92:
                    self.escape = True
                elif byte == 34:
                    value = json.loads(bytes(self.token)) if self.capture else None
                    self.mode = None; self.token.clear()
                    self._accept('string', value)
                else:
                    _require(32 <= byte < 128, 'dispatch_metric_json')
                continue
            if self.mode == 'atom':
                if byte in b'0123456789-+.eEabcdefghijklmnopqrstuvwxyz':
                    self.token.append(byte); self.offset += 1
                    _require(len(self.token) <= 128, 'dispatch_metric_token')
                    continue
                self._atom()
                continue
            self.offset += 1
            if byte in b' \t\n\r': continue
            if byte == 34:
                frame = self.stack[-1] if self.stack else None
                self.capture = bool(frame and frame['kind'] == 'object' and
                                    frame['phase'] in ('key', 'key_or_end'))
                self.token = bytearray(b'"') if self.capture else bytearray()
                self.mode = 'string'; self.escape = False; self.hex_left = 0
            elif byte in b'{}[]:,':
                self._accept(chr(byte))
            else:
                _require(byte in b'-0123456789ntf', 'dispatch_metric_json')
                self.token = bytearray((byte,)); self.mode = 'atom'
        return self.gap

    def _atom(self):
        raw = bytes(self.token)
        try: value = json.loads(raw)
        except (ValueError, UnicodeError):
            raise EvidenceUnavailable('dispatch_metric_json') from None
        if raw in (b'null', b'true', b'false'):
            kind = raw.decode('ascii')
        else:
            _require(type(value) in (int, float) and
                     (type(value) is int or math.isfinite(value)), 'dispatch_metric_json')
            kind = 'number'
        self.mode = None; self.token.clear(); self._accept(kind, value)

    def finish(self):
        if self.mode == 'atom': self._atom()
        _require(self.mode is None and not self.stack and self.finished,
                 'dispatch_metric_json')
        _require(self.gaps_seen, 'dispatch_metric_bounds')
        # The existing preparation contract also emits authenticated boundary
        # waits with no interval verdict. A resolved creation floor can likewise
        # exclude the original genesis request. Neither is dispatch authority.
        if self.gaps_null:return False
        _require(self.lower is not None and self.upper is not None and
                 self.lower <= self.upper, 'dispatch_metric_bounds')
        _require(self.first_gap is None or self.lower <= self.first_gap <= self.last_gap <= self.upper,
                 'dispatch_metric_intervals')
        return self.lower <= self.lo <= self.hi <= self.upper


class DispatchProbe:
    """One active resumable context, shared by the actor's optional workers."""
    def __init__(self, history):
        self.history = history
        self.db = history.db
        self.writer = history.writer
        self.context = None
        self._install()

    def _ddl(self, statement, kind, name):
        self.db.execute(statement)
        # TEMP invalidation belongs to this sole canonical-owner connection.
        # Persisting the UDF-backed trigger would prevent an older authenticated
        # source from preparing writes after a rollback on this same database.
        def normalized(sql):
            return sql.replace(' IF NOT EXISTS ', ' ', 1).replace('CREATE TEMP TRIGGER ',
                'CREATE TRIGGER ', 1).strip()
        catalog = 'sqlite_temp_master' if kind == 'trigger' else 'sqlite_master'
        actual = self.db.execute('SELECT sql FROM '+catalog+' WHERE type=? AND name=?',
                                 (kind, name)).fetchone()
        _require(actual is not None and normalized(actual[0]) == normalized(statement),
                 'dispatch_probe_schema')

    def _install(self):
        self.db.create_function('dispatch_probe_prefix_append_v1',9,_prefix_append,deterministic=True)
        with self.writer.transaction():
            self._ddl(f'''CREATE TABLE IF NOT EXISTS {GUARD}(
                id INTEGER PRIMARY KEY CHECK(id=1),active INTEGER NOT NULL,
                stale INTEGER NOT NULL,anchored INTEGER NOT NULL,version INTEGER NOT NULL,
                turn INTEGER NOT NULL,
                job_id TEXT,job_hash TEXT,family TEXT,address TEXT,market TEXT,
                lo INTEGER,hi INTEGER,scope0 TEXT,scope1 TEXT,prep_id TEXT,
                prep_rowid INTEGER,body_hash TEXT,dependency TEXT,metric_hash TEXT)''', 'table', GUARD)
            self.db.execute(f'INSERT OR IGNORE INTO {GUARD}(id,active,stale,anchored,version,turn) VALUES(1,0,0,0,0,0)')
            self.db.execute(f'UPDATE {GUARD} SET active=0,stale=1,anchored=0 WHERE id=1')
            self._ddl('''CREATE INDEX IF NOT EXISTS dispatch_preparation_candidate_v1
                ON rolling_preparation_jobs(json_extract(body,'$.family'),
                json_extract(body,'$.address'),status,id)''', 'index', 'dispatch_preparation_candidate_v1')
            self._ddl('''CREATE INDEX IF NOT EXISTS dispatch_pending_proof_v1
                ON candidate_pending_proofs(scope,lo,hi,id)''', 'index', 'dispatch_pending_proof_v1')
            for table in ('candidate_coverage', 'candidate_gaps', 'candidate_pending_proofs'):
                for action in ('INSERT', 'UPDATE', 'DELETE'):
                    sides = ('OLD', 'NEW') if action == 'UPDATE' else (('OLD',) if action == 'DELETE' else ('NEW',))
                    overlap = ' OR '.join(f'''({side}.scope IN (scope0,scope1)
                        AND {side}.lo<=hi AND COALESCE({side}.hi,hi)>=lo)''' for side in sides)
                    if table=='candidate_coverage' and action=='UPDATE':
                        overlap='('+overlap+''') AND NOT (OLD.scope=NEW.scope AND
                            dispatch_probe_prefix_append_v1(OLD.points,OLD.hash,NEW.points,NEW.hash,
                                OLD.lo,NEW.lo,OLD.hi,NEW.hi,hi)=1)'''
                    name = 'dispatch_probe_'+table+'_'+action.lower()+'_v1'
                    self._ddl(f'''CREATE TEMP TRIGGER IF NOT EXISTS {name} AFTER {action} ON main.{table}
                        BEGIN UPDATE {GUARD} SET stale=1 WHERE id=1 AND active=1 AND ({overlap}); END''', 'trigger', name)
            for table, predicate, columns in (
                    ('evidence_bindings', '{s}.family=family AND {s}.address=address', None),
                    ('rolling_origins', '{s}.family=family AND {s}.address=market', None),
                    ('candidate_lifecycle', '{s}.family=family AND {s}.address=address', 'first_slot')):
                for action in ('INSERT', 'UPDATE', 'DELETE'):
                    sides = ('OLD', 'NEW') if action == 'UPDATE' else (('OLD',) if action == 'DELETE' else ('NEW',))
                    match = ' OR '.join('('+predicate.format(s=side)+')' for side in sides)
                    event = 'UPDATE OF '+columns if action == 'UPDATE' and columns else action
                    name = 'dispatch_probe_'+table+'_'+action.lower()+'_v1'
                    self._ddl(f'''CREATE TEMP TRIGGER IF NOT EXISTS {name} AFTER {event} ON main.{table}
                        BEGIN UPDATE {GUARD} SET stale=1 WHERE id=1 AND active=1 AND ({match}); END''', 'trigger', name)
            for action in ('UPDATE', 'DELETE'):
                name = 'dispatch_probe_preparation_'+action.lower()+'_v1'
                event = ('UPDATE OF body,hash,dependency,metric,metric_hash,status' if action == 'UPDATE' else action)
                self._ddl(f'''CREATE TEMP TRIGGER IF NOT EXISTS {name} AFTER {event} ON main.rolling_preparation_jobs
                    BEGIN UPDATE {GUARD} SET stale=1 WHERE id=1 AND active=1 AND prep_id=OLD.id; END''', 'trigger', name)
            for action in ('UPDATE', 'DELETE'):
                name = 'dispatch_probe_job_'+action.lower()+'_v1'
                event = ('UPDATE OF '+','.join(JOB_FIELDS[1:])+',status' if action == 'UPDATE' else action)
                self._ddl(f'''CREATE TEMP TRIGGER IF NOT EXISTS {name} AFTER {event} ON main.acquisition_jobs
                    BEGIN UPDATE {GUARD} SET stale=1,anchored=0 WHERE id=1 AND active=1 AND job_id=OLD.id; END''', 'trigger', name)

    def _job_hash(self, job):
        _require(type(job) is dict and all(key in job for key in JOB_FIELDS), 'dispatch_probe_job')
        _require(_hash(job['id']) and job['family'] in ('pump', 'pumpswap') and
                 type(job['address']) is str and 0 < len(job['address']) <= 256 and
                 type(job['lo']) is int and type(job['hi']) is int and 0 <= job['lo'] <= job['hi'] < 2**63 and
                 type(job['priority']) is int and 2 < job['priority'] <= 6 and
                 type(job['pages']) is int and job['pages'] >= 0 and
                 type(job['deadline']) in (int, float) and 0 <= job['deadline'] < 10**18 and
                 math.isfinite(job['deadline']), 'dispatch_probe_job')
        return digest([job[key] for key in JOB_FIELDS])

    def _current_job_hash(self, identity):
        row = self.db.execute('SELECT '+','.join(JOB_FIELDS)+' FROM acquisition_jobs '
            "WHERE id=? AND status='pending'", (identity,)).fetchone()
        return None if row is None else digest(list(row))

    def reset(self):
        self.context = None
        self.db.execute(f'UPDATE {GUARD} SET active=0,anchored=0,stale=1 WHERE id=1')

    def _generation(self):
        from .solana_history_delivery import generation
        return digest(generation(self.history.lifecycle))

    def _new(self, job, job_hash, after_slot=None):
        self.reset()
        scope = self.history.scope_for(job['family'], job['address'])
        scopes = tuple(self.history.rolling.scopes(job['family'], scope))
        _require(1 <= len(scopes) <= 2, 'dispatch_probe_scopes')
        binding = self.db.execute('SELECT market_address FROM evidence_bindings WHERE family=? AND address=?',
                                  (job['family'], job['address'])).fetchone()
        market = job['address'] if binding is None else binding[0]
        self.db.execute(f'''UPDATE {GUARD} SET active=1,stale=0,anchored=0,version=version+1,
            job_id=?,job_hash=?,family=?,address=?,market=?,lo=?,hi=?,scope0=?,scope1=?,
            prep_id=NULL,prep_rowid=NULL,body_hash=NULL,dependency=NULL,metric_hash=NULL WHERE id=1''',
            (job['id'], job_hash, job['family'], job['address'], market, job['lo'], job['hi'],
             scopes[0], scopes[-1]))
        self.context = dict(job=dict(job), job_hash=job_hash, scopes=scopes, phase='lookup',
            exact=False, after='', pending_headers=[], selected=None, result=None,
            generation=self._generation(),after_slot=after_slot)

    def _header(self, identity):
        return self.db.execute('''SELECT rowid,substr(id,1,65),substr(CAST(body AS BLOB),1,4097),
            substr(hash,1,65),substr(dependency,1,65),substr(metric_hash,1,65),substr(status,1,17)
            FROM rolling_preparation_jobs WHERE id=?''', (identity,)).fetchone()

    def _decode_header(self, row, job):
        if row is None or row[6] != 'complete' or row[4] is None:return None
        raw = row[2]
        _require(type(raw) is bytes and len(raw) <= BODY_LIMIT and _hash(row[1]) and _hash(row[3]) and
                 hashlib.sha256(raw).hexdigest() == row[3] and _hash(row[4]) and _hash(row[5]),
                 'dispatch_preparation_metadata')
        try: spec = json.loads(raw)
        except (ValueError, UnicodeError):
            raise EvidenceUnavailable('dispatch_preparation_metadata') from None
        if (type(spec) is not dict or spec.get('kind') is not None or
                spec.get('family') != job['family'] or spec.get('address') != job['address'] or
                type(spec.get('lo')) is not int or type(spec.get('hi')) is not int or
                not spec['lo'] <= job['lo'] <= job['hi'] <= spec['hi']):return None
        return dict(rowid=row[0], id=row[1], body_hash=row[3], dependency=row[4],
                    metric_hash=row[5], spec=spec)

    def _expect(self, selected):
        self.db.execute(f'''UPDATE {GUARD} SET prep_id=?,prep_rowid=?,body_hash=?,dependency=?,
            metric_hash=?,anchored=0,stale=0 WHERE id=1 AND active=1''',
            tuple(selected[key] for key in ('id','rowid','body_hash','dependency','metric_hash')))

    def preparation_applied(self, prep_id, metric_hash):
        """Called only by reusable HistoricalTasks.apply in its original transaction.

        The hook advances only the SQLite anchor, never a volatile parser cursor.
        An enclosing rollback therefore cannot publish an anchored preparation.
        """
        _require(self.db.in_transaction, 'dispatch_probe_anchor_transaction')
        row = self.db.execute(f'''SELECT job_id,job_hash,prep_id,active FROM {GUARD} WHERE id=1''').fetchone()
        if row is None or row[3] != 1 or row[2] != prep_id:return False
        if self.context is None or self.context.get('generation')!=self._generation():return False
        current = self.db.execute('SELECT '+','.join(JOB_FIELDS)+' FROM acquisition_jobs '
            "WHERE id=? AND status='pending'", (row[0],)).fetchone()
        if current is None or digest(list(current)) != row[1]:return False
        header = self._header(prep_id)
        if header is None or header[6] != 'complete' or header[5] != metric_hash or not _hash(header[4]):return False
        if self._decode_header(header,dict(zip(JOB_FIELDS,current))) is None:return False
        _require(_hash(metric_hash) and _hash(header[3]), 'dispatch_preparation_metadata')
        self.db.execute(f'''UPDATE {GUARD} SET prep_rowid=?,body_hash=?,dependency=?,metric_hash=?,
            anchored=1,stale=0,version=version+1 WHERE id=1 AND active=1 AND prep_id=?''',
            (header[0],header[3],header[4],metric_hash,prep_id))
        return True

    def _guard(self):
        return self.db.execute(f'''SELECT active,stale,anchored,version,prep_id,prep_rowid,
            body_hash,dependency,metric_hash,job_id,job_hash FROM {GUARD} WHERE id=1''').fetchone()

    def _enqueue(self, context):
        job = context['job']; tasks = self.history.historical_tasks
        metric = tasks.enqueue(job['family'], job['address'], job['lo'], job['hi'],
            deadline=job['deadline'], priority=job['priority'])
        identity = metric.get('historical_job') if type(metric) is dict else None
        if identity is None:identity = digest([job['family'],job['address'],job['lo'],job['hi']])
        _require(_hash(identity), 'dispatch_preparation_metadata')
        self.db.execute(f'''UPDATE {GUARD} SET prep_id=?,anchored=0,stale=0,
            prep_rowid=NULL,body_hash=NULL,dependency=NULL,metric_hash=NULL WHERE id=1''', (identity,))
        context['phase'] = 'await'
        return DispatchStep(DEFERRED, job_id=job['id'], reason='PREPARATION_PENDING')

    def _start_metric(self, context, guard):
        selected = self._decode_header(self._header(guard[4]), context['job'])
        _require(selected is not None and
                 (selected['rowid'],selected['body_hash'],selected['dependency'],selected['metric_hash']) ==
                 (guard[5],guard[6],guard[7],guard[8]), 'dispatch_preparation_changed')
        context.update(selected=selected, anchor=guard[3], phase='metric', parser=_Metric(
            context['job']['lo'],context['job']['hi']), checksum=hashlib.sha256(), read=0,
            total=None, interval=None, had_gap=False, proof=None, verified=False,
            saved=None,highest_gap=None,after_missing=False)

    def _begin_proof(self,context,a,b):
        context['proof']=dict(cursor=a,hi=b,branches=[dict(scope=scope,
            after=(-1,-1,''),rows=[],done=False) for scope in context['scopes']])

    def _resume_after(self,context,after_slot):
        saved=context['saved']
        context.update(parser=copy.deepcopy(saved['parser']),read=saved['read'],
            after_slot=after_slot,interval=None,proof=None,result=None,after_missing=False)
        a,b=saved['gap']
        if b>after_slot:
            context['after_missing']=True
            self._begin_proof(context,max(a,after_slot+1),b)

    def _proof_step(self, context):
        proof = context['proof']
        for branch in proof['branches']:
            if not branch['rows'] and not branch['done']:
                after = branch['after']
                rows = self.db.execute('''SELECT lo,hi,substr(id,1,65) FROM candidate_pending_proofs
                    INDEXED BY dispatch_pending_proof_v1 WHERE scope=? AND (lo,hi,id)>(?,?,?)
                    AND lo<=? ORDER BY lo,hi,id LIMIT 16''',
                    (branch['scope'],*after,proof['hi'])).fetchall()
                _require(all(type(a) is int and type(b) is int and 0 <= a <= b < 2**63 and
                    _hash(identity) for a,b,identity in rows), 'dispatch_pending_proof_shape')
                branch['rows'] = rows
                branch['done'] = len(rows) < PAGE
                if rows:branch['after'] = tuple(rows[-1])
                return False
        for _ in range(PAGE):
            available = [(branch['rows'][0], index) for index,branch in enumerate(proof['branches']) if branch['rows']]
            if not available:
                if all(branch['done'] for branch in proof['branches']):
                    context['interval'] = (proof['cursor'],proof['hi'])
                    context['proof'] = None
                    return True
                return False
            (lo,hi,_), index = min(available)
            if lo > proof['cursor']:
                context['interval'] = (proof['cursor'],min(proof['hi'],lo-1))
                context['proof'] = None
                return True
            proof['branches'][index]['rows'].pop(0)
            proof['cursor'] = max(proof['cursor'],hi+1)
            if proof['cursor'] > proof['hi']:
                context['proof'] = None
                return True
            if not proof['branches'][index]['rows'] and not proof['branches'][index]['done']:return False
        return False

    def step(self, job, after_slot=None):
        # Read progress is volatile, but every quantum has a matching committed
        # tag. If an enclosing owner transaction rolls back, discard its parser
        # and proof cursor rather than retaining observations from that snapshot.
        turn = self.db.execute(f'SELECT turn FROM {GUARD} WHERE id=1').fetchone()[0]
        if self.context is not None and self.context.get('turn') != turn:self.context = None
        self.db.execute(f'UPDATE {GUARD} SET turn=turn+1 WHERE id=1')
        try:
            result = self._step(job,after_slot)
            if self.context is not None:
                self.context['turn'] = self.db.execute(f'SELECT turn FROM {GUARD} WHERE id=1').fetchone()[0]
            return result
        except BaseException:
            self.context = None
            raise

    def _step(self, job,after_slot):
        job_hash = self._job_hash(job)
        _require(after_slot is None or type(after_slot) is int and job['lo']-1<=after_slot<=job['hi'],
                 'dispatch_probe_after_slot')
        if self.context is None or self.context['job_hash'] != job_hash:self._new(job,job_hash,after_slot)
        context = self.context
        guard = self._guard()
        if guard is None or guard[0] != 1 or guard[9:] != (job['id'],job_hash):
            self._new(job,job_hash,after_slot);context=self.context;guard=self._guard()
        if context['generation']!=self._generation():
            self._new(job,job_hash,after_slot);context=self.context;guard=self._guard()
        if context['after_slot']!=after_slot:
            previous=context.get('result')
            if (after_slot is not None and context.get('verified') and context.get('saved')
                    and previous is not None and previous.state==READY
                    and after_slot>=previous.interval[1] and not guard[1] and guard[2]
                    and context.get('anchor')==guard[3]):
                self._resume_after(context,after_slot)
            else:
                self._new(job,job_hash,after_slot);context=self.context;guard=self._guard()
        if self._current_job_hash(job['id']) != job_hash:
            self.reset();return DispatchStep(DEFERRED,job_id=job['id'],reason='JOB_CHANGED')
        if context['phase'] == 'await':
            if guard[1]:
                self._new(job,job_hash,after_slot);context=self.context;guard=self._guard()
            elif not guard[2]:return DispatchStep(DEFERRED,job_id=job['id'],reason='PREPARATION_PENDING')
            else:self._start_metric(context,guard)
        elif guard[1]:
            self._new(job,job_hash,after_slot);context=self.context;guard=self._guard()
        if context['phase'] == 'lookup':
            rows = context['pending_headers']
            if not context['exact']:
                context['exact'] = True
                row = self._header(digest([job['family'],job['address'],job['lo'],job['hi']]))
                if row is not None:rows.append(row)
            if not rows:
                rows = self.db.execute('''SELECT rowid,substr(id,1,65),substr(CAST(body AS BLOB),1,4097),
                    substr(hash,1,65),substr(dependency,1,65),substr(metric_hash,1,65),substr(status,1,17)
                    FROM rolling_preparation_jobs INDEXED BY dispatch_preparation_candidate_v1
                    WHERE json_extract(body,'$.family')=? AND json_extract(body,'$.address')=?
                    AND status='complete' AND id>? ORDER BY id LIMIT 16''',
                    (job['family'],job['address'],context['after'])).fetchall()
                if not rows:return self._enqueue(context)
                context['after'] = rows[-1][1]
            # At most one fresh dependency check per turn; metadata pages remain
            # bounded even if many old preparations belong to this candidate.
            row = rows.pop(0); context['pending_headers'] = rows
            selected = self._decode_header(row,job)
            if selected is not None:
                from .solana_history_work import dependency_stamp
                if selected['dependency'] == dependency_stamp(self.history.rolling,selected['spec']):
                    with self.writer.transaction():
                        self._expect(selected)
                        _require(self.preparation_applied(selected['id'],selected['metric_hash']),
                                 'dispatch_preparation_changed')
                    self._start_metric(context,self._guard())
            return DispatchStep(DEFERRED,job_id=job['id'],continuation=True)
        guard = self._guard()
        if guard[1] or not guard[2]:return self._enqueue(context)
        if context.get('anchor') != guard[3]:self._start_metric(context,guard)
        if context.get('result') is not None:return context['result']
        if context['proof'] is not None:
            self._proof_step(context)
            # A prior pass already authenticated this entire immutable metric.
            # Repeated fanout needs only the next bounded pending-proof check,
            # not another parse of its potentially large remaining suffix.
            if context['verified'] and context['interval'] is not None:
                result=DispatchStep(READY,interval=context['interval'],job_id=job['id'],
                    dependency=guard[7],scanned_through=context['interval'][1],missing_any=True)
                context['result']=result
                return result
            return DispatchStep(DEFERRED,job_id=job['id'],continuation=True)
        parser = context['parser']
        if parser.offset < len(parser.buffer):
            parser.scan()
        elif context['total'] is None or context['read'] < context['total']:
            # sqlite3_blob handles TEXT as original UTF-8 bytes. A fresh handle
            # is opened and closed inside this turn; no snapshot survives it.
            with self.db.blobopen('rolling_preparation_jobs','metric',guard[5],readonly=True) as blob:
                total = len(blob)
                _require(context['total'] is None or context['total'] == total,
                         'dispatch_preparation_changed')
                context['total'] = total
                blob.seek(context['read']);chunk=blob.read(min(CHUNK,total-context['read']))
            context['read'] += len(chunk)
            if not context['verified']:context['checksum'].update(chunk)
            parser.feed(chunk);parser.scan()
        else:
            usable=parser.finish()
            _require(context['verified'] or context['checksum'].hexdigest() == guard[8], 'historical_metric_corrupt')
            context['verified']=True
            selected = self._decode_header(self._header(guard[4]),job)
            _require(selected is not None and (selected['rowid'],selected['body_hash'],
                selected['dependency'],selected['metric_hash']) == (guard[5],guard[6],guard[7],guard[8]),
                'dispatch_preparation_changed')
            if not usable:
                self.reset()
                return DispatchStep(DEFERRED,job_id=job['id'],reason='PREPARATION_UNUSABLE')
            if context['interval'] is None and context['had_gap']:
                high=context['highest_gap'];reason='PENDING_PUBLICATION' if context['after_missing'] else 'FANOUT_COMPLETE'
                self.reset();return DispatchStep(DEFERRED,job_id=job['id'],reason=reason,
                    scanned_through=high,missing_any=True)
            result = DispatchStep(READY if context['interval'] is not None else COMPLETE,
                interval=context['interval'],job_id=job['id'],dependency=guard[7],
                scanned_through=context['interval'][1] if context['interval'] is not None else job['hi'],
                missing_any=context['had_gap'])
            context['result'] = result
            return result
        if parser.gap is not None:
            context['had_gap'] = True
            context['highest_gap']=parser.gap[1]
            lower=job['lo']-1 if after_slot is None else after_slot
            if parser.gap[1]>lower:context['after_missing']=True
            if context['interval'] is None and parser.gap[1]>lower:
                a,b=parser.gap
                checkpoint=copy.deepcopy(parser);checkpoint.gap=None
                context['saved']=dict(parser=checkpoint,read=context['read'],gap=(a,b))
                self._begin_proof(context,max(a,lower+1),b)
            parser.gap = None
        return DispatchStep(DEFERRED,job_id=job['id'],continuation=True)

    def current(self, job, result):
        """Fresh same-owner claim; no cached verdict survives a relevant mutation."""
        context=self.context
        if context is None or result is not context.get('result') or result.state not in (READY,COMPLETE):return False
        job_hash=self._job_hash(job);guard=self._guard()
        return bool(guard is not None and guard[0:3] == (1,0,1) and
            guard[3] == context['anchor'] and guard[9:] == (job['id'],job_hash) and
            context['generation']==self._generation() and
            self.db.execute(f'SELECT turn FROM {GUARD} WHERE id=1').fetchone()[0] == context.get('turn') and
            self._current_job_hash(job['id']) == job_hash and job['deadline'] > self.history.clock())
