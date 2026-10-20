"""Disposable public acquisition and replay of native, unfunded projections.

This is an engineering alternative while the production provider/funding boundary
cannot safely be attached to disposable state. It is never a canonical-history,
full-market-speed, readiness, recovery, protection or acceptance attestation.
"""
from contextlib import closing, contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import re
import signal
import sqlite3
import stat
import tempfile
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, build_opener

from .isolated_market_observer import (
    SOLANA, ROBINHOOD, NoRedirect, ObservationUnavailable, canonical, require,
    safe_runtime,
)

SCHEMA = 'isolated-public-native-workload-v1'
METHODS = {
    SOLANA: frozenset(('getSlot', 'getBlocks', 'getBlock')),
    ROBINHOOD: frozenset(('eth_chainId', 'eth_blockNumber', 'eth_getLogs',
        'eth_getBlockByNumber', 'eth_getTransactionReceipt',
        'eth_getTransactionByHash', 'eth_call', 'eth_getCode')),
}
MAX_BODY = 16 * 1024**2
MAX_CORPUS = 64 * 1024**2
MAX_REQUESTS = 150
MAX_EVENTS = 300
MAX_DISK = MAX_CORPUS + 1024**2
MAX_SOLANA_SLOT_WINDOW = 40

# These receipts admit fixed source literals, never an arbitrary exception
# message merely because its characters happen to look safe.
PUMP_FAILURE_CODES = frozenset((
    'isolated_pump_private_root_required', 'isolated_pump_private_root_permissions',
    'isolated_pump_financial_ancestor_refused', 'isolated_pump_production_environment_refused',
    'isolated_pump_fresh_root_required', 'isolated_pump_owned_database_required',
    'isolated_pump_database_byte_bound', 'isolated_pump_slot_shape',
    'isolated_pump_block_time', 'isolated_pump_block_identity',
    'isolated_pump_block_byte_bound', 'isolated_pump_transaction_bound',
    'isolated_pump_transaction_shape', 'isolated_pump_transaction_identity',
    'isolated_pump_account_key_shape', 'isolated_pump_transaction_slot',
    'isolated_pump_transaction_time', 'isolated_pump_transaction_order',
    'isolated_pump_complete_logs_required', 'isolated_pump_closed',
    'isolated_pump_observation_time', 'isolated_pump_block_replay_conflict',
    'isolated_pump_economic_time', 'isolated_pump_event_bound',
    'isolated_pump_restoration_mutated_economics',
    'isolated_pump_unexpected_authority_or_proof', 'isolated_pump_financial_state_forbidden',
))
PONS_FAILURE_CODES = frozenset((
    'pons_public_method_refused', 'pons_logical_batch_bound',
    'pons_projection_symlink_refused', 'pons_projection_financial_ancestor_refused',
    'pons_projection_private_owned_directory_required', 'pons_projection_foreign_state_refused',
    'pons_projection_marker_mismatch', 'pons_projection_unmarked_state_refused',
    'pons_projection_storage_bound', 'pons_projection_event_bound',
    'pons_projection_closed', 'pons_projection_range_bound',
    'pons_projection_noncontiguous_range', 'pons_projection_observation_clock',
    'pons_projection_history_unverified', 'pons_projection_history_mismatch',
))
WORKLOAD_FAILURE_CODES = frozenset((
    'native_chain_head_regressed', 'native_chain_head_shape', 'native_corpus_byte_limit',
    'native_corpus_completion_missing_event', 'native_corpus_completion_rpc_count',
    'native_corpus_completion_unverified', 'native_corpus_event_context_overlap',
    'native_corpus_event_hash', 'native_corpus_event_limit', 'native_corpus_event_missing',
    'native_corpus_event_rpc_link', 'native_corpus_event_shape', 'native_corpus_external_hash',
    'native_corpus_file_bound', 'native_corpus_integrity', 'native_corpus_link_limit',
    'native_corpus_path', 'native_corpus_request_limit', 'native_corpus_request_shape',
    'native_corpus_response_hash', 'native_corpus_response_limit', 'native_corpus_table',
    'native_corpus_unclosed', 'native_duration', 'native_pons_chain', 'native_pons_head',
    'native_processing_population_changed', 'native_provider_http_error',
    'native_provider_response_unavailable', 'native_provider_429', 'native_replay_cancelled',
    'native_replay_input_missing', 'native_replay_input_unused', 'native_replay_method',
    'native_rpc_method_refused', 'native_rpc_rejected', 'native_rpc_request_body_limit',
    'native_rpc_request_limit', 'native_rpc_response_identity', 'native_rpc_response_limit',
    'native_scratch_path', 'native_scratch_permissions', 'native_scratch_storage_admission',
    'native_solana_block_unavailable', 'native_solana_head', 'native_work_window_closed',
    'native_solana_enumeration_range', 'native_solana_enumeration_shape',
    'native_solana_enumeration_order', 'native_solana_absence_not_enumerated',
))


def private_directory(path):
    path = Path(path)
    require(path.resolve(strict=True) == path and not path.is_symlink(),
            'native_scratch_path')
    info = path.stat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
            and stat.S_IMODE(info.st_mode) == 0o700, 'native_scratch_permissions')
    return path


class Corpus:
    """One durable, bounded input corpus; no production locator or portfolio."""
    def __init__(self, root):
        self.root = private_directory(root)
        self.path = self.root / 'corpus.sqlite3'
        fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_RDWR, 0o600)
        os.close(fd)
        self.db = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False)
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
            CREATE TABLE rpc(id INTEGER PRIMARY KEY,endpoint TEXT,method TEXT,
                params TEXT,response TEXT,sha256 TEXT,elapsed REAL);
            CREATE TABLE events(id INTEGER PRIMARY KEY,lane TEXT,body TEXT,
                sha256 TEXT,observed REAL);
            CREATE TABLE rpc_events(rpc_id INTEGER PRIMARY KEY,event_id INTEGER NOT NULL);
            CREATE TABLE completions(event_id INTEGER PRIMARY KEY,body_sha256 TEXT NOT NULL,
                completed REAL NOT NULL,rpc_count INTEGER NOT NULL);
        ''')
        self.lock = threading.RLock()
        self.bytes = 0
        self.local = threading.local()

    def append(self, table, *values):
        require(table in ('rpc', 'events'), 'native_corpus_table')
        size = sum(len(v.encode()) for v in values if type(v) is str)
        with self.lock:
            require(self.bytes + size <= MAX_CORPUS, 'native_corpus_byte_limit')
            marks = ','.join('?' for _ in values)
            result = self.db.execute('INSERT INTO ' + table + ' VALUES(NULL,' + marks + ')', values)
            self.bytes += size
            return result.lastrowid

    def request(self, endpoint, method, params, response, elapsed):
        body = canonical(response)
        identity = self.append('rpc', endpoint, method, canonical(params), body,
            hashlib.sha256(canonical([endpoint, method, params, response]).encode()).hexdigest(), elapsed)
        event_id = getattr(self.local, 'event_id', None)
        if event_id is not None:
            with self.lock:
                self.db.execute('INSERT INTO rpc_events VALUES(?,?)', (identity, event_id))
        return identity

    def event(self, lane, value, observed):
        body = canonical(value)
        require(lane in ('pump', 'pons') and len(body.encode()) <= MAX_BODY
                and type(observed) in (int, float) and math.isfinite(observed)
                and observed >= 0, 'native_corpus_event_shape')
        with self.lock:
            require(self.db.execute('SELECT count(*) FROM events').fetchone()[0] < MAX_EVENTS,
                    'native_corpus_event_limit')
            return self.append('events', lane, body, hashlib.sha256(body.encode()).hexdigest(), observed)

    @contextmanager
    def recording(self, event_id):
        require(getattr(self.local, 'event_id', None) is None,
                'native_corpus_event_context_overlap')
        self.local.event_id = event_id
        try:
            yield
        finally:
            del self.local.event_id

    def complete(self, event_id):
        with self.lock:
            row = self.db.execute('SELECT sha256 FROM events WHERE id=?', (event_id,)).fetchone()
            require(row is not None, 'native_corpus_event_missing')
            count = self.db.execute('SELECT count(*) FROM rpc_events WHERE event_id=?',
                                    (event_id,)).fetchone()[0]
            self.db.execute('INSERT INTO completions VALUES(?,?,?,?)',
                            (event_id, row[0], time.time(), count))

    def counts(self):
        with self.lock:
            return {lane: dict(attempted_events=attempted, completed_events=completed)
                for lane, attempted, completed in self.db.execute('''
                    SELECT e.lane,count(*),count(c.event_id) FROM events e
                    LEFT JOIN completions c ON c.event_id=e.id GROUP BY e.lane''')}

    def close(self):
        self.db.close()


class PublicRPC:
    """Read methods only, fixed endpoints, global pacing, bounded stop on 429."""
    def __init__(self, corpus, stop, deadline, *, transport=None,
                 clock=time.monotonic, sleeper=time.sleep):
        self.corpus, self.stop, self.deadline = corpus, stop, deadline
        self.transport = transport or self._transport
        self.clock, self.sleeper = clock, sleeper
        self.lock = threading.Lock()
        self.last = None
        self.requests = 0
        self.http_429 = 0
        self.rejection = None

    @staticmethod
    def _transport(endpoint, payload, timeout):
        req = Request(endpoint, data=payload, method='POST', headers={
            'Content-Type': 'application/json', 'User-Agent': 'MM-Isolated-Native/1'})
        with build_opener(NoRedirect()).open(req, timeout=timeout) as response:
            raw = response.read(MAX_BODY + 1)
        require(len(raw) <= MAX_BODY, 'native_rpc_response_limit')
        return raw

    def call(self, endpoint, method, params):
        require(endpoint in METHODS and method in METHODS[endpoint]
                and type(params) is list, 'native_rpc_method_refused')
        if endpoint == SOLANA and method == 'getBlocks':
            require(len(params) == 3 and type(params[2]) is dict
                    and params[2] == {'commitment':'finalized'}, 'native_solana_enumeration_range')
            _validate_solana_enumeration(params[0], params[1], [])
        # Serialize transport too: concurrent lanes share one public pacing
        # budget and cannot manufacture throughput by multiplying requests.
        with self.lock:
            require(not self.stop.is_set() and self.clock() < self.deadline,
                    'native_work_window_closed')
            require(self.requests < MAX_REQUESTS, 'native_rpc_request_limit')
            if self.last is not None:
                delay = max(0.0, 1.0 - (self.clock() - self.last))
                require(self.clock() + delay < self.deadline, 'native_work_window_closed')
                if delay:
                    self.sleeper(delay)
            require(not self.stop.is_set() and self.clock() < self.deadline,
                    'native_work_window_closed')
            self.last = start = self.clock()
            self.requests += 1
            payload = canonical(dict(jsonrpc='2.0', id=self.requests,
                                     method=method, params=params)).encode()
            require(len(payload) <= 65536, 'native_rpc_request_body_limit')
            try:
                raw = self.transport(endpoint, payload, min(6, self.deadline - start))
                require(type(raw) is bytes and len(raw) <= MAX_BODY,
                        'native_rpc_response_limit')
                row = json.loads(raw)
                require(type(row) is dict and row.get('jsonrpc') == '2.0'
                        and type(row.get('id')) is int and row['id'] == self.requests,
                        'native_rpc_response_identity')
                if 'error' in row:
                    error = row['error']
                    code = error.get('code') if type(error) is dict else None
                    self.rejection = dict(method=method, code=code
                        if type(code) is int and -(2**31) <= code < 2**31 else None)
                    raise ObservationUnavailable('native_rpc_rejected')
                require('result' in row, 'native_rpc_rejected')
                self.corpus.request(endpoint, method, params, row['result'], self.clock() - start)
                return row['result']
            except HTTPError as error:
                if error.code == 429:
                    self.http_429 += 1
                    self.stop.set()
                    raise ObservationUnavailable('native_provider_429') from None
                raise ObservationUnavailable('native_provider_http_error') from None
            except (OSError, ValueError, TypeError):
                raise ObservationUnavailable('native_provider_response_unavailable') from None


def _corpus_file(path, expected_sha256=None):
    path = Path(path)
    private_directory(path.parent)
    require(path.resolve(strict=True) == path and not path.is_symlink(),
            'native_corpus_path')
    info = path.stat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
            and stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1
            and 0 < info.st_size <= MAX_DISK, 'native_corpus_file_bound')
    require(not any(Path(str(path) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')),
            'native_corpus_unclosed')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(65536), b''):
            digest.update(block)
    actual = digest.hexdigest()
    if expected_sha256 is not None:
        require(type(expected_sha256) is str and re.fullmatch('[0-9a-f]{64}', expected_sha256)
                and actual == expected_sha256, 'native_corpus_external_hash')
    return path, actual


@contextmanager
def _corpus_readonly(path):
    with closing(sqlite3.connect(Path(path).as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
        db.execute('PRAGMA query_only=ON')
        require(db.execute('PRAGMA integrity_check').fetchone() == ('ok',),
                'native_corpus_integrity')
        yield db


class ReplayRPC:
    """Hash-verified local response bytes only; no network fallback.

    Only replay() binds this local consistency check to an externally supplied
    whole-file digest. A recomputed row checksum alone authenticates no source.
    """
    def __init__(self, path, *, event_id=None):
        path, _ = _corpus_file(path)
        self.rows = {}
        total = 0
        with _corpus_readonly(path) as db:
            require(db.execute('SELECT count(*) FROM rpc').fetchone()[0] <= MAX_REQUESTS,
                    'native_corpus_request_limit')
            query = 'SELECT r.endpoint,r.method,r.params,r.response,r.sha256 FROM rpc r '
            args = ()
            if event_id is not None:
                require(type(event_id) is int and event_id > 0, 'native_corpus_event_missing')
                query += 'JOIN rpc_events e ON e.rpc_id=r.id WHERE e.event_id=? '
                args = (event_id,)
            for endpoint, method, params, body, checksum in db.execute(query + 'ORDER BY r.id', args):
                require(endpoint in METHODS and method in METHODS[endpoint]
                        and type(params) is str and len(params.encode()) <= 65536
                        and type(body) is str and len(body.encode()) <= MAX_BODY,
                        'native_corpus_response_limit')
                arguments, response = json.loads(params), json.loads(body)
                require(type(arguments) is list and canonical(arguments) == params,
                        'native_corpus_request_shape')
                total += len(params.encode()) + len(body.encode())
                require(total <= MAX_CORPUS, 'native_corpus_byte_limit')
                require(hashlib.sha256(canonical([endpoint, method, arguments, response]).encode()).hexdigest() == checksum,
                        'native_corpus_response_hash')
                self.rows.setdefault((endpoint, method, params), []).append(body)
        self.indices = {}

    def call(self, endpoint, method, params):
        require(endpoint in METHODS and method in METHODS[endpoint], 'native_replay_method')
        key = (endpoint, method, canonical(params))
        index = self.indices.get(key, 0)
        require(key in self.rows and index < len(self.rows[key]), 'native_replay_input_missing')
        self.indices[key] = index + 1
        return json.loads(self.rows[key][index])

    def assert_consumed(self):
        require(all(self.indices.get(key, 0) == len(rows) for key, rows in self.rows.items()),
                'native_replay_input_unused')


def resources():
    usage = resource.getrusage(resource.RUSAGE_SELF)
    value = dict(monotonic=time.monotonic(), cpu_seconds=usage.ru_utime + usage.ru_stime,
        peak_rss_bytes=usage.ru_maxrss * 1024, process_io=None, io_pressure=None,
        scope='isolated_worker_process_with_host_io_pressure', cgroup_limits=None,
        cgroup_resource_state='UNKNOWN', production_processes_measured=False)
    try:
        value['process_io'] = {k: int(v) for k, v in (
            line.split(':', 1) for line in Path('/proc/self/io').read_text().splitlines())}
    except (OSError, ValueError):
        pass
    try:
        value['io_pressure'] = {line.split()[0]: dict(
            item.split('=', 1) for item in line.split()[1:])
            for line in Path('/proc/pressure/io').read_text().splitlines()}
    except (OSError, ValueError):
        pass
    return value


def _directory(root, name):
    path = root / name
    path.mkdir(mode=0o700)
    return path


def _storage_admission(root):
    usage = os.statvfs(root)
    free = usage.f_bavail * usage.f_frsize
    total = usage.f_blocks * usage.f_frsize
    used = (total - usage.f_bfree * usage.f_frsize) / total if total else 1
    require(total > 0 and free >= 5 * 1024**3 + 256 * 1024**2 and used < .85,
            'native_scratch_storage_admission')
    return dict(available_bytes=free, filesystem_bytes=total, filesystem_used_fraction=used)


def _failure(error):
    # Reporting must remain available when component import/startup failed.
    # These type names admit only the fixed literal codes below; they never
    # authorize work or serialize a component's arbitrary exception text.
    kind = type(error)
    pons_component = (kind.__module__ == 'meme_machine.operational.isolated_native_pons'
                      and kind.__name__ == 'PonsProjectionUnavailable')
    pons_boundary = (kind.__module__ == 'meme_machine.lanes.pons'
                     and kind.__name__ == 'BoundaryError')
    allowed = (WORKLOAD_FAILURE_CODES if type(error) is ObservationUnavailable else
               PUMP_FAILURE_CODES if type(error) is ValueError else
               PONS_FAILURE_CODES if pons_component else frozenset())
    candidate = error.args[0] if len(error.args) == 1 else None
    code = candidate if type(candidate) is str and candidate in allowed else None
    site = None
    # Unexpected AttributeError previously hid its origin behind a generic
    # public-workload refusal and cancelled the other lane. Attribute source
    # location is a fixed module/function/line triple from the pinned package;
    # exception messages, local variables, file paths and provider bodies stay private.
    if pons_boundary or type(error) is AttributeError:
        application = Path(__file__).resolve().parents[1]
        trace = error.__traceback__
        while trace is not None:
            frame = trace.tb_frame
            module = frame.f_globals.get('__name__')
            function = frame.f_code.co_name
            if (type(module) is str and re.fullmatch(r'meme_machine\.[a-zA-Z_][a-zA-Z_0-9.]*', module)
                    and re.fullmatch('[a-zA-Z_][a-zA-Z_0-9]{0,100}', function)
                    and Path(frame.f_code.co_filename).resolve().is_relative_to(application)
                    and 0 < trace.tb_lineno < 10**7):
                site = dict(module=module, function=function, line=trace.tb_lineno)
            trace = trace.tb_next
    name = type(error).__name__
    return dict(state='PARTIAL_OR_BLOCKED', error_type=name
        if re.fullmatch('[a-zA-Z_][a-zA-Z_0-9]{0,79}', name) else 'UnknownError',
        code=code, failure_site=site)


def _projection(lane, root):
    if lane == 'pump':
        from .isolated_native_pump import PumpNativeProjection
        return PumpNativeProjection(_directory(root, lane))
    from .isolated_native_pons import PonsNativeProjection
    return PonsNativeProjection(_directory(root, lane))


def _finish_projection(projection, outcome):
    if projection is None:
        return
    try:
        outcome['projection'] = projection.snapshot()
        outcome['restoration'] = projection.reopen()
    except Exception as error:
        receipt = _failure(error)
        outcome.update(state='PARTIAL_OR_BLOCKED', restoration_error_type=receipt['error_type'])
        outcome['restoration_failure'] = receipt
    finally:
        try:
            projection.close()
            outcome['projection_closed'] = True
        except Exception as error:
            receipt = _failure(error)
            outcome.update(state='PARTIAL_OR_BLOCKED', close_error_type=receipt['error_type'],
                           projection_closed=False)
            outcome['close_failure'] = receipt


class Progress:
    """One sampled slot/block population; decoded blocks and absences stay distinct."""
    def __init__(self, lane):
        self.lane, self.first, self.latest = lane, None, None
        self.processed = 0
        self.last_completed = None
        self.last_accounted = None
        self.enumerated_blocks = 0
        self.enumerated_absent = 0
        self.enumerations = []
        self._enumeration = None
        self.samples = []

    def sample(self, head=None, *, first=None, last=None):
        if head is not None:
            require(type(head) is int and 0 <= head < 2**63, 'native_chain_head_shape')
            require(self.latest is None or head >= self.latest, 'native_chain_head_regressed')
            if self.first is None:
                self.first = head
            self.latest = head
        if first is not None:
            require(type(first) is int and type(last) is int and self.first is not None
                    and first <= last <= self.latest
                    and first == (self.first if self.last_accounted is None else self.last_accounted + 1),
                    'native_processing_population_changed')
            if self.lane == 'pump':
                require(self._enumeration is not None and first == last and first in self._enumeration[2],
                        'native_processing_population_changed')
            self.processed += last - first + 1
            self.last_completed = last
            self.last_accounted = last
        self._record()

    def enumerate_slots(self, first, last, blocks):
        """Record public absence as acquisition evidence, never decoded economics."""
        _validate_solana_enumeration(first, last, blocks)
        require(self.lane == 'pump' and self.first is not None and last <= self.latest
                and first == (self.first if self.last_accounted is None else self.last_accounted+1)
                and (not self.enumerations or first > self.enumerations[-1]['last_slot']),
                'native_processing_population_changed')
        absent = [slot for slot in range(first, last+1) if slot not in blocks]
        self.enumerated_blocks += len(blocks)
        self.enumerated_absent += len(absent)
        self.enumerations.append(dict(first_slot=first, last_slot=last,
            returned_block_slots=list(blocks), enumerated_absent_slots=absent,
            source='public_getBlocks_finalized_request', canonical_completeness=False,
            absence_scope='provider_reported_only; backend_disagreement_or_unavailability_not_excluded'))
        self._enumeration = (first, last, frozenset(blocks))
        self._record()

    def reported_absent(self, first, last):
        """Advance only over absent slots from the exact bounded enumeration."""
        window = self._enumeration
        require(self.lane == 'pump' and window is not None
                and type(first) is int and type(last) is int and window[0] <= first <= last <= window[1]
                and first == (self.first if self.last_accounted is None else self.last_accounted+1)
                and not any(slot in window[2] for slot in range(first, last+1)),
                'native_solana_absence_not_enumerated')
        self.last_accounted = last
        self._record()

    def _record(self):
        offered = 0 if self.first is None else self.latest - self.first + 1
        self.samples.append(dict(monotonic=time.monotonic(), wall_epoch_seconds=time.time(),
            sampled_head=self.latest, completed_through=self.last_completed,
            accounted_through=self.last_accounted,
            offered_chain_units=offered, completed_chain_units=self.processed,
            enumerated_block_chain_units=self.enumerated_blocks,
            provider_enumerated_absent_chain_units=self.enumerated_absent,
            unenumerated_head_span_chain_units=(offered-self.enumerated_blocks-self.enumerated_absent
                                               if self.lane == 'pump' else None),
            sampled_backlog_population=('provider_enumerated_available_block_slots'
                                       if self.lane == 'pump' else 'sampled_robinhood_head_span'),
            sampled_backlog_chain_units=(self.enumerated_blocks-self.processed
                                        if self.lane == 'pump' else offered-self.processed)))

    def summary(self):
        return dict(chain_units='solana_slots' if self.lane == 'pump' else 'robinhood_blocks',
            population='initial_sampled_head_through_latest_sampled_head',
            completion_semantics=('decoded_returned_blocks_only; public_absences_are_acquisition_facts'
                                  if self.lane == 'pump' else 'native_consumed_robinhood_blocks'),
            public_absences_are_chain_proof=False,
            latest_actual_head_at_shutdown='UNKNOWN', samples=self.samples,
            public_slot_enumerations=self.enumerations)


def _validate_solana_enumeration(first, last, blocks):
    require(type(first) is int and type(last) is int and 0 <= first <= last < 2**63
            and last-first < MAX_SOLANA_SLOT_WINDOW, 'native_solana_enumeration_range')
    require(type(blocks) is list and len(blocks) <= last-first+1
            and all(type(slot) is int and first <= slot <= last for slot in blocks),
            'native_solana_enumeration_shape')
    require(all(left < right for left, right in zip(blocks, blocks[1:])),
            'native_solana_enumeration_order')


def solana_block_slots(rpc, first, head):
    """Bounded public enumeration, retained by the existing RPC corpus recorder."""
    require(type(first) is int and type(head) is int and 0 <= first <= head < 2**63,
            'native_solana_enumeration_range')
    last = min(head, first+MAX_SOLANA_SLOT_WINDOW-1)
    blocks = rpc.call(SOLANA, 'getBlocks', [first, last, {'commitment':'finalized'}])
    _validate_solana_enumeration(first, last, blocks)
    return last, blocks


def _partial(**facts):
    return dict(schema=SCHEMA, result='PARTIAL_NATIVE_ALTERNATIVE', financial_authority=False,
        production_state_written=False, historical_callbacks_settled=False,
        production_equivalent=False, full_market_speed_proven=False,
        held_protection_exercised=False, acceptance_passed=False, **facts)


def _join_workers(threads, stop):
    # Native work cannot safely be killed in a Python thread. Keep ownership
    # and SQLite open until all workers actually exit. The workflow process
    # group TERM/KILL boundary is the absolute guard for noncooperative work.
    stop.set()
    for thread in threads:
        while thread.is_alive():
            thread.join(timeout=.25)


def capture(root, *, duration=120):
    require(type(duration) is int and 12 <= duration <= 120, 'native_duration')
    root = private_directory(root)
    storage = _storage_admission(root)
    corpus = Corpus(root)
    stop = threading.Event()
    start = time.monotonic()
    rpc = PublicRPC(corpus, stop, start + duration)
    outcomes = {lane: dict(state='NOT_STARTED') for lane in ('pump', 'pons')}
    snapshots = [resources()]

    def worker(lane):
        projection = None
        progress = Progress(lane)
        try:
            projection = _projection(lane, root)
            next_unit = None
            if lane == 'pons':
                require(rpc.call(ROBINHOOD, 'eth_chainId', []) == '0x1237', 'native_pons_chain')
            while not stop.is_set() and time.monotonic() < rpc.deadline:
                _storage_admission(root)
                if lane == 'pump':
                    head = rpc.call(SOLANA, 'getSlot', [{'commitment': 'finalized'}])
                    require(type(head) is int and head > 0, 'native_solana_head')
                else:
                    raw = rpc.call(ROBINHOOD, 'eth_blockNumber', [])
                    require(type(raw) is str and re.fullmatch('0x[0-9a-fA-F]+', raw), 'native_pons_head')
                    head = int(raw, 16)
                progress.sample(head)
                if next_unit is None:
                    next_unit = head
                if next_unit > head:
                    stop.wait(1)
                    continue
                seen = time.time()
                if lane == 'pump':
                    upper, block_slots = solana_block_slots(rpc, next_unit, head)
                    progress.enumerate_slots(next_unit, upper, block_slots)
                    cursor = next_unit
                    for slot in block_slots:
                        if slot > cursor:
                            progress.reported_absent(cursor, slot-1)
                        seen = time.time()
                        block = rpc.call(SOLANA, 'getBlock', [slot, dict(
                            commitment='finalized', encoding='json', transactionDetails='full',
                            rewards=False, maxSupportedTransactionVersion=1)])
                        require(type(block) is dict, 'native_solana_block_unavailable')
                        event_id = corpus.event(lane,
                            dict(slot=slot, block=block, acquired_head=head), seen)
                        projection.consume(slot, block, observed_at=seen)
                        corpus.complete(event_id)
                        progress.sample(first=slot, last=slot)
                        cursor = slot+1
                    if cursor <= upper:
                        progress.reported_absent(cursor, upper)
                else:
                    upper = min(head, next_unit + 39)
                    event_id = corpus.event(lane,
                        dict(first=next_unit, last=upper, acquired_head=head), seen)
                    with corpus.recording(event_id):
                        projection.consume(next_unit, upper, rpc, observed_at=seen)
                    # An input becomes completed only after native consumption.
                    corpus.complete(event_id)
                    progress.sample(first=next_unit, last=upper)
                next_unit = upper + 1
            outcomes[lane] = dict(state='BOUNDED_WINDOW_ENDED')
        except Exception as error:
            outcomes[lane] = _failure(error)
            stop.set()
        finally:
            outcomes[lane]['processing'] = progress.summary()
            _finish_projection(projection, outcomes[lane])

    old_handler = signal.getsignal(signal.SIGTERM)
    started = []
    try:
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        threads = [threading.Thread(target=worker, args=(lane,), name='isolated-' + lane)
                   for lane in ('pump', 'pons')]
        for thread in threads:
            thread.start()
            started.append(thread)
        while any(thread.is_alive() for thread in started):
            for thread in started:
                thread.join(timeout=.25)
            if time.monotonic() >= rpc.deadline:
                stop.set()
            if time.monotonic() - snapshots[-1]['monotonic'] >= 2:
                snapshots.append(resources())
        snapshots.append(resources())
        counts = corpus.counts()
        for lane in outcomes:
            outcomes[lane].update(counts.get(lane, dict(attempted_events=0, completed_events=0)))
        return _partial(lanes=outcomes, elapsed_seconds=time.monotonic() - start,
            provider_requests=rpc.requests, provider_http_429=rpc.http_429,
            provider_rpc_rejection=getattr(rpc, 'rejection', None),
            resource_samples=snapshots, corpus_bytes=corpus.bytes, storage_admission=storage,
            all_started_workers_joined=True,
            cleanup_completed=all(row.get('projection_closed') is True for row in outcomes.values()),
            native_cancellation_bounded=False,
            absolute_process_guard='workflow_225_seconds_TERM_then_6_seconds_KILL')
    finally:
        _join_workers(started, stop)
        signal.signal(signal.SIGTERM, old_handler)
        corpus.close()


def replay(corpus_path, root, expected_sha256):
    """Replay completed disposable inputs bound to an external whole-file SHA.

    The digest identifies retained bytes, not canonical market authentication.
    Incomplete events and their RPCs are excluded. Every included Pons response
    must be consumed exactly once by its original completed event.
    """
    require(type(expected_sha256) is str and re.fullmatch('[0-9a-f]{64}', expected_sha256),
            'native_corpus_external_hash')
    root = private_directory(root)
    path, actual = _corpus_file(corpus_path, expected_sha256)
    events = {lane: [] for lane in ('pump', 'pons')}
    counts = {lane: dict(attempted_events=0, completed_events=0) for lane in events}
    with _corpus_readonly(path) as db:
        require(db.execute('SELECT count(*) FROM events').fetchone()[0] <= MAX_EVENTS,
                'native_corpus_event_limit')
        require(db.execute('SELECT count(*) FROM rpc_events').fetchone()[0] <= MAX_REQUESTS
                and db.execute('SELECT count(*) FROM completions').fetchone()[0] <= MAX_EVENTS,
                'native_corpus_link_limit')
        require(db.execute('SELECT count(*) FROM rpc_events x LEFT JOIN rpc r ON x.rpc_id=r.id '
                           'LEFT JOIN events e ON x.event_id=e.id '
                           'WHERE r.id IS NULL OR e.id IS NULL').fetchone()[0] == 0,
                'native_corpus_event_rpc_link')
        require(db.execute('SELECT count(*) FROM completions c LEFT JOIN events e '
                           'ON c.event_id=e.id WHERE e.id IS NULL').fetchone()[0] == 0,
                'native_corpus_completion_missing_event')
        total = 0
        query = ('SELECT e.id,e.lane,e.body,e.sha256,e.observed,c.body_sha256,c.completed,c.rpc_count '
                 'FROM events e LEFT JOIN completions c ON c.event_id=e.id ORDER BY e.id')
        for identity, lane, body, checksum, observed, complete_hash, completed, rpc_count in db.execute(query):
            require(lane in events and type(body) is str and len(body.encode()) <= MAX_BODY
                    and type(observed) in (int, float) and math.isfinite(observed)
                    and observed >= 0, 'native_corpus_event_shape')
            total += len(body.encode())
            require(total <= MAX_CORPUS, 'native_corpus_byte_limit')
            require(hashlib.sha256(body.encode()).hexdigest() == checksum, 'native_corpus_event_hash')
            value = json.loads(body)
            require(type(value) is dict and canonical(value) == body, 'native_corpus_event_shape')
            counts[lane]['attempted_events'] += 1
            if complete_hash is None:
                continue
            require(complete_hash == checksum and type(completed) in (int, float)
                    and math.isfinite(completed) and completed >= observed,
                    'native_corpus_completion_unverified')
            require(type(rpc_count) is int and 0 <= rpc_count <= MAX_REQUESTS
                    and rpc_count == db.execute('SELECT count(*) FROM rpc_events WHERE event_id=?',
                                               (identity,)).fetchone()[0],
                    'native_corpus_completion_rpc_count')
            require(type(value.get('acquired_head')) is int and 0 <= value['acquired_head'] < 2**63,
                    'native_corpus_event_shape')
            if lane == 'pump':
                require(type(value.get('slot')) is int and 0 < value['slot'] <= value['acquired_head']
                        and type(value.get('block')) is dict, 'native_corpus_event_shape')
            else:
                require(type(value.get('first')) is int and type(value.get('last')) is int
                        and 0 <= value['first'] <= value['last'] <= value['acquired_head']
                        and value['last'] - value['first'] < 40, 'native_corpus_event_shape')
            counts[lane]['completed_events'] += 1
            events[lane].append((identity, value, observed))
    # Freeze validated responses before constructing native projections. Each
    # event gets its own replay cursor, never a different event's response.
    clients = {identity: ReplayRPC(path, event_id=identity)
               for identity, _, _ in events['pons']}
    _corpus_file(path, actual)
    storage = _storage_admission(root)
    outcomes = {}
    snapshots = [resources()]
    stop = threading.Event()
    started = []
    begin = time.monotonic()

    def worker(lane):
        projection = None
        outcome = dict(state='REPLAY_COMPLETED_INPUTS', replayed_events=0, **counts[lane])
        outcomes[lane] = outcome
        try:
            projection = _projection(lane, root)
            for identity, value, observed in events[lane]:
                if stop.is_set():
                    raise ObservationUnavailable('native_replay_cancelled')
                _storage_admission(root)
                if lane == 'pump':
                    projection.consume(value['slot'], value['block'], observed_at=observed)
                else:
                    rpc = clients[identity]
                    projection.consume(value['first'], value['last'], rpc, observed_at=observed)
                    rpc.assert_consumed()
                outcome['replayed_events'] += 1
        except Exception as error:
            outcome.update(_failure(error))
            stop.set()
        finally:
            _finish_projection(projection, outcome)

    try:
        for lane in events:
            thread = threading.Thread(target=worker, args=(lane,), name='replay-' + lane)
            thread.start()
            started.append(thread)
        for thread in started:
            thread.join()
        snapshots.append(resources())
        _corpus_file(path, actual)
        return _partial(lanes=outcomes, corpus_sha256=actual,
            source_provenance='externally_identified_local_corpus_only', provider_requests=0,
            elapsed_seconds=time.monotonic() - begin, resource_samples=snapshots,
            storage_admission=storage, native_cancellation_bounded=False,
            all_started_workers_joined=True,
            cleanup_completed=all(row.get('projection_closed') is True for row in outcomes.values()))
    finally:
        _join_workers(started, stop)


def main():
    safe_runtime()
    base = Path(os.environ['RUNNER_TEMP']).resolve(strict=True)
    os.umask(0o077)
    root = Path(tempfile.mkdtemp(prefix='mm-isolated-native-' + os.environ['GITHUB_RUN_ID'] + '-', dir=base))
    result = capture(root)
    result['corpus_sha256'] = _corpus_file(root / 'corpus.sqlite3')[1]
    body = canonical(result) + '\n'
    with (root / 'summary.json').open('x') as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    print(body, end='')
    # A partial alternative is never a successful production capability gate.
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
