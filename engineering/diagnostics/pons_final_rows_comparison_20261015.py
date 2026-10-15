"""One offline final-report reader comparison on unchanged retained Pons rows.

This exercises History.rows, including its real JSON/hash checks and sorting.
It does not run Runtime, reconstruct market history, replay a monetary book,
or establish held protection or whole-machine throughput. No population scaling
or invented candidate records is permitted.
"""
import argparse
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import sqlite3
import time

ROW_LIMIT = 2048
BODY_LIMIT = 16 * 1024**2
FILE_LIMIT = 34 * 1024**2


def copied_records(path):
    from meme_machine.runtime.journal import digest
    from meme_machine.runtime.survivor_history import History
    if path.stat().st_size > FILE_LIMIT:
        raise ValueError('cohort_file_bound')
    raw = path.read_bytes()
    manifest = json.loads(path.with_suffix('.manifest.json').read_text())
    if manifest['sha256'] != hashlib.sha256(raw).hexdigest() or manifest['bytes'] != len(raw):
        raise ValueError('cohort_manifest_mismatch')
    cohort = json.loads(raw)
    if (cohort['schema'] != 'pons-authentic-final-report-cohort-v1'
            or cohort['scope'] != 'AUTHENTIC_ACTIVE_HISTORY_REPORT_INPUT_NOT_MARKET_REPLAY_OR_NATIVE_BOOK'
            or cohort['status'] != 'AUTHENTIC_ACTIVE_COHORT_VERIFIED'):
        raise ValueError('authentic_complete_cohort_unavailable')
    items = cohort['items']
    if not 0 < len(items) <= ROW_LIMIT or digest(items) != cohort['raw_records_digest']:
        raise ValueError('cohort_record_bound_or_digest')
    verifier = History.__new__(History)
    records = []
    for item in items:
        value = verifier._verified((item['body'], item['hash']))
        if value['id'] != item['id'] or value.get('state') == 'retired':
            raise ValueError('cohort_identity_or_active_predicate')
        if value.get('position'):
            raise ValueError('held_native_book_not_in_reader_fixture')
        records.append((item['id'], item['body'], item['hash']))
    size = sum(len(value.encode('utf-8')) for row in records for value in row)
    if (size > BODY_LIMIT or size != cohort['source_row_bytes']
            or len(records) != cohort['authenticated_rows']
            or not 0 <= cohort['read_seconds'] <= 2):
        raise ValueError('complete_cohort_admission_mismatch')
    if len({row[0] for row in records}) != len(records):
        raise ValueError('duplicate_copied_identity')
    return cohort, raw, records


def report(history, reuse, handoff_ready):
    final_rows = history.rows() if reuse else None
    protected = [row['id'] for row in (final_rows if reuse else history.rows())]
    safety = [row.get('position_safety', dict(at=0, evidence_current=False,
        blocker='pons_survivor_position_not_observed'))
        for row in (final_rows if reuse else history.rows()) if row.get('position')]
    count = len(final_rows if reuse else history.rows())
    # Authentic input has no held references. Calling the real helper with no
    # book is valid only because no _load is reached; it proves no held path.
    handoff = handoff_ready(None, final_rows if reuse else history.rows())
    return dict(protected=protected, position_safety=safety,
                candidate_count=count, durable_handoff=handoff)


def variant(path, records, *, reuse):
    from meme_machine.runtime.journal import digest
    from meme_machine.runtime.survivor_commit import handoff_ready
    from meme_machine.runtime.survivor_history import History

    class MeasuredHistory(History):
        def rows(self, **kwargs):
            self.row_calls += 1
            return super().rows(**kwargs)

        def _verified(self, row):
            self.verified_rows += int(row is not None)
            return super()._verified(row)

    db = sqlite3.connect(path, isolation_level=None)
    history = MeasuredHistory.__new__(MeasuredHistory)
    history.db = db
    history.row_calls = history.verified_rows = 0
    try:
        # Exact production candidates schema, containing only the unchanged
        # copied inputs. Constructor/recovery and economic stores are excluded.
        db.execute('CREATE TABLE candidates(id TEXT PRIMARY KEY,body TEXT NOT NULL,hash TEXT NOT NULL)')
        with db:
            db.executemany('INSERT INTO candidates VALUES(?,?,?)', records)
        before_rows = db.execute('SELECT id,body,hash FROM candidates ORDER BY id').fetchall()
        changes = db.total_changes
        before_wall, before_cpu = time.perf_counter(), time.process_time()
        result = report(history, reuse, handoff_ready)
        cpu, wall = time.process_time()-before_cpu, time.perf_counter()-before_wall
        after_rows = db.execute('SELECT id,body,hash FROM candidates ORDER BY id').fetchall()
        assert before_rows == after_rows == sorted(records)
        assert db.total_changes == changes
        expected_calls = 1 if reuse else 4
        assert history.row_calls == expected_calls
        assert history.verified_rows == len(records) * expected_calls
        return dict(variant='one_final_population' if reuse else 'original_four_populations',
            wall_seconds=wall, cpu_seconds=cpu, rows_calls=history.row_calls,
            candidate_selects=history.row_calls, verified_rows=history.verified_rows,
            decoded_body_bytes=sum(len(row[1].encode('utf-8')) for row in records) * expected_calls,
            unchanged_raw_rows_digest=digest(after_rows), output_digest=digest(result),
            candidate_count=result['candidate_count'], held_reference_rows=0,
            exact_output=result)
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cohort', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    from operational.tests import network_guard
    from meme_machine.operational.artifact_storage import Policy, Scratch, headroom
    network_guard()

    def expired(*_):
        raise TimeoutError('final_rows_comparison_30_second_bound')

    signal.signal(signal.SIGALRM, expired)
    signal.alarm(30)
    started = time.monotonic()
    try:
        cohort, raw, records = copied_records(args.cohort)
        headroom(args.output.parent, 64 * 1024, warn=False)
        source_root = Path(__file__).resolve().parents[2]
        sources = {name: hashlib.sha256((source_root / name).read_bytes()).hexdigest() for name in (
            'meme_machine/runtime/survivor_history.py',
            'meme_machine/lanes/pons/pons_survivor_runtime.py')}
        with Scratch(policy=replace(Policy.environment(), scratch_max_bytes=128 * 1024**2)) as scratch:
            results = []
            for reuse in (False, True):
                scratch.check()
                results.append(variant(scratch.path / ('reuse.sqlite' if reuse else 'original.sqlite'),
                                       records, reuse=reuse))
                scratch.check()
            assert results[0]['exact_output'] == results[1]['exact_output']
            assert results[0]['unchanged_raw_rows_digest'] == results[1]['unchanged_raw_rows_digest']
            assert sources == {name: hashlib.sha256((source_root / name).read_bytes()).hexdigest()
                               for name in sources}
            for result in results:
                del result['exact_output']
            output = dict(status='AUTHENTIC_FINAL_REPORT_READER_PAIR_EQUIVALENT',
                at=datetime.now(timezone.utc).isoformat(), elapsed_seconds=time.monotonic()-started,
                driver_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), sources=sources,
                cohort=dict(sha256=hashlib.sha256(raw).hexdigest(), records=len(records),
                            source_row_bytes=cohort['source_row_bytes'], collected_at=cohort['collected_at']),
                variants=results, limits=dict(wall_seconds=30, fixture_bytes=128 * 1024**2,
                    source_rows=ROW_LIMIT, source_row_bytes=BODY_LIMIT, reporting_cycles_per_variant=1),
                provider_calls=0, authoritative_writes=0,
                scope='One final-report reader pair on the entire bounded authentic active population',
                limitations=['No runtime startup, market replay, monetary replay or held-position exercise',
                    'One sequential pair, not a statistical or matched OS-cache capacity comparison',
                    'CPU/wall include the same report projection and tiny read/authentication counters',
                    'Fixture creation, verification and storage checks are outside variant timing',
                    'No full-machine throughput, readiness or provider-suitability claim'])
            encoded = (json.dumps(output, sort_keys=True, indent=2)+'\n').encode()
            with os.fdopen(os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as saved:
                saved.write(encoded)
                saved.flush()
                os.fsync(saved.fileno())
            scratch.success = True
        print(json.dumps(dict(status=output['status'], records=len(records),
            variants=[{key: value[key] for key in ('variant', 'rows_calls', 'verified_rows',
                'decoded_body_bytes', 'cpu_seconds', 'wall_seconds')} for value in results])))
    finally:
        signal.alarm(0)


if __name__ == '__main__':
    main()
