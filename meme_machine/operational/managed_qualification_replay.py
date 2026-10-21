"""Provider-free comparison over one just-stopped, isolated native generation.

Only the two optimized read seams differ. The reference seams are the exact
predecessor operations; both readers use the same unchanged strategy functions.
No held-position or complete strategy-readiness claim follows from this check.
"""
import hashlib
import json
from pathlib import Path
import tempfile
import time

from .managed_pump_qualification import QualificationReader

PREDECESSOR = '66c9f5b67ac9b9934ed874a0fd18c2dad29968dc'


class ReferenceReader(QualificationReader):
    def _history_event(self, mint, identity, *, prepared=None):
        self._reference_scope(mint, identity)
        return self.history.event('pump', mint, identity)

    def _creation_events(self, mint):
        self._reference_scope(mint, kind='pump_create')
        return self.history.events('pump', mint, kind='pump_create',
                                   cancelled=self.cancelled.is_set)


class MissingReplayInput(ValueError):
    pass


class NoNetworkProvider:
    """Unknown provider inputs are missing evidence, never a synthetic quote."""
    def __init__(self):
        self.missing = 0

    def snapshot(self, *args):
        self.missing += 1
        raise MissingReplayInput('qualification_replay_snapshot_unavailable')

    concentration = snapshot


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _output(reader):
    digest = hashlib.sha256()
    rows = 0
    for table, order in (('observations', 'sequence'), ('candidate_state', 'mint')):
        digest.update(table.encode())
        for row in reader.db.execute('SELECT * FROM ' + table + ' ORDER BY ' + order):
            raw = _canonical(row).encode()
            digest.update(len(raw).to_bytes(8, 'big'))
            digest.update(raw)
            if table == 'observations':
                rows += 1
    return rows, digest.hexdigest()


def compare_readers(config, *, until, as_of, decision_target=None):
    """Replay the same published prefix and verify durable resume independently.

    Source/history handles stay read-only. Separate observation files remain in
    this fresh epoch. The caller owns the ORIGINAL provider-free replay lease
    and fingerprints native evidence before and after this comparison.
    """
    if decision_target is not None and (type(decision_target) is not int or decision_target <= 0):
        raise ValueError('qualification_replay_retained_integer_target_required')
    directory = Path(tempfile.mkdtemp(prefix='qualification-replay-', dir=config.root))
    results = []
    for base, name in ((ReferenceReader, 'reference'), (QualificationReader, 'optimized')):
        path = directory / (name + '.sqlite')
        costs = {phase: dict(calls=0, wall_nanoseconds=0, cpu_nanoseconds=0)
                 for phase in ('native_reference', 'creation_history')}
        def measured(phase, operation, *args, **kwargs):
            wall, cpu = time.perf_counter_ns(), time.thread_time_ns()
            try:
                return operation(*args, **kwargs)
            finally:
                metric = costs[phase]
                metric['calls'] += 1
                metric['wall_nanoseconds'] += time.perf_counter_ns()-wall
                metric['cpu_nanoseconds'] += time.thread_time_ns()-cpu
        class Reader(base):
            @property
            def path(self):
                return path

            def _history_event(self, *args, **kwargs):
                return measured('native_reference', super()._history_event, *args, **kwargs)

            def _creation_events(self, *args, **kwargs):
                return measured('creation_history', super()._creation_events, *args, **kwargs)
        provider = NoNetworkProvider()
        reader = Reader(config, clock=lambda: as_of, provider=provider,
                        decision_target=decision_target)
        acknowledgements = []
        counts = {'history_selects': 0, 'canonical_selects': 0, 'source_selects': 0}
        def trace(key):
            def count(sql):
                if sql.lstrip().upper().startswith(('SELECT', 'WITH')):
                    counts[key] += 1
            return count
        try:
            if not reader._open():
                raise ValueError('qualification_replay_source_unavailable')
            begun, cpu = time.monotonic(), time.thread_time()
            reader.history.db.set_trace_callback(trace('history_selects'))
            reader.plane.reader.db.set_trace_callback(trace('canonical_selects'))
            # RuntimeEvidence normally emits consumer acknowledgements. A
            # comparison may compare their intents, but has no ACK authority.
            reader.plane.acknowledge = lambda *args: acknowledgements.append(args)
            def no_command(**request):
                raise ValueError('qualification_replay_ipc_refused')
            reader.plane.command = no_command
            for db in (reader.db, reader.history.db, reader.plane.reader.db):
                db.set_progress_handler(lambda: int(time.monotonic() >= until), 1000)
            tracked = set()
            source_complete = True
            while True:
                if time.monotonic() >= until:
                    raise ValueError('qualification_replay_deadline')
                for db in getattr(reader.history, '_source_readers', {}).values():
                    if id(db) not in tracked:
                        db.set_trace_callback(trace('source_selects'))
                        db.set_progress_handler(lambda: int(time.monotonic() >= until), 1000)
                        tracked.add(id(db))
                snapshot = reader.step()
                # A lazy canonical connection can be opened within this turn.
                # Do not report its untraced first reads as zero operations.
                source_complete &= all(id(db) in tracked for db in
                    getattr(reader.history, '_source_readers', {}).values())
                if not snapshot.get('processed_this_turn'):
                    break
            output = _output(reader)
            state = dict(snapshot)
            ack_digest = hashlib.sha256(_canonical(acknowledgements).encode()).hexdigest()
        finally:
            reader.close()
        elapsed, cpu_seconds = time.monotonic()-begun, time.thread_time()-cpu
        read_costs = {key: dict(value) for key, value in costs.items()}
        # Reopen the exact private observation store through the normal reader
        # identity/rebuild path, rather than treating file existence as recovery.
        resumed = Reader(config, clock=lambda: as_of, provider=NoNetworkProvider(),
                         decision_target=decision_target)
        try:
            if time.monotonic() >= until or not resumed._open():
                raise ValueError('qualification_replay_restart_unavailable')
            resumed.plane.acknowledge = lambda *args: None
            resumed.plane.command = no_command
            after_restart = resumed.step()
            restarted = (_output(resumed) == output
                and after_restart == state)
        finally:
            resumed.close()
        results.append(dict(implementation=name, rows=output[0], output_sha256=output[1],
            ack_intents_sha256=ack_digest, snapshot=state, restart_verified=restarted,
            missing_provider_inputs=provider.missing, **counts,
            source_selects_complete=source_complete,
            read_costs=read_costs,
            elapsed_seconds=elapsed, cpu_seconds=cpu_seconds))
    reference, optimized = results
    coherent = all(reference[key] == optimized[key] for key in
        ('rows', 'output_sha256', 'ack_intents_sha256', 'snapshot'))
    incomplete = sum(row['missing_provider_inputs'] + sum(
        row['snapshot'].get('stages', {}).get(stage, 0) for stage in
        ('creation_unavailable', 'decision_target_unavailable',
         'native_evidence_incomplete', 'postgraduation_unproven'))
        for row in results)
    restarted = all(row['restart_verified'] for row in results)
    return dict(verified=coherent and restarted and incomplete == 0,
        coherent=coherent, complete=incomplete == 0 and all(
            row['snapshot'].get('native_event_backlog') == 0 for row in results),
        reader_restart_verified=restarted, incomplete_outcomes=incomplete,
        input_rows=reference['rows'], output_rows=optimized['rows'],
        provider_requests=0, predecessor=PREDECESSOR, as_of=as_of,
        timing_order='reference_then_optimized_not_cache_neutral',
        scope='pump_current_late_curve_published_prefix_no_uncaptured_provider_inputs',
        reference=reference, optimized=optimized)
