"""Actual fresh-ledger/replay boundaries; no market provider or financial stub."""
from contextlib import closing, redirect_stdout
from decimal import Decimal
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
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
                    self.assertIn('STANDALONE_RESOURCE_BINDING_UNAVAILABLE', result['blockers'])
                    self.assertIn('STANDALONE_STORAGE_BINDING_UNAVAILABLE', result['blockers'])
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


if __name__ == '__main__':
    unittest.main()
