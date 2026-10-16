"""Offline contracts for the one-attempt diagnostic; no services or providers."""
import importlib
import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import sqlite3
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from engineering.diagnostics import current_combined_observation_20261014 as diagnostic
from engineering.diagnostics import diagnostic_access_20261014 as access
from meme_machine.operational.supervisor import Supervisor


class DiagnosticWindowTests(unittest.TestCase):
    def test_shorter_measurement_preserves_original_readiness_and_hard_deadlines(self):
        window = diagnostic.Window(0, measurement_seconds=300)
        window.decision(200, True)
        self.assertIsNone(window.decision(300, True))
        self.assertEqual(window.original_readiness, 'PASS')
        self.assertEqual(window.decision(500, True), 'POST_STARTUP_COMPLETE')
        late = diagnostic.Window(0, measurement_seconds=300)
        late.decision(300, False); late.decision(350, True)
        self.assertEqual(late.original_readiness, 'FAIL')
        self.assertEqual(late.decision(650, True), 'POST_STARTUP_COMPLETE')
        for value in (299, 901, True, 300.0):
            with self.assertRaisesRegex(ValueError, 'diagnostic_measurement_bound'):
                diagnostic.Window(0, measurement_seconds=value)

    def test_explicit_source_revision_must_match_installed_git(self):
        diagnostic.validate_revision('a' * 40, 'a' * 40)
        with self.assertRaisesRegex(ValueError, 'revision_mismatch'):
            diagnostic.validate_revision('a' * 40, 'b' * 40)
        with self.assertRaisesRegex(ValueError, 'revision_mismatch'):
            diagnostic.validate_revision('unvalidated', 'unvalidated')

    def test_required_unit_runtime_stop_and_restart_properties(self):
        properties = dict(Restart='no', RuntimeMaxUSec='30min', TimeoutStopUSec='1min 5s',
                          KillMode='control-group')
        diagnostic.verify_unit_properties(properties)
        for key, value in [('Restart', 'always'), ('RuntimeMaxUSec', '31min 5s'),
                           ('TimeoutStopUSec', '70s'), ('KillMode', 'process')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                diagnostic.verify_unit_properties(dict(properties, **{key: value}))

    def test_original_failure_survives_late_restoration(self):
        window = diagnostic.Window(100)
        self.assertIsNone(window.decision(400, False))
        self.assertEqual(window.original_readiness, 'FAIL')
        self.assertIsNone(window.decision(450, True))
        self.assertEqual(window.original_readiness, 'FAIL')
        self.assertEqual(window.decision(1350, True), 'POST_STARTUP_COMPLETE')

    def test_startup_and_total_work_are_bounded(self):
        window = diagnostic.Window(0)
        self.assertEqual(window.decision(900, False), 'STARTUP_LIMITATION')
        window = diagnostic.Window(0)
        window.decision(899, True)
        self.assertEqual(window.decision(1800, True), 'WORK_DEADLINE')

    def test_early_restoration_and_readiness_loss(self):
        window = diagnostic.Window(0)
        window.decision(200, True)
        window.decision(300, True)
        self.assertEqual(window.original_readiness, 'PASS')
        self.assertEqual(window.decision(301, False), 'REQUIRED_READINESS_LOST')


class DiagnosticOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.service = diagnostic.SingleAttemptSupervisor(self.root, output=self.root, offline=True)

    def test_second_lane_spawn_is_rejected_before_dispatch(self):
        with patch.object(Supervisor, 'start_lane') as spawn:
            self.service.start_lane('pump')
            with self.assertRaisesRegex(RuntimeError, 'first_worker_exit:pump'):
                self.service.start_lane('pump')
        self.assertEqual(spawn.call_count, 1)
        self.assertTrue(self.service.stop_requested)
        self.assertFalse(json.loads((self.root / 'supervisor-fatal.json').read_text())['retry_dispatched'])

    def test_existing_backoff_can_defer_only_the_first_source_start(self):
        self.service.evidence = None
        with patch.object(Supervisor, 'start_services') as spawn:
            self.service.start_services()
            self.assertFalse(self.service.source_attempted)
            def admitted():
                self.service.evidence = Mock(pid=91); self.service.evidence.poll.return_value = 1
            spawn.side_effect = admitted
            self.service.start_services()
            with self.assertRaisesRegex(RuntimeError, 'first_worker_exit:solana'):
                self.service.start_services()
        self.assertEqual(spawn.call_count, 2)

    def test_source_recovery_never_restarts(self):
        self.service.evidence = Mock(pid=92); self.service.evidence.poll.return_value = 1
        with patch.object(Supervisor, 'recover_evidence') as recovery:
            with self.assertRaisesRegex(RuntimeError, 'first_worker_exit:solana'):
                self.service.recover_evidence()
        recovery.assert_not_called()

    def test_fatal_essentials_survive_optional_file_failure(self):
        self.service.attempted_lanes.add('pump')
        with patch.object(diagnostic, 'write_metadata', side_effect=OSError), patch('builtins.print') as stderr:
            with self.assertRaisesRegex(RuntimeError, 'first_worker_exit:pump'):
                self.service.start_lane('pump')
        self.assertTrue(self.service.stop_requested)
        self.assertIn('"actor": "pump"', stderr.call_args.args[0])
        self.assertIn('"retry_dispatched": false', stderr.call_args.args[0])

    def test_existing_run_finally_drains_after_first_lane_exit(self):
        def started(lane):
            self.service.processes[lane] = Mock(pid=93)
            self.service.processes[lane].poll.return_value = 1
        with patch.object(Supervisor, 'initialize'), patch.object(Supervisor, 'start_services'), \
             patch.object(Supervisor, 'start_lane', side_effect=started) as spawn, \
             patch.object(Supervisor, 'stop_lanes') as drain, patch.object(Supervisor, 'publish'):
            with self.assertRaisesRegex(RuntimeError, 'first_worker_exit:pump'):
                self.service.run(seconds=.1)
        self.assertEqual(spawn.call_count, 2)  # Initial Pump and Pons only.
        drain.assert_called_once()

    def test_non_observation_mode_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'requires_observation'):
            diagnostic.SingleAttemptSupervisor(self.root, output=self.root, admission='NORMAL')


class DiagnosticCollectionTests(unittest.TestCase):
    def test_handler_identity_and_disposition_survive_collection_without_arbitrary_error_text(self):
        import asyncio
        from meme_machine.solana_source_drain import HandlerLedger
        async def interrupted():
            ledger=HandlerLedger('a'*32)
            number=ledger.accept('b'*32,'c'*32,'yellowstone','pump','block_meta',100.,slot=123)
            ledger.phase('CANDIDATE_JOIN');ledger.fail(number,ValueError('api_key=do-not-publish'))
            return ledger.snapshot()
        accounting=asyncio.run(interrupted())
        drain=dict(state='RECOVERY_REQUIRED',source_pid=accounting['pid'],run_identity='a'*32,
            handler_accounting=accounting)
        ipc={('generic_'+str(i)):dict(noise=i) for i in range(256)};ipc['source_drain']=drain
        output=json.loads(json.dumps(diagnostic.required_counters(dict(pid=accounting['pid'],ipc=ipc))))
        selected=output['source_drain']['handler_accounting']
        self.assertEqual(selected,accounting);self.assertEqual(selected['records'][0]['slot'],123)
        self.assertEqual(selected['records'][0]['phase'],'CANDIDATE_JOIN')
        self.assertNotIn('api_key',json.dumps(output))
        accounting['records'][0]['expanded_sql']='do-not-copy'
        selected=diagnostic.required_source_drain(dict(pid=accounting['pid'],ipc=ipc))
        self.assertEqual(selected['handler_accounting'],diagnostic.UNAVAILABLE)
        self.assertNotIn('do-not-copy',json.dumps(selected))

    def test_current_source_drain_survives_fixed_selection_and_missing_stays_unavailable(self):
        queues={name:dict(accepted=10,committed=9,pending=1) for name in ('control','scout','rolling','candidate')}
        drain=dict(state='DRAINING',source_pid=123,run_identity='a'*32,started_at_monotonic=1.,terminal=False,
            accepted_handlers=40,settled_handlers=40,pending_handlers=0,
            closed_sessions=1,preserved_partial_sessions=1,unpreserved_sessions=0,
            all_accepted_committed=False,queues=queues,unreviewed_secret='must_not_copy')
        ipc={('irrelevant_'+str(n)):n for n in range(256)};ipc['source_drain']=drain
        output=json.loads(json.dumps(diagnostic.required_counters(dict(pid=123,ipc=ipc))))['source_drain']
        self.assertEqual(output['queues'],queues);self.assertEqual(output['run_identity'],'a'*32)
        self.assertEqual(output['terminal_at_monotonic'],diagnostic.UNAVAILABLE)
        self.assertNotIn('unreviewed_secret',output)
        # An old canonical terminal row is retained evidence, not a current IPC
        # observation and cannot become a false current drain PASS.
        self.assertEqual(diagnostic.required_counters(dict(source_drain=drain))['source_drain'],diagnostic.UNAVAILABLE)
        queues['scout'].pop('committed')
        self.assertEqual(diagnostic.required_source_drain(dict(pid=123,ipc=ipc))['queues']['scout']['committed'],diagnostic.UNAVAILABLE)
        self.assertEqual(diagnostic.required_source_drain(dict(pid=124,ipc=ipc)),diagnostic.UNAVAILABLE)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); (self.root / 'shared').mkdir()
        self.path = self.root / 'shared/solana-evidence.sqlite'
        with sqlite3.connect(self.path) as db:
            db.executescript('''
                CREATE TABLE service_health(key TEXT PRIMARY KEY,value TEXT);
                CREATE TABLE prewarm_startup(id INTEGER PRIMARY KEY,session TEXT);
                INSERT INTO prewarm_startup VALUES(1,'session-1');
                CREATE TABLE candidate_history_outbox(id TEXT PRIMARY KEY,family TEXT,address TEXT,kind TEXT,created REAL,consumed REAL,body TEXT,hash TEXT);
                CREATE INDEX candidate_history_pending ON candidate_history_outbox(consumed,created);
                CREATE INDEX candidate_history_canonical_pending ON candidate_history_outbox(family,json_extract(body,'$.record.slot')) WHERE kind='canonical' AND consumed IS NULL;
                CREATE TABLE rolling_preparation_jobs(id TEXT PRIMARY KEY,status TEXT,deadline REAL,created REAL);
                CREATE INDEX rolling_preparation_expiry ON rolling_preparation_jobs(status,deadline);
                CREATE TABLE rolling_economic_events(scope TEXT,slot INTEGER,market_time REAL,first_seen REAL);
                CREATE INDEX rolling_event_order ON rolling_economic_events(scope,slot);
            ''')
            for key, value in [('pid', 44), ('owner_scheduler', {'owner_admission': {'generation': 'gen-1'}}),
                               ('ipc', {'pipeline': {'evidence_timing:rolling': {'calls': 10}}})]:
                db.execute('INSERT INTO service_health VALUES(?,?)', (key, json.dumps(value)))
            db.executemany('INSERT INTO candidate_history_outbox VALUES(?,?,?,?,?,NULL,?,?)',
                           [(str(i), 'pump', 'address', 'canonical', float(i),
                             json.dumps({'record': {'identity': 'event-'+str(i), 'slot': i}, 'available': i}),
                             'source-'+str(i)) for i in range(100)])
            db.execute("INSERT INTO rolling_preparation_jobs VALUES('job','pending',20,10)")
            db.execute("INSERT INTO rolling_economic_events VALUES('program:pump',99,100,101)")

    def test_current_generation_bounded_heads_and_explicit_missing_edges(self):
        sample = diagnostic.pipeline_sample(self.root, 44)
        self.assertTrue(sample['available'])
        self.assertEqual(sample['generation'], 'gen-1')
        self.assertEqual(len(sample['pending_outbox_head']), 1)
        self.assertEqual(sample['pending_outbox_head'][0][0], '0')
        self.assertEqual(sample['outbox_head_scope'], 'OLDEST_ONE_ALL_RETAINED_FAMILIES_NOT_REQUIRED_PUMP_HISTORY')
        self.assertEqual(sample['history_deadline_heads']['pending'], ('job', 20, 10))
        self.assertNotIn('ipc', sample['service_health'])
        self.assertEqual(sample['ipc_scope'], 'EXPLICIT_REQUIRED_COUNTERS_ONLY_NOT_DUPLICATED_DESCRIPTIVE_IPC')
        self.assertEqual(sample['required_counters']['ipc_pipeline']['evidence_timing:rolling']['calls'], 10)
        self.assertEqual(sample['missing_edges']['sql_wait_actor'], 'UNAVAILABLE')
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM candidate_history_outbox').fetchone()[0], 100)

    def test_prior_source_pid_is_not_current_evidence(self):
        sample = diagnostic.pipeline_sample(self.root, 45)
        self.assertFalse(sample['available'])
        self.assertEqual(sample['unavailable_reason'], 'SOURCE_PID_MISMATCH')
        self.assertNotIn('pending_outbox_head', sample)

    def test_missing_existing_index_marks_collection_unavailable(self):
        with sqlite3.connect(self.path) as db:
            db.execute('DROP INDEX candidate_history_pending')
        sample = diagnostic.pipeline_sample(self.root, 44)
        self.assertFalse(sample['available'])
        self.assertEqual(sample['unavailable_reason'], 'OperationalError')

    def test_output_limit_stops_without_discarding_prior_samples(self):
        path = self.root / 'metrics.jsonl'; path.write_bytes(b'old\n')
        with patch.object(diagnostic, 'OUTPUT_BYTES', diagnostic.TERMINAL_BYTES + 8):
            with self.assertRaisesRegex(ValueError, 'output_limit'):
                diagnostic.append_sample(path, {'new': 'sample'})
        self.assertEqual(path.read_bytes(), b'old\n')

    def test_metadata_and_terminal_have_independent_reserved_bytes(self):
        path = self.root / 'metrics.jsonl'
        body = {'metric': 1}
        body_bytes = len(json.dumps(body, sort_keys=True, separators=(',', ':')).encode()) + 1
        with patch.object(diagnostic, 'OUTPUT_BYTES', 2 * diagnostic.TERMINAL_BYTES + body_bytes):
            diagnostic.append_sample(path, body)
            self.assertEqual(path.stat().st_size, body_bytes)
            with self.assertRaisesRegex(ValueError, 'output_limit'):
                diagnostic.append_sample(path, body)
        diagnostic.write_metadata(self.root, 'clock.json', {'origin': 0})
        with self.assertRaisesRegex(ValueError, 'metadata_reserve'):
            diagnostic.write_metadata(self.root, 'result.json', {'oversized': 'x' * diagnostic.TERMINAL_BYTES})

    def test_five_second_cadence_preserves_original_cached_collection_clocks(self):
        sampler = diagnostic.FiveSecondSampler()
        first = {'collected_at': 100, 'collected_at_monotonic': 0, 'available': True}
        second = {'collected_at': 105, 'collected_at_monotonic': 5, 'available': True}
        collect = Mock(side_effect=[first, second])
        self.assertEqual(sampler.read(0, collect), (first, True))
        for now in (1, 2, 3, 4.999):
            observation, due = sampler.read(now, collect)
            self.assertIs(observation, first)
            self.assertFalse(due)
            self.assertEqual(observation['collected_at'], 100)
            self.assertEqual(observation['collected_at_monotonic'], 0)
        self.assertEqual(sampler.read(5, collect), (second, True))
        self.assertEqual(collect.call_count, 2)

    def test_retained_payload_shape_fits_output_at_corrected_cadence(self):
        # O7's largest retained complete shape, transformed with the current
        # fixed phases, sixteen thread rows/inventories and large counters.
        # Not a universal future-size guarantee: the live output guard and
        # independent terminal reserve remain necessary. Duplicate IPC/owner
        # copies and thirty-one unrelated old outbox headers are omitted;
        # all thirty-two canonical receipt/ACK cohort members remain.
        base_bytes, cohort_bytes = 59812, 27573
        sampler = diagnostic.FiveSecondSampler(); full_count = 0; guard_count = 0
        for now in range(1800):
            _, due = sampler.read(now, lambda: {'collected_at_monotonic': now})
            full_count += due
            guard_count += not due
        self.assertEqual((full_count, guard_count), (360, 1440))
        maximum_retained_shape_bytes = full_count * (base_bytes + cohort_bytes) + guard_count * diagnostic.GUARD_BYTES
        self.assertLess(maximum_retained_shape_bytes, diagnostic.OUTPUT_BYTES - 2 * diagnostic.TERMINAL_BYTES)
        path = self.root / 'metrics.jsonl'
        with self.assertRaisesRegex(ValueError, 'guard_record_bound'):
            diagnostic.append_guard(path, {'oversized': 'x' * diagnostic.GUARD_BYTES})
        self.assertFalse(path.exists())

    def test_fixed_frontiers_exclude_arbitrary_provider_urls_and_errors(self):
        providers = {'evidence': {'program_frontiers': [
            {'scope': diagnostic.program_scope('pump'), 'slot': 10, 'updated': 11,
             'market_time': 12, 'error': 'secret-url'},
            {'scope': 'untrusted-scope', 'slot': 20}]}}
        output = diagnostic.selected_frontiers(providers)
        self.assertEqual(len(output['program_frontiers']), 1)
        self.assertNotIn('secret-url', json.dumps(output))

    def test_kernel_scope_is_bounded_owned_cgroup_and_main_thread_only(self):
        fields = ['0'] * 45; fields[0] = 'S'
        def kernel(path, limit=8192):
            if path.name == 'cgroup.procs':
                return ' '.join(str(pid) for pid in range(101, 171))
            if path.name == 'stat' and '/proc/' in str(path):
                return '101 (owned) ' + ' '.join(fields)
            if path.name == 'schedstat':
                return '1000 2000 3'
            if path.name == 'io':
                return 'read_bytes: 4\nwrite_bytes: 5\n'
            return 'some avg10=0.00 total=1\n'
        with patch.object(diagnostic, 'bounded_text', side_effect=kernel) as reads:
            result = diagnostic.counters(Path('/mock-cgroup'), {'pump': 101, 'foreign': 999})
        self.assertTrue(result['process_scope_truncated'])
        self.assertEqual(len(result['workers']), 64)
        self.assertEqual(result['workers']['pump']['runnable_wait_ns'], 2000)
        self.assertEqual(result['workers']['pump']['schedstat_scope'], 'PROCESS_MAIN_THREAD_ONLY')
        self.assertEqual(result['owner_thread_schedstat'], 'UNAVAILABLE_NO_EXPORTED_NATIVE_TID')
        self.assertFalse(any('/proc/999/' in str(call.args[0]) for call in reads.call_args_list))

    def test_actual_owner_thread_counters_require_matching_owned_source(self):
        fields=['0']*45;fields[0]='D';fields[39]='12'
        def kernel(path,limit=8192):
            if path.name=='cgroup.procs':return '44'
            if path.name=='stat':return '44 (owner) '+' '.join(fields)
            if path.name=='schedstat':return '1000 2000 3'
            if path.name=='wchan':return 'folio_wait_bit_common\n'
            if path.name=='io':return 'read_bytes: 4\n'
            return 'some avg10=0.00 total=1\n'
        with patch.object(diagnostic,'bounded_text',side_effect=kernel) as reads:
            result=diagnostic.counters(Path('/mock'),{'solana':44},dict(owner_pid=44,native_thread_id=55))
            owner=result['owner_thread_schedstat']
            self.assertEqual(owner['native_thread_id'],55);self.assertEqual(owner['pid'],44)
            self.assertEqual(owner['runnable_wait_ns'],2000);self.assertEqual(owner['state'],'D')
            self.assertEqual(owner['wait_channel'],'folio_wait_bit_common')
            self.assertEqual(owner['delayacct_blkio_ticks'],12)
            self.assertTrue(any(str(c.args[0])=='/proc/44/task/55/schedstat' for c in reads.call_args_list))
        with patch.object(diagnostic,'bounded_text',side_effect=kernel) as reads:
            result=diagnostic.counters(Path('/mock'),{'solana':44},dict(owner_pid=99,native_thread_id=55))
            self.assertEqual(result['owner_thread_schedstat'],'UNAVAILABLE_OWNER_IDENTITY_MISMATCH')
            self.assertFalse(any('/proc/99/' in str(c.args[0]) for c in reads.call_args_list))

    def test_pons_thread_sample_is_owned_identity_bound_and_keeps_collection_clock(self):
        proc = self.root / 'proc'; task = proc / '44' / 'task'
        fields = ['0'] * 45; fields[0] = 'S'; fields[11] = '7'; fields[12] = '3'; fields[19] = '900'
        (proc / '44').mkdir(parents=True)
        (proc / '44' / 'stat').write_text('44 (python) ' + ' '.join(fields))
        for tid in (44, 55):
            folder = task / str(tid); folder.mkdir(parents=True)
            (folder / 'stat').write_text(str(tid) + ' (python) ' + ' '.join(fields))
            (folder / 'schedstat').write_text('1000 2000 3')
            (folder / 'io').write_text('rchar: 400\nsyscr: 20\nread_bytes: 0\nwrite_bytes: 8\n')
            (folder / 'wchan').write_text('futex_wait_queue\n')
        inventory = dict(pid=44, collected_at_monotonic=95, truncated=False,
            threads=[dict(native_thread_id=44, role='main'),
                     dict(native_thread_id=55, role='pons-discovery')])
        with patch.object(diagnostic.time, 'monotonic', return_value=100):
            result = diagnostic.pons_thread_counters(44, [44], inventory, proc=proc)
        self.assertTrue(result['available']); self.assertEqual(result['process_start_ticks'], 900)
        self.assertEqual(result['inventory']['collected_at_monotonic'], 95)
        self.assertEqual(result['threads'][1]['role'], 'pons-discovery')
        self.assertEqual(result['threads'][1]['io']['rchar'], 400)
        self.assertEqual(result['threads'][1]['runnable_wait_ns'], 2000)
        self.assertEqual(result['threads'][1]['start_ticks'], 900)
        with patch.object(diagnostic.os, 'scandir') as scan:
            rejected = diagnostic.pons_thread_counters(44, [99], inventory, proc=proc)
        self.assertFalse(rejected['available']); scan.assert_not_called()
        with patch.object(diagnostic.time, 'monotonic', return_value=111):
            stale = diagnostic.pons_thread_counters(44, [44], inventory, proc=proc)
        self.assertFalse(stale['inventory']['available'])
        self.assertEqual(stale['inventory']['collected_at_monotonic'], 95)
        self.assertTrue(all(row['role'] == 'UNAVAILABLE' for row in stale['threads']))

    def test_pons_thread_sample_truncation_disappearance_and_pid_reuse_are_explicit(self):
        proc = self.root / 'proc'; folder = proc / '44'; folder.mkdir(parents=True)
        fields = ['0'] * 45; fields[0] = 'R'; fields[19] = '900'
        raw = '44 (python) ' + ' '.join(fields)
        (folder / 'stat').write_text(raw)
        for tid in range(44, 62):(folder / 'task' / str(tid)).mkdir(parents=True)
        # Threads disappear between enumeration and individual counter reads.
        result = diagnostic.pons_thread_counters(44, [44], None, proc=proc)
        self.assertTrue(result['available']); self.assertTrue(result['truncated'])
        self.assertEqual(result['observed_thread_count_lower_bound'], 17)
        self.assertEqual(len(result['threads']), 16)
        self.assertTrue(all(row['available'] is False for row in result['threads']))
        changed = list(fields); changed[19] = '901'
        with patch.object(diagnostic, 'bounded_text', side_effect=[raw, '44 (python) ' + ' '.join(changed)]), \
                patch.object(diagnostic.os, 'scandir') as entries:
            entries.return_value.__enter__.return_value = iter(())
            result = diagnostic.pons_thread_counters(44, [44], None, proc=proc)
        self.assertFalse(result['available']); self.assertEqual(result['reason'], 'PONS_PROCESS_IDENTITY_CHANGED')
        self.assertEqual(result['threads'], [])

    def test_completed_owner_identity_and_slow_ring_survive_required_serialization(self):
        row=dict(stage='maintenance_decision',component='NONE',origin_module='meme_machine.solana_evidence_service',
            origin_line=999,priority=4,sequence=12,pid=44,native_thread_id=55,
            started_monotonic=10,completed_monotonic=52,execution_microseconds=42000000,
            execution_cpu_microseconds=1000000,queue_microseconds=200000,outcome='COMPLETED',
            unexpected_text='must-not-retain')
        owner={f'unrelated_{i}':i for i in range(160)}
        owner.update(owner_pid=44,native_thread_id=55,active_operation=row,
            recent_slow_operations=[dict(row) for _ in range(8)])
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE service_health SET value=? WHERE key='owner_scheduler'",(json.dumps(owner),))
        sample=diagnostic.pipeline_sample(self.root,44)
        output=self.root/'owner-metrics.jsonl';diagnostic.append_sample(output,dict(sample_kind='full',pipeline=sample))
        required=json.loads(output.read_text())['pipeline']['required_counters']
        self.assertEqual(required['owner_scheduler']['native_thread_id'],55)
        active=required['owner_operations']['active'];self.assertEqual(active['stage'],'maintenance_decision')
        self.assertEqual(active['execution_microseconds'],42000000)
        self.assertEqual(len(required['owner_operations']['recent']),8)
        self.assertNotIn('must-not-retain',json.dumps(required))
        owner['recent_slow_operations'].append(dict(row))
        self.assertEqual(diagnostic.required_counters({'owner_scheduler':owner})['owner_operations']['recent'],'UNAVAILABLE')

    def test_owner_telemetry_ring_bounds_and_preserves_original_failure(self):
        from meme_machine import solana_evidence_control as control
        clock=[100.0]
        owner=control.PriorityOwner(lambda:SimpleNamespace(close=lambda:None),clock=lambda:clock[0])
        owner.ready.result(timeout=1)
        sentinel=RuntimeError('original callback error')
        try:
            for number in range(10):
                def command(state):
                    clock[0]+=2
                    if number==9:raise sentinel
                    return number
                future=owner.submit(command,priority=4)
                if number==9:
                    with self.assertRaises(RuntimeError) as raised:future.result(timeout=1)
                    self.assertIs(raised.exception,sentinel)
                else:self.assertEqual(future.result(timeout=1),number)
            # A following callback fences the preceding completed record.
            owner.submit(lambda state:None,priority=4).result(timeout=1)
            snapshot=owner.telemetry();self.assertEqual(len(snapshot['recent_slow_operations']),8)
            self.assertEqual(snapshot['recent_slow_operations'][-1]['outcome'],'FAILED')
            self.assertEqual(snapshot['recent_slow_operations'][-1]['execution_microseconds'],2000000)
            snapshot['recent_slow_operations'].clear()
            self.assertEqual(len(owner.telemetry()['recent_slow_operations']),8)
        finally:owner.close()

    def test_required_recorder_registration_missing_false_and_pid_mismatch(self):
        coverage = diagnostic.RecorderCoverage()
        self.assertIsNone(coverage.check({}, 44, 0))
        self.assertEqual(coverage.check({}, 44, 30), 'REQUIRED_RECORDER_MISSING')
        for row in ({'pid': 44, 'recorder_valid': False}, {'pid': 45, 'recorder_valid': True}):
            self.assertEqual(diagnostic.RecorderCoverage().check(
                {'service_health': {'sqlite_failure_recorder': row}}, 44, 0),
                'REQUIRED_RECORDER_INVALID_OR_WRONG_PID')

    def test_required_recorder_loss_after_valid_registration_stops_immediately(self):
        coverage = diagnostic.RecorderCoverage()
        self.assertIsNone(coverage.check({'service_health': {'sqlite_failure_recorder':
            {'pid': 44, 'recorder_valid': True}}}, 44, 0))
        self.assertEqual(coverage.check({}, 44, 1), 'REQUIRED_RECORDER_MISSING')

    def test_import_never_installs_or_dispatches(self):
        with patch.object(subprocess, 'check_output', side_effect=AssertionError('dispatch')), \
             patch.object(subprocess, 'run', side_effect=AssertionError('dispatch')):
            importlib.reload(diagnostic)

    def test_exact_cohort_distinguishes_consumer_commit_from_owner_ack(self):
        consumer_path = self.root / 'shared/solana-candidate-history.sqlite'
        with sqlite3.connect(consumer_path) as db:
            db.execute('CREATE TABLE source_receipts(id TEXT PRIMARY KEY,at REAL,body TEXT,hash TEXT)')
            for identity in ('0', '1'):
                body = json.dumps({'source_hash': 'source-'+identity,
                    'scope': 'candidate:pump:address', 'canonical_identity': 'event-'+identity})
                db.execute('INSERT INTO source_receipts VALUES(?,?,?,?)',
                           (identity, 500, body, hashlib.sha256(body.encode()).hexdigest()))
        with sqlite3.connect(self.path) as db:
            from meme_machine.solana_evidence_plane import canonical
            compact = canonical({'source_hash': 'source-1',
                                 'record': {'identity': 'event-1', 'slot': 1}, 'available': 1})
            db.execute('UPDATE candidate_history_outbox SET consumed=501,body=?,hash=? WHERE id=?',
                       (compact, hashlib.sha256(compact.encode()).hexdigest(), '1'))
        cohort = diagnostic.ReceiptCohort(); cohort.identities = ['0', '1', '2']
        pipeline = diagnostic.pipeline_sample(self.root, 44); pipeline['pending_canonical_heads'] = []
        sample = cohort.sample(self.root, pipeline)
        self.assertTrue(sample['available'])
        self.assertEqual([row['state'] for row in sample['identities']],
                         ['CONSUMER_RECEIPT_OBSERVED_ACK_PENDING', 'ACK_MARKER_OBSERVED', 'DELIVERY_PENDING'])
        self.assertEqual(sample['identities'][1]['original_available'], 1)

    def test_cohort_authenticates_receipt_and_keeps_original_identity(self):
        consumer_path = self.root / 'shared/solana-candidate-history.sqlite'
        with sqlite3.connect(consumer_path) as db:
            db.execute('CREATE TABLE source_receipts(id TEXT PRIMARY KEY,at REAL,body TEXT,hash TEXT)')
            db.execute("INSERT INTO source_receipts VALUES('0',500,'{}','bad-hash')")
        cohort = diagnostic.ReceiptCohort(); cohort.identities = ['0']
        pipeline = diagnostic.pipeline_sample(self.root, 44); pipeline['pending_canonical_heads'] = []
        sample = cohort.sample(self.root, pipeline)
        self.assertEqual(sample['identities'][0]['state'], 'RECEIPT_AUTHENTICATION_UNAVAILABLE_OR_SKEW')
        self.assertEqual(cohort.identities, ['0'])

    def test_required_nested_counters_survive_real_sql_collection_and_serialization(self):
        # This reproduces the retained IPC shape: >128 aggregate keys preceded
        # pipeline, and nested descriptive keys also exceeded that limit.
        ipc = {f'unrelated_{i}': i for i in range(160)}
        ipc.update({'owner.stage.source_commit.execution_cpu_total_microseconds': 1234,
                    'owner.stage.source_commit.component.candidate.queue_total_microseconds': 2345,
                    'checkpoint.boundary_total_microseconds': 3456,
                    'secret_url': 'https://secret.invalid/?apikey=never-copy',
                    'pipeline': {'economic_prepared:rolling': {'calls': 7, 'records': 11,
                        'cpu_seconds_total_microseconds': 4567, 'wall_seconds_total_microseconds': 5000},
                        'candidate_phase:economic_store': {'calls': 8, 'failed_calls': 1,
                            'bulk_calls': 5, 'bulk_records': 500, 'scalar_calls': 2, 'scalar_records': 8,
                            'wall_seconds_total_microseconds': 11000,
                            'cpu_seconds_total_microseconds': 9000,
                            'runnable_wait_seconds_total_microseconds': 1000,
                            'runnable_measured_calls': 7, 'runnable_unavailable_calls': 1,
                            'unmeasured_calls': 0, 'secret': 'do-not-copy'},
                        'evidence_timing:rolling': {'calls': 13, 'latest_slot': 101,
                            'owner_queue_total_microseconds': 5678},
                        'arbitrary-address-key': {'calls': 999}}})
        storage = {f'unrelated_{i}': i for i in range(160)}
        storage.update({'owner_sql_transactions': {'commit.calls': 19,
            'commit.wall_total_microseconds': 6789}, 'source_commit.total_microseconds': 7890})
        retention={f'retention_phase.{phase}.{clock}_us':n+1
                   for n,(phase,clock) in enumerate((phase,clock)
                   for phase in ('plan','transaction','housekeeping','post')
                   for clock in ('wall','cpu','runnable'))}
        retention['retention_phase.unmeasured']=1
        storage.update(retention)
        storage['retention_phase.plan.secret']='do-not-copy'
        owner = {f'unrelated_{i}': i for i in range(160)}
        owner.update(owner_admission={'generation': 'gen-1'}, queued=4)
        owner['priority5.queue_total_us'] = 8901
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE service_health SET value=? WHERE key='ipc'", (json.dumps(ipc),))
            db.execute("UPDATE service_health SET value=? WHERE key='owner_scheduler'", (json.dumps(owner),))
            db.execute('INSERT INTO service_health VALUES(?,?)', ('storage_maintenance', json.dumps(storage)))
        sample = diagnostic.pipeline_sample(self.root, 44)
        self.assertNotIn('ipc', sample['service_health'])  # Fixed fields retained once, before clipping.
        output = self.root / 'metrics.jsonl'
        diagnostic.append_sample(output, {'sample_kind': 'full', 'pipeline': sample})
        retained = json.loads(output.read_text())['pipeline']['required_counters']
        self.assertEqual(retained['ipc_pipeline']['economic_prepared:rolling']['records'], 11)
        self.assertEqual(retained['ipc_pipeline']['economic_prepared:rolling']['wall_seconds_total_microseconds'], 5000)
        phases = retained['ipc_pipeline']['candidate_phase:economic_store']
        self.assertEqual(phases['wall_seconds_total_microseconds'], 11000)
        self.assertEqual(phases['runnable_wait_seconds_total_microseconds'], 1000)
        self.assertEqual(phases['failed_calls'], 1)
        self.assertEqual(phases['runnable_unavailable_calls'], 1)
        self.assertEqual({key: phases[key] for key in ('bulk_calls','bulk_records','scalar_calls','scalar_records')},
                         dict(bulk_calls=5,bulk_records=500,scalar_calls=2,scalar_records=8))
        self.assertNotIn('secret', phases)
        self.assertEqual(retained['ipc_pipeline']['evidence_timing:rolling']['latest_slot'], 101)
        self.assertEqual(retained['ipc_aggregate']['checkpoint.boundary_total_microseconds'], 3456)
        self.assertEqual(retained['owner_sql_transactions']['commit.calls'], 19)
        self.assertEqual(retained['storage_stages']['source_commit.total_microseconds'], 7890)
        self.assertEqual({key:retained['storage_stages'][key] for key in retention},retention)
        self.assertNotIn('retention_phase.plan.secret',retained['storage_stages'])
        self.assertEqual(retained['owner_scheduler']['priority5.queue_total_us'], 8901)
        self.assertEqual(retained['owner_scheduler']['queued'], 4)
        self.assertNotIn('secret.invalid', output.read_text())
        self.assertNotIn('arbitrary-address-key', retained['ipc_pipeline'])

    def test_startup_declaration_and_exact_feed_window_survive_without_rechecking_proofs(self):
        from meme_machine.solana_evidence_plane import digest
        body={'required_intervals':{'pump':[100,100],'pumpswap':[100,100]},
              'failure':'private-do-not-copy'}
        with sqlite3.connect(self.path) as db:
            for column in ('phase TEXT','released INTEGER','body TEXT','hash TEXT'):
                db.execute('ALTER TABLE prewarm_startup ADD COLUMN '+column)
            db.execute('UPDATE prewarm_startup SET phase=?,released=0,body=?,hash=?',
                ('WAIT_FOR_DURABLE_PUBLICATION',json.dumps(body),digest(body)))
            db.execute('CREATE TABLE prewarm_startup_feeds(session TEXT,family TEXT,lo INTEGER,hi INTEGER,ack_at REAL,native_at REAL,PRIMARY KEY(session,family))')
            db.executemany('INSERT INTO prewarm_startup_feeds VALUES(?,?,?,?,?,?)',
                [('session-1','pump',100,100,10,11),('session-1','pumpswap',100,100,10,None),
                 ('old-session','pump',1,999,1,2)])
        sample=diagnostic.pipeline_sample(self.root,44)
        self.assertEqual(sample['source_session'],'session-1')
        self.assertEqual(sample['startup_gate'],dict(phase='WAIT_FOR_DURABLE_PUBLICATION',released=False,
            feeds=[('pump',100,100,10,11),('pumpswap',100,100,10,None)]))
        output=self.root/'startup-metrics.jsonl'
        diagnostic.append_sample(output,{'sample_kind':'full','pipeline':sample})
        retained=json.loads(output.read_text())['pipeline']['startup_gate']
        self.assertFalse(retained['released']);self.assertEqual(retained['feeds'][1][4],None)
        self.assertNotIn('private-do-not-copy',output.read_text())
        with sqlite3.connect(self.path) as db:db.execute("UPDATE prewarm_startup SET hash='bad'")
        sample=diagnostic.pipeline_sample(self.root,44)
        self.assertFalse(sample['startup_gate']['available'])
        self.assertNotIn('released',sample['startup_gate'])

    def test_missing_startup_detail_preserves_source_session_and_stays_unavailable(self):
        sample=diagnostic.pipeline_sample(self.root,44)
        self.assertEqual(sample['source_session'],'session-1')
        self.assertEqual(sample['startup_gate'],dict(available=False,reason='STARTUP_FIELDS_UNAVAILABLE'))

    def test_missing_required_counter_groups_are_unavailable_not_zero(self):
        selected = diagnostic.required_counters({'ipc': {'pipeline': None}})
        self.assertEqual(selected['ipc_pipeline'], 'UNAVAILABLE')
        self.assertEqual(selected['ipc_aggregate'], 'UNAVAILABLE')
        self.assertEqual(selected['owner_sql_transactions'], 'UNAVAILABLE')
        self.assertEqual(selected['storage_stages'], 'UNAVAILABLE')
        self.assertEqual(selected['development_phases'], 'UNAVAILABLE')
        with patch.object(diagnostic, 'COUNTER_BYTES', 1):
            self.assertEqual(diagnostic.required_counters({}),
                             {'available': False, 'reason': 'REQUIRED_COUNTER_BOUND'})

    def test_operation_costs_survive_full_sql_collection_without_private_or_fake_values(self):
        from meme_machine.runtime import operation_costs as costs
        raw = dict(enabled=True, pid=44, collected_monotonic=100, collected_wall=200,
            recorder_valid=True, recording_lost_calls=0, active_overflow_calls=0,
            rows={'owner.reactivation_promote': {**{key: 7 for key in costs._FIELDS},
                'sql': {bucket: {key: 9 for key in costs._SQL_FIELDS} for bucket in costs.SQL_BUCKETS},
                'secret': 'never-copy-provider-token'}}, active=[], not_reached=list(costs.NAMES[1:]))
        raw['rows']['owner.reactivation_promote']['sql']['statement']['cpu_microseconds'] = None
        ipc = {f'unrelated_{i}': i for i in range(160)}
        ipc['operation_costs'] = raw
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE service_health SET value=? WHERE key='ipc'", (json.dumps(ipc),))
        sample = diagnostic.pipeline_sample(self.root, 44)
        output = self.root / 'operation-costs.jsonl'
        diagnostic.append_sample(output, dict(sample_kind='full', pipeline=sample,
            lanes=diagnostic.descriptive_lanes({'pons': {'phase': 'DISCOVERING', 'operation_costs': raw}}),
            pons_operation_costs=diagnostic.operation_costs(dict(raw, pid=55), 55)))
        retained = json.loads(output.read_text())
        profile = retained['pipeline']['required_counters']['operation_costs']
        self.assertTrue(profile['available'])
        values = profile['rows']['owner.reactivation_promote']
        self.assertEqual(values[profile['fields'].index('calls')], 7)
        self.assertEqual(values[profile['fields'].index('statement.cpu_microseconds')], 'UNAVAILABLE')
        self.assertNotIn('operation_costs', retained['lanes']['pons'])
        self.assertNotIn('never-copy', output.read_text())
        self.assertEqual(retained['pons_operation_costs']['collected_monotonic'], 100)
        self.assertFalse(diagnostic.operation_costs(raw, 55)['available'])
        self.assertFalse(diagnostic.operation_costs(None)['available'])

    def test_operation_cost_coverage_preserves_unavailable_stale_and_failed_samples(self):
        coverage = diagnostic.OperationCoverage()
        self.assertIsNone(coverage.check('pons', {'available': False}, 100))
        row = dict(available=True, recorder_valid=True, recording_lost_calls=0,
                   active_overflow_calls=0, collected_monotonic=99)
        self.assertIsNone(coverage.check('pons', row, 100))
        self.assertEqual(coverage.check('pons', row, 115), 'operation_cost_sample_stale:pons')
        self.assertEqual(coverage.check('pons', dict(row, recorder_valid=False), 100),
                         'operation_cost_recorder_lost:pons')
        self.assertEqual(coverage.check('pons', {'available': False}, 100), 'operation_cost_coverage_lost:pons')
        self.assertEqual(row['collected_monotonic'], 99)

    def test_development_attribution_survives_real_collection_with_fixed_private_schema(self):
        ipc={f'unrelated_{i}':i for i in range(160)}
        row={name:i+1 for i,name in enumerate(diagnostic.DEVELOPMENT_PHASE_FIELDS)}
        row.update(secret='https://secret.invalid/?api_key=never-copy',unexpected=99)
        phases={'development_phase:'+name:dict(row) for name in diagnostic.DEVELOPMENT_PHASE_NAMES}
        phases['development_phase:arbitrary-address']={'calls':9}
        phases['development_phase:plan']['cpu_seconds_total_microseconds']=float('nan')
        del phases['development_phase:plan']['wall_seconds_total_microseconds']
        ipc['pipeline']=phases
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE service_health SET value=? WHERE key='ipc'",(json.dumps(ipc),))
        sample=diagnostic.pipeline_sample(self.root,44)
        output=self.root/'development.jsonl'
        diagnostic.append_sample(output,{'sample_kind':'full','pipeline':sample})
        retained=json.loads(output.read_text())['pipeline']['required_counters']['development_phases']
        self.assertEqual(retained['fields'],list(diagnostic.DEVELOPMENT_PHASE_FIELDS))
        self.assertEqual(set(retained['rows']),set(diagnostic.DEVELOPMENT_PHASE_NAMES))
        self.assertEqual(retained['rows']['selection'],list(range(1,9)))
        for field in ('cpu_seconds_total_microseconds','wall_seconds_total_microseconds'):
            self.assertEqual(retained['rows']['plan'][retained['fields'].index(field)],'UNAVAILABLE')
        self.assertNotIn('secret.invalid',output.read_text())
        self.assertNotIn('arbitrary-address',output.read_text())
        self.assertNotIn('unexpected',output.read_text())

    def join_sample(self):
        return dict(plane='rolling',session='b'*32,source_pid=44,source_generation='a'*32,
            sampled_at=100,sampled_at_monotonic=10,state='ACTIVE',
            join=dict(completed=200,pending_slots=3,pending_bytes=1234,oldest_slot=201,
                      oldest_age=2,oldest_meta=False,oldest_missing_logs=1),
            commit_queue=dict(count=4,bytes=5678))

    def test_existing_join_health_survives_full_sql_and_serialization_path(self):
        from types import SimpleNamespace
        from meme_machine.solana_evidence_service import source_join_snapshot
        sample=self.join_sample()
        sample['join']['secret_url']='https://secret.invalid/?apikey=never-copy'
        source=SimpleNamespace(join_state={'rolling':sample})
        ipc={f'unrelated_{i}':i for i in range(160)}
        ipc['join_state']=source_join_snapshot(source)
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE service_health SET value=? WHERE key='ipc'",(json.dumps(ipc),))
            db.execute("UPDATE service_health SET value=? WHERE key='owner_scheduler'",
                (json.dumps({'owner_admission':{'generation':'a'*32}}),))
        with patch.object(diagnostic.time,'monotonic',return_value=12):
            result=diagnostic.pipeline_sample(self.root,44)
        self.assertNotIn('ipc',result['service_health'])
        output=self.root/'join-metrics.jsonl';diagnostic.append_sample(output,result)
        row=json.loads(output.read_text())['required_counters']['native_join_state']['rolling']
        self.assertEqual(row['status'],'SAMPLED_CURRENT_NOT_COVERAGE')
        self.assertEqual(row['sampled_at'],100);self.assertEqual(row['sampled_at_monotonic'],10)
        self.assertEqual(row['observation_age_seconds'],2)
        self.assertEqual(row['commit_queue'],dict(count=4,bytes=5678))
        self.assertFalse(row['join']['oldest_meta']);self.assertEqual(row['join']['oldest_missing_logs'],1)
        self.assertNotIn('secret.invalid',output.read_text())

    def test_join_stale_closed_and_missing_samples_never_refresh_or_zero(self):
        raw=self.join_sample()
        health=dict(pid=44,ipc={'join_state':{'rolling':raw}},
                    owner_scheduler={'owner_admission':{'generation':'a'*32}})
        first=diagnostic.required_counters(health,now_monotonic=15)['native_join_state']
        stale=diagnostic.required_counters(health,now_monotonic=16)['native_join_state']
        self.assertEqual(first['rolling']['status'],'SAMPLED_CURRENT_NOT_COVERAGE')
        self.assertEqual(stale['rolling']['status'],'STALE')
        self.assertEqual(stale['rolling']['sampled_at_monotonic'],10)
        self.assertEqual(stale['rolling']['observation_age_seconds'],6)
        self.assertEqual(stale['candidate'],'UNAVAILABLE')
        raw['state']='CLOSED';raw['commit_queue']['bytes']=None
        closed=diagnostic.required_counters(health,now_monotonic=20)['native_join_state']['rolling']
        self.assertEqual(closed['status'],'CLOSED');self.assertEqual(closed['commit_queue']['count'],4)
        self.assertEqual(closed['commit_queue']['bytes'],'UNAVAILABLE')
        self.assertEqual(closed['join']['oldest_finality'],'UNAVAILABLE')
        self.assertEqual(closed['sampled_at'],100)

    def test_join_context_fences_and_fixed_schema_remain_bounded(self):
        raw=self.join_sample()
        health=dict(pid=44,ipc={'join_state':{'rolling':raw}},
                    owner_scheduler={'owner_admission':{'generation':'a'*32}})
        for key,value,status in [('source_generation','c'*32,'SOURCE_GENERATION_MISMATCH'),
            ('source_pid',45,'SOURCE_PID_MISMATCH'),('plane','candidate','PLANE_MISMATCH'),
            ('session','untrusted://secret','PROVENANCE_UNAVAILABLE'),
            ('sampled_at_monotonic',30,'SAMPLE_TIME_UNAVAILABLE')]:
            with self.subTest(key=key):
                sample=dict(raw,**{key:value})
                health['ipc']['join_state']={'rolling':sample,**{str(i):sample for i in range(160)}}
                rows=diagnostic.required_counters(health,now_monotonic=12)['native_join_state']
                self.assertEqual(set(rows),{'rolling','candidate'})
                self.assertEqual(rows['rolling']['status'],status)
                self.assertEqual(rows['rolling']['commit_queue']['count'],4)
                self.assertNotIn('untrusted://secret',json.dumps(rows))

    def consumer(self):
        path = self.root / 'shared/solana-candidate-history.sqlite'
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS source_receipts(id TEXT PRIMARY KEY,at REAL,body TEXT,hash TEXT)')
        return path

    def current_record(self, identity, *, slot, market, available, created, family='pump', kind='canonical'):
        from meme_machine.solana_evidence_plane import canonical
        raw = canonical(dict(record=dict(identity='economic-'+identity, slot=slot, market_time=market),
                             available=available))
        with sqlite3.connect(self.path) as db:
            db.execute('INSERT INTO candidate_history_outbox VALUES(?,?,?,?,?,NULL,?,?)',
                       (identity, family, 'address', kind, created, raw, hashlib.sha256(raw.encode()).hexdigest()))
        return raw

    def test_old_stock_cannot_select_the_cohort_and_pending_identities_are_preserved(self):
        self.consumer()
        # Old scout/activity population and historical canonical stock do not
        # become current arrivals merely because source PID is current.
        for i in range(16):
            self.current_record('new-'+str(i), slot=1000+i, market=1001, available=1002, created=1003)
        self.current_record('scout-new', slot=9999, market=1001, available=1002, created=1003, kind='scout')
        cohort = diagnostic.ReceiptCohort(1000)
        first = cohort.sample(self.root, diagnostic.pipeline_sample(self.root, 44))
        self.assertEqual({row['outbox_identity'] for row in first['identities']},
                         {'new-'+str(i) for i in range(16)})
        self.assertTrue(all(row['kind'] == 'canonical' for row in first['identities']))
        self.current_record('later', slot=2000, market=1004, available=1005, created=1006)
        second = cohort.sample(self.root, diagnostic.pipeline_sample(self.root, 44))
        self.assertIn('new-0', cohort.identities)  # No longer in the newest16 head.
        self.assertIn('later', cohort.identities)
        self.assertLessEqual(len(cohort.identities), diagnostic.COHORT_SIZE)
        self.assertEqual(second['retained_pending_count'], 17)

    def test_replayed_market_is_separate_from_current_availability_and_missing_times(self):
        self.consumer()
        self.current_record('replayed', slot=2000, market=1, available=1002, created=1003)
        self.current_record('current', slot=2001, market=1001, available=1002, created=1003)
        self.current_record('unknown', slot=2002, market=None, available=1002, created=1003)
        cohort = diagnostic.ReceiptCohort(1000)
        rows = {row['outbox_identity']: row for row in cohort.sample(
            self.root, diagnostic.pipeline_sample(self.root, 44))['identities']}
        self.assertEqual(rows['replayed']['arrival_class'],
                         'RETAINED_OR_REPLAYED_MARKET_AVAILABLE_DURING_ATTEMPT')
        self.assertEqual(rows['current']['arrival_class'], 'CURRENT_MARKET_EVIDENCE_PHYSICAL_ARRIVAL_UNVERIFIED')
        self.assertEqual(rows['unknown']['original_market_time'], 'UNAVAILABLE')
        self.assertEqual(rows['unknown']['arrival_class'], 'CURRENT_GENERATION_CAPTURE_MARKET_ARRIVAL_UNAVAILABLE')
        self.assertEqual(rows['current']['captured_generation'], 'gen-1')
        self.assertEqual(rows['current']['captured_source_session'], 'session-1')

    def test_generation_change_keeps_pending_identities_but_does_not_report_current_ack(self):
        self.consumer(); self.current_record('current', slot=2000, market=1001, available=1002, created=1003)
        cohort = diagnostic.ReceiptCohort(1000)
        original = diagnostic.pipeline_sample(self.root, 44); cohort.sample(self.root, original)
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE prewarm_startup SET session='session-2' WHERE id=1")
        # Even a stale cached pipeline fence cannot conceal a changed source.
        changed = cohort.sample(self.root, original)
        self.assertFalse(changed['available'])
        self.assertEqual(changed['reason'], 'SOURCE_GENERATION_CHANGED_DURING_CAPTURE')
        self.assertEqual(cohort.identities, ['current'])
        changed = cohort.sample(self.root, diagnostic.pipeline_sample(self.root, 44))
        self.assertEqual(changed['reason'], 'SOURCE_GENERATION_INVALIDATED')

    def test_exact_ack_requires_matching_receipt_and_compacted_source_content(self):
        from meme_machine.solana_evidence_plane import canonical
        consumer = self.consumer()
        raw = self.current_record('current', slot=2000, market=1001, available=1002, created=1003)
        cohort = diagnostic.ReceiptCohort(1000)
        cohort.sample(self.root, diagnostic.pipeline_sample(self.root, 44))
        original_hash = hashlib.sha256(raw.encode()).hexdigest()
        receipt = canonical(dict(source_hash=original_hash, scope='candidate:pump:address', canonical_identity='economic-current'))
        with sqlite3.connect(consumer) as db:
            db.execute('INSERT INTO source_receipts VALUES(?,?,?,?)',
                ('current', 1003, receipt, hashlib.sha256(receipt.encode()).hexdigest()))
        compact = canonical(dict(source_hash=original_hash, record=dict(identity='economic-current', slot=2000), available=1002))
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE candidate_history_outbox SET consumed=1004,body=?,hash='wrong' WHERE id='current'", (compact,))
        row = cohort.sample(self.root, diagnostic.pipeline_sample(self.root, 44))['identities'][0]
        self.assertEqual(row['state'], 'EXACT_ACK_CONTENT_UNAVAILABLE_OR_SKEW')
        self.assertEqual(row['exact_ack_consumed_at'], 'UNAVAILABLE')
        self.assertIn('current', cohort.identities)
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE candidate_history_outbox SET hash=? WHERE id='current'",
                       (hashlib.sha256(compact.encode()).hexdigest(),))
        row = cohort.sample(self.root, diagnostic.pipeline_sample(self.root, 44))['identities'][0]
        self.assertEqual(row['state'], 'ACK_MARKER_OBSERVED')
        self.assertEqual(row['exact_ack_consumed_at'], 1004)
        self.assertEqual(row['original_market_time'], 1001)  # Preserved through compaction.
        self.assertEqual(cohort.identities, [])

    def test_missing_source_session_cannot_be_presented_as_current_history(self):
        self.consumer()
        pipeline = diagnostic.pipeline_sample(self.root, 44); pipeline.pop('source_session')
        result = diagnostic.ReceiptCohort(1000).sample(self.root, pipeline)
        self.assertEqual(result['reason'], 'CURRENT_SOURCE_PROVENANCE_UNAVAILABLE')

    def test_original_source_hash_is_fenced_when_scalars_are_unchanged(self):
        from meme_machine.solana_evidence_plane import canonical
        consumer = self.consumer()
        original = self.current_record('current', slot=2000, market=1001, available=1002, created=1003)
        cohort = diagnostic.ReceiptCohort(1000)
        cohort.sample(self.root, diagnostic.pipeline_sample(self.root, 44))
        original_hash = hashlib.sha256(original.encode()).hexdigest()
        self.assertEqual(cohort.source_hashes['current'], original_hash)
        changed_hash = 'b'*64
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE candidate_history_outbox SET hash=? WHERE id='current'", (changed_hash,))
        row = cohort.sample(self.root, diagnostic.pipeline_sample(self.root, 44))['identities'][0]
        self.assertEqual(row['state'], 'SOURCE_CONTENT_CHANGED')
        self.assertEqual(cohort.identities, ['current'])
        # A compact ACK and matching consumer receipt for the substituted hash
        # must still fail against the captured original economic content.
        compact = canonical(dict(source_hash=changed_hash, record=dict(identity='economic-current', slot=2000), available=1002))
        receipt = canonical(dict(source_hash=changed_hash, scope='candidate:pump:address', canonical_identity='economic-current'))
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE candidate_history_outbox SET consumed=1004,body=?,hash=? WHERE id='current'",
                       (compact, hashlib.sha256(compact.encode()).hexdigest()))
        with sqlite3.connect(consumer) as db:
            db.execute('INSERT INTO source_receipts VALUES(?,?,?,?)',
                       ('current', 1003, receipt, hashlib.sha256(receipt.encode()).hexdigest()))
        row = cohort.sample(self.root, diagnostic.pipeline_sample(self.root, 44))['identities'][0]
        self.assertEqual(row['state'], 'SOURCE_CONTENT_CHANGED')
        self.assertEqual(cohort.identities, ['current'])


class DiagnosticTriggerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.output = Path(self.tmp.name)

    def test_trigger_facts_survive_unchanged_guard_exception_and_reserved_serialization(self):
        record = {}
        providers = {'robinhood': dict(state='CURRENT', sampled_at=100,
            queue_depth=1, oldest_wait_seconds=6.98, endpoint_identity='a'*64,
            role='discovery', cooldown_seconds=7.5, adaptive_interval_seconds=.5)}
        with self.assertRaisesRegex(ValueError, '^provider_queue_limit:robinhood$'):
            diagnostic.provider_queue_guard(providers, self.output, record, now=200, wall=101)
        facts = diagnostic.read_json(self.output / 'guard-failure.json')
        self.assertEqual(facts, record['triggering_guard'])
        self.assertEqual(facts['oldest_wait_seconds'], 6.98)
        self.assertEqual(facts['maximum_queue_wait_seconds'], 5)
        self.assertEqual(facts['provider_sampled_at'], 100)
        self.assertEqual(facts['observed_at'], 101)
        self.assertEqual(facts['cooldown_seconds'], 7.5)
        self.assertEqual(facts['endpoint_identity'], 'a'*64)
        diagnostic.write_metadata(self.output, 'result.json', record)
        self.assertEqual(diagnostic.read_json(self.output / 'result.json')['triggering_guard'], facts)

    def test_failed_recording_preserves_original_error_no_probe_retry_or_delay(self):
        record = {}
        with patch.object(diagnostic, 'write_metadata', side_effect=OSError('private error')) as writer, \
             patch.object(diagnostic.time, 'sleep', side_effect=AssertionError('no retry')), \
             patch.object(diagnostic.sqlite3, 'connect', side_effect=AssertionError('no probe')):
            with self.assertRaisesRegex(ValueError, '^provider_queue_limit:robinhood$'):
                diagnostic.provider_queue_guard({'robinhood': {'queue_depth': 65}},
                    self.output, record, now=1, wall=2)
        writer.assert_called_once()
        self.assertFalse(record['triggering_guard_recorded'])
        self.assertEqual(record['triggering_guard']['queue_depth'], 65)
        self.assertEqual(record['triggering_guard']['oldest_wait_seconds'], 'UNAVAILABLE')

    def test_guard_preserves_exact_boundaries_and_honest_unavailable_private_context(self):
        record = {}
        diagnostic.provider_queue_guard({'robinhood': {'queue_depth': 64, 'oldest_wait_seconds': 5}},
                                       self.output, record, now=1, wall=2)
        self.assertEqual(record, {})
        with self.assertRaisesRegex(ValueError, 'provider_queue_limit:solana'):
            diagnostic.provider_queue_guard({'solana': {'queue_depth': 65,
                'endpoint_identity': 'https://secret.invalid', 'role': 'secret-role'}},
                self.output, record, now=1, wall=2)
        facts = record['triggering_guard']
        self.assertEqual(facts['endpoint_identity'], 'UNAVAILABLE')
        self.assertEqual(facts['role'], 'UNAVAILABLE')
        self.assertNotIn('secret', json.dumps(facts))

    def test_actual_observe_path_keeps_trigger_facts_through_final_result_without_second_start(self):
        root = self.output / 'state'; root.mkdir()
        output = self.output / 'diagnostic'; output.mkdir()
        (root / 'health.json').write_text(json.dumps({'pid': 10,
            'providers': {'robinhood': {'state': 'CURRENT', 'sampled_at': 100,
                'queue_depth': 1, 'oldest_wait_seconds': 6.98}}, 'lanes': {}}))
        starts = []; pid_reads = []
        revision = 'a' * 40
        def ctl(*args, **kwargs):
            if args[:3] == ('show', diagnostic.UNIT, '-p') and args[3:] == ('MainPID', '--value'):
                pid_reads.append(True); return '0' if len(pid_reads) == 1 else '10'
            if args[-2:] == ('UnitFileState', '--value'):
                return 'disabled'
            if args[-2:] == ('ExecStart', '--value'):
                return f'current_combined_observation_20261014 supervise {root} {output} {revision}'
            if args[:2] == ('--no-block', 'start'):
                starts.append(args); return ''
            return 'Restart=no\nRuntimeMaxUSec=30min\nTimeoutStopUSec=1min 5s\nKillMode=control-group'
        real_read = Path.read_text
        def read(path, *args, **kwargs):
            return '1' if path.name == 'memory.current' else real_read(path, *args, **kwargs)
        from types import SimpleNamespace
        with patch.object(diagnostic, 'control', side_effect=ctl), \
             patch.object(diagnostic.subprocess, 'check_output', return_value=revision), \
             patch.object(diagnostic, 'economic', return_value={'flat': True}), \
             patch.object(diagnostic, 'check_access', return_value={'pass': True}), \
             patch.object(diagnostic, 'drain', return_value={'drained': True, 'recovery_required': False}) as drained, \
             patch.object(diagnostic.os, 'statvfs', return_value=SimpleNamespace(f_bavail=10*1024**3, f_frsize=1)), \
             patch.object(Path, 'read_text', new=read), \
             patch.object(diagnostic, 'pipeline_sample', side_effect=AssertionError('guard stops before expensive collection')):
            self.assertEqual(diagnostic.observe_once(root, output, revision), 2)
        self.assertEqual(len(starts), 1)
        drained.assert_called_once()
        result = diagnostic.read_json(output / 'result.json')
        self.assertEqual(result['stop_reason'], 'provider_queue_limit:robinhood')
        self.assertEqual(result['triggering_guard']['oldest_wait_seconds'], 6.98)
        self.assertEqual(result['triggering_guard']['provider_sampled_at'], 100)
        self.assertTrue(result['failure'])
        self.assertEqual(result['acceptance_minutes'], 0)


class DiagnosticNativeRetentionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_pons_cohort_recovery_operation_is_retained_without_admitting_unknown_labels(self):
        operation=dict(operation='pons.cohort_recovery',state='ACTIVE',pid=10,
            native_thread_id=11,at=100,monotonic=200,arbitrary='private-context')
        lane=dict(phase='RECONCILING',reconciled=False,native_operation=operation,
            native_recent_operations=[dict(operation,state='COMPLETE'),
                dict(operation,operation='pons.unreviewed_recovery')])
        output=self.root/'pons-recovery.jsonl'
        diagnostic.append_sample(output,dict(native_lifecycle=diagnostic.native_lifecycle({'pons':lane})))
        retained=json.loads(output.read_text())['native_lifecycle']['pons']
        self.assertEqual(retained['native_operation']['operation'],'pons.cohort_recovery')
        self.assertEqual(retained['native_operation']['state'],'ACTIVE')
        self.assertEqual(retained['native_operation']['native_thread_id'],11)
        self.assertEqual(retained['native_recent_operations'][0]['operation'],'pons.cohort_recovery')
        self.assertEqual(retained['native_recent_operations'][1],'UNAVAILABLE')
        self.assertFalse(retained['reconciled'])
        self.assertNotIn('private-context',output.read_text())
        self.assertNotIn('unreviewed_recovery',output.read_text())

    def test_native_operations_and_signal_survive_descriptive_clipping(self):
        lane = {f'unrelated{i}': i for i in range(160)}
        lane.update(phase='RECONCILING', reconciled=False,
            native_operation=dict(operation='pump.current_runtime_restore', state='ACTIVE',
                pid=10, native_thread_id=11, at=100, monotonic=200, arbitrary='secret'),
            native_recent_operations=[dict(operation='pump.accounting_restore', state='COMPLETE',
                pid=10, native_thread_id=11, at=90, monotonic=190, completed_at=91, elapsed_seconds=1)],
            cancellation_signal=dict(signal=15, pid=10, native_thread_id=11, at=101, monotonic=201))
        self.assertNotIn('native_operation', diagnostic.numeric(lane))
        retained = diagnostic.native_lifecycle({'pump': lane})
        output = self.root / 'metrics.jsonl'
        diagnostic.append_sample(output, {'sample_kind': 'full', 'native_lifecycle': retained})
        retained = json.loads(output.read_text())['native_lifecycle']['pump']
        self.assertEqual(retained['native_operation']['native_thread_id'], 11)
        self.assertEqual(retained['native_operation']['operation'], 'pump.current_runtime_restore')
        self.assertFalse(retained['reconciled'])
        self.assertEqual(retained['cancellation_signal']['signal'], 15)
        self.assertNotIn('secret', output.read_text())

    def test_final_shutdown_projection_is_pid_fenced_bounded_and_not_native_pass(self):
        rows = [dict(operation='wait_timeout', lane='pump', run_id='run-1', at=100, monotonic=200,
            caller_pid=10, caller_native_thread_id=11, target_pid=12, timeout_seconds=15,
            arbitrary='secret')] * 60
        (self.root / 'health.json').write_text(json.dumps(dict(pid=10, at='2026-10-14T17:00:00Z',
            native_shutdown=rows, lanes={'pump': {'phase': 'RECONCILING', 'reconciled': False}})))
        with patch.object(diagnostic.time, 'monotonic', return_value=1800):
            result = diagnostic.final_native_health(self.root, 10, 0)
        self.assertEqual(len(result['native_shutdown']), 48)
        self.assertTrue(result['native_shutdown_truncated'])
        self.assertFalse(result['native_lifecycle']['pump']['reconciled'])
        self.assertEqual(result['native_shutdown'][0]['exit_code'], 'UNAVAILABLE')
        self.assertEqual(result['scope'], 'FINAL_PROJECTION_NOT_PROOF_OF_DRAIN_OR_COMPLETED_RECONCILIATION')
        self.assertNotIn('secret', json.dumps(result))
        with patch.object(diagnostic.time, 'monotonic', return_value=1800):
            self.assertEqual(diagnostic.final_native_health(self.root, 20, 0)['reason'],
                             'FINAL_HEALTH_SUPERVISOR_PID_MISMATCH')
        with patch.object(diagnostic.time, 'monotonic', return_value=1865), \
             patch.object(diagnostic, 'read_json', side_effect=AssertionError('no overdue read')):
            self.assertFalse(diagnostic.final_native_health(self.root, 10, 0)['available'])

    def test_nested_observed_candidate_event_read_is_retained_as_active_operation(self):
        lane = dict(phase='RECONCILING', reconciled=False,
            native_operation=dict(operation='pump.observed_candidate_events', state='ACTIVE',
                pid=10, native_thread_id=11, at=100, monotonic=200))
        output = self.root / 'metrics.jsonl'
        diagnostic.append_sample(output, dict(native_lifecycle=diagnostic.native_lifecycle({'pump': lane})))
        retained = json.loads(output.read_text())['native_lifecycle']['pump']['native_operation']
        self.assertEqual(retained['operation'], 'pump.observed_candidate_events')
        self.assertEqual(retained['state'], 'ACTIVE')
        self.assertEqual(retained['native_thread_id'], 11)

    def test_startup_cleanup_failures_survive_final_projection_and_serialization(self):
        names=('candidate_history_open','accounting_restore','pipeline_open',
               'runtime_evidence_open','evidence_broker_open','sessions_open','survivor_worker_open')
        rows=[dict(operation='pump.startup_cleanup.'+name,state='ERROR',
                   error_type='OSError',pid=10,native_thread_id=11,at=100,monotonic=200,
                   arbitrary='private-cleanup-context') for name in names]
        rows.append(dict(operation='pump.startup_cleanup.unreviewed',state='ERROR'))
        lanes={'pump':dict(phase='STOPPED',reconciled=False,native_recent_operations=rows,
            native_operation=dict(operation='pump.survivor_runtime_restore',state='CANCELLED',
                                  pid=10,native_thread_id=12,at=100,monotonic=200))}
        (self.root/'health.json').write_text(json.dumps(dict(pid=10,lanes=lanes)))
        with patch.object(diagnostic.time,'monotonic',return_value=1800):
            final=diagnostic.final_native_health(self.root,10,0)
        output=self.root/'cleanup.jsonl'
        diagnostic.append_sample(output,dict(native_lifecycle=final['native_lifecycle']))
        retained=json.loads(output.read_text())['native_lifecycle']['pump']
        self.assertIs(retained['reconciled'],False)
        self.assertEqual(retained['phase'],'STOPPED')
        self.assertEqual(retained['native_operation']['operation'],'pump.survivor_runtime_restore')
        self.assertEqual(retained['native_operation']['native_thread_id'],12)
        self.assertEqual(retained['native_operation']['state'],'CANCELLED')
        for original,record in zip(rows[:7],retained['native_recent_operations'][:7]):
            self.assertEqual(record['operation'],original['operation'])
            self.assertEqual(record['state'],'ERROR')
            self.assertEqual(record['error_type'],'OSError')
            self.assertEqual(record['native_thread_id'],11)
        self.assertEqual(retained['native_recent_operations'][7],diagnostic.UNAVAILABLE)
        self.assertNotIn('private-cleanup-context',output.read_text())


class DiagnosticDrainTests(unittest.TestCase):
    def test_failed_unit_is_recovery_required_even_with_no_children(self):
        ctl = Mock(side_effect=['', 'MainPID=0\nActiveState=failed\nSubState=failed'])
        result = diagnostic.drain(0, ctl=ctl, clock=lambda: 1800, children=lambda: [])
        self.assertTrue(result['drained']); self.assertTrue(result['recovery_required'])
        self.assertEqual(result['native_drain'], 'UNVERIFIED_TIMEOUT_ESCALATION_POSSIBLE')
    def test_shutdown_timeout_is_recovery_failure_without_force_kill(self):
        ctl = Mock(side_effect=subprocess.TimeoutExpired('systemctl', 15))
        result = diagnostic.drain(0, ctl=ctl, clock=lambda: 1850, children=lambda: [])
        self.assertFalse(result['drained']); self.assertTrue(result['recovery_required'])
        self.assertEqual(ctl.call_args.args[:2], ('stop', diagnostic.UNIT))
        self.assertEqual(ctl.call_count, 1)

    def test_deadline_exhaustion_dispatches_no_new_stop(self):
        ctl = Mock()
        result = diagnostic.drain(0, ctl=ctl, clock=lambda: 1865)
        self.assertFalse(result['drained']); ctl.assert_not_called()

    def test_main_pid_zero_requires_all_children_drained(self):
        ctl = Mock(side_effect=['', 'MainPID=0\nActiveState=inactive\nSubState=dead'])
        result = diagnostic.drain(0, ctl=ctl, clock=lambda: 1800, children=lambda: ['94'])
        self.assertFalse(result['drained']); self.assertTrue(result['recovery_required'])

    def test_completed_drain_records_service_state(self):
        ctl = Mock(side_effect=['', 'MainPID=0\nActiveState=inactive\nSubState=dead'])
        result = diagnostic.drain(0, ctl=ctl, clock=lambda: 1800, children=lambda: [])
        self.assertTrue(result['drained']); self.assertFalse(result['recovery_required'])


class DiagnosticFinalNativeVerdictTests(unittest.TestCase):
    """Actual controller serialization, without a service or provider start."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'state'; self.root.mkdir()
        self.output = Path(self.tmp.name) / 'diagnostic'; self.output.mkdir()
        self.expected = {'pump': dict(pid=12, process_instance='a' * 32),
                         'pons': dict(pid=13, process_instance='b' * 32)}

    def terminal_health(self):
        now = diagnostic.time.monotonic()
        return dict(pid=10, at='2026-10-15T01:00:00Z',
            lanes={name: dict(identity, phase='STOPPED', reconciled=True,
                exit_code=0, at='2026-10-15T01:00:00Z') for name, identity in self.expected.items()},
            native_shutdown=[dict(operation='wait_completed', lane=name, run_id='c' * 32,
                caller_pid=10, caller_native_thread_id=11, target_pid=identity['pid'],
                at=100, monotonic=now, exit_code=0) for name, identity in self.expected.items()])

    def observe(self, transform=lambda health: None, *, original_failure=False):
        initial = dict(pid=10, lanes={name: dict(identity, phase='DISCOVERING', reconciled=True)
                       for name, identity in self.expected.items()}, providers={})
        if original_failure:
            initial['providers'] = {'robinhood': {'queue_depth': 65}}
        (self.root / 'health.json').write_text(json.dumps(initial))
        starts = []; pid_reads = []; revision = 'a' * 40
        def ctl(*args, **kwargs):
            if args[:3] == ('show', diagnostic.UNIT, '-p') and args[3:] == ('MainPID', '--value'):
                pid_reads.append(True); return '0' if len(pid_reads) == 1 else '10'
            if args[-2:] == ('UnitFileState', '--value'):return 'disabled'
            if args[-2:] == ('ExecStart', '--value'):
                return f'current_combined_observation_20261014 supervise {self.root} {self.output} {revision}'
            if args[:2] == ('--no-block', 'start'):
                starts.append(args); return ''
            return 'Restart=no\nRuntimeMaxUSec=30min\nTimeoutStopUSec=1min 5s\nKillMode=control-group'
        def drain(_):
            health = self.terminal_health(); transform(health)
            (self.root / 'health.json').write_text(json.dumps(health))
            return dict(drained=True, recovery_required=False, native_drain='UNVERIFIED_TIMEOUT_ESCALATION_POSSIBLE')
        real_read = Path.read_text
        def read(path, *args, **kwargs):
            return '1' if path.name == 'memory.current' else real_read(path, *args, **kwargs)
        pipeline = dict(available=False, collected_at=100, collected_at_monotonic=100)
        with patch.object(diagnostic, 'control', side_effect=ctl), \
             patch.object(diagnostic.subprocess, 'check_output', return_value=revision), \
             patch.object(diagnostic, 'economic', return_value={'flat': True}), \
             patch.object(diagnostic, 'check_access', return_value={'pass': True}), \
             patch.object(diagnostic, 'drain', side_effect=drain) as drained, \
             patch.object(diagnostic.os, 'statvfs', return_value=SimpleNamespace(f_bavail=10*1024**3, f_frsize=1)), \
             patch.object(Path, 'read_text', new=read), \
             patch.object(diagnostic.FiveSecondSampler, 'read', return_value=(pipeline, False)), \
             patch.object(diagnostic, 'readiness', return_value=False), \
             patch.object(diagnostic.Window, 'decision', return_value='STARTUP_LIMITATION'):
            code = diagnostic.observe_once(self.root, self.output, revision)
        self.assertEqual(len(starts), 1); drained.assert_called_once()
        result = diagnostic.read_json(self.output / 'result.json')
        self.assertEqual(result['acceptance_minutes'], 0)
        self.assertTrue(result['drained']); self.assertTrue(result['economic_continuity'])
        return code, result

    def test_killed_discovering_native_overrides_empty_group_and_flat_money(self):
        def killed(health):
            health['lanes']['pump'].update(phase='DISCOVERING', exit_code=-9)
            health['native_shutdown'][:0] = [dict(operation=operation, lane='pump',
                run_id='c' * 32, caller_pid=10, target_pid=12, at=100,
                monotonic=diagnostic.time.monotonic(), **fields) for operation, fields in (
                    ('wait_timeout', {'timeout_seconds': 15}), ('signal_sent', {'signal': 9}))]
            health['native_shutdown'][2]['exit_code'] = -9
            health['native_shutdown'][0]['private'] = 'secret-context'
        code, result = self.observe(killed)
        self.assertEqual(code, 2)
        self.assertEqual(result['stop_reason'], 'STARTUP_LIMITATION')
        self.assertEqual(result['native_drain'], 'FAILED')
        self.assertTrue(result['recovery_required'])
        self.assertEqual(result['status'], 'RECOVERY_REQUIRED')
        pump = result['final_native_health']['native_workers']['pump']
        self.assertEqual((pump['phase'], pump['exit_code'], pump['state']), ('DISCOVERING', -9, 'FAILED'))
        self.assertEqual(pump['expected_process_instance'], 'a' * 32)
        self.assertNotIn('secret', (self.output / 'result.json').read_text())

    def test_current_clean_native_stop_is_only_scoped_stop_evidence(self):
        code, result = self.observe()
        self.assertEqual(code, 0)
        self.assertFalse(result['recovery_required'])
        self.assertEqual(result['status'], 'STOPPED_REVIEW_REQUIRED')
        self.assertEqual(result['native_drain'], 'VERIFIED_NATIVE_WORKER_STOP_ONLY')
        self.assertEqual(result['stop_reason'], 'STARTUP_LIMITATION')
        final = result['final_native_health']
        self.assertEqual(final['native_drain_scope'],
            'CURRENT_NATIVE_WORKER_STOP_NOT_GLOBAL_RECOVERY_OR_RESUMABILITY_PROOF')
        self.assertEqual(final['native_workers']['pump']['current_shutdown_records'], 1)

    def test_nonterminal_or_unreconciled_native_never_becomes_clean_stop(self):
        for fields in (dict(phase='RECONCILING', reconciled=False), dict(phase='DISCOVERING'),
                       dict(phase='STOPPED', reconciled=False)):
            with self.subTest(fields=fields):
                code, result = self.observe(lambda health: health['lanes']['pump'].update(fields))
                self.assertEqual(code, 2); self.assertTrue(result['recovery_required'])
                self.assertEqual(result['status'], 'RECOVERY_REQUIRED')

    def test_missing_or_stale_native_evidence_remains_unavailable(self):
        def missing_generation(health):health['lanes']['pump'].pop('process_instance')
        def stale_generation(health):health['lanes']['pump']['process_instance'] = 'd' * 32
        def wrong_pid(health):health['native_shutdown'][0]['target_pid'] = 99
        def wrong_reporter(health):health['native_shutdown'][0]['caller_pid'] = 99
        def old_clock(health):health['native_shutdown'][0]['monotonic'] = 0
        def future_clock(health):health['native_shutdown'][0]['monotonic'] += 10000
        def missing_exit(health):health['lanes']['pump'].pop('exit_code')
        def missing_reconciliation(health):health['lanes']['pump'].pop('reconciled')
        def missing_terminal(health):health.pop('native_shutdown')
        def conflicting_run(health):health['native_shutdown'][0]['run_id'] = 'd' * 32
        for mutate in (missing_generation, stale_generation, wrong_pid, wrong_reporter,
                       old_clock, future_clock, missing_exit, missing_reconciliation,
                       missing_terminal, conflicting_run):
            with self.subTest(mutate=mutate.__name__):
                code, result = self.observe(mutate)
                self.assertEqual(code, 2); self.assertTrue(result['recovery_required'])
                self.assertEqual(result['native_drain'], diagnostic.UNAVAILABLE)
                self.assertEqual(result['status'], 'RECOVERY_REQUIRED')

    def test_original_guard_failure_survives_later_native_failure(self):
        code, result = self.observe(lambda health: health['lanes']['pump'].update(exit_code=-9),
                                    original_failure=True)
        self.assertEqual(code, 2)
        self.assertEqual(result['stop_reason'], 'provider_queue_limit:robinhood')
        self.assertEqual(result['triggering_guard']['queue_depth'], 65)
        self.assertEqual(result['native_drain'], 'FAILED')
        self.assertTrue(result['recovery_required'])

    def test_unavailable_final_projection_preserves_original_guard_failure(self):
        code, result = self.observe(lambda health: health.clear(), original_failure=True)
        self.assertEqual(code, 2)
        self.assertEqual(result['stop_reason'], 'provider_queue_limit:robinhood')
        self.assertEqual(result['triggering_guard']['queue_depth'], 65)
        self.assertEqual(result['native_drain'], diagnostic.UNAVAILABLE)
        self.assertFalse(result['final_native_health']['available'])
        self.assertTrue(result['recovery_required'])

    def test_truncated_native_shutdown_cannot_establish_clean_stop(self):
        def truncated(health):health['native_shutdown'] *= 25
        code, result = self.observe(truncated)
        self.assertEqual(code, 2)
        self.assertTrue(result['final_native_health']['native_shutdown_truncated'])
        self.assertEqual(len(result['final_native_health']['native_shutdown']), 48)
        self.assertEqual(result['native_drain'], diagnostic.UNAVAILABLE)
        self.assertTrue(result['recovery_required'])

    def test_shutdown_request_clock_is_current_but_clean_pre_stop_exits_remain_valid(self):
        health = self.terminal_health()
        for row in health['native_shutdown']:
            row.update(operation='already_exited', monotonic=1500)
        (self.root / 'health.json').write_text(json.dumps(health))
        with patch.object(diagnostic.time, 'monotonic', return_value=1800):
            final = diagnostic.final_native_health(self.root, 10, 1000,
                expected_workers=self.expected, shutdown_started=1700)
            self.assertEqual(final['native_drain'], 'VERIFIED_NATIVE_WORKER_STOP_ONLY')
            for invalid in (999, 1801, float('nan'), None):
                with self.subTest(shutdown_started=invalid):
                    final = diagnostic.final_native_health(self.root, 10, 1000,
                        expected_workers=self.expected, shutdown_started=invalid)
                    self.assertEqual(final['native_drain'], diagnostic.UNAVAILABLE)
                    self.assertEqual(final['native_workers']['pump']['current_shutdown_records'], 0)


class DiagnosticAccessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.properties = dict.fromkeys(access.ACCESS_PROPERTIES, '')
        self.properties.update(User='meme-machine', Group='meme-machine',
            DynamicUser='no', PrivateUsers='no', UMask='0077',
            WorkingDirectory='/opt/meme-machine', ProtectSystem='full', ProtectHome='yes',
            PrivateTmp='yes', NoNewPrivileges='yes', RestrictNamespaces='no')
        self.identity = dict(uid=997, gid=987, groups=[987])

    def mock_output(self):
        output = self.root / 'private-run'; output.mkdir(mode=0o700)
        return output

    def test_probe_preserves_installed_controls_and_disables_network(self):
        command = access.probe_command('/private/probe', self.properties, self.identity, 'a' * 40)
        for value in ('User=meme-machine', 'Group=meme-machine', 'ProtectSystem=full',
                      'ProtectHome=yes', 'PrivateTmp=yes', 'NoNewPrivileges=yes', 'UMask=0077',
                      'PrivateNetwork=yes', 'IPAddressDeny=any', 'RestrictAddressFamilies=AF_UNIX',
                      'RuntimeMaxSec=10', 'TimeoutStopSec=2', 'Restart=no'):
            self.assertIn('--property=' + value, command)
        self.assertNotIn(diagnostic.UNIT, command)
        self.assertNotIn('supervise', command)
        self.assertEqual(command[command.index('--working-directory') + 1], '/opt/meme-machine')
        with self.assertRaisesRegex(ValueError, 'properties_incomplete'):
            access.probe_command('/private/probe', {}, self.identity, 'a' * 40)

    def test_probe_failure_removes_only_own_files_without_real_clock(self):
        output = self.mock_output()
        owned = output.stat()
        identity = dict(uid=owned.st_uid, gid=owned.st_gid, groups=[])
        with patch.object(access, 'service_identity', return_value=identity), \
             patch.object(access.os, 'chown'), \
             self.assertRaisesRegex(ValueError, 'service_probe_failed'):
            access.check_access(output, self.root / 'economic', 'a' * 40, self.properties,
                write_metadata=diagnostic.write_metadata, run=Mock(return_value=Mock(returncode=1)))
        self.assertEqual(list(output.iterdir()), [])
        self.assertFalse((output / 'clock.json').exists())

    def test_controller_can_read_service_outputs_and_probe_clock_is_disposable(self):
        output = self.mock_output(); owned = output.stat()
        identity = dict(uid=owned.st_uid, gid=owned.st_gid, groups=sorted(set(os.getgroups())))
        trusted_payload = access.probe_payload()
        observed = []
        def execute(command, **kwargs):
            probe = Path(command[command.index('--probe-dir') + 1])
            observed.append(json.loads((probe / 'clock.json').read_text()))
            access.service_probe(probe, identity, 'a' * 40, self.properties['WorkingDirectory'])
            return Mock(returncode=0)
        with patch.object(access, 'service_identity', return_value=identity), \
             patch.object(access.os, 'chown'), \
             patch.object(access, 'probe_payload', return_value=trusted_payload), \
             patch.object(access, 'installed_source_identity', return_value=dict(
                 revision='a' * 40, tree='b' * 40, clean=True)):
            verdict = access.check_access(output, self.root / 'economic', 'a' * 40, self.properties,
                write_metadata=diagnostic.write_metadata, run=execute)
        self.assertTrue(verdict['verified']); self.assertTrue(verdict['simulated_clock_only'])
        self.assertEqual(observed, [dict(access_probe=True, revision='a' * 40, origin_monotonic=0)])
        self.assertEqual(verdict['installed_source'], dict(revision='a' * 40, tree='b' * 40, clean=True))
        self.assertEqual(list(output.iterdir()), [])

    def test_installed_source_guard_uses_only_three_read_only_commands_and_one_deadline(self):
        values = [Mock(returncode=0, stdout='a' * 40 + '\n'), Mock(returncode=0, stdout=''),
                  Mock(returncode=0, stdout='b' * 40 + '\n')]
        with patch.object(access.subprocess, 'run', side_effect=values) as run, \
             patch.object(access.time, 'monotonic', side_effect=[10, 11, 12, 13]):
            self.assertEqual(access.installed_source_identity('/installed/source', 'a' * 40),
                             dict(revision='a' * 40, tree='b' * 40, clean=True))
        self.assertEqual([call.args[0] for call in run.call_args_list], [
            ['git', 'rev-parse', 'HEAD'], ['git', 'status', '--porcelain'],
            ['git', 'rev-parse', 'HEAD^{tree}']])
        self.assertEqual([call.kwargs['timeout'] for call in run.call_args_list], [4, 3, 2])
        for call in run.call_args_list:
            self.assertEqual(call.kwargs['env']['GIT_OPTIONAL_LOCKS'], '0')
            self.assertEqual(call.kwargs['cwd'], Path('/installed/source'))
            self.assertEqual(call.kwargs['stderr'], subprocess.DEVNULL)

    def test_installed_source_errors_dirty_tree_and_mismatch_remain_unavailable(self):
        cases = [([Mock(returncode=128, stdout='')], 'source_unavailable'),
                 ([Mock(returncode=0, stdout='a' * 40), Mock(returncode=0, stdout=''),
                   Mock(returncode=128, stdout='')], 'source_unavailable'),
                 ([Mock(returncode=0, stdout='b' * 40), Mock(returncode=0, stdout=''),
                   Mock(returncode=0, stdout='b' * 40)], 'revision_mismatch'),
                 ([Mock(returncode=0, stdout='a' * 40), Mock(returncode=0, stdout=' M tracked'),
                   Mock(returncode=0, stdout='b' * 40)], 'source_not_clean'),
                 ([Mock(returncode=0, stdout='a' * 40), Mock(returncode=0, stdout=''),
                   Mock(returncode=0, stdout='private tree failure')], 'tree_unavailable')]
        for responses, expected in cases:
            with self.subTest(expected=expected), \
                 patch.object(access.subprocess, 'run', side_effect=responses), \
                 self.assertRaisesRegex(ValueError, expected):
                access.installed_source_identity('/installed/source', 'a' * 40)
        with patch.object(access.subprocess, 'run', side_effect=subprocess.TimeoutExpired('git', 1)), \
             self.assertRaisesRegex(ValueError, 'source_unavailable:head'):
            access.installed_source_identity('/installed/source', 'a' * 40)
        with patch.object(access.time, 'monotonic', side_effect=[10, 16]), \
             patch.object(access.subprocess, 'run') as run, \
             self.assertRaisesRegex(ValueError, 'installed_deadline:head'):
            access.installed_source_identity('/installed/source', 'a' * 40)
        run.assert_not_called()

    def test_source_failure_phase_survives_service_probe_and_controller_cleanup(self):
        output = self.mock_output(); owned = output.stat()
        identity = dict(uid=owned.st_uid, gid=owned.st_gid, groups=sorted(set(os.getgroups())))
        trusted_payload = access.probe_payload()
        def execute(command, **kwargs):
            probe = Path(command[command.index('--probe-dir') + 1])
            try:access.service_probe(probe, identity, 'a' * 40, '/installed/source')
            except ValueError:return Mock(returncode=1)
            self.fail('source failure was not preserved')
        with patch.object(access, 'service_identity', return_value=identity), \
             patch.object(access.os, 'chown'), \
             patch.object(access, 'probe_payload', return_value=trusted_payload), \
             patch.object(access, 'installed_source_identity', side_effect=ValueError(
                 'diagnostic_access_installed_source_unavailable:tree')), \
             self.assertRaisesRegex(ValueError, 'service_probe_failed:tree:source_unavailable'):
            access.check_access(output, self.root / 'economic', 'a' * 40, self.properties,
                write_metadata=diagnostic.write_metadata, run=execute)
        self.assertEqual(list(output.iterdir()), [])

    def test_failure_precedes_real_clock_and_any_paper_start_request(self):
        def ctl(*args, **kwargs):
            if 'MainPID' in args: return '0'
            if 'UnitFileState' in args: return 'disabled'
            if 'ExecStart' in args:
                return 'current_combined_observation_20261014 supervise ' + str(self.root) + ' ' + \
                    str(self.root / 'run') + ' ' + 'a' * 40
            keys = [args[i + 1] for i, value in enumerate(args[:-1]) if value == '-p']
            values = dict(self.properties, Restart='no', RuntimeMaxUSec='30min',
                          TimeoutStopUSec='1min 5s', KillMode='control-group')
            return '\n'.join(key + '=' + values[key] for key in keys)
        output = self.root / 'run'
        with patch.object(diagnostic, 'control', side_effect=ctl) as control, \
             patch.object(diagnostic.subprocess, 'check_output', return_value='a' * 40), \
             patch.object(diagnostic, 'economic', return_value={}), \
             patch.object(diagnostic, 'check_access', side_effect=ValueError('access_failed')) as check, \
             patch.object(diagnostic.time, 'monotonic') as clock, \
             patch.object(diagnostic, 'write_metadata') as writer:
            with self.assertRaisesRegex(ValueError, 'access_failed'):
                diagnostic.observe_once(self.root, output, 'a' * 40)
        check.assert_called_once(); clock.assert_not_called(); writer.assert_not_called()
        self.assertFalse(any('start' in call.args for call in control.call_args_list))

    def test_probe_timeout_stops_only_own_probe_before_cleanup(self):
        output = self.mock_output(); owned = output.stat()
        identity = dict(uid=owned.st_uid, gid=owned.st_gid, groups=[])
        stop = Mock(return_value=Mock(returncode=0, stdout='0'))
        with patch.object(access, 'service_identity', return_value=identity), \
             patch.object(access.os, 'chown'), self.assertRaisesRegex(ValueError, 'probe_timeout'):
            access.check_access(output, self.root / 'economic', 'a' * 40, self.properties,
                write_metadata=diagnostic.write_metadata,
                run=Mock(side_effect=subprocess.TimeoutExpired('probe', access.PROBE_SECONDS)),
                stop_probe=stop)
        self.assertEqual(stop.call_count, 2)
        self.assertTrue(stop.call_args_list[0].args[0][2].startswith('meme-machine-diagnostic-access-'))
        self.assertFalse(any(diagnostic.UNIT in call.args[0] for call in stop.call_args_list))
        self.assertEqual(list(output.iterdir()), [])

    def test_unverified_probe_stop_preserves_probe_files_and_blocks_dispatch(self):
        output = self.mock_output(); owned = output.stat()
        identity = dict(uid=owned.st_uid, gid=owned.st_gid, groups=[])
        with patch.object(access, 'service_identity', return_value=identity), \
             patch.object(access.os, 'chown'), self.assertRaisesRegex(ValueError, 'stop_unverified'):
            access.check_access(output, self.root / 'economic', 'a' * 40, self.properties,
                write_metadata=diagnostic.write_metadata,
                run=Mock(side_effect=subprocess.TimeoutExpired('probe', access.PROBE_SECONDS)),
                stop_probe=Mock(return_value=Mock(returncode=1, stdout='')))
        retained = list(output.iterdir()); self.assertEqual(len(retained), 1)
        self.assertTrue((retained[0] / 'clock.json').exists())

    def test_preparation_rejects_unrelated_parent_before_permission_changes(self):
        parent = self.root / 'unrelated'; parent.mkdir(mode=0o700)
        with patch.object(access, 'service_identity', return_value=self.identity), \
             patch.object(access.os, 'chown') as chown, patch.object(access.os, 'chmod') as chmod:
            with self.assertRaisesRegex(ValueError, 'exact_parent_required'):
                access.prepare_output(parent / 'fresh', self.properties)
        chown.assert_not_called(); chmod.assert_not_called()

    def test_private_output_and_economic_state_checks_still_fail_closed(self):
        output = self.mock_output(); output.chmod(0o755)
        with self.assertRaisesRegex(ValueError, 'private_directory'):
            access.validate_output(output, self.root / 'economic')
        output.chmod(0o700)
        with self.assertRaisesRegex(ValueError, 'outside_economic'):
            access.validate_output(output, output)
        link = self.root / 'link'; link.symlink_to(output)
        with self.assertRaisesRegex(ValueError, 'private_directory'):
            access.validate_output(link, self.root / 'economic')

    @unittest.skipUnless(os.geteuid() == 0 and shutil.which('systemd-run') and
                         Path('/run/systemd/system').exists(),
                         'actual service identity/filesystem namespace need root/systemd')
    def test_actual_service_identity_rejects_root_only_parent_and_accepts_explicit_repair(self):
        try:
            account = pwd.getpwnam('meme-machine')
        except KeyError:
            self.skipTest('configured service identity is unavailable')
        from meme_machine.operational.artifact_storage import Scratch
        current = subprocess.check_output(['systemctl', 'show', diagnostic.UNIT,
            *(argument for key in access.ACCESS_PROPERTIES for argument in ('-p', key))],
            text=True, timeout=5)
        self.properties = dict(line.split('=', 1) for line in current.splitlines())
        revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'],
            cwd=self.properties['WorkingDirectory'], text=True, timeout=5).strip()
        identity = access.service_identity(self.properties)
        old_umask = os.umask(0o022)
        try:
            # This tiny admitted fixture is outside ProtectHome and PrivateTmp.
            # It never touches the real diagnostic parent or application state.
            with Scratch(parent=Path('/var/lib')) as scratch:
                scratch.path.chmod(0o711)
                parent = scratch.path / 'diagnostics'; parent.mkdir(mode=0o700)
                prior = parent / 'prior-evidence'; prior.mkdir(mode=0o700)
                preserved = prior / 'retained'; preserved.write_text('unchanged')
                output = parent / 'fresh'; output.mkdir(mode=0o700)
                os.chown(output, account.pw_uid, identity['gid'])
                with self.assertRaisesRegex(ValueError, 'service_probe_failed'):
                    access.check_access(output, scratch.path / 'economic', revision,
                        self.properties, write_metadata=diagnostic.write_metadata)
                self.assertEqual(list(output.iterdir()), [])
                # Retain the prior failed directory; use a fresh run and repair
                # only its specified parent, with no recursive permission change.
                corrected = parent / 'corrected'
                access.prepare_output(corrected, self.properties, diagnostic_parent=parent)
                self.assertEqual(parent.stat().st_mode & 0o777, 0o710)
                self.assertEqual(parent.stat().st_gid, identity['gid'])
                verdict = access.check_access(corrected, scratch.path / 'economic', revision,
                    self.properties, write_metadata=diagnostic.write_metadata)
                self.assertTrue(verdict['verified']); self.assertEqual(list(corrected.iterdir()), [])
                self.assertEqual(verdict['controller_clock_mode'], 0o644)
                # An unreadable root-created clock must not pass actual UID checks.
                os.umask(0o077)
                with self.assertRaisesRegex(ValueError, 'service_probe_failed'):
                    access.check_access(corrected, scratch.path / 'economic', revision,
                        self.properties, write_metadata=diagnostic.write_metadata)
                os.umask(0o022)
                self.assertEqual(preserved.read_text(), 'unchanged')
                self.assertEqual(prior.stat().st_mode & 0o777, 0o700)
                second = parent / 'second-fresh'; parent.chmod(0o700)
                access.prepare_output(second, self.properties, diagnostic_parent=parent)
                self.assertEqual(parent.stat().st_mode & 0o777, 0o710)
                scratch.check(); scratch.success = True
        finally:
            os.umask(old_umask)

    @unittest.skipUnless(os.geteuid() == 0 and shutil.which('systemd-run') and shutil.which('git') and
                         Path('/run/systemd/system').exists(),
                         'actual service identity/filesystem namespace need root/systemd/git')
    def test_linked_worktree_git_access_and_exact_revision_are_required_before_start(self):
        try:
            pwd.getpwnam('meme-machine')
        except KeyError:
            self.skipTest('configured service identity is unavailable')
        from meme_machine.operational.artifact_storage import Scratch
        current = subprocess.check_output(['systemctl', 'show', diagnostic.UNIT,
            *(argument for key in access.ACCESS_PROPERTIES for argument in ('-p', key))],
            text=True, timeout=5)
        properties = dict(line.split('=', 1) for line in current.splitlines())
        identity = access.service_identity(properties)
        if 0 in identity['groups']:
            self.skipTest('root-group service cannot reproduce root:root 0660 denial')
        installed_package = Path(properties['WorkingDirectory']) / 'meme_machine'
        old_umask = os.umask(0o022)
        try:
            with Scratch(parent=Path('/var/lib')) as scratch:
                scratch.path.chmod(0o711)
                repo = scratch.path / 'repository'; installed = scratch.path / 'installed'
                def git(*args):
                    return subprocess.check_output(['git', *args], cwd=repo,
                        text=True, stderr=subprocess.DEVNULL, timeout=5).strip()
                subprocess.run(['git', 'init', '--quiet', str(repo)], check=True, timeout=5,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                (repo / 'fixture').write_text('retained fixture\n')
                (repo / 'meme_machine').symlink_to(installed_package, target_is_directory=True)
                git('add', 'fixture', 'meme_machine')
                git('-c', 'user.name=Offline fixture', '-c', 'user.email=offline@example.invalid',
                    'commit', '--no-gpg-sign', '--quiet', '-m', 'Disposable linked source')
                revision = git('rev-parse', 'HEAD'); tree = git('rev-parse', 'HEAD^{tree}')
                git('worktree', 'add', '--quiet', '--detach', str(installed), revision)
                admin = repo / '.git' / 'worktrees' / 'installed'
                # These exact disposable ownership assignments let Git perform
                # its ordinary safe-directory checks, without a global override.
                for path in (repo, repo / '.git', installed, installed / '.git', admin):
                    os.chown(path, identity['uid'], identity['gid'])
                head = admin / 'HEAD'; os.chown(head, 0, 0); head.chmod(0o660)
                tree_object = repo / '.git' / 'objects' / tree[:2] / tree[2:]
                index_before = (admin / 'index').read_bytes()
                properties = dict(properties, WorkingDirectory=str(installed))
                parent = scratch.path / 'diagnostics'; parent.mkdir(mode=0o700)
                prior = parent / 'prior'; prior.mkdir(mode=0o700)
                (prior / 'retained').write_text('unchanged')
                output = parent / 'fresh'
                access.prepare_output(output, properties, diagnostic_parent=parent)

                def blocked_before_start(requested):
                    def ctl(*args, **kwargs):
                        if 'MainPID' in args:return '0'
                        if 'UnitFileState' in args:return 'disabled'
                        if 'ExecStart' in args:
                            return f'current_combined_observation_20261014 supervise {scratch.path / "state"} {output} {requested}'
                        keys = [args[i + 1] for i, value in enumerate(args[:-1]) if value == '-p']
                        values = dict(properties, Restart='no', RuntimeMaxUSec='30min',
                                      TimeoutStopUSec='1min 5s', KillMode='control-group')
                        return '\n'.join(key + '=' + values[key] for key in keys)
                    with patch.object(diagnostic, 'control', side_effect=ctl) as control, \
                         patch.object(diagnostic.subprocess, 'check_output', return_value=requested), \
                         patch.object(diagnostic, 'economic', return_value={}), \
                         self.assertRaisesRegex(ValueError, 'service_probe_failed'):
                        diagnostic.observe_once(scratch.path / 'state', output, requested)
                    self.assertFalse(any('start' in call.args for call in control.call_args_list))
                    self.assertEqual(list(output.iterdir()), [])
                    self.assertFalse((output / 'clock.json').exists())

                blocked_before_start(revision)
                os.chown(head, 0, identity['gid']); head.chmod(0o640)
                verdict = access.check_access(output, scratch.path / 'state', revision,
                    properties, write_metadata=diagnostic.write_metadata)
                self.assertEqual(verdict['installed_source'], dict(revision=revision, tree=tree, clean=True))
                self.assertEqual(list(output.iterdir()), [])
                # Unreadable Git objects are a separate source-identity failure,
                # even when the worktree HEAD itself is readable.
                os.chown(tree_object, 0, 0); tree_object.chmod(0o600)
                blocked_before_start(revision)
                os.chown(tree_object, 0, identity['gid']); tree_object.chmod(0o440)
                verdict = access.check_access(output, scratch.path / 'state', revision,
                    properties, write_metadata=diagnostic.write_metadata)
                self.assertTrue(verdict['verified'])
                blocked_before_start('0' * 40)
                (installed / 'fixture').write_text('changed fixture\n')
                blocked_before_start(revision)
                self.assertEqual((admin / 'index').read_bytes(), index_before)
                self.assertEqual((prior / 'retained').read_text(), 'unchanged')
                self.assertEqual(list(output.iterdir()), [])
                scratch.check(); scratch.success = True
        finally:
            os.umask(old_umask)


if __name__ == '__main__':
    unittest.main()
