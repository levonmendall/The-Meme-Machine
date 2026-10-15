"""One bounded, offline real-caller audit-index discriminator.

This is not a market replay or a whole-machine throughput benchmark. The two
disposable fixtures use current Admission/transport/accounting and the existing
mock HTTP fixture. Only variant B gains three narrow seq indexes. Seed bodies
are copies of a real four-element *offline* audit, never production records.
"""
import argparse
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import sqlite3
import time
from unittest.mock import patch

TABLES = ('transport_starts', 'admissions', 'transports')


def io_counts():
    return {key: int(value) for key, value in
            (line.split(':', 1) for line in Path('/proc/self/io').read_text().splitlines())}


def rows_digest(rows):
    return hashlib.sha256(json.dumps(rows, separators=(',', ':')).encode()).hexdigest()


def scenario(scratch, indexed):
    from tests.test_provider_usage_wal_race import ProviderDemandCallerTests
    fixture = ProviderDemandCallerTests()
    fixture.setUp()
    try:
        context = fixture.context('current')
        fixture.batch(context, 'current', [
            ('eth_getBlockByHash', ['0xseed'+str(n), False]) for n in range(4)])
        db = sqlite3.connect(fixture.path)
        bodies = {table: db.execute('SELECT body FROM '+table+' ORDER BY seq DESC LIMIT 1').fetchone()[0]
                  for table in TABLES}
        with db:
            for table in TABLES:
                trigger = db.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name=? AND sql LIKE '%BEFORE DELETE%'", (table,)).fetchone()
                assert trigger
                db.execute('DROP TRIGGER '+trigger[0])
                db.execute('DELETE FROM '+table)
                db.executemany('INSERT INTO '+table+'(seq,body) VALUES(?,?)',
                               [(n, bodies[table]) for n in range(1, 4097)])
                db.execute(trigger[1])
                if indexed:
                    db.execute('CREATE INDEX probe_'+table+'_seq ON '+table+'(seq)')
        plans = {table: {name: db.execute('EXPLAIN QUERY PLAN '+sql).fetchall()
                 for name, sql in dict(count='SELECT COUNT(*) FROM '+table,
                    boundary='SELECT seq FROM '+table+' WHERE 1=1 ORDER BY seq DESC LIMIT 1 OFFSET 4095').items()}
                 for table in TABLES}
        initial = {table: db.execute('SELECT seq,body FROM '+table+' ORDER BY seq').fetchall()
                   for table in TABLES}
        usage_before = dict(db.execute('SELECT metric,SUM(value) FROM provider_usage GROUP BY metric'))
        db.close()
        initial_bytes = sum(p.stat().st_size for p in Path(fixture.temp.name).iterdir() if p.is_file())
        appended = {table: [] for table in TABLES}
        operations = Counter()
        ticks = [0]
        enabled = [True]
        original_connect = sqlite3.connect

        class Measured(sqlite3.Connection):
            def execute(self, sql, *args, **kwargs):
                if enabled[0]:
                    # Only fixed operation labels; no bindings/expanded SQL.
                    verb = sql.lstrip().split(None, 1)[0].upper()
                    operations[verb] += 1
                    for table in TABLES:
                        if sql.startswith('SELECT '+ 'seq FROM '+table+' WHERE 1=1 ORDER BY seq DESC LIMIT 1 OFFSET'):
                            operations['audit_boundary:'+table] += 1
                return super().execute(sql, *args, **kwargs)

        def opened(*args, **kwargs):
            kwargs.setdefault('factory', Measured)
            value = original_connect(*args, **kwargs)
            def progress():
                if enabled[0]: ticks[0] += 1000
                return 0
            value.set_progress_handler(progress, 1000)
            return value

        original_http = fixture.http
        prior_wire = len(fixture.requests)
        http_sequences = []

        def http(request, **kwargs):
            # Exact new initiated attempt is durable before the mocked wire.
            with original_connect(fixture.path) as reader:
                seq, body = reader.execute('SELECT seq,body FROM transport_starts ORDER BY seq DESC LIMIT 1').fetchone()
                payload = json.loads(request.data)
                assert seq == 4097 + len(http_sequences)
                assert json.loads(body)['methods'] == [r['method'] for r in payload]
                http_sequences.append(seq)
            return original_http(request, **kwargs)

        scratch.check()
        before_io, before_wall, before_cpu = io_counts(), time.perf_counter(), time.process_time()
        with patch.object(sqlite3, 'connect', opened), patch('meme_machine.lanes.pons.provider.urlopen', side_effect=http):
            for batch in range(32):
                calls = [('eth_getBlockByHash', ['0xmeasure'+str(batch)+'_'+str(n), False]) for n in range(4)]
                values = fixture.batch(context, 'current', calls)
                assert [value['hash'] for value in values] == [call[1][0] for call in calls]
                # Same verification work in both variants; excluded from SQL
                # counters, included in wall/CPU/I/O with explicit scope.
                with original_connect(fixture.path) as reader:
                    for table in TABLES:
                        appended[table].append(reader.execute('SELECT seq,body FROM '+table+' ORDER BY seq DESC LIMIT 1').fetchone())
                scratch.check()
        cpu, wall, after_io = time.process_time()-before_cpu, time.perf_counter()-before_wall, io_counts()
        enabled[0] = False
        assert len(fixture.requests)-prior_wire == len(http_sequences) == 32
        db = original_connect(fixture.path)
        try:
            retained = {}
            for table in TABLES:
                rows = db.execute('SELECT seq,body FROM '+table+' ORDER BY seq').fetchall()
                expected = (initial[table]+appended[table])[-4096:]
                assert rows == expected
                retained[table] = dict(count=len(rows), minimum_seq=rows[0][0], maximum_seq=rows[-1][0],
                                       digest=rows_digest(rows), oracle_equal=True)
                try:
                    db.execute('DELETE FROM '+table+' WHERE seq=?', (rows[0][0],))
                except sqlite3.IntegrityError as error:
                    assert str(error) == 'append_only'
                else:
                    raise AssertionError('append_only_guard_lost')
                db.rollback()
            usage_after = dict(db.execute('SELECT metric,SUM(value) FROM provider_usage GROUP BY metric'))
            delta = {key: value-usage_before.get(key, 0) for key, value in usage_after.items()
                     if value != usage_before.get(key, 0)}
            assert delta['physical_http_requests'] == 32
            assert delta['logical_rpc_calls'] == 128
            assert delta['completed_transport_attempts'] == 32
            pages, page_size = db.execute('PRAGMA page_count').fetchone()[0], db.execute('PRAGMA page_size').fetchone()[0]
        finally:
            db.close()
        return dict(variant='seq_indexes' if indexed else 'current', wall_seconds=wall, cpu_seconds=cpu,
                    io_delta={key: after_io[key]-before_io[key] for key in after_io},
                    measured_connect_execute_counts=dict(operations), vm_steps_quantized_lower_bound=ticks[0],
                    query_plans=plans, mock_transports=32, logical_elements=128,
                    before_http_initiated_attempt_verified=True, retained=retained,
                    usage_delta=delta, seed_body_bytes={key: len(body.encode()) for key, body in bodies.items()},
                    initial_fixture_file_bytes=initial_bytes, final_ledger_main_pages_bytes=pages*page_size)
    finally:
        fixture.doCleanups()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    from operational.tests import network_guard
    from meme_machine.operational.artifact_storage import Policy, Scratch
    network_guard()
    def deadline(*_): raise TimeoutError('offline_pair_absolute_90_second_limit')
    signal.signal(signal.SIGALRM, deadline)
    signal.alarm(90)
    started = time.monotonic()
    try:
        policy = replace(Policy.environment(), scratch_max_bytes=256*1024**2)
        with Scratch(policy=policy) as scratch:
            variants = [scenario(scratch, indexed) for indexed in (False, True)]
            assert variants[0]['usage_delta'] == variants[1]['usage_delta']
            result = dict(status='OFFLINE_ACCOUNTING_PAIR_COMPLETE', at=datetime.now(timezone.utc).isoformat(),
                base_source='76a48e67fcb2ef53a2cb82e3c8d5db7d2812b2ee',
                driver_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                elapsed_seconds=time.monotonic()-started, variants=variants,
                limits=dict(wall_seconds=90, fixture_bytes=256*1024**2, measured_mock_transports_per_variant=32),
                scope='Synthetic saturated audit rings and real caller/mock HTTP/accounting; not full-system throughput',
                seeds='Copies of real offline four-element audit rows, not authentic market replay or a production copy',
                timing='Includes identical per-request correctness/scratch checks; SQL counts cover measured new connections only',
                provider_calls=0, authoritative_writes=0)
            args.output.write_text(json.dumps(result, sort_keys=True, indent=2)+'\n')
            os.chmod(args.output, 0o600)
            scratch.success = True
        print(json.dumps(dict(status=result['status'], output=str(args.output),
                              elapsed_seconds=result['elapsed_seconds'],
                              variants=[{k: v[k] for k in ('variant','wall_seconds','cpu_seconds','io_delta')}
                                        for v in variants])))
    finally:
        signal.alarm(0)


if __name__ == '__main__':
    main()
