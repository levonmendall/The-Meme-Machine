"""Bounded exact-native idle-loop discriminator on synthetic disposable state.

Population counts resemble a retained receipt; bodies, lane placement, result
distribution and peer-write frequency are explicitly synthetic, not AWS facts.
No providers, books, financial databases, historical ACKs or readiness authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

from engineering.diagnostics.pons_query_cost import fixture
from engineering.diagnostics.pons_maintenance_cost import observe
from meme_machine.operational.artifact_storage import Scratch
from meme_machine.operational.offline import install_network_guard
from meme_machine.runtime.robinhood.accounting import high_water, project
from meme_machine.runtime.robinhood.plane import Plane, canonical
from meme_machine.runtime.robinhood.pons import Broker
from meme_machine.runtime.operating_families import active_sql
from meme_machine.lanes.pons.pipeline import Pipeline
from meme_machine.lanes.pons.pons_attempts import Attempts
from meme_machine.lanes.pons.pons_natural_observation import MarketScout


DOMAIN = 'pons:shared:synthetic-empty-loop'


def logical_state(plane, pipeline):
    tables = {}
    for table in ('candidates', 'transitions', 'observations', 'result_consumption',
                  'pons_current_watch'):
        tables[table] = [list(row) for row in plane.db.execute(
            'SELECT * FROM ' + table + ' ORDER BY rowid')]
    tables['progress_sources'] = [list(row) for row in pipeline.db.execute(
        'SELECT * FROM progress_sources ORDER BY source,sequence')]
    # Original projection timestamps are process clocks, not economic content.
    tables['progress'] = [list(row) for row in pipeline.db.execute(
        'SELECT lane,policy_hash,candidate,stage,reason,classification,details '
        'FROM progress ORDER BY sequence')]
    return hashlib.sha256(canonical(tables).encode()).hexdigest()


def all_native_tables(plane):
    tables = {}
    for (name,) in plane.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
        tables[name] = sorted((list(row) for row in plane.db.execute('SELECT * FROM ' + name)), key=repr)
    return hashlib.sha256(canonical(tables).encode()).hexdigest()


def run(output, *, repeat=16, padding=768, covering=False):
    if sys.version_info[:3] != (3, 12, 14):
        raise ValueError('benchmark_pinned_python_required')
    install_network_guard()
    os.environ['MM_OPERATIONAL_PHASE'] = 'OFFLINE_COST'
    os.environ['MM_MODE'] = 'PAPER'
    # A benchmark never inherits a configured provider or cache capability.
    for key in ('MM_PROVIDER_DB', 'MM_ROBINHOOD_READ_RPC_URL', 'MM_RPC_CACHE_DB'):
        os.environ.pop(key, None)
    output = Path(output).resolve()
    source = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    with Scratch() as scratch:
        def audit(event, args):
            if event == 'sqlite3.connect':
                value = os.fsdecode(args[0]).removeprefix('file:').split('?', 1)[0]
                if not Path(value).resolve().is_relative_to(scratch.path):
                    raise RuntimeError('benchmark_foreign_database_forbidden')
            if event == 'open' and not isinstance(args[0], int) and args[2] & (
                    os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC):
                path = Path(os.fsdecode(args[0])).resolve()
                if path != output and not path.is_relative_to(scratch.path):
                    raise RuntimeError('benchmark_foreign_write_forbidden')
        sys.addaudithook(audit)
        path = scratch.path / 'plane.sqlite'
        now = [1001.]
        broker = Broker(path, 'synthetic-offline-policy', clock=lambda: now[0])
        plane = broker.plane
        populated = fixture(path, 1169, 4096, padding, 4096)
        populated.close()
        with plane.transaction():
            # Quiescent acknowledged candidates, preserving the wide rows which
            # every real empty claim/outbox probe must correctly exclude.
            plane.db.execute('UPDATE candidates SET pending=0,interpretation=?,completed=desired,result=?',
                (canonical(broker.policy), canonical(dict(synthetic=True, padding='r' * padding))))
            plane.db.execute('INSERT INTO result_consumption SELECT id,generation,1001 FROM candidates')
            plane.db.execute('INSERT INTO pons_current_watch SELECT id,?, ?,1e100,0 FROM candidates',
                (canonical(dict(synthetic=True)), 'synthetic-unused-watch'))
        if covering:
            plane.db.executescript('''
                CREATE INDEX diagnostic_candidate_claimed ON candidates(lane,claim_until) WHERE claim IS NOT NULL;
                CREATE INDEX diagnostic_candidate_delivery ON candidates(lane,priority,deadline,id,generation)
                    WHERE result IS NOT NULL AND completed=desired;
                CREATE INDEX diagnostic_candidate_generation ON candidates(id,generation);
                CREATE INDEX diagnostic_watch_due ON pons_current_watch(next_at,attempt,candidate);
            ''')
        pipeline = Pipeline(scratch.path / 'pipeline.sqlite', 'pons', 'synthetic-offline-policy')
        peer = Plane(path, clock=lambda: now[0])
        attempts = Attempts(plane)
        try:
            while project(plane, pipeline, through=high_water(plane)) == 256:
                scratch.check()
            plane.maintain(); attempts.maintain(now[0]); pipeline.snapshot()
            before = logical_state(plane, pipeline)
            result = dict(schema='pons-empty-loop-cost-v1', source_commit=source,
                benchmark_generation_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                variant='diagnostic_covering' if covering else 'exact_source_schema',
                runtime_source_sha256={name: hashlib.sha256(Path(name).read_bytes()).hexdigest()
                    for name in ('meme_machine/runtime/robinhood/plane.py',
                                 'meme_machine/runtime/robinhood/pons.py')},
                sqlite=sqlite3.sqlite_version, python=sys.version,
                fixture=dict(candidates=1169, observations=4096, transitions=4096,
                    evidence=4096, acknowledged_results=1169, payload_bytes=padding,
                    watch_due=False, analyzed=False, orphan_transitions=0),
                installed_indexes=[row[0] for row in plane.db.execute(
                    "SELECT name FROM sqlite_master WHERE type='index' ORDER BY name")],
                source_claim='EXACT_NATIVE_METHODS_SYNTHETIC_POPULATION_AND_CADENCE',
                production_cause_proven=False, provider_requests=0, financial_authority=False,
                vm_scope='Approximate steps assigned to latest statement per connection; '
                    'prepare peer writes excluded from reader cost.', measurements=[])
            def coverage():
                broker.report_to(pipeline)
                attempts.maintain(now[0])
                pipeline.snapshot()
            def empty_turn():
                coverage()
                if next(broker.committed(), None) is not None or broker.pop(now=now[0]) is not None:
                    raise ValueError('benchmark_expected_genuinely_empty_native_work')
            obsolete = ('DELETE FROM result_consumption WHERE candidate NOT IN '
                '(SELECT id FROM candidates WHERE NOT (' + active_sql('lane') + ')) '
                'AND NOT EXISTS(SELECT 1 FROM candidates c '
                'WHERE c.id=result_consumption.candidate AND c.generation=result_consumption.generation)')
            def consumption_maintenance():
                with plane.transaction():
                    plane.db.execute(obsolete)
            operations = (
                ('coverage', coverage), ('empty_current_turn', empty_turn),
                ('project', lambda: project(plane, pipeline, through=high_water(plane))),
                ('maintain', plane.maintain), ('recover', plane.recover),
                ('unconsumed', lambda: plane.unconsumed('pons')),
                ('pop', lambda: broker.pop(now=now[0])),
                ('consumption_maintenance', consumption_maintenance),
            )
            number = [100000]
            def mutate(kind):
                number[0] += 1; n = number[0]
                if kind == 'header':
                    peer.put(DOMAIN + ':header_number', str(n), dict(number=n, synthetic=True),
                        dict(authority='SYNTHETIC_OFFLINE_FIXTURE'))
                elif kind == 'receipt':
                    peer.put_receipt(DOMAIN + ':receipt', str(n), dict(synthetic=True, receipt=n),
                        dict(authority='SYNTHETIC_OFFLINE_FIXTURE'))
                elif kind == 'checkpoint':
                    peer.checkpoint('synthetic_unrelated_survivor_checkpoint', dict(sequence=n))
            for kind in ('none', 'header', 'receipt', 'checkpoint'):
                for name, call in operations:
                    sample = observe(kind + ':' + name, call, repeat,
                        [('current', plane.db), ('pipeline', pipeline.db)],
                        prepare=None if kind == 'none' else lambda kind=kind: mutate(kind))
                    sample['maintenance_sweeps'] = sum(row['calls'] for row in sample['sql_shapes']
                        if 'DELETE FROM result_consumption' in row['sql'])
                    result['measurements'].append(sample)
                    output.write_text(json.dumps(result, sort_keys=True, indent=2) + '\n')
                    scratch.check()
            result['economic_state_before_sha256'] = before
            result['economic_state_after_sha256'] = logical_state(plane, pipeline)
            if before != result['economic_state_after_sha256']:
                raise ValueError('benchmark_changed_economic_or_reporting_content')
            result['query_plans'] = {}
            for name, sql, args in (
                ('consumption_maintenance', obsolete, ()),
                ('recover', "SELECT * FROM candidates WHERE lane IN ('pump','pons') AND claim IS NOT NULL", ()),
                ('outbox', '''SELECT c.* FROM candidates c LEFT JOIN result_consumption a
                    ON c.id=a.candidate AND c.generation=a.generation WHERE c.lane=?
                    AND c.result IS NOT NULL AND c.completed=c.desired AND a.candidate IS NULL
                    ORDER BY c.priority,c.deadline,c.id''', ('pons',)),
            ):
                result['query_plans'][name] = [list(row) for row in plane.db.execute(
                    'EXPLAIN QUERY PLAN ' + sql, args)]
            # Capture actual executed statements, rather than inferring the new
            # query from the deliberately retained old-plan comparators above.
            for name, call in (('actual_recover', plane.recover),
                               ('actual_outbox', lambda: plane.unconsumed('pons'))):
                traced = []
                plane.db.set_trace_callback(traced.append)
                try: call()
                finally: plane.db.set_trace_callback(None)
                sql = next(row for row in traced if row.startswith(('SELECT', 'WITH')))
                result['query_plans'][name] = [list(row) for row in plane.db.execute(
                    'EXPLAIN QUERY PLAN ' + sql)]
            # A fixed native public-observation publication batch measures the
            # subtractive read gain against additional index-write cost. Its
            # local RPC arrays are synthetic nominations, never qualification.
            scout = MarketScout(plane)
            class OfflineRpc:
                def batch(self, calls, **kwargs):
                    values = []
                    for method, params in calls:
                        if method == 'eth_getBlockByNumber':
                            block = int(params[0], 16)
                            values.append(dict(number=hex(block), hash='0x' + f'{block:064x}', timestamp=hex(int(now[0]))))
                        elif method == 'eth_getLogs':
                            block = int(params[0]['fromBlock'], 16)
                            values.append([dict(address='0x' + f'{n + 1:040x}',
                                transactionHash='0x' + f'{block * 8 + n:064x}', logIndex=hex(n),
                                transactionIndex='0x0', blockNumber=hex(block),
                                blockHash='0x' + f'{block:064x}', topics=[scout.curve_topics[0]],
                                data='0x') for n in range(8)])
                        else:
                            raise ValueError('benchmark_unexpected_rpc_method')
                    return values
            counter = [2000000]
            def publication():
                counter[0] += 1; block = counter[0]
                scout.read_market(OfflineRpc(), block, block,
                    nominate=lambda event, observed: broker.enqueue(event, now=observed))
            result['native_publication'] = observe('same_native_eight_event_publication',
                publication, 8, [('current', plane.db)])
            result['native_publication_economic_sha256'] = logical_state(plane, pipeline)
            result['native_publication_all_tables_sha256'] = all_native_tables(plane)
            for name in ('candidate_generation_identity', 'candidate_claimed',
                         'candidate_delivery', 'pons_watch_due'):
                plane.db.execute('DROP INDEX IF EXISTS ' + name)
            def reopen():
                owned = Plane(path, clock=lambda: now[0]); owned.close()
            result['populated_constructor_migration'] = observe('populated_constructor_migration',
                reopen, 1, [])
            result['economic_after_migration_sha256'] = logical_state(plane, pipeline)
            result['native_all_tables_after_migration_sha256'] = all_native_tables(plane)
            if result['economic_after_migration_sha256'] != result['native_publication_economic_sha256']:
                raise ValueError('benchmark_migration_changed_native_rows')
            if result['native_all_tables_after_migration_sha256'] != result['native_publication_all_tables_sha256']:
                raise ValueError('benchmark_migration_changed_full_native_tables')
            output.write_text(json.dumps(result, sort_keys=True, indent=2) + '\n')
            scratch.success = True
            return result
        finally:
            peer.close(); pipeline.close(); broker.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output')
    parser.add_argument('--repeat', type=int, choices=range(1, 65), default=16)
    parser.add_argument('--padding', type=int, choices=(768, 4096), default=768)
    parser.add_argument('--covering', action='store_true')
    args = parser.parse_args()
    run(args.output, repeat=args.repeat, padding=args.padding, covering=args.covering)
