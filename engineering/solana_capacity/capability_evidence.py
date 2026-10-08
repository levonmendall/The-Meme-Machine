"""Two disposable production joins; independent statuses remain indispensable.

No economic expectation, arrival clock, decision deadline or population is
retimed to make the comparison pass. Private database paths alone are normalized
in checksummed consumer references. Failure identities never create economics.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
from types import SimpleNamespace

from .capability_limits import CapabilityStop
from meme_machine.solana_candidate_join import CandidateTransactionJoin, scope_labels
from meme_machine.solana_evidence_plane import EvidenceWriter, digest
from meme_machine.solana_evidence_service import FinalizedFence
from meme_machine.solana_native_evidence import signature, transaction_error
from meme_machine.solana_rolling_history import program_scope
from meme_machine.solana_selective_history import PROGRAMS
from meme_machine.solana_selective_source import install, commit_scout, commit_control, commit_candidates

FAMILIES = ('pump', 'pumpswap')
ADDRESSES = {PROGRAMS[f]: program_scope(f) for f in FAMILIES}
LABELS = {label: scope.split(':')[1] for scope, label in scope_labels(ADDRESSES).items()}
PROJECTIONS = ('market_observations', 'candidate_lifecycle', 'evidence_bindings',
               'rolling_origins', 'candidate_checkpoints', 'candidate_coverage',
               'candidate_gaps', 'candidate_pending_proofs', 'rolling_economic_addresses',
               'candidate_history_outbox')


@contextmanager
def candidate_destination(path):
    prior = os.environ.get('MM_SOLANA_CANDIDATE_HISTORY_DB')
    os.environ['MM_SOLANA_CANDIDATE_HISTORY_DB'] = str(path)
    try:
        yield
    finally:
        if prior is None:
            os.environ.pop('MM_SOLANA_CANDIDATE_HISTORY_DB', None)
        else:
            os.environ['MM_SOLANA_CANDIDATE_HISTORY_DB'] = prior


def json_digest(value):
    return digest(value)


class Side:
    def __init__(self, root, endpoint_identity, wall, mono, budget):
        self.root, self.wall, self.budget = root, wall, budget
        root.mkdir()
        self.writer = EvidenceWriter(root/'canonical.sqlite', clock=lambda: wall[0])
        self.state = SimpleNamespace(writer=self.writer, fence=FinalizedFence(
            self.writer, endpoint_identity=endpoint_identity))
        with candidate_destination(root/'candidate.sqlite'):
            self.history = install(self.state)
        self.history.clock = self.history.lifecycle.clock = lambda: wall[0]
        self.history.startup.begin()
        self.join = None
        self.control = None
        self.commit_metrics = dict(count=0, seconds=0.0, maximum_seconds=0.0)
        self.mono = mono
        self.writer.db.executescript('''
            CREATE TABLE capability_commits(slot INTEGER PRIMARY KEY,parent INTEGER,
                hash TEXT,previous_hash TEXT,seen REAL);
            CREATE TABLE capability_witnesses(slot INTEGER,signature TEXT,tx_index INTEGER,
                scopes TEXT,error TEXT,available REAL,PRIMARY KEY(slot,signature));
        ''')
        # SQLite work is also interruptible during a slow source commit/query.
        self.writer.db.set_progress_handler(self.progress, 2000)

    def progress(self):
        try:
            self.budget.resources()
            return int(self.budget.stop.is_set())
        except CapabilityStop:
            return 1

    def start(self, floor, tip, control_floor, full):
        self.join = CandidateTransactionJoin(ADDRESSES, full, clock=self.mono,
            filtered_from_slot=floor, max_join_seconds=120)
        if self.control is None:
            self.control = CandidateTransactionJoin({}, set(), clock=self.mono,
                filtered_from_slot=control_floor, max_join_seconds=120)
        for family in FAMILIES:
            self.history.startup.feed_ack(family, floor, max(floor, tip))

    def candidate(self, frame):
        if frame is None:
            return
        started = time.monotonic()
        commit_candidates(self.state, frame, ADDRESSES, 'capability-candidate', publish=False)
        block = frame.update.block
        with self.writer.transaction():
            self.writer.db.execute('INSERT OR IGNORE INTO capability_commits VALUES(?,?,?,?,?)',
                (block.slot, block.parent_slot, block.blockhash, block.parent_blockhash, frame.seen))
            for sig, index, scopes, error, available in frame.candidate_statuses:
                self.writer.db.execute('INSERT OR IGNORE INTO capability_witnesses VALUES(?,?,?,?,?,?)',
                    (block.slot, sig, index, json.dumps(scopes), json.dumps(error, sort_keys=True), available))
        self.history.startup.native(FAMILIES)
        self.publish()
        elapsed = time.monotonic()-started
        self.commit_metrics['count'] += 1
        self.commit_metrics['seconds'] += elapsed
        self.commit_metrics['maximum_seconds'] = max(self.commit_metrics['maximum_seconds'], elapsed)

    def publish(self):
        self.history.lifecycle.publish()
        self.history.startup.advance()

    def rows_digest(self, table, *, canonical=False, consumer=False):
        db = self.writer.db
        owned = None
        if consumer:
            path = self.root/'candidate.sqlite'
            if not path.exists():
                return dict(rows=0, sha256=hashlib.sha256().hexdigest())
            owned = db = sqlite3.connect(path.as_uri()+'?mode=ro', uri=True)
        try:
            if not db.execute('SELECT 1 FROM sqlite_master WHERE name=?', (table,)).fetchone():
                return dict(rows=0, sha256=hashlib.sha256().hexdigest())
            fields = ('identity,scope,slot,signature,transaction_index,event_index,hash,first_seen,body'
                      if canonical else '*')
            checksum = hashlib.sha256()
            count = 0
            for row in db.execute('SELECT '+fields+' FROM '+table+' ORDER BY 1,2'):
                self.budget.resources()
                row = list(row)
                if consumer and table == 'canonical_event_refs':
                    ref = json.loads(row[8])
                    if digest(ref) != row[9]:
                        raise CapabilityStop('consumer_reference_checksum')
                    ref['path'] = '<canonical.sqlite>'
                    row[8] = json.dumps(ref, sort_keys=True, separators=(',', ':'))
                    row[9] = digest(ref)
                row = [v.hex() if isinstance(v, bytes) else v for v in row]
                raw = json.dumps(row, sort_keys=True, separators=(',', ':'))
                # A private storage path is not an economic comparison field.
                raw = raw.replace(str(self.root/'canonical.sqlite'), '<canonical.sqlite>')
                checksum.update(raw.encode()+b'\n')
                count += 1
            return dict(rows=count, sha256=checksum.hexdigest())
        finally:
            if owned:
                owned.close()

    def projection(self):
        result = {t: self.rows_digest(t) for t in PROJECTIONS}
        result['canonical_evidence'] = self.rows_digest('canonical_evidence', canonical=True)
        result['native_witnesses'] = self.rows_digest('capability_witnesses')
        for table in ('canonical_event_refs', 'candidates', 'work'):
            result['consumer:'+table] = self.rows_digest(table, consumer=True)
        return result

    def pending(self):
        if not self.join:
            return dict(not_started=True)
        j = self.join
        return dict(slots=len(j.pending), bytes=j.pending_bytes,
                    early_logs=len(j.early_logs), early_log_bytes=j.early_log_bytes,
                    recent_bytes=j.recent_bytes, recent_slots=len(j.recent),
                    missing_logs=sum(len(s['missing_logs']) for s in j.pending.values()),
                    prefix_bytes=j.replay_prefix_bytes)

    def close(self):
        self.writer.db.set_progress_handler(None, 0)
        self.writer.close()


class PairedEvidence:
    def __init__(self, out, endpoint_identity, budget, *, mono):
        self.out, self.budget, self.wall = Path(out), budget, [0.0]
        self.reference = Side(self.out/'reference', endpoint_identity, self.wall, mono, budget)
        self.alternative = Side(self.out/'alternative', endpoint_identity, self.wall, mono, budget)
        self.db = sqlite3.connect(self.out/'comparison.sqlite', isolation_level=None)
        self.db.executescript('''
            CREATE TABLE early_ws(ordinal INTEGER PRIMARY KEY,slot INTEGER,signature TEXT,
                family TEXT,logs TEXT,error TEXT,seen REAL);
            CREATE TABLE ws(slot INTEGER,signature TEXT,family TEXT,logs_hash TEXT,error TEXT,
                seen REAL,bytes INTEGER,PRIMARY KEY(slot,signature,family));
            CREATE TABLE statuses(slot INTEGER,signature TEXT,family TEXT,tx_index INTEGER,
                error TEXT,bank INTEGER,seen REAL,PRIMARY KEY(slot,signature,family));
            CREATE TABLE bodies(slot INTEGER,signature TEXT,tx_index INTEGER,logs_hash TEXT,
                error TEXT,seen REAL,bytes INTEGER,PRIMARY KEY(slot,signature));
            CREATE TABLE traffic(ordinal INTEGER PRIMARY KEY,transport TEXT,component TEXT,
                slot INTEGER,bytes INTEGER,seen REAL,phase TEXT);
        ''')
        self.floor = None
        self.phase = 'paired'
        self.ordinal = 0
        self.suppression_floor = None

    def start(self, floor, tip, control_floor):
        if self.floor is not None:
            raise CapabilityStop('filter_rebuild_forbidden')
        self.floor = floor
        for side, full in ((self.reference, set()), (self.alternative, {PROGRAMS['pumpswap']})):
            side.start(floor, tip, control_floor, full)
        # Retain the original bounded WS prefix in SQLite rather than an extra
        # raw-frame queue. Only the partial first slot falls below the real floor.
        for slot, sig, family, logs, error, seen in self.db.execute(
                'SELECT slot,signature,family,logs,error,seen FROM early_ws ORDER BY ordinal'):
            if error == 'null':
                self.log_joins(slot, sig, family, json.loads(logs), seen)
        self.db.execute('DROP TABLE early_ws')

    def traffic(self, transport, component, slot, size, seen):
        self.ordinal += 1
        phase = self.phase
        if phase == 'paired' and self.budget.clock()-self.budget.started >= self.budget.limits.paired_seconds:
            phase = 'transition'
        self.db.execute('INSERT INTO traffic VALUES(?,?,?,?,?,?,?)',
                        (self.ordinal, transport, component, slot, size, seen, phase))

    def fact(self, table, key, values):
        names = {'ws': ('slot', 'signature', 'family'),
                 'statuses': ('slot', 'signature', 'family'), 'bodies': ('slot', 'signature')}[table]
        old = self.db.execute('SELECT * FROM '+table+' WHERE '+' AND '.join(n+'=?' for n in names), key).fetchone()
        # seen/bytes may differ for duplicate delivery; immutable facts may not.
        identity_fields = {'ws': 5, 'statuses': 6, 'bodies': 5}[table]
        row = (*key, *values)
        if old is not None and old[:identity_fields] != row[:identity_fields]:
            raise CapabilityStop(table+'_identity_contradiction')
        self.db.execute('INSERT OR IGNORE INTO '+table+' VALUES('+','.join('?' for _ in row)+')', row)
        self.check_identity(key[0], key[1])

    def check_identity(self, slot, sig):
        bodies = self.db.execute('SELECT tx_index,logs_hash,error FROM bodies WHERE slot=? AND signature=?', (slot, sig)).fetchone()
        statuses = self.db.execute('SELECT family,tx_index,error FROM statuses WHERE slot=? AND signature=?', (slot, sig)).fetchall()
        logs = self.db.execute('SELECT family,logs_hash,error FROM ws WHERE slot=? AND signature=?', (slot, sig)).fetchall()
        for family, index, error in statuses:
            if bodies and (bodies[0] != index or bodies[2] != error):
                raise CapabilityStop('body_status_contradiction')
            for log_family, log_hash, log_error in logs:
                if log_family == family and log_error != error:
                    raise CapabilityStop('ws_status_contradiction')
        for _, log_hash, error in logs:
            if bodies and (bodies[1] != log_hash or bodies[2] != error):
                raise CapabilityStop('ws_body_contradiction')
        if len({(h, e) for _, h, e in logs}) > 1:
            raise CapabilityStop('multi_program_log_contradiction')

    def ws(self, family, slot, sig, logs, error, size, seen):
        self.wall[0] = seen
        self.traffic('websocket', family+('_success' if error is None else '_failed'), slot, size, seen)
        err = json.dumps(error, sort_keys=True)
        self.fact('ws', (slot, sig, family), (json_digest(logs), err, seen, size))
        if self.floor is None:
            self.db.execute('INSERT INTO early_ws VALUES(?,?,?,?,?,?,?)',
                (self.ordinal, slot, sig, family, json.dumps(logs), err, seen))
        elif error is None:
            self.log_joins(slot, sig, family, logs, seen)

    def log_joins(self, slot, sig, family, logs, seen):
        self.reference.candidate(self.reference.join.feed_log(slot, sig, logs, None, seen))
        if family == 'pump':
            self.alternative.candidate(self.alternative.join.feed_log(slot, sig, logs, None, seen))

    def native(self, family, update, size, seen):
        self.wall[0] = seen
        kind = update.WhichOneof('update_oneof')
        item = getattr(update, kind) if kind else None
        slot = getattr(item, 'slot', None)
        self.traffic('yellowstone', family+':'+str(kind), slot, size, seen)
        if kind in ('ping', 'pong'):
            return
        if family == 'pump':
            if kind != 'account':
                raise CapabilityStop('scout_update_filter')
            for side in (self.reference, self.alternative):
                commit_scout(side.state, update, seen)
                side.publish()
            return
        if family == 'shared':
            for side in (self.reference, self.alternative):
                frame = side.control.feed(update, size, seen)
                if frame:
                    commit_control(side.state, frame)
                    side.publish()
            return
        if kind == 'transaction_status':
            sig = signature(bytes(item.signature))
            error = transaction_error(bytes(item.err.err)) if item.HasField('err') else None
            for label in update.filters:
                if label not in LABELS:
                    raise CapabilityStop('native_status_labels')
                self.fact('statuses', (slot, sig, LABELS[label]),
                    (item.index, json.dumps(error, sort_keys=True), item.bank_id, seen))
        if kind == 'transaction':
            tx = item.transaction
            sig = signature(bytes(tx.signature))
            error = transaction_error(bytes(tx.meta.err.err)) if tx.meta.HasField('err') else None
            self.fact('bodies', (slot, sig), (tx.index, json_digest(list(tx.meta.log_messages)),
                                             json.dumps(error, sort_keys=True), seen, size))
        if kind != 'transaction':
            self.reference.candidate(self.reference.join.feed(update, size, seen))
        self.alternative.candidate(self.alternative.join.feed(update, size, seen))

    def compare(self):
        if self.floor is None:
            return dict(complete=False, reasons=['original_ws_frontier_unavailable'])
        a, b = self.reference, self.alternative
        a.publish()
        b.publish()
        left, right = a.projection(), b.projection()
        differences = [table for table in left if left[table] != right[table]]
        commits_a = list(a.writer.db.execute('SELECT slot,parent,hash,previous_hash FROM capability_commits ORDER BY slot'))
        commits_b = list(b.writer.db.execute('SELECT slot,parent,hash,previous_hash FROM capability_commits ORDER BY slot'))
        common = sorted(set(commits_a) & set(commits_b))
        intervals = [(p[0], c[0]-1) for p, c in zip(common, common[1:])
                     if p[0] == c[1] and p[2] == c[3]]
        lower = self.floor
        upper = intervals[-1][1] if intervals else lower-1
        missing = self.db.execute('''SELECT COUNT(*) FROM ws w LEFT JOIN statuses s
            USING(slot,signature,family) WHERE w.slot BETWEEN ? AND ? AND s.signature IS NULL''', (lower, upper)).fetchone()[0]
        successes = dict(self.db.execute('''SELECT s.family,COUNT(*) FROM statuses s JOIN ws w
            USING(slot,signature,family) WHERE s.slot BETWEEN ? AND ? AND s.error='null' GROUP BY s.family''', (lower, upper)))
        missing_bodies = self.db.execute('''SELECT COUNT(*) FROM statuses s LEFT JOIN bodies b
            USING(slot,signature) WHERE s.family='pumpswap' AND s.error='null'
            AND s.slot BETWEEN ? AND ? AND b.signature IS NULL''', (lower, upper)).fetchone()[0]
        unmatched_success = self.db.execute('''SELECT COUNT(*) FROM statuses s LEFT JOIN ws w
            USING(slot,signature,family) WHERE s.error='null' AND s.slot BETWEEN ? AND ?
            AND w.signature IS NULL''', (lower, upper)).fetchone()[0]
        reasons = []
        if len(intervals) < 3:
            reasons.append('fewer_than_three_complete_common_intervals')
        if any(successes.get(f, 0) == 0 for f in FAMILIES):
            reasons.append('pump_or_pumpswap_success_unsampled')
        if missing or missing_bodies or unmatched_success:
            reasons.append('missing_independent_status_log_or_body')
        if differences:
            reasons.append('canonical_history_or_clock_difference')
        if commits_a != commits_b:
            reasons.append('unequal_committed_interval_population')
        for side in (a, b):
            if not side.history.startup.snapshot().get('released'):
                reasons.append('model_b_publication_not_released')
                break
        return dict(complete=not reasons, reasons=reasons, common_intervals=intervals,
                    differing_projections=differences, reference=left, alternative=right,
                    sampled_successes=successes, missing_statuses=missing,
                    missing_bodies=missing_bodies, unmatched_successes=unmatched_success,
                    reference_pending=a.pending(), alternative_pending=b.pending(),
                    clocks='ORIGINAL_RECEIPTS_UNMODIFIED', funded_position_sample='UNSAMPLED')

    def suppression_result(self):
        if self.suppression_floor is None:
            return dict(attempted=False, complete=False)
        j = self.alternative.join
        lo, hi = self.suppression_floor, j.completed
        missing = self.db.execute('''SELECT COUNT(*) FROM statuses s LEFT JOIN bodies b USING(slot,signature)
            WHERE s.family='pumpswap' AND s.error='null' AND s.slot BETWEEN ? AND ? AND b.signature IS NULL''', (lo, hi)).fetchone()[0]
        success, failures = self.db.execute("""SELECT SUM(error='null'),SUM(error!='null') FROM statuses
            WHERE family='pumpswap' AND slot BETWEEN ? AND ?""", (lo, hi)).fetchone()
        witnesses = self.alternative.writer.db.execute('SELECT COUNT(*) FROM capability_witnesses WHERE slot BETWEEN ? AND ?', (lo, hi)).fetchone()[0]
        commits = list(self.alternative.writer.db.execute('SELECT slot,parent FROM capability_commits WHERE slot>=? ORDER BY slot', (lo,)))
        linked = sum(parent == prior for (prior, _), (_, parent) in zip(commits, commits[1:]))
        return dict(attempted=True, complete=not missing and linked > 0 and witnesses > 0 and bool(success),
                    missing_success_bodies=missing, linked_intervals=linked,
                    pumpswap_successes=success or 0, pumpswap_failures=failures or 0,
                    economic_success_sample='SAMPLED' if success else 'UNSAMPLED_NO_WINDOW_EXTENSION',
                    independent_witnesses=witnesses, final_tail=self.alternative.pending())

    def traffic_report(self, comparison, received_phase=None):
        rows = [dict(transport=t, component=c, phase=p, bytes=n, messages=count)
                for t, c, p, n, count in self.db.execute('''SELECT transport,component,phase,
                    SUM(bytes),COUNT(*) FROM traffic GROUP BY transport,component,phase''')]
        n, size = self.db.execute("SELECT COUNT(*),COALESCE(SUM(bytes),0) FROM traffic WHERE component='pumpswap:transaction'").fetchone()
        intervals = comparison.get('common_intervals', [])
        lo, hi = (intervals[0][0], intervals[-1][1]) if intervals else (1, 0)
        matched = dict(self.db.execute('''SELECT component,SUM(bytes) FROM traffic WHERE phase='paired'
            AND slot BETWEEN ? AND ? GROUP BY component''', (lo, hi)))
        ws = matched.get('pumpswap_success', 0) + matched.get('pumpswap_failed', 0)
        full = matched.get('pumpswap:transaction', 0)
        count = self.db.execute("SELECT COUNT(*) FROM traffic WHERE phase='paired' AND component='pumpswap:transaction' AND slot BETWEEN ? AND ?", (lo, hi)).fetchone()[0]
        identities = self.db.execute("SELECT COUNT(*) FROM statuses WHERE family='pumpswap' AND error='null' AND slot BETWEEN ? AND ?", (lo, hi)).fetchone()[0]
        latency = self.db.execute('''SELECT COUNT(*),MIN(b.seen-w.seen),AVG(b.seen-w.seen),MAX(b.seen-w.seen)
            FROM bodies b JOIN ws w USING(slot,signature) WHERE w.family='pumpswap' ''').fetchone()
        classified_total = self.db.execute("SELECT COALESCE(SUM(bytes),0) FROM traffic WHERE phase='paired'").fetchone()[0]
        paired_total = (sum(n for (phase,transport,_),n in received_phase.items()
                            if phase=='paired' and transport in ('websocket','yellowstone'))
                        if received_phase is not None else classified_total)
        paired_http = (sum(n for (phase,transport,_),n in received_phase.items() if phase=='paired' and transport=='http')
                       if received_phase is not None else None)
        paired_full = self.db.execute("SELECT COALESCE(SUM(bytes),0) FROM traffic WHERE phase='paired' AND component='pumpswap:transaction'").fetchone()[0]
        paired_ws = self.db.execute("SELECT COALESCE(SUM(bytes),0) FROM traffic WHERE phase='paired' AND component IN ('pumpswap_success','pumpswap_failed','ack:2')").fetchone()[0]
        return dict(all_delivery_components=rows, full_native_success_messages=n,
                    full_native_success_application_bytes=size,
                    mean_full_native_success_bytes=size/n if n else None,
                    matching_interval_ws_replacement_bytes=ws,
                    matching_interval_native_full_bytes=full,
                    matching_interval_native_success_count=count,
                    matching_interval_distinct_native_success_identities=identities,
                    matching_interval_break_even=ws/count if count else None,
                    paired_component_delta_bytes=ws-full if comparison.get('complete') else None,
                    observed_paired_streaming_total=paired_total,
                    observed_paired_http_bytes=paired_http,
                    paired_streaming_bytes_not_routed_to_evidence=paired_total-classified_total,
                    unrouted_bytes='CHARGED_IN_BOTH_ALLOCATIONS_INCLUDING_HEARTBEAT_STOPPING_AND_CANCELLATION_DATA',
                    allocated_architecture_a_streaming_bytes=paired_total-paired_full,
                    allocated_architecture_b_streaming_bytes=paired_total-paired_ws,
                    paired_session_component_delta_bytes=paired_ws-paired_full,
                    paired_ws_replacement_outside_common_intervals=paired_ws-ws,
                    paired_native_full_outside_common_intervals=paired_full-full,
                    paired_allocation_break_even_per_common_success=(paired_ws-(paired_full-full))/identities if identities else None,
                    break_even_limit='PAIRED_COMPONENT_ALLOCATION_ONLY; DIFFERENTIAL_RECOVERY_HTTP_AND_POSITION_OVERHEAD_UNMEASURED',
                    allocation='MEASURED_COMPONENTS_ON_ONE_SIMULTANEOUS_SESSION_NOT_TWO_INDEPENDENT_PROVIDER_RUNS',
                    original_native_minus_ws_receipt_seconds=dict(samples=latency[0], minimum=latency[1], average=latency[2], maximum=latency[3]),
                    engineering_commit_metrics=dict(reference=self.reference.commit_metrics, alternative=self.alternative.commit_metrics),
                    verified_provider_savings_bytes=0,
                    disposition='INCONCLUSIVE_UNTIL_ALL_SESSION_OVERHEAD_AND_RECOVERY_ARE_RECONCILED',
                    additional_http_requests=0, recovery='NO_RECONNECT_OR_RETRY_AUTHORIZED',
                    positions='INDEPENDENT_PRODUCTION_INTERESTS_PRESERVED_NOT_INSTANTIATED')

    def close(self):
        self.db.close()
        self.reference.close()
        self.alternative.close()
