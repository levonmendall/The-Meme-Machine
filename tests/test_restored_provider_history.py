"""Exact restored observation compatibility; disposable real usage/accounting.

Production identity pins are replaced only with the corresponding authenticated
facts of these disposable fixtures. Verification, Budget and journal paths run
unchanged. No provider transport or protected AWS state is accessed.
"""
from contextlib import closing
from copy import deepcopy
import os
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from meme_machine.operational import restored_provider_history as restored
from meme_machine.operational.admission import available
from meme_machine.operational.bounded_provider import Budget
from meme_machine.operational.supervisor import Supervisor
from meme_machine.shared_capital.runtime import process_identity
from tests import test_continuous_paper, test_pump_pons_capital_preparation


class RestoredProviderHistoryTests(unittest.TestCase):
    fixture = test_pump_pons_capital_preparation.RuntimeIntegrationTests.fixture
    service = test_continuous_paper.AdmissionTests.service

    def setUp(self):
        self.root, self.authority, self.now, prior = self.service(all_regimes=True)
        self.path = self.root / 'shared/provider-usage.continuous.sqlite'
        prior.provider_budget.path.rename(self.path)
        self.budget = Budget(self.path)
        self.profile = self.budget.envelope
        # Real API accounting creates durable nonzero rows in every table;
        # these are priced offline reservations, with no network acquisition.
        token = self.budget.stream_open('yellowstone')
        self.budget.native('yellowstone', 1234, token=token)
        self.budget.stream_close(token, unread_possible=True)
        response = self.budget.reserve_http(
            'https://solana-mainnet.g.alchemy.com/v2/offline', [dict(method='getSlot')])
        response.close()
        self.budget.publish_readiness(False, 'retained-offline-run', reason='observation_funding_closed')
        self.old_path = restored.RESTORED_IDENTITY['old_path']
        self.authority.command('fixture-retained-observation', 'runtime_admission',
            dict(mode='OBSERVATION', run_id='retained-offline-run', pid=os.getpid(),
                process_start=process_identity(os.getpid()), provider_db=self.old_path,
                continuous_provider_db=self.old_path), self.now)
        state = self.authority.ledger()
        self.enterContext(patch.dict(os.environ, dict(MM_MODE='PAPER',
            MM_STATE_ROOT=str(self.root), MM_PROVIDER_USAGE_DB=str(self.path),
            MM_PROVIDER_OPERATION_MODE='CONTINUOUS', MM_PAPER_EPOCH=state['epoch_id'])))
        sequence, journal, projection = self.authority.db.execute(
            'SELECT sequence,hash,state_hash FROM shared_capital_events ORDER BY sequence DESC LIMIT 1').fetchone()
        with closing(sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True)) as db:
            cohort = restored.provider_facts(db)
        self.assertTrue(all(cohort['rows'][name] for name in ('run', 'streams', 'http_receipts', 'usage_hours')))
        self.identity = dict(root=str(self.root), old_path=self.old_path,
            epoch=state['epoch_id'], inception=state['inception_sha256'],
            projection=projection, journal=journal, sequence=sequence,
            admission=restored._digest(state['runtime_admission']), provider=cohort['sha256'])
        self.enterContext(patch.object(restored, 'RESTORED_IDENTITY', self.identity))

    def observed(self, mode='OBSERVATION'):
        service = Supervisor(self.root, offline=True, admission=mode)
        service.shared_capital = self.authority
        service.epoch = self.authority.ledger()['epoch_id']
        return service

    def facts(self):
        with closing(sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True)) as db:
            usage = {name: db.execute('SELECT * FROM ' + name + ' ORDER BY 1').fetchall()
                for name in ('run', 'streams', 'http_receipts', 'usage_hours')}
            usage['schema'] = db.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name').fetchall()
        financial = self.authority.db.execute('SELECT * FROM shared_capital_events ORDER BY sequence').fetchall()
        projection = self.authority.db.execute('SELECT * FROM shared_capital_projection').fetchall()
        return usage, financial, projection

    def refuse(self, service=None, state=None):
        service = service or self.observed()
        with patch.object(Budget, '__init__', side_effect=AssertionError('constructor_before_proof')), \
                patch.object(Budget, 'create', side_effect=AssertionError('replacement_usage_forbidden')):
            with self.assertRaisesRegex(ValueError, 'restore_not_reseed'):
                if state is None:
                    service.configure_admission()
                else:
                    restored.require_restored_history(service, state, self.path, self.profile)

    def test_exact_observation_proof_is_readonly_then_original_admission_records_aws_path_once(self):
        service = self.observed()
        state = self.authority.ledger()
        before = self.facts()
        restored.require_restored_history(service, state, self.path, self.profile)
        self.assertEqual(self.facts(), before)
        usage = self.budget.snapshot()
        with patch.object(Budget, 'create', side_effect=AssertionError('replacement_usage_forbidden')):
            service.configure_admission()
        after = self.authority.ledger()
        self.assertEqual(after['runtime_admission']['provider_db'], str(self.path))
        self.assertEqual(after['runtime_admission']['continuous_provider_db'], str(self.path))
        self.assertEqual(after['runtime_admission']['mode'], 'OBSERVATION')
        self.assertEqual(len(self.facts()[1]), len(before[1]) + 1)
        for key in ('cash', 'initial_capital', 'inception', 'positions', 'reservations',
                'commitments', 'obligations', 'pending_deliveries', 'realized', 'policy'):
            self.assertEqual(after[key], state[key])
        for key in ('started', 'started_wall', 'boot', 'rpc_cu', 'rpc_elements', 'http_attempts',
                'http_bytes', 'http_uncertain_bytes', 'native_bytes', 'native_uncertain_bytes', 'native_opens'):
            self.assertEqual(service.provider_budget.snapshot()[key], usage[key])
        for regime in self.profile['funding_regimes']:
            self.assertEqual(available(after, self.now, live=True, regime=regime), 'observation_only_funding_closed')
        # Normal same-path observation restart uses the original guard, without
        # reapplying or replenishing the consumed fixed-cohort opportunity.
        resumed = self.observed()
        with patch.object(restored, 'require_restored_history', side_effect=AssertionError('translation_reused')), \
                patch.object(Budget, 'create', side_effect=AssertionError('replacement_usage_forbidden')):
            resumed.configure_admission()
        self.assertEqual(resumed.provider_budget.snapshot()['rpc_cu'], usage['rpc_cu'])
        self.authority.verify_replay()

    def test_normal_autonomy_and_nonpaper_modes_cannot_use_restored_exception(self):
        before = self.facts()
        for mode in ('NORMAL', 'AUTONOMY'):
            with self.subTest(mode=mode):
                self.refuse(self.observed(mode))
                self.assertEqual(self.facts(), before)
        with patch.dict(os.environ, MM_MODE='LIVE'):
            self.refuse()
        self.assertEqual(self.facts(), before)

    def test_existing_paper_default_and_derived_epoch_need_no_new_parent_environment_labels(self):
        before = self.facts()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('MM_MODE', None)
            os.environ.pop('MM_PAPER_EPOCH', None)
            restored.require_restored_history(self.observed(), self.authority.ledger(), self.path, self.profile)
        self.assertEqual(self.facts(), before)
        with patch.dict(os.environ, MM_PAPER_EPOCH='explicit-conflicting-epoch'):
            self.refuse()
        self.assertEqual(self.facts(), before)

    def test_unknown_retained_paths_and_financial_identity_are_rejected_without_writes(self):
        before = self.facts()
        original = self.authority.ledger()
        changes = [('epoch_id', 'another-epoch'), ('inception_sha256', 'f' * 64),
            ('cash', '999.00'), ('runtime_admission.provider_db', '/unknown/provider.sqlite'),
            ('runtime_admission.continuous_provider_db', '/unknown/provider.sqlite'),
            ('runtime_admission.run_id', 'another-run')]
        for key, value in changes:
            with self.subTest(key=key):
                state = deepcopy(original)
                target = state
                for part in key.split('.')[:-1]:
                    target = target[part]
                target[key.split('.')[-1]] = value
                self.refuse(state=state)
                self.assertEqual(self.facts(), before)

    def test_missing_and_symlinked_current_ledger_never_create_or_alias_history(self):
        preserved = self.path.with_name('preserved-original.sqlite')
        self.path.rename(preserved)
        try:
            self.refuse()
            self.assertFalse(self.path.exists())
            self.path.symlink_to(preserved)
            try:
                self.refuse()
                self.assertTrue(self.path.is_symlink())
            finally:
                self.path.unlink()
        finally:
            preserved.rename(self.path)

    def test_all_original_tables_configuration_and_schema_participate_in_cohort(self):
        mutations = (
            ("UPDATE run SET value=CAST(value AS INTEGER)+1 WHERE key='rpc_cu'", (),
                "UPDATE run SET value=? WHERE key='rpc_cu'", (self.budget.snapshot()['rpc_cu'],)),
            ('UPDATE streams SET remaining=remaining+1', (), 'UPDATE streams SET remaining=remaining-1', ()),
            ('UPDATE http_receipts SET remaining=remaining+1', (), 'UPDATE http_receipts SET remaining=remaining-1', ()),
            ('UPDATE usage_hours SET rpc_cu=rpc_cu+1', (), 'UPDATE usage_hours SET rpc_cu=rpc_cu-1', ()),
            ("UPDATE run SET value='[{}]' WHERE key='continuous_configuration_changes'", (),
                "UPDATE run SET value=? WHERE key='continuous_configuration_changes'", ('[]',)),
            ("UPDATE run SET value='{}' WHERE key='continuous_envelope'", (),
                "UPDATE run SET value=? WHERE key='continuous_envelope'", (self.budget.snapshot()['continuous_envelope'],)),
            ('CREATE INDEX unexpected_usage_schema ON streams(closed)', (), 'DROP INDEX unexpected_usage_schema', ()),
        )
        original = self.facts()
        for sql, parameters, restore_sql, restore_parameters in mutations:
            with self.subTest(sql=sql):
                with closing(sqlite3.connect(self.path, isolation_level=None)) as db:
                    db.execute(sql, parameters)
                changed = self.facts()
                self.assertNotEqual(changed, original)
                self.refuse()
                self.assertEqual(self.facts(), changed)
                with closing(sqlite3.connect(self.path, isolation_level=None)) as db:
                    db.execute(restore_sql, restore_parameters)
                self.assertEqual(self.facts(), original)

    def test_reset_usage_ledger_with_valid_configuration_cannot_replace_original_cohort(self):
        preserved = self.path.with_name('preserved-original.sqlite')
        self.path.rename(preserved)
        try:
            replacement = Budget.create(self.path, continuous=self.profile)
            replacement.publish_readiness(False, 'retained-offline-run')
            before = self.facts()
            self.refuse()
            self.assertEqual(self.facts(), before)
        finally:
            self.path.unlink()
            preserved.rename(self.path)

    def test_file_disappearing_after_proof_fails_mode_rw_without_create_fallthrough(self):
        service = self.observed()
        original = restored.require_restored_history
        preserved = self.path.with_name('preserved-original.sqlite')
        financial = self.facts()[1:]
        def remove_after_proof(*args):
            original(*args)
            self.path.rename(preserved)
        try:
            with patch.object(restored, 'require_restored_history', remove_after_proof), \
                    patch.object(Budget, 'create', side_effect=AssertionError('replacement_usage_forbidden')):
                with self.assertRaises(sqlite3.OperationalError):
                    service.configure_admission()
            self.assertFalse(self.path.exists())
            self.assertEqual(self.authority.db.execute('SELECT * FROM shared_capital_events ORDER BY sequence').fetchall(), financial[0])
            self.assertEqual(self.authority.db.execute('SELECT * FROM shared_capital_projection').fetchall(), financial[1])
        finally:
            if preserved.exists():
                preserved.rename(self.path)


if __name__ == '__main__':
    unittest.main()
