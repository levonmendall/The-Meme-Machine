"""Resource lifetime and same-cycle reuse; no providers or production state."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from meme_machine.operational import artifact_storage as storage, backup
from meme_machine.shared_capital import runtime
from meme_machine.shared_capital.model import CapitalError, digest


class SelectionReaders(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.portfolio = self.root / 'portfolio.sqlite'
        self.shared = self.root / 'shared-capital.sqlite'
        self.state = dict(epoch_id='offline-epoch', inception_sha256='a'*64,
                          policy={'sizing_basis': 'shared_realized_equity'})
        with closing(sqlite3.connect(self.portfolio)) as db, db:
            db.execute('CREATE TABLE portfolio_funding_authority(id,body)')
            marker = dict(state='SHARED', epoch_id=self.state['epoch_id'],
                          inception_sha256=self.state['inception_sha256'],
                          policy_sha256=digest(self.state['policy']))
            db.execute('INSERT INTO portfolio_funding_authority VALUES(1,?)', (json.dumps(marker),))
        with closing(sqlite3.connect(self.shared)) as db, db:
            db.execute('CREATE TABLE shared_capital_projection(id,body,hash)')
            db.execute('INSERT INTO shared_capital_projection VALUES(1,?,?)',
                       (json.dumps(self.state), digest(self.state)))
        self.opened = []
        self.original_connect = sqlite3.connect

    def track(self, *args, **kwargs):
        connection = self.original_connect(*args, **kwargs)
        # Strong references deliberately prevent GC from hiding leaked readers.
        self.opened.append(connection)
        return connection

    def assert_closed(self):
        for connection in self.opened:
            with self.assertRaises(sqlite3.ProgrammingError):
                connection.execute('SELECT 1')

    def test_repeated_success_closes_both_readers_without_gc_or_writes(self):
        before = {p: p.read_bytes() for p in (self.portfolio, self.shared)}
        with patch.object(runtime.sqlite3, 'connect', side_effect=self.track):
            for _ in range(20):
                self.assertEqual(runtime.selected(self.portfolio), self.shared)
                self.assert_closed()
        self.assertEqual(len(self.opened), 40)
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_identity_mismatch_closes_all_readers_and_preserves_error(self):
        with closing(sqlite3.connect(self.shared)) as db, db:
            changed = dict(self.state, epoch_id='different-epoch')
            db.execute('UPDATE shared_capital_projection SET body=?,hash=?',
                       (json.dumps(changed), digest(changed)))
        with patch.object(runtime.sqlite3, 'connect', side_effect=self.track):
            with self.assertRaisesRegex(CapitalError, 'selected_shared_authority_identity_mismatch'):
                runtime.selected(self.portfolio)
        self.assertEqual(len(self.opened), 2)
        self.assert_closed()

    def test_missing_authority_closes_selection_reader_and_fails_closed(self):
        self.shared.unlink()
        with patch.object(runtime.sqlite3, 'connect', side_effect=self.track):
            with self.assertRaisesRegex(CapitalError, 'selected_shared_authority_missing'):
                runtime.selected(self.portfolio)
        self.assertEqual(len(self.opened), 1)
        self.assert_closed()

    def test_second_open_failure_closes_first_and_preserves_exception(self):
        error = sqlite3.OperationalError('original selection failure')
        def connect(*args, **kwargs):
            if self.opened:
                raise error
            return self.track(*args, **kwargs)
        with patch.object(runtime.sqlite3, 'connect', side_effect=connect):
            with self.assertRaises(sqlite3.OperationalError) as caught:
                runtime.selected(self.portfolio)
        self.assertIs(caught.exception, error)
        self.assert_closed()

    def test_projection_query_failure_closes_both_readers(self):
        with closing(sqlite3.connect(self.shared)) as db, db:
            db.execute('DROP TABLE shared_capital_projection')
        with patch.object(runtime.sqlite3, 'connect', side_effect=self.track):
            with self.assertRaisesRegex(sqlite3.OperationalError, 'no such table'):
                runtime.selected(self.portfolio)
        self.assertEqual(len(self.opened), 2)
        self.assert_closed()

    def test_unselected_and_missing_portfolios_preserve_original_result(self):
        with closing(sqlite3.connect(self.portfolio)) as db, db:
            db.execute('DROP TABLE portfolio_funding_authority')
        with patch.object(runtime.sqlite3, 'connect', side_effect=self.track):
            self.assertIsNone(runtime.selected(self.portfolio))
            self.assertIsNone(runtime.selected(self.root / 'absent.sqlite'))
        self.assertEqual(len(self.opened), 1)
        self.assert_closed()


class RecoveryVerification(unittest.TestCase):
    def test_two_independent_constructor_replays_and_closures_preserve_shared_fence(self):
        from meme_machine.portfolio_accounting import inception_receipt
        from meme_machine.shared_capital import RiskPolicy
        from meme_machine.shared_capital.cutover import install
        from meme_machine.shared_capital.operational_candidate import initialize_new_epoch
        from tests.shared_capital_support import CONTRACTS, legacy_identities, utc
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'source'
            plan = initialize_new_epoch(root, inception_receipt('offline-restored-1000', utc(0),
                'fixture', starting_capital='1000.00', shared=True),
                portfolio_identities=legacy_identities(),
                lane_identities={family: legacy_identities(family) for family in ('pump','pons','meteora','ramses')},
                contracts=CONTRACTS, policy=RiskPolicy(sizing_basis='shared_realized_equity'))
            install(root, plan, approved_policy=plan['policy'], prerequisites={key: True for key in
                ('writers_stopped','coherent_backup_verified','native_mapping_verified','recovery_verified','provider_proof_verified')})
            target = Path(directory) / 'restored'
            backup.copy_state(root, target)
            original_verify = runtime.RuntimeCapital.verify_replay
            original_close = runtime.RuntimeCapital.close
            openings, closures = [], []
            def verify(authority):
                openings.append(authority)
                return original_verify(authority)
            def close(authority):
                closures.append(authority)
                return original_close(authority)
            with patch.object(runtime.RuntimeCapital, 'verify_replay', verify), \
                    patch.object(runtime.RuntimeCapital, 'close', close):
                result = backup.prove_replay(target)
            self.assertTrue(result['replay_idempotent'])
            self.assertTrue(result['legacy_funding_fenced'])
            self.assertEqual(len(openings), 2)
            self.assertEqual(openings, closures)
            self.assertIsNot(openings[0], openings[1])
            self.assertEqual(backup.state_identity(root), backup.state_identity(target))


class ScratchMeasurement(unittest.TestCase):
    def test_active_scope_measured_once_per_cycle_and_concurrent_scopes_remain_counted(self):
        with tempfile.TemporaryDirectory() as parent:
            other = Path(parent) / 'mm-engineering-other'
            other.mkdir(); (other / 'retained-failure').write_text('keep')
            with storage.Scratch(parent) as scope:
                original = storage.tree_bytes
                for _ in range(2):
                    with patch.object(storage, 'tree_bytes', wraps=original) as measure:
                        scope.check()
                    measured = [call.args[0] for call in measure.call_args_list]
                    self.assertEqual(measured.count(scope.path), 1)
                    self.assertEqual(measured.count(other), 1)
                self.assertEqual((other / 'retained-failure').read_text(), 'keep')
                scope.success = True

    def test_disappearing_file_during_active_walk_is_tolerated_without_double_walk(self):
        with tempfile.TemporaryDirectory() as parent:
            with storage.Scratch(parent) as scope:
                gone = scope.path / 'gone'
                gone.write_text('disposable')
                original = Path.lstat
                def lstat(path, *args, **kwargs):
                    if path == gone:
                        gone.unlink(missing_ok=True)
                        raise FileNotFoundError(str(gone))
                    return original(path, *args, **kwargs)
                with patch.object(Path, 'lstat', lstat):
                    scope.check()
                scope.success = True


class SuiteCoverage(unittest.TestCase):
    def test_only_duplicate_meteora_executions_disappear_with_identical_unique_ids(self):
        from operational.tests import FAST, OPERATIONAL
        module = 'tests.test_meteora_discovery_scheduler'
        self.assertEqual(FAST.count(module), 1)
        self.assertEqual(OPERATIONAL.count(module), 1)
        def ids(suite):
            for item in suite:
                if isinstance(item, unittest.TestSuite):
                    yield from ids(item)
                else:
                    yield item.id()
        duplicate = list(ids(unittest.defaultTestLoader.loadTestsFromName(module)))
        current = list(ids(unittest.defaultTestLoader.loadTestsFromNames(OPERATIONAL)))
        self.assertEqual(set(current), set(current + duplicate))
        self.assertEqual(len(current + duplicate) - len(current), len(duplicate))


if __name__ == '__main__':
    unittest.main()
