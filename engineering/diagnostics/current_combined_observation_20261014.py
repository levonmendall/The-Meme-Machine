"""One funding-closed diagnostic; install/preflight/authorization happen separately.

The prepared PAPER unit must invoke this module's ``supervise`` command with the
same output directory, RuntimeMaxSec=1800, TimeoutStopSec=65 and Restart=no.
``observe`` requests one start and collects existing local facts. Neither command
installs configuration, changes provider controls, retries, or rewinds state.
An overdue drain is a failure requiring recovery, never a promised safe deadline.
"""
import argparse
from contextlib import closing
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import sqlite3
import subprocess
import sys
import time

from engineering.diagnostics.diagnostic_access_20261014 import ACCESS_PROPERTIES, check_access
from meme_machine.operational.observation import atomic_json, numeric
from meme_machine.operational.supervisor import Supervisor
from meme_machine.solana_selective_runtime import CONTROL
from meme_machine.solana_rolling_history import program_scope

UNIT = 'meme-machine-paper.service'
OUTPUT_BYTES = 32 * 1024**2
TERMINAL_BYTES = 64 * 1024
INPUT_BYTES = 1024 * 1024
GUARD_BYTES = 1024
FULL_SAMPLE_SECONDS = 5
RESERVE_BYTES = 5 * 1024**3
MISSING_EDGES = ('per_event_precommit_timing', 'proof_eligibility_reason', 'oldest_missing_join_component',
                 'pons_request_ancestry', 'sql_wait_actor')
UNAVAILABLE = 'UNAVAILABLE'
COUNTER_BYTES = 64 * 1024
COHORT_SIZE = 32
NATIVE_OPERATIONS = frozenset('pump.' + name for name in (
    'candidate_history_open', 'confirmation_restore', 'accounting_genesis_read', 'accounting_restore',
    'terminal_recovery', 'pipeline_open', 'initial_report', 'runtime_evidence_open', 'evidence_broker_open',
    'sessions_open', 'survivor_worker_open', 'survivor_recovery_submit', 'survivor_recovery_wait',
    'survivor_runtime_restore',
    'current_runtime_restore', 'observed_candidates_restore', 'observed_candidate_events',
    'startup_cleanup.candidate_history_open', 'startup_cleanup.accounting_restore',
    'startup_cleanup.pipeline_open', 'startup_cleanup.runtime_evidence_open',
    'startup_cleanup.evidence_broker_open', 'startup_cleanup.sessions_open',
    'startup_cleanup.survivor_worker_open')) | frozenset(('pons.shared_capital_restore',))


def native_lifecycle(lanes):
    """Essential native startup/cancellation facts before descriptive clipping."""
    def cancellation_stack(row):
        if not isinstance(row,dict):return UNAVAILABLE
        frames=[];provided=row.get('frames')
        for frame in provided[:8] if isinstance(provided,list) else ():
            if not isinstance(frame,dict):continue
            module=frame.get('module');function=frame.get('function');line=frame.get('line')
            if (isinstance(module,str) and len(module)<=160 and
                    re.fullmatch(r'meme_machine(?:\.[A-Za-z_][A-Za-z0-9_]*)+',module) and
                    isinstance(function,str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,79}',function) and
                    type(line) is int and 0<line<10**7):
                frames.append(dict(module=module,function=function,line=line))
        result={key:row.get(key) if finite_number(row.get(key)) else UNAVAILABLE for key in
                ('at','monotonic','pid','reporter_native_thread_id',
                 'target_native_thread_id','target_python_thread_id')}
        captured=row.get('state')=='CAPTURED' and bool(frames)
        reason=row.get('reason')
        result.update(state='CAPTURED' if captured else UNAVAILABLE,
            reason=reason if reason in ('owned_python_frames','probe_failed','main_thread_unavailable',
                'main_thread_frame_missing','no_owned_frames') else UNAVAILABLE,
            frames=frames,frames_truncated=row.get('frames_truncated') is True,
            scope='MAIN_THREAD_PYTHON_FRAMES_NOT_SQL_OR_LOCK_ATTRIBUTION')
        return result
    def operation(row):
        if not isinstance(row, dict) or row.get('operation') not in NATIVE_OPERATIONS:
            return UNAVAILABLE
        result = {key: row.get(key) if finite_number(row.get(key)) else UNAVAILABLE for key in
                  ('at', 'monotonic', 'pid', 'native_thread_id', 'completed_at', 'elapsed_seconds')}
        result.update(operation=row['operation'], state=row.get('state') if row.get('state') in
                      ('ACTIVE', 'COMPLETE', 'ERROR', 'CANCELLED') else UNAVAILABLE)
        error = row.get('error_type')
        if isinstance(error, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,79}', error):
            result['error_type'] = error
        return result
    result = {}
    for name in ('pump', 'pons'):
        lane = lanes.get(name, {})
        lane = lane if isinstance(lane, dict) else {}
        signal_row = lane.get('cancellation_signal')
        signal_facts = {key: signal_row.get(key) if finite_number(signal_row.get(key)) else UNAVAILABLE
                        for key in ('signal', 'at', 'monotonic', 'pid', 'native_thread_id')
                        } if isinstance(signal_row, dict) else UNAVAILABLE
        recent = lane.get('native_recent_operations')
        result[name] = dict(phase=numeric(lane.get('phase')) or UNAVAILABLE,
            reconciled=lane['reconciled'] if type(lane.get('reconciled')) is bool else 'UNKNOWN',
            native_operation=operation(lane.get('native_operation')),
            native_recent_operations=[operation(row) for row in recent[:8]] if isinstance(recent, list) else UNAVAILABLE,
            cancellation_signal=signal_facts,cancellation_stack=cancellation_stack(lane.get('cancellation_stack')))
    return result


def final_native_health(root, expected_pid, origin):
    """Bounded final projection, not a graceful-drain or reconciliation verdict."""
    if time.monotonic() >= origin + 1865 or expected_pid is None:
        return dict(available=False, reason='FINAL_HEALTH_DEADLINE_OR_PID_UNAVAILABLE')
    try:
        health = read_json(Path(root) / 'health.json')
        if health.get('pid') != expected_pid:
            return dict(available=False, reason='FINAL_HEALTH_SUPERVISOR_PID_MISMATCH')
        shutdown = health.get('native_shutdown')
        rows = []
        if isinstance(shutdown, list):
            for row in shutdown[:48]:
                if not isinstance(row, dict) or row.get('operation') not in (
                    'signal_requested', 'signal_sent', 'wait_started', 'wait_timeout', 'wait_completed', 'already_exited'):
                    continue
                facts = {key: row.get(key) if finite_number(row.get(key)) else UNAVAILABLE for key in
                    ('at', 'monotonic', 'caller_pid', 'caller_native_thread_id', 'target_pid', 'signal',
                     'timeout_seconds', 'exit_code')}
                facts.update(operation=row['operation'], lane=row.get('lane') if row.get('lane') in ('pump','pons') else UNAVAILABLE)
                run = row.get('run_id')
                facts['run_id'] = run if isinstance(run, str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', run) else UNAVAILABLE
                rows.append(facts)
        return dict(available=True, supervisor_pid=expected_pid,
            health_at=health.get('at') if isinstance(health.get('at'), str) and re.fullmatch(r'[0-9T:.+Z-]{1,40}', health['at']) else UNAVAILABLE,
            native_lifecycle=native_lifecycle(health.get('lanes', {})),
            native_shutdown=rows if isinstance(shutdown, list) else UNAVAILABLE,
            native_shutdown_truncated=isinstance(shutdown, list) and len(shutdown) > 48,
            scope='FINAL_PROJECTION_NOT_PROOF_OF_DRAIN_OR_COMPLETED_RECONCILIATION')
    except (OSError, ValueError, TypeError, AttributeError):
        return dict(available=False, reason='FINAL_NATIVE_HEALTH_UNAVAILABLE')


def finite_number(value):
    return type(value) is int or type(value) is float and math.isfinite(value)


def required_join_state(health, now_monotonic):
    """Two already-computed samples, never a coverage/readiness assertion."""
    ipc=health.get('ipc', {})
    source=ipc.get('join_state', {}) if isinstance(ipc, dict) else {}
    owner=health.get('owner_scheduler', {})
    admission=owner.get('owner_admission', {}) if isinstance(owner, dict) else {}
    generation=admission.get('generation') if isinstance(admission, dict) else None
    result={}
    fields=('filtered_from_slot','completed','pending_slots','pending_bytes',
        'early_log_count','early_log_bytes','early_log_min_slot','early_log_max_slot',
        'oldest_slot','oldest_age','oldest_finality','oldest_statuses','oldest_bodies',
        'oldest_missing_logs','replay_prefix_bytes')
    for plane in ('rolling','candidate'):
        row=source.get(plane) if isinstance(source, dict) else None
        if not isinstance(row, dict):
            result[plane]=UNAVAILABLE;continue
        numbers={key:row.get(key) if finite_number(row.get(key)) else UNAVAILABLE
                 for key in ('source_pid','sampled_at','sampled_at_monotonic')}
        session=row.get('session');captured=row.get('source_generation')
        session=session if isinstance(session,str) and re.fullmatch(r'[0-9a-f]{32}',session) else UNAVAILABLE
        captured=captured if isinstance(captured,str) and re.fullmatch(r'[0-9a-f]{32}',captured) else UNAVAILABLE
        sampled=row.get('sampled_at_monotonic')
        age=(now_monotonic-sampled if finite_number(now_monotonic) and finite_number(sampled)
             and now_monotonic>=sampled else UNAVAILABLE)
        state=row.get('state') if row.get('state') in ('ACTIVE','CLOSED') else UNAVAILABLE
        if row.get('plane')!=plane:status='PLANE_MISMATCH'
        elif type(row.get('source_pid')) is not int or row.get('source_pid')!=health.get('pid'):status='SOURCE_PID_MISMATCH'
        elif captured==UNAVAILABLE or session==UNAVAILABLE:status='PROVENANCE_UNAVAILABLE'
        elif captured!=generation:status='SOURCE_GENERATION_MISMATCH'
        elif age==UNAVAILABLE:status='SAMPLE_TIME_UNAVAILABLE'
        elif state=='CLOSED':status='CLOSED'
        elif state!= 'ACTIVE':status='STATE_UNAVAILABLE'
        elif age>FULL_SAMPLE_SECONDS:status='STALE'
        else:status='SAMPLED_CURRENT_NOT_COVERAGE'
        join=row.get('join', {});queue=row.get('commit_queue', {})
        join=join if isinstance(join,dict) else {}
        queue=queue if isinstance(queue,dict) else {}
        facts={key:join.get(key) if finite_number(join.get(key)) else UNAVAILABLE for key in fields}
        facts['oldest_meta']=join.get('oldest_meta') if type(join.get('oldest_meta')) is bool else UNAVAILABLE
        result[plane]=dict(numbers,plane=plane,session=session,source_generation=captured,
            sample_state=state,status=status,observation_age_seconds=age,join=facts,
            commit_queue={key:queue.get(key) if type(queue.get(key)) is int and queue[key]>=0
                          else UNAVAILABLE for key in ('count','bytes')},
            scope='LAST_SAMPLED_SESSION_NOT_POPULATION_OWNER_HELD_BATCH_INCLUDED')
    return result


def required_counters(health, *, now_monotonic=None):
    """Select fixed diagnostic schemas before the descriptive 128-key clip.

    This is not an arbitrary dictionary copier. Unrecognized keys and all text
    values are excluded; overflow makes the section unavailable, never complete.
    Missing counters are not zero and collection clocks are supplied by caller.
    """
    ipc = health.get('ipc', {})
    storage = health.get('storage_maintenance', {})
    if not isinstance(ipc, dict):
        ipc = {}
    if not isinstance(storage, dict):
        storage = {}
    stages = ('source_commit', 'candidate_development', 'archive_plan', 'archive_commit_plan',
              'retention', 'maintenance_health', 'health_ipc', 'health_scheduler',
              'checkpoint_prepare', 'checkpoint_finish', 'maintenance_decision',
              'history_dispatch', 'history_apply', 'candidate_delivery_capture', 'candidate_delivery_ack')
    components = ('control', 'candidate', 'scout', 'history_publication', 'delivery_accounting')
    stages_re = '|'.join(stages)
    components_re = '|'.join(components)
    aggregate_pattern = re.compile(
        r'(?:owner\.stage\.(?:' + stages_re + r')(?:\.component\.(?:' + components_re + r'))?\.'
        r'(?:calls|(?:queue|execution|execution_cpu)_(?:total|peak)_microseconds)|'
        r'owner\.priority[0-6]\.(?:queue|execution)_(?:total|peak)_microseconds|'
        r'checkpoint\.(?:calls|total_microseconds|peak_microseconds|busy|bulk_incomplete|tail_deferred|'
        r'boundary_calls|boundary_total_microseconds|boundary_peak_microseconds|boundary_reclaimed|'
        r'incomplete|reclaimed|yielded))')
    aggregate = {key: value for key, value in ipc.items()
                 if isinstance(key, str) and aggregate_pattern.fullmatch(key) and finite_number(value)}
    pipeline_pattern = re.compile(
        r'(?:(?:joined_frame|economic_prepared|evidence_timing|publication_timing|history_delivery_timing|'
        r'decode_timing):(?:shared|rolling|candidate)|native_frame:'
        r'(?:shared|pump|pumpswap|discovery|replay|candidate|rolling):'
        r'(?:slot|block_meta|transaction_status|transaction|account|ping|pong|unknown))')
    metric_pattern = re.compile(
        r'(?:calls|records|bytes|latest_slot|latest_durable_wall|latest_joined_wall|latest_received_wall|'
        r'latest_provider_created_wall|unmeasured_calls|unmeasured_bytes_frames|'
        r'(?:decode|decode_cpu|cpu_seconds|transfer_and_wait_seconds|wall_seconds|owner_queue|execution)'
        r'_(?:total|peak)_microseconds)')
    pipeline = {}
    source_pipeline = ipc.get('pipeline', {})
    if isinstance(source_pipeline, dict):
        for key, values in source_pipeline.items():
            if not isinstance(key, str) or not pipeline_pattern.fullmatch(key) or not isinstance(values, dict):
                continue
            pipeline[key] = {name: value for name, value in values.items()
                             if isinstance(name, str) and metric_pattern.fullmatch(name) and finite_number(value)}
    transaction_pattern = re.compile(r'(?:begin|commit)\.(?:calls|(?:wall|cpu)_(?:total|peak)_microseconds)')
    transactions = storage.get('owner_sql_transactions', {})
    transactions = {key: value for key, value in transactions.items()
                    if isinstance(key, str) and transaction_pattern.fullmatch(key) and finite_number(value)
                    } if isinstance(transactions, dict) else {}
    storage_pattern = re.compile(r'(?:source_commit|archive_plan|archive_commit|retention|repair_apply)\.'
                                 r'(?:calls|failed|yielded|total_microseconds|peak_microseconds)')
    storage_stages = {key: value for key, value in storage.items()
                      if isinstance(key, str) and storage_pattern.fullmatch(key) and finite_number(value)}
    owner = health.get('owner_scheduler', {})
    owner_pattern = re.compile(r'(?:owner_pid|native_thread_id|queued|queue_peak|rejected|admission_waited|aged_selections|'
        r'nonurgent_fifo_selections|background_yields|checkpoint_handoffs|checkpoint_handoff_(?:total|peak)_us|'
        r'priority[0-6]\.(?:completed|(?:queue|execution)_(?:total|peak)_us))')
    owner_counters = {key: value for key, value in owner.items()
        if isinstance(key, str) and owner_pattern.fullmatch(key) and finite_number(value)
        } if isinstance(owner, dict) else {}
    def operation(row):
        if not isinstance(row,dict):return UNAVAILABLE
        stage=row.get('stage');component=row.get('component');module=row.get('origin_module')
        if stage not in (*stages,'UNLABELLED') or component not in (*components,'NONE'):
            return UNAVAILABLE
        result={key:row[key] for key in ('priority','sequence','pid','native_thread_id',
            'origin_line','started_monotonic','observed_monotonic','completed_monotonic',
            'queue_microseconds','elapsed_microseconds','execution_microseconds',
            'execution_cpu_microseconds') if finite_number(row.get(key))}
        result.update(stage=stage,component=component,
            origin_module=module if isinstance(module,str) and re.fullmatch(r'meme_machine\.[A-Za-z0-9_.]{1,128}',module) else UNAVAILABLE)
        if row.get('outcome') in ('COMPLETED','FAILED'):result['outcome']=row['outcome']
        return result
    recent=owner.get('recent_slow_operations') if isinstance(owner,dict) else None
    operations=dict(active=operation(owner.get('active_operation')) if isinstance(owner,dict) else UNAVAILABLE,
        recent=[operation(row) for row in recent] if isinstance(recent,list) and len(recent)<=8 else UNAVAILABLE)
    result = dict(ipc_pipeline=pipeline or UNAVAILABLE, ipc_aggregate=aggregate or UNAVAILABLE,
                  native_join_state=required_join_state(health,
                      time.monotonic() if now_monotonic is None else now_monotonic),
                  owner_sql_transactions=transactions or UNAVAILABLE,
                  owner_scheduler=owner_counters or UNAVAILABLE,
                  owner_operations=operations,
                  storage_stages=storage_stages or UNAVAILABLE,
                  scope='EXPLICIT_FIXED_COUNTER_SCHEMAS_NOT_OVERLAPPING_STAGE_TOTAL')
    if len(json.dumps(result, sort_keys=True, allow_nan=False).encode()) > COUNTER_BYTES:
        return dict(available=False, reason='REQUIRED_COUNTER_BOUND')
    return dict(available=True, **result)


def validate_revision(expected, actual):
    if not re.fullmatch(r'[0-9a-f]{40}', expected) or expected != actual:
        raise ValueError('diagnostic_revision_mismatch')


def duration_seconds(value):
    value = value.replace(' ', '')
    parts = list(re.finditer(r'(\d+(?:\.\d+)?)(us|ms|min|s|h)', value))
    if ''.join(part.group() for part in parts) != value or not parts:
        raise ValueError('unit_duration_unavailable')
    factors = dict(us=.000001, ms=.001, s=1, min=60, h=3600)
    return sum(float(part[1]) * factors[part[2]] for part in parts)


def verify_unit_properties(properties):
    if (properties.get('Restart') != 'no' or properties.get('KillMode') != 'control-group' or
            duration_seconds(properties.get('RuntimeMaxUSec', '')) != 1800 or
            duration_seconds(properties.get('TimeoutStopUSec', '')) != 65):
        raise ValueError('diagnostic_unit_stop_or_restart_settings')


def selected_frontiers(providers):
    allowed = {CONTROL, 'program:pump', 'program:pumpswap', program_scope('pump'), program_scope('pumpswap')}
    evidence = providers.get('evidence', {})
    return {kind: [dict(scope=row['scope'], **{key: row[key] for key in
        ('slot', 'updated', 'market_time', 'linked_child_slot') if type(row.get(key)) in (int, float)})
        for row in evidence.get(kind, []) if isinstance(row, dict) and row.get('scope') in allowed]
        for kind in ('frontiers', 'program_frontiers')}


def write_metadata(output, name, value):
    body_bytes = len(json.dumps(value, sort_keys=True, allow_nan=False).encode()) + 1
    other_bytes = sum((output / item).stat().st_size for item in
        ('clock.json', 'result.json', 'supervisor-fatal.json', 'guard-failure.json')
        if item != name and (output / item).exists())
    if other_bytes + body_bytes > TERMINAL_BYTES:
        raise ValueError('diagnostic_metadata_reserve')
    atomic_json(output / name, value)


def read_json(path):
    with Path(path).open('rb') as stream:
        body = stream.read(INPUT_BYTES + 1)
    if len(body) > INPUT_BYTES:
        raise ValueError('diagnostic_input_bound')
    return json.loads(body)


class Window:
    """One outer clock; a late restoration never repairs the original verdict."""
    def __init__(self, origin):
        self.origin = origin
        self.restored = None
        self.original_readiness = None

    def decision(self, now, ready):
        elapsed = now - self.origin
        if self.original_readiness is None and elapsed >= 300:
            self.original_readiness = 'PASS' if self.restored is not None else 'FAIL'
        if elapsed >= 1800:
            return 'WORK_DEADLINE'
        if self.restored is None:
            if elapsed >= 900:
                return 'STARTUP_LIMITATION'
            if ready:
                self.restored = now
        elif not ready:
            return 'REQUIRED_READINESS_LOST'
        elif now - self.restored >= 900:
            return 'POST_STARTUP_COMPLETE'
        return None


class FiveSecondSampler:
    """Retain one local observation without renewing its collection clocks."""
    def __init__(self):
        self.last = None
        self.next_sample = 0

    def read(self, now, collect):
        due = self.last is None or now >= self.next_sample
        if due:
            self.last = collect()
            self.next_sample = now + FULL_SAMPLE_SECONDS
        return self.last, due


class SingleAttemptSupervisor(Supervisor):
    """Reuse native ownership/drain; reject a retry before it can spawn."""
    def __init__(self, root, *, output, **kwargs):
        if kwargs.get('admission', 'OBSERVATION') != 'OBSERVATION':
            raise ValueError('diagnostic_requires_observation')
        kwargs['admission'] = 'OBSERVATION'
        super().__init__(root, **kwargs)
        self.output = Path(output)
        self.attempted_lanes = set()
        self.source_attempted = False

    def fatal(self, actor, proc):
        self.stop_requested = True
        facts = dict(
            actor=actor, pid=getattr(proc, 'pid', None),
            exit_code=None if proc is None else proc.poll(),
            retry_dispatched=False, at=time.time())
        try:
            write_metadata(self.output, 'supervisor-fatal.json', facts)
        except BaseException:
            # Essential fixed fields survive optional-file failure in systemd's
            # existing stderr channel. Never print exception text or argv.
            print('diagnostic_fatal_file_unavailable:' + json.dumps(facts), file=sys.stderr, flush=True)
        raise RuntimeError('diagnostic_first_worker_exit:' + actor)

    def start_lane(self, lane):
        if lane in self.attempted_lanes:
            self.fatal(lane, self.processes.get(lane))
        self.attempted_lanes.add(lane)
        return super().start_lane(lane)

    def start_services(self):
        if self.source_attempted:
            self.fatal('solana', getattr(self, 'evidence', None))
        super().start_services()
        # An existing provider backoff may defer the first source admission.
        if getattr(self, 'evidence', None) is not None:
            self.source_attempted = True

    def recover_evidence(self):
        self.fatal('solana', self.evidence)


def pipeline_sample(root, expected_pid):
    """PK/indexed reads only; no counts, population scans, payloads or SQL trace."""
    started = time.monotonic()
    result = dict(available=False, collected_at=time.time(), collected_at_monotonic=started,
                  missing_edges={k: 'UNAVAILABLE' for k in MISSING_EDGES})
    try:
        path = Path(root) / 'shared/solana-evidence.sqlite'
        with closing(sqlite3.connect(path.absolute().as_uri() + '?mode=ro', uri=True,
                                     timeout=0, isolation_level=None)) as db:
            db.execute('PRAGMA query_only=ON')
            db.set_progress_handler(lambda: int(time.monotonic() - started >= .25), 1000)
            db.execute('BEGIN')
            keys = ('pid', 'heartbeat', 'phase', 'ipc', 'owner_scheduler',
                    'storage_maintenance', 'sqlite_failure_recorder', 'native_streams')
            health = {}; retained = 0
            for key, value in db.execute('SELECT key,value FROM service_health WHERE key IN (' +
                                        ','.join('?' for _ in keys) + ')', keys):
                retained += len(value.encode())
                if retained > INPUT_BYTES:
                    raise ValueError('service_health_input_bound')
                health[key] = json.loads(value)
            if expected_pid is None or health.get('pid') != expected_pid:
                result['unavailable_reason'] = 'SOURCE_PID_MISMATCH'
                return result
            generation = health.get('owner_scheduler', {}).get('owner_admission', {}).get('generation')
            result.update(available=True, source_pid=expected_pid, generation=generation,
                          generation_state='CURRENT' if generation is not None else 'UNAVAILABLE',
                          required_counters=required_counters(health,now_monotonic=started), service_health=numeric(health))
            # Each sample is bounded independently of retained historical stock.
            result['pending_outbox_head'] = db.execute(
                'SELECT id,family,kind,created FROM candidate_history_outbox '
                'INDEXED BY candidate_history_pending WHERE consumed IS NULL '
                'ORDER BY created LIMIT 32').fetchall()
            result['pending_outbox_depth'] = 'UNAVAILABLE_NO_POPULATION_SCAN'
            result['outbox_head_scope'] = 'INDEX_PREFIX_ALL_RETAINED_FAMILIES'
            try:
                # Newest canonical heads prevent old unrelated retained activity
                # from consuming the whole diagnostic cohort. This existing index
                # bounds the read even when old canonical work is still pending.
                result['pending_canonical_heads'] = [row for family in ('pump', 'pumpswap')
                    for row in db.execute("SELECT id,family,kind,created,"
                        "body -> '$.record.identity',body -> '$.record.slot',"
                        "body -> '$.record.observed_at',body -> '$.record.market_time',"
                        "body -> '$.available',hash FROM candidate_history_outbox "
                        "INDEXED BY candidate_history_canonical_pending WHERE family=? "
                        "AND kind='canonical' AND consumed IS NULL "
                        "ORDER BY json_extract(body,'$.record.slot') DESC LIMIT 16", (family,))]
            except sqlite3.Error:
                result['pending_canonical_heads'] = UNAVAILABLE
            result['canonical_heads_scope'] = 'NEWEST_PENDING_SLOT_INDEX_PREFIX_PER_PROGRAM_NOT_POPULATION'
            result['history_deadline_heads'] = {status: db.execute(
                'SELECT id,deadline,created FROM rolling_preparation_jobs '
                'INDEXED BY rolling_preparation_expiry WHERE status=? '
                'ORDER BY deadline LIMIT 1', (status,)).fetchone()
                for status in ('pending', 'active')}
            result['history_heads_scope'] = 'STATUS_INDEX_PREFIX_NOT_OLDEST_REQUIRED_PUMP'
            result['stored_economics'] = {scope: db.execute(
                'SELECT slot,market_time,first_seen FROM rolling_economic_events '
                'INDEXED BY rolling_event_order WHERE scope=? ORDER BY slot DESC LIMIT 1',
                (scope,)).fetchone() for scope in ('program:pump', 'program:pumpswap')}
            try:
                session = db.execute('SELECT session FROM prewarm_startup WHERE id=1').fetchone()
                result['source_session'] = None if session is None else session[0]
                result['pending_proof_heads'] = db.execute(
                    'SELECT id,scope,lo,hi,available FROM candidate_pending_proofs '
                    'INDEXED BY candidate_proof_publication ORDER BY lo,hi LIMIT 2').fetchall()
                result['proof_control_bounds'] = {identity: [db.execute(
                    'SELECT slot,parent,hash,previous_hash,session,sealed FROM stream_receipts '
                    'WHERE scope=? AND slot=?', (CONTROL, slot)).fetchone()
                    for slot in (lo, hi)] for identity, _, lo, hi, _ in result['pending_proof_heads']}
                result['proof_checkpoints'] = {scope: db.execute(
                    'SELECT slot,updated FROM candidate_checkpoints WHERE scope=?', (scope,)).fetchone()
                    for _, scope, _, _, _ in result['pending_proof_heads']}
                result['proof_eligibility'] = 'UNAVAILABLE_NOT_REEVALUATED'
            except sqlite3.Error:
                result['pending_proof_heads'] = 'UNAVAILABLE'
                result['proof_control_bounds'] = 'UNAVAILABLE'
    except (OSError, sqlite3.Error, ValueError, TypeError) as error:
        result.update(available=False, unavailable_reason=type(error).__name__)
    finally:
        result['collection_seconds'] = time.monotonic() - started
    return result


class ReceiptCohort:
    """Keep pending canonical identities; fill free slots with current work.

    The sampled process generation is a capture fence, not invented per-event
    provenance. Original availability/market times keep replay stock distinct.
    Cross-database reads never claim an atomic consumer/owner snapshot.
    """
    def __init__(self, origin_wall=0):
        self.identities = []
        self.origin_wall = origin_wall
        self.generation = None
        self.references = {}
        self.source_hashes = {}

    def sample(self, root, pipeline):
        fence = (pipeline.get('source_pid'), pipeline.get('generation'), pipeline.get('source_session'))
        if not pipeline.get('available') or any(value is None for value in fence):
            return dict(available=False, reason='CURRENT_SOURCE_PROVENANCE_UNAVAILABLE',
                        retained_pending_identities=list(self.identities))
        if self.generation is not None and self.generation != fence:
            return dict(available=False, reason='SOURCE_GENERATION_INVALIDATED',
                        retained_pending_identities=list(self.identities))
        self.generation = fence
        heads = pipeline.get('pending_canonical_heads')
        if isinstance(heads, list):
            safe_heads = [row for row in heads if isinstance(row, (list, tuple)) and len(row) >= 10
                          and isinstance(row[0], str) and finite_number(row[3])]
            for row in sorted(safe_heads, key=lambda row: (row[3], row[0])):
                # No fallback to scout/activity or old rows that merely remain
                # pending. Market-time replay classification is independent.
                if (len(self.identities) >= COHORT_SIZE or row[0] in self.identities or
                        row[1] not in ('pump', 'pumpswap') or row[2] != 'canonical' or
                        row[3] < self.origin_wall):
                    continue
                try:
                    if any(isinstance(value, str) and len(value) > 4096 for value in row[4:9]):
                        return dict(available=False, reason='CANONICAL_HEAD_SCALAR_BOUND',
                                    retained_pending_identities=list(self.identities))
                    references = [None if value is None else json.loads(value) for value in row[4:9]]
                except (ValueError, TypeError):
                    return dict(available=False, reason='CANONICAL_HEAD_SCALARS_UNAVAILABLE',
                                retained_pending_identities=list(self.identities))
                if not isinstance(references[0], str) or type(references[1]) is not int:
                    continue
                if not isinstance(row[9], str) or not re.fullmatch(r'[0-9a-f]{64}', row[9]):
                    return dict(available=False, reason='CANONICAL_SOURCE_HASH_UNAVAILABLE',
                                retained_pending_identities=list(self.identities))
                self.identities.append(row[0])
                self.references[row[0]] = references
                self.source_hashes[row[0]] = row[9]
        if not self.identities:
            return dict(available=False, reason='NO_CURRENT_CANONICAL_COHORT_CAPTURED',
                        sampling_scope=pipeline.get('canonical_heads_scope', UNAVAILABLE))
        started = time.monotonic(); rows = []
        try:
            paths = [Path(root) / 'shared' / name for name in
                     ('solana-evidence.sqlite', 'solana-candidate-history.sqlite')]
            with closing(sqlite3.connect(paths[0].absolute().as_uri() + '?mode=ro', uri=True,
                                         timeout=0, isolation_level=None)) as source, \
                 closing(sqlite3.connect(paths[1].absolute().as_uri() + '?mode=ro', uri=True,
                                         timeout=0, isolation_level=None)) as consumer:
                for db in (source, consumer):
                    db.execute('PRAGMA query_only=ON')
                    db.set_progress_handler(lambda: int(time.monotonic() - started >= .25), 1000)
                    db.execute('BEGIN')
                actual = dict(source.execute("SELECT key,value FROM service_health WHERE key IN ('pid','owner_scheduler')"))
                actual_pid = json.loads(actual.get('pid', 'null'))
                actual_generation = json.loads(actual.get('owner_scheduler', '{}')).get('owner_admission', {}).get('generation')
                actual_session = source.execute('SELECT session FROM prewarm_startup WHERE id=1').fetchone()
                if (actual_pid, actual_generation, None if actual_session is None else actual_session[0]) != self.generation:
                    return dict(available=False, reason='SOURCE_GENERATION_CHANGED_DURING_CAPTURE',
                                retained_pending_identities=list(self.identities))
                for identity in self.identities:
                    row = source.execute("SELECT family,address,kind,created,consumed,hash,"
                        "body -> '$.record.identity',body -> '$.record.slot',body -> '$.available',"
                        "body -> '$.source_hash',body -> '$.record.market_time' "
                        "FROM candidate_history_outbox WHERE id=?",
                        (identity,)).fetchone()
                    if row is None:
                        rows.append(dict(outbox_identity=identity, state='OUTBOX_UNAVAILABLE')); continue
                    family,address,kind,created,consumed,checksum,record,slot,available,original_hash,market = row
                    record_id = None if record is None else json.loads(record)
                    record_slot = None if slot is None else json.loads(slot)
                    original_available = None if available is None else json.loads(available)
                    observed_market = None if market is None else json.loads(market)
                    expected_hash = json.loads(original_hash) if original_hash is not None else checksum
                    captured_hash = self.source_hashes.get(identity)
                    if captured_hash is not None and expected_hash != captured_hash:
                        rows.append(dict(outbox_identity=identity, state='SOURCE_CONTENT_CHANGED'))
                        continue
                    captured = self.references.get(identity)
                    if captured is not None:
                        # ACK compaction drops market detail; preserve the exact
                        # original scalar captured before compaction.
                        if (record_id, record_slot, original_available) != (captured[0], captured[1], captured[4]):
                            rows.append(dict(outbox_identity=identity, state='SOURCE_CONTENT_CHANGED'))
                            continue
                        observed_market = captured[3]
                    # ``at`` is the original source receipt time in the existing
                    # schema, not an observed consumer COMMIT completion time.
                    receipt = consumer.execute('SELECT at,body,hash FROM source_receipts WHERE id=?',
                                               (identity,)).fetchone()
                    valid = False; ack_exact = False
                    if receipt is not None:
                        if len(receipt[1].encode()) > 4096:
                            raise ValueError('consumer_receipt_bound')
                        facts = json.loads(receipt[1])
                        valid = (hashlib.sha256(receipt[1].encode()).hexdigest() == receipt[2] and
                            facts == dict(source_hash=expected_hash, scope='candidate:' + family + ':' + address,
                                          canonical_identity=record_id) and kind == 'canonical' and
                            isinstance(record_id, str) and type(record_slot) is int and finite_number(original_available))
                        if valid and consumed is not None and original_hash is not None:
                            from meme_machine.solana_evidence_plane import canonical
                            compact = canonical(dict(source_hash=expected_hash,
                                record=dict(identity=record_id, slot=record_slot), available=original_available))
                            ack_exact = hashlib.sha256(compact.encode()).hexdigest() == checksum
                    state = ('RECEIPT_AUTHENTICATION_UNAVAILABLE_OR_SKEW' if receipt is not None and not valid else
                             'EXACT_ACK_CONTENT_UNAVAILABLE_OR_SKEW' if consumed is not None and not ack_exact else
                             'ACK_MARKER_OBSERVED' if ack_exact else
                             'CONSUMER_RECEIPT_OBSERVED_ACK_PENDING' if valid else 'DELIVERY_PENDING')
                    arrival_class = ('PREEXISTING_OR_REPLAY' if created < self.origin_wall or
                        finite_number(original_available) and original_available < self.origin_wall else
                        'RETAINED_OR_REPLAYED_MARKET_AVAILABLE_DURING_ATTEMPT' if
                        finite_number(observed_market) and observed_market < self.origin_wall else
                        'CURRENT_MARKET_EVIDENCE_PHYSICAL_ARRIVAL_UNVERIFIED' if
                        finite_number(observed_market) and finite_number(original_available) else
                        'CURRENT_GENERATION_CAPTURE_MARKET_ARRIVAL_UNAVAILABLE')
                    rows.append(dict(outbox_identity=identity, family=family, kind=kind,
                        created=created, canonical_identity=record_id, slot=record_slot,
                        original_available=original_available if original_available is not None else UNAVAILABLE,
                        original_market_time=observed_market if observed_market is not None else UNAVAILABLE,
                        captured_source_pid=self.generation[0], captured_generation=self.generation[1],
                        captured_source_session=self.generation[2],
                        consumer_receipt_authenticated=valid, consumer_commit_receipt_present=receipt is not None,
                        consumer_receipt_at=None if receipt is None else receipt[0],
                        exact_ack_consumed_at=consumed if ack_exact else UNAVAILABLE,
                        owner_consumed_marker=consumed if consumed is not None else UNAVAILABLE,
                        state=state, arrival_class=arrival_class))
            completed = {row['outbox_identity'] for row in rows if row['state'] == 'ACK_MARKER_OBSERVED'}
            # Only authenticated exact completion frees diagnostic slots. A slow
            # or missing pending item remains tracked while other slots fill.
            self.identities = [identity for identity in self.identities if identity not in completed]
            for identity in completed:
                self.references.pop(identity, None)
                self.source_hashes.pop(identity, None)
            return dict(available=True, source_pid=pipeline.get('source_pid'),
                        generation=pipeline.get('generation'), identities=rows,
                        source_generation_scope='CAPTURE_FENCE_NOT_PER_EVENT_GENERATION_PROOF',
                        sampling_scope=pipeline.get('canonical_heads_scope', UNAVAILABLE),
                        progress_scope='OUTBOX_OBLIGATIONS_NOT_DISTINCT_ECONOMIC_EVENTS_OR_SLOTS',
                        cohort_limit=COHORT_SIZE, retained_pending_count=len(self.identities),
                        snapshots='INDEPENDENT_READ_SNAPSHOTS_NO_ATOMIC_CROSS_DATABASE_CLAIM')
        except (OSError, sqlite3.Error, ValueError, TypeError) as error:
            return dict(available=False, reason=type(error).__name__)


class RecorderCoverage:
    def __init__(self):
        self.first_source_seen = None
        self.registered = False

    def check(self, pipeline, source_pid, now):
        if source_pid is None:
            return None
        if self.first_source_seen is None:
            self.first_source_seen = now
        row = pipeline.get('service_health', {}).get('sqlite_failure_recorder')
        if row is None:
            return ('REQUIRED_RECORDER_MISSING' if self.registered or
                    now - self.first_source_seen >= 30 else None)
        if row.get('pid') != source_pid or row.get('recorder_valid') is not True:
            return 'REQUIRED_RECORDER_INVALID_OR_WRONG_PID'
        self.registered = True
        return None


def readiness(root, main_pid):
    # The original gate uses local projections and /proc; it dispatches no RPC.
    from meme_machine.operational.acceptance import observe
    try:
        health, _, _ = observe(Path(root))
        if health.get('pid') != main_pid:
            return False
        for lane in ('pump', 'pons'):
            proof = health['lanes'][lane].get('native_continuation', {})
            if not all(proof.get(k) is True for k in ('current_restored',
                    'survivor_replay_verified', 'survivor_handoff_ready', 'exit_path_bound')):
                return False
        if any(health['providers'].get(k, {}).get('state') != 'CURRENT'
               for k in ('solana', 'robinhood')):
            return False
        rows = health['providers']['evidence'].get('program_frontiers', [])
        return len(rows) == 2 and all(0 <= time.time() - row['updated'] <= 5 and
            0 <= time.time() - row['market_time'] <= 15 for row in rows)
    except (OSError, ValueError, KeyError, TypeError):
        return False


def bounded_text(path, limit=8192):
    with path.open() as stream:
        value = stream.read(limit + 1)
    if len(value) > limit:
        raise ValueError('kernel_counter_input_bound')
    return value


def counters(group, pids, owner=None):
    result = {}
    for name, path in [('cpu_stat', group / 'cpu.stat'), ('io_stat', group / 'io.stat'),
                       ('cpu_pressure', group / 'cpu.pressure'), ('io_pressure', group / 'io.pressure'),
                       ('memory_pressure', group / 'memory.pressure'),
                       ('device_stat', Path('/sys/block/sda/stat'))]:
        try:
            result[name] = bounded_text(path)
        except (OSError, ValueError):
            result[name] = 'UNAVAILABLE'
    result.update(pressure_scope='SERVICE_CGROUP_AGGREGATE',
                  device_scope='DEVICE_AGGREGATE_NOT_ACTOR_WAIT',
                  owner_thread_schedstat='UNAVAILABLE_NO_EXPORTED_NATIVE_TID')
    try:
        owned = [int(pid) for pid in bounded_text(group / 'cgroup.procs').split()]
        result['process_scope_truncated'] = len(owned) > 64
        owned = owned[:64]
    except (OSError, ValueError):
        result['process_scope'] = 'UNAVAILABLE'
        return result
    result['workers'] = {}
    names = {pid: name for name, pid in pids.items()}
    for pid in owned:
        name = names.get(pid, 'cgroup_pid_' + str(pid))
        try:
            folder = Path('/proc/' + str(pid))
            fields = bounded_text(folder / 'stat').rsplit(')', 1)[1].split()
            schedstat = [int(value) for value in bounded_text(folder / 'schedstat').split()]
            result['workers'][name] = dict(pid=pid, state=fields[0], user_ticks=int(fields[11]),
                system_ticks=int(fields[12]), rss_pages=int(fields[21]),
                io=bounded_text(folder / 'io'), schedstat_scope='PROCESS_MAIN_THREAD_ONLY',
                runtime_ns=schedstat[0], runnable_wait_ns=schedstat[1], timeslices=schedstat[2],
                delayacct_blkio_ticks=int(fields[39]) if len(fields) > 39 else 'UNAVAILABLE',
                delayacct_scope='KERNEL_ACCOUNTING_AVAILABILITY_UNVERIFIED')
        except (OSError, ValueError, IndexError):
            result['workers'][name] = dict(pid=pid, state='UNAVAILABLE')
    if isinstance(owner,dict) and type(owner.get('native_thread_id'))is int:
        pid=owner.get('owner_pid');tid=owner['native_thread_id']
        if type(pid)is not int or pid!=pids.get('solana') or pid not in owned or tid<=0:
            result['owner_thread_schedstat']='UNAVAILABLE_OWNER_IDENTITY_MISMATCH'
        else:
            try:
                folder=Path('/proc/'+str(pid)+'/task/'+str(tid))
                fields=bounded_text(folder/'stat').rsplit(')',1)[1].split()
                schedstat=[int(value) for value in bounded_text(folder/'schedstat').split()]
                try:
                    wait=bounded_text(folder/'wchan',128).strip()
                    wait=wait if re.fullmatch(r'[A-Za-z0-9_.]{1,80}',wait) else UNAVAILABLE
                except (OSError,ValueError):wait=UNAVAILABLE
                result['owner_thread_schedstat']=dict(pid=pid,native_thread_id=tid,state=fields[0],
                    runtime_ns=schedstat[0],runnable_wait_ns=schedstat[1],timeslices=schedstat[2],
                    wait_channel=wait,schedstat_scope='ACTUAL_CANONICAL_OWNER_NATIVE_THREAD',
                    delayacct_blkio_ticks=int(fields[39]) if len(fields)>39 else UNAVAILABLE,
                    delayacct_scope='KERNEL_ACCOUNTING_AVAILABILITY_UNVERIFIED')
            except (OSError,ValueError,IndexError):
                result['owner_thread_schedstat']='UNAVAILABLE_OWNER_THREAD_EXITED_OR_UNREADABLE'
    return result


def append_sample(path, sample):
    body = json.dumps(sample, sort_keys=True, allow_nan=False).encode() + b'\n'
    size = path.stat().st_size if path.exists() else 0
    if len(body) > INPUT_BYTES or size + len(body) > OUTPUT_BYTES - 2 * TERMINAL_BYTES:
        raise ValueError('diagnostic_output_limit')
    with path.open('ab') as stream:
        stream.write(body)


def append_guard(path, sample):
    if len(json.dumps(sample, sort_keys=True, allow_nan=False).encode()) + 1 > GUARD_BYTES:
        raise ValueError('diagnostic_guard_record_bound')
    append_sample(path, sample)


def provider_queue_guard(providers, output, record, *, now=None, wall=None):
    """Persist only the triggering fixed facts; never replace or retry the stop.

    The small record shares the existing metadata reserve, independently of
    metrics and the source SQLite terminal channel. No DB probe, provider call,
    sleep or retry occurs on this failure path.
    """
    now = time.monotonic() if now is None else now
    wall = time.time() if wall is None else wall
    for name in ('solana', 'robinhood'):
        row = providers.get(name, {})
        row = row if isinstance(row, dict) else {}
        depth = row.get('queue_depth')
        oldest = row.get('oldest_wait_seconds')
        # Preserve the existing guard's exact limits and greater-than boundary.
        if not (row.get('queue_depth', 0) > 64 or row.get('oldest_wait_seconds', 0) > 5):
            continue
        facts = dict(failure='provider_queue_limit', provider=name,
            observed_at=wall, observed_at_monotonic=now,
            provider_sampled_at=row.get('sampled_at') if finite_number(row.get('sampled_at')) else UNAVAILABLE,
            queue_depth=depth if finite_number(depth) else UNAVAILABLE,
            oldest_wait_seconds=oldest if finite_number(oldest) else UNAVAILABLE,
            maximum_queue_depth=64, maximum_queue_wait_seconds=5,
            crossed='DEPTH' if finite_number(depth) and depth > 64 else 'WAIT',
            endpoint_identity=UNAVAILABLE, role=UNAVAILABLE,
            cooldown_seconds=row.get('cooldown_seconds') if finite_number(row.get('cooldown_seconds')) else UNAVAILABLE,
            adaptive_interval_seconds=row.get('adaptive_interval_seconds') if finite_number(row.get('adaptive_interval_seconds')) else UNAVAILABLE,
            admission_state=row.get('state') if row.get('state') in ('CURRENT','UNAVAILABLE','STALE','FAIL_CLOSED') else UNAVAILABLE)
        # Only fingerprints/known roles qualify, never URLs or arbitrary text.
        endpoint = row.get('endpoint_identity')
        if isinstance(endpoint, str) and re.fullmatch(r'[0-9a-f]{64}', endpoint):
            facts['endpoint_identity'] = endpoint
        if row.get('role') in ('discovery', 'position_monitor', 'conversion', 'historical', 'protective'):
            facts['role'] = row['role']
        record['triggering_guard'] = facts
        try:
            write_metadata(output, 'guard-failure.json', facts)
            record['triggering_guard_recorded'] = True
        except BaseException:
            record['triggering_guard_recorded'] = False
            # Fixed facts remain in the final reserved result even when the
            # optional immediate record cannot be written. Original failure wins.
        raise ValueError('provider_queue_limit:' + name)


def economic(root):
    from meme_machine.operational.backup import state_identity
    identity = state_identity(root)
    state = identity['replayed_state']
    if any(state.get(k) for k in ('positions', 'reservations', 'commitments',
            'obligations', 'pending_deliveries', 'pending_backing', 'runtime_pending', 'runtime_inbox')):
        raise ValueError('existing_obligations_require_safe_handoff')
    return dict(epoch_id=identity['epoch_id'], inception_sha256=identity['inception_sha256'],
                cash=state.get('cash'), policy_sha256=hashlib.sha256(
                    json.dumps(state.get('policy'), sort_keys=True).encode()).hexdigest(),
                realized=state.get('realized'))


def control(*args, timeout=5):
    return subprocess.check_output(['systemctl', *args], text=True, timeout=timeout).strip()


def live_children():
    try:
        return (Path('/sys/fs/cgroup/system.slice') / UNIT / 'cgroup.procs').read_text().split()
    except FileNotFoundError:
        return []  # systemd removes the empty stopped unit's cgroup.
    except OSError:
        return None


def drain(origin, *, ctl=control, clock=time.monotonic, children=live_children):
    """Request existing graceful drain; never hide timeout or force recovery."""
    remaining = origin + 1865 - clock()
    if remaining <= 0:
        return dict(drained=False, recovery_required=True, reason='ABSOLUTE_DEADLINE_EXHAUSTED')
    try:
        ctl('stop', UNIT, timeout=remaining)
        remaining = origin + 1865 - clock()
        if remaining <= 0:
            raise TimeoutError
        state = ctl('show', UNIT, '-p', 'MainPID', '-p', 'ActiveState', '-p', 'SubState',
                    timeout=min(5, remaining))
        drained = ('MainPID=0' in state and children() == [] and
                   ('ActiveState=inactive' in state or 'ActiveState=failed' in state))
        return dict(drained=drained, recovery_required=not drained or 'ActiveState=failed' in state,
                    service_state=state, native_drain='UNVERIFIED_TIMEOUT_ESCALATION_POSSIBLE')
    except (OSError, subprocess.SubprocessError, TimeoutError):
        return dict(drained=False, recovery_required=True, reason='DRAIN_TIMEOUT_OR_UNAVAILABLE')


def observe_once(root, output, source_revision):
    """Execute only after the separately authorized spec preflight and install."""
    from meme_machine.operational.supervisor import SOURCE_ROOT
    validate_revision(source_revision, subprocess.check_output(['git', 'rev-parse', 'HEAD'],
                      cwd=SOURCE_ROOT, text=True, timeout=5).strip())
    if control('show', UNIT, '-p', 'MainPID', '--value') != '0':
        raise ValueError('existing_service_must_be_stopped')
    if control('show', UNIT, '-p', 'UnitFileState', '--value') != 'disabled':
        raise ValueError('existing_service_must_remain_disabled')
    command = control('show', UNIT, '-p', 'ExecStart', '--value')
    if ('current_combined_observation_20261014' not in command or 'supervise' not in command or
            str(root) not in command or str(output) not in command or source_revision not in command):
        raise ValueError('single_attempt_supervisor_overlay_required')
    properties = dict(line.split('=', 1) for line in control('show', UNIT, '-p', 'Restart',
        '-p', 'RuntimeMaxUSec', '-p', 'TimeoutStopUSec', '-p', 'KillMode').splitlines())
    verify_unit_properties(properties)
    before = economic(root)
    access_properties = dict(line.split('=', 1) for line in control('show', UNIT,
        *(argument for key in ACCESS_PROPERTIES for argument in ('-p', key))).splitlines())
    access = check_access(output, root, source_revision, access_properties,
                          write_metadata=write_metadata)
    record = dict(revision=source_revision, funding=False, acceptance_minutes=0,
                  status='STARTING', before=before, recovery_required=True, unit_properties=properties,
                  diagnostic_access=access)
    origin = time.monotonic()
    window = Window(origin)
    write_metadata(output, 'clock.json', dict(origin_monotonic=origin, revision=source_revision))
    stopped = [False]
    prior = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    for sig in prior:
        signal.signal(sig, lambda *_: stopped.__setitem__(0, True))
    known = {}; covered = False; generation = None; observed_supervisor_pid = None
    sampler = FiveSecondSampler()
    cohort = ReceiptCohort(time.time())
    coverage = RecorderCoverage()
    try:
        control('--no-block', 'start', UNIT)
        while True:
            now = time.monotonic()
            if stopped[0] or now >= origin + 1800:
                record['stop_reason'] = 'INTERRUPTED' if stopped[0] else 'WORK_DEADLINE'
                break
            main_pid = int(control('show', UNIT, '-p', 'MainPID', '--value',
                                   timeout=min(5, origin + 1800 - now)))
            if (output / 'supervisor-fatal.json').exists() or (output / 'source-sqlite-terminal.txt').exists():
                record.update(stop_reason='FIRST_FATAL_WORKER', failure=True); break
            if not main_pid:
                # A --no-block start may not have published MainPID yet.
                if now - origin < 20:
                    time.sleep(min(1, origin + 1800 - now)); continue
                record.update(stop_reason='SUPERVISOR_ENDED', failure=True); break
            observed_supervisor_pid = main_pid
            try:
                health = read_json(root / 'health.json')
            except (OSError, ValueError):
                health = {}
            if health.get('pid') != main_pid:
                health = {}
            lanes = health.get('lanes', {})
            providers = health.get('providers', {})
            source_pid = providers.get('evidence', {}).get('pid')
            pids = {k: lanes[k]['pid'] for k in ('pump', 'pons') if lanes.get(k, {}).get('pid')}
            if source_pid:
                pids['solana'] = source_pid
            if any(k in known and known[k] != v for k, v in pids.items()):
                raise ValueError('unexpected_worker_restart')
            known.update(pids)
            group = Path('/sys/fs/cgroup/system.slice') / UNIT
            memory = int((group / 'memory.current').read_text())
            if memory >= 6 * 1024**3:
                raise ValueError('observation_memory_limit')
            free = {str(p): os.statvfs(p).f_bavail * os.statvfs(p).f_frsize for p in (Path('/'), root)}
            if min(free.values()) < RESERVE_BYTES:
                raise ValueError('observation_disk_reserve')
            provider_queue_guard(providers, output, record)
            pipeline, full_sample_due = sampler.read(now, lambda: pipeline_sample(root, source_pid))
            if covered and not pipeline['available']:
                raise ValueError('required_pipeline_coverage_lost')
            covered |= pipeline['available']
            recorder_failure = coverage.check(pipeline, source_pid, time.monotonic())
            if recorder_failure:
                record['sqlite_attribution_valid'] = False
                raise ValueError(recorder_failure)
            observed_generation = pipeline.get('generation')
            if generation is not None and observed_generation != generation:
                raise ValueError('source_generation_changed_or_lost')
            if observed_generation is not None:
                generation = observed_generation
            ready = readiness(root, main_pid)
            decision = window.decision(time.monotonic(), ready)
            # The 1-Hz checks above use current atomic health/resource facts.
            # Reused SQL recorder/generation facts keep their original clocks.
            guard = dict(sample_kind='guard', elapsed_seconds=time.monotonic() - origin,
                at=time.time(), main_pid=main_pid, source_pid=source_pid, ready=ready,
                original_readiness=window.original_readiness, memory_bytes=memory,
                root_free_bytes=free[str(Path('/'))], state_free_bytes=free[str(root)],
                pipeline_collected_at=pipeline['collected_at'],
                pipeline_collected_at_monotonic=pipeline['collected_at_monotonic'],
                pipeline_observed_source_pid=pipeline.get('source_pid'),
                pipeline_observation_age_seconds=max(0, time.monotonic() - pipeline['collected_at_monotonic']),
                pipeline_observation='NEW_READ' if full_sample_due else 'CACHED_READ',
                pipeline_observed_available=pipeline['available'])
            if full_sample_due:
                sample = dict(guard, sample_kind='full', lanes=numeric(lanes), providers=numeric(providers),
                    native_lifecycle=native_lifecycle(lanes),
                    fixed_scope_frontiers=selected_frontiers(providers), pipeline=pipeline,
                    sqlite_coverage_scope='CANONICAL_PARENT_ONLY_CHILD_HEALTH_UNAVAILABLE')
                sample['counters'] = counters(group, dict(pids, supervisor=main_pid),
                    pipeline.get('required_counters',{}).get('owner_scheduler'))
                sample['receipt_cohort'] = cohort.sample(root, pipeline)
                append_sample(output / 'metrics.jsonl', sample)
            else:
                append_guard(output / 'metrics.jsonl', guard)
            if decision:
                record['stop_reason'] = decision; break
            time.sleep(min(1, max(0, origin + 1800 - time.monotonic())))
    except BaseException as error:
        record.update(stop_reason=str(error) if type(error) is ValueError else type(error).__name__, failure=True)
    finally:
        record.update(drain(origin), original_readiness=window.original_readiness,
                      restored_at_monotonic=window.restored, elapsed_to_drain_seconds=time.monotonic() - origin)
        record['final_native_health'] = final_native_health(root, observed_supervisor_pid, origin)
        if record['drained']:
            try:
                record['economic_continuity'] = economic(root) == before
            except (OSError, ValueError, sqlite3.Error):
                record['economic_continuity'] = False
            record['recovery_required'] |= not record['economic_continuity']
        record['recovery_required'] |= record.get('failure', False)
        record['status'] = 'STOPPED_REVIEW_REQUIRED' if not record['recovery_required'] else 'RECOVERY_REQUIRED'
        write_metadata(output, 'result.json', record)
        for sig, handler in prior.items():
            signal.signal(sig, handler)
    return 0 if not record['recovery_required'] else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('observe', 'supervise'))
    parser.add_argument('--state-root', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--source-revision', required=True)
    args = parser.parse_args()
    validate_revision(args.source_revision, args.source_revision)
    if (not args.output.is_absolute() or not args.state_root.is_absolute() or
            not args.output.is_dir() or args.output.is_symlink() or args.output.stat().st_mode & 0o077):
        parser.error('output must be an existing private directory')
    if args.output.resolve() == args.state_root.resolve() or args.state_root.resolve() in args.output.resolve().parents:
        parser.error('output must be outside economic state')
    if args.command == 'observe':
        return observe_once(args.state_root, args.output, args.source_revision)
    clock = read_json(args.output / 'clock.json')
    if clock['revision'] != args.source_revision:
        parser.error('clock revision mismatch')
    from meme_machine.operational.supervisor import SOURCE_ROOT
    validate_revision(args.source_revision, subprocess.check_output(['git', 'rev-parse', 'HEAD'],
                      cwd=SOURCE_ROOT, text=True, timeout=5).strip())
    remaining = clock['origin_monotonic'] + 1800 - time.monotonic()
    if not 0 < remaining <= 1800:
        parser.error('outer work clock exhausted or invalid')
    os.environ['MM_SQLITE_DIAGNOSTIC_REQUIRED'] = '1'
    os.environ['MM_SQLITE_TERMINAL_RECORD_PATH'] = str(args.output / 'source-sqlite-terminal.txt')
    SingleAttemptSupervisor(args.state_root, output=args.output).run(seconds=remaining)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
