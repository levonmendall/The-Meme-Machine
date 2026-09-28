"""Execute the exact old and new production snapshot methods on the same SQLite.

Only aggregate statement/VM counts, output hashes and timings are retained. The
old method is read from its exact reviewed Git object, not reimplemented here.
"""
import argparse
import ast
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import textwrap
import time
import types
from meme_machine import solana_evidence_plane as plane
from tests.test_run381_retention_progress import record, proof

BASE = '23f06ed84e5b5e2d4efd074618ab44ae7ed58011'


def baseline_method():
    source = subprocess.check_output(['git', 'show', BASE+':meme_machine/solana_evidence_plane.py'], text=True)
    cls = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef) and n.name == 'EvidenceWriter')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'archive_snapshot')
    text = textwrap.dedent('\n'.join(source.splitlines()[method.lineno-1:method.end_lineno]))
    namespace = dict(vars(plane)); exec(compile(text, BASE+':archive_snapshot', 'exec'), namespace)
    return namespace['archive_snapshot']


def measure(writer, operation):
    metrics = dict(statements=0, select_statements=0, vm_steps_approx=0)
    def statement(sql):
        metrics['statements'] += 1
        if sql.startswith(('SELECT', 'WITH')):
            metrics['select_statements'] += 1
    def progress():
        metrics['vm_steps_approx'] += 1000
        return 0
    writer.db.set_trace_callback(statement); writer.db.set_progress_handler(progress, 1000)
    started = time.perf_counter()
    try:
        value = operation()
    finally:
        metrics['wall_seconds'] = time.perf_counter()-started
        writer.db.set_trace_callback(None); writer.db.set_progress_handler(None, 0)
    return value, metrics


def run(output):
    old = baseline_method(); comparisons = []
    with tempfile.TemporaryDirectory() as td:
        writer = plane.EvidenceWriter(Path(td)/'db', clock=lambda:1000)
        try:
            rows = [replace(record(), identity='probe:%04d'%i, signature='s:%04d'%i,
                            slot=10+i//128, market_time=10+i//128,
                            payload=dict(event=dict(index=i, amount=i+1),
                                         raw_lineage=dict(logs=['shared authenticated log '*128], err=None)))
                    for i in range(1000)]
            writer.ingest(rows, proof=proof(10, 20))
            pinned = replace(record(), identity='pin', signature='pin', slot=100)
            gap = replace(record(), identity='gap', signature='gap', slot=50)
            writer.ingest([pinned, gap]); writer.interest('position', 'pump', lower_slot=100, priority=0, lifecycle='open')
            writer.gap('pump', 50, 50)
            for max_records, max_bytes in ((1000, 4*1024*1024), (64, 4096), (1, 100)):
                before, old_metrics = measure(writer, lambda:old(writer, 1000, max_records=max_records, max_bytes=max_bytes))
                after, new_metrics = measure(writer, lambda:writer.archive_snapshot(1000, max_records=max_records, max_bytes=max_bytes))
                if before != after:
                    raise AssertionError('archive_snapshot_not_byte_equivalent')
                if any(r['identity'] in ('pin', 'gap') for r in after['rows']):
                    raise AssertionError('archive_snapshot_lost_pin')
                old_plan = writer.prepare_archive(before, max_bytes=16*1024*1024)
                new_plan = writer.prepare_archive(after, max_bytes=16*1024*1024)
                original_bytes = '\n'.join(plane.canonical(row) for row in old_plan).encode()
                repaired_bytes = '\n'.join(plane.canonical(row) for row in new_plan).encode()
                if original_bytes != repaired_bytes:
                    raise AssertionError('archive_output_bytes_changed')
                comparisons.append(dict(max_records=max_records, max_bytes=max_bytes,
                    rows=len(after['rows']), encoded_bytes=after['encoded_bytes'],
                    archive_sha256=hashlib.sha256(repaired_bytes).hexdigest(),
                    old=old_metrics, repaired=new_metrics))
            largest = comparisons[0]
            if largest['rows'] != 1000:
                raise AssertionError('archive_probe_did_not_exercise_full_snapshot')
            if not (largest['old']['select_statements'] >= 4001
                    and largest['repaired']['select_statements'] <= 50):
                raise AssertionError('archive_set_read_bound_not_met')
            integrity = writer.db.execute('PRAGMA integrity_check').fetchone()[0]
            if integrity != 'ok':
                raise AssertionError('archive_probe_integrity')
        finally:
            writer.close()
    result = dict(passed=True, baseline=BASE, integration_sha=subprocess.check_output(
        ['git','rev-parse','HEAD'],text=True).strip(), comparisons=comparisons,
        integrity=integrity, provider_calls=0, paper_only=True)
    path=Path(output);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True)
    run(parser.parse_args().output)
