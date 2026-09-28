"""Provider-free bounded-progress proof using production PriorityOwner and SQLite.

This proves cleanup-admission bounds, not wall-clock pressure throughput.
"""
from __future__ import annotations
import argparse
from collections import Counter
from dataclasses import replace
import gzip
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile

SCOPES = ('program:meteora', 'program:pump', 'program:pumpswap')
SLICE = 256
ADMISSION_BOUND = 2 * len(SCOPES)
SEED_PER_SCOPE = 4096
TURNS_PER_EPOCH = 12
EPOCHS = 2


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--expect-starvation', action='store_true')
    args = parser.parse_args()
    root = Path(args.source).resolve()
    destination = Path(args.output).resolve()
    os.chdir(root)
    sys.path.insert(0, str(root))
    from meme_machine.solana_evidence_control import PriorityOwner
    from meme_machine.solana_evidence_plane import EvidenceUnavailable, digest, decode_body
    from meme_machine.solana_evidence_service import ServiceState
    from meme_machine.solana_provider_config import AlchemyEndpoint
    from tests.test_run381_retention_progress import record
    config = AlchemyEndpoint.parse('https://solana-mainnet.g.alchemy.com/v2/offline-test')
    template = record()
    reports = []
    failures = []
    modes = ('source',) if args.expect_starvation else ('source', 'urgent', 'mixed')
    for mode in modes:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'evidence.db'
            initial_hashes = {}
            expected_hot = {}
            phases = []
            source_receipts = []
            total_removed = Counter()
            integrity_checks = []

            def factory():
                state = ServiceState(path, config)
                if not initial_hashes:
                    for scope in SCOPES:
                        rows = [replace(template, scope=scope,
                            identity=f'{scope}:old:{i:05d}', signature=f'{scope}:old-signature:{i:05d}',
                            slot=i+1, market_time=10,
                            addresses=tuple(f'{scope}:address:{j}' for j in range(8)))
                            for i in range(SEED_PER_SCOPE)]
                        initial_hashes.update((r.identity, digest(r.body())) for r in rows)
                        for offset in range(0, len(rows), 1000):
                            state.writer.ingest(rows[offset:offset+1000])
                        anchors = [replace(template, scope=scope,
                            identity=f'{scope}:pinned:{i}', signature=f'{scope}:pinned-signature:{i}',
                            slot=10000+i, market_time=10) for i in range(2)]
                        state.writer.ingest(anchors)
                        expected_hot.update((r.identity, r.body()) for r in anchors)
                        state.writer.interest(f'proof:{scope}', scope, lower_slot=10000,
                                              priority=0, lifecycle='open')
                        state.writer.gap(scope, 10001, 10001, 'proof_unresolved_gap')
                    while state.writer.archive(900, max_records=1000):
                        pass
                    counts = dict(state.writer.db.execute(
                        'SELECT scope,COUNT(*) FROM records WHERE body IS NULL GROUP BY scope'))
                    assert counts == {s: SEED_PER_SCOPE for s in SCOPES}, counts
                return state

            def snapshot(state):
                counts = dict(state.writer.db.execute(
                    'SELECT scope,COUNT(*) FROM records WHERE body IS NULL GROUP BY scope'))
                return {s: counts.get(s, 0) for s in SCOPES}

            for epoch in range(EPOCHS):
                owner = PriorityOwner(factory)
                owner.ready.result(90)
                visits = []
                rows_by_turn = []
                max_gap = {}
                try:
                    before = owner.submit(snapshot, priority=0).result(10)
                    for turn in range(TURNS_PER_EPOCH):
                        sequence = epoch*TURNS_PER_EPOCH+turn
                        priority = 2 if mode=='source' else 0 if mode=='urgent' else (2,2,0,2,1,2)[turn%6]
                        fresh = [replace(template, scope=s,
                            identity=f'{s}:fresh:{sequence}', signature=f'{s}:fresh-signature:{sequence}',
                            slot=11000+sequence, market_time=1000, observed_at=1000) for s in SCOPES]
                        expected_hot.update((r.identity, r.body()) for r in fresh)
                        admitted = []

                        def source_work(state, fresh=tuple(fresh)):
                            with state.writer.transaction():
                                state.writer.ingest(fresh)
                                state.writer._count('proof_source_commits')
                            return len(fresh)

                        def compact(state):
                            def on_statement(sql):
                                if not admitted and sql.startswith('DELETE FROM lineage'):
                                    admitted.append(owner.submit(source_work, priority=priority))
                            state.writer.db.set_trace_callback(on_statement)
                            try:
                                state.writer.retain(900, max_records=1000, archive_first=False, checkpoint=False)
                            finally:
                                state.writer.db.set_trace_callback(None)

                        task = owner.submit(compact, priority=4)
                        yielded = False
                        try:
                            task.result(15)
                        except EvidenceUnavailable as exc:
                            if str(exc)!='evidence_background_yield':
                                raise
                            yielded = True
                        assert yielded and len(admitted)==1, 'source_arrival_not_exercised'
                        source_receipts.append(admitted[0].result(15))
                        after = owner.submit(snapshot, priority=0).result(15)
                        delta = {s: before[s]-after[s] for s in SCOPES}
                        assert all(n>=0 for n in delta.values()), delta
                        assert sum(delta.values())==SLICE, ('durable_slice_changed', delta)
                        visited = [s for s,n in delta.items() if n]
                        assert len(visited)==1, ('slice_crossed_scope_boundary', delta)
                        visits.extend(visited)
                        rows_by_turn.append(delta)
                        total_removed.update(delta)
                        before = after
                    violations = []
                    for start in range(len(visits)-ADMISSION_BOUND+1):
                        missing = sorted(set(SCOPES)-set(visits[start:start+ADMISSION_BOUND]))
                        if missing:
                            violations.append({'window_start': start+1, 'missing': missing})
                    for scope in SCOPES:
                        positions = [i+1 for i,s in enumerate(visits) if s==scope]
                        boundaries = [0,*positions,len(visits)+1]
                        max_gap[scope] = max(b-a for a,b in zip(boundaries,boundaries[1:]))
                    if violations:
                        failures.append({'mode': mode, 'epoch': epoch,
                                         'failure': 'scope_starvation', 'windows': violations})
                    phases.append({'epoch': epoch, 'visits': visits,
                        'compacted_by_scope': {s:sum(d[s] for d in rows_by_turn) for s in SCOPES},
                        'max_progress_gap_admissions': max_gap, 'violations': violations})
                    integrity_checks.append(owner.submit(
                        lambda s:s.writer.db.execute('PRAGMA integrity_check').fetchone()[0],
                        priority=0).result(15))
                finally:
                    owner.close()
            archived_hashes = {}
            for archive in path.parent.glob('*.archive/*.gz'):
                assert hashlib.sha256(archive.read_bytes()).hexdigest()==archive.name.split('.')[0]
                with gzip.open(archive,'rt') as stream:
                    for line in stream:
                        row = json.loads(line)
                        assert digest(row['body'])==row['hash'] and row['lineage']
                        archived_hashes[row['identity']] = row['hash']
            assert archived_hashes==initial_hashes, 'archive_identity_or_content_changed'
            with sqlite3.connect(path) as db:
                assert db.execute('PRAGMA integrity_check').fetchone()==('ok',)
                assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
                assert db.execute('PRAGMA synchronous').fetchone()[0]==2
                assert db.execute("SELECT value FROM counters WHERE key='proof_source_commits'").fetchone()[0]==EPOCHS*TURNS_PER_EPOCH
                actual_hot = {identity:decode_body(raw,db) for identity,raw in db.execute(
                    'SELECT identity,body FROM records WHERE body IS NOT NULL')}
                assert actual_hot==expected_hot, 'pinned_or_fresh_evidence_changed'
                assert db.execute('SELECT COUNT(*) FROM interests WHERE active=1').fetchone()[0]==len(SCOPES)
                assert db.execute("SELECT COUNT(*) FROM gaps WHERE reason='proof_unresolved_gap' AND repaired IS NULL").fetchone()[0]==len(SCOPES)
                assert db.execute("SELECT value FROM counters WHERE key='restarts'").fetchone()[0]>=1
                assert not db.execute('SELECT 1 FROM address_refs a LEFT JOIN records r ON r.rowid=a.record_id WHERE r.rowid IS NULL LIMIT 1').fetchone()
                remaining = dict(db.execute('SELECT scope,COUNT(*) FROM records WHERE body IS NULL GROUP BY scope'))
                assert sum(remaining.values())+sum(total_removed.values())==len(initial_hashes)
            reports.append({'mode':mode, 'epochs':phases, 'compacted_by_scope':dict(total_removed),
                'source_commit_count':len(source_receipts), 'source_rows_preserved':sum(source_receipts),
                'archive_records_verified':len(archived_hashes), 'remaining_archived_rows_by_scope':remaining,
                'pinned_and_fresh_rows_verified':len(actual_hot), 'database_integrity':integrity_checks,
                'restart_verified':True})
    result = {'schema':'stagee19-production-sqlite-bounded-scope-proof-v1',
        'source_sha':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        'proof_scope':'bounded eligible cleanup admissions, not wall-clock pressure certification',
        'scopes':SCOPES, 'per_transaction_records':SLICE, 'progress_bound_cleanup_admissions':ADMISSION_BOUND,
        'provider_calls':0, 'passed':not failures, 'failures':failures,
        'expected_baseline_starvation':args.expect_starvation, 'cases':reports}
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print(json.dumps(result,sort_keys=True),flush=True)
    if args.expect_starvation:
        assert failures and all(f['failure']=='scope_starvation' for f in failures), 'baseline_did_not_reproduce'
        return 0
    return 1 if failures else 0

if __name__=='__main__':
    raise SystemExit(main())
