"""Bounded offline costs of exact native Pons reporting/storage queries.

Uses production Plane/Pipeline/accounting functions on clearly synthetic SQLite
state under admitted engineering Scratch. No providers, portfolios, callbacks or
financial authority are attached. Synthetic measurements do not establish the
population or frequency of an AWS failure; match those separately to receipts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import resource
import sqlite3
import subprocess
import time

from meme_machine.operational.artifact_storage import Scratch
from meme_machine.operational.offline import install_network_guard
from meme_machine.runtime.robinhood.plane import Plane, canonical
from meme_machine.runtime.robinhood.accounting import high_water, project
from meme_machine.runtime.robinhood.pons import save_cohort_checkpoint
from meme_machine.lanes.pons.pipeline import Pipeline


FIRST = ('SELECT t.* FROM transitions t JOIN candidates c ON c.id=t.candidate '
         'WHERE c.lane=? ORDER BY t.seq LIMIT 1')
KINDS = ('discovered', 'watching', 'canonical_evidence_requested',
         'canonical_evidence_complete', 'superseded', 'strategy_rejected')


def io():
    return {key: int(value) for key, value in
            (line.split(':', 1) for line in Path('/proc/self/io').read_text().splitlines())}


def measure(label, call, repeat, *, db=None):
    steps = 0
    statements = 0
    until = time.monotonic() + 15
    def progress():
        nonlocal steps
        steps += 1000
        return int(time.monotonic() > until)
    def trace(_):
        nonlocal statements
        statements += 1
    if db is not None:
        db.set_progress_handler(progress, 1000)
        db.set_trace_callback(trace)
    before = io()
    cpu = time.thread_time()
    clock = time.monotonic()
    try:
        for _ in range(repeat):
            call()
    finally:
        elapsed = time.monotonic() - clock
        used_cpu = time.thread_time() - cpu
        after = io()
        if db is not None:
            db.set_progress_handler(None, 0)
            db.set_trace_callback(None)
    return dict(operation=label, repeat=repeat, seconds=elapsed,
                thread_cpu_seconds=used_cpu, seconds_each=elapsed/repeat,
                sqlite_vm_steps_approx=steps if db is not None else None,
                statements=statements if db is not None else None,
                process_io_delta={key: after[key]-before[key] for key in before},
                max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


def fixture(path, candidates, transitions, payload_bytes, evidence_records, *, orphan_prefix=0, analyze=False):
    plane = Plane(path)
    padding = 'x' * payload_bytes
    with plane.transaction():
        plane.db.executemany('''INSERT INTO candidates(
            id,lane,generation,interpretation,latest_id,observed,ordering,desired,
            payload,state,pending,priority,rank,deadline,queued)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            ((f'pons:synthetic:{index:08d}', 'pons', 1, '{}', str(index), 1000,
              canonical([index,0,0]), '{}', canonical(dict(synthetic=True,padding=padding)),
              'watching', 1, 4, 0, 1005, 1000) for index in range(candidates)))
        plane.db.executemany('INSERT INTO transitions VALUES(?,?,?,?,?,?,?,?,?)',
            ((index+1, f'retired:synthetic:{index:08d}' if index < orphan_prefix else
              f'pons:synthetic:{index % candidates:08d}', 1, 1000+index,
              KINDS[index % len(KINDS)], 'obsolete_completion' if index % 101 == 0 else None,
              '{}', '{}', canonical(dict(synthetic=True,padding=padding)))
             for index in range(transitions)))
        plane.db.executemany('INSERT INTO observations VALUES(?,?,?,?)',
            ((f'pons:synthetic:{index % candidates:08d}', str(index),
              canonical(dict(synthetic=True,padding=padding)), 1000)
             for index in range(transitions)))
        plane.db.executemany('INSERT INTO evidence VALUES(?,?,?,?,?)',
            (('pons:synthetic-cost', str(index),
              canonical(dict(synthetic=True,padding=padding)),
              canonical(dict(authority='SYNTHETIC_OFFLINE_FIXTURE')), 1000)
             for index in range(evidence_records)))
        plane.db.execute("INSERT INTO observation_counts VALUES('pons',?)", (transitions,))
    if analyze:
        plane.db.execute('ANALYZE')
    return plane


def run(args):
    install_network_guard()
    source = subprocess.check_output(['git','rev-parse','HEAD'], text=True).strip()
    tree = subprocess.check_output(['git','rev-parse','HEAD^{tree}'], text=True).strip()
    accounting = Path(__file__).resolve().parents[2] / 'meme_machine/runtime/robinhood/accounting.py'
    with Scratch() as scratch:
        path = scratch.path / 'candidate.sqlite'
        plane = fixture(path, args.candidates, args.transitions, args.payload_bytes,
                        args.evidence_records, orphan_prefix=args.orphan_prefix,
                        analyze=args.analyze)
        pipeline = Pipeline(scratch.path / 'pipeline.sqlite', 'pons', 'synthetic-offline-policy')
        try:
            # Populate real native reporting receipts once before measuring the
            # unchanged idle path. Setup durability is immaterial to this fully
            # disposable fixture; restore SQLite FULL before measured calls.
            pipeline.db.execute('PRAGMA synchronous=OFF')
            through = high_water(plane)
            while project(plane, pipeline, through=through) == 256:
                scratch.check()
            pipeline.db.execute('PRAGMA synchronous=FULL')
            source_id = plane.checkpoint_read('projection_source:pons')
            plans = dict(first=[list(row) for row in plane.db.execute(
                'EXPLAIN QUERY PLAN '+FIRST, ('pons',))],
                transition_aggregate=[list(row) for row in plane.db.execute(
                    'EXPLAIN QUERY PLAN SELECT kind,COUNT(*) n FROM transitions '
                    'WHERE candidate IN (SELECT id FROM candidates WHERE lane=?) GROUP BY kind',
                    ('pons',))])
            results = []
            # Warm the actual connection, then retain kernel read counters and
            # approximate VM steps. rchar is logical read traffic, not disk I/O.
            for label, call in (
                ('first_transition_join', lambda: plane.db.execute(FIRST, ('pons',)).fetchone()),
                ('checkpoint_read', lambda: plane.checkpoint_read('projection_source:pons')),
                ('unchanged_checkpoint_transaction', lambda: plane.checkpoint('projection_source:pons', source_id)),
                ('native_accounting_project_idle', lambda: project(plane,pipeline,through=through)),
                ('native_plane_snapshot', lambda: plane.snapshot('pons')),
            ):
                call()
                scratch.check()
                results.append(measure(label, call, args.repeat, db=plane.db))
            def open_close():
                reopened = Plane(path)
                reopened.close()
            result = dict(candidate_plane_path=str(path), rows=[], qualifiers=[],
                          lifecycles=[], discovery_sessions=[], sequencer_recoveries=[])
            for label, call in (
                ('native_plane_open_close_quick_check', open_close),
                ('native_save_cohort_checkpoint', lambda: save_cohort_checkpoint(result, 1000, 'offline_cost')),
            ):
                scratch.check()
                results.append(measure(label, call, min(args.repeat, 8)))
            output = dict(schema='pons-native-query-cost-offline-v1',
                source_commit=source, source_tree=tree, sqlite_version=sqlite3.sqlite_version,
                accounting_source_sha256=hashlib.sha256(accounting.read_bytes()).hexdigest(),
                fixture=dict(candidates=args.candidates,transitions=args.transitions,
                    observations=args.transitions,evidence_records=args.evidence_records,
                    orphan_transition_prefix=args.orphan_prefix,
                    padding_bytes=args.payload_bytes,analyzed=args.analyze,
                    database_bytes=path.stat().st_size,
                    wal_bytes=Path(str(path)+'-wal').stat().st_size if Path(str(path)+'-wal').exists() else 0),
                query_plans=plans, measurements=results, financial_authority=False,
                production_population_measured=False, production_cause_proven=False)
            print(json.dumps(output, sort_keys=True, indent=2))
            scratch.success = True
            return output
        finally:
            pipeline.close()
            plane.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidates',type=int,default=256)
    parser.add_argument('--transitions',type=int,default=8192)
    parser.add_argument('--evidence-records',type=int,default=1024)
    parser.add_argument('--orphan-prefix',type=int,default=0)
    parser.add_argument('--payload-bytes',type=int,default=768)
    parser.add_argument('--repeat',type=int,default=8)
    parser.add_argument('--analyze',action='store_true')
    args = parser.parse_args()
    if not (1<=args.candidates<=4096 and args.candidates<=args.transitions<=65536 and
            0<=args.evidence_records<=8192 and 0<=args.payload_bytes<=4096 and
            0<=args.orphan_prefix<args.transitions and
            1<=args.repeat<=256):
        parser.error('bounded synthetic fixture parameters required')
    run(args)


if __name__ == '__main__':
    main()
