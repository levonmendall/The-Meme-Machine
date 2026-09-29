"""One provider-free diagnostic of an unchanged E27 runtime, never qualification.

Observers call each original exactly once. No gate, workload, priority, sleep,
transaction, or source file is changed. Events are bounded and written after
execution. Worker timestamps travel in an ignored, diagnostic-only receipt key;
the original archive bytes, plan, commit fields and worker metrics are untouched.
"""
from __future__ import annotations
import argparse
import asyncio
from collections import Counter
from contextlib import ExitStack, contextmanager
import concurrent.futures
import functools
import hashlib
import itertools
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

# The workflow runs from the separate immutable runtime checkout.
sys.path.insert(0, os.getcwd())
from certification import run381_pressure as pressure
from certification import cleanup_recovery, combined_observer
from certification.maintenance_qualification import qualification, frozen_inputs
from meme_machine import solana_evidence_control as control
from meme_machine import solana_evidence_service as service
from meme_machine.solana_evidence_plane import EvidenceWriter
from meme_machine.solana_retention_outcome import RetentionProgress

SHA = '9356068cc92f9cadbd35adead3c33b532cbd4268'
TREE = 'b7fea73f83b29e569b9c8ffde47ae11ecb04cf1d'
PARENT = 'fdeee2721d2bb63e0ff3234328b06936257493b1'
NATIVE_MEASURED_ARCHIVE = pressure.measured_archive
TLS = threading.local()
TRACE_KEY = '_e27_diagnostic_worker_timing'


def snapshot_key(snapshot):
    rows = (snapshot or {}).get('rows') or []
    if not rows:
        return None
    # Never hash/retain payloads or full request text in timing events.
    text = rows[0]['identity'] + '\n' + rows[-1]['identity'] + '\n' + str(len(rows))
    return hashlib.sha256(text.encode()).hexdigest()[:24]


def traced_measured_archive(path, snapshot, **kwargs):
    # Top-level function is spawn-importable; the native function is captured
    # before any parent patch and is also native after child module import.
    started = time.monotonic_ns()
    result = NATIVE_MEASURED_ARCHIVE(path, snapshot, **kwargs)
    ended = time.monotonic_ns()
    receipt = result[1]
    if receipt is not None:
        receipt[TRACE_KEY] = dict(start_ns=started, end_ns=ended,
                                  pid=os.getpid())
    return result


class Recorder:
    def __init__(self, limit=200_000):
        self.limit = limit
        self.events = []
        self.dropped = 0
        self.emit_ns = 0
        self.lock = threading.Lock()
        self.ids = itertools.count(1)
        self.started = time.monotonic_ns()
        self.owners = []

    def emit(self, kind, **fields):
        started = time.monotonic_ns()
        event = dict(t_ns=started, event=kind, tid=threading.get_ident(),
                     job=getattr(TLS, 'job', None), **fields)
        with self.lock:
            if len(self.events) < self.limit:
                self.events.append(event)
            else:
                self.dropped += 1
            self.emit_ns += time.monotonic_ns() - started

    def queue(self, owner):
        # Only read existing in-memory queue entries under their native lock.
        with owner.cv:
            return [dict(priority=x[0], sequence=x[1],
                         job=getattr(x[3], '_trace_job', None),
                         label=getattr(x[3], '_trace_label', None))
                    for x in owner.queue]

    def save(self, output):
        output.mkdir(parents=True, exist_ok=True)
        ended = time.monotonic_ns()
        with self.lock:
            events = sorted(self.events, key=lambda e: e['t_ns'])
        with (output/'events.jsonl').open('w') as target:
            for row in events:
                target.write(json.dumps(row, sort_keys=True)+'\n')
        stats = dict(events=len(events), dropped=self.dropped,
                     event_limit=self.limit, started_ns=self.started,
                     ended_ns=ended, emit_wall_ns=self.emit_ns,
                     emit_wall_fraction=self.emit_ns/max(1, ended-self.started),
                     overhead_definition='Measured event-emission wall time only; metadata/wrapper overhead is not included.',
                     canonical_authority=False, qualification_authority=False)
        (output/'trace-statistics.json').write_text(json.dumps(stats, indent=2)+'\n')
        return stats


def closure_values(fn):
    code = getattr(fn, '__code__', None)
    if code is None:
        return {}
    values = {}
    for name, cell in zip(code.co_freevars, fn.__closure__ or ()):
        try:
            values[name] = cell.cell_contents
        except ValueError:
            pass
    return values


def callback_metadata(fn, priority):
    values = closure_values(fn)
    target = values.get('fn', fn)
    nested = closure_values(target)
    names = getattr(getattr(target, '__code__', None), 'co_names', ())
    mapping = [('archive_commit_slice_and_plan', 'archive_commit_plan'),
               ('archive_plan', 'archive_plan'), ('retention', 'retention'),
               ('source_batch', 'source_commit'), ('publish_health', 'maintenance_health'),
               ('checkpoint_prepare', 'checkpoint_prepare'),
               ('checkpoint_finish', 'checkpoint_finish'),
               ('checkpoint_handoff_after_current', 'checkpoint_boundary')]
    label = next((label for name, label in mapping if name in names),
                 'urgent' if priority == 0 else 'foreground' if priority == 1 else 'other')
    receipt = nested.get('receipt')
    return dict(label=label, priority=priority,
                receipt=(receipt or {}).get('hash') if isinstance(receipt, dict) else None)


@contextmanager
def tracing(recorder):
    native_submit = control.PriorityOwner.submit
    native_pool_submit = pressure.MeasuredProcessPool.submit
    native_plan = service.ServiceState.archive_plan
    native_commit = EvidenceWriter.commit_archive
    native_source = pressure.MeasuredServiceState.source_batch
    native_retention = service.ServiceState.retention
    native_retired = RetentionProgress.commit
    native_handoff = control.PriorityOwner.checkpoint_handoff_after_current
    native_release = control.PriorityOwner.release_checkpoint_handoff
    native_eligible = combined_observer.eligible
    native_window = combined_observer.observe_window
    native_checkpoint = EvidenceWriter.checkpoint

    def submit(owner, fn, *, priority=1, expires=None):
        job = next(recorder.ids)
        metadata = callback_metadata(fn, priority)
        if owner not in recorder.owners:
            recorder.owners.append(owner)
        recorder.emit('owner_submit', request=job, **metadata)
        @functools.wraps(fn)
        def observed(state):
            previous = getattr(TLS, 'job', None)
            TLS.job = job
            recorder.emit('owner_start', request=job, **metadata)
            try:
                value = fn(state)
            except BaseException as exc:
                recorder.emit('owner_error', request=job,
                              error=type(exc).__name__, reason=str(exc)[:96], **metadata)
                raise
            else:
                recorder.emit('owner_end', request=job, **metadata)
                return value
            finally:
                TLS.job = previous
        observed._trace_job = job
        observed._trace_label = metadata['label']
        try:
            return native_submit(owner, observed, priority=priority, expires=expires)
        except BaseException as exc:
            recorder.emit('owner_rejected', request=job, error=type(exc).__name__, **metadata)
            raise

    def pool_submit(pool, fn, *args, **kwargs):
        archival = fn is EvidenceWriter.prepare_and_write_archive
        key = snapshot_key(args[1]) if archival else None
        if archival:
            recorder.emit('worker_submit', snapshot=key, rows=len(args[1]['rows']))
        future = native_pool_submit(pool, fn, *args, **kwargs)
        if archival:
            def ready(done):
                try:
                    plan, receipt = done.result()
                    recorder.emit('worker_ready', snapshot=key, rows=len(plan),
                        receipt=(receipt or {}).get('hash'),
                        worker=(receipt or {}).get(TRACE_KEY),
                        native_metrics=(receipt or {}).get('worker_metrics'),
                        queues=[recorder.queue(owner) for owner in recorder.owners])
                except BaseException as exc:
                    recorder.emit('worker_error', snapshot=key, error=type(exc).__name__)
            future.add_done_callback(ready)
        return future

    def archive_plan(state):
        recorder.emit('plan_start')
        try:
            snapshot = native_plan(state)
        except BaseException as exc:
            recorder.emit('plan_error', error=type(exc).__name__)
            raise
        recorder.emit('plan_end', snapshot=snapshot_key(snapshot),
                      rows=len(snapshot['rows']) if snapshot else 0)
        return snapshot

    def commit(writer, plan, receipt):
        meta = dict(receipt=(receipt or {}).get('hash'), rows=len(plan),
                    planned_by_scope=dict(Counter(row['body']['scope'] for row in plan)))
        recorder.emit('archive_slice_start', **meta)
        try:
            archived = native_commit(writer, plan, receipt)
        except BaseException as exc:
            recorder.emit('archive_slice_error', error=type(exc).__name__, **meta)
            raise
        recorder.emit('archive_slice_end', archived=archived, **meta)
        return archived

    def source(state, items):
        recorder.emit('source_start', frames=len(items))
        try:
            return native_source(state, items)
        finally:
            recorder.emit('source_end', frames=len(items))

    def retention(state):
        recorder.emit('retention_start')
        try:
            outcome = native_retention(state)
        except BaseException as exc:
            recorder.emit('retention_error', error=type(exc).__name__)
            raise
        recorder.emit('retention_end', retired=outcome.retired_records,
                      slices=outcome.committed_slices, pending=outcome.pending,
                      interrupted=outcome.interrupted, yield_reason=outcome.yield_reason)
        return outcome

    def retired(progress, scope, records, continuity, floor_updates, remaining):
        result = native_retired(progress, scope, records, continuity, floor_updates, remaining)
        recorder.emit('retention_slice_committed', scope=scope, retired=records,
                      continuity=continuity, floor_updates=floor_updates, remaining=remaining)
        return result

    def handoff(owner):
        result = native_handoff(owner)
        recorder.emit('checkpoint_handoff_start', token=id(result))
        return result

    def release(owner, token):
        recorder.emit('checkpoint_handoff_release', token=id(token))
        return native_release(owner, token)

    def eligible(db):
        result = native_eligible(db)
        recorder.emit('reader_eligibility', eligible=result, transaction=db.in_transaction)
        return result

    def window(reader, path, before, sample):
        result = native_window(reader, path, before, sample)
        recorder.emit('reader_observation', sample=dict(sample), before=dict(before))
        return result

    def checkpoint(path):
        recorder.emit('checkpoint_io_start')
        try:
            value = native_checkpoint(path)
        except BaseException as exc:
            recorder.emit('checkpoint_io_error', error=type(exc).__name__)
            raise
        recorder.emit('checkpoint_io_end', result=value)
        return value

    with ExitStack() as stack:
        for obj, name, replacement in [
            (control.PriorityOwner, 'submit', submit),
            (pressure.MeasuredProcessPool, 'submit', pool_submit),
            (pressure, 'measured_archive', traced_measured_archive),
            (service.ServiceState, 'archive_plan', archive_plan),
            (EvidenceWriter, 'commit_archive', commit),
            (pressure.MeasuredServiceState, 'source_batch', source),
            (service.ServiceState, 'retention', retention),
            (RetentionProgress, 'commit', retired),
            (control.PriorityOwner, 'checkpoint_handoff_after_current', handoff),
            (control.PriorityOwner, 'release_checkpoint_handoff', release),
            (combined_observer, 'eligible', eligible),
            (combined_observer, 'observe_window', window),
            (EvidenceWriter, 'checkpoint', staticmethod(checkpoint)),
        ]:
            stack.enter_context(patch.object(obj, name, replacement))
        yield


def identity():
    git = lambda *args: subprocess.check_output(['git', *args], text=True).strip()
    value = dict(sha=git('rev-parse', 'HEAD'), tree=git('rev-parse', 'HEAD^{tree}'),
                 parent=git('rev-parse', 'HEAD^'), clean=not git('status', '--porcelain'))
    if value != dict(sha=SHA, tree=TREE, parent=PARENT, clean=True):
        raise RuntimeError('diagnostic_runtime_identity_mismatch:'+json.dumps(value))
    if not frozen_inputs():
        raise RuntimeError('diagnostic_frozen_input_mismatch')
    return value


class Tests(unittest.TestCase):
    def test_bounded_recorder(self):
        record = Recorder(2)
        for _ in range(3): record.emit('test')
        self.assertEqual(len(record.events), 2)
        self.assertEqual(record.dropped, 1)

    def test_metadata_has_no_payload(self):
        receipt = dict(hash='h', name='n', bytes=1)
        plan = []
        fn = lambda state: state.archive_commit_slice_and_plan(plan, receipt)
        def timed(state): return fn(state)
        self.assertEqual(callback_metadata(timed, 4),
                         dict(label='archive_commit_plan', priority=4, receipt='h'))

    def test_snapshot_key_ignores_body(self):
        a = dict(rows=[dict(identity='a', encoded='secret')])
        b = dict(rows=[dict(identity='a', encoded='different')])
        self.assertEqual(snapshot_key(a), snapshot_key(b))

    def test_worker_preserves_native_fields_and_single_call(self):
        result = ([dict(identity='a')], dict(hash='h', name='n', bytes=1,
                   worker_metrics=dict(prepare_microseconds=1, publish_microseconds=2, records=1)))
        expected = json.loads(json.dumps(result))
        with patch.object(sys.modules[__name__], 'NATIVE_MEASURED_ARCHIVE', return_value=result) as native:
            actual = traced_measured_archive('p', dict(rows=[]), max_bytes=42)
            native.assert_called_once_with('p', dict(rows=[]), max_bytes=42)
        meta = actual[1].pop(TRACE_KEY)
        self.assertEqual(json.loads(json.dumps(actual)), expected)
        self.assertGreaterEqual(meta['end_ns'], meta['start_ns'])

    def test_worker_propagates_errors(self):
        with patch.object(sys.modules[__name__], 'NATIVE_MEASURED_ARCHIVE', side_effect=ValueError('test')):
            with self.assertRaises(ValueError): traced_measured_archive('p', {})

    def test_owner_preserves_priority_result_and_exception(self):
        class State:
            def close(self): pass
        recorder = Recorder()
        native = control.PriorityOwner.submit
        with tracing(recorder):
            owner = control.PriorityOwner(State)
            owner.ready.result(timeout=3)
            self.assertEqual(owner.submit(lambda state: 17, priority=0).result(timeout=3), 17)
            def bad(state): raise ValueError('test')
            with self.assertRaises(ValueError): owner.submit(bad, priority=4).result(timeout=3)
            owner.close()
        self.assertIs(control.PriorityOwner.submit, native)
        submits = [e for e in recorder.events if e['event']=='owner_submit']
        self.assertEqual([e['priority'] for e in submits], [0, 4])
        self.assertTrue(any(e['event']=='owner_error' for e in recorder.events))

    def test_no_extra_retention_invocation(self):
        class Writer:
            _retention_atomic = False
        class State:
            writer = Writer()
        from meme_machine.solana_retention_outcome import RetentionOutcome
        expected = RetentionOutcome(retired_records=4, pending=False)
        recorder = Recorder()
        with patch.object(service.ServiceState, 'retention', return_value=expected) as native:
            with tracing(recorder):
                value = service.ServiceState.retention(State())
            native.assert_called_once()
        self.assertIs(value, expected)
        self.assertEqual([e['event'] for e in recorder.events], ['retention_start','retention_end'])

    def test_worker_spawn_import(self):
        import multiprocessing
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            with pressure.NativeProcessPool(max_workers=1, mp_context=multiprocessing.get_context('spawn')) as pool:
                value = pool.submit(traced_measured_archive, str(Path(directory)/'db'), None).result(timeout=15)
        self.assertEqual(value, ([], None))

    def test_identity_still_frozen(self):
        self.assertEqual(identity()['sha'], SHA)


async def run(output):
    from certification.qualification_environment import require
    require()
    initial = identity()
    recorder = Recorder()
    row = None
    error = None
    output.mkdir(parents=True, exist_ok=True)
    (output/'diagnostic-intent.json').write_text(json.dumps(dict(
        runtime=initial, kind='single-non-authoritative-timing-diagnostic',
        frames=4445, retries=0, original_cohort_run=36525293113,
        canonical_authority=False, qualification_authority=False, market_authority=False,
        reason='Historical originals omit paired receipt timing and in-window owner/retention events.',
        trace_receipt_key=TRACE_KEY,
        source_files_changed=False, runtime_policy_changed=False), indent=2)+'\n')
    try:
        with qualification(), tracing(recorder):
            row = await cleanup_recovery.extended_run(output/'diagnostic-runtime')
    except BaseException as exc:
        error = dict(type=type(exc).__name__, message=str(exc)[:500])
        raise
    finally:
        stats = recorder.save(output)
        final = identity()
        (output/'diagnostic-index.json').write_text(json.dumps(dict(
            initial_identity=initial, final_identity=final, error=error,
            runtime_result=(row or {}).get('passed'),
            observed_failures=((row or {}).get('cleanup_recovery') or {}).get('failures'),
            trace=stats, historical_cohort_unchanged=True,
            canonical_authority=False, qualification_authority=False,
            no_candidate_created=True, no_promotion=True, no_phase_f=True), indent=2)+'\n')
        manifest = {str(p.relative_to(output)):hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in sorted(output.rglob('*')) if p.is_file()}
        (output/'SHA256.json').write_text(json.dumps(manifest, indent=2)+'\n')
    # A failed diagnostic workload is preserved evidence, not a reason to rerun.
    return 0 if stats['dropped']==0 else 2


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.self_test:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(Tests)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        raise SystemExit(0 if result.wasSuccessful() else 1)
    if args.output is None: parser.error('--output is required')
    raise SystemExit(asyncio.run(run(args.output)))
