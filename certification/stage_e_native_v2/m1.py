"""Finite M1 witness; observations never repair or credit the native runtime."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
from unittest.mock import patch

from .clock import DeterministicClock
from .contract import sha256
from .fixtures import b58
from .native import empty_frame
from .restart import records

WITNESS_VERSION = 'native-m1-completion-witness-v2q2-1'
PROGRESS_SELECT = 'SELECT scope,side,at,units,record_at,records FROM maintenance_progress ORDER BY scope,side LIMIT '
SCOPE = 'program:meteora'


def decision_identity(decision, generation):
    if decision is None:
        return None
    return dict(generation=generation, sequence=decision.sequence, side=decision.side)


class LedgerReads:
    """Transparent SQL observation, including errors raised while fetching rows.

    All SQL, cursors, handlers and exceptions are forwarded unchanged. The
    completion purpose is identified by the actual native caller's code object,
    independently of the ordinal. Only the first owner turn uses this observer.
    """
    def __init__(self, connection, runtime):
        self.connection = connection
        self.runtime = runtime
        self.reads = []
        self.preemption_enabled = True

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def set_progress_handler(self, handler, steps):
        self.preemption_enabled = handler is not None and steps > 0
        return self.connection.set_progress_handler(handler, steps)

    def execute(self, sql, parameters=()):
        if not sql.startswith(PROGRESS_SELECT):
            return self.connection.execute(sql, parameters)
        caller = sys._getframe(1).f_code
        row = dict(ordinal=len(self.reads)+1,
            purpose='completion_accounting' if caller is self.runtime._native_progress.__func__.__code__ else 'initial_observation',
            query_hash=sha256(sql.encode()), limit=parameters[0],
            pending=decision_identity(self.runtime.arbiter.pending, self.runtime.generation),
            transaction_open=self.connection.in_transaction,
            preemption_enabled=self.preemption_enabled, status='started',
            sqlite_errorcode=None, owner_interrupt_flag=False, rows=[])
        self.reads.append(row)
        try:
            cursor = self.connection.execute(sql, parameters)
        except BaseException as exc:
            self.failed(row, exc)
            raise
        observer = self

        class Cursor:
            def fetchall(self):
                try:
                    result = cursor.fetchall()
                except BaseException as exc:
                    observer.failed(row, exc)
                    raise
                row.update(status='completed', rows=[list(r) for r in result])
                return result

            def __getattr__(self, name):
                return getattr(cursor, name)

        return Cursor()

    def failed(self, row, exc):
        code = getattr(exc, 'sqlite_errorcode', None)
        flag = getattr(self.runtime.writer, '_background_sql_interrupted', False)
        row.update(status='interrupted' if isinstance(exc, sqlite3.OperationalError) and code == sqlite3.SQLITE_INTERRUPT else 'failed',
            sqlite_errorcode=code, owner_interrupt_flag=flag)


def evidence_fields(payload):
    reads = payload['ledger_reads']
    interrupted = [r for r in reads if r['status'] == 'interrupted']
    retries = [r for r in reads if r['purpose'] == 'completion_accounting' and r['ordinal'] > 2]
    return dict(completion_read_count=len(reads),
        interruption_injected_at_read=payload['interruption_injections'][0] if len(payload['interruption_injections']) == 1 else None,
        interruption_observed=len(interrupted) == 1 and interrupted[0]['ordinal'] == 2
            and interrupted[0]['purpose'] == 'completion_accounting'
            and interrupted[0]['sqlite_errorcode'] == sqlite3.SQLITE_INTERRUPT
            and interrupted[0]['owner_interrupt_flag'] is True,
        bounded_completion_retry_count=len(retries),
        retry_read_ordinal=retries[0]['ordinal'] if len(retries) == 1 else None)


def witness_gates(payload):
    """Recompute success from SQL, accounting, durable state and owner evidence."""
    from meme_machine.solana_maintenance_state import MAX_SCOPES
    reads = payload['ledger_reads']; fields = evidence_fields(payload)
    before, after = payload['before'], payload['after']
    pending = reads[1]['pending'] if len(reads) > 1 else None
    calls = payload['completion_accounting']
    retry = reads[2] if len(reads) == 3 else {}
    row_sequence = [r['ordinal'] for r in reads] == list(range(1, len(reads)+1))
    interruption = (row_sequence and fields['interruption_injected_at_read'] == 2
        and fields['interruption_observed'] and reads[0]['purpose'] == 'initial_observation'
        and reads[0]['status'] == 'completed' and reads[0]['pending'] is None
        and pending is not None and pending['generation'] == payload['generation'] and pending['side'] == 'archive'
        and all(r['limit'] == MAX_SCOPES*2+3 and r['transaction_open'] is False
            and r['query_hash'] == sha256((PROGRESS_SELECT+'?').encode()) for r in reads))
    one_retry = (fields['completion_read_count'] == 3 and fields['bounded_completion_retry_count'] == 1
        and fields['retry_read_ordinal'] == 3 and retry.get('purpose') == 'completion_accounting'
        and retry.get('status') == 'completed' and retry.get('pending') == pending
        and retry.get('preemption_enabled') is False and payload['interruption_injections'] == [2])
    scope_rows = [r for r in retry.get('rows', []) if r[:2] == [SCOPE, 'archive']]
    original_rows = [r for r in reads[0]['rows'] if r[:2] == [SCOPE, 'archive']] if reads else []
    delta = (scope_rows[0][3]- (original_rows[0][3] if original_rows else 0),
             scope_rows[0][5]- (original_rows[0][5] if original_rows else 0)) if len(scope_rows) == 1 else None
    accounted = (len(calls) == 1 and calls[0]['decision'] == pending
        and calls[0]['pending_before'] == pending and calls[0]['exact_pending_identity'] is True
        and calls[0]['read_ordinal'] == 3 and calls[0]['transaction_open'] is False
        and calls[0]['returned'] is True and calls[0]['error'] is None and calls[0]['pending_after'] is None
        and calls[0]['ledger'] == [512, 512] and delta == (512, 512)
        and calls[0]['progress'].get(SCOPE) == 512 and calls[0]['record_progress'].get(SCOPE) == 512
        and sum(calls[0]['record_progress'].values()) == 512
        and all(v == 0 for k, v in calls[0]['progress'].items() if k != SCOPE))
    plan = {r['identity']:r['hash'] for r in payload['input_plan']}
    committed = {r['identity']:r['hash'] for r in before['committed_records']}
    remaining = before['receipt_remaining_identities']
    continued = {r['identity']:r['hash'] for r in after['committed_records']}
    remaining_after = after['receipt_remaining_identities']
    continuation_count = len(continued)-len(committed)
    durable = (len(plan) == 1000 and len(payload['input_plan']) == 1000
        and len(committed) == len(before['committed_records']) == 512
        and all(plan.get(k) == v for k, v in committed.items())
        and before['hot'] == 1288 and before['progress'] == [512, 512]
        and before['receipt_hash'] == payload['archive_receipt']['hash'] == payload['durable_archive_hash'])
    receipt = (before['receipt_remaining'] == 488 and len(remaining) == len(set(remaining)) == 488
        and set(remaining) == set(plan)-set(committed)
        and 0 <= continuation_count <= 488 and set(committed) <= set(continued)
        and all(plan.get(k) == v for k, v in continued.items())
        and after['receipt_remaining'] == len(remaining_after) == len(set(remaining_after)) == 488-continuation_count
        and set(remaining_after) == set(plan)-set(continued)
        and after['receipt_hash'] == (before['receipt_hash'] if remaining_after else None))
    completed = (interruption and one_retry and accounted and before['pending'] is False
        and before['pending_identity'] is None and before['arbiter_failed'] is False)
    next_turn = payload['next_turn']
    next_usable = (next_turn['accepted'] is True and next_turn['completed'] is True
        and next_turn['error'] is None and payload['second_error'] is None and isinstance(next_turn['result'], dict)
        and next_turn['event']['sequence'] is not None and pending is not None
        and next_turn['event']['sequence'] > pending['sequence']
        and next_turn['event']['generation'] == payload['generation']
        and next_turn['event'].get('completion') == 'completed'
        and after['pending'] is False and after['pending_identity'] is None
        and after['arbiter_failed'] is False and after['runtime_failure'] is None)
    return dict(urgent_admitted=payload['urgent']['accepted'] is True,
        urgent_completed=payload['urgent']['completed'] is True and payload['urgent']['error'] is None
            and payload['urgent']['result'] == 1928,
        accepted_future_completed=payload['first_turn']['accepted'] is True and payload['first_turn']['completed'] is True,
        completion_query_interrupted=interruption, bounded_completion_retry=one_retry,
        cooperative_yield=payload['first_error'] == 'EvidenceUnavailable:evidence_background_yield',
        native_slice_committed=durable, receipt_continuation_preserved=receipt,
        transaction_closed=before['open_transaction'] is False and after['open_transaction'] is False,
        integrity=before['integrity'] == after['integrity'] == 'ok',
        cooperative_error_nonfatal=before['runtime_failure'] is None,
        episode_not_rebased=before['episodes'] == after['episodes'],
        durable_accounting=accounted, no_duplicate_durable_progress=0 <= continuation_count <= 488
            and len(continued) == len(after['committed_records'])
            and after['progress'] == [512+continuation_count, 512+continuation_count]
            and after['hot'] == 1288-continuation_count
            and next_turn['event'].get('durable_records', {}).get(SCOPE, 0) == continuation_count
            and (continuation_count == 0 or next_turn['event'].get('selected') == 'archive'),
        decision_completed=completed, next_admission_usable=next_usable,
        original_contract=payload['original_thresholds'] is True and payload['repair_applied'] is False
            and payload['material_executions'] == 0 and payload['seed_records'] == 1928)


def validate_witness(payload):
    try:
        if payload['witness_version'] != WITNESS_VERSION:
            raise ValueError('m1_witness_version')
        if any(payload[k] != v or type(payload[k]) is not type(v) for k, v in evidence_fields(payload).items()):
            raise ValueError('m1_read_evidence_contradiction')
        gates = witness_gates(payload)
        if payload['gates'] != gates or any(type(v) is not bool for v in payload['gates'].values()):
            raise ValueError('m1_fabricated_gate')
        if payload['passed'] is not all(gates.values()):
            raise ValueError('m1_fabricated_outcome')
        return payload['passed']
    except (KeyError, TypeError, IndexError, AttributeError) as exc:
        raise ValueError('m1_witness_evidence_missing_or_malformed') from exc


def qualify(output):
    from meme_machine import solana_evidence_service as service
    from meme_machine.solana_evidence_control import PriorityOwner
    from meme_machine.solana_evidence_plane import EvidenceWriter
    from meme_machine.solana_maintenance_runtime import ArchiveFlight, MaintenanceRuntime
    from meme_machine.solana_provider_config import AlchemyEndpoint
    from .native import ENDPOINT
    clock=DeterministicClock();clock.begin();box={};accepted=[];injections=[];accounting=[]
    path=Path(output)/'m1.sqlite'
    def seed():
        state=service.ServiceState(path,AlchemyEndpoint.parse(ENDPOINT));state.writer.clock=clock.time
        for i in range(1,129):
            state.writer.ingest(records(clock,'account:'+b58(i.to_bytes(32,'big')),1,'m1-ledger',account=True))
        assert state.writer.archive(clock.time()-180)==128
        rows=records(clock,SCOPE,1800,'m1-recovery')
        state.writer.ingest(rows[:1000]);state.writer.ingest(rows[1000:])
        sub=next(s for s in service.program_subscriptions() if s.scope==SCOPE)
        state.fence.block(sub,json.loads(empty_frame(10000,int(clock.time()))),clock.time())
        runtime=MaintenanceRuntime(state,monotonic=clock.monotonic,wall=clock.time)
        plan,receipt=EvidenceWriter.prepare_and_write_archive(path,state.archive_plan())
        assert len(plan)==1000
        flight=ArchiveFlight(pending=(plan,receipt),submitted=clock.monotonic(),generation=runtime.generation)
        archive=path.parent/(path.name+'.archive')/receipt['name']
        box.update(state=state,runtime=runtime,flight=flight,receipt=receipt,
            input_plan=[dict(identity=row['identity'],hash=row['hash']) for row in plan],
            archive_hash=sha256(archive.read_bytes()))
        return state
    def outcome(future):
        try:
            return None, future.result(20)
        except BaseException as exc:
            return type(exc).__name__+':'+str(exc), None
    def submit(owner,fn,priority):
        future=owner.submit(fn,priority=priority);accepted.append(future);return future
    def observe(state):
        r=box['runtime'];f=box['flight']
        # An independent read-only connection proves committed SQLite effects.
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
            progress=db.execute("SELECT units,records FROM maintenance_progress WHERE scope=? AND side='archive'",(SCOPE,)).fetchone()
            return dict(pending=r.arbiter.pending is not None,
                pending_identity=decision_identity(r.arbiter.pending,r.generation),runtime_failure=r.failure,
                arbiter_failed=r.arbiter.failed,hot=db.execute(
                    "SELECT COUNT(*) FROM records WHERE scope=? AND body IS NOT NULL",(SCOPE,)).fetchone()[0],
                progress=list(progress) if progress else None,
                committed_records=[dict(identity=i,hash=h) for i,h in db.execute(
                    "SELECT identity,hash FROM records WHERE scope=? AND body IS NULL AND archive=? ORDER BY identity",(SCOPE,box['receipt']['name']))],
                episodes=[list(row) for row in db.execute('SELECT * FROM maintenance_episodes ORDER BY scope,side')],
                open_transaction=state.writer.db.in_transaction,receipt_remaining=len(f.pending[0]) if f.pending else 0,
                receipt_remaining_identities=[row['identity'] for row in f.pending[0]] if f.pending else [],
                receipt_hash=f.pending[1]['hash'] if f.pending else None,
                integrity=db.execute('PRAGMA integrity_check').fetchone()[0])
    with patch.object(service,'time',clock):
        owner=PriorityOwner(seed,clock=clock.monotonic)
        try:
            owner.ready.result(20);r=box['runtime'];f=box['flight']
            def turn(state):
                connection=state.writer.db;observer=LedgerReads(connection,r)
                original_complete=r.arbiter.complete
                def complete(decision, now, progress, *, record_progress=None):
                    row=dict(decision=decision_identity(decision,r.generation),
                        pending_before=decision_identity(r.arbiter.pending,r.generation),
                        exact_pending_identity=decision is r.arbiter.pending,read_ordinal=len(observer.reads),
                        transaction_open=connection.in_transaction,progress=dict(progress),
                        record_progress=dict(record_progress or {}),ledger=list(connection.execute(
                            "SELECT units,records FROM maintenance_progress WHERE scope=? AND side='archive'",(SCOPE,)).fetchone()),
                        returned=False,error=None,pending_after=None)
                    accounting.append(row)
                    try:
                        result=original_complete(decision,now,progress,record_progress=record_progress)
                        row['returned']=True
                        return result
                    except BaseException as exc:
                        row['error']=type(exc).__name__+':'+str(exc)
                        raise
                    finally:
                        row['pending_after']=decision_identity(r.arbiter.pending,r.generation)
                def trace(sql):
                    if sql.startswith(PROGRESS_SELECT) and len(observer.reads)==2:
                        injections.append(observer.reads[-1]['ordinal'])
                        box['urgent']=submit(owner,lambda state:state.writer.db.execute('SELECT COUNT(*) FROM records').fetchone()[0],0)
                state.writer.db=observer
                connection.set_trace_callback(trace)
                try:
                    with patch.object(r.arbiter,'complete',complete):
                        return r.turn(f,clock.monotonic())
                finally:
                    connection.set_trace_callback(None);state.writer.db=connection
                    box['reads']=observer.reads
            first=submit(owner,turn,4);first_error,_=outcome(first)
            urgent_error,urgent_result=outcome(box['urgent']) if 'urgent' in box else (None,None)
            before=submit(owner,observe,2).result(10)
            second=submit(owner,lambda state:r.turn(f,clock.monotonic()),4);second_error,second_result=outcome(second)
            after=submit(owner,observe,2).result(10)
            payload=dict(witness_version=WITNESS_VERSION,ledger_reads=box['reads'],
                interruption_injections=injections,completion_accounting=accounting,
                first_turn=dict(accepted=first in accepted,completed=first.done()),
                urgent=dict(accepted='urgent' in box and box['urgent'] in accepted,
                    completed='urgent' in box and box['urgent'].done(),error=urgent_error,result=urgent_result),
                next_turn=dict(accepted=second in accepted,completed=second.done(),error=second_error,
                    result=second_result,event=dict(r.ring[-1])),
                first_error=first_error,second_error=second_error,before=before,after=after,
                generation=r.generation,seed_records=1928,input_plan=box['input_plan'],
                archive_receipt=box['receipt'],durable_archive_hash=box['archive_hash'],
                original_thresholds=True,repair_applied=False,material_executions=0)
            payload.update(evidence_fields(payload));payload['gates']=witness_gates(payload)
            payload['passed']=all(payload['gates'].values())
            validate_witness(payload)
            return payload
        finally:
            owner.close()
            assert all(f.done() for f in accepted) and not owner.thread.is_alive()
