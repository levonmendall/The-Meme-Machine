"""Fixed-cut outbox retention accounting, separate from market/evaluation work.

The adapter must acquire the boot-support cuts from its actual private owner,
capture source metadata in the original read snapshot, and call committed only
after the original FULL history writer returns. This reducer performs no SQL,
provider operation or native cursor change and cannot issue a boot witness.
"""
from dataclasses import dataclass
import json
import math
import os
import threading
import time
import stat
from pathlib import Path

from .economic_cohort import checksum, _hash, MAX_POSITION

SCOPE = 'program:pump'
SCOPES = ('program:meteora', 'program:pump', 'program:pumpswap')
MAX_ROWS = 5000
ZERO = '0' * 64
KEY_LEASE_SECONDS = .025
KEY_PAGE_ROWS = 5000

# Source code and the actual exclusive native owner make this table append-only.
# These are metadata seeks, not a database-enforced immutability assertion.
KEY_SQL = '''SELECT sequence,
    CASE WHEN typeof(identity)='text' AND length(CAST(identity AS BLOB)) BETWEEN 1 AND 512 THEN identity END,
    CASE WHEN typeof(scope)='text' AND length(CAST(scope AS BLOB))<=64 THEN scope END,
    CASE WHEN typeof(slot)='integer' THEN slot END,
    CASE WHEN typeof(first_seen) IN ('integer','real') THEN first_seen END
    FROM candidate_outbox INDEXED BY candidate_outbox_scope
    WHERE scope='program:pump' AND sequence>? AND sequence<=?
    ORDER BY sequence LIMIT ?'''
KEY_INITIAL_SQL=KEY_SQL.replace('sequence>?','sequence>=?')
SCHEMA_SQL="""SELECT type,name,CASE WHEN length(CAST(sql AS BLOB))<=8192 THEN sql END
    FROM sqlite_master WHERE name IN('candidate_outbox','candidate_outbox_scope') ORDER BY name"""
FRONTIER_SQL="""SELECT CASE WHEN typeof(value)='text' AND length(CAST(value AS BLOB))<=16384
    THEN value END FROM service_health WHERE key='source_generation_frontier'"""


@dataclass(frozen=True)
class _KeyCapture:
    issuer: object
    version: int
    prefix: tuple
    complete: bool
    future_rows: int
    expired: bool
    rows: int


class InheritedKeyCensus:
    """Resumable independent metadata EOF at an authentic fixed support cut.

    The protected adapter validates the same original inode/schema/private
    generation before and after each call. The reviewed native writer only
    appends beyond this cut; authorized recovery/cutover cannot run concurrently.
    This class neither holds a transaction across calls nor replaces a progress
    handler. Its exact indexed seek has a fixed row bound; cancellation and the
    short lease are checked between SQLite rows, with every cursor finalized.
    """
    def __init__(self, upper, visibility_wall, *, clock=time.monotonic):
        if (upper is not None and (type(upper) is not int or not 0<=upper<=MAX_POSITION)
                or type(visibility_wall) not in (int,float) or not math.isfinite(visibility_wall)):
            raise ValueError('support_cut')
        self.upper=upper;self.visibility=visibility_wall;self.clock=clock
        self.owner=(os.getpid(),threading.get_native_id())
        self.prefix=empty_prefix();self.complete=False;self.future_rows=0
        self.leases=0;self.expired=0;self.version=0;self.staged=None;self.loss=None

    def unavailable(self):
        if self.loss is None:self.loss='KEY_CENSUS_UNAVAILABLE'

    def _owned(self):
        if self.owner!=(os.getpid(),threading.get_native_id()):raise ValueError('owner')

    def capture(self, db, *, validate, cancelled):
        if self.loss:return None
        from .stop import Shutdown
        cursor=None
        try:
            self._owned()
            if self.staged is not None or not db.in_transaction:raise ValueError('snapshot')
            if cancelled():raise Shutdown()
            if validate() is not True:raise ValueError('support')
            value=dict(self.prefix);count=0;future=self.future_rows;complete=self.complete;expired=False
            started=self.clock()
            if type(started) not in (int,float) or not math.isfinite(started) or started<0:
                raise ValueError('clock')
            deadline=started+KEY_LEASE_SECONDS;previous=started
            if not complete:
                initial=value['last_sequence'] is None
                cursor=db.execute(KEY_INITIAL_SQL if initial else KEY_SQL,
                    (-2**63 if initial else value['last_sequence'],self.upper,KEY_PAGE_ROWS+1))
                while True:
                    if cancelled():raise Shutdown()
                    now=self.clock()
                    if (type(now) not in (int,float) or not math.isfinite(now)
                            or now<previous):raise ValueError('clock')
                    previous=now
                    if now>=deadline:
                        expired=True;break
                    row=cursor.fetchone()
                    if cancelled():raise Shutdown()
                    now=self.clock()
                    if (type(now) not in (int,float) or not math.isfinite(now)
                            or now<previous):raise ValueError('clock')
                    previous=now
                    if now>=deadline:
                        expired=True;break
                    if row is None:
                        complete=True;break
                    if count==KEY_PAGE_ROWS:break # This is real lookahead, not EOF.
                    value=advance(value,row);count+=1
                    if row[4]>self.visibility:future+=1
            if cursor is not None:cursor.close();cursor=None
            if cancelled():raise Shutdown()
            if validate() is not True:raise ValueError('support')
            ticket=_KeyCapture(self,self.version,tuple(value.items()),complete,future,expired,count)
            self.staged=ticket
            return ticket
        except Exception:
            self.unavailable();return None
        finally:
            if cursor is not None:cursor.close()

    def committed(self,ticket):
        """Retain this read-only capture after its original snapshot has closed."""
        if self.loss:return
        try:
            self._owned()
            if (type(ticket) is not _KeyCapture or ticket is not self.staged
                    or ticket.issuer is not self or ticket.version!=self.version):
                raise ValueError('ticket')
            value=dict(ticket.prefix)
            if ticket.complete and value['last_sequence']!=self.upper:
                raise ValueError('missing_support_tail')
            self.prefix=value;self.complete=ticket.complete;self.future_rows=ticket.future_rows
            self.leases+=1;self.expired+=int(ticket.expired);self.version+=1;self.staged=None
        except Exception:self.unavailable()

    def snapshot(self):
        self._owned()
        return dict(state='UNKNOWN' if self.loss else 'EOF' if self.complete else 'INCOMPLETE',
            reason=self.loss,upper=self.upper,visibility_wall=self.visibility,
            population=dict(self.prefix),future_at_support_cut=self.future_rows,
            leases=self.leases,expired_leases=self.expired,capture_pending=self.staged is not None,
            contract='FIXED_CUT_KEY_ONLY_EOF_UNDER_TRUSTED_NATIVE_APPEND_ONLY_WRITER_NOT_DB_ENFORCED',
            historical_completion=False,readiness_authority=False,funding_authority=False)


def empty_prefix():
    return dict(records=0, first_sequence=None, last_sequence=None, prefix_sha256=ZERO)


def prefix(value):
    """Normalize the fixed native prefix; publication batch count is descriptive."""
    fields = {'records', 'first_sequence', 'last_sequence', 'prefix_sha256'}
    if type(value) is not dict or set(value) not in (fields, fields | {'batches'}):
        raise ValueError('prefix')
    count = value['records']
    if type(count) is not int or not 0 <= count <= MAX_POSITION:
        raise ValueError('prefix')
    first, last = value['first_sequence'], value['last_sequence']
    if count == 0:
        if first is not None or last is not None or value['prefix_sha256'] != ZERO:
            raise ValueError('empty_prefix')
    elif (type(first) is not int or type(last) is not int
            or not 0 <= first <= last <= MAX_POSITION):
        raise ValueError('prefix')
    if 'batches' in value and (type(value['batches']) is not int
            or not 0 <= value['batches'] <= count
            or (value['batches'] == 0) != (count == 0)):
        raise ValueError('batches')
    return {key: _hash(value[key]) if key == 'prefix_sha256' else value[key]
            for key in fields}


def advance(value, row):
    """Same original five-tuple/per-row chain as the source transaction registry."""
    if type(row) not in (list, tuple) or len(row) != 5:
        raise ValueError('tuple')
    sequence, identity, scope, slot, available = row
    if (type(sequence) is not int or not 0 <= sequence <= MAX_POSITION
            or type(identity) is not str or not 0 < len(identity.encode()) <= 512
            or scope != SCOPE or type(slot) is not int or not 0 <= slot <= MAX_POSITION
            or type(available) not in (int, float) or not math.isfinite(available)
            or value['last_sequence'] is not None and sequence <= value['last_sequence']
            or value['records'] >= MAX_POSITION):
        raise ValueError('tuple')
    return dict(records=value['records'] + 1,
        first_sequence=sequence if value['first_sequence'] is None else value['first_sequence'],
        last_sequence=sequence, prefix_sha256=checksum([value['prefix_sha256'], row]))


@dataclass(frozen=True)
class _Capture:
    issuer: object
    version: int
    first: int
    last: int
    rows: int
    batch_sha256: str
    inherited: tuple
    fresh: tuple
    expected_fresh: tuple | None
    source_metadata_present: bool
    replay: bool


class CurrentInputPrefixes:
    """Pure accounting after authentic adapter admission, never an issuer.

    The support digest authenticates an inherited census; source generation
    identity and its atomic publication registry authenticate newly issued
    obligations. Neither is an economic-market denominator or job completion.
    """
    def __init__(self, support_sha256, inherited, source_identity_sha256, generation,
                 *, inherited_upper=None):
        self.support = _hash(support_sha256)
        self.expected_inherited = None if inherited is None else prefix(inherited)
        self.inherited_upper = (inherited_upper if inherited is None else
            self.expected_inherited['last_sequence'])
        if self.inherited_upper is not None and (type(self.inherited_upper) is not int
                or not 0 <= self.inherited_upper <= MAX_POSITION):
            raise ValueError('inherited_cut')
        self.source = _hash(source_identity_sha256)
        if (type(generation) is not str or len(generation) != 32
                or any(c not in '0123456789abcdef' for c in generation)):
            raise ValueError('generation')
        self.generation = generation
        self.owner = (os.getpid(), threading.get_native_id())
        self.inherited = empty_prefix()
        self.fresh = empty_prefix()
        self.expected_fresh = None
        self.cursor = 0
        self.version = 0
        self.staged = None
        self.previous = None
        self.replayed = 0
        self.source_metadata_present = False
        self.loss = None

    def unavailable(self):
        if self.loss is None: self.loss = 'INPUT_PREFIX_UNAVAILABLE'

    def _owned(self):
        if self.owner != (os.getpid(), threading.get_native_id()):
            raise ValueError('owner')

    def _publication(self, value):
        if value is None: return None
        if (type(value) is not dict or set(value) != {'schema', 'identity_sha256', 'generation',
                    'active_programs', 'initial_program_outbox_sequence', 'economic'}
                or value.get('schema') != 'normal-source-publication-frontier-v1'
                or value.get('identity_sha256') != self.source
                or value.get('generation') != self.generation
                or type(value.get('active_programs')) is not list
                or len(value['active_programs']) > len(SCOPES)
                or value['active_programs'] != sorted(set(value['active_programs']))
                or SCOPE not in value['active_programs']
                or any(scope not in SCOPES for scope in value['active_programs'])):
            raise ValueError('source')
        cuts = value['initial_program_outbox_sequence']
        if (type(cuts) is not dict or set(cuts) != set(SCOPES)
                or any(v is not None and (type(v) is not int or not 0 <= v <= MAX_POSITION)
                       for v in cuts.values())
                or cuts[SCOPE] != self.inherited_upper):
            raise ValueError('source_cut')
        economic = value['economic']
        if (type(economic) is not dict or set(economic) != {'all', 'programs'}
                or type(economic['programs']) is not dict
                or set(economic['programs']) != set(SCOPES)):
            raise ValueError('programs')
        aggregate = prefix(economic['all'])
        programs = {scope: prefix(item) for scope, item in economic['programs'].items()}
        if aggregate['records'] != sum(item['records'] for item in programs.values()):
            raise ValueError('programs')
        # The registry validator owns all-program semantics; validate the exact
        # scoped comparison rather than combining unlike program chains.
        answer = programs[SCOPE]
        lower = self.inherited_upper
        if answer['records'] and lower is not None and answer['first_sequence'] <= lower:
            raise ValueError('source_cut')
        previous = self.expected_fresh
        if previous is not None:
            if answer['records'] < previous['records']:
                raise ValueError('regressing_source')
            if answer['records'] == previous['records'] and answer != previous:
                raise ValueError('changed_source')
        return answer

    def capture(self, first, rows, publication, *, as_of):
        """Stage fixed metadata from one original native read transaction."""
        if self.loss: return None
        try:
            self._owned()
            if (self.staged is not None or type(first) is not int or not 0 <= first <= MAX_POSITION
                    or type(rows) not in (tuple, list) or len(rows) > MAX_ROWS
                    or type(as_of) not in (int, float) or not math.isfinite(as_of)):
                raise ValueError('capture')
            expected = self._publication(publication)
            inherited, fresh = dict(self.inherited), dict(self.fresh)
            sequence, batch_sha = first, ZERO
            replay = first != self.cursor
            if replay and (self.previous is None or first != self.previous.first):
                raise ValueError('cursor')
            for row in rows:
                # Validate even a physical replay, without retaining its payload.
                if type(row) not in (tuple, list) or len(row) != 5:
                    raise ValueError('tuple')
                if type(row[0]) is not int or row[0] <= sequence or row[4] > as_of:
                    raise ValueError('visibility')
                sequence = row[0]
                batch_sha = checksum([batch_sha, row])
                upper = self.inherited_upper
                target = inherited if upper is not None and sequence <= upper else fresh
                updated = advance(empty_prefix() if replay else target, row)
                if not replay:
                    if target is inherited: inherited = updated
                    else: fresh = updated
            if replay and (sequence != self.cursor or self.previous.rows != len(rows)
                    or batch_sha != self.previous.batch_sha256):
                raise ValueError('changed_replay')
            if not replay:
                if self.expected_inherited is not None:
                    self._matches(inherited, self.expected_inherited)
                if expected is not None: self._matches(fresh, expected)
            ticket = _Capture(self, self.version, first, sequence, len(rows), batch_sha,
                tuple(inherited.items()), tuple(fresh.items()),
                None if expected is None else tuple(expected.items()), publication is not None, replay)
            self.staged = ticket
            return ticket
        except Exception:
            self.unavailable()
            return None

    @staticmethod
    def _matches(observed, expected):
        if observed['records'] > expected['records']:
            raise ValueError('excess')
        if observed['records'] == expected['records'] and observed != expected:
            raise ValueError('different_prefix')
        return observed == expected

    def committed(self, ticket):
        """Called only after the adapter checks the original FULL return/count."""
        if self.loss: return
        try:
            self._owned()
            if (type(ticket) is not _Capture or ticket is not self.staged
                    or ticket.issuer is not self or ticket.version != self.version):
                raise ValueError('ticket')
            inherited, fresh = dict(ticket.inherited), dict(ticket.fresh)
            if self.expected_inherited is not None:
                self._matches(inherited, self.expected_inherited)
            if ticket.expected_fresh is not None:
                self._matches(fresh, dict(ticket.expected_fresh))
            self.inherited, self.fresh = inherited, fresh
            if ticket.expected_fresh is not None:
                self.expected_fresh = dict(ticket.expected_fresh)
            self.source_metadata_present = ticket.source_metadata_present
            self.cursor = ticket.last
            if ticket.replay:
                self.replayed += ticket.rows
                if self.replayed > MAX_POSITION: raise ValueError('replay_bound')
            else: self.previous = ticket
            self.version += 1
            self.staged = None
        except Exception: self.unavailable()

    def census_sealed(self, value):
        """Only a complete independent fixed-cut metadata EOF supplies this."""
        try:
            self._owned()
            expected = prefix(value)
            if (expected['last_sequence'] != self.inherited_upper
                    or self.expected_inherited is not None and self.expected_inherited != expected):
                raise ValueError('inherited_census')
            self._matches(self.inherited, expected)
            self.expected_inherited = expected
        except Exception: self.unavailable()

    def snapshot(self):
        try:
            self._owned()
            inherited_complete = self.expected_inherited is not None and self.inherited == self.expected_inherited
            fresh_complete = (self.source_metadata_present and self.expected_fresh is not None
                and self.fresh == self.expected_fresh)
            result = dict(schema='pump-current-input-prefix-v1',
                state='UNKNOWN' if self.loss else 'OBSERVED' if inherited_complete
                    and fresh_complete and self.staged is None else 'INCOMPLETE',
                reason=self.loss, support_sha256=self.support, source_identity_sha256=self.source,
                inherited_expected=None if self.expected_inherited is None else dict(self.expected_inherited),
                inherited_retained=dict(self.inherited), inherited_upper=self.inherited_upper,
                source_expected=None if self.expected_fresh is None else dict(self.expected_fresh),
                source_retained=dict(self.fresh), inherited_prefix_retained=inherited_complete,
                source_issuance_prefix_retained=fresh_complete,
                cursor=self.cursor, physical_replay_rows=self.replayed,
                capture_pending=self.staged is not None,
                contract='EXACT_OUTBOX_TUPLES_AFTER_NATIVE_FULL_RETENTION_NOT_ECONOMIC_OR_JOB_COMPLETION',
                queued_native_work='SEPARATE_BOOT_SUPPORT_JOBS_NOT_CLOSED_BY_RETENTION',
                historical_completion=False, readiness_authority=False, funding_authority=False)
            if len(json.dumps(result, allow_nan=False).encode()) > 4096:
                raise ValueError('bound')
            return result
        except Exception:
            return dict(state='UNKNOWN', reason='INPUT_PREFIX_UNAVAILABLE', funding_authority=False)


@dataclass(frozen=True)
class _NativeCapture:
    issuer: object
    census: _KeyCapture | None
    retained: _Capture | None
    rows: int
    source_db: object


class PrivateCurrentInputContext:
    """Adapter for an actual accepted Pump owner and its private boot support."""
    def __init__(self, owner, support, *, epoch, process_instance):
        from ..operational.normal_pump_boot import NativePumpOwnerContext, current_pump_owner_context
        from ..operational.normal_boot_support import NativeBootSupportBoundary
        if (type(owner) is not NativePumpOwnerContext or owner is not current_pump_owner_context()
                or type(support) is not NativeBootSupportBoundary):
            raise ValueError('private_owner')
        self.owner=owner;self.support=support
        self.description=support.outbox_support(SCOPE)
        value=owner.identity();description=self.description
        if (type(description) is not dict or set(description)!={'schema','support_identity_sha256',
                'association','visibility_wall','database','upper_sequence'}
                or description['schema']!='normal-native-outbox-support-v1'
                or description['support_identity_sha256']!=support.identity_sha256
                or value['owner']['pid']!=os.getpid()
                or value['owner']['process_instance']!=process_instance):
            raise ValueError('support')
        association=description['association'];launch=value['launch']
        if (type(association) is not dict or set(association)!={'instance','record_sha256',
                'certificate_sha256','application_commit','application_tree','epoch_id',
                'inception_sha256','native_input_sha256','physical_generation_sha256'}
                or association['epoch_id']!=epoch
                or any(association[key]!=launch[key] for key in ('instance','record_sha256',
                    'certificate_sha256','application_commit','application_tree','epoch_id','inception_sha256'))):
            raise ValueError('association')
        for key in ('native_input_sha256','physical_generation_sha256'):_hash(association[key])
        database=description['database']
        if (type(database) is not dict or set(database)!={'relative_path','device','inode','schema_sha256'}
                or database['relative_path']!='shared/solana-evidence.sqlite'
                or any(type(database[key]) is not int or database[key]<0 for key in ('device','inode'))
                or database['inode']==0):
            raise ValueError('database')
        _hash(database['schema_sha256'])
        self.path=Path(value['root'])/database['relative_path']
        self.census=InheritedKeyCensus(description['upper_sequence'],description['visibility_wall'])
        self.prefixes=None;self.source=None;self.loss=None;self.staged=None

    def unavailable(self):
        if self.loss is None:self.loss='INPUT_PREFIX_UNAVAILABLE'
        self.census.unavailable()
        if self.prefixes is not None:self.prefixes.unavailable()

    def bind_source(self,value):
        try:
            self.owner.require_current()
            if (type(value) is not dict or value['instance_sha256']!=checksum(self.description['association']['instance'])
                    or value['epoch_sha256']!=checksum(self.description['association']['epoch_id'])):
                raise ValueError('source')
            if self.source is not None:
                if self.source!=value:raise ValueError('source_changed')
                return
            self.source=dict(value)
            self.prefixes=CurrentInputPrefixes(self.support.identity_sha256,None,
                value['identity_sha256'],value['generation'],inherited_upper=self.description['upper_sequence'])
        except Exception:self.unavailable()

    def _validate(self,reader,*,schema=False):
        self.owner.require_current()
        if (self.support.identity_sha256!=self.description['support_identity_sha256']
                or self.support.outbox_support(SCOPE)!=self.description
                or reader.path!=self.path or self.path.is_symlink()):
            raise ValueError('support_changed')
        actual=self.path.stat(follow_symlinks=False);database=self.description['database']
        if (not stat.S_ISREG(actual.st_mode) or (actual.st_dev,actual.st_ino)
                !=(database['device'],database['inode'])):
            raise ValueError('database_changed')
        if schema:
            cursor=reader.db.execute(SCHEMA_SQL)
            try:rows=cursor.fetchall()
            finally:cursor.close()
            if (len(rows)!=2 or [(row[0],row[1]) for row in rows]!=[
                    ('table','candidate_outbox'),('index','candidate_outbox_scope')]
                    or any(row[2] is None for row in rows)
                    or checksum(rows)!=database['schema_sha256']):
                raise ValueError('schema_changed')
        return True

    def capture(self,reader,first,rows,records,*,as_of,cancelled):
        if self.loss or self.prefixes is None:return None
        try:
            if self.staged is not None or len(rows)!=len(records):raise ValueError('capture')
            self._validate(reader,schema=True)
            cursor=reader.db.execute(FRONTIER_SQL)
            try:metadata=cursor.fetchone()
            finally:cursor.close()
            if metadata is None:publication=None
            else:
                from ..operational.normal_source_registry import validate_publication_frontier
                publication=validate_publication_frontier(metadata[0])
            key_capture=self.census.capture(reader.db,
                validate=lambda:self._validate(reader),cancelled=cancelled)
            tuples=[(raw[0],raw[3],record['scope'],raw[2],raw[8])
                for raw,record in zip(rows,records,strict=True)]
            retained=self.prefixes.capture(first,tuples,publication,as_of=as_of)
            ticket=_NativeCapture(self,key_capture,retained,len(rows),reader.db)
            self.staged=ticket;return ticket
        except Exception:self.unavailable();return None

    def retained(self,ticket,history,count,history_path):
        if self.loss:return
        try:
            self.owner.require_current()
            if (type(ticket) is not _NativeCapture or ticket is not self.staged or ticket.issuer is not self
                    or history.db.in_transaction or ticket.source_db.in_transaction
                    or str(history.path.resolve())!=history_path
                    or type(count) is not int or count!=ticket.rows):
                raise ValueError('retention')
            if ticket.census is not None:self.census.committed(ticket.census)
            if self.census.loss is not None:raise ValueError('census')
            if self.census.complete:self.prefixes.census_sealed(self.census.prefix)
            if ticket.retained is not None:self.prefixes.committed(ticket.retained)
            self.staged=None
        except Exception:self.unavailable()

    def snapshot(self):
        try:
            self.owner.require_current()
            return dict(schema='pump-current-input-context-v1',
                state='UNKNOWN' if self.loss else 'INCOMPLETE' if self.prefixes is None else self.prefixes.snapshot()['state'],
                support_identity_sha256=self.support.identity_sha256,
                private_owner_sha256=self.owner.identity_sha256,
                key_census=self.census.snapshot(),
                retained_prefix=None if self.prefixes is None else self.prefixes.snapshot(),
                native_queued_work='SEPARATE_BOOT_SUPPORT_GENERATIONS_NOT_CLOSED_BY_INPUT_RETENTION',
                full_market_rate='UNKNOWN_REQUIRES_ECONOMIC_CENSUS_AND_NATIVE_OUTCOMES',
                historical_completion=False,readiness_authority=False,funding_authority=False)
        except Exception:return dict(state='UNKNOWN',reason='INPUT_PREFIX_UNAVAILABLE',funding_authority=False)


def create_input_context(epoch,process_instance):
    """Legacy/no-private-context paths acquire no descriptor or database read."""
    try:
        from ..operational.normal_pump_boot import current_pump_owner_context
    except ImportError:return None
    owner=current_pump_owner_context()
    if owner is None:return None
    return PrivateCurrentInputContext(owner,owner.boot_support(),epoch=epoch,process_instance=process_instance)


def project_input_context(value):
    """Bounded public counts/hashes; serialized projections confer no authority."""
    if value is None:return None
    unavailable=dict(state='UNKNOWN',reason='INPUT_PREFIX_UNAVAILABLE',funding_authority=False)
    try:
        if type(value) is not dict or value.get('schema')!='pump-current-input-context-v1':
            return unavailable
        def integer(number):
            if type(number) is not int or not 0<=number<=MAX_POSITION:raise ValueError('integer')
            return number
        def boolean(number):
            if type(number) is not bool:raise ValueError('boolean')
            return number
        def nullable_integer(number):return None if number is None else integer(number)
        key=value['key_census']
        if type(key) is not dict or key['state'] not in ('UNKNOWN','EOF','INCOMPLETE'):
            raise ValueError('census')
        if key['reason'] not in (None,'KEY_CENSUS_UNAVAILABLE'):raise ValueError('reason')
        wall=key['visibility_wall']
        if type(wall) not in (int,float) or not math.isfinite(wall):raise ValueError('clock')
        population=prefix(key['population']);upper=nullable_integer(key['upper'])
        future=integer(key['future_at_support_cut']);leases=integer(key['leases'])
        expired=integer(key['expired_leases']);pending=boolean(key['capture_pending'])
        if (future>population['records'] or expired>leases
                or key['state']=='EOF' and population['last_sequence']!=upper):
            raise ValueError('census')
        census=dict(state=key['state'],reason=key['reason'],upper=upper,visibility_wall=wall,
            population=population,future_at_support_cut=future,leases=leases,expired_leases=expired,
            capture_pending=pending,
            contract='FIXED_CUT_KEY_ONLY_EOF_UNDER_TRUSTED_NATIVE_APPEND_ONLY_WRITER_NOT_DB_ENFORCED',
            historical_completion=False,readiness_authority=False,funding_authority=False)
        support=_hash(value['support_identity_sha256']);raw=value['retained_prefix'];retained=None
        if raw is not None:
            if (type(raw) is not dict or raw.get('schema')!='pump-current-input-prefix-v1'
                    or raw['state'] not in ('UNKNOWN','INCOMPLETE','OBSERVED')
                    or raw['reason'] not in (None,'INPUT_PREFIX_UNAVAILABLE')
                    or raw['support_sha256']!=support or raw['inherited_upper']!=upper):
                raise ValueError('retained')
            inherited=prefix(raw['inherited_retained']);fresh=prefix(raw['source_retained'])
            expected=None if raw['inherited_expected'] is None else prefix(raw['inherited_expected'])
            source=None if raw['source_expected'] is None else prefix(raw['source_expected'])
            old_done=boolean(raw['inherited_prefix_retained'])
            source_done=boolean(raw['source_issuance_prefix_retained'])
            capture_pending=boolean(raw['capture_pending'])
            if (old_done and (key['state']!='EOF' or expected!=population or inherited!=expected)
                    or source_done and (source is None or fresh!=source)
                    or raw['state']=='OBSERVED' and (not old_done or not source_done or capture_pending)):
                raise ValueError('completion')
            retained=dict(schema='pump-current-input-prefix-v1',state=raw['state'],reason=raw['reason'],
                support_sha256=support,source_identity_sha256=_hash(raw['source_identity_sha256']),
                inherited_expected=expected,inherited_retained=inherited,inherited_upper=upper,
                source_expected=source,source_retained=fresh,inherited_prefix_retained=old_done,
                source_issuance_prefix_retained=source_done,cursor=integer(raw['cursor']),
                physical_replay_rows=integer(raw['physical_replay_rows']),capture_pending=capture_pending,
                contract='EXACT_OUTBOX_TUPLES_AFTER_NATIVE_FULL_RETENTION_NOT_ECONOMIC_OR_JOB_COMPLETION',
                queued_native_work='SEPARATE_BOOT_SUPPORT_JOBS_NOT_CLOSED_BY_RETENTION',
                historical_completion=False,readiness_authority=False,funding_authority=False)
        state=value['state']
        if (state not in ('UNKNOWN','INCOMPLETE','OBSERVED') or state=='OBSERVED'
                and (retained is None or retained['state']!='OBSERVED' or key['state']!='EOF' or pending)):
            raise ValueError('state')
        result=dict(schema='pump-current-input-context-v1',state=state,
            support_identity_sha256=support,private_owner_sha256=_hash(value['private_owner_sha256']),
            key_census=census,retained_prefix=retained,
            native_queued_work='SEPARATE_BOOT_SUPPORT_GENERATIONS_NOT_CLOSED_BY_INPUT_RETENTION',
            full_market_rate='UNKNOWN_REQUIRES_ECONOMIC_CENSUS_AND_NATIVE_OUTCOMES',
            historical_completion=False,readiness_authority=False,funding_authority=False)
        if len(json.dumps(result,allow_nan=False).encode())>4096:raise ValueError('bound')
        return result
    except Exception:return unavailable
