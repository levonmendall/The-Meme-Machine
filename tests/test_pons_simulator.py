"""Actual fresh-ledger/replay boundaries; no market provider or financial stub."""
from contextlib import closing, redirect_stdout
from decimal import Decimal
from datetime import datetime
import io
import json
import os
from pathlib import Path
import sqlite3
import resource
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from meme_machine.operational import pons_simulator as simulator


class PonsSimulatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.state = self.base / 'separate-experiment/state'
        self.addCleanup(patch.stopall)
        patch.object(simulator, 'STATE', self.state).start()
        patch.object(simulator, 'LOCATION', 'workspace').start()
        patch.dict(os.environ, {}, clear=True).start()

    def rows(self):
        with closing(sqlite3.connect(self.state / 'shared-capital.sqlite')) as db:
            return (db.execute('SELECT * FROM shared_capital_events ORDER BY sequence').fetchall(),
                    db.execute('SELECT * FROM shared_capital_projection').fetchall())

    def test_actual_1000_inception_backup_replay_and_readonly_export_no_reseed(self):
        from meme_machine.portfolio_accounting import PortfolioAccounting
        result = simulator.prepare()
        self.assertEqual(result['state'], 'PREPARED_FUNDING_CLOSED')
        self.assertFalse(result['original_state_imported'])
        self.assertFalse(result['provider_history_imported'])
        financial = result['financial']
        self.assertEqual(financial['epoch_id'], simulator.EPOCH)
        self.assertEqual(financial['admission_mode'], 'OBSERVATION')
        self.assertTrue(financial['replay']['conservation'])
        self.assertTrue(all(value == 0 for value in financial['obligations'].values()))
        portfolio = financial['portfolio']
        self.assertEqual(Decimal(portfolio['shared_capital']['realized_equity']), 1000)
        self.assertEqual(Decimal(portfolio['balances']['available_cash']), 1000)
        self.assertEqual(Decimal(portfolio['shared_capital']['directional_sizing']['pons_current']['new_position_target']), 50)
        self.assertEqual(portfolio['shared_capital']['policy_sha256'], simulator.RISK_SHA256)
        with closing(simulator.readonly(self.state / 'simulator-inception-backup.sqlite')) as db:
            reader = object.__new__(PortfolioAccounting)
            reader.db = db
            seed = reader._replay()
            reader._reconcile(seed)
            self.assertEqual(seed['receipt']['epoch_id'], simulator.EPOCH)
            self.assertFalse(seed['positions'])
        before = self.rows()
        self.assertEqual(simulator.status()['state'], 'LEDGER_RECONCILED')
        self.assertEqual(simulator.export_state()['journal_hash'], financial['journal_hash'])
        with self.assertRaisesRegex(simulator.SimulatorFailure, 'SIMULATOR_EPOCH_EXISTS_NO_RESEED'):
            simulator.prepare()
        self.assertEqual(self.rows(), before)
        self.assertFalse((self.state / 'pons').exists())
        self.assertFalse((self.state / 'shared/provider-usage.continuous.sqlite').exists())

    def test_unprepared_and_live_commands_do_not_create_state_or_expose_configuration(self):
        for provider in ('', 'https://unapproved.invalid/v2/SECRET_DO_NOT_EXPORT',
                         'https://robinhood-mainnet.g.alchemy.com/v2/PRIVATE_TEST_KEY'):
            with self.subTest(provider=bool(provider)), patch.dict(os.environ,
                    {'MM_ROBINHOOD_READ_RPC_URL': provider}, clear=True):
                for command in ('shadow', 'run'):
                    output = io.StringIO()
                    with redirect_stdout(output):
                        code = simulator.main([command])
                    result = json.loads(output.getvalue())
                    self.assertEqual(code, 2)
                    self.assertEqual(result['state'], 'BLOCKED')
                    self.assertFalse(result['native_runtime_started'])
                    self.assertFalse(result['shadow_accepted'])
                    self.assertIn('SIMULATOR_NOT_PREPARED', result['blockers'])
                    if not provider or 'unapproved.invalid' in provider:
                        self.assertIn('CANONICAL_ALCHEMY_PROVIDER_NOT_CONFIGURED', result['blockers'])
                    self.assertNotIn('SECRET_DO_NOT_EXPORT', output.getvalue())
                    self.assertNotIn('PRIVATE_TEST_KEY', output.getvalue())
        self.assertFalse(self.state.parent.exists())

    def test_changed_risk_refuses_before_creating_an_experiment(self):
        path = self.base / 'unapproved-risk.json'
        path.write_text('{}')
        with patch.object(simulator, 'RISK_FILE', path):
            with self.assertRaisesRegex(simulator.SimulatorFailure, 'SIMULATOR_APPROVED_RISK_REQUIRED'):
                simulator.prepare()
        self.assertFalse(self.state.parent.exists())

    def test_ancestor_alias_cannot_create_files_in_another_epoch(self):
        protected = self.base / 'protected'
        protected.mkdir()
        (protected / 'retained').write_bytes(b'original evidence')
        alias = self.base / 'alias'
        alias.symlink_to(protected, target_is_directory=True)
        with patch.object(simulator, 'STATE', alias / 'new-experiment/state'):
            with self.assertRaisesRegex(simulator.SimulatorFailure, 'SIMULATOR_PATH_NOT_PHYSICAL'):
                simulator.prepare()
        self.assertEqual(list(protected.iterdir()), [protected / 'retained'])
        self.assertEqual((protected / 'retained').read_bytes(), b'original evidence')

    def test_state_alias_and_database_alias_are_refused_before_any_sqlite_read(self):
        protected = self.base / 'protected'
        protected.mkdir()
        self.state.parent.mkdir()
        self.state.symlink_to(protected, target_is_directory=True)
        with self.assertRaisesRegex(simulator.SimulatorFailure, 'SIMULATOR_EPOCH_EXISTS_NO_RESEED'):
            simulator.prepare()
        with patch.object(simulator.sqlite3, 'connect') as connect:
            with self.assertRaisesRegex(simulator.SimulatorFailure, 'SIMULATOR_PATH_NOT_PHYSICAL'):
                simulator.export_state()
            connect.assert_not_called()
        self.state.unlink()
        self.state.mkdir()
        (self.state / 'portfolio.sqlite').symlink_to(protected / 'original.sqlite')
        with patch.object(simulator.sqlite3, 'connect') as connect:
            with self.assertRaisesRegex(simulator.SimulatorFailure, 'SIMULATOR_PATH_NOT_PHYSICAL'):
                simulator.export_state()
            connect.assert_not_called()

    def test_corrupt_projection_is_not_repaired_or_reported_reconciled(self):
        simulator.prepare()
        with closing(sqlite3.connect(self.state / 'shared-capital.sqlite')) as db:
            db.execute("UPDATE shared_capital_projection SET hash=? WHERE id=1", ('f' * 64,))
            db.commit()
        before = self.rows()
        output = io.StringIO()
        with redirect_stdout(output):
            code = simulator.main(['status'])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output.getvalue())['state'], 'REFUSED')
        self.assertEqual(self.rows(), before)

    def test_fresh_profile_narrows_only_funding_and_integer_cpu_without_minting_usage(self):
        simulator.prepare()
        original = json.loads(simulator.PROFILE_SOURCE.read_text())
        expected = dict(original, funding_regimes=['pons_current'], maximum_cpu_cores='1')
        self.assertEqual(simulator.continuous_profile(), expected)
        self.assertEqual(simulator.continuous_profile(), expected)
        self.assertFalse((self.state / 'shared/provider-usage.continuous.sqlite').exists())
        path = self.state / 'continuous-profile.json'
        altered = dict(expected, maximum_queue_depth=65)
        path.write_bytes(simulator.canonical(altered))
        with self.assertRaisesRegex(simulator.SimulatorFailure, 'SIMULATOR_CONTINUOUS_PROFILE_CHANGED'):
            simulator.continuous_profile()
        self.assertEqual(json.loads(path.read_bytes()), altered)

    def test_experimental_storage_binds_existing_inception_and_refuses_changed_device(self):
        simulator.prepare()
        binding = simulator.verify_experimental_storage()
        self.assertEqual(binding['inception_sha256'], simulator.export_state()['inception_sha256'])
        self.assertFalse(binding['power_loss_recovery_verified'])
        before = self.rows()
        self.assertEqual(simulator.verify_experimental_storage(), binding)
        path = self.state / 'simulator-storage.json'
        altered = dict(binding, device=binding['device'] + 1)
        path.write_bytes(simulator.canonical(altered))
        with self.assertRaisesRegex(simulator.SimulatorFailure, 'SIMULATOR_STORAGE_BINDING_CHANGED'):
            simulator.verify_experimental_storage()
        self.assertEqual(self.rows(), before)

    def test_default_supervisor_storage_and_launch_hooks_keep_original_operations(self):
        from meme_machine.operational.supervisor import Supervisor
        service = Supervisor.__new__(Supervisor)
        service.root = self.state
        with patch('meme_machine.operational.storage_guard.verify_storage', return_value='actual') as verify:
            self.assertEqual(service.verify_storage(), 'actual')
            verify.assert_called_once_with(self.state)
        with patch('meme_machine.operational.supervisor.subprocess.Popen', return_value='child') as spawn:
            self.assertEqual(service.launch_lane('pons', ['python', 'native'], self.state, {'MODE': 'PAPER'}), 'child')
            spawn.assert_called_once_with(['python', 'native'], cwd=self.state,
                                          env={'MODE': 'PAPER'}, start_new_session=True)

    def test_actual_single_thread_launcher_applies_limits_and_affinity_before_exec_boundary(self):
        if resource.getrlimit(resource.RLIMIT_NOFILE)[1] < simulator.NOFILE:
            self.skipTest('host descriptor hard limit cannot admit the experimental contract')
        code = ('import json,os,resource;from meme_machine.operational import pons_simulator as s;'
                'a=s.install_process_limits(native=True);'
                'print(json.dumps(dict(affinity=sorted(a),address=resource.getrlimit(resource.RLIMIT_AS),'
                'files=resource.getrlimit(resource.RLIMIT_NOFILE),core=resource.getrlimit(resource.RLIMIT_CORE))))')
        result = subprocess.run([sys.executable, '-c', code], cwd=simulator.SOURCE,
            env=dict(os.environ, PYTHONPATH=str(simulator.SOURCE)), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=10)
        observed = json.loads(result.stdout)
        self.assertEqual(len(observed['affinity']), 1)
        self.assertEqual(observed['address'], [simulator.NATIVE_AS, simulator.NATIVE_AS])
        self.assertEqual(observed['files'], [simulator.NOFILE, simulator.NOFILE])
        self.assertEqual(observed['core'], [0, 0])

    def test_experimental_resource_proof_rejects_limit_affinity_and_topology_drift(self):
        from copy import deepcopy
        kind = simulator.supervisor_type()
        service = kind.__new__(kind)
        service.expected_affinity = {3}
        service.parent_start = 11
        service.native_start = (202, 22)
        service.processes = {'pons': SimpleNamespace(pid=202)}
        service.provider_budget = SimpleNamespace(envelope={'maximum_rss_bytes': 6 * 1024**3})
        service.storage_device = 77
        service.admission = 'OBSERVATION'
        service.stop_requested = False
        service.resource_failure = None
        base = dict(start=11, parent=1, pid=101, rss=1024, children={202}, affinities=[{3}], cgroup='0::/\n',
            limits={'Max address space': (simulator.PARENT_AS, simulator.NATIVE_AS),
                    'Max open files': (simulator.NOFILE, simulator.NOFILE), 'Max core file size': (0, 0)})
        child = dict(base, start=22, parent=101, pid=202, children=set(),
                     limits=dict(base['limits'], **{'Max address space': (simulator.NATIVE_AS, simulator.NATIVE_AS)}))
        for mutation in (None, 'limit', 'affinity', 'children', 'identity', 'device'):
            parent, native = deepcopy(base), deepcopy(child)
            if mutation == 'limit': native['limits']['Max address space'] = (simulator.NATIVE_AS + 1,) * 2
            if mutation == 'affinity': native['affinities'] = [{3, 4}]
            if mutation == 'children': native['children'] = {303}
            if mutation == 'identity': native['start'] = 23
            with self.subTest(mutation=mutation), patch.object(simulator.os, 'getpid', return_value=101), \
                    patch.object(simulator, 'process_facts', side_effect=[parent, native]), \
                    patch.object(simulator, 'own_cgroup_memory', return_value=(4096, 16 * 1024**3)), \
                    patch.object(simulator, 'storage_space', return_value={'device': 78 if mutation == 'device' else 77}):
                reason = service.resource_health(100., None)
            self.assertEqual(service.resource_measurement['limits_verified'], mutation is None)
            self.assertFalse(service.resource_measurement['original_cgroup_contract_verified'])
            self.assertEqual(reason is None, mutation is None)
            if mutation is not None:
                self.assertTrue(service.stop_requested)
                self.assertEqual(service.resource_failure, 'SIMULATOR_RESOURCE_EVIDENCE_UNAVAILABLE')

    def test_existing_provider_usage_is_reopened_without_counter_or_clock_reset(self):
        simulator.prepare()
        budget = simulator.ensure_provider_usage()
        with closing(budget.db()) as db:
            db.execute("UPDATE run SET value='17' WHERE key='http_attempts'")
            db.execute("UPDATE run SET value='900' WHERE key='alchemy_rpc_cu'")
            db.commit()
        before = budget.snapshot()
        reopened = simulator.ensure_provider_usage()
        self.assertEqual(reopened.snapshot(), before)
        self.assertEqual(reopened.snapshot()['http_attempts'], '17')

    def test_missing_previously_initialized_provider_ledger_never_mints_a_new_allowance(self):
        simulator.prepare()
        budget = simulator.ensure_provider_usage()
        path = budget.path
        retained = path.with_name('retained-provider.sqlite')
        path.rename(retained)
        with patch('meme_machine.operational.bounded_provider.Budget.create') as create:
            with self.assertRaisesRegex(simulator.SimulatorFailure, 'SIMULATOR_PROVIDER_HISTORY_REQUIRED'):
                simulator.ensure_provider_usage()
            create.assert_not_called()
        self.assertTrue(retained.is_file())
        self.assertFalse(path.exists())

    def test_interrupted_first_provider_creation_retains_intent_and_refuses_unchanged_retry(self):
        simulator.prepare()
        with patch('meme_machine.operational.bounded_provider.Budget.create', side_effect=OSError('disposable failure')):
            with self.assertRaises(OSError):
                simulator.ensure_provider_usage()
        self.assertTrue((self.state / 'simulator-provider-initialization.json').is_file())
        with patch('meme_machine.operational.bounded_provider.Budget.create') as create:
            with self.assertRaisesRegex(simulator.SimulatorFailure, 'SIMULATOR_PROVIDER_HISTORY_REQUIRED'):
                simulator.ensure_provider_usage()
            create.assert_not_called()

    def test_final_joined_observation_publication_preserves_prior_fault_without_dead_pid_probe(self):
        from meme_machine.operational.supervisor import Supervisor
        kind = simulator.supervisor_type()
        for failure in (None, 'SIMULATOR_RESOURCE_EVIDENCE_UNAVAILABLE'):
            service = kind.__new__(kind)
            service.admission = 'OBSERVATION'
            service.provider_budget = object()
            service.stop_requested = True
            service.processes = {'pons': SimpleNamespace(poll=lambda: 0)}
            service.resource_failure = failure
            with self.subTest(failure=failure), patch.object(kind, 'resource_health') as sample, \
                    patch.object(Supervisor, 'publish', return_value='published'):
                self.assertEqual(service.publish(), 'published')
                sample.assert_not_called()
            self.assertEqual(service.resource_failure, failure)
            self.assertEqual(service.resource_measurement['state'], 'STOPPED')
            self.assertFalse(service.resource_measurement['limits_verified'])

    def test_native_launcher_refuses_parent_source_mismatch_before_limits_or_exec(self):
        env = dict(MM_MODE='PAPER', MM_STATE_ROOT=str(self.state), MM_PAPER_EPOCH=simulator.EPOCH,
                   MM_RUNTIME_LANE='pons', MM_PONS_SIMULATOR_SOURCE_COMMIT='a' * 40,
                   MM_PONS_SIMULATOR_SOURCE_TREE='b' * 40)
        with patch.dict(os.environ, env, clear=True), \
                patch.object(simulator, 'source_binding', return_value={'commit': 'c' * 40, 'tree': 'b' * 40}), \
                patch.object(simulator, 'install_process_limits') as limits, \
                patch.object(simulator.os, 'execv') as execute:
            with self.assertRaisesRegex(simulator.SimulatorFailure, 'SIMULATOR_NATIVE_SOURCE_CHANGED'):
                simulator.native_child()
            limits.assert_not_called()
            execute.assert_not_called()

    def test_missing_actual_provider_clock_blocks_before_any_runtime_configuration_write(self):
        from meme_machine.runtime.provider_clock import ProviderClockError
        simulator.prepare()
        env = {'MM_ROBINHOOD_READ_RPC_URL':
               'https://robinhood-mainnet.g.alchemy.com/v2/PRIVATE_OFFLINE_TEST_KEY'}
        with patch.dict(os.environ, env, clear=True), \
                patch('meme_machine.runtime.provider_clock.current_identity',
                      side_effect=ProviderClockError('disposable unavailable clock')), \
                patch('meme_machine.operational.bounded_provider.Budget.create') as create, \
                patch.object(simulator, 'verify_experimental_storage') as storage, \
                patch.object(simulator, 'continuous_profile') as profile, \
                patch.object(simulator, 'source_binding') as source:
            result = simulator.runtime('shadow')
            self.assertEqual(result['state'], 'BLOCKED')
            self.assertIn('PROVIDER_CLOCK_IDENTITY_UNAVAILABLE', result['blockers'])
            self.assertFalse(result['native_runtime_started'])
            with self.assertRaisesRegex(simulator.SimulatorFailure, 'PROVIDER_CLOCK_IDENTITY_UNAVAILABLE'):
                simulator.configure_runtime()
            create.assert_not_called()
            storage.assert_not_called()
            profile.assert_not_called()
            source.assert_not_called()
        for relative in ('continuous-profile.json', 'simulator-storage.json', 'simulator-provider.json',
                         'simulator-provider-initialization.json', 'shared/provider-usage.continuous.sqlite'):
            self.assertFalse((self.state / relative).exists(), relative)

    def test_location_is_fixed_and_unknown_location_or_ec2_prepare_cannot_write(self):
        self.assertEqual(simulator.LOCATIONS['ec2'], Path(
            '/opt/mm-ec2-admin-runner/_work/meme-machine-admin/pons-simulator-experiment-20261024'))
        for location, reason in (('/arbitrary/state', 'SIMULATOR_LOCATION_INVALID'),
                                 ('ec2', 'SIMULATOR_EC2_RESEED_FORBIDDEN')):
            with self.subTest(location=location), patch.object(simulator, 'LOCATION', location), \
                    patch.object(simulator, 'approved_risk') as risk:
                with self.assertRaisesRegex(simulator.SimulatorFailure, reason):
                    simulator.prepare()
                risk.assert_not_called()
        with patch.object(simulator, 'LOCATION', '/arbitrary/state'), \
                patch.object(simulator, 'require_provider_clock') as clock:
            with self.assertRaisesRegex(simulator.SimulatorFailure, 'SIMULATOR_LOCATION_INVALID'):
                simulator.configure_runtime()
            clock.assert_not_called()
        self.assertFalse(self.state.parent.exists())

    def test_retired_workspace_refuses_every_entry_to_writes_and_exports_old_authority_time(self):
        financial = simulator.prepare()['financial']
        simulator.verify_experimental_storage()
        kind = simulator.supervisor_type()
        service = kind.__new__(kind)
        service.root = self.state
        with closing(simulator.readonly(self.state / 'shared-capital.sqlite')) as db:
            ledger_at = json.loads(db.execute('SELECT body FROM shared_capital_projection').fetchone()[0])['at']
        marker = dict(schema='pons-simulator-authority-retired-v1', epoch_id=simulator.EPOCH,
            inception_sha256=financial['inception_sha256'], destination_location='ec2',
            financial_journal_hash=financial['journal_hash'], retired_at='2026-10-24T00:00:00Z',
            checkpoint_sha256='a' * 64)
        simulator.write_once(self.state / simulator.RETIRED_MARKER, marker)
        before = self.rows()
        with patch.object(simulator, 'require_provider_clock'), \
                patch.object(simulator, 'source_binding') as source, \
                patch.object(simulator, 'verify_experimental_storage') as storage, \
                patch('meme_machine.operational.bounded_provider.Budget.create') as create:
            result = simulator.runtime('shadow')
            self.assertIn('SIMULATOR_AUTHORITY_RETIRED', result['blockers'])
            self.assertFalse(result['native_runtime_started'])
            for operation in (simulator.configure_runtime, simulator.ensure_provider_usage,
                              simulator.native_child, service.verify_storage,
                              lambda: simulator.write_once(self.state / 'new.json', {})):
                with self.assertRaisesRegex(simulator.SimulatorFailure, 'SIMULATOR_AUTHORITY_RETIRED'):
                    operation()
            source.assert_not_called(); create.assert_not_called(); storage.assert_not_called()
        with patch.object(simulator.time, 'time', return_value=ledger_at + 86400):
            retained = simulator.export_state()
            self.assertEqual(simulator.status()['state'], 'RETIRED_MIRROR')
        self.assertTrue(retained['authority_retired'])
        self.assertEqual(retained['authority'], 'RETIRED_MIRROR')
        self.assertEqual(int(datetime.fromisoformat(retained['portfolio']['as_of'].replace('Z', '+00:00')).timestamp()), ledger_at)
        self.assertEqual(retained['journal_hash'], financial['journal_hash'])
        self.assertEqual(self.rows(), before)
        self.assertFalse((self.state / 'new.json').exists())
        self.assertFalse((self.state / 'continuous-profile.json').exists())

    def test_ec2_replays_exact_imported_checkpoint_before_any_configuration_write(self):
        financial = simulator.prepare()['financial']
        before = self.rows()
        with patch.object(simulator, 'LOCATION', 'ec2'), \
                patch.object(simulator, 'require_provider_clock'), \
                patch.object(simulator, 'continuous_profile') as profile, \
                patch.object(simulator, 'verify_experimental_storage') as storage:
            with self.assertRaisesRegex(simulator.SimulatorFailure, 'SIMULATOR_RESTORED_CHECKPOINT_REQUIRED'):
                simulator.configure_runtime()
            profile.assert_not_called(); storage.assert_not_called()
            with patch.object(simulator, 'RESTORED_INCEPTION', financial['inception_sha256']), \
                    patch.object(simulator, 'RESTORED_JOURNAL', financial['journal_hash']), \
                    patch.object(simulator, 'RESTORED_PROJECTION', financial['projection_sha256']):
                self.assertEqual(simulator.export_state()['journal_hash'], financial['journal_hash'])
                with patch.object(simulator, 'RESTORED_PROJECTION', 'f' * 64):
                    with self.assertRaisesRegex(simulator.SimulatorFailure, 'SIMULATOR_RESTORED_CHECKPOINT_REQUIRED'):
                        simulator.export_state()
        self.assertEqual(self.rows(), before)
        self.assertFalse((self.state / 'continuous-profile.json').exists())

    def test_ec2_native_launcher_retains_existing_observer_admission_and_cache_paths(self):
        observer = self.base / 'observer'
        observer.mkdir()
        for name in ('provider.sqlite', 'evidence.sqlite'):
            (observer / name).write_bytes(b'retained provider evidence')
        kind = simulator.supervisor_type()
        service = kind.__new__(kind)
        service.frozen_source = dict(commit='a' * 40, tree='b' * 40)
        service.expected_affinity = {3}
        facts = dict(start=22, parent=os.getpid(), affinities=[{3}], limits={
            'Max address space': (simulator.NATIVE_AS, simulator.NATIVE_AS),
            'Max open files': (simulator.NOFILE, simulator.NOFILE), 'Max core file size': (0, 0)})
        child = SimpleNamespace(pid=202)
        with patch.object(simulator, 'LOCATION', 'ec2'), patch.object(simulator, 'OBSERVER', observer), \
                patch.object(kind, 'runtime_lanes', return_value=('pons',)), \
                patch.object(simulator, 'process_facts', return_value=facts), \
                patch.object(simulator.subprocess, 'Popen', return_value=child) as spawn:
            service.launch_lane('pons', [], self.base, {'MM_PROVIDER_DB': 'obsolete', 'MM_RPC_CACHE_DB': 'obsolete'})
        passed = spawn.call_args.kwargs['env']
        self.assertEqual(passed['MM_PONS_SIMULATOR_LOCATION'], 'ec2')
        self.assertEqual(passed['MM_PROVIDER_DB'], str(observer / 'provider.sqlite'))
        self.assertEqual(passed['MM_RPC_CACHE_DB'], str(observer / 'evidence.sqlite'))
        for name in ('provider.sqlite', 'evidence.sqlite'):
            self.assertEqual((observer / name).read_bytes(), b'retained provider evidence')


if __name__ == '__main__':
    unittest.main()
