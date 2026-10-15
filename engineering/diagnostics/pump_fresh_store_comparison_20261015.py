"""Bounded economic-store comparison on unique retained authentic records.

Each variant starts with a new disposable database. No source identities are
invented or re-ingested into an already populated store. This measures the exact
RollingHistory storage contract, not acquisition, complete historical state,
strategy readiness, full-machine capacity or a faithful market replay.
"""
import argparse
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import sqlite3
import time
from types import SimpleNamespace

TABLES = ('rolling_economic_events', 'rolling_economic_addresses',
          'rolling_event_lineage', 'candidate_content_receipts',
          'native_order_attestations', 'cursors', 'counters')


def sql_label(sql):
    words = sql.strip().upper().split()
    verb = words[0] if words else 'EMPTY'
    table = next((name for name in (*TABLES, 'canonical_evidence') if name.upper() in words), 'other')
    return verb+':'+table


class MeasuredDB:
    """Fixed labels only; no SQL, bindings or expanded statement collection."""
    def __init__(self, db):
        self.db = db
        self.rows = defaultdict(lambda: dict(api_calls=0, row_steps=0, wall_seconds=0., cpu_seconds=0.))
        self.vm_steps = 0
        db.set_progress_handler(self.progress, 1000)

    def progress(self):
        self.vm_steps += 1000
        return 0

    def __getattr__(self, name):
        return getattr(self.db, name)

    def call(self, method, sql, args, steps):
        label = sql_label(sql)
        row = self.rows[label]
        before, cpu = time.perf_counter(), time.thread_time()
        try:
            return method(sql, *args)
        finally:
            row['api_calls'] += 1
            row['row_steps'] += steps
            row['wall_seconds'] += time.perf_counter()-before
            row['cpu_seconds'] += time.thread_time()-cpu

    def execute(self, sql, *args):
        return self.call(self.db.execute, sql, args, 1)

    def executemany(self, sql, values):
        values = tuple(values)
        return self.call(self.db.executemany, sql, (values,), len(values))


def records(cohort):
    from meme_machine.solana_evidence_plane import FinalizedRecord, canonical, digest
    from meme_machine.solana_economic_preparation import prepare_economic_record
    result = []
    for item in cohort['items']:
        body, lineage = item['body'], item['lineage']
        assert canonical(body) == item['encoded'] and digest(body) == item['hash']
        values = dict(body, addresses=tuple(body['addresses']), source=lineage['source'],
                      endpoint_identity=lineage['endpoint'], observed_at=item['first_seen'])
        record = FinalizedRecord(**values)
        product = prepare_economic_record(record)
        assert product.encoded == item['encoded'] and product.checksum == item['hash']
        assert product.economic_hash == item['receipt']['economic_hash']
        assert record.transaction_index is not None
        result.append(product)
    assert len({r.record.identity for r in result}) == len(result)
    return sorted(result, key=lambda p: (p.record.slot, p.record.scope,
                                        p.record.transaction_index, p.record.event_index, p.record.identity))


def variant(root, products, *, bulk, measured, check):
    from meme_machine.solana_evidence_plane import EvidenceWriter
    from meme_machine.solana_evidence_service import FinalizedFence
    from meme_machine.solana_selective_source import install
    path = root / ('bulk' if bulk else 'scalar')
    path = path.with_name(path.name+('-measured' if measured else '-plain')).with_suffix('.sqlite')
    now = max(p.record.observed_at for p in products)+1
    writer = EvidenceWriter(path, clock=lambda: now)
    try:
        state = SimpleNamespace(writer=writer, fence=FinalizedFence(writer,
            endpoint_identity=products[0].record.endpoint_identity))
        history = install(state)
        history.clock = history.lifecycle.clock = lambda: now
        measured_db = MeasuredDB(writer.db) if measured else None
        if measured_db is not None:
            writer.db = history.db = history.rolling.db = measured_db
        groups = defaultdict(list)
        for product in products:
            groups[product.record.slot].append(product)
        before, cpu = time.perf_counter(), time.thread_time()
        operation_wall = operation_cpu = guard_wall = guard_cpu = 0.
        for batch in groups.values():
            step, step_cpu = time.perf_counter(), time.thread_time()
            with writer.transaction():
                if bulk:
                    assert history.rolling.store_many(tuple(p.record for p in batch), tuple(batch))
                else:
                    for product in batch:
                        history.rolling.store(product.record, serialized=product)
            operation_wall += time.perf_counter()-step
            operation_cpu += time.thread_time()-step_cpu
            step, step_cpu = time.perf_counter(), time.thread_time()
            check()
            guard_wall += time.perf_counter()-step
            guard_cpu += time.thread_time()-step_cpu
        elapsed, used_cpu = time.perf_counter()-before, time.thread_time()-cpu
        # Queries below are verification, outside the measured path.
        actual = writer.db.db if measured_db is not None else writer.db
        actual.set_progress_handler(None, 0)
        snapshots = {}
        for table in TABLES:
            rows = actual.execute('SELECT rowid,* FROM '+table+' ORDER BY rowid').fetchall()
            snapshots[table] = dict(rows=len(rows), hash=hashlib.sha256(
                json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()).hexdigest())
        integrity = actual.execute('PRAGMA quick_check').fetchone()
        assert integrity == ('ok',)
        actual_rows = actual.execute('SELECT identity,body,hash,first_seen FROM rolling_economic_events').fetchall()
        expected = {p.record.identity: (p.encoded, p.checksum, p.record.observed_at) for p in products}
        assert {identity: (body, checksum, seen) for identity, body, checksum, seen in actual_rows} == expected
        result = dict(variant='bulk' if bulk else 'scalar', measured=measured,
            records=len(products), distinct_slots=len(groups), wall_seconds=elapsed, cpu_seconds=used_cpu,
            store_transaction_wall_seconds=operation_wall, store_transaction_cpu_seconds=operation_cpu,
            containment_guard_wall_seconds=guard_wall, containment_guard_cpu_seconds=guard_cpu,
            snapshot=snapshots, quick_check='ok', exact_input_economics=True,
            database_main_bytes=path.stat().st_size,
            method_metrics={} if measured_db is None else dict(measured_db.rows),
            vm_steps_quantized_lower_bound=None if measured_db is None else measured_db.vm_steps)
        return result
    finally:
        writer.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cohort', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    from operational.tests import network_guard
    from meme_machine.operational.artifact_storage import Policy, Scratch
    from unittest.mock import patch
    network_guard()
    def expired(*_):
        raise TimeoutError('fresh_store_comparison_90_second_bound')
    signal.signal(signal.SIGALRM, expired)
    signal.alarm(90)
    started = time.monotonic()
    try:
        raw = args.cohort.read_bytes()
        assert len(raw) <= 16*1024**2
        cohort = json.loads(raw)
        assert cohort['scope'] == 'AUTHENTIC_RETAINED_ECONOMIC_STORE_COHORT_NOT_RAW_FEED_OR_FULL_MACHINE_REPLAY'
        products = records(cohort)
        assert 0 < len(products) <= 8192
        sources = {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in (
            'meme_machine/solana_rolling_history.py', 'meme_machine/solana_selective_history.py')}
        with Scratch(policy=replace(Policy.environment(), scratch_max_bytes=256*1024**2)) as scratch:
            # Preserve the scratch binding but remove all application paths and
            # credentials from fixture constructors. No production store opens.
            with patch.dict(os.environ, {'TMPDIR': str(scratch.path), 'MM_SOLANA_HISTORY_SEPARATED': '1'}, clear=True):
                results = [variant(scratch.path, products, bulk=bulk, measured=measured, check=scratch.check)
                           for measured in (False, True) for bulk in (False, True)]
            assert all(r['snapshot'] == results[0]['snapshot'] for r in results)
            assert sources == {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in sources}
            result = dict(status='AUTHENTIC_ECONOMIC_STORE_PAIR_EQUIVALENT',
                at=datetime.now(timezone.utc).isoformat(), elapsed_seconds=time.monotonic()-started,
                driver_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                cohort=dict(path=str(args.cohort), sha256=hashlib.sha256(raw).hexdigest(),
                            records=len(products), source_window=cohort['source_window']),
                sources=sources, variants=results, provider_calls=0, authoritative_writes=0,
                scope='Unique retained authentic economic records on fresh disposable stores; exact storage-contract comparison only',
                limitations=['No raw acquisition/join/census tape, actor schedule or complete initial market state',
                    'Does not reproduce full large-state residency, native preparation, owner queue contention or Pons workload',
                    'One sequential pair, no statistical confidence or matched OS-cache claim',
                    'Outer totals include scratch checks; store_transaction and containment_guard are measured separately',
                    'Measured pair adds per-API timing and VM instrumentation; plain pair has neither',
                    'No whole-system throughput, evidence-readiness, strategy-eligibility or held-protection proof'])
            args.output.write_text(json.dumps(result, sort_keys=True, indent=2)+'\n')
            os.chmod(args.output, 0o600)
            scratch.success = True
        print(json.dumps(dict(status=result['status'], output=str(args.output),
            elapsed_seconds=result['elapsed_seconds'], variants=[{k: r[k] for k in
            ('variant', 'measured', 'records', 'store_transaction_wall_seconds',
             'store_transaction_cpu_seconds', 'containment_guard_cpu_seconds')} for r in results])))
    finally:
        signal.alarm(0)


if __name__ == '__main__':
    main()
