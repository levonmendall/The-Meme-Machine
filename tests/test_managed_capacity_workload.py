import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from meme_machine.operational import managed_capacity_workload as workload
from meme_machine.operational.managed_capacity_evidence import canonical


def _accepted_decoder_fixture(directory):
    """A spawn worker with accepted work held until its coordinator stops."""
    root = Path(directory)
    (root / 'decoder-ready').write_text(str(os.getpid()))
    deadline = time.monotonic() + 10
    while not (root / 'decoder-release').exists():
        if time.monotonic() >= deadline:
            raise TimeoutError('offline_decoder_not_released')
        time.sleep(.005)
    (root / 'decoder-committed').write_text('accepted-native-work')
    return 'accepted-native-work'


class ManagedWorkload(unittest.TestCase):
    def test_actual_pump_child_supplies_fresh_reference_factory_with_no_financial_environment(self):
        from meme_machine.operational import managed_native_pump
        from meme_machine.operational import managed_pump_qualification
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'pump').mkdir(mode=0o700)
            args = SimpleNamespace(root=str(root), lane='pump', generation='a'*32,
                request_id='ec2-100-1', duration_seconds=120)
            constructed = Mock(return_value=Mock())
            async def native(config, stop, **kwargs):
                self.assertFalse(any(key.startswith('MM_') for key in os.environ))
                self.assertIsNone(kwargs.get('decision_target_lamports'))
                constructed.assert_not_called()
                self.assertIs(kwargs['decision_target_reader_factory'](), constructed.return_value)
                return dict(native_observation=True, financial_authority=False)
            with patch.dict(os.environ, dict(MM_SOLANA_READ_RPC_URL='https://solana-mainnet.g.alchemy.com/v2/offline-key',
                    MM_CAPACITY_SOURCE_COMMIT='b'*40, MM_CAPACITY_USAGE_DB=str(root/'usage.sqlite'),
                    MM_CAPACITY_PROVIDER_PROFILE=str(root/'profile.json')), clear=True), \
                    patch.object(workload.signal, 'signal'), \
                    patch.object(managed_native_pump, 'run_pump', side_effect=native), \
                    patch.object(managed_pump_qualification, 'FreshReferenceSizing', constructed):
                self.assertEqual(workload._child(args), 0)
            constructed.assert_called_once_with(args.generation)
            report = json.loads((root/'pump/result.json').read_bytes())
            self.assertEqual(report['state'], 'NATIVE_RESULT')
            self.assertFalse(report['financial_authority'])
            self.assertFalse(list(root.rglob('portfolio.sqlite')))

    def _run_exited_lane_sampling_race(self, *, global_denial=False):
        """Real failed child and process-group cleanup; no native/provider work."""
        from meme_machine.operational import bounded_provider
        real_popen = subprocess.Popen
        original_read = Path.read_text
        children = {}
        pump_program = '''
import json, pathlib, sys
root = pathlib.Path(sys.argv[1])
(root / 'result.json').write_text(json.dumps(dict(state='NATIVE_FAILED',
    error_type='EvidenceUnavailable', financial_authority=False)))
raise SystemExit(17)
'''
        pons_program = '''
import time
time.sleep(30)
'''
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            def spawn(command, **kwargs):
                lane = command[command.index('--lane') + 1]
                program = pump_program if lane == 'pump' else pons_program
                child = real_popen([sys.executable, '-I', '-B', '-c', program, str(root / lane)],
                    **kwargs)
                children[lane] = child
                if lane == 'pump':
                    # Do not poll/reap before the parent takes its real sample.
                    os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOWAIT)
                return child
            def denied(path, *args, **kwargs):
                target = Path('/proc/stat') if global_denial else (
                    Path('/proc') / str(children['pump'].pid) / 'io')
                if path == target:
                    raise PermissionError('secret-sampling-failure-never-output')
                return original_read(path, *args, **kwargs)
            budget = SimpleNamespace(reap_orphans=Mock(), usage=lambda: {})
            started = time.monotonic()
            try:
                with patch.object(workload, 'parameters', return_value=(root, 'a' * 40, {})), \
                     patch.object(bounded_provider.Budget, 'create', return_value=budget), \
                     patch.object(workload.subprocess, 'Popen', spawn), \
                     patch.object(Path, 'read_text', denied), \
                     patch.dict(os.environ, {}, clear=True):
                    report = workload.run(root, 120, 'a' * 32, 'ec2-100-1')
                rows = [json.loads(line) for part in (root / 'evidence').glob('evidence-*.jsonl')
                        for line in part.read_text().splitlines()]
                self.assertLess(time.monotonic() - started, 10)
                self.assertEqual(children['pump'].returncode, 17)
                self.assertIsNotNone(children['pons'].returncode)
                for child in children.values():
                    with self.assertRaises(ProcessLookupError):
                        os.kill(child.pid, 0)
                budget.reap_orphans.assert_called_once_with()
                return report, rows
            finally:
                # A regression in the coordinator must not leak fixture children.
                workload._signal_children(children, signal.SIGKILL)
                for child in children.values():
                    child.wait(timeout=5)

    @unittest.skipUnless(sys.platform == 'linux' and hasattr(os, 'WNOWAIT'),
                         'requires an unwaited Linux child')
    def test_exited_lane_sampling_race_retains_native_failure_and_bounded_cleanup(self):
        report, rows = self._run_exited_lane_sampling_race()
        self.assertEqual(report['cause'], 'native_lane_exited')
        self.assertIsNone(report['workload_failure'])
        self.assertEqual(report['lanes']['pump']['state'], 'NATIVE_FAILED')
        self.assertEqual(report['lanes']['pump']['error_type'], 'EvidenceUnavailable')
        self.assertFalse(report['workload_completed'])
        self.assertFalse(report['financial_authority'])
        sample = next(row['value']['host'] for row in rows if row['kind'] == 'sample')
        unavailable = [p for p in sample['processes'].values() if p.get('io_available') is False]
        self.assertEqual(len(unavailable), 1)
        self.assertIsNone(unavailable[0]['io'])
        stopped = next(row['value'] for row in rows if row['kind'] == 'stopped')
        self.assertEqual(stopped['cause'], 'native_lane_exited')
        self.assertNotIn('secret-sampling-failure', json.dumps(report))

    @unittest.skipUnless(sys.platform == 'linux' and hasattr(os, 'WNOWAIT'),
                         'requires an unwaited Linux child')
    def test_global_sample_permission_denial_remains_fatal_with_safe_origin(self):
        report, rows = self._run_exited_lane_sampling_race(global_denial=True)
        self.assertEqual(report['cause'], 'workload_PermissionError')
        failure = report['workload_failure']
        self.assertEqual(failure['error_type'], 'PermissionError')
        self.assertEqual(failure['origin']['module'],
                         'meme_machine.operational.managed_capacity_evidence')
        self.assertEqual(failure['origin']['function'], 'host_sample')
        self.assertGreater(failure['origin']['line'], 0)
        self.assertEqual(report['lanes']['pump']['state'], 'NATIVE_FAILED')
        self.assertFalse(report['workload_completed'])
        self.assertEqual([row['kind'] for row in rows], ['identity', 'stopped'])
        self.assertNotIn('secret-sampling-failure', json.dumps(report))

    def test_source_drain_and_provider_free_replay_have_separate_bounded_leases(self):
        from meme_machine.operational.managed_capacity_evidence import atomic_json
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'pump').mkdir(mode=0o700)
            child = SimpleNamespace(poll=lambda: None, wait=Mock())
            elapsed = [100.]
            def sleep(seconds): elapsed[0] += seconds
            with patch.object(workload, 'SHUTDOWN_SECONDS', 1):
                result = workload._wait_children({'pump': child}, root, 'a'*32,
                    clock=lambda: elapsed[0], sleeper=sleep)
            self.assertEqual(result, 'native_shutdown_deadline')
            child.wait.assert_not_called()
            self.assertLess(elapsed[0], 101.2)
            atomic_json(root/'pump/drained.json', dict(generation='a'*32,
                                                     native_provider_work_drained=True))
            self.assertIsNone(workload._wait_children({'pump': child}, root, 'a'*32,
                clock=lambda: elapsed[0], sleeper=sleep))
            self.assertAlmostEqual(child.wait.call_args.kwargs['timeout'], workload.REPLAY_SECONDS)

    def test_lane_environment_never_inherits_financial_or_other_provider_secrets(self):
        env = dict(MM_SOLANA_READ_RPC_URL='solana-private-fixture',
            MM_SOLANA_YELLOWSTONE_TOKEN='yellowstone-private-fixture',
            MM_ROBINHOOD_READ_RPC_URL='robinhood-private-fixture',
            MM_SHARED_CAPITAL_DB='/old/financial.sqlite', AWS_SECRET_ACCESS_KEY='aws-private-fixture')
        with patch.dict(os.environ, env, clear=True):
            pump = workload._environment('pump', Path('/fresh'), 'a' * 40)
            pons = workload._environment('pons', Path('/fresh'), 'a' * 40)
        self.assertNotIn('MM_ROBINHOOD_READ_RPC_URL', pump)
        self.assertNotIn('MM_SOLANA_READ_RPC_URL', pons)
        self.assertNotIn('MM_SOLANA_YELLOWSTONE_TOKEN', pons)
        for child in (pump, pons):
            self.assertNotIn('MM_SHARED_CAPITAL_DB', child)
            self.assertNotIn('AWS_SECRET_ACCESS_KEY', child)
            self.assertEqual(child['MM_CAPACITY_USAGE_DB'], '/fresh/provider-usage.sqlite')

    def test_dead_leader_still_has_its_owned_process_group_stopped(self):
        child = SimpleNamespace(pid=12345, poll=lambda: 2)
        with patch.object(workload.os, 'killpg') as kill:
            workload._signal_children({'pump': child}, signal.SIGTERM)
        kill.assert_called_once_with(12345, signal.SIGTERM)

    def test_graceful_stop_only_signals_living_lane_coordinator(self):
        child = SimpleNamespace(pid=12345, poll=lambda: None, send_signal=Mock())
        with patch.object(workload.os, 'killpg') as kill:
            workload._signal_children({'pump': child}, signal.SIGTERM)
        child.send_signal.assert_called_once_with(signal.SIGTERM)
        kill.assert_not_called()

    def test_forced_stop_still_reaches_living_lane_descendants(self):
        child = SimpleNamespace(pid=12345, poll=lambda: None, send_signal=Mock())
        with patch.object(workload.os, 'killpg') as kill:
            workload._signal_children({'pump': child}, signal.SIGKILL)
        kill.assert_called_once_with(12345, signal.SIGKILL)
        child.send_signal.assert_not_called()

    def test_graceful_lane_stop_preserves_actual_spawn_decoder_until_commit(self):
        # Production serve owns a spawn ProcessPool in the lane's process
        # group. Group-wide TERM kills that accepted worker before its owner
        # can drain it, even though the lane itself handles TERM gracefully.
        source = str(Path(__file__).resolve().parents[1])
        script = '''
import multiprocessing, signal, sys, threading
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from tests.test_managed_capacity_workload import _accepted_decoder_fixture
root = Path(sys.argv[2])
def release(*_):
    threading.Timer(.1, lambda: (root / 'decoder-release').write_text('stop')).start()
signal.signal(signal.SIGTERM, release)
with ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context('spawn')) as pool:
    future = pool.submit(_accepted_decoder_fixture, str(root))
    assert future.result(timeout=12) == 'accepted-native-work'
'''
        for original_group_stop in (True, False):
            with self.subTest(original_group_stop=original_group_stop), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                child = subprocess.Popen([sys.executable, '-I', '-B', '-c', script, source, tmp],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                    start_new_session=True)
                try:
                    deadline = time.monotonic() + 8
                    while not (root / 'decoder-ready').exists() and child.poll() is None:
                        self.assertLess(time.monotonic(), deadline, 'spawn decoder readiness deadline')
                        time.sleep(.005)
                    self.assertIsNone(child.poll(), 'lane exited before accepted decode')
                    decoder_pid = int((root / 'decoder-ready').read_text())
                    self.assertEqual(os.getpgid(decoder_pid), child.pid)
                    if original_group_stop:
                        os.killpg(child.pid, signal.SIGTERM)
                    else:
                        workload._signal_children({'pump': child}, signal.SIGTERM)
                    _, error = child.communicate(timeout=12)
                    if original_group_stop:
                        self.assertNotEqual(child.returncode, 0)
                        self.assertIn(b'BrokenProcessPool', error)
                        self.assertFalse((root / 'decoder-committed').exists())
                    else:
                        self.assertEqual(child.returncode, 0, error.decode(errors='replace'))
                        self.assertEqual((root / 'decoder-committed').read_text(), 'accepted-native-work')
                finally:
                    workload._signal_children({'pump': child}, signal.SIGKILL)
                    child.wait(timeout=5)
                    if child.stderr is not None:
                        child.stderr.close()

    def test_readiness_requires_native_durability_not_provider_calls(self):
        self.assertFalse(workload._active('pump', dict(provider_requests=100)))
        self.assertFalse(workload._active('pons', dict(provider_requests=100)))
        self.assertFalse(workload._active('pons', dict(durable_blocks=0)))
        self.assertTrue(workload._active('pump', dict(canonical=dict(sealed_finalized_blocks=1))))
        self.assertTrue(workload._active('pons', dict(durable_blocks=1)))

    def test_growing_native_coverage_is_not_duplicated_into_sample_payloads(self):
        row = dict(generation='a' * 32, observed_at=10,
            canonical=dict(sealed_finalized_blocks=10, finalized_blocks=11,
                latest_sealed_slot=30, latest_finalized_slot=31,
                coverage=[['scope'+str(n), 1, n, n] for n in range(10000)],
                unresolved_gaps=[], outbox=[['event', 10, 10]]),
            source_frames=dict(accepted_handlers=100, settled_handlers=99,
                queues=dict(control=dict(accepted=10, committed=10, pending=0))),
            history=dict(events=20, canonical_event_refs=30))
        small = workload.sample_projection('pump', row)
        self.assertEqual(small['coverage_scopes'], 10000)
        self.assertEqual(small['source_queues']['control']['committed'], 10)
        self.assertNotIn('coverage', small['canonical'])
        self.assertLess(len(canonical(small)) * (3600 // 5 + 1), 1024**2)
        self.assertEqual(small['history']['events'], 20)

    def test_qualification_projection_retains_actual_native_arrival_and_cursor_fields(self):
        native = dict(incoming_native_events=128, durably_observed_native_events=64,
            native_event_backlog=64, latest_source_sequence=140, durable_sequence=70,
            stages={'creation_observed': 64}, full_qualifications=0,
            decision_target_available=False, full_qualification_proven=False)
        small = workload.sample_projection('pump', dict(qualification_worker=native))
        for key, value in native.items():
            self.assertEqual(small['qualification_worker'][key], value)
        self.assertNotIn('source_native_events', small['qualification_worker'])

    def test_pons_child_binds_exact_state_and_preserves_blocked_result(self):
        from meme_machine.operational import managed_native_pons
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'pons').mkdir(mode=0o700)
            env = dict(MM_ROBINHOOD_READ_RPC_URL='private-provider-fixture',
                MM_CAPACITY_SOURCE_COMMIT='a' * 40,
                MM_CAPACITY_PROVIDER_PROFILE=str(root / 'profile.json'),
                MM_CAPACITY_USAGE_DB=str(root / 'provider-usage.sqlite'))
            seen = {}
            def blocked(*args, **kwargs):
                seen.update(os.environ)
                return dict(error=dict(reason='provider_http_429'), verdict='BLOCKED')
            args = SimpleNamespace(root=str(root), lane='pons', generation='a' * 32,
                                   duration_seconds=120, request_id='ec2-100-1')
            with patch.dict(os.environ, env, clear=True), \
                 patch.object(managed_native_pons, 'run_pons', blocked), \
                 patch.object(workload.signal, 'signal'):
                self.assertEqual(workload._child(args), 2)
            self.assertEqual(seen['MM_ROBINHOOD_STATE_DIR'], str(root / 'pons'))
            self.assertEqual(seen['MM_PROVIDER_DB'], str(root / 'pons/provider.sqlite'))
            self.assertEqual(seen['MM_RPC_CACHE_DB'], str(root / 'pons/evidence.sqlite'))
            self.assertEqual(seen['MM_PONS_OBSERVATION_ROUTE'], 'canonical_primary')
            self.assertEqual(seen['MM_RUNTIME_LANE'], 'pons')
            saved = json.loads((root / 'pons/result.json').read_text())
            self.assertEqual(saved['state'], 'NATIVE_FAILED')
            self.assertFalse(saved['financial_authority'])

    def test_protected_request_identity_requires_both_run_and_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            for request_id in ('ec2-100', 'ec2-100-0', 'ec2-0-1', 'arbitrary-shell'):
                with self.assertRaisesRegex(ValueError, 'capacity_request_id'):
                    workload.parameters(Path(tmp), 120, 'a' * 32, request_id)

    def test_pump_child_retains_native_first_error_without_credential_message(self):
        from meme_machine.operational import managed_native_pump
        from meme_machine.solana_evidence_plane import EvidenceUnavailable
        import sqlite3
        failures = [EvidenceUnavailable('writer_failed'),
                    RuntimeError('secret-provider-credential-do-not-export'),
                    sqlite3.OperationalError('secret-provider-credential-do-not-export')]
        failures[-1].sqlite_errorcode = sqlite3.SQLITE_BUSY
        failures[-1].sqlite_errorname = 'SQLITE_BUSY'
        for error in failures:
            with self.subTest(kind=type(error).__name__), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); (root / 'pump').mkdir(mode=0o700)
                env = dict(MM_SOLANA_READ_RPC_URL='https://solana-mainnet.g.alchemy.com/v2/offline-fixture',
                    MM_CAPACITY_SOURCE_COMMIT='a' * 40,
                    MM_CAPACITY_PROVIDER_PROFILE=str(root / 'profile.json'),
                    MM_CAPACITY_USAGE_DB=str(root / 'provider-usage.sqlite'))
                async def failed(*args, **kwargs):
                    raise error
                args = SimpleNamespace(root=str(root), lane='pump', generation='a' * 32,
                                       duration_seconds=120, request_id='ec2-100-1')
                with patch.dict(os.environ, env, clear=True), \
                     patch.object(managed_native_pump, 'run_pump', failed), \
                     patch.object(workload.signal, 'signal'):
                    self.assertEqual(workload._child(args), 2)
                raw = (root / 'pump/result.json').read_text()
                self.assertNotIn('secret-provider-credential', raw)
                native = json.loads(raw)['native_failure']
                if isinstance(error, EvidenceUnavailable):
                    self.assertIn('writer_failed', native)
                if isinstance(error, sqlite3.Error):
                    self.assertIn('SQLITE_BUSY', native)


class ImmutableCapacityProposalTests(unittest.TestCase):
    """Pure producer tests; candidate code and providers are never executed."""
    def setUp(self):
        import importlib.util
        path=Path(__file__).resolve().parents[1]/'engineering/ec2_capacity/authorization_producer.py'
        spec=importlib.util.spec_from_file_location('offline_capacity_authorizer',path)
        self.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.module)
        self.template=json.loads((path.parent/'release-template.json').read_bytes())
        self.commit='a'*40;self.tree='b'*40;self.previous='c'*40
        self.files={'meme_machine/operational/managed_capacity_workload.py':'d'*64}
        self.release=dict(self.template,application_commit=self.commit,application_tree=self.tree,
                          application_files=self.files)
        self.release_sha=self.module.sha(self.module.canonical(self.release))
        self.rows=[dict(id=101+index,run_attempt=1,workflow_id=wid,path=path,
            head_sha=self.commit,status='completed',conclusion='success',event='pull_request',
            repository={'full_name':self.module.REPO},head_repository={'full_name':self.module.REPO})
            for index,(wid,path) in enumerate(self.module.CI.items())]

    def build(self,**changes):
        args=dict(commit=self.commit,tree=self.tree,files=self.files,previous_commit=self.previous,
            previous_release='e'*64,expected_release=self.release_sha,review='f'*64,
            ci_rows=self.rows,producer_run=501,producer_attempt=1)
        args.update(changes)
        return self.module.release_manifest(self.template,**args)

    def test_manifest_reconstructs_exact_frozen_release_and_binds_previous_and_review(self):
        value=self.build()
        self.assertEqual(value['release'],self.release)
        self.assertEqual(value['release_sha256'],self.release_sha)
        self.assertEqual(value['previous_release_sha256'],'e'*64)
        self.assertEqual(value['review_evidence_sha256'],'f'*64)
        self.assertEqual(value['ci_runs'],[{'run_id':101,'attempt':1},{'run_id':102,'attempt':1}])
        self.assertNotIn('approval',value) # The producer cannot approve itself.
        title=self.module.producer_title(self.commit,'e'*64,self.release_sha,'f'*64)
        self.assertEqual(title,'EC2AUTH '+self.commit+' '+'e'*64+' '+self.release_sha+' '+'f'*64)
        self.assertLess(len(title),256)

    def test_wrong_source_or_release_digests_fail_before_publication(self):
        for changes in ({'expected_release':'0'*64},{'tree':'0'*40},
                        {'files':dict(self.files,unexpected='0'*64)},
                        {'commit':'main'},{'review':'not-an-approval'}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.build(**changes)

    def test_ci_requires_exact_completed_source_repository_workflow_and_distinct_runs(self):
        import copy
        for changes in ({'head_sha':'0'*40},{'conclusion':'failure'}, {'status':'in_progress'},
                        {'event':'workflow_dispatch'},{'path':'.github/workflows/fake.yml'},
                        {'head_repository':{'full_name':'attacker/fork'}}):
            rows=copy.deepcopy(self.rows);rows[0].update(changes)
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.build(ci_rows=rows)
        with self.assertRaises(ValueError):self.build(ci_rows=[self.rows[0],self.rows[0]])

    def test_real_committed_blob_census_never_executes_candidate_and_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'meme_machine/operational';source.mkdir(parents=True)
            candidate=source/'managed_capacity_workload.py'
            candidate.write_text("raise RuntimeError('candidate must never execute')\n")
            def git(*args):
                return subprocess.check_output(['/usr/bin/git','-c','user.name=Offline',
                    '-c','user.email=offline@example.invalid','-C',str(root),*args],
                    stderr=subprocess.DEVNULL).decode().strip()
            git('init','-q');git('add','.');git('commit','-qm','offline source')
            commit=git('rev-parse','HEAD');tree,files=self.module.source_census(root,commit)
            self.assertEqual(tree,git('rev-parse','HEAD^{tree}'))
            self.assertEqual(files['meme_machine/operational/managed_capacity_workload.py'],
                             self.module.sha(candidate.read_bytes()))
            with self.assertRaises(ValueError):self.module.source_census(root,'0'*40)
            (root/'untrusted-link').symlink_to('/etc/passwd');git('add','.');git('commit','-qm','symlink')
            with self.assertRaisesRegex(ValueError,'regular_files_only'):
                self.module.source_census(root,git('rev-parse','HEAD'))
