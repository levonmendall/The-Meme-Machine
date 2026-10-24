"""Actual fresh-ledger/replay boundaries; no market provider or financial stub."""
from contextlib import closing, redirect_stdout
from decimal import Decimal
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
        base = dict(start=11, parent=1, pid=101, rss=1024, children={202}, affinities=[{3}],
            limits={'Max address space': (simulator.PARENT_AS, simulator.NATIVE_AS),
                    'Max open files': (simulator.NOFILE, simulator.NOFILE), 'Max core file size': (0, 0)})
        child = dict(base, start=22, parent=101, pid=202, children=set(),
                     limits=dict(base['limits'], **{'Max address space': (simulator.NATIVE_AS, simulator.NATIVE_AS)}))
        for mutation in (None, 'limit', 'affinity', 'children', 'identity'):
            parent, native = deepcopy(base), deepcopy(child)
            if mutation == 'limit': native['limits']['Max address space'] = (simulator.NATIVE_AS + 1,) * 2
            if mutation == 'affinity': native['affinities'] = [{3, 4}]
            if mutation == 'children': native['children'] = {303}
            if mutation == 'identity': native['start'] = 23
            with self.subTest(mutation=mutation), patch.object(simulator.os, 'getpid', return_value=101), \
                    patch.object(simulator, 'process_facts', side_effect=[parent, native]), \
                    patch.object(simulator, 'own_cgroup_memory', return_value=(4096, 16 * 1024**3)), \
                    patch.object(simulator, 'storage_space'):
                reason = service.resource_health(100., None)
            self.assertEqual(service.resource_measurement['limits_verified'], mutation is None)
            self.assertFalse(service.resource_measurement['original_cgroup_contract_verified'])
            self.assertEqual(reason is None, mutation is None)

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


if __name__ == '__main__':
    unittest.main()
